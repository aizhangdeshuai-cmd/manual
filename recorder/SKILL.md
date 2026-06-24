---
name: recorder
description: Opt-in plugin for the user-manual skill. Drives a Chromium browser via Playwright to capture screenshots and videos for task cards. Trigger when the user-manual skill encounters a `[SCREENSHOT NEEDED]` / `[VIDEO NEEDED]` placeholder and the recorder is installed. Requires: user-manual skill + the recorder plugin installed per `recorder/INSTALL.md`.
---

# Recorder (opt-in plugin for user-manual)

## What it does

Given a declarative JSON script (or a sequence of MCP tool calls), drives a headless Chromium via Playwright, takes screenshots, records videos, annotates them, masks private regions, and emits assets ready to drop into user-manual task cards.

## Prerequisites

Before running the recorder, the host environment must have:

| Requirement | Min version | How to verify | Notes |
|---|---|---|---|
| Python | 3.10+ | `python3 --version` | Tests pass on 3.10-3.13 |
| `playwright` (pip) | ≥1.40 (see `pyproject.toml` for upper bound) | `python3 -c "import playwright; print(playwright.__version__)"` | Provided by `pip install -e .` in `INSTALL.md` |
| `Pillow` (pip) | 10.0+ | `python3 -c "import PIL; print(PIL.__version__)"` | Annotation rendering |
| `mcp` (pip) | 1.0+ | `python3 -c "import mcp"` | Only needed for MCP server mode |
| `ffmpeg` (system) | 4.4+ | `ffmpeg -version` | Video slicing + concat |
| Chromium (Playwright) | bundled | `python3 -m playwright install chromium` | First-time setup |
| CJK fonts (Linux only) | noto-cjk | `fc-list :lang=zh` | macOS has system fonts |

**v0.2.4 — no LLM deps.** The recorder no longer calls any LLM API. AI
vision annotation is fulfilled by the agent loop using its own model
(Claude in Claude Code, GPT-4o in Codex, Llama-3.2-vision in Ollama,
etc.). Zero provider lock-in. See §14.

## When the parent user-manual skill uses it

When the user-manual skill's LLM agent encounters a `[SCREENSHOT NEEDED]` or `[VIDEO NEEDED]` placeholder in a task card, it should:

1. Read this `recorder/SKILL.md` to learn the script schema and tool set.
2. Compose a script (or a sequence of MCP tool calls) targeting the relevant UI.
3. Run the script via `python3 -m recorder_plugin.cli run <script.json>` or the MCP server.
4. Insert the resulting asset paths back into the task card's `![caption](path)` / `[VIDEO: path]` slots.

## When NOT to use it

- Static site documentation that needs no UI demonstration → use static images directly.
- The user explicitly wants manual recording.
- The target is not a web app (desktop, mobile) — those are out of v1 scope.

## Quick start (for the LLM agent)

```bash
# Verify the recorder is installed
python3 -m recorder_plugin.cli --version    # → 0.2.4
ffmpeg -version | head -1                    # → ffmpeg 4.4+

# No API keys needed — vision is handled by your agent's own LLM

# Run an existing script
python3 -m recorder_plugin.cli run examples/sample_script.json

# The output is JSON on stdout, with paths to all generated assets.
# If the script had ai_annotate steps, look for "pending_ai_annotations"
# in the output — the agent fulfills those via the request/response protocol.
```

## Script schema (declarative mode)

See `examples/sample_script.json` for a complete example. The 10 step actions:
`navigate`, `click`, `type`, `wait_for`, `screenshot`, `login`, `video_start`, `video_stop`, `set_viewport`, `ai_annotate` (v0.2.4: request/response — see §14 below).

The `video_stop` step produces a single MP4 (concat of N 10s webm slices) via `video.concat_slices_to_mp4`. State-tracked across re-runs: a script with the same name will skip the video session if it was already validated.

### Narration (v0.3.2 — TTS voiceover for video_stop)

