"""v0.3.8: HUD overlay (cursor + keystroke + click ripple) for recorded video.

The recorder injects a visible HUD into the recorded page so the
webm shows a real-looking cursor that follows the mouse, click
ripples at the moment of mousedown, and keystroke chips when
keys are pressed. This makes the recording look like a real
person using the app, not a slide-show.

The pattern is from snomiao/demowright (MIT, 2026) — split into
two pieces:
  - A listener (addInitScript) that runs in every new document,
    updates state.cx/cy / state.keys but never touches the DOM.
  - A DOM injector (page.evaluate) that creates the visible
    elements and wires them to the listener via callbacks.

These tests verify both pieces and the integration.

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
class TestHudOverlay(unittest.IsolatedAsyncioTestCase):
    """End-to-end: launch Chromium headless against a real page,
    install + inject the HUD, manipulate it, verify DOM state."""

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
        # v0.3.8: install() registers an addInitScript that runs
        # in every new document. Must be called BEFORE goto() so
        # the listener is already active when the page loads.
        await cursor_mod.install(self._ctx)
        self._page = await self._ctx.new_page()
        await self._page.goto(self._tmp_path.as_uri())
        # After navigation, inject the visible DOM elements.
        await cursor_mod.inject_overlay(self._page)

    async def asyncTearDown(self) -> None:
        try:
            await cursor_mod.remove_overlay(self._page)
            await self._ctx.close()
            await self._browser.close()
            await self._pw.stop()
        except Exception:
            pass
        try:
            self._tmp_path.unlink()
        except Exception:
            pass

    async def test_inject_creates_cursor_with_svg(self) -> None:
        """After inject_overlay, the HUD host should exist and
        contain the cursor <div> with an <svg> child."""
        info = await self._page.evaluate("""
            () => {
                const host = document.getElementById('__rec_hud_host__');
                const cursor = document.getElementById('__rec_cursor__');
                if (!host || !cursor) return { found: false };
                return {
                    found: true,
                    hostPointerEvents: getComputedStyle(host).pointerEvents,
                    cursorHasSvg: !!cursor.querySelector('svg'),
                    hostZIndex: parseInt(getComputedStyle(host).zIndex, 10),
                };
            }
        """)
        self.assertTrue(info["found"], "HUD host or cursor missing")
        self.assertEqual(info["hostPointerEvents"], "none")
        self.assertTrue(info["cursorHasSvg"], "cursor <div> has no <svg> child")
        # z-index 2147483647 is max-int; should be the largest possible
        self.assertGreaterEqual(info["hostZIndex"], 2147483646)

    async def test_cursor_tracks_mousemove(self) -> None:
        """v0.3.7 bug regression: the cursor overlay's transform
        must actually follow mouse moves. The listener's callback
        updates cursor.style.transform; the cursor's transform
        CSS variable should reflect the latest mouse position."""
        # Initial position is the state's cx/cy (defaults to -40,-40)
        await self._page.evaluate("""
            () => {
                const c = document.getElementById('__rec_cursor__');
                window.__t0 = c.style.transform;
            }
        """)
        # Dispatch a mousemove
        await self._page.evaluate("""
            () => document.dispatchEvent(new MouseEvent('mousemove',
                { clientX: 200, clientY: 300, bubbles: true }))
        """)
        await self._page.wait_for_timeout(50)
        new_xform = await self._page.evaluate("""
            () => document.getElementById('__rec_cursor__').style.transform
        """)
        # The transform should now contain 200, 300 somewhere
        self.assertIn("200", new_xform, f"transform did not update: {new_xform!r}")
        self.assertIn("300", new_xform, f"transform did not update: {new_xform!r}")

    async def test_inject_is_idempotent(self) -> None:
        """Re-injecting the overlay should leave exactly ONE host element."""
        await cursor_mod.inject_overlay(self._page)
        count = await self._page.evaluate("""
            () => document.querySelectorAll('#__rec_hud_host__').length
        """)
        self.assertEqual(count, 1, "duplicate HUD hosts after re-inject")

    async def test_remove_clears_host_and_callbacks(self) -> None:
        """remove_overlay removes the host AND nulls the state
        callbacks, so a later inject gets a clean slate."""
        await cursor_mod.remove_overlay(self._page)
        gone = await self._page.evaluate("""
            () => !document.getElementById('__rec_hud_host__')
        """)
        self.assertTrue(gone, "HUD host still present after remove")
        callbacks_cleared = await self._page.evaluate("""
            () => {
                const s = window.__recHud;
                return !s.onCursorMove && !s.onMouseDown && !s.onKeyDown;
            }
        """)
        self.assertTrue(callbacks_cleared, "state callbacks not cleared")
        # Re-inject should succeed cleanly.
        await cursor_mod.inject_overlay(self._page)
        again = await self._page.evaluate("""
            () => !!document.getElementById('__rec_hud_host__')
        """)
        self.assertTrue(again, "could not re-inject after remove")

    async def test_mousedown_creates_click_ripple(self) -> None:
        """A mousedown event should create a ripple element at
        the click coordinates."""
        await self._page.evaluate("""
            () => document.dispatchEvent(new MouseEvent('mousedown',
                { clientX: 150, clientY: 250, bubbles: true }))
        """)
        await self._page.wait_for_timeout(50)
        info = await self._page.evaluate("""
            () => {
                const r = document.querySelector('.__rec_ripple__');
                if (!r) return { found: false };
                return {
                    found: true,
                    left: r.style.left,
                    top: r.style.top,
                };
            }
        """)
        self.assertTrue(info["found"], "no ripple element after mousedown")
        self.assertEqual(info["left"], "150px")
        self.assertEqual(info["top"], "250px")

    async def test_keydown_creates_keystroke_chip(self) -> None:
        """A keydown event should add a chip to the keystroke HUD."""
        await self._page.evaluate("""
            () => document.dispatchEvent(new KeyboardEvent('keydown',
                { key: 'a', bubbles: true }))
        """)
        await self._page.wait_for_timeout(50)
        chip = await self._page.evaluate("""
            () => {
                const chips = document.querySelectorAll('.__rec_key__');
                return chips.length > 0 ? chips[0].textContent : null;
            }
        """)
        self.assertEqual(chip, "a", f"expected keystroke chip 'a', got {chip!r}")

    async def test_hud_does_not_block_clicks(self) -> None:
        """The HUD host must have pointer-events:none so clicks
        pass through to the elements underneath. Verify by
        clicking the test button and checking the click reached it."""
        await self._page.evaluate("""
            () => { window.__btnClicked = false;
                    document.getElementById('test-btn').addEventListener(
                        'click', () => { window.__btnClicked = true; }
                    ); }
        """)
        await self._page.mouse.click(250, 225)
        clicked = await self._page.evaluate("() => window.__btnClicked")
        self.assertTrue(clicked, "button click was blocked by HUD overlay")

    async def test_install_survives_navigation(self) -> None:
        """v0.3.7 missed this: addInitScript runs on every
        navigation, so a page.goto() after install() should still
        leave the listener active. This is the whole point of using
        addInitScript instead of page.evaluate."""
        # Navigate to a different page (same file but reload)
        await self._page.goto(self._tmp_path.as_uri())
        # The listener should still be active; dispatch a mousemove
        # and check state.cx/cy updated.
        await self._page.evaluate("""
            () => document.dispatchEvent(new MouseEvent('mousemove',
                { clientX: 333, clientY: 444, bubbles: true }))
        """)
        state = await self._page.evaluate("""
            () => ({ cx: window.__recHud.cx, cy: window.__recHud.cy })
        """)
        self.assertEqual(state["cx"], 333, "listener did not survive navigation")
        self.assertEqual(state["cy"], 444, "listener did not survive navigation")

    async def test_cursor_has_css_transition(self) -> None:
        """v0.3.9: the cursor overlay must have a CSS `transition`
        so that successive setCursorPos() calls are visually
        interpolated by the GPU, not snap-instant. Without this
        the cursor teleports on every mousemove and looks robotic.
        """
        css = await self._page.evaluate(
            "() => { const e = document.getElementById('__rec_cursor__');"
            "        return e ? getComputedStyle(e).transition : null; }"
        )
        self.assertIsNotNone(css, "cursor element missing after inject")
        # `transform` must appear in the transition property so the
        # GPU interpolates position changes.
        self.assertIn("transform", css,
                      f"cursor missing transform transition: {css!r}")

    async def test_cursor_starts_hidden_until_first_mousemove(self) -> None:
        """v0.3.9: the cursor is opacity:0 by default. It only
        becomes visible on the first real mousemove. This is what
        prevents the 'ghost cursor at 50%/50%' on a freshly-loaded
        page."""
        opacity = await self._page.evaluate(
            "() => getComputedStyle(document.getElementById('__rec_cursor__')).opacity"
        )
        self.assertEqual(float(opacity), 0.0,
                         f"cursor should start hidden, got opacity={opacity}")
        # Now fire a mousemove — it should reveal.
        await self._page.evaluate(
            """() => document.dispatchEvent(new MouseEvent('mousemove',
                   { clientX: 100, clientY: 100, bubbles: true }))"""
        )
        # Give the CSS transition a tick to settle.
        await self._page.wait_for_timeout(250)
        opacity = await self._page.evaluate(
            "() => getComputedStyle(document.getElementById('__rec_cursor__')).opacity"
        )
        self.assertEqual(float(opacity), 1.0,
                         f"cursor should be visible after mousemove, got opacity={opacity}")

    async def test_pagehide_hides_cursor_and_clears_ripples(self) -> None:
        """v0.3.9: when the page is about to navigate away, the
        cursor should fade out and any in-flight ripples should be
        removed. This is what prevents a click ripple from
        appearing in empty space on the next page."""
        # Make the cursor visible first.
        await self._page.evaluate(
            """() => document.dispatchEvent(new MouseEvent('mousemove',
                   { clientX: 200, clientY: 200, bubbles: true }))"""
        )
        await self._page.wait_for_timeout(250)
        # Add a ripple (simulate a click).
        await self._page.evaluate(
            """() => document.dispatchEvent(new MouseEvent('mousedown',
                   { clientX: 200, clientY: 200, bubbles: true }))"""
        )
        # Fire pagehide (about to navigate).
        await self._page.evaluate(
            """() => window.dispatchEvent(new Event('pagehide'))"""
        )
        # Wait for the CSS opacity transition (0.2s) to complete.
        await self._page.wait_for_timeout(300)
        # Cursor should now be hidden.
        opacity = await self._page.evaluate(
            """() => parseFloat(getComputedStyle(
                   document.getElementById('__rec_cursor__')).opacity)"""
        )
        self.assertEqual(opacity, 0.0,
                         f"cursor should hide on pagehide, got opacity={opacity}")
        # Ripples should be cleared.
        ripple_count = await self._page.evaluate(
            """() => document.querySelectorAll('.__rec_ripple__').length"""
        )
        self.assertEqual(ripple_count, 0,
                         f"ripples should be cleared on pagehide, got {ripple_count}")

    async def test_listener_tracks_pagehide_and_pageshow(self) -> None:
        """v0.3.9: the addInitScript listener must register
        pagehide + pageshow listeners so the DOM injector can
        hide/reveal the cursor on navigation."""
        has_pagehide = await self._page.evaluate(
            """() => {
              // Fire a pagehide and check the state flag was set.
              window.dispatchEvent(new Event('pagehide'));
              return window.__recHud.navInFlight === true;
            }"""
        )
        self.assertTrue(has_pagehide,
                        "listener should set navInFlight=true on pagehide")

    async def test_ripple_is_blue_not_red(self) -> None:
        """v0.3.9: ripple color was changed from red to blue
        (matches the cursor ring + typical app button accent).
        Red is 'error' territory; blue is 'action here'."""
        # Trigger a mousedown and check the ripple's border color.
        await self._page.evaluate(
            """() => document.dispatchEvent(new MouseEvent('mousedown',
                   { clientX: 300, clientY: 300, bubbles: true }))"""
        )
        # Get the computed border-color of the ripple. (May take a
        # tick for the element to be appended.)
        await self._page.wait_for_timeout(50)
        border = await self._page.evaluate(
            """() => {
              const r = document.querySelector('.__rec_ripple__');
              return r ? getComputedStyle(r).borderColor : null;
            }"""
        )
        self.assertIsNotNone(border, "ripple not created on mousedown")
        # Should be a blue-ish color, not red. The exact RGB may
        # vary, but blue's red component should be < 100.
        # Parse 'rgb(R, G, B)' or 'rgba(R, G, B, A)'.
        import re
        m = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", border)
        self.assertIsNotNone(m, f"could not parse border color: {border!r}")
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        self.assertLess(r, 100, f"ripple should be blue (low R), got R={r}")
        self.assertGreater(b, 100, f"ripple should be blue (high B), got B={b}")

    async def test_cursor_idle_fades_after_no_movement(self) -> None:
        """v0.3.9: the cursor should fade to opacity 0 after
        ~700ms of no mousemove. This is what handles the
        'cursor floats in empty space after a page transition'
        case: Playwright headless doesn't fire mousemove after
        navigation, so the cursor naturally fades if no real
        action happens within 700ms."""
        # Reveal the cursor with a mousemove.
        await self._page.evaluate(
            """() => document.dispatchEvent(new MouseEvent('mousemove',
                   { clientX: 100, clientY: 100, bubbles: true }))"""
        )
        # Wait for CSS opacity transition (0.2s) to complete.
        await self._page.wait_for_timeout(300)
        opacity = await self._page.evaluate(
            """() => parseFloat(getComputedStyle(
                   document.getElementById('__rec_cursor__')).opacity)"""
        )
        self.assertEqual(opacity, 1.0, f"cursor should be visible after mousemove, got {opacity}")
        # Wait > 700ms (idle fade threshold) + 200ms (CSS transition).
        await self._page.wait_for_timeout(1000)
        opacity = await self._page.evaluate(
            """() => parseFloat(getComputedStyle(
                   document.getElementById('__rec_cursor__')).opacity)"""
        )
        self.assertEqual(opacity, 0.0,
                         f"cursor should fade after idle, got {opacity}")

    async def test_mousemove_resets_idle_fade_timer(self) -> None:
        """v0.3.9: every mousemove should reset the idle-fade
        timer, so a cursor that's actively moving stays visible.
        A cursor that's been still for >700ms should hide."""
        # Fire mousemove every 200ms for 1.5s — timer keeps resetting,
        # cursor should stay visible the whole time.
        for _ in range(7):
            await self._page.evaluate(
                """() => document.dispatchEvent(new MouseEvent('mousemove',
                       { clientX: 100 + Math.random() * 10,
                         clientY: 100 + Math.random() * 10,
                         bubbles: true }))"""
            )
            await self._page.wait_for_timeout(200)
        opacity = await self._page.evaluate(
            """() => parseFloat(getComputedStyle(
                   document.getElementById('__rec_cursor__')).opacity)"""
        )
        self.assertEqual(opacity, 1.0,
                         f"cursor should stay visible while moving, got {opacity}")


