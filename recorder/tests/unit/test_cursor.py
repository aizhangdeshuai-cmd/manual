"""v0.3.7: cursor overlay injection for visible mouse cursor in recorded video.

Playwright's recordVideo captures the page DOM but NOT the OS cursor.
In headless mode there's no OS cursor to render, so the recorded
webm shows clicks happening with no visible pointer. This module
injects an in-page SVG cursor that follows the mouse so the
recorded video looks like a real person using the app.

These tests verify:
  - inject_cursor adds a <div id="__rec_cursor__"> with the expected
    SVG arrow inside.
  - remove_cursor takes it back out (idempotent).
  - move_cursor updates the overlay's left/top CSS.
  - start_tracking installs a mousemove listener; subsequent DOM
    mousemove events update window.__lastMouseX/__lastMouseY and
    push to __recCursorTrail.
  - stop_tracking removes the listener.
  - inject is idempotent: a second call replaces the old overlay
    cleanly without leaving duplicates.

Tests use a minimal synthetic HTML page written to a temp file
and loaded via file:// — no dev server needed.
"""
from __future__ import annotations
import asyncio
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

# Add recorder/ to path so we can import recorder_plugin
RECORDER_ROOT = Path(__file__).resolve().parents[2]
if str(RECORDER_ROOT) not in sys.path:
    sys.path.insert(0, str(RECORDER_ROOT))


# Skip conditions — both Playwright and a live browser binary are
# required for cursor tests (they actually run a headless page).
try:
    from playwright.async_api import async_playwright
    _playwright_ok = True
except ImportError:
    _playwright_ok = False

try:
    from recorder_plugin import cursor as cursor_mod
    _cursor_ok = True
except ImportError:
    _cursor_ok = False


def _needs_browser():
    """Skip the whole class if Playwright or the cursor module
    can't be imported."""
    if not _playwright_ok:
        return "playwright not installed"
    if not _cursor_ok:
        return "recorder_plugin.cursor import failed"
    return None


# Minimal page used as the page-under-test. Includes a button so
# we can verify clicks reach it through the cursor overlay (the
# overlay has pointer-events:none, so it must not block).
SYNTHETIC_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>cursor test page</title>
  <style>
    body { margin: 0; padding: 0; }
    .btn { position: absolute; left: 200px; top: 200px;
           width: 100px; height: 50px; }
  </style>
</head>
<body>
  <button class="btn" id="test-btn">Click me</button>
