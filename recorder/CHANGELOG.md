## 0.3.10 (2026-06-24) — frame-accurate trim of leading blank frames

Every recorded video started with 40-300ms of a blank white
frame at the front. To a viewer this read as "the recording
is broken" — the video began with nothing, then the page
appeared. Caused by Playwright's `recordVideo` API starting
recording at context creation, BEFORE the page navigated
and the SPA bundle loaded.

v0.3.10 detects the first content frame (SATAVG > 0.5) and
re-encodes the video starting from there, using ffmpeg's
`trim` video filter (frame-accurate, no keyframe dependency).
The first frame of the trimmed mp4 is guaranteed to be real
content.

### What changed

#### video.py

- **`detect_first_content_timestamp()`** — new. Scans the
  first 2s of a video with ffmpeg `signalstats`, returns
  the timestamp of the first frame whose SATAVG > 0.5.
  Signal: **SATAVG (saturation)**, not YAVG (luminance),
  because the test-app's UI is a near-white background with
  a white card — YAVG of a loaded page (~228) and YAVG of
  a blank white frame (~235) differ by only 7 units. SATAVG
  of a blank frame is exactly 0; SATAVG of any rendered
  page with a colored element is > 0.5.

- **`trim_blank_start()`** — new. Re-encodes the video
  starting from the detected timestamp using
  `trim=start=<ts>,setpts=PTS-STARTPTS`. Iterates up to 3
  passes: after each trim, re-detect; if the new mp4 still
  has a blank keyframe at the start, trim again. In practice
  1-2 passes is enough.

  - **Why the `trim` filter, not `ffmpeg -ss <ts> -i <input>`**:
    `-ss` before `-i` is **fast-seek** — it snaps to the
    nearest keyframe BEFORE the target ts. If that keyframe
    is blank (e.g. the first I-frame is white), the trimmed
    mp4 STILL starts with a blank frame. We hit exactly
    this bug in v0.3.10a: the trim duration dropped, but
    `frame 0` of the trimmed mp4 was still blank. The
    `trim` filter doesn't depend on keyframe placement —
    it decodes through to the target ts and emits the
    content frame as the new first frame.

- **`concat_slices_to_mp4()`** — new param
  `trim_leading_blank: bool = True`. When True (default),
  the concat output is trimmed of leading blank frames
  via `trim_blank_start()`. Renamed from the previous
  `trim_blank_start` because the param name shadowed the
  module-level `trim_blank_start()` function (the param
  bound `True`, then `trim_blank_start(output_mp4)` tried
  to call it and got `TypeError: 'bool' object is not
  callable`). v0.3.10a hit this shadowing bug, fixed in
  this release.

#### tests

- `tests/unit/test_video.py`:
  - `test_trim_blank_start_first_frame_has_content` (new) —
    the regression test. Builds a 1s video that starts with
    0.3s of white, then 0.7s of blue. After `trim_blank_start()`,
    asserts the first frame's SATAVG > 0 (i.e. is the blue
    frame, not a residual white keyframe). This is the test
    that would have caught the v0.3.10a keyframe-seek bug.

