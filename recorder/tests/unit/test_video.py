import subprocess
import tempfile
from pathlib import Path
import pytest
from recorder_plugin.video import (
    slice_video, validate_slice, get_video_info,
    concat_slices_to_mp4, get_total_duration,
)


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
    assert len(paths) >= 1
    assert all(p.exists() for p in paths)
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


# v1.1: concat_slices_to_mp4

def test_concat_slices_to_mp4_produces_single_file(tmp_path):
    slices = []
    for i in range(3):
        s = tmp_path / f"slice{i:04d}.webm"
        _make_test_video(s, duration=1)
        slices.append(s)
    out = tmp_path / "concat.mp4"
    result = concat_slices_to_mp4(slices, out)
    assert result == out
    assert out.exists()
    info = get_video_info(out)
    # 3 slices × 1s = ~3s total
    assert 2.5 < info["duration_s"] < 4.0
    assert info["codec"] == "h264"


def test_concat_slices_to_mp4_rejects_empty_list(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        concat_slices_to_mp4([], tmp_path / "out.mp4")


def test_concat_slices_to_mp4_rejects_missing_slice(tmp_path):
    real = tmp_path / "real.webm"
    _make_test_video(real, duration=1)
    fake = tmp_path / "fake.webm"  # doesn't exist
    with pytest.raises(FileNotFoundError, match="missing slice"):
        concat_slices_to_mp4([real, fake], tmp_path / "out.mp4")


def test_concat_slices_to_mp4_with_audio_silent(tmp_path):
    """audio=True adds a silent lavfi track; result should still be h264 + aac."""
    s = tmp_path / "s.webm"
    _make_test_video(s, duration=1)
    out = tmp_path / "with-audio.mp4"
    concat_slices_to_mp4([s], out, audio=True)
    assert out.exists()
    info = get_video_info(out)
    assert info["codec"] == "h264"


def test_concat_slices_to_mp4_without_audio(tmp_path):
    s = tmp_path / "s.webm"
    _make_test_video(s, duration=1)
    out = tmp_path / "no-audio.mp4"
    concat_slices_to_mp4([s], out, audio=False)
    assert out.exists()
    info = get_video_info(out)
    assert info["codec"] == "h264"


def test_get_total_duration_sums_correctly(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"v{i}.webm"
        _make_test_video(p, duration=1)
        paths.append(p)
    total = get_total_duration(paths)
    assert 2.5 < total < 3.5


# === v0.2.4 audit round 3: H1 (validate_slice logging) ===

def test_validate_slice_logs_when_file_missing(caplog):
    """H1: a missing file used to return False silently. Now logs a
    warning naming the path so the operator can diagnose."""
    import logging
    from recorder_plugin.video import validate_slice
    caplog.set_level(logging.WARNING, logger="recorder_plugin.video")
    missing = Path("/tmp/this/does/not/exist/anywhere.webm")
    assert validate_slice(missing) is False
    assert any("does not exist" in r.message for r in caplog.records)


def test_validate_slice_logs_when_file_truncated(caplog):
    """H1: a < 100 byte file used to return False silently. Now logs
    a warning with the actual size."""
    import logging
    from recorder_plugin.video import validate_slice
    caplog.set_level(logging.WARNING, logger="recorder_plugin.video")
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(b"x" * 50)  # < 100 bytes
        tiny_path = Path(f.name)
    try:
        assert validate_slice(tiny_path) is False
        assert any("truncated" in r.message for r in caplog.records)
        assert any("50 bytes" in r.message for r in caplog.records)
    finally:
        tiny_path.unlink()


def test_validate_slice_logs_when_ffprobe_fails(caplog):
    """H1: a file that exists and is > 100 bytes but fails ffprobe
    used to return False silently. Now logs the ffprobe error type."""
    import logging
    from recorder_plugin.video import validate_slice
    caplog.set_level(logging.WARNING, logger="recorder_plugin.video")
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(b"\x00" * 200)  # 200 bytes of zeros
        bogus_path = Path(f.name)
    try:
        assert validate_slice(bogus_path) is False
        assert len(caplog.records) >= 1, (
            f"expected at least 1 warning, got 0; this is the H1 "
            f"regression — validate_slice returned False silently again."
        )
    finally:
        bogus_path.unlink()
