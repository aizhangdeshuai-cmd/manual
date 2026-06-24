"""Mux narration audio onto a recorded video.

Public API:
    concat_segments_with_gaps(segment_paths, output_path, *, gap_seconds=2.0) -> Path
    mux_narration_with_video(video_path, audio_path, output_path) -> Path

The two-step pipeline matches real recorder data:
  1. `concat_segments_with_gaps`: N per-step narration mp3s → 1 mp3 with N-1
     silence gaps. Gap length is configurable; default 2.0s gives the viewer
     time to "look at the screenshot, then listen to the next step".
  2. `mux_narration_with_video`: prepend the (possibly gappy) narration to a
     Playwright-recorded webm/mp4 via `ffmpeg -i video -i audio`. We always
     set `-t <out_dur>` where `out_dur = min(vid_dur, audio_dur)`, so the
     video is NEVER looped — the user sees the recorded operation exactly
     once, even if narration is longer. See v0.3.6 changelog for the bug
     this contract fixed (the v0.3.2-v0.3.5 design looped the video and
     caused 视频内容在重复).

Why two functions instead of one combined call:
  - Stage 1 produces an inspectable intermediate (you can `ffprobe` it,
    play it standalone, swap gaps without re-running TTS).
  - Stage 1 is independent of the video — pure audio ops, easy to unit-test.
  - The recorder can SKIP stage 1 if there's only one narration segment.

Both stages are subprocess-based ffmpeg calls; we don't link libav.

v0.3.6 — never loop the video. Output duration = min(vid_dur, audio_dur);
  the previous `stream-loop -1` design caused the user to see the same
  operation N times in a row, reported as "视频内容在重复".
"""
from __future__ import annotations
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Union

logger = logging.getLogger(__name__)


PathLike = Union[str, Path]


def _to_path(p: PathLike) -> Path:
    return p if isinstance(p, Path) else Path(p)


# --- stage 1: concat narration with gaps -------------------------------------

def generate_silence_mp3(seconds: float, output_path: PathLike) -> Path:
    """Generate `seconds` of silence as a mono 24kHz mp3 (matches edge-tts)."""
    out = _to_path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if seconds <= 0:
        # Zero-second silence: still write a valid file so concat doesn't fail.
        seconds = 0.001
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate=24000",
        "-t", f"{seconds}",
        "-c:a", "libmp3lame", "-b:a", "48k",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


def concat_segments_with_gaps(
    segment_paths: Iterable[PathLike],
    output_path: PathLike,
    *,
    gap_seconds: float = 2.0,
) -> Path:
    """Concatenate N narration mp3s with `gap_seconds` of silence between them.

    Args:
        segment_paths: ordered list of input mp3 paths (one per task-card step).
            Empty list is a hard error — there must be at least 1 segment.
        output_path: destination .mp3 (will be created/overwritten).
        gap_seconds: silence to insert between segments. 0 = back-to-back.
            Negative values are treated as 0.

    Returns: the output Path.

    Raises:
        ValueError: segment_paths is empty, or any input missing.
        subprocess.CalledProcessError: ffmpeg concat fails.
    """
    segments: List[Path] = [_to_path(p) for p in segment_paths]
    if not segments:
        raise ValueError("concat_segments_with_gaps: segment_paths is empty")
    for p in segments:
        if not p.exists():
            raise FileNotFoundError(f"concat_segments_with_gaps: missing {p}")

    out = _to_path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Build a concat demuxer list file. For gaps, we interleave silence files
    # generated to a temp dir.
    tmpdir = Path(tempfile.mkdtemp(prefix="um-narration-"))
    try:
        # Pre-compute gap files (only if gap_seconds > 0 and we have >1 segments).
        gap_files: List[Path] = []
        if gap_seconds > 0 and len(segments) > 1:
            for i in range(len(segments) - 1):
                g = tmpdir / f"gap_{i:03d}.mp3"
                generate_silence_mp3(gap_seconds, g)
                gap_files.append(g)

        # Build the list: seg0, gap, seg1, gap, seg2, ...
        list_file = tmpdir / "concat.txt"
        with list_file.open("w") as f:
            for i, seg in enumerate(segments):
                f.write(f"file '{seg.as_posix()}'\n")
                if i < len(gap_files):
                    f.write(f"file '{gap_files[i].as_posix()}'\n")

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(out),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    finally:
        # Best-effort cleanup. We don't fail the call if rm fails (CI sandboxes).
        try:
            for p in tmpdir.iterdir():
                p.unlink(missing_ok=True)
            tmpdir.rmdir()
        except OSError:
            pass

    return out