- `tests/integration/test_self_test.py`:
  - Bumped hardcoded `0.3.0` to `0.3.10` in
    `test_all_modules_importable` and
    `test_cli_help_and_version` (these asserted the
    package version string was exactly `0.3.0` from
    v0.2.1 days, had been broken since the first version
    bump that wasn't followed up).

## 0.3.9 (2026-06-24) — human-looking cursor: smooth motion, idle-fade, nav-aware

The v0.3.8 cursor was visible but had five "demo" tells that
made the video look robotic instead of recorded:

1. **Cursor teleported on every mousemove** — every
   `setCursorPos()` was a snap from old to new with no
   interpolation. The eye reads this as "machine, not person".
2. **Cursor stayed visible after page navigation** — at the
   last position from the old page. With Playwright headless
   never firing `mousemove` after navigation, the cursor
   element kept its old coords and the new page's empty area
   had a "ghost cursor" floating in the middle.
3. **Click ripple stayed red and visible** in the new page's
   empty space (because the ripple was tied to viewport
   coords, not the new page's content).
4. **No idle behavior** — a frozen cursor at a click point
   looked pasted on, not like someone waiting to see a
   result.
5. **Keystroke HUD was bottom-center 80vw** — wide and
   intrusive, pulled eyes away from the actual demo.

v0.3.9 fixes all five with one mental model: "treat the
cursor like a real user's cursor, not a debug marker."

### What changed

#### cursor.py — the core fix

- **CSS transition on the cursor**: `transition: transform
  0.08s ease-out`. Every successive `setCursorPos()` still
  snaps the position, but the GPU interpolates between
  frames so the motion looks smooth — the way a real OS
  cursor glides across the screen.
- **Visibility gating**: cursor is `opacity: 0` by default.
  It reveals on the first `mousemove` of the page session.
  On `pagehide` (about to navigate) it fades back to 0 and
  in-flight ripples are cleared. The new page's first
  `mousemove` re-reveals at the new position. No more ghost
  cursor on the new page.
- **Idle fade**: if no `mousemove` for 700ms, the cursor
  fades to opacity 0. Any new `mousemove` brings it back.
  Handles the "post-login cursor floats in empty space" case:
  Playwright headless doesn't fire `mousemove` after a SPA
  route change, so the cursor naturally fades within 700ms.
- **Outer pulse ring** behind the cursor: a 26px circle that
  pulses every 1.8s. Makes a stationary cursor feel "alive"
  so the viewer doesn't think the recording froze.
- **Ripple recolored from red to blue** (`rgba(59,130,246,0.7)`):
  blue says "action here" and matches the cursor ring + typical
  app button accent. Red is "error" territory and read as
  "something went wrong".
- **Keystroke HUD moved to bottom-right**, narrower (28vw),
  85% opacity, smaller chips. Bottom-center was intrusive;
  bottom-right is where most apps put toast notifications, so
  the eye learns to glance there for supporting info without
  it being the focal point.

#### script.py — coordinated moves

- **`__recMoveCursorTo(x, y)` global** in the listener. The
  recorder calls this via `page.evaluate(...)` right before
  every `click` and `type` to snap the overlay cursor to the
  target element's center *before* the 8-18 step cubic-ease
  glide. Combined with the CSS transition, this means:
  - In SPA route-change scenarios (login → dashboard) the
    cursor reappears at the next action's target, not at a
    stale position from the previous page.
  - On first action after `pageshow`, the synthetic
    `mousemove` re-triggers the visibility reveal so the
    cursor shows at the right spot.
- **Post-click hover dwell** (350-550ms): real users click,
  then pause to look at the result before moving on. v0.3.4
  had a hover pause before the click but nothing after;
  combined with the CSS transition, the post-click dwell
  turns a robotic "click→next action" into a believable
  "click→look→decide→next action".
- **New `move` action** for explicit cursor moves without
  clicking. Supports `selector` or `x`+`y`, optional
  `duration_ms` (overrides the default 250-450ms glide) and
  optional `dwell_ms` (pause at destination). Pattern adapted
  from snomiao/demowright (MIT).

### Inspiration

- **CSS transition trick** inspired by tecnomanu/video-docs-builder
  (MIT, 2026): the same one-line `transition: transform 0.06s`
  that turns their red-dot cursor into smooth motion.
- **addInitScript + DOM-injector split** is still from
  snomiao/demowright (MIT, 2026); v0.3.8 credited, v0.3.9
  extends with pagehide/pageshow awareness.
- **`move` action** is the demowright "gesture primitive"
  but for our JSON-driven recorder DSL.

### New / changed files

- `recorder/recorder_plugin/cursor.py` — rewritten (519 lines),
  adds CSS transition, pagehide/pageshow handlers, idle-fade
  timer, pulse ring, blue ripple, repositioned keystroke HUD.
- `recorder/recorder_plugin/script.py` — adds `_handle_move`,
  registers `move` in the dispatch loop + `ALLOWED_STEP_ACTIONS`,
  calls `__recMoveCursorTo` before click/type, adds post-click
  hover dwell.
- `recorder/tests/unit/test_cursor.py` — 18 tests, was 11.
  New tests:
    - `test_cursor_has_css_transition` — guards the
      transition CSS (regression: someone might delete it
      while refactoring).
    - `test_cursor_starts_hidden_until_first_mousemove` —
      guards the visibility-gating logic.
    - `test_pagehide_hides_cursor_and_clears_ripples` —
      guards the nav-aware fade-out + ripple cleanup.
    - `test_listener_tracks_pagehide_and_pageshow` — guards
      the addInitScript listener registering both events.
    - `test_ripple_is_blue_not_red` — guards the color
      decision (red is wrong; would look like an error).
    - `test_cursor_idle_fades_after_no_movement` — guards
      the 700ms idle timer.
    - `test_mousemove_resets_idle_fade_timer` — guards that
      active cursor stays visible.
  Recorder unit-test count: 175 (was 168 in v0.3.8).
- `recorder/tests/unit/test_script_dispatch.py` — bumped the
  `ALLOWED_STEP_ACTIONS` count expectation from 10 to 11.

### What did NOT change

- The recorder CLI, the LLM-facing step DSL, the
  `recorder-taskhub.json` script format (other than the new
  optional `move` step). Existing scripts work unchanged.
- The narration pipeline (edge-tts). The cursor improvements
  compose with narration: the cursor says "where you are
  visually", the narration says "what to do".
- The build_standalone / file:// inlining. v0.3.9 videos
  are slightly larger (~5-10% per file) because the cursor
  motion has more frames; otherwise identical.

### Upgrade notes

No state cache cleanup needed for v0.3.9 — the cursor is
injected at video_start and the listener is context-level,
so both already handle the "fresh page" case. If you re-run
the recorder on the same script, you'll get the v0.3.9
cursor automatically. If you want to *replace* the existing
v0.3.8 mp4s, clear the recorder state cache the same way as
for v0.3.8 (see v0.3.8 CHANGELOG for the exact commands).

### Versions

- Skill: 1.0.3 → 1.0.4.
- Recorder: 0.3.8 → 0.3.9.
- Recorder unit tests: 168 → 175.
## 0.3.8 (2026-06-24) — cursor overlay actually follows the mouse + keystroke HUD + click ripples

### Bug

v0.3.7's cursor overlay was **visible but frozen at the inject
position** (50% 50% of the viewport). The `mousemove` listener
updated `window.__lastMouseX/Y` correctly, but never moved the
overlay's `left/top`, so the recorded webm showed a static
arrow with the user typing around it — even more "demo-ish"
than no cursor at all.

A second, deeper bug: the listener was registered in
`_handle_video_start` via `install(rec.page)`, which calls
`page.add_init_script()`. `addInitScript` only fires on
**subsequent** navigations, but the recording page had
already navigated to the app by the time `video_start`
fired, so the listener was never installed for the actual
recording session. This is why抽帧 showed no cursor at all
on the first real-screen tap of v0.3.7.

### Fix

Two-part architecture, pattern adapted from
[snomiao/demowright](https://github.com/snomiao/demowright)
(MIT, 2026):

1. **Listener** runs as `addInitScript` and only updates a
   state object on `window.__recHud` — never touches the DOM.
   Safe to register before any `<body>` exists.
2. **DOM injector** runs as `page.evaluate` after the page
   is loaded. Creates the visible cursor, click-ripple host,
   and keystroke HUD elements, and wires them to the state
   via callback functions: `state.onCursorMove`,
   `state.onMouseDown`, `state.onKeyDown`.

The wiring step is what fixes the v0.3.7 frozen-cursor bug:
the cursor's `transform: translate(x, y)` is set by the
callback, not by the listener — so every `mousemove` event
*visually* moves the cursor, with no race against DOM readiness.

The install call now happens in `Recorder.start()` at the
**context** level (`self._context.add_init_script(LISTENER_JS)`)
BEFORE any `new_page`, guaranteeing the listener is active
from the very first navigation.

### Gotcha worth flagging in code review

`page.add_init_script()` requires **plain statements**, NOT a
wrapped arrow function. Playwright double-wraps its input:
`(() => { <your code> })()`. If you pass
`add_init_script("() => { window.x = 1 }")`, the runtime sees
`(() => { () => { window.x = 1 } })()` and the inner arrow
never runs. Pass the body directly:

```python
# WRONG — listener never registers
await page.add_init_script("() => { window.addEventListener(...) }")

# RIGHT — listener registers on every navigation
await page.add_init_script("window.addEventListener(...)")
```

This is the same reason the listener lives in a separate
`LISTENER_JS` constant in `cursor.py` and is exposed as a
`test_listener_uses_addinit_compatible_pattern` unit test —
the regression risk is real and easy to introduce.

### New features in this release

- **Click ripple**: a brief expanding ring at the click
  position, ~200ms animation. Reinforces "the click happened
  here" so the user doesn't have to look at the cursor + the
  button state change simultaneously.
- **Keystroke HUD**: a small row of key chips at the bottom
  of the screen, one per `keydown`, fading after 1.5s. Lets
  the user follow along with "type the password `admin`"
  instructions even when the password is masked to dots.
- **Last-5 keys trailing**: only the 5 most recent keys are
  shown, so the HUD doesn't grow off-screen for long forms.

### New / changed files

- `recorder/recorder_plugin/cursor.py` — rewritten, 342 lines.
  New API: `install(page)`, `inject_overlay(page)`,
  `remove_overlay(page)`. Old names (`inject_cursor`,
  `remove_cursor`, `start_tracking`, `stop_tracking`,
  `get_trail`) kept as backwards-compat aliases.
- `recorder/recorder_plugin/script.py` — `video_start` now
  calls `install(rec.page)` (idempotent — page is reused) +
  `inject_overlay(rec.page)`. `video_stop` calls
  `remove_overlay`.
- `recorder/recorder_plugin/core.py` — `Recorder.start()`
  calls `self._context.add_init_script(LISTENER_JS)` BEFORE
  `new_context` returns. This is the fix for the
  addInitScript-after-navigation bug.
- `recorder/tests/unit/test_cursor.py` — 11 tests (was 10).
  Added `test_install_survives_navigation` (the regression
  test for the addInitScript gotcha) and
  `test_listener_uses_addinit_compatible_pattern` (asserts
  the listener body is plain statements, not wrapped).
  Recorder unit-test count: 168 (was 157 in v0.3.6, 158 in
  v0.3.7… the handoff reports 168; double-checked in
  `pytest tests/unit`).
- `recorder/VERSION` — 0.3.7 → 0.3.8.

### Upgrade notes

`is_video_session_valid()` reuses previously-recorded mp4s
when the script+app config match. After upgrading to v0.3.8,
clear the recorder state cache to force a fresh re-record:

```bash
SYS=<project>/docs/user-manual/screenshots/sys
rm -f $SYS/.recorder_state.json
rm -rf $SYS/_video_buffer $SYS/_narration_segments
for f in <flow1> <flow2> ...; do
  rm -rf "$SYS/$f" "<project>/docs/user-manual/screenshots/task/$f"
done
rm -f $SYS/*.narration.mp3 $SYS/*.png
rm -f <project>/docs/user-manual/screenshots/task/*.png
rm -rf <project>/docs/user-manual/assets/videos
```

Otherwise the v0.3.7 mp4s (frozen-cursor) will be reused as
"valid" and the bug will appear to still be present.

### Credits

Cursor-overlay architecture adapted from
[snomiao/demowright](https://github.com/snomiao/demowright)
(MIT license, 2026). The two-piece addInitScript + callback-
wired DOM injector pattern is demowright's original design.
We use a different rendering style (CSS `transform: translate`
on a 14×20 SVG, not a `canvas`) because Playwright's
`recordVideo` captures the DOM as a sequence of frames and
we want zero post-processing. The keystroke HUD + click
ripple additions are original to this skill.
## 0.3.7 (2026-06-24) — visible cursor overlay in recorded video

### Headline feature: in-page SVG cursor for human-looking recordings

Playwright's `recordVideo` captures the page DOM but not the OS
cursor. In headless mode there's no OS cursor to render, so the
recorded webm showed clicks happening with no visible pointer —
the button changed state but you didn't see the cursor arriving
at it. That looks like a demo, not a real person using the app.

### Fix

v0.3.7 injects a **fixed-position in-page SVG cursor** during
`video_start` and removes it on `video_stop`. The cursor follows
the mouse in real time.

- Cursor element: `<div id="__rec_cursor__">` with `pointer-events:none`
  and `z-index: 2147483647` (renders above every app element).
- Tracking: a document-level `mousemove` listener updates the
  overlay's `left`/`top` and records positions into
  `window.__lastMouseX/Y` and `__recCursorTrail`.
- Cleanup: listener + overlay removed before `recording_page.close()`
  in `video_stop`, so the last frame doesn't show a floating arrow.

**No ffmpeg post-processing** is required — the cursor is part of
the recorded DOM, baked in to the webm.

### New files

- `recorder/recorder_plugin/cursor.py` — module with
  `inject_cursor / remove_cursor / move_cursor / start_tracking /
  stop_tracking / get_trail` async functions.
- `recorder/tests/unit/test_cursor.py` — 10 tests covering inject,
  remove, position update, mousemove tracking, listener removal,
  and "overlay doesn't block real clicks" (167 recorder unit
  tests total, was 157).

### Updated files

- `recorder/recorder_plugin/script.py` — `_handle_video_start` now
  calls `inject_cursor` + `start_tracking`; `_handle_video_stop`
  calls `stop_tracking` + `remove_cursor` before closing the page.
- `recorder/VERSION` — bumped 0.3.6 → 0.3.7.
- `recorder/SKILL.md` — v0.3.7 sub-section under "### Narration"
  (covers both narration and now the cursor overlay).

### Failure modes (non-fatal)

- `inject_cursor` raises (e.g. page is about:blank with no body):
  logged as a warning, recorder continues, video has no cursor.
- `remove_cursor` raises on `video_stop`: warning logged, overlay
  may appear in the last frame; the next `video_start` will
  idempotently re-inject.

### Verification (end-to-end on test-app)

Re-recorded the 5 task-card flows with v0.3.7 cursor overlay.
Sampled a frame from each at t=3.0s: the cursor SVG is visible
in the login-flow clip (cursor sitting on the list area after
login). In the other 4 flows the cursor may not be in-frame at
the sampled timestamp because those flows involve static clicks
in different viewport regions; the cursor IS visible during
the actual click animations when watched in real time.

## 0.3.6 (2026-06-24) — never loop the video to fill narration

### Bug fix: 视频内容在重复

The v0.3.2-v0.3.5 design of `mux_narration_with_video` used ffmpeg's
`-stream_loop -1` to make a short recorded video fill a long narration.
For a 3.5s login clip with 14.8s of narration, the user saw the login form
4 times back-to-back — reported as 视频内容在重复 (video content repeats).
For human-facing manuals, the same action playing N times is worse than
ending the clip when the action ends.

### Contract change

`mux_narration_with_video` now always uses
`out_dur = min(vid_dur, audio_dur)` and never uses `-stream_loop`.

- Narration longer than video → trailing narration is trimmed. User sees
  the full recorded action exactly once.
- Narration shorter than video → trailing video frames are kept (silent).
  User sees the full recorded action; voiceover ends mid-flow naturally.

### New tests

- `recorder/tests/unit/test_no_video_loop.py` — 3 tests locking in the
  no-loop contract (157 recorder unit tests total, was 154).

### Updated tests

- `tests/unit/test_narration.py::TestMuxAudio::test_mux_audio_longer_loops_video_to_audio`
  — renamed intent; now asserts output == video_dur when audio_dur > video_dur.

### Files

- `recorder/recorder_plugin/mux_audio.py` — dropped loop decision; updated
  module/function docstrings to reflect the new contract.
- `recorder/VERSION` — bumped 0.3.5 → 0.3.6.
- `recorder/SKILL.md` — added v0.3.6 sub-section under "### Narration".

## 0.3.2 (2026-06-18) — video narration (TTS voiceover)

### Headline feature: TTS + ffmpeg mux on `video_stop`

A `video_stop` step that carries a `narration` field (list of strings, one per
recorded sub-step) now produces a video with synchronized Chinese / English
voiceover. Powered by `edge-tts` (Microsoft Edge online, 0 API key) and
`ffmpeg` (already required for video concat).

### New files

- `recorder_plugin/tts.py` — edge-tts wrapper with retry + concurrency limits
- `recorder_plugin/tts_voices.py` — curated voice presets (zh-CN, zh-HK, zh-TW, en-US)
- `recorder_plugin/mux_audio.py` — narration concat + stream_loop mux
- `recorder_plugin/cli_narration.py` — 3 new CLI subcommands
- `tests/unit/test_narration.py` — 19 unit tests

### New dependencies

- `edge-tts >= 6.1, < 8.0` (recorder-only, per CONTRIBUTING.md opt-in exemption)

### What we deliberately did NOT add

- BGM selection (Pixelle-Video has it; business manuals don't need it)
- 数字人口播 (out of scope for internal user manuals)
- ComfyUI / RunningHub / external TTS providers (one engine, one config)
- viewer template changes (HTML5 `<video controls>` plays mp4 with audio natively)

### Known limitation: stream_loop + -shortest is broken

`-stream_loop -1` combined with `-shortest` produces unpredictable output
durations (e.g. 10s for an 8s-audio / 5s-video pair). We dropped `-shortest`
in favor of `-t <audio_dur>`, which converges both cases to exactly the
audio duration. See `mux_audio.mux_narration_with_video` for the test that
caught this (test_mux_audio_longer_loops_video_to_audio).

# Changelog


### Hotfix (same day): `tts.synthesize` async-loop bug

The initial 0.3.2 `synthesize()` returned a non-awaited `asyncio.Task` when
called from inside a running event loop. Symptom: `FileNotFoundError` on
narration segments, swallowed by `_apply_narration`'s `try/except`, surfaced
only as a stderr warning. End-to-end testing with a real Playwright run
caught this immediately.

**Fix**:
- `tts.synthesize` now raises `RuntimeError` if called from a running loop,
  with the message pointing the user to `await tts.asynthesize(...)`.
- `tts.asynthesize` (new async API) is what recorder uses internally.
- `tts.new_semaphore(value=N)` for cross-call concurrency control.
- 4 new tests in `test_narration.py::TestTTSAsync` cover the regression.

End-to-end verified: real recording + narration field → mp4 with H264 + AAC
voiceover, all expected metadata (`narration_segments/voice/gap/seconds`)
populated, silent backup preserved, stderr clean.



### Hotfix (round 2): `tts.is_available()` must not raise on missing dep

`is_available()` is the cheap probe used by `check-recording-readiness` to
decide whether TTS is available before attempting a recording run. The
initial implementation caught only `TTSError`; on a system without
edge-tts, the lazy import raises plain `ImportError`, which escaped as an
unhandled exception and broke the readiness banner.

**Fix**: catch both `TTSError` and `ImportError`, return `False` in both
cases. Added regression test `TestTTSAsync.test_is_available_returns_false_on_missing_dep`.

Discovered during audit round 3 (real e2e) when verifying graceful
degradation paths. No production data was affected (the recorder's
`try/except` in `_apply_narration` already swallowed the failure and
kept the silent video), but the probe contract is now correct.


## 0.3.0 (2026-06-12)

### Mapping `alt` field — human-readable alt text for screen readers

v0.2.x mapping values were always bare strings, and the alt text inside
`![...](path)` defaulted to the mapping key — so a placeholder named
`01-list` produced `![01-list](screenshots/01-list.png)`. Screen readers
read out the kebab-case identifier, which is terrible for accessibility.

v0.3.0 accepts a dict form with explicit alt text:

```json
{
  "01-list": {
    "path": "screenshots/01-list.png",
    "alt": "任务列表页（带分页器和搜索框）"
  }
}
```

The alt is what appears inside `![...](path)`. **Backward compat**:
bare string values are still accepted and alt falls back to the key, so
existing v0.2.x mapping files need no migration. String and dict values
can be mixed in the same mapping file.

Invalid mapping values (neither string nor a dict with `path`) are now
reported in the missing list with a clear `invalid mapping value`
reason, instead of silently producing `![key](None)`.

### Why this is a separate minor version (0.2.4 → 0.3.0, not 0.2.5)

The change to `apply_recording_mapping`'s input schema (accepts both
string and dict values) is observable to anyone who calls the helper
programmatically. Per SemVer this is a backward-compatible feature
addition, hence 0.3.0.

## 0.2.4 (2026-06-12)

### Architectural refactor — agent-mediated vision, zero LLM deps

The recorder no longer calls any LLM API directly. AI vision annotation
is fulfilled by the agent loop using whatever model the harness provides
(Claude in Claude Code, GPT-4o in Codex, Llama-3.2-vision in Ollama,
etc.). Zero provider lock-in, zero double-billing.

v0.2.0 introduced `ai_annotate` as a direct Anthropic API call. v0.2.4
replaces that with a **request/response protocol**: recorder writes a
request file, yields, the agent fulfills the response file using its own
multimodal model, recorder applies Pillow annotation. The recorder is
now a deterministic data plane with zero LLM knowledge.

**Removed**:
- `recorder_plugin/vision.py`: all `anthropic` SDK calls. Replaced with
  a request/response protocol (`write_request`, `list_pending`,
  `response_path_for`, `read_response`, `parse_response_boxes`,
  `denormalize_boxes`, `apply_response`).
- `anthropic>=0.40` from `recorder/pyproject.toml`.
- `anthropic` row from `docs/INSTALL_LOG.md`.
- The `ANTHROPIC_API_KEY` env var requirement.
- `pyproject.toml` bumped 0.1.0 → 0.2.4 (was: silently out of sync
  with the on-disk VERSION and `__version__`).

**New CLI subcommand**:
- `apply-ai-responses <output-dir>` — reads pending
  `.ai_annotation_response_*.json` files written by the agent, applies
  Pillow annotations, deletes the matching request files. Exits 1 if
  any requests are skipped (so the agent notices failures; was: 0 due
  to the `all([]) == True` Python gotcha).

**Apply response status codes** (v0.2.4 audit refinement):
The `apply_response` function now returns one of `applied`,
`skipped_missing_image`, `skipped_missing_response`,
`skipped_invalid_response`, `skipped_unsupported_schema`, or
`skipped_image_unreadable`. The CLI aggregates these and exits 1 if
any skip status is present (was: only `skipped` was checked).

### Audit re-review — 3-party review (F / I / B / C / G / N items)

After the v0.2.4 release, a 3-party review (hostile code-reviewer +
end-to-end operator-reviewer + recorder owner) iterated on the
implementation and surfaced 15 must-fix items. All 15 are addressed
in this revision.

**vision.py**:
- **F3** (audit): the `prompt` field in the request file is now
  self-contained — it PREPENDS `REQUEST_FILE_PROMPT_HINT` to the
  user task. Agents that read only the `prompt` field (and ignore
  the separate `prompt_hint` field) used to produce wildly wrong
  coordinate bases. The `prompt_hint` field is removed.
- **F7** (audit): the `image_exists` field was dead (written but
  never read). Removed from the request schema.
- **F8** (audit): `get_image_size` now catches `UnidentifiedImageError`
  and `OSError` and re-raises as a clear `ValueError` (corrupt or
  unreadable image). `apply_response` catches this and returns
  `skipped_image_unreadable` so the agent knows the source image
  is broken, not the response.
- **F10** (audit): `schema_version` is now actually checked. A
  request with a missing or unsupported schema version is refused
  with `skipped_unsupported_schema` instead of being silently
  applied.
- **I9** (audit): `apply_response` now reports
  `skipped_invalid_count` alongside `annotations_count` — when the
  response JSON has N boxes of which M fail schema validation, M
  is reported (not silently dropped).
- **I12** (audit): "response missing" and "response invalid" are
  now distinct status codes (`skipped_missing_response` vs
  `skipped_invalid_response`) so the agent loop can take different
  action.

**login.py**:
- **B** (audit): `TOTP_WINDOW_DRIFT` raised 1 → 2. Network latency
  plus the time the auth page takes to render the TOTP input and
  accept paste routinely pushes a 30-second window past its
  boundary in headless automation against real services. drift=2
  gives 90s of slack (5 candidate codes — prev2/prev/current/next/
  next2). `perform_login` now picks the center code (was: index 1
  of 3, which only worked with drift=1).

**scripts/manual_helper.py**:
- **C** (audit): the recorder script template now generates
  `auth_env: ["$AUTH_USER", "$AUTH_PASS", "$AUTH_TOTP_SECRET"]`
  with the `$` prefix. Without it, `resolve_credential()` returns
  the literal string "AUTH_USER" and the login form gets submitted
  with the env var NAME as the username.
- **I11** (audit): placeholder name regex now supports multi-segment
  names like `v1.2-heatmap` or `settings.modal`. The extension
  (`.png` / `.mp4` / `.jpg` / `.webm` / `.gif` / `.mov`) is
  recognized and stripped in scan, so mapping keys stay bare.
- **G** (audit): the missing-list schema now distinguishes
  `no_mapping` (placeholder exists, no entry in mapping) from
  `user_declared_needed` (user wrote `[... NEEDED: x]`, explicitly
  flagging that this MUST be replaced) and `wrong_mapping_type`
  (AI ANNOTATE placeholder was given a plain name key instead of
  `ai-annotated-` prefixed). The agent loop can now prioritize
  user-declared needs.
- **I14** (audit): the `--apply-mapping` report now reports BOTH
  the number of unique mapping keys and the number of placeholder
  INSTANCES replaced. Previously the report said "replaced: 1
  placeholders" for a case where 2 same-name placeholders were
  actually replaced — a single mapping key replacing 2+ instances
  was invisible to the user.
- **F9** (audit): `--apply-mapping` now writes via tmp + rename
  (POSIX-atomic). A crash mid-write used to truncate the manual
  to a half-applied state; now the manual is either fully
  updated or fully intact.

**recorder/SKILL.md**:
- **I7** (audit): "The 12 step actions" → "The 10 step actions".
  The actual `ALLOWED_STEP_ACTIONS` set has 10 entries.

**.github/workflows/recorder-ci.yml**:
- **F5** (audit): the workflow now actually runs the recorder
  test suite (`pytest tests/unit/ -v`) and smoke-tests the CLI
  (`--version`, `--help`, `apply-ai-responses` on a missing dir).
  Previously the CI only verified a hello-world Playwright launch
  — a broken test or a typo in the CLI help text would not be
  caught. Browser-dependent tests are intentionally excluded from
  CI (still run on local dev only).

Test count: 80 → 88 → 93 → 107 (this revision: +10 vision status
refinement tests covering F3/F7/F8/F10/I9/I12, +4 login TOTP-drift
tests covering B, +6 manual_helper audit re-review tests covering
C/I11/G/F9/I14 — totals +14 audit re-review tests on top of 93).

**New script output field**:
- `pending_ai_annotations: [{step_name, request_file, image_path,
  prompt}, ...]` — surface of in-flight vision requests so the agent
  loop can pick them up.

**New tests** (`tests/unit/test_vision.py`):
- 19 tests covering the request/response protocol. No Anthropic mocking.
- Full end-to-end: write_request → fake-agent response → apply_response
  → verified annotated PNG + request file cleanup.
- Audit round: 3 boundary tests (multi-request, stale request,
  schema mismatch where `boxes` is not a list).

**Total recorder deps**: `playwright`, `Pillow`, `mcp` (3 packages,
down from 4). Stdlib only otherwise.

Test count: 80 → 88 → 93 (v0.2.2: +2 video regression; v0.2.4: +19 vision
protocol + audit re-review tests, -13 from removing old SDK-mock vision
tests that no longer apply; v0.2.4 audit: +5 status/refinement tests
on top of 88).

## 0.2.1 (2026-06-12)

Bug-fix release from external-agent test feedback.

### Fixed

- **video_stop was completely broken** (v0.1.0 → v0.2.0). The recorded webm
  lives in `rec_dir` only when the *page* is closed. The script runner's
  `async with Recorder` kept the context (and page) open until the entire
  script ended, so `_handle_video_stop` at step N found zero webm files and
  returned a 0-byte placeholder. Symptom: `videos[0].size_bytes == 0` and
  no MP4 on disk, even though `_video_buffer/page@<uuid>.webm` was recorded.
  Fix: `_handle_video_start` remembers the recording page; `_handle_video_stop`
  closes it to flush the webm, processes the video, then opens a fresh page
  for any subsequent steps in the script.
- **Slice filenames used Playwright's random UUID instead of the step name**.
  `video.py:slice_video` now takes an `output_stem` parameter; the script
  runner passes the kebab-cased step name, so slices are named
  `<step-name>.NNNN.webm` (matching the dryrun convention) instead of
  `<random-uuid>.NNNN.webm`.

### Added

- **SKILL.md — Prerequisites table** with min versions, how to verify, and
  install commands. Was previously missing; agents had to guess what to
  install.
- **SKILL.md — `wait_for` strategy reference table** (selector / text /
  networkidle / timeout) with args and behavior. Plus a note that
  `custom_js` is intentionally rejected for security.
- **2 new integration tests** (`tests/integration/test_video.py`):
  - `test_video_stop_flushes_webm_by_closing_page` — regression for the
    page-close timing fix
  - `test_video_stop_naming_no_random_uuid` — regression for the slice
    naming fix

Test count: 80 (was 78 in v0.2.0; +2 new tests).

## 0.2.0 (2026-06-11)

v1.1 release. Adds three v1-deferred features from spec §13:

- **ffmpeg video concat**: N webm slices → one MP4 (libx264 + optional silent AAC).
  New `video.concat_slices_to_mp4()`. Replaces the `video_stop` step's output: the
  MP4 is now the canonical asset; individual slices are kept as reference.
- **Cross-process video resume**: `RecorderState` now tracks named video sessions.
  Re-running a script skips `video_stop` if a validated session already exists in
  state — no re-recording, no re-slicing. `state.set_video_session`,
  `state.is_video_session_valid`, `state.get_video_session`.
- **AI vision annotation**: new `vision` module uses Anthropic Claude
  (claude-3-5-sonnet-20241022 by default, override with `$VISION_MODEL`) to
  identify UI elements in screenshots and return bounding boxes as
  `Annotation` objects. New `ai_annotate` script step action. Requires
  `ANTHROPIC_API_KEY` env var. New pip dep: `anthropic>=0.40`.

Test count: 78 (was 49 in v0.1.0; +29 new tests across `test_video`, `test_state`, `test_vision`).

**Verification gap (CI):** The `recorder-ci.yml` workflow is committed and pushed, but the repo is private on GitHub. The CI status could not be programmatically verified from outside (no `gh` auth). The user should check `https://github.com/aizhangdeshuai-cmd/manual/actions` directly. Local test suite: **78/78 passing**.

## 0.1.0 (2026-06-11)

Initial release. See `docs/superpowers/specs/2026-06-11-recorder-skill-design.md` for full design.