class TestCursorModuleShape(unittest.TestCase):
    """Static checks on the cursor module — run without a browser."""

    def test_module_exports_expected_functions(self) -> None:
        from recorder_plugin import cursor as c
        for name in ("install", "inject_overlay", "remove_overlay",
                     "inject_cursor", "remove_cursor", "start_tracking",
                     "stop_tracking", "get_trail"):
            fn = getattr(c, name, None)
            self.assertIsNotNone(fn, f"cursor.{name} is missing")
            self.assertTrue(
                inspect.iscoroutinefunction(fn),
                f"cursor.{name} should be a coroutine function",
            )

    def test_listener_uses_addinit_compatible_pattern(self) -> None:
        """The listener JS must be self-contained (a function that
        runs immediately) and must NOT touch the DOM at script-
        load time. This is what makes it safe to register via
        addInitScript (which runs before <body> exists)."""
        from recorder_plugin import cursor as c
        self.assertIn("__recHudInstalled", c.LISTENER_JS,
                      "listener should guard against re-install")
        self.assertNotIn("document.body", c.LISTENER_JS,
                         "listener must not touch document.body")

    def test_injector_creates_known_element_ids(self) -> None:
        """The injector JS must create the elements that the
        SKILL.md and CHANGELOG describe."""
        from recorder_plugin import cursor as c
        for expected_id in ("__rec_hud_host__", "__rec_cursor__",
                            "__rec_keys__"):
            self.assertIn(expected_id, c.INJECTOR_JS,
                          f"injector missing {expected_id}")


if __name__ == "__main__":
    unittest.main()
