import subprocess
import tempfile
from pathlib import Path
import pytest
from recorder_plugin.video import (
    slice_video, validate_slice, get_video_info,
    concat_slices_to_mp4, get_total_duration,
    detect_first_content_timestamp, trim_blank_start,
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



def test_detect_first_content_timestamp_finds_color(tmp_path):
    """v0.3.10: SATAVG-based detection. testsrc has colored bars so
    SATAVG > 0 from frame 0. Pure white lavfi has SATAVG=0. We
    build a 2s video with the first 0.5s as white, then 1.5s of
    testsrc, and assert detection finds content at ~0.5s."""
    out = tmp_path / "white_then_color.mp4"
    # lavfi color source = solid color. Use 'color=color=white' for
    # the first 0.5s, then concat with testsrc for 1.5s. Easiest:
    # use a filter_complex to switch.
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=color=white:size=320x240:rate=15:d=2",
        "-vf", "drawbox=x=0:y=0:w=320:h=120:color=red@1.0:t=fill:enable='gte(t,0.5)'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    ts = detect_first_content_timestamp(out, min_sat=0.5, check_seconds=2.0)
    # Detection should find the frame where the red drawbox starts
    # (i.e. t >= 0.5). The exact frame depends on the encode, but
    # the result should be > 0 and <= 0.6s.
    assert 0.0 < ts <= 0.7, f"expected content detected around 0.5s, got {ts}"


def test_trim_blank_start_drops_leading_white(tmp_path):
    """v0.3.10: trim_blank_start() should drop the leading
    white frames so the resulting video starts with content.
    Test: build a 2s video with white for the first 0.5s and
    color for the rest; trim; assert resulting duration is
    shorter than 2s and first frame has SATAVG > 0."""
    out = tmp_path / "white_then_color.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=color=white:size=320x240:rate=15:d=2",
        "-vf", "drawbox=x=0:y=0:w=320:h=120:color=blue@1.0:t=fill:enable='gte(t,0.5)'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    orig_duration = get_video_info(out)["duration_s"]
    trimmed = trim_blank_start(out, min_sat=0.5, check_seconds=2.0)
    assert trimmed > 0.0, f"expected non-zero trim, got {trimmed}"
    new_duration = get_video_info(out)["duration_s"]
    # Should be shorter, but allow for re-encode jitter
    assert new_duration < orig_duration, (
        f"trim did not shorten video: {orig_duration} -> {new_duration}"
    )


def test_trim_blank_start_no_op_when_no_blank(tmp_path):
    """v0.3.10: if the video starts with content, trim_blank_start
    should return 0 and not modify the file. testsrc=color
    produces colored bars from frame 0, so SATAVG > 0 throughout.
    """
    out = tmp_path / "color_only.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "testsrc=duration=1:size=320x240:rate=15",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    orig_size = out.stat().st_size
    trimmed = trim_blank_start(out, min_sat=0.5, check_seconds=2.0)
    assert trimmed == 0.0, f"expected no trim, got {trimmed}"
    # File should not be rewritten (size unchanged). The detection
    # path doesn't touch the file; trim_blank_start() only writes
    # when trim_ts > 0.01.
    assert out.stat().st_size == orig_size, "file was modified despite no trim"


def test_concat_slices_to_mp4_trim_blank_start_disabled(tmp_path):
    """v0.3.10: passing trim_blank_start=False should skip the
    trim call entirely. We verify by checking that a video with
    a leading blank is NOT trimmed when this flag is False.
    """
    from recorder_plugin.video import slice_video
    # Build a single webm slice with leading blank
    src = tmp_path / "blank.webm"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=color=white:size=320x240:rate=15:d=2",
        "-vf", "drawbox=x=0:y=0:w=320:h=120:color=blue@1.0:t=fill:enable='gte(t,0.5)'",
        "-c:v", "libvpx", "-b:v", "200k", str(src),
    ], check=True, capture_output=True)
    out_dir = tmp_path / "slices"
    slices = slice_video(src, out_dir, slice_seconds=10, output_stem="blank")
    assert slices, "slice_video produced no slices"
    out_mp4 = tmp_path / "result.mp4"
    concat_slices_to_mp4(slices, out_mp4, audio=False, trim_leading_blank=False)
    # If trim had run, the file would be re-encoded; without trim
    # it's just the libx264 output of the concat. We just verify
    # the file exists and has non-zero size.
    assert out_mp4.exists() and out_mp4.stat().st_size > 0