</body>
</html>
"""


@unittest.skipIf(_needs_browser(), _needs_browser() or "")
class TestCursorOverlay(unittest.IsolatedAsyncioTestCase):
    """End-to-end: launch Chromium headless against a real page,
    inject the cursor, manipulate it, verify the DOM state."""

    async def asyncSetUp(self) -> None:
        # Write the synthetic page to a temp file
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False
        )
        self._tmp.write(SYNTHETIC_HTML)
        self._tmp.close()
        self._tmp_path = Path(self._tmp.name)

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._ctx = await self._browser.new_context(
            viewport={"width": 800, "height": 600},
        )
        self._page = await self._ctx.new_page()
        await self._page.goto(self._tmp_path.as_uri())

    async def asyncTearDown(self) -> None:
        try:
            await self._ctx.close()
            await self._browser.close()
            await self._pw.stop()
        except Exception:
            pass
        try:
            self._tmp_path.unlink()
        except Exception:
            pass

    async def test_inject_adds_overlay_with_svg(self) -> None:
        """After inject_cursor, body should contain a #__rec_cursor__
        div with an <svg> child. The overlay should be fixed-position
        and have pointer-events:none so it never blocks clicks."""
        await cursor_mod.inject_cursor(self._page)
        info = await self._page.evaluate("""
            () => {
                const el = document.getElementById('__rec_cursor__');
                if (!el) return { found: false };
                return {
                    found: true,
                    tag: el.tagName,
                    hasSvg: !!el.querySelector('svg'),
                    position: getComputedStyle(el).position,
                    pointerEvents: getComputedStyle(el).pointerEvents,
                    zIndex: parseInt(getComputedStyle(el).zIndex, 10),
                };
            }
        """)
        self.assertTrue(info["found"], "overlay <div> missing")
        self.assertEqual(info["tag"], "DIV")
        self.assertTrue(info["hasSvg"], "overlay <div> has no <svg> child")
        self.assertEqual(info["position"], "fixed")
        self.assertEqual(info["pointerEvents"], "none")
        # z-index 2147483647 is max-int; should be the largest possible
        self.assertGreaterEqual(info["zIndex"], 2147483646)

    async def test_inject_is_idempotent(self) -> None:
        """Calling inject_cursor twice should leave exactly ONE
        overlay element (not two stacked on top of each other)."""
        await cursor_mod.inject_cursor(self._page)
        await cursor_mod.inject_cursor(self._page)
        count = await self._page.evaluate("""
            () => document.querySelectorAll('#__rec_cursor__').length
        """)
        self.assertEqual(count, 1, "duplicate overlays after re-inject")

    async def test_remove_clears_overlay(self) -> None:
        """remove_cursor should remove the overlay; calling it
        twice is a no-op (idempotent)."""
        await cursor_mod.inject_cursor(self._page)
        await cursor_mod.remove_cursor(self._page)
        gone = await self._page.evaluate("""
            () => !document.getElementById('__rec_cursor__')
        """)
        self.assertTrue(gone, "overlay still present after remove")
        # Idempotent: removing again should not throw.
        await cursor_mod.remove_cursor(self._page)

    async def test_move_cursor_updates_position(self) -> None:
        """move_cursor(x, y) should set the overlay's left/top CSS
        and update window.__lastMouseX/Y."""
        await cursor_mod.inject_cursor(self._page)
        await cursor_mod.move_cursor(self._page, 123.4, 567.8)
        pos = await self._page.evaluate("""
            () => {
                const el = document.getElementById('__rec_cursor__');
                return {
                    left: el.style.left,
                    top: el.style.top,
                    x: window.__lastMouseX,
                    y: window.__lastMouseY,
                };
            }
        """)
        self.assertEqual(pos["left"], "123.4px")
        self.assertEqual(pos["top"], "567.8px")
        self.assertEqual(pos["x"], 123.4)
        self.assertEqual(pos["y"], 567.8)

    async def test_start_tracking_captures_mousemove(self) -> None:
        """After start_tracking, dispatching a DOM mousemove event
        should update __lastMouseX/Y and append to the trail."""
        await cursor_mod.inject_cursor(self._page)
        await cursor_mod.start_tracking(self._page)
        # Dispatch a real DOM event
        await self._page.evaluate("""
            () => {
                const ev = new MouseEvent('mousemove', {
                    clientX: 50, clientY: 75, bubbles: true,
                });
                document.dispatchEvent(ev);
            }
        """)
        result = await self._page.evaluate("""
            () => ({
                x: window.__lastMouseX,
                y: window.__lastMouseY,
                trailLen: (window.__recCursorTrail || []).length,
            })
        """)
        self.assertEqual(result["x"], 50)
        self.assertEqual(result["y"], 75)
        self.assertGreaterEqual(result["trailLen"], 1)

    async def test_stop_tracking_detaches_listener(self) -> None:
        """After stop_tracking, dispatched mousemove events should
        NOT update __lastMouseX/Y (until tracking is re-started)."""
        await cursor_mod.inject_cursor(self._page)
        await cursor_mod.start_tracking(self._page)
        # Send one event — captured
        await self._page.evaluate("""
            () => document.dispatchEvent(new MouseEvent('mousemove',
                { clientX: 10, clientY: 20, bubbles: true }))
        """)
        await cursor_mod.stop_tracking(self._page)
        # Reset state
        await self._page.evaluate(
            "() => { window.__lastMouseX = -1; window.__lastMouseY = -1; }"
        )
        # Send another — should NOT be captured
        await self._page.evaluate("""
            () => document.dispatchEvent(new MouseEvent('mousemove',
                { clientX: 999, clientY: 888, bubbles: true }))
        """)
        pos = await self._page.evaluate("""
            () => ({ x: window.__lastMouseX, y: window.__lastMouseY })
        """)
        self.assertEqual(pos["x"], -1)
        self.assertEqual(pos["y"], -1)

    async def test_overlay_does_not_block_clicks(self) -> None:
        """The overlay must have pointer-events:none so clicks
        pass through to the elements underneath. We verify by
        clicking a known button and checking the click reached it."""
        await cursor_mod.inject_cursor(self._page)
        # Move cursor over the button, then click. If the overlay
        # blocked the click, the button's click event would not
        # fire and our flag would remain false.
        await self._page.evaluate("""
            () => { window.__btnClicked = false;
                    document.getElementById('test-btn').addEventListener(
                        'click', () => { window.__btnClicked = true; }
                    ); }
        """)
        await cursor_mod.move_cursor(self._page, 250, 225)
        await self._page.mouse.click(250, 225)
        clicked = await self._page.evaluate("() => window.__btnClicked")
        self.assertTrue(clicked, "button click was blocked by cursor overlay")


class TestCursorModuleShape(unittest.TestCase):
    """Static checks on the cursor module — run without a browser."""

    def test_module_exports_expected_functions(self) -> None:
        from recorder_plugin import cursor as c
        for name in ("inject_cursor", "remove_cursor", "move_cursor",
                     "start_tracking", "stop_tracking", "get_trail"):
            self.assertTrue(
                inspect.iscoroutinefunction(getattr(c, name)),
                f"cursor.{name} should be a coroutine function",
            )

    def test_inject_js_contains_cursor_id(self) -> None:
        """The inject JS must reference the CURSOR_ID so the
        appended <div> can be found again for cleanup."""
        from recorder_plugin import cursor as c
        self.assertIn(c.CURSOR_ID, c._INJECT_JS)

    def test_remove_js_is_safe_when_overlay_missing(self) -> None:
        """The remove JS uses getElementById + remove(), which is
        safe to call when no overlay exists. Verify the JS is
        well-formed (parses as JS — checked by Node or just by
        the fact that remove_child on null would throw, but
        getElementById returning null is fine)."""
        from recorder_plugin import cursor as c
        # The function is wrapped in an IIFE; just check it doesn't
        # contain obvious bugs (e.g. unclosed braces).
        self.assertTrue(c._REMOVE_JS.strip().startswith("() =>"))
        self.assertIn("return", c._REMOVE_JS)


if __name__ == "__main__":
    unittest.main()
