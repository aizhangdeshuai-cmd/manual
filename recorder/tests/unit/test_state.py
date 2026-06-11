import json
from pathlib import Path
from recorder_plugin.state import RecorderState, atomic_write_json, file_lock


def test_atomic_write_json(tmp_path):
    f = tmp_path / "state.json"
    atomic_write_json(f, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(f.read_text()) == {"a": 1, "b": [1, 2, 3]}


def test_atomic_write_json_no_partial_file(tmp_path):
    f = tmp_path / "state.json"
    atomic_write_json(f, {"a": 1})
    assert not (tmp_path / "state.json.tmp").exists()


def test_recorder_state_skip_when_valid(tmp_path):
    state = RecorderState(tmp_path, "test-script")
    out = tmp_path / "out.png"
    out.write_bytes(b"fake")
    state.set_step(3, input_hash="abc", output_path=out, validated=True)
    state.set_step(3, input_hash="abc", output_path=out, validated=True)
    record = state.get_step(3)
    assert record["validated"] is True


def test_file_lock_exclusive(tmp_path):
    f = tmp_path / "lock.file"
    with file_lock(f):
        assert f.exists()


# v1.1: video session tracking for cross-process resume

def test_video_session_set_and_check(tmp_path):
    state = RecorderState(tmp_path, "test-script")
    out = tmp_path / "create-flow.mp4"
    out.write_bytes(b"fake video")
    state.set_video_session("create-flow", out, validated=True)
    assert state.is_video_session_valid("create-flow") is True
    record = state.get_video_session("create-flow")
    assert record["output_path"] == str(out)
    assert record["validated"] is True


def test_video_session_not_set_returns_false(tmp_path):
    state = RecorderState(tmp_path, "test-script")
    assert state.is_video_session_valid("never-set") is False
    assert state.get_video_session("never-set") is None


def test_video_session_invalid_when_output_missing(tmp_path):
    state = RecorderState(tmp_path, "test-script")
    out = tmp_path / "gone.mp4"
    state.set_video_session("gone", out, validated=True)
    # Don't create the file → should be invalid
    assert state.is_video_session_valid("gone") is False


def test_video_session_invalid_when_not_validated(tmp_path):
    state = RecorderState(tmp_path, "test-script")
    out = tmp_path / "v.mp4"
    out.write_bytes(b"x")
    state.set_video_session("v", out, validated=False)
    assert state.is_video_session_valid("v") is False


def test_state_loads_legacy_without_video_sessions(tmp_path):
    """Backward compat: state files written by v1.0 (no video_sessions key) load OK."""
    legacy = {
        "script_name": "old",
        "steps": {"0": {"input_hash": "x", "output_path": "/tmp/x", "mtime": "2026-01-01", "validated": True}},
    }
    state_file = tmp_path / ".recorder_state.json"
    state_file.write_text(json.dumps(legacy))
    state = RecorderState(tmp_path, "old")
    # v1.1 sections should be added on load
    assert "video_sessions" in state._data
    assert state._data["video_sessions"] == {}
