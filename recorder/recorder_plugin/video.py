"""Video recording: Playwright records webm; ffmpeg slices into 10s chunks; ffprobe validates each.

v1.1 adds `concat_slices_to_mp4` — re-encode N webm slices into one MP4 (libx264) for
doc embed. Uses the ffmpeg concat demuxer (requires intermediate concat list file).
"""
from __future__ import annotations
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


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
        "codec": video_stream.get("codec_name", ""),
    }


def validate_slice(path: Path) -> bool:
    """ffprobe-validate a slice. Returns True if parseable and duration > 0."""
    if not path.exists() or path.stat().st_size < 100:
        return False
    try:
        info = get_video_info(path)
        return info["duration_s"] > 0
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
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


def concat_slices_to_mp4(
    slice_paths: list[Path],
    output_mp4: Path,
    *,
    crf: int = 23,
    preset: str = "medium",
    audio: bool = True,
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

    return output_mp4


def get_total_duration(paths: list[Path]) -> float:
    """Sum the durations of all given video files."""
    return sum(get_video_info(p)["duration_s"] for p in paths)
