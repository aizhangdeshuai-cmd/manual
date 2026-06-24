"""v0.3.5: preserve_session keeps the user logged in across video segments.

The recorder's v0.2.1 design closes the recording page on video_stop
to flush Playwright's webm stream. That discards all in-page state
(localStorage, cookies, JS memory) so the next video segment starts
from scratch. With the test app's `user` ref living in JS memory, the
recorder forced a re-login intro on every single video segment — the
user saw "log in again" 5 times in a row for a 5-segment task flow.

v0.3.5 fixes this by capturing localStorage BEFORE the page close and
replaying it on the fresh page that replaces the closed one, then
reloading so the app reads the restored state on init.

These tests lock in the contract.
"""
import ast
from pathlib import Path
import pytest

SCRIPT_PY = Path(__file__).resolve().parents[2] / "recorder_plugin" / "script.py"


def _parse() -> ast.Module:
    return ast.parse(SCRIPT_PY.read_text())


def test_video_stop_signature_has_preserve_session():
    """_handle_video_stop must take an opt-in preserve_session flag."""
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            kwonly = [a.arg for a in node.args.kwonlyargs]
            assert "preserve_session" in kwonly, (
                f"_handle_video_stop kwonly args = {kwonly}"
            )
            return
    pytest.fail("_handle_video_stop not found")


def test_preserve_session_default_is_false():
    """Default preserve_session=False so the v0.3.4 contract is preserved
    for scripts that don't opt in."""
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            for i, arg in enumerate(node.args.kwonlyargs):
                if arg.arg == "preserve_session":
                    assert i < len(node.args.kw_defaults), (
                        "preserve_session must have a default"
                    )
                    default = node.args.kw_defaults[i]
                    assert isinstance(default, ast.Constant)
                    assert default.value is False, (
                        f"preserve_session default must be False, got {default.value!r}"
                    )
                    return
            pytest.fail("preserve_session not in kwonly args")
    pytest.fail("_handle_video_stop not found")


def test_capture_local_storage_uses_evaluate():
    """v0.3.5 must use page.evaluate to read localStorage before the
    page closes (Playwright only flushes webm on page close, so we have
    to read first)."""
    src = SCRIPT_PY.read_text()
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            body = ast.unparse(node)
            assert "localStorage" in body, (
                "_handle_video_stop must reference localStorage"
            )
            assert "evaluate" in body, (
                "_handle_video_stop must use page.evaluate to read storage"
            )
            # The capture must happen BEFORE the close
            capture_pos = body.find("localStorage.length")
            close_pos = body.find("recording_page.close")
            if capture_pos == -1 or close_pos == -1:
                # alternate forms
                capture_pos = body.find("localStorage")
                close_pos = body.find("close()")
            assert 0 <= capture_pos < close_pos, (
                f"localStorage capture (pos {capture_pos}) must be before "
                f"page close (pos {close_pos})"
            )
            return
    pytest.fail("_handle_video_stop not found")


def test_replay_local_storage_then_reload():
    """After replaying localStorage on the new page, the recorder must
    reload so the app's init code reads the restored state."""
    src = SCRIPT_PY.read_text()
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            body = ast.unparse(node)
            # Should call .reload() to re-init
            assert ".reload(" in body, (
                "_handle_video_stop must call page.reload after replaying "
                "localStorage so the app reads the restored state on init"
            )
            # setItem should appear (we set the captured entries)
            assert "setItem" in body, (
                "_handle_video_stop must write captured localStorage entries "
                "via setItem"
            )
            return
    pytest.fail("_handle_video_stop not found")


def test_run_script_reads_preserve_session_flag():
    """run_script must read `preserve_session` from the script JSON
    and pass it to _handle_video_stop."""
    src = SCRIPT_PY.read_text()
    assert "preserve_session" in src, (
        "run_script must read `preserve_session` from the script JSON"
    )


def test_preserve_session_is_gated_on_flag():
    """The replay logic must be inside `if preserve_session and ...`
    so it doesn't run by default (and so scripts without the flag keep
    the v0.3.4 behavior of starting fresh after each video_stop)."""
    src = SCRIPT_PY.read_text()
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            body = ast.unparse(node)
            assert "preserve_session and" in body, (
                "localStorage replay in _handle_video_stop must be gated on "
                "`preserve_session and ...` to keep it opt-in"
            )
            return
    pytest.fail("_handle_video_stop not found")
