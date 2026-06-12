# Changelog

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
  `_ai_annotation_response_*.json` files written by the agent, applies
  Pillow annotations, deletes the matching request files. Exits 1 if
  any requests are skipped (so the agent notices failures; was: 0 due
  to the `all([]) == True` Python gotcha).

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

Test count: 80 → 88 (v0.2.2: +2 video regression; v0.2.4: +19 vision
protocol; -13 from removing old SDK-mock vision tests that no longer
apply).

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
