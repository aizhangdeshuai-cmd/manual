"""v0.3.3: opt-in post-video re-navigation must not regress.

The recorder closes the recording page on `video_stop` to flush Playwright's
webm stream, then opens a new page. Without an opt-in flag, the new page
is `about:blank` and every subsequent step fails.

The fix:
- `Recorder.navigate()` uses `urljoin` so relative URLs work.
- `_handle_video_start` records `recording_url` + `base_url` on the session.
- `_handle_video_stop` only re-navigates the new page when the script
  sets `reopen_page_after_video: true` (default false).

These tests lock in the contract so a future refactor doesn't silently
break either direction.
"""
import inspect
from pathlib import Path
import pytest


SCRIPT_PY = Path(__file__).resolve().parents[2] / "recorder_plugin" / "script.py"
CORE_PY = Path(__file__).resolve().parents[2] / "recorder_plugin" / "core.py"


def test_recorder_navigate_signature_uses_urljoin():
    """v0.3.3: Recorder.navigate must use urljoin to resolve relative URLs."""
    src = CORE_PY.read_text()
    assert "urljoin" in src, (
        "Recorder.navigate must use urljoin so relative URLs (e.g. '/') "
        "resolve against the last visited absolute URL."
    )
    # And it must refuse to navigate to a bare-relative URL when no base has
    # been seen — that would be ambiguous and silently fail.
    assert "first navigate must be absolute" in src, (
        "Recorder.navigate must raise a clear error if called with a relative "
        "URL before any absolute URL has been seen."
    )


def test_video_stop_signature_has_reopen_flag():
    """v0.3.3: _handle_video_stop must take an opt-in reopen_after_video flag."""
    import ast
    mod = ast.parse(SCRIPT_PY.read_text())
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            kwonly_arg_names = [a.arg for a in node.args.kwonlyargs]
            assert "reopen_after_video" in kwonly_arg_names, (
                f"_handle_video_stop must have reopen_after_video as a keyword-only arg; "
                f"got kwonly={kwonly_arg_names}"
            )
            return
    pytest.fail("_handle_video_stop not found")


def test_reopen_flag_default_is_false():
    """v0.3.3: opt-in — default reopen_after_video=False to preserve prior
    contract (script author must `navigate` explicitly between videos)."""
    import ast
    mod = ast.parse(SCRIPT_PY.read_text())
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            for i, arg in enumerate(node.args.kwonlyargs):
                if arg.arg == "reopen_after_video":
                    if i >= len(node.args.kw_defaults):
                        pytest.fail("reopen_after_video must have a default value (False)")
                    default = node.args.kw_defaults[i]
                    assert isinstance(default, ast.Constant) and default.value is False, (
                        f"reopen_after_video default must be False, got {ast.unparse(default)!r}"
                    )
                    return
            pytest.fail("reopen_after_video not in kwonly args")
    pytest.fail("_handle_video_stop not found")


def test_run_script_reads_reopen_flag():
    """v0.3.3: run_script must read reopen_page_after_video from script JSON
    and pass it to _handle_video_stop."""
    src = SCRIPT_PY.read_text()
    assert "reopen_page_after_video" in src, (
        "run_script must read `reopen_page_after_video` from the script JSON"
    )


def test_reopen_block_is_gated_on_flag():
    """The re-navigation code in _handle_video_stop must be inside an
    `if reopen_after_video and ...` block — otherwise it would auto-navigate
    on every video_stop, which is the v0.2.1 behavior we want to disable."""
    import ast
    mod = ast.parse(SCRIPT_PY.read_text())
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_video_stop":
            body_src = ast.unparse(node)
            assert "reopen_after_video and" in body_src, (
                "re-navigation in _handle_video_stop must be gated on "
                "`reopen_after_video and ...` to keep it opt-in."
            )
            # Also: the block should contain a goto call
            assert "new_page.goto" in body_src, (
                "Expected new_page.goto inside the opt-in re-navigation block"
            )
            return
    pytest.fail("_handle_video_stop not found")
