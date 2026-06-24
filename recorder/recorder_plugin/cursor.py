"""v0.3.8: visible cursor + keystroke badges + click ripples in recorded video.

Why we need this:
  Playwright's `recordVideo` captures the page DOM, not the OS cursor.
  In headless mode there is no OS cursor to render, so the recorded
  webm shows clicks happening "out of nowhere". Without visual feedback,
  the user can't tell what was clicked or what was typed.

What this module does:
  1. install(page): addInitScript that runs on every navigation. The
     script attaches mousemove/mousedown/mouseup/keydown listeners
     that update a state object on window.__recHud. The listeners
     do NOT touch the DOM — they're safe to run before <body> exists.
  2. inject_overlay(page): page.evaluate that creates the cursor
     overlay <div>, a click-ripple element, and a keyboard HUD
     element. Wires the elements to the state via callbacks:
        state.onCursorMove = (x,y) => { cursor.style.transform = ... }
        state.onMouseDown   = (x,y) => { cursor click ripple }
        state.onKeyDown     = (label) => { show key chip }
  3. remove_overlay(page): tear down DOM + clear state callbacks.

Pattern source: snomiao/demowright (MIT) — uses the same
addInitScript + callback-wired DOM injector split. We credit
demowright in SKILL.md because the architectural pattern is
their original work.

Differences from demowright:
  - We use left/top (CSS pixel) not transform translate, because
    the recorder's click handler reads `window.__lastMouseX/Y`
    (already in client coords) and we want minimal JS — the
    pointer-events: none overlay can use either.
  - We don't support auto-slowdown, TTS, SRT — those are
    out of scope for the user-manual skill (the skill has its
    own TTS via edge-tts, see mux_audio.py).
  - We DO add keystroke badges because the user asked for
    smoother comprehension — seeing the keys being typed
    reinforces what the user should type.

Failure modes are non-fatal: install/inject exceptions are
swallowed and the recorder continues. The video records
without HUD instead of crashing the run.
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
# the latest cursor position + recent key presses; does NOT touch the DOM.
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
    onCursorMove: null,
    onMouseDown: null,
    onMouseUp: null,
    onKeyDown: null,
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
}
"""


# --- The DOM injector (called via page.evaluate) ---------------------------
#
# Creates the visible HUD elements and wires them to state callbacks.
# Idempotent: skips if host element already exists.
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
  // keystrokes, scale animation for click ripples.
  const style = document.createElement('style');
  style.textContent = `
    #__rec_cursor__ {
      position: fixed; top: 0; left: 0;
      width: 14px; height: 20px;
      pointer-events: none;
      transform: translate(-40px, -40px);
      will-change: transform;
      filter: drop-shadow(1px 1px 1px rgba(0,0,0,0.4));
    }
    #__rec_cursor__.clicking {
      transform: translate(var(--rec-cursor-x), var(--rec-cursor-y)) scale(0.85);
    }
    .__rec_ripple__ {
      position: fixed; width: 18px; height: 18px;
      margin-left: -9px; margin-top: -9px;
      border-radius: 50%;
      border: 2px solid rgba(255, 80, 80, 0.85);
      pointer-events: none;
      animation: __rec_ripple_anim__ 0.5s ease-out forwards;
    }
    @keyframes __rec_ripple_anim__ {
      0%   { transform: scale(0.4); opacity: 1; }
      100% { transform: scale(3.5); opacity: 0; }
    }
    #__rec_keys__ {
      position: fixed; bottom: 18px; left: 50%;
      transform: translateX(-50%);
      display: flex; gap: 6px; flex-wrap: wrap;
      justify-content: center; max-width: 80vw;
      pointer-events: none;
    }
    .__rec_key__ {
      background: rgba(0,0,0,0.78);
      color: #fff;
      font: 13px/1 ui-monospace, "SF Mono", Menlo, monospace;
      padding: 5px 9px;
      border-radius: 5px;
      border: 1px solid rgba(255,255,255,0.25);
      box-shadow: 0 2px 6px rgba(0,0,0,0.4);
      animation: __rec_key_fade__ 1.5s ease-out forwards;
    }
    @keyframes __rec_key_fade__ {
      0%   { opacity: 1; transform: translateY(0); }
      70%  { opacity: 1; transform: translateY(0); }
      100% { opacity: 0; transform: translateY(-10px); }
    }
  `;
  host.appendChild(style);

  // --- Cursor overlay ---
  const cursor = document.createElement('div');
  cursor.id = '__rec_cursor__';
  // Standard mouse pointer SVG, white outline + black fill so it
  // shows on both light and dark backgrounds.
  cursor.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="20" viewBox="0 0 14 20" fill="none">'
    + '<path d="M0 0 L0 16 L4 12 L6.5 18 L9 17 L6.5 11 L11 11 Z" fill="black" stroke="white" stroke-width="1" stroke-linejoin="round"/>'
    + '</svg>';
  host.appendChild(cursor);

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
    cursor.style.setProperty('--rec-cursor-x', x + 'px');
    cursor.style.setProperty('--rec-cursor-y', y + 'px');
    // For the non-clicking state we still need to update the
    // base transform. We do it via a direct style assignment so
    // the CSS variable trick above only applies during .clicking.
    cursor.style.transform = 'translate(' + x + 'px,' + y + 'px)';
  }
  setCursorPos(state.cx, state.cy);

  state.onCursorMove = (x, y) => { setCursorPos(x, y); };

  state.onMouseDown = (x, y) => {
    cursor.classList.add('clicking');
    const r = document.createElement('div');
    r.className = '__rec_ripple__';
    r.style.left = x + 'px';
    r.style.top = y + 'px';
    rippleHost.appendChild(r);
    // Auto-clean ripple after animation.
    setTimeout(() => r.remove(), 600);
  };
  state.onMouseUp = () => { cursor.classList.remove('clicking'); };

  state.onKeyDown = (label) => {
    const chip = document.createElement('span');
    chip.className = '__rec_key__';
    chip.textContent = label;
    keys.appendChild(chip);
    // Fade out via the CSS animation; remove from DOM after it ends
    // so we don't leak elements.
    setTimeout(() => chip.remove(), KEY_FADE_MS + 100);
  };

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
  }
  return true;
}
"""


async def install(page: Page) -> None:
    """Register the mousemove/mousedown/keydown listener via addInitScript.

    Safe to call BEFORE any navigation — the listener will be active
    in every new document from the moment addInitScript registers it.
    Idempotent: addInitScript + the script's own __recHudInstalled
    guard make repeat calls no-ops.
    """
    try:
        await page.add_init_script(LISTENER_JS)
    except Exception as e:
        logger.warning("install (addInitScript) failed: %s", e)


async def inject_overlay(page: Page) -> None:
    """Create the HUD DOM elements (cursor, click ripple host, key HUD)
    and wire them to the listener's state callbacks.

    Must be called AFTER at least one navigation has happened (so
    document.body exists). Idempotent: re-injecting is a no-op.
    """
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
    """Deprecated alias — in v0.3.8 tracking is started by install()
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
