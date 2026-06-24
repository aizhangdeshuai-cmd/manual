"""v0.3.7: inject a visible cursor overlay into the recorded page.

Why we need this:
  Playwright's `recordVideo` records the page DOM, not the OS cursor.
  In headless mode there is no real OS cursor to render. Without an
  in-page cursor, the recorded video shows clicks happening "out of
  nowhere" — the user sees a button change state but no pointer
  arriving at it. That's the difference between "looks like a demo"
  and "looks like a real person using the app".

What this module does:
  - inject_cursor(page): append a fixed-position <div id="__rec_cursor__">
    to the page, containing an SVG arrow. The element has
    `pointer-events: none` so it never blocks real clicks/typing.
  - move_cursor(page, x, y): update the overlay's left/top to track
    the mouse. Cheap — sets two CSS properties via DOM.
  - start_tracking(page): install a `mousemove` listener on the page
    that records positions into window.__recCursorTrail (a list of
    {x,y,t}). Used by the recorder's click handler so the cursor
    moves naturally between actions (not just teleporting on click).
  - stop_tracking(page) / remove_cursor(page): cleanup.

The arrow SVG is a standard 14×20px mouse pointer (white outline +
black fill), large enough to be visible at 100% but not so large it
covers the element being clicked.

Concurrency note: all functions are async (page.evaluate is async).
They never block the event loop more than a few ms; the overlay's
position is updated via direct DOM property writes, not React/Vue
state, so it doesn't trigger app re-renders.
"""
from __future__ import annotations
import logging
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


CURSOR_ID = "__rec_cursor__"
CURSOR_TRAIL_KEY = "__recCursorTrail"
CURSOR_X_KEY = "__lastMouseX"
CURSOR_Y_KEY = "__lastMouseY"

# Standard mouse-pointer SVG. White outline + black fill so it's
# visible on both light and dark backgrounds. Sized 14x20 to match
# what the OS cursor looks like at 100% DPI.
CURSOR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="20" '
    'viewBox="0 0 14 20" fill="none">'
    '<path d="M0 0 L0 16 L4 12 L6.5 18 L9 17 L6.5 11 L11 11 Z" '
    'fill="black" stroke="white" stroke-width="1" stroke-linejoin="round"/>'
    '</svg>'
)


_INJECT_JS = f"""
() => {{
  // Remove any pre-existing overlay (idempotent re-injection).
  const existing = document.getElementById({CURSOR_ID!r});
  if (existing) existing.remove();

  const div = document.createElement('div');
  div.id = {CURSOR_ID!r};
  div.style.cssText = [
    'position: fixed',
    'left: 50%',
    'top: 50%',
    'width: 14px',
    'height: 20px',
    'pointer-events: none',
    'z-index: 2147483647',  // max int — overlay every app element
    'transform: translate(-1px, -1px)',
    'transition: none',     // no smoothing — direct mouse tracking
    'will-change: transform',
  ].join('; ');
  div.innerHTML = {CURSOR_SVG!r};
  document.body.appendChild(div);

  // Initialize trail buffer; recorder's click handler reads it.
  if (!window.{CURSOR_TRAIL_KEY}) {{
    window.{CURSOR_TRAIL_KEY} = [];
  }}
  return true;
}}
"""


_REMOVE_JS = f"""
() => {{
  const el = document.getElementById({CURSOR_ID!r});
  if (el) el.remove();
  return true;
}}
"""


_MOVE_JS = f"""
({{x, y}}) => {{
  // Playwright's page.evaluate() takes a single argument. We
  // destructure {{x, y}} so callers can pass a plain dict.
  const el = document.getElementById({CURSOR_ID!r});
  if (!el) return false;
  el.style.left = x + 'px';
  el.style.top = y + 'px';
  window.{CURSOR_X_KEY} = x;
  window.{CURSOR_Y_KEY} = y;
  window.{CURSOR_TRAIL_KEY} = window.{CURSOR_TRAIL_KEY} || [];
  window.{CURSOR_TRAIL_KEY}.push({{x, y, t: performance.now()}});
  return true;
}}
"""


