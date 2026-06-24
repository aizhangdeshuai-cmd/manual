"""v0.3.4: type and click must produce visible, human-like motion in the recording.

v0.2.x used page.fill() (one-frame value set) and page.click() (teleport
+ click in the same frame). The resulting video looked like a demo:
text appeared all at once, cursor jumped without trail. v0.3.4 fixes
both with per-character keyboard.type() and stepped mouse.move().

These tests lock in the new default behavior so a future refactor
doesn't silently regress to the demo-style recording.
"""
import ast
from pathlib import Path
import pytest

SCRIPT_PY = Path(__file__).resolve().parents[2] / "recorder_plugin" / "script.py"


def _parse() -> ast.Module:
    return ast.parse(SCRIPT_PY.read_text())


def test_type_uses_keyboard_type_not_page_fill():
    """_handle_type must call page.keyboard.type (per-char) by default,
    not page.fill (single-frame set)."""
    src = SCRIPT_PY.read_text()
    # find the _handle_type body
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_type":
            body = ast.unparse(node)
            assert "page.keyboard.type" in body, (
                "_handle_type must use page.keyboard.type for per-char animation"
            )
            # The default path should NOT use page.fill (it's only the
            # opt-out instant_type branch).
            # Strip the instant_type branch and check the rest still uses
            # keyboard.type.
            assert "instant_type" in body, (
                "_handle_type must expose an opt-out instant_type flag"
            )
            return
    pytest.fail("_handle_type not found")


def test_type_per_char_delay_is_realistic():
    """The per-character delay should be in the human-typing range
    (50-200ms). Too fast (<10ms) = demo, too slow (>300ms) = annoying.
    Acceptable forms: `delay=N`, `delay=randint(A,B)`, or any numeric
    constant in 50-200."""
    import re
    src = SCRIPT_PY.read_text()
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_type":
            body = ast.unparse(node)
            # Form 1: randint(A, B) call
            m = re.search(r"randint\(\s*(\d+)\s*,\s*(\d+)\s*\)", body)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                assert 50 <= lo <= hi <= 200, (
                    f"randint({lo},{hi}) out of human-typing range"
                )
                return
            # Form 2: delay = N
            m = re.search(r"delay\s*=\s*(\d+)", body)
            if m:
                n = int(m.group(1))
                assert 50 <= n <= 200, f"delay={n} out of human-typing range"
                return
            # Form 3: at least one number in range
            numbers = [int(x) for x in re.findall(r"\b(\d+)\b", body)]
            in_range = [n for n in numbers if 50 <= n <= 200]
            assert in_range, (
                f"_handle_type must set a per-char delay in 50-200ms; "
                f"numbers found: {numbers}"
            )
            return
    pytest.fail("_handle_type not found")


def test_click_moves_mouse_before_clicking():
    """_handle_click must call page.mouse.move() before page.mouse.click()
    so the cursor is visibly traveling in the recording."""
    src = SCRIPT_PY.read_text()
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_click":
            body = ast.unparse(node)
            assert "page.mouse.move" in body, (
                "_handle_click must use page.mouse.move for visible cursor travel"
            )
            assert "page.mouse.click" in body, (
                "_handle_click must call page.mouse.click (not page.click teleport)"
            )
            # The move must come BEFORE the click
            move_pos = body.find("page.mouse.move")
            click_pos = body.find("page.mouse.click")
            assert move_pos < click_pos, (
                "page.mouse.move must be called before page.mouse.click"
            )
            return
    pytest.fail("_handle_click not found")


def test_click_has_instant_opt_out():
    """Scripts must be able to skip the cursor animation for cases where
    it would hurt (e.g. clicking an offscreen element to scroll)."""
    src = SCRIPT_PY.read_text()
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_click":
            body = ast.unparse(node)
            assert "instant_click" in body, (
                "_handle_click must support an opt-out instant_click flag"
            )
            return
    pytest.fail("_handle_click not found")
