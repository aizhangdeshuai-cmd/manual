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
| Python | 3.10+ | `python3 --version` | Tests pass on 3.10-3.15 |
| `playwright` (pip) | 1.40 - 1.59 | `python3 -c "import playwright; print(playwright.__version__)"` | Provided by `pip install -e .` in `INSTALL.md` |
| `Pillow` (pip) | 10.0+ | `python3 -c "import PIL; print(PIL.__version__)"` | Annotation rendering |
| `mcp` (pip) | 1.0+ | `python3 -c "import mcp"` | Only needed for MCP server mode |
| `anthropic` (pip) | 0.40+ | optional — only for `ai_annotate` step | Set `ANTHROPIC_API_KEY` env var |
| `ffmpeg` (system) | 4.4+ | `ffmpeg -version` | Video slicing + concat |
| Chromium (Playwright) | bundled | `python3 -m playwright install chromium` | First-time setup |
| CJK fonts (Linux only) | noto-cjk | `fc-list :lang=zh` | macOS has system fonts |

The `INSTALL.md` walks through installing all of the above.

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
python3 -m recorder_plugin.cli --version    # → 0.2.1
ffmpeg -version | head -1                    # → ffmpeg 4.4+

# Optional: for AI annotation, set the API key
export ANTHROPIC_API_KEY=sk-ant-...           # needed only for `ai_annotate` steps

# Run an existing script
python3 -m recorder_plugin.cli run examples/sample_script.json

# The output is JSON on stdout, with paths to all generated assets.
```

## Script schema (declarative mode)

See `examples/sample_script.json` for a complete example. The 12 step actions:
`navigate`, `click`, `type`, `wait_for`, `screenshot`, `login`, `video_start`, `video_stop`, `set_viewport`, `ai_annotate` (v1.1, requires `ANTHROPIC_API_KEY`).

The `video_stop` step produces a single MP4 (concat of N 10s webm slices) via `video.concat_slices_to_mp4`. State-tracked across re-runs: a script with the same name will skip the video session if it was already validated.

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
