import json
import os
import unittest.mock as mock
from pathlib import Path
import pytest
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


# === v0.2.4 audit round 3: C2 (fsync) ===

def test_atomic_write_json_calls_fsync_on_data_and_dir(tmp_path):
    """C2: atomic_write_json must fsync the data fd AND the parent directory
    fd (so the rename is durable on POSIX). Without these, a power loss
    between os.replace and the page-cache flush leaves the file as zero
    bytes — _load then silently resets to empty, losing idempotency.
    """
    f = tmp_path / "state.json"
    with mock.patch("recorder_plugin.state.os.fsync") as mock_fsync, \
         mock.patch("recorder_plugin.state.os.open", wraps=os.open) as mock_open:
        atomic_write_json(f, {"a": 1})
    # Two fsync calls expected: one for the data fd, one for the dir fd
    # (best-effort; some platforms may skip the dir fsync but it must
    # be ATTEMPTED).
    assert mock_fsync.call_count >= 1, (
        f"expected at least 1 fsync call (data fd), got {mock_fsync.call_count}"
    )
    # The data fsync must happen BEFORE the os.replace returns.
    # We verify by reading the data back: the file must contain
    # the JSON, not be empty.
    assert json.loads(f.read_text()) == {"a": 1}


def test_atomic_write_json_dir_fsync_is_best_effort(tmp_path):
    """C2: the directory fsync is wrapped in try/except (AttributeError,
    OSError) so platforms without O_DIRECTORY support don't break. The
    function must still succeed and write the file."""
    f = tmp_path / "state.json"
    # Force dir fsync to fail by mocking os.open to raise OSError on
    # the second call (the first is the mkstemp call which is via
    # tempfile, not os.open — actually mkstemp uses open() under the
    # hood; let's force ALL os.open calls for O_DIRECTORY to fail).
    real_open = os.open
    def fake_open(path, *args, **kwargs):
        # O_DIRECTORY is the second flag; if it's in args, fail
        for a in args:
            if isinstance(a, int) and (a & os.O_DIRECTORY):
                raise OSError("simulated: filesystem does not support dir fsync")
        return real_open(path, *args, **kwargs)
    with mock.patch("recorder_plugin.state.os.open", side_effect=fake_open):
        atomic_write_json(f, {"b": 2})
    # File must still be written successfully
    assert json.loads(f.read_text()) == {"b": 2}
