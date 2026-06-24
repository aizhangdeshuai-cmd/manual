"""v0.3.9: human-looking cursor overlay (CSS transition + idle fade + nav-hide).

The v0.3.8 cursor was visible but it had five "demo" tells that made
the video look robotic instead of recorded:

  1. Cursor teleported on every mousemove — no interpolation between
     positions, just `transform: translate(x,y)` snap to new spot.
  2. Cursor stayed visible at its last-known position after a page
     navigation, so it appeared to "float" in empty areas of the
     new page (Playwright headless doesn't fire mousemove after
     navigation, so the cursor element kept its old coords).
  3. Click ripple was red and stayed 500ms in the empty new-page
     area, reinforcing the "ghost cursor" look.
  4. No idle behavior — a frozen cursor at a click point looked
     pasted on, not like someone waiting to see the result.
  5. Keystroke HUD was bottom-center 80vw — wide and intrusive,
     pulled eyes away from the actual demo.

v0.3.9 fixes all five with one mental model: "treat the cursor
like a real user's cursor, not a debug marker."

  - CSS `transition: transform 80ms ease-out` on the cursor. Every
    `mousemove` event still snaps the position, but the GPU
    interpolates between frames so the motion looks smooth, the
    way a real cursor glides.
  - On `pagehide` (just before navigation), fade the cursor to
    opacity 0. On `pageshow` (after new page loads), keep opacity 0
    until the first real mousemove fires — so the cursor reappears
    AT the new mouse position, not at a stale position. No more
    ghost cursor on the new page.
  - Ripple uses a softer blue (`rgba(59,130,246,0.7)`), and the
    `pagehide` handler removes any in-flight ripples too.
  - Cursor gets a 1.4s outer-ring pulse so it feels alive when
    stationary, the way an OS cursor's hover state does.
  - Keystroke HUD moved to bottom-right, narrower (28vw), 60%
    opacity so it supports the demo without dominating.

What this module does:
  1. install(page): addInitScript that runs on every navigation. The
     script attaches mousemove/mousedown/mouseup/keydown/pagehide/
     pageshow listeners that update a state object on window.__recHud.
     The listeners do NOT touch the DOM.
  2. inject_overlay(page): page.evaluate that creates the cursor
     overlay, click-ripple host, and keystroke HUD. Wires them to
     the state via callbacks.
  3. remove_overlay(page): tear down DOM + clear state callbacks.

Pattern source: snomiao/demowright (MIT) for the addInitScript
split. CSS-transition smoothing inspired by tecnomanu/video-docs-builder
(MIT, 2026) which uses the same trick.
"""
from __future__ import annotations
import logging
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


# State key — the listener stores cursor pos + key presses here.
HUD_STATE_KEY = "__recHud"
# Overlay element ids (used for cleanup + debugging).
CURSOR_ID = "__rec_cursor__"
KEYS_ID = "__rec_keys__"
RIPPLE_HOST_ID = "__rec_ripples__"
HOST_ID = "__rec_hud_host__"