When a `video_stop` step carries a `narration` field (a list of strings, one per
recorded sub-step), the recorder synthesizes each segment with edge-tts, concatenates
them with silence gaps, and muxes the resulting audio track onto the recorded video.
The output mp4 plays the recording with synchronized voiceover.

Script shape:

```json
{
  "name": "create-employee-flow",
  "steps": [
    {"action": "video_start", "name": "create-employee"},
    {"action": "click", "name": "open-user-mgmt", "selector": "..."},
    {"action": "click", "name": "add-user-btn",   "selector": "..."},
    {"action": "type", "name": "fill-employee-id", "selector": "..."},
    {"action": "video_stop", "name": "create-employee",
     "narration": [
       "打开系统管理菜单,进入用户管理页面。",
       "点击右上角新增用户按钮。",
       "填写工号、姓名、手机号。",
       "点击保存,列表里出现新员工。"
     ],
     "narration_gap": 2.0,
     "narration_voice": "zh-CN-XiaoxiaoNeural",
     "narration_rate": "+0%"
    }
  ]
}
```

The original silent video is kept as `<name>.silent.mp4` next to the new
`<name>.mp4` (with audio). Narration is opt-in: if the `narration` field is
absent, video_stop behaves exactly as before (silent output).

If `edge-tts` is not installed or the network is unavailable, the recorder logs a
warning to stderr and keeps the silent video — it does NOT fail the run. This
mirrors the v0.2.4 philosophy: optional capabilities degrade, they don't break.

CLI subcommands for direct use (no script needed):

```bash
# Synthesize one narration segment
python3 -m recorder_plugin.cli tts-synth "打开系统管理。" --out nar1.mp3

# Concatenate segments with 2s silence gaps
python3 -m recorder_plugin.cli concat-narration nar1.mp3 nar2.mp3 --out full.mp3 --gap 2.0

# Mux narration onto a video
python3 -m recorder_plugin.cli mux-audio recording.webm full.mp3 --out with-voice.mp4
```

#### v0.3.11 — Humanized cursor motion (bezier bow + smooth overshoot + 3-mode typing)

The v0.3.9 cursor glided in a straight line with constant per-step
delay. v0.3.10 fixed the blank-start issue, but a viewer could
still tell the glides were "robotic": the cursor teleported along
a line, every step took the same time, and the typing cadence was
a metronome. v0.3.11 fixes this with a new `human_motion` module
that randomizes the five things that read as "real human" instead
of "script":

1. **Bezier bow** — the cursor's path is a quadratic bezier whose
   control point is offset *perpendicular* to the start-end
   vector (left or right, randomized per glide). Real hand
   trajectories curve because the hand pivots at the
   wrist/elbow; the eye reads a straight-line glide as
   mechanical.
2. **Smooth overshoot near the end** — in the t=0.85-0.98 range
   the path adds a sinusoidal bump (1-4px past the target along
   the start-end vector) then a recovery oscillation in
   t=0.98-1.0 that lands the cursor ON the target. This is the
   "hand physics" of real cursor use — momentum carries the
   cursor slightly past where the user intended, then the hand
   corrects.
3. **Trapezoid per-step delay** — `initial_ms`, `peak_ms`,
   `final_ms` scaled by distance, applied as
   start-fast / mid-slow / settle (e.g. 12-18ms → 7-11ms →
   16-26ms on a 500+px move). Constant per-step delay reads as
   a screensaver; deceleration into the target reads as
   "a person was aiming".
4. **3-mode typing mixture** — 75% "flow" (50-95ms), 20% "burst"
   (30-55ms), 5% "hesitate" (180-350ms). Real typing has bursts
   and pauses, not a fixed cadence.
5. **Triangular hover + post-click pauses** — most are 120-250ms
   (hover) and 200-400ms (post-click), with a ~1.5% chance of a
   1-2s "wait, I need to read this" hover and a ~5% chance of a
   1-2s "the user is reading a modal" post-click. The 5% / 1.5%
   long pauses are what make the recording read as "a person
   thinking", not "a script that knows what to click next".

