"""Idempotency state: per-script JSON, atomic writes, flock for cross-process safety.

v1.1: also tracks named video sessions (e.g. "create-flow") so re-runs of the same
script can skip already-completed video recording sessions.
"""
from __future__ import annotations
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

STATE_FILENAME = ".recorder_state.json"


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: write to .tmp, fsync, then os.replace, fsync the dir.

    v0.2.4 audit round 3 (C2): added `os.fsync(fd)` before close and
    `os.fsync(dir_fd)` on the parent directory after `os.replace`. A
    power loss / SIGKILL between replace and the page-cache flush
    used to leave a zero-byte or stale file; the on-load
    JSONDecodeError branch then silently reset to empty, making
    every subsequent run treat all steps as fresh (loss of
    idempotency). With both fsyncs, the data is durable before
    os.replace returns.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_state_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(fd)
        os.replace(tmp_path, path)
        # fsync the directory entry too (POSIX requires this for the
        # rename to be durable). Best-effort: not all filesystems
        # support dir fsync; ignore OSError.
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            pass
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive flock on `lock_path`. Releases on context exit.

    v0.2.4 audit round 3 (M1): a non-blocking probe is performed first.
    If another process already holds the lock, raise a clear
    `RecorderStateLocked` error instead of blocking forever. The
    caller (RecorderState) translates this into a warning, since
    parallel invocations of the same script on the same output_dir
    are not a supported pattern.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            os.close(fd)
            raise RecorderStateLocked(
                f"state lock {lock_path} is held by another live process. "
                f"Concurrent invocations of the same recorder script on the "
                f"same output_dir are not supported (would race on the "
                f"state file)."
            ) from e
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    except RecorderStateLocked:
        raise
    except Exception:
        # If anything else fails mid-yield, still release the lock
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)
        raise


class RecorderStateLocked(RuntimeError):
    """Raised when the state file is held by another live process."""


class RecorderState:
    """Per-script idempotency state.

    Stores:
    - steps: {step_idx: {input_hash, output_path, mtime, validated}}
    - video_sessions: {session_name: {output_path, validated, mtime}}  (v1.1)

    Re-run skips a step if its output_path exists and input_hash matches.
    Re-run skips a video session if its output_path exists and is validated.
    """

    def __init__(self, output_dir: Path, script_name: str):
        self.output_dir = Path(output_dir)
        self.script_name = script_name
        self.path = self.output_dir / STATE_FILENAME
        self._data: dict = {
            "script_name": script_name,
            "steps": {},
            "video_sessions": {},
        }
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                with file_lock(self.path.with_suffix(".lock")):
                    self._data = json.loads(self.path.read_text())
                # Ensure new sections exist for state files written by older versions
                self._data.setdefault("steps", {})
                self._data.setdefault("video_sessions", {})
            except (json.JSONDecodeError, OSError):
                self._data = {
                    "script_name": self.script_name,
                    "steps": {},
                    "video_sessions": {},
                }

    def _save(self) -> None:
        with file_lock(self.path.with_suffix(".lock")):
            atomic_write_json(self.path, self._data)

    def set_step(self, step_idx: int, input_hash: str, output_path: Path, validated: bool) -> None:
        from datetime import datetime, timezone
        path = Path(output_path)
        existing = self._data["steps"].get(str(step_idx))
        if path.exists() and existing and existing.get("input_hash") == input_hash:
            return
        self._data["steps"][str(step_idx)] = {
            "input_hash": input_hash,
            "output_path": str(path),
            "mtime": datetime.now(timezone.utc).isoformat(),
            "validated": validated,
        }
        self._save()

    def get_step(self, step_idx: int) -> dict | None:
        return self._data["steps"].get(str(step_idx))

    def is_step_valid(self, step_idx: int, input_hash: str) -> bool:
        record = self.get_step(step_idx)
        if not record:
            return False
        if record["input_hash"] != input_hash:
            return False
        return Path(record["output_path"]).exists()

    # v1.1: video session tracking

    def set_video_session(self, name: str, output_path: Path, validated: bool) -> None:
        from datetime import datetime, timezone
        path = Path(output_path)
        self._data["video_sessions"][name] = {
            "output_path": str(path),
            "validated": validated,
            "mtime": datetime.now(timezone.utc).isoformat(),
        }
        self._save()

    def is_video_session_valid(self, name: str) -> bool:
        record = self._data.get("video_sessions", {}).get(name)
        if not record:
            return False
        if not record.get("validated"):
            return False
        return Path(record["output_path"]).exists()

    def get_video_session(self, name: str) -> dict | None:
        return self._data.get("video_sessions", {}).get(name)