# --- The listener script (registered via addInitScript) --------------------
#
# Runs in EVERY new document/frame, before <body> exists. Just records
# the latest cursor position + recent key presses + page transition
# signals; does NOT touch the DOM.
# The DOM injector (page.evaluate) wires these state values to visible
# elements by setting the onXxx callbacks.
# Playwright's add_init_script wraps the script in an IIFE
# automatically — we pass PLAIN STATEMENTS here, not a function
# expression. (If we wrap in `() => { ... }`, add_init_script
# double-wraps and the inner arrow function never runs.)
LISTENER_JS = r"""
if (window.__recHudInstalled) {} else {
  window.__recHudInstalled = true;
  var __recModifierKeys = new Set(['Shift', 'Control', 'Alt', 'Meta', 'CapsLock']);
  var __recState = (window.__recHud = window.__recHud || {
    cx: -40, cy: -40,
    keys: [],
    // v0.3.9: nav signal — true while a navigation is in flight. DOM
    // injector reads this to hide the cursor until the new page fires
    // its first mousemove. Defaults to false on first page.
    navInFlight: false,
    onCursorMove: null,
    onMouseDown: null,
    onMouseUp: null,
    onKeyDown: null,
    onPageHide: null,
    onPageShow: null,
  });
  function __recFormatKey(e) {
    if (__recModifierKeys.has(e.key)) return e.key;
    var parts = [];
    if (e.ctrlKey) parts.push('Ctrl');
    if (e.altKey) parts.push('Alt');
    if (e.shiftKey) parts.push('Shift');
    if (e.metaKey) parts.push('Meta');
    var k = e.key;
    if (k === ' ') k = 'Space';
    parts.push(k);
    return parts.join('+');
  }
  document.addEventListener('mousemove', function(e) {
    __recState.cx = e.clientX;
    __recState.cy = e.clientY;
    if (__recState.onCursorMove) __recState.onCursorMove(e.clientX, e.clientY);
  }, true);
  // v0.3.9: programmatic move. _handle_click / _handle_type call
  // this right before the real action, dispatching a synthetic
  // mousemove so the existing listener pipeline updates the cursor
  // overlay to the new position. Crucially, this re-triggers the
  // nav-aware visibility logic (the cursor is shown on the first
  // real mousemove of a page), so even after a SPA route change
  // the cursor reappears at the action target, not at some stale
  // position from a previous page.
  window.__recMoveCursorTo = function(x, y) {
    document.dispatchEvent(new MouseEvent('mousemove', {
      clientX: x, clientY: y, bubbles: true,
    }));
  };
  document.addEventListener('mousedown', function(e) {
    if (__recState.onMouseDown) __recState.onMouseDown(e.clientX, e.clientY);
  }, true);
  document.addEventListener('mouseup', function() {
    if (__recState.onMouseUp) __recState.onMouseUp();
  }, true);
  document.addEventListener('keydown', function(e) {
    var label = __recFormatKey(e);
    if (__recModifierKeys.has(e.key)) return;
    __recState.keys.push({label, t: performance.now()});
    if (__recState.keys.length > 20) __recState.keys.shift();
    if (__recState.onKeyDown) __recState.onKeyDown(label);
  }, true);
  // v0.3.9: pagehide/pageshow for nav-aware cursor visibility.
  // pagehide fires when the browser is about to navigate away; we
  // set the flag so the DOM injector (still in the old page) can
  // fade the cursor out. The new page won't fire pagehide on load;
  // it fires pageshow — at which point the cursor is still hidden
  // (state.navInFlight is true). The first mousemove on the new
  // page clears the flag and the cursor reappears AT that position,
  // not the old one.
  window.addEventListener('pagehide', function() {
    __recState.navInFlight = true;
    if (__recState.onPageHide) __recState.onPageHide();
  }, true);
  window.addEventListener('pageshow', function() {
    if (__recState.onPageShow) __recState.onPageShow();
  }, true);
}
"""


