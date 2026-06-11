# Changelog

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
