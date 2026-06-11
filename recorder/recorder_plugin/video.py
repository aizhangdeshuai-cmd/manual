"""Video recording: Playwright records webm; ffmpeg slices into 10s chunks; ffprobe validates each."""
from __future__ import annotations
import json
import subprocess
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


def slice_video(src: Path, out_dir: Path, slice_seconds: int = 10) -> list[Path]:
    """Slice a video into fixed-duration chunks. Returns list of slice paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / f"{src.stem}.%04d.webm"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(slice_seconds),
        "-reset_timestamps", "1",
        str(pattern),
    ], check=True, capture_output=True)
    return sorted(out_dir.glob(f"{src.stem}.*.webm"))
