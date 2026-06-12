# Changelog

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