# --- The DOM injector (called via page.evaluate) ---------------------------
#
# Creates the visible HUD elements and wires them to state callbacks.
# Idempotent: skips if host element already exists.
# v0.3.9 changes:
#   - cursor uses CSS transition for smooth motion
#   - cursor is hidden on pagehide, shown on first mousemove of new page
#   - ripple is blue, not red
#   - keystroke HUD is bottom-right, narrower, 60% opacity
#   - cursor gets an outer ring that pulses every 1.4s (idle "alive" cue)
INJECTOR_JS = r"""
() => {
  if (document.getElementById('__rec_hud_host__')) return false;
  const state = window.__recHud;
  if (!state) return false;
  const KEY_FADE_MS = 1500;

  // Host container — high z-index, pointer-events:none so we
  // never block real interactions. Everything HUD-related lives
  // under this single root so cleanup is one removeChild.
  const host = document.createElement('div');
  host.id = '__rec_hud_host__';
  host.style.cssText = [
    'position: fixed',
    'top: 0', 'left: 0',
    'width: 0', 'height: 0',
    'z-index: 2147483647',
    'pointer-events: none',
  ].join('; ');
  document.body.appendChild(host);

  // Style sheet — drop-shadow on the cursor, fade-out keyframes for
  // keystrokes, scale animation for click ripples. v0.3.9: cursor
  // uses CSS transition so mousemove snaps feel like smooth motion;
  // outer ring pulses to feel "alive" when stationary.
  const style = document.createElement('style');
  style.textContent = `
    /* v0.3.9: cursor SVG with CSS transition for smooth motion. */
    #__rec_cursor__ {
      position: fixed; top: 0; left: 0;
      width: 14px; height: 20px;
      pointer-events: none;
      transform: translate(-40px, -40px);
      will-change: transform, opacity;
      /* The transition is what makes cursor motion look smooth
         instead of teleporting. 80ms is the "OS cursor glide" feel —
         long enough to interpolate, short enough to not lag. */
      transition: transform 0.08s ease-out, opacity 0.2s ease-out;
      opacity: 0;
      filter: drop-shadow(1px 1px 1px rgba(0,0,0,0.4));
    }
    #__rec_cursor__.rec-visible {
      opacity: 1;
    }
    #__rec_cursor__.rec-clicking {
      transform-origin: 0 0;
    }
    /* v0.3.9: outer ring around the cursor with a slow pulse, so
       when the cursor is stationary (e.g. waiting on a form
       submit) the user still sees "the cursor is here, alive". */
    #__rec_cursor_ring__ {
      position: fixed; top: 0; left: 0;
      width: 26px; height: 26px;
      margin-left: -6px; margin-top: -6px;
      border-radius: 50%;
      border: 1.5px solid rgba(59, 130, 246, 0.35);
      pointer-events: none;
      transform: translate(-40px, -40px);
      will-change: transform, opacity;
      transition: transform 0.12s ease-out, opacity 0.2s ease-out;
      opacity: 0;
      animation: __rec_ring_pulse__ 1.8s ease-in-out infinite;
    }
    #__rec_cursor_ring__.rec-visible {
      opacity: 1;
    }
    @keyframes __rec_ring_pulse__ {
      0%   { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.25); }
      70%  { box-shadow: 0 0 0 6px rgba(59, 130, 246, 0); }
      100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0); }
    }
    /* v0.3.9: ripple is blue (matches the cursor ring + app button
       accent), not red. Red is "error" territory; blue says "tap
       here, this is the action". */
    .__rec_ripple__ {
      position: fixed; width: 18px; height: 18px;
      margin-left: -9px; margin-top: -9px;
      border-radius: 50%;
      border: 2px solid rgba(59, 130, 246, 0.7);
      pointer-events: none;
      animation: __rec_ripple_anim__ 0.45s ease-out forwards;
    }
    @keyframes __rec_ripple_anim__ {
      0%   { transform: scale(0.4); opacity: 0.9; }
      100% { transform: scale(2.8); opacity: 0; }
    }
    /* v0.3.9: keystroke HUD moved to bottom-right and made smaller +
       60% opacity. Bottom-center was intrusive and pulled eyes away
       from the demo. Bottom-right is where most apps' "toast"
       notifications live, so the eye learns to glance there for
       supporting info without it being the focal point. */
    #__rec_keys__ {
      position: fixed; bottom: 14px; right: 14px;
      display: flex; gap: 4px; flex-wrap: wrap;
      justify-content: flex-end; max-width: 28vw;
      pointer-events: none;
      opacity: 0.85;
    }
    .__rec_key__ {
      background: rgba(0,0,0,0.72);
      color: #fff;
      font: 11px/1 ui-monospace, "SF Mono", Menlo, monospace;
      padding: 3px 6px;
      border-radius: 4px;
      border: 1px solid rgba(255,255,255,0.18);
      box-shadow: 0 1px 3px rgba(0,0,0,0.35);
      animation: __rec_key_fade__ 1.5s ease-out forwards;
    }
    @keyframes __rec_key_fade__ {
      0%   { opacity: 1; transform: translateY(0); }
      70%  { opacity: 1; transform: translateY(0); }
      100% { opacity: 0; transform: translateY(-6px); }
    }
  `;
  host.appendChild(style);

  // --- Cursor overlay (the arrow) ---
  const cursor = document.createElement('div');
  cursor.id = '__rec_cursor__';
  // Standard mouse pointer SVG, white outline + black fill so it
  // shows on both light and dark backgrounds.
  cursor.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="20" viewBox="0 0 14 20" fill="none">'
    + '<path d="M0 0 L0 16 L4 12 L6.5 18 L9 17 L6.5 11 L11 11 Z" fill="black" stroke="white" stroke-width="1" stroke-linejoin="round"/>'
    + '</svg>';
  host.appendChild(cursor);

  // v0.3.9: outer pulse ring — sits 6px behind the cursor tip and
  // pulses every 1.8s. Makes a stationary cursor feel "alive" so
  // the viewer doesn't think the recording froze.
  const ring = document.createElement('div');
  ring.id = '__rec_cursor_ring__';
  host.appendChild(ring);

  // --- Click ripple host ---
  const rippleHost = document.createElement('div');
  rippleHost.id = '__rec_ripples__';
  host.appendChild(rippleHost);

  // --- Keystroke HUD ---
  const keys = document.createElement('div');
  keys.id = '__rec_keys__';
  host.appendChild(keys);

  // Wire state callbacks. Each callback is a closure that captures
  // the elements above. Setting onXxx = null on teardown will
  // stop the listener from invoking them.
  function setCursorPos(x, y) {
    // Apply both arrow + ring in lockstep. The CSS transition
    // (0.08s on the arrow, 0.12s on the ring) interpolates between
    // successive setCursorPos calls, producing the "glide" effect.
    cursor.style.transform = 'translate(' + x + 'px,' + y + 'px)';
    ring.style.transform = 'translate(' + x + 'px,' + y + 'px)';
  }
  setCursorPos(state.cx, state.cy);

  // v0.3.9: visibility gating. Cursor is hidden by default
  // (opacity: 0 in CSS). It shows on the FIRST mousemove of the
  // page session. On pagehide (about to navigate) we hide it
  // again. The new page re-shows on its first mousemove — which
  // is the right behavior because Playwright's headless doesn't
  // fire a mousemove after navigation, so we have to wait for a
  // real one.
  let isVisible = false;
  function showCursor() {
    if (isVisible) return;
    isVisible = true;
    cursor.classList.add('rec-visible');
    ring.classList.add('rec-visible');
  }
  function hideCursor() {
    isVisible = false;
    cursor.classList.remove('rec-visible');
    ring.classList.remove('rec-visible');
  }

  // v0.3.9: idle-fade timer. Resets on every mousemove; fires
  // after IDLE_FADE_MS of stillness. Hides the cursor so the
  // viewer doesn't see a "ghost" cursor in empty space (e.g.
  // between page transitions, or during a slow wait_for).
  const IDLE_FADE_MS = 700;
  let idleTimer = null;
  function clearIdleFade() {
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
  }
  function scheduleIdleFade() {
    clearIdleFade();
    idleTimer = setTimeout(() => { hideCursor(); idleTimer = null; },
                           IDLE_FADE_MS);
  }

  state.onCursorMove = (x, y) => {
    setCursorPos(x, y);
    showCursor();
    scheduleIdleFade();
  };

  state.onMouseDown = (x, y) => {
    cursor.classList.add('rec-clicking');
    const r = document.createElement('div');
    r.className = '__rec_ripple__';
    r.style.left = x + 'px';
    r.style.top = y + 'px';
    rippleHost.appendChild(r);
    // Auto-clean ripple after animation finishes.
    setTimeout(() => r.remove(), 500);
  };
  state.onMouseUp = () => { cursor.classList.remove('rec-clicking'); };

  state.onKeyDown = (label) => {
    const chip = document.createElement('span');
    chip.className = '__rec_key__';
    chip.textContent = label;
    keys.appendChild(chip);
    setTimeout(() => chip.remove(), KEY_FADE_MS + 100);
  };

  // v0.3.9: nav-aware visibility. pagehide (about to navigate)
  // hides the cursor and clears any in-flight ripples so they
  // don't appear in the new page's empty area. pageshow (new
  // page loaded) keeps it hidden until first mousemove fires.
  state.onPageHide = () => {
    clearIdleFade();
    hideCursor();
    // Clear any ripples that were mid-animation so they don't
    // appear in the new page's empty area.
    while (rippleHost.firstChild) rippleHost.firstChild.remove();
  };
  state.onPageShow = () => {
    clearIdleFade();
    // Stay hidden — will show on next mousemove callback.
    hideCursor();
  };

  // If we landed here via a navigation (state.navInFlight was set
  // by the old page's pagehide listener), we already started
  // hidden, so the first mousemove on this page will reveal us at
  // the right position. No additional work needed.

  return true;
}
"""