The 5 algorithm changes all live in one new module
(`recorder_plugin/human_motion.py`) so they can be tuned
independently from `script.py`'s step executor.

**Why t=0.85 (not earlier) for the overshoot**: a quadratic
bezier at t<0.85 is still 150+ pixels short of the target on a
1000px move. Adding an overshoot that far from the target would
be invisible — the bump would be on a position the viewer can't
visually distinguish from the rest of the glide. Concentrating
the overshoot near the end (where the bezier is near the target)
makes the "hand correction" wobble visible without making the
cursor look glitchy mid-glide.

**Why a sinusoidal bump (not a linear one)**: a linear bump
would have a sharp peak at t=0.915 that the eye reads as
"snapped" or "teleported". The sine envelope produces smooth
acceleration into and out of the peak, which reads as a single
fluid correction.

**Why 1-4px (not 10-20px) for the overshoot magnitude**: at
10+px the cursor looks glitchy / lossy. At 1-4px it just looks
like the user wasn't 100% precise — which is what real cursor
use actually looks like. The `min(distance * 0.012, 4.5)`
formula scales with distance but caps at 4.5px so a 1000px move
doesn't have a 12px overshoot.

All 11 functions in `human_motion.py` accept an optional
`rng=random.Random(seed)` for deterministic unit tests. The
default is to use the global `random` module.

Test count: 218 (was 195 in v0.3.10; +23 new tests in
`tests/unit/test_human_motion.py`).

#### v0.3.10 — Frame-accurate trim of leading blank frames

Every recorded video started with 40-300ms of a blank white
frame at the front. To a viewer this read as "the recording
is broken" — the video began with nothing, then the page
appeared. Caused by Playwright's `recordVideo` API starting
recording at context creation, BEFORE the page navigated
and the SPA bundle loaded.

v0.3.10 detects the first content frame (SATAVG > 0.5) and
re-encodes the video starting from there, using ffmpeg's
`trim` video filter. Frame-accurate, no keyframe dependency.

**Why the `trim` filter, not `ffmpeg -ss <ts> -i <input>`**:
the latter is **fast-seek** — it snaps to the nearest
keyframe BEFORE the target ts. If that keyframe is blank
(e.g. the first I-frame is white), the trimmed mp4 STILL
starts with a blank frame. The `trim` filter decodes
through to the target ts and emits the content frame as
the new first frame. See
`tests/unit/test_video.py::test_trim_blank_start_first_frame_has_content`
for the regression test.

**Why SATAVG (saturation), not YAVG (luminance)**: the
test-app's UI is a near-white background with a white card
— YAVG of a loaded page (~228) and YAVG of a blank white
frame (~235) differ by only 7 units, too close to call
reliably. SATAVG of a blank frame is exactly 0; SATAVG of
any rendered page with a colored element is > 0.5.

The new `trim_blank_start()` in `video.py` iterates up to 3
passes: after each trim, re-detect; if the new mp4 still
has a blank keyframe at the start, trim again. In practice
1-2 passes is enough.

API: `concat_slices_to_mp4(..., trim_leading_blank: bool = True)`.
The previous param name `trim_blank_start` shadowed the
module-level `trim_blank_start()` function and crashed with
`TypeError: 'bool' object is not callable` — renamed in
this release.

#### v0.3.9 — Human-looking cursor (smooth motion, idle-fade, nav-aware)

