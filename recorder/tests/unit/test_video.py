import subprocess
from pathlib import Path
from recorder_plugin.video import slice_video, validate_slice, get_video_info


def _make_test_video(path: Path, duration: int = 2, size: str = "320x240", rate: int = 15) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={duration}:size={size}:rate={rate}",
        "-c:v", "libvpx", "-b:v", "200k", str(path)
    ], check=True, capture_output=True)


def test_get_video_info_returns_duration(tmp_path):
    src = tmp_path / "input.webm"
    _make_test_video(src, duration=2)
    info = get_video_info(src)
    assert 1.5 < info["duration_s"] < 2.5


def test_slice_video_produces_chunks(tmp_path):
    src = tmp_path / "input.webm"
    _make_test_video(src, duration=5)
    out_dir = tmp_path / "slices"
    paths = slice_video(src, out_dir, slice_seconds=2)
    # ffmpeg segment muxer with -c copy splits on keyframes. The libvpx default
    # keyframe interval may be > 2s, so we get >= 1 chunk; the recorder uses
    # Playwright's webm which has frequent keyframes, so 10s slices produce
    # clean chunks. This test asserts the slicer runs without error.
    assert len(paths) >= 1
    assert all(p.exists() for p in paths)
    # Total duration of all slices should approximately equal source duration
    from recorder_plugin.video import get_video_info
    total = sum(get_video_info(p)["duration_s"] for p in paths)
    assert 3.5 < total < 6


def test_validate_slice_passes_valid_file(tmp_path):
    src = tmp_path / "input.webm"
    _make_test_video(src, duration=1)
    assert validate_slice(src) is True


def test_validate_slice_rejects_missing_file(tmp_path):
    assert validate_slice(tmp_path / "does_not_exist.webm") is False


def test_validate_slice_rejects_tiny_file(tmp_path):
    tiny = tmp_path / "tiny.webm"
    tiny.write_bytes(b"x")
    assert validate_slice(tiny) is False
