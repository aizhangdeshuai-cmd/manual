"""Video recording: Playwright records webm; ffmpeg slices into 10s chunks; ffprobe validates each.

v1.1 adds `concat_slices_to_mp4` — re-encode N webm slices into one MP4 (libx264) for
doc embed. Uses the ffmpeg concat demuxer (requires intermediate concat list file).
"""
from __future__ import annotations
import json
import logging
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_video_info(path: Path) -> dict[str, Any]:
    """Return {duration_s, width, height, codec} via ffprobe."""
    out = subprocess.check_output([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ])
    data = json.loads(out)
    fmt = data.get("format", {})
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration_s": float(fmt.get("duration", 0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "codec": str(video_stream.get("codec_name", "")),
    }


def validate_slice(path: Path) -> bool:
    """ffprobe-validate a slice. Returns True if parseable and duration > 0.

    v0.2.4 audit round 3 (H1): a corrupt / truncated slice used to return
    False silently, and the caller (script._handle_video_stop) then
    cached the bad slice as validated=True in state.set_video_session.
    Now we log the reason on failure so the operator can see WHICH
    slice failed ffprobe and WHY (size, ffprobe error, duration=0).
    """
    if not path.exists():
        logger.warning("validate_slice: file does not exist: %s", path)
        return False
    if path.stat().st_size < 100:
        logger.warning("validate_slice: %s is %d bytes (< 100, likely truncated)",
                       path, path.stat().st_size)
        return False
    try:
        info = get_video_info(path)
        if info["duration_s"] <= 0:
            logger.warning("validate_slice: %s has zero duration (ffprobe ok)", path)
            return False
        return True
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        logger.warning("validate_slice: ffprobe failed for %s: %s: %s",
                       path, type(e).__name__, e)
        return False