# --- The teardown script ---------------------------------------------------
REMOVE_JS = r"""
() => {
  const host = document.getElementById('__rec_hud_host__');
  if (host) host.remove();
  // Clear callbacks so a later inject gets a clean state.
  const state = window.__recHud;
  if (state) {
    state.onCursorMove = null;
    state.onMouseDown = null;
    state.onMouseUp = null;
    state.onKeyDown = null;
    state.onPageHide = null;
    state.onPageShow = null;
  }
  return true;
}
"""


async def install(page: Page) -> None:
    """Register the mousemove/mousedown/keydown/pagehide/pageshow
    listener via addInitScript. Safe to call BEFORE any navigation —
    the listener will be active in every new document from the moment
    addInitScript registers it. Idempotent."""
    try:
        await page.add_init_script(LISTENER_JS)
    except Exception as e:
        logger.warning("install (addInitScript) failed: %s", e)


async def inject_overlay(page: Page) -> None:
    """Create the HUD DOM elements (cursor, click ripple host, key HUD)
    and wire them to the listener's state callbacks. Must be called
    AFTER at least one navigation has happened (so document.body
    exists). Idempotent: re-injecting is a no-op."""
    try:
        await page.evaluate(INJECTOR_JS)
    except Exception as e:
        # Don't crash recording on HUD failure — just log.
        logger.warning("inject_overlay failed: %s", e)


