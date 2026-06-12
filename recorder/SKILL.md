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