# --- stage 2: mux audio onto video -------------------------------------------

def mux_narration_with_video(
    video_path: PathLike,
    audio_path: PathLike,
    output_path: PathLike,
) -> Path:
    """Combine a (possibly gappy) narration mp3 with a recorded video.

    The output is always a single mp4 with:
      - video: from `video_path` (re-encoded with libx264 to be safe across
        webm input, CRF 23, faststart enabled for HTTP streaming).
      - audio: from `audio_path` (encoded as AAC 128k).

    Behavior when lengths differ (v0.3.6 contract — NEVER loop the video):
      - If narration is LONGER than video: the trailing narration is TRIMMED.
        The user sees the full recorded operation exactly once, voiceover
        ends naturally when the action ends. No `stream-loop` is used.
      - If narration is SHORTER than video: the trailing video frames are
        KEPT (via the `out_dur` flag). The user sees the full recorded flow,
        voiceover ends mid-flow, video continues silently until the action
        ends — this preserves the "human recording" feel and matches the
        standalone recording's natural end-of-action tail.

    Why we don't loop the video:
      The previous v0.3.2-v0.3.5 design used `stream-loop -1` to make a
      short video fill a long narration. The user reported "视频内容在重复"
      (video content repeats) — a 3.5s login clip with 14.8s of narration
      showed the login form 4 times back-to-back. For human-facing manuals,
      seeing the same action N times is a worse experience than ending the
      clip when the action ends. The recorder is for manuals, not audiobooks.

    Args:
        video_path: input video (webm from Playwright, or mp4 from earlier step).
        audio_path: input narration (mp3 from concat_segments_with_gaps or
            a single edge-tts output).
        output_path: destination .mp4 (will be created/overwritten).

    Returns: the output Path.

    Raises:
        FileNotFoundError: any input missing.
        subprocess.CalledProcessError: ffmpeg fails.
    """
    v = _to_path(video_path)
    a = _to_path(audio_path)
    out = _to_path(output_path)
    if not v.exists():
        raise FileNotFoundError(f"mux_narration_with_video: missing video {v}")
    if not a.exists():
        raise FileNotFoundError(f"mux_narration_with_video: missing audio {a}")
    out.parent.mkdir(parents=True, exist_ok=True)

    # Probe both inputs so we can decide whether to loop the video.
    # v0.3.6: dropped the loop-vs-shortest decision entirely. We always
    # use a fixed `-t out_dur` where out_dur = min(vid_dur, audio_dur).
    from recorder_plugin.video import get_video_info  # local import, no cycle
    try:
        vid_dur = get_video_info(v)["duration_s"]
    except Exception as e:
        raise RuntimeError(f"mux_narration_with_video: cannot read video duration: {e}")

    # ffprobe for audio duration (no helper for mp3 in this module; do it inline)
    audio_probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(a),
    ], capture_output=True, text=True, check=True)
    try:
        audio_dur = float(audio_probe.stdout.strip())
    except ValueError as e:
        raise RuntimeError(
            f"mux_narration_with_video: cannot read audio duration: {audio_probe.stdout!r}"
        ) from e

    # v0.3.6 fix: NEVER loop the video. The user sees the recorded
    # operation once; narration is the part that gets stretched or
    # trimmed. The previous "loop video to fill long narration" approach
    # made the user watch the same login form 4 times in a row, which
    # looked like a bug ("重复登录") even though it was technically
    # correct muxing. The recorder is for human-facing manuals, not
    # audiobooks — a tight clip that ends when the action ends is more
    # useful than a stretched clip that fills the voiceover.
    #
    # Output duration = min(vid_dur, audio_dur):
    #   - video shorter than narration → trim the trailing silence/text
    #     (the user sees the full operation; voiceover may cut mid-sentence
    #     on the last segment, but that's OK — the next segment starts
    #     with silence, not with a truncated phrase)
    #   - video longer than narration → keep the trailing video frames
    #     (the user sees the full operation; voiceover ends naturally)
    out_dur = min(vid_dur, audio_dur)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    cmd += ["-i", str(v), "-i", str(a)]
    cmd += [
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", f"{out_dur:.3f}",
        "-movflags", "+faststart",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Surface the actual ffmpeg error in the exception message.
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )
    return out
