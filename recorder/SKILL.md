---
name: recorder
description: Opt-in plugin for the user-manual skill. Drives a Chromium browser via Playwright to capture screenshots and videos for task cards. Trigger when the user-manual skill encounters a `[SCREENSHOT NEEDED]` / `[VIDEO NEEDED]` placeholder and the recorder is installed. Requires: user-manual skill + the recorder plugin installed per `recorder/INSTALL.md`.
---

# Recorder (opt-in plugin for user-manual)

## What it does

Given a declarative JSON script (or a sequence of MCP tool calls), drives a headless Chromium via Playwright, takes screenshots, records videos, annotates them, masks private regions, and emits assets ready to drop into user-manual task cards.

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
python3 -m recorder_plugin.cli --version    # → 0.1.0
ffmpeg -version | head -1                    # → ffmpeg 4.4+

# Run an existing script
python3 -m recorder_plugin.cli run examples/sample_script.json

# The output is JSON on stdout, with paths to all generated assets.
```

## Script schema (declarative mode)

See `examples/sample_script.json` for a complete example. The 11 step actions:
`navigate`, `click`, `type`, `wait_for`, `screenshot`, `login`, `video_start`, `video_stop`, `set_viewport`, `set_retry_policy`.

## MCP tools (imperative mode)

`recorder_navigate`, `recorder_click`, `recorder_type`, `recorder_wait_for`,
`recorder_screenshot`, `recorder_video_start`, `recorder_video_stop`, `recorder_run_script`.

## Output shape

See `examples/dryrun-recorder.md` for a sample output.

## Install

See `recorder/INSTALL.md`.