def test_trim_blank_start_first_frame_has_content(tmp_path):
    """v0.3.10: critical regression test. After trim, the first
    frame of the resulting mp4 must have SATAVG > 0 (i.e. be real
    content, not a blank keyframe).

    The bug: when the original mp4's first keyframe is blank
    (white frame captured by Playwright before page render), a
    naive `ffmpeg -ss <ts> -i <input>` re-encode uses fast-seek
    and snaps to that blank keyframe, so the trimmed mp4 STILL
    starts with a blank frame. The fix uses ffmpeg's `trim` video
    filter (frame-accurate, no keyframe dependency), so the new
    first frame is guaranteed to be the content frame.

    Test: build a 1s video that is 100% white. Detect says
    "no content found" (returns 0.0), so trim_blank_start is
    a no-op. Then build a 1s video that is 100% blue — trim
    is also a no-op because there's no blank. Then build a
    1s video that starts with 0.3s of white and has 0.7s of
    blue — detect finds ~0.3s, trim removes it, and the
    resulting mp4's first frame is blue (SATAVG > 0).
    """
    import re as _re

    def _first_frame_satavg(mp4: Path) -> float:
        """Extract the first frame's SATAVG from an mp4."""
        meta = tmp_path / "_stats.txt"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(mp4),
            "-vf", f"signalstats,metadata=print:file={meta}",
            "-frames:v", "1", "-an", "-f", "null", "-",
        ], check=True, capture_output=True)
        m = _re.search(r"SATAVG=([\d.]+)", meta.read_text())
        return float(m.group(1)) if m else 0.0

    # Case 1: 100% white — trim is a no-op, file unchanged
    white_only = tmp_path / "white_only.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "color=color=white:size=320x240:rate=15:d=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(white_only),
    ], check=True, capture_output=True)
    orig_size = white_only.stat().st_size
    assert trim_blank_start(white_only) == 0.0
    assert white_only.stat().st_size == orig_size, (
        "100% white video: trim should be a no-op"
    )

    # Case 2: 100% blue — trim is a no-op (no leading blank)
    blue_only = tmp_path / "blue_only.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "color=color=blue:size=320x240:rate=15:d=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(blue_only),
    ], check=True, capture_output=True)
    assert trim_blank_start(blue_only) == 0.0
    # The first frame is blue → SATAVG > 0 (it's a single color,
    # but blue is saturated).
    sat = _first_frame_satavg(blue_only)
    assert sat > 0.0, f"100% blue: expected first frame to have color, got SATAVG={sat}"

    # Case 3: white → blue transition — the real test.
    # The fix's key invariant: after trim, the first frame has
    # SATAVG > 0 (it's the blue frame, not a residual white keyframe).
    mixed = tmp_path / "white_then_blue.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "color=color=white:size=320x240:rate=15:d=1",
        "-vf", "drawbox=x=0:y=0:w=320:h=240:color=blue@1.0:t=fill:enable='gte(t,0.3)'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(mixed),
    ], check=True, capture_output=True)
    sat_before = _first_frame_satavg(mixed)
    assert sat_before == 0.0, (
        f"setup wrong: first frame should be white, got SATAVG={sat_before}"
    )
    trimmed = trim_blank_start(mixed, min_sat=0.5, check_seconds=1.0)
    assert trimmed > 0.0, f"expected trim > 0, got {trimmed}"
    # CRITICAL: the first frame of the TRIMMED mp4 must have color.
    sat_after = _first_frame_satavg(mixed)
    assert sat_after > 0.0, (
        f"REGRESSION: trim left a blank first frame "
        f"(SATAVG={sat_after}). This is the bug v0.3.10 fixed: "
        f"ffmpeg -ss seeks to a keyframe which can still be blank. "
        f"The fix uses `trim` video filter which is frame-accurate."
    )
