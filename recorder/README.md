# recorder (user-manual opt-in plugin)

Drives a Chromium browser via Playwright to produce task-card screenshots and videos for the [user-manual skill](../SKILL.md).

**Status:** Opt-in plugin, v0.3.2. Not part of the core user-manual skill.

**v0.3.2 new:** Video narration via `edge-tts` — add a `narration` field to your `video_stop` step and the recorder auto-synthesizes a voiceover track with edge-tts, muxes it onto the recorded video with ffmpeg. Falls back to silent video if edge-tts is unavailable.

**Supports:** macOS, Linux (Ubuntu LTS). Windows is not supported in v1.

See [`SKILL.md`](./SKILL.md) for the agent-facing frontmatter, [`INSTALL.md`](./INSTALL.md) for setup, and [`examples/dryrun-recorder.md`](./examples/dryrun-recorder.md) for a sample output.
