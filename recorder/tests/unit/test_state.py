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
    out.write_bytes(b"fake")  # so the file exists
    state.set_step(3, input_hash="abc", output_path=out, validated=True)
    # Second set with same hash and existing file: should be no-op
    state.set_step(3, input_hash="abc", output_path=out, validated=True)
    record = state.get_step(3)
    assert record["validated"] is True


def test_file_lock_exclusive(tmp_path):
    f = tmp_path / "lock.file"
    with file_lock(f):
        assert f.exists()