async def remove_overlay(page: Page) -> None:
    """Tear down the HUD. Clears state callbacks too so a later
    inject (e.g. next video_start) starts clean."""
    try:
        await page.evaluate(REMOVE_JS)
    except Exception as e:
        logger.warning("remove_overlay failed: %s", e)


# Backwards-compat aliases — old v0.3.7 callers used these names.
# New code should use inject_overlay / remove_overlay.
async def inject_cursor(page: Page) -> None:
    """Deprecated: use inject_overlay()."""
    await inject_overlay(page)


async def remove_cursor(page: Page) -> None:
    """Deprecated: use remove_overlay()."""
    await remove_overlay(page)


async def start_tracking(page: Page) -> None:
    """Deprecated alias — in v0.3.8+ tracking is started by install()
    via addInitScript. This function is a no-op kept for API compat."""
    return


async def stop_tracking(page: Page) -> None:
    """Deprecated alias — see start_tracking."""
    return


async def get_trail(page: Page) -> list[dict[str, Any]]:
    """No-op kept for API compat. The listener still records
    positions into state.cx/cy but we don't expose the full
    trail (was unused by the recorder)."""
    try:
        state = await page.evaluate("() => ({x: window.__recHud?.cx, y: window.__recHud?.cy})")
        return [state] if state and state.get("x") is not None else []
    except Exception:
        return []