_START_TRACK_JS = f"""
() => {{
  // Record ALL mouse moves on the page. Playwright dispatches its
  // page.mouse.move() as real DOM mousemove events, so this listener
  // captures them without us having to wrap every move call.
  if (window.__recCursorTrackInstalled) return false;
  window.__recCursorTrackInstalled = true;
  const handler = (ev) => {{
    const x = ev.clientX, y = ev.clientY;
    window.{CURSOR_X_KEY} = x;
    window.{CURSOR_Y_KEY} = y;
    (window.{CURSOR_TRAIL_KEY} = window.{CURSOR_TRAIL_KEY} || []).push(
      {{x, y, t: performance.now()}}
    );
  }};
  // Capture phase so we get moves even on elements that stop propagation.
  document.addEventListener('mousemove', handler, true);
  window.__recCursorTrackHandler = handler;
  return true;
}}
"""


_STOP_TRACK_JS = f"""
() => {{
  if (!window.__recCursorTrackInstalled) return false;
  const h = window.__recCursorTrackHandler;
  if (h) document.removeEventListener('mousemove', h, true);
  window.__recCursorTrackInstalled = false;
  return true;
}}
"""


async def inject_cursor(page: Page) -> None:
    """Append the cursor overlay <div> to the page body.

    Idempotent: re-injecting removes the old overlay first.
    Safe to call before the page is fully loaded — the overlay
    lives in <body>, so if <body> doesn't exist yet, the call
    just no-ops (the overlay will be injected on the next navigate).
    """
    try:
        await page.evaluate(_INJECT_JS)
    except Exception as e:
        # Don't crash the whole recording just because cursor failed.
        # Logged at warning level so the agent can see why some
        # videos don't have a cursor.
        logger.warning("inject_cursor failed: %s", e)


async def remove_cursor(page: Page) -> None:
    """Remove the cursor overlay and stop tracking. Idempotent."""
    try:
        await page.evaluate(_REMOVE_JS)
    except Exception as e:
        logger.warning("remove_cursor failed: %s", e)


async def move_cursor(page: Page, x: float, y: float) -> None:
    """Update the cursor overlay's position.

    Cheap: one DOM property write + push to a JS array. Safe to
    call on every mousemove event without blocking the recorder.
    """
    try:
        # Playwright's page.evaluate() takes exactly one arg, so
        # we pass {x, y} as a dict and let the JS destructure.
        await page.evaluate(_MOVE_JS, {"x": x, "y": y})
    except Exception:
        # If the page navigated or closed mid-call, swallow — the
        # next call will re-anchor.
        pass


async def start_tracking(page: Page) -> None:
    """Install a global mousemove listener that updates __lastMouseX/Y.

    This is what lets the cursor follow the mouse even between
    recorder-emitted actions (page.mouse.move in click handler).
    Without it the cursor would only update on the explicit
    move_cursor() calls and would not follow the trail.
    """
    try:
        await page.evaluate(_START_TRACK_JS)
    except Exception as e:
        logger.warning("start_tracking failed: %s", e)


async def stop_tracking(page: Page) -> None:
    """Remove the mousemove listener. Idempotent."""
    try:
        await page.evaluate(_STOP_TRACK_JS)
    except Exception as e:
        logger.warning("stop_tracking failed: %s", e)


async def get_trail(page: Page) -> list[dict[str, Any]]:
    """Read the recorded mouse trail (list of {x, y, t} dicts).

    Used by debug tooling; the recorder doesn't read it back. Useful
    for unit tests that want to verify the listener fires.
    """
    try:
        return await page.evaluate(f"() => window.{CURSOR_TRAIL_KEY} || []")
    except Exception:
        return []