v0.3.8 shipped a cursor that was visible but had five "demo"
tells that made the video look robotic instead of recorded:

  1. Cursor teleported on every mousemove — every
     `setCursorPos()` was a snap, no interpolation.
  2. Cursor stayed visible after page navigation at the
     last position from the old page (Playwright headless
     doesn't fire `mousemove` after navigation).
  3. Click ripple stayed red and visible in the new page's
     empty space (because the ripple was tied to viewport
     coords, not the new page's content).
  4. No idle behavior — a frozen cursor looked pasted on,
     not like someone waiting to see a result.
  5. Keystroke HUD was bottom-center 80vw — too intrusive.

v0.3.9 fixes all five with one mental model: "treat the
cursor like a real user's cursor, not a debug marker."

**What changed in cursor.py**:

- **CSS `transition: transform 0.08s ease-out`** on the
  cursor element. Every `setCursorPos()` still snaps the
  position, but the GPU interpolates between frames so the
  motion looks smooth — the way a real OS cursor glides
  across the screen. Inspired by tecnomanu/video-docs-builder
  (MIT, 2026) which uses the same trick.
- **Visibility gating**: cursor is `opacity: 0` by default.
  It reveals on the first `mousemove` of the page session.
  On `pagehide` (about to navigate) it fades back to 0 and
  in-flight ripples are cleared. The new page's first
  `mousemove` re-reveals at the new position. No more ghost
  cursor on the new page.
- **Idle fade** (700ms): if no `mousemove` for 700ms, the
  cursor fades to opacity 0. Any new `mousemove` brings it
  back. This is what handles the "post-login cursor floats
  in empty space" case: Playwright headless doesn't fire
  `mousemove` after a SPA route change, so the cursor
  naturally fades within 700ms.
- **Outer pulse ring** behind the cursor: a 26px circle
  that pulses every 1.8s. Makes a stationary cursor feel
  "alive" so the viewer doesn't think the recording froze.
- **Ripple recolored from red to blue**
  (`rgba(59,130,246,0.7)`): blue says "action here" and
  matches the cursor ring + typical app button accent. Red
  is "error" territory and read as "something went wrong".
- **Keystroke HUD moved to bottom-right**, narrower (28vw),
  85% opacity, smaller chips. Bottom-center was intrusive;
  bottom-right is where most apps put toast notifications,
  so the eye learns to glance there for supporting info
  without it being the focal point.

**What changed in script.py**:

- **`__recMoveCursorTo(x, y)` global** in the listener.
  The recorder calls this via `page.evaluate(...)` right
  before every `click` and `type` to snap the overlay
  cursor to the target element's center *before* the 8-18
  step cubic-ease glide. Combined with the CSS transition,
  this means:
    - In SPA route-change scenarios (login → dashboard) the
      cursor reappears at the next action's target, not at
      a stale position from the previous page.
    - On first action after `pageshow`, the synthetic
      `mousemove` re-triggers the visibility reveal so the
      cursor shows at the right spot.
- **Post-click hover dwell** (350-550ms): real users
  click, then pause to look at the result before moving on.
  v0.3.4 had a hover pause before the click but nothing
  after; combined with the CSS transition, this turns a
  robotic "click→next action" into a believable
  "click→look→decide→next action".
- **New `move` action** for explicit cursor moves without
  clicking. Supports `selector` or `x`+`y`, optional
  `duration_ms` (overrides the default 250-450ms glide),
  and optional `dwell_ms` (pause at destination). Pattern
  adapted from snomiao/demowright (MIT). Example:

  ```json
  { "action": "move", "selector": "h1", "duration_ms": 800, "dwell_ms": 400 }
  ```

  This glides the cursor to the `<h1>` over 800ms (slow,
  deliberate) then dwells there for 400ms (let the user
  read the heading) before the next action.

**Why this all matters for the manual**: the v0.3.8 video
showed clicks happening at the right places but the cursor
teleported to each one. Viewers read this as "the screen
is being driven by a script, not a person". v0.3.9 makes
the cursor glide smoothly between targets, fades when
nothing's happening, reappears at the right place on each
new page, and uses blue ripples (action) instead of red
(errors). Net result: the video looks like a real person
recorded it, not a test rig.

#### v0.3.8 — Cursor actually follows the mouse + keystroke HUD + click ripples

v0.3.7 introduced a visible cursor overlay but the cursor was
**frozen at the inject position** (50%/50% of the viewport).
The recorded webm showed a static arrow while the user typed
around it — even more "demo-ish" than no cursor. Plus a
second bug: the `mousemove` listener was registered with
`page.add_init_script()` AFTER the page had navigated, so
on the *first* page load the listener never ran at all.

This release fixes both bugs by splitting the cursor subsystem
into two pieces, following the
[snomiao/demowright](https://github.com/snomiao/demowright)
pattern (MIT, 2026):

- **Listener** (registered with `context.add_init_script()`
  in `Recorder.start()` BEFORE any page is created). The
  listener runs on every navigation, attaches
  `mousemove`/`mousedown`/`mouseup`/`keydown` handlers, and
  updates a state object on `window.__recHud`. **It does
  not touch the DOM** — safe to run before `<body>` exists.
- **DOM injector** (called from `video_start` via
  `page.evaluate` after the page is loaded). Creates the
  visible cursor, click-ripple host, and keystroke HUD
  elements, and wires them to the state via callback
  functions: `state.onCursorMove`, `state.onMouseDown`,
  `state.onKeyDown`.

The split fixes the v0.3.7 frozen-cursor bug because the
cursor's `transform: translate(x, y)` is set by the DOM
injector's callback, not by the listener — so every
`mousemove` *visually* moves the cursor with no race
against DOM readiness.

**Critical gotcha worth knowing** (covered by
`test_listener_uses_addinit_compatible_pattern`):

`page.add_init_script()` double-wraps its input. If you
pass an arrow function, the runtime sees
`(() => { () => { ... } })()` and the inner arrow never
runs. The listener MUST be plain statements:

```python
# WRONG — listener never registers
await page.add_init_script("() => { window.addEventListener(...) }")

# RIGHT — listener registers on every navigation
await page.add_init_script("window.addEventListener(...)")
```

This is why the listener lives in a module-level
`LISTENER_JS` constant in `cursor.py` and is asserted by
a dedicated test.

**New in this release**:

- **Click ripple** — a brief expanding ring at the click
  position, ~200ms. Reinforces "the click happened here".
- **Keystroke HUD** — a row of key chips at the bottom of
  the screen, one per `keydown`, last 5 keys, 1.5s fade.
  Lets the user follow password-typing instructions even
  when the password is masked to dots.
- **Context-level install** — `Recorder.start()` calls
  `self._context.add_init_script(LISTENER_JS)` BEFORE
  `new_page`. Listener is active from the first navigation.

**Upgrade note**: clear `.recorder_state.json` + the
`_video_buffer/` + the per-flow `sys/<flow>/` directories
after pulling v0.3.8, otherwise `is_video_session_valid()`
will reuse the v0.3.7 (broken-cursor) mp4s. See
`CHANGELOG.md` for the exact commands.

#### v0.3.7 — Visible cursor in recorded video (in-page SVG overlay)

Playwright's `recordVideo` captures the page DOM but **not** the OS
cursor. In headless mode there's no OS cursor to render, so the
recorded webm shows clicks happening with no visible pointer — the
button changes state but you don't see the cursor arriving at it.
That looks like a demo, not a real person using the app.

v0.3.7 fixes this by injecting a **fixed-position in-page SVG
cursor** during `video_start` and removing it on `video_stop`. The
cursor follows the mouse through three mechanisms:

1. **On inject**: a `<div id="__rec_cursor__">` containing a 14×20
   SVG mouse pointer is appended to `<body>`. The div has
   `pointer-events: none` (so it never blocks real clicks) and
   `z-index: 2147483647` (so it renders on top of every app
   element, including modals).
2. **On `start_tracking`**: a document-level `mousemove` listener
   updates the overlay's `left`/`top` to follow the mouse, and
   records positions into `window.__lastMouseX/Y` and
   `__recCursorTrail`.
3. **On `video_stop`**: the listener is removed and the overlay
   div is removed before the recording page is closed, so the
   last frame doesn't show a floating arrow.

Because the cursor lives in the page DOM, Playwright's recorder
captures it as part of the normal webm. **No ffmpeg post-processing
is needed** — the cursor is "baked in" to the recorded video.

**Cursor visibility on different backgrounds**: the SVG uses a
white outline + black fill so it's visible on both light and
dark app UIs. The size (14×20) matches what the OS cursor looks
like at 100% DPI.

**Failure modes are non-fatal**: if `inject_cursor` raises (e.g.
the page is about:blank with no `<body>`), the recorder logs a
warning and continues without a cursor overlay. The video still
records, just without a visible pointer.

**Tested by**: `recorder/tests/unit/test_cursor.py` — 10 tests
covering injection, removal, position updates, mousemove tracking,
listener removal, and that the overlay doesn't block real clicks.

#### v0.3.6 — Narration is trimmed, never stretched by looping the video

If the synthesized narration is **longer** than the recorded video, the trailing
narration is **trimmed** to the video length. The output mp4 plays the
recorded action exactly once; the voiceover ends when the action ends.

**Why not loop the video?** The v0.3.2-v0.3.5 design used ffmpeg's
`-stream_loop -1` to make a short video fill a long voiceover. The user
reported 视频内容在重复 (video content repeats): a 3.5s login clip with
14.8s of narration played the login form 4 times back-to-back. For
human-facing manuals, seeing the same action N times is worse than
ending the clip when the action ends. Output duration is now always
`min(vid_dur, audio_dur)`; the video is the canonical timeline.

**Tuning options** (in the recorder step or CLI):
- Shorter narration segments → fewer words per segment so narration
  roughly matches the action's natural length.
- Lower `narration_rate` (e.g. `-15%`) → compresses timing without
  cutting content.
- Trim `narration_gap` from 2.0 to 1.0 or 0.5 → 2-3 segments with
  default 1.5s/segment audio budget fit a 3-5s action.

**Tested by**: `recorder/tests/unit/test_no_video_loop.py` (3 tests,
locked in v0.3.6). See also `test_narration.py::TestMuxAudio` for the
end-to-end audio+video duration contract.

### `ai_annotate` step (v0.2.4 — agent-mediated, provider-agnostic)

The `ai_annotate` step writes a request file and **does not** call any LLM. The recorder never depends on a specific vision provider.

Protocol:

1. **Recorders writes** `<output-dir>/.ai_annotation_request_<name>.json` containing `{image_path, prompt, step_name, coord_base: 1000, prompt_hint}`.
2. **Script runner returns** the script output JSON with `pending_ai_annotations: [{step_name, request_file, image_path, prompt}, ...]`.
3. **The LLM agent loop** sees `pending_ai_annotations`, reads the request files, uses its own multimodal model (Claude/GPT-4o/Llama/etc.) to identify UI elements, and writes:
   ```
   <output-dir>/.ai_annotation_response_<name>.json
   ```
   with `{step_name, boxes: [{label, x, y, w, h}, ...]}` (coords normalized to 0-1000).
4. **Recorder applies** by re-running:
   ```
   python3 -m recorder_plugin.cli apply-ai-responses <output-dir>
   ```
   which reads each response, applies Pillow annotations, writes `<name>.ai-annotated.png`, and deletes the request file.

**This means**: zero provider lock-in, zero double-billing. The recorder pays for nothing; vision is fulfilled by whichever model the user's harness already provides.

**Prerequisite** (v0.2.4 audit round 3 follow-up): AI annotation requires the **harness's configured LLM to be vision-capable** — e.g. Claude Sonnet/Opus, GPT-4o, Gemini, Qwen-VL, LLaVA via Ollama. If the harness is configured with a **text-only** model (Qwen 2.5/3, DeepSeek V3/R1, MiniMax Text-01, etc.), the agent loop **cannot fulfill** `pending_ai_annotations` and `apply-ai-responses` will exit 1 with `skipped_missing_response` indefinitely. The recorder does NOT route around this — it's the user's choice of model. Workarounds: switch the harness to a vision-capable model, or manually annotate the screenshots outside the recorder, or omit `[AI ANNOTATE: x]` placeholders from the manual entirely.

### `apply-ai-responses` return contract (v0.2.4 audit round 3, H5)

When the agent loop calls `python -m recorder_plugin.cli apply-ai-responses <output-dir>`, each request produces one of these statuses:

| Status | Meaning | Agent action |
|---|---|---|
| `applied` | The annotation was applied; PNG written; request file deleted. | Continue. |
| `skipped_missing_image` | The source PNG referenced by the request does not exist. | **Re-run the screenshot step** (or check why the file was deleted), then re-invoke. |
| `skipped_missing_response` | The request file is there but no `.ai_annotation_response_*.json` exists yet. | **Write the response file using your own LLM**, then re-invoke. **Do not retry the CLI in a tight loop** — it will exit 1 every time until you produce the response. |
| `skipped_invalid_response` | The response file exists but is not valid JSON. | **Overwrite the response file** with valid JSON, then re-invoke. |
| `skipped_unsupported_schema` | The request file's `schema_version` is missing or newer than what this recorder understands. | The recorder and the agent must agree on the schema; check for a version mismatch in the harness. |
| `skipped_image_unreadable` | The source PNG is corrupt (UnidentifiedImageError). | Re-take the screenshot; do not retry. |

The CLI aggregates all results and **exits 1 if any request was skipped**. The agent loop must read each `skipped` entry's `status` field to decide whether to (a) produce a response, (b) overwrite an existing one, or (c) re-run a screenshot.

### TOTP drift override (v0.2.4 audit round 3, H4)

The recorder's `TOTP_WINDOW_DRIFT` constant defaults to **2** (accept the current TOTP window ±2 = 5 candidate codes). This tolerates network latency and the time the auth page takes to render the TOTP input.

Override per-script via the `LoginStep.totp_drift_seconds` field:

```json
{
  "action": "login",
  "url": "https://app.example.com/login",
  "user_field": "input[name='u']",
  "user": "$AUTH_USER",
  "pass_field": "input[name='p']",
  "pass": "$AUTH_PASS",
  "submit_selector": "button[type='submit']",
  "totp_secret": "$AUTH_TOTP_SECRET",
  "totp_drift_seconds": 3
}
```

A value of 0 means "current window only" (no drift tolerance). The recorder picks `codes[drift]` (the center of the candidate list) and submits it. If the server rejects the code as expired, the recorder does NOT retry — the agent loop must decide retry policy.

### `wait_for` strategies (v1 whitelist)

| Strategy | Args | Behavior |
|---|---|---|
| `selector` | `selector`, `state?: visible\|hidden\|attached` | Wait for a Playwright locator to reach the state. Default state: `visible`. |
| `text` | `text`, `exact?: bool` | Wait for a text node matching the given string. `exact=true` requires full-string match; `exact=false` (default) allows substring. |
| `networkidle` | (none) | Wait for the page to reach `networkidle` (no in-flight requests for 500ms). |
| `timeout` | `ms` | Hard sleep. Use as last-resort fallback when nothing else fits. |

`custom_js` is **not** supported in v1 (security: arbitrary JS in a JSON script is a remote-code-execution surface). If you find yourself needing it, the underlying need is probably already covered by one of the four whitelisted strategies.

## MCP tools (imperative mode)

| Tool | Purpose |
|---|---|
| `recorder_navigate` | Navigate to URL |
| `recorder_click` | Click a selector (with retry) |
| `recorder_type` | Type into a field |
| `recorder_wait_for` | Wait for a whitelisted predicate (see table above) |
| `recorder_screenshot` | Take a screenshot with optional annotation/mask |
| `recorder_video_start` | Start video recording for a named segment |
| `recorder_video_stop` | Stop recording and produce a single MP4 |
| `recorder_run_script` | Execute a declarative JSON script |

## Output shape

See `examples/dryrun-recorder.md` for a sample output.

## Install

See `recorder/INSTALL.md`.