def slice_video(src: Path, out_dir: Path, slice_seconds: int = 10, output_stem: str | None = None) -> list[Path]:
    """Slice a video into fixed-duration chunks. Returns list of slice paths.

    v0.2.1: `output_stem` controls the slice filename prefix. Default is
    `src.stem` (the input file's name, e.g. a Playwright random UUID). Pass
    an explicit stem (e.g. the step name) to get predictable, dryrun-aligned
    filenames like `create-flow.0000.webm`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem or src.stem
    pattern = out_dir / f"{stem}.%04d.webm"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(slice_seconds),
        "-reset_timestamps", "1",
        str(pattern),
    ], check=True, capture_output=True)
    return sorted(out_dir.glob(f"{stem}.*.webm"))


def detect_first_content_timestamp(
    video_path: Path,
    *,
    min_sat: float = 0.5,
    check_seconds: float = 2.0,
) -> float:
    """v0.3.10: detect the first frame that has real content (not
    a white blank) and return its timestamp in seconds. Used to
    trim the leading blank frames that Playwright's recordVideo
    captures when the page is still loading.

    The signal: average frame SATAVG (saturation). A blank frame
    (e.g. white background, no elements) has SATAVG=0. A rendered
    page with any colored element (blue button, red ripple, etc.)
    has SATAVG > 0.5. We scan the first `check_seconds` seconds of
    the video at 1 frame / 40ms and return the timestamp of the
    first frame where SATAVG > min_sat.

    Why SATAVG (saturation) not YAVG (luminance): the test-app's
    UI is a near-white background with a white card, so YAVG of a
    loaded page (~228) and YAVG of a blank white frame (~235)
    differ by only ~7 units -- too close to call reliably. SATAVG
    of a blank frame is exactly 0 (no color); SATAVG of any
    rendered page with the blue login button or red delete button
    is > 0.5.

    Returns 0.0 if no content frame is found in `check_seconds`
    (caller should treat that as "don't trim" since the video
    doesn't seem to have a leading blank).
    """
    import re as _re
    import tempfile as _tempfile
    with _tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as out:
        meta_path = out.name
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-t", str(check_seconds),
            "-vf", "signalstats,metadata=print:file=" + str(meta_path),
            "-an", "-f", "null", "-",
        ]
        subprocess.run(cmd, check=False, capture_output=True, text=True)
        if not Path(meta_path).exists():
            return 0.0
        with open(meta_path) as f:
            content = f.read()
        blocks = _re.findall(
            r"pts_time:([\d.]+).*?SATAVG=([\d.]+)",
            content, flags=_re.DOTALL,
        )
        for ts_str, sat_str in blocks:
            try:
                sat = float(sat_str)
            except ValueError:
                continue
            if sat > min_sat:
                return float(ts_str)
        return 0.0
    finally:
        Path(meta_path).unlink(missing_ok=True)


def trim_blank_start(
    video_path: Path,
    *,
    min_sat: float = 0.5,
    check_seconds: float = 2.0,
    max_passes: int = 3,
) -> float:
    """v0.3.10: trim the leading blank frames from a recorded
    video in-place. Returns the number of seconds trimmed (0 if
    no blank frames found).

    The Playwright `recordVideo` API starts recording when the
    context is created, BEFORE the page navigates and before the
    SPA bundle has finished loading. The result is 80-300ms of
    blank white frames at the start of every video. To a viewer
    this reads as "the recording is broken" -- the video starts
    with nothing, then content appears.

    Fix: detect the first content frame via
    detect_first_content_timestamp() and re-encode the video
    starting from that timestamp, using ffmpeg's `trim` video
    filter (not `-ss`). The filter is frame-accurate — it does
    NOT depend on keyframe placement, so the new mp4's first
    frame is guaranteed to be the content frame.

    Why not `ffmpeg -ss <ts> -i <input>`: that's fast-seek — it
    snaps to the nearest keyframe BEFORE the target ts, which
    means the new mp4 can still start with a blank keyframe. We
    tried it in v0.3.10a and the first frame was still blank
    even though the duration had been correctly trimmed.

    Iterates up to `max_passes` times: after each trim, we
    re-detect the first content frame. If the new mp4 still
    has a blank keyframe at the start, we trim again. In
    practice 1-2 passes is enough.

    Non-destructive: writes to <video_path>.trimmed.mp4, then
    atomically replaces the original. If the detect step finds
    no content frame (very rare -- the video is entirely blank),
    we leave the original alone.
    """
    total_trimmed = 0.0
    for pass_idx in range(max_passes):
        trim_ts = detect_first_content_timestamp(
            video_path, min_sat=min_sat, check_seconds=check_seconds,
        )
        if trim_ts <= 0.01:
            # No more leading blank frames — done.
            break
        tmp_out = video_path.with_suffix(".trimmed.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"trim=start={trim_ts:.3f},setpts=PTS-STARTPTS",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",  # recorder videos are silent; the silent track would
                    # be misaligned after trim, so drop it.
            str(tmp_out),
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0 or not tmp_out.exists():
            print(
                f"WARNING: trim_blank_start pass {pass_idx+1} failed for "
                f"{video_path.name} (returncode={result.returncode}); "
                f"keeping current video.",
                file=sys.stderr,
            )
            if tmp_out.exists():
                tmp_out.unlink()
            return total_trimmed
        tmp_out.replace(video_path)
        total_trimmed += trim_ts
    return total_trimmed




def concat_slices_to_mp4(
    slice_paths: list[Path],
    output_mp4: Path,
    *,
    crf: int = 23,
    preset: str = "medium",
    audio: bool = True,
    trim_leading_blank: bool = True,
) -> Path:
    """Concatenate N webm slices into a single MP4 (libx264).

    Uses ffmpeg concat demuxer. Re-encodes to libx264 with consistent params so the
    output is one playable MP4 (most doc viewers and HTML <video> elements support it).

    Args:
        slice_paths: ordered list of input slice files.
        output_mp4: where to write the concatenated MP4.
        crf: libx264 quality (lower = better, 18-28 sane range, default 23).
        preset: libx264 speed/quality tradeoff (ultrafast → veryslow).
        audio: include audio stream (default True; recorder captures no audio, so
            this typically produces a silent track).
        trim_leading_blank: v0.3.10 — if True (default), detect the first
            content frame via SATAVG and re-encode starting from
            there. Eliminates the 80-300ms of blank-white frames at
            the start that Playwright's recordVideo captures during
            page load. Renamed from `trim_blank_start` in v0.3.10
            because that name shadowed the module-level
            `trim_blank_start()` function.

    Returns: path to the written MP4.
    """
    if not slice_paths:
        raise ValueError("concat_slices_to_mp4: slice_paths is empty")
    for p in slice_paths:
        if not p.exists():
            raise FileNotFoundError(f"concat_slices_to_mp4: missing slice {p}")
    output_mp4.parent.mkdir(parents=True, exist_ok=True)

    # Write a temp concat list file
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in slice_paths:
            # ffmpeg concat demuxer format: file '/path/to/slice.webm'
            f.write(f"file '{p.as_posix()}'\n")
        concat_list = Path(f.name)

    try:
        # Build inputs first, then output options
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
        ]
        if audio:
            # Recorder captures no audio, but the demuxer expects stream layout.
            # Generate a silent audio track via lavfi to keep layout consistent.
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        # All output options AFTER inputs
        cmd += [
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
        ]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "128k"]
            cmd += ["-shortest"]
        cmd += ["-movflags", "+faststart", str(output_mp4)]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    finally:
        concat_list.unlink(missing_ok=True)

    # v0.3.10: trim the leading blank frames. Playwright's
    # recordVideo starts recording at context creation, BEFORE
    # the page navigates and the SPA bundle has loaded. The
    # resulting 80-300ms of blank-white frames at the start of
    # every video make it look like the recording is broken.
    # trim_blank_start() detects the first frame with real
    # content (SATAVG > 0.5) and re-encodes starting from there.
    if trim_leading_blank:
        try:
            trimmed = trim_blank_start(output_mp4)
            if trimmed > 0:
                print(
                    f"INFO: trimmed {trimmed:.2f}s of leading blank frames "
                    f"from {output_mp4.name}",
                    file=sys.stderr,
                )
        except Exception as e:
            # Non-fatal — keep the un-trimmed video if trim fails.
            print(
                f"WARNING: trim_blank_start failed for {output_mp4.name} "
                f"({type(e).__name__}: {e}); keeping un-trimmed video.",
                file=sys.stderr,
            )

    return output_mp4


def get_total_duration(paths: list[Path]) -> float:
    """Sum the durations of all given video files."""
    return sum(get_video_info(p)["duration_s"] for p in paths)
