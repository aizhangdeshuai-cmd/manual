# Recorder Narration Visibility — v0.5.1 Spec

**Status:** Implemented
**Date:** 2026-06-23
**Owner:** user-manual skill maintainer
**Repo:** `aizhangdeshuai-cmd/manual`
**Scope:** `recorder/recorder_plugin/script.py`, `scripts/manual_helper.py:cmd_check_recorder_script`, `SKILL.md §2.6.1`

---

## 1. Context

v0.3.2 added optional video narration via edge-tts: a `narration: [...]` list
on a `video_stop` step synthesizes per-step TTS, concatenates with gaps, and
muxes the audio onto the recorded mp4. The design was deliberately opt-in
(per SKILL §2.6.1: "narration 是可选字段, 不写就不配音").

In practice, **"opt-in" turned into "silent failure"**:

- If the LLM agent forgets the `narration` field on every `video_stop` step,
  `_apply_narration` is silently skipped (line 502: `if narration_segs and
  isinstance(...) and ...`). The recorder emits no warning, no exit code
  change, and the user gets a fully silent mp4 with no signal of why.
- If `edge-tts` is not installed in the environment, the same silent path
  is taken via the `except Exception` branch at line 506 (warn-to-stderr is
  printed, but only in this branch — not in the "field missing" branch).
- `_apply_narration` itself has **zero unit-test coverage** (audit 2026-06-23
  found 15 tests in `test_narration.py` covering helpers `tts.py` /
  `mux_audio.py` only, not the orchestration in `script.py`).

A real user reported this on 2026-06-23: "为什么视频没有声音?" The skill
itself was working as documented, but the documentation was wrong: the
"opt-in" framing made it look like silence was a *deliberate* feature, when
in fact the LLM almost always intended narration and just forgot the field.

## 2. Goals (v0.5.1)

1. **Preflight WARNING** when a recorder script has `video_stop` steps
   without `narration` (either partial or total coverage). The WARNING is
   loud and itemizes which video sessions are affected.
2. **Preflight in `check-recorder-script`**: a new check #5 (NARRATION
   COVERAGE) returns FAIL when no `video_stop` has narration, WARN when
   some do, OK when all do. Catches the problem at script-load time, before
   the recorder runs.
3. **Runtime WARNING**: `_preflight_narration_coverage()` runs at the top
   of `run_script()` and prints the same warning to stderr. Catches the
   case where the user skipped `check-recorder-script` and ran the
   recorder directly.
4. **`force=True` raise mode** for CI / `--strict-narration` (future flag):
   converts the WARNING into a RuntimeError so hard-enforcement environments
   can fail the build.
5. **End-to-end test coverage** for `_apply_narration` (4 new tests in
   `test_narration.py`):
   - happy path (returns muxed mp4, original moved to `.silent.mp4`)
   - edge-tts unavailable → TTSError
   - all-empty segments → TTSError (catches the "field present but
     empty strings" mistake)
   - `_preflight_narration_coverage` 5 sub-cases (no sessions, all OK,
     missing, partial, force-raises)

## 3. Non-Goals (v0.5.1 explicit)

- Auto-generating `narration` from step text. Still requires the agent to
  write the field explicitly. (Templated fallback could be a v0.6 feature.)
- Adding `--strict-narration` CLI flag to the recorder's `run_script`
  wrapper. The `force=True` API is in place; the CLI wiring is a v0.5.2
  follow-up.
- Changing `_apply_narration`'s core behavior. Only added the preflight
  warning and test coverage; the silent-skip-on-missing-field is now loud,
  not gone.
- Filling `narration` for the user via `build_recorder_template`. Out of
  scope: the LLM is the one that knows what each step "sounds like".

## 4. Design

### 4.1 New helper: `_preflight_narration_coverage(steps, *, force=False)`

```python
def _preflight_narration_coverage(steps: list, *, force: bool = False) -> None:
    """Walk script steps; warn (or raise with force=True) if any video_stop
    is missing the `narration` field. Called from run_script() at the
    top, right after we know we have a record_video session."""
```

Behavior matrix:

| video_stop count | with narration | without narration | result |
|---|---|---|---|
| 0 | n/a | n/a | silent (nothing to check) |
| N | N | 0 | silent (all good) |
| N | 0 | N | stderr WARNING, list of missing names, fix hint |
| N | k < N | N - k | stderr WARNING with missing names + `--strict-narration` mention |
| any | 0 | ≥1, force=True | raises RuntimeError |

### 4.2 New check in `cmd_check_recorder_script` (skill side)

Check #5 NARRATION COVERAGE:
- 0 video sessions → OK (n/a)
- all video_stops have `narration` → OK
- some have `narration` → WARN with missing names + fix
- none have `narration` → FAIL (loud, with fix hint pointing at
  `narration: [...]` syntax)

### 4.3 `_apply_narration` end-to-end test coverage

4 new tests in `tests/unit/test_narration.py`:

- `TestApplyNarrationEndToEnd.test_happy_path_returns_muxed_mp4_and_archives_silent`
- `TestApplyNarrationEndToEnd.test_tts_unavailable_raises_tts_error`
- `TestApplyNarrationEndToEnd.test_all_empty_narration_segs_raises_tts_error`
- `TestPreflightNarrationCoverage` (5 sub-tests)

## 5. Migration

- v0.5.0 users who relied on the silent behavior: **no longer silent**.
  If you intentionally want silent videos, do one of:
  - Remove the `video_start` / `video_stop` steps entirely
  - Pass `--strict-narration=off` (future flag; for now, just ignore the WARNING)
- v0.5.0 scripts that DO have `narration` on every video_stop: no change
  in behavior. The new preflight is silent on the OK path.
- CI environments: add `python3 -m manual_helper check-recorder-script <script>`
  to the pre-record pipeline. Check #5 will FAIL the build if narration
  is missing.

## 6. Test Plan

- `recorder/tests/unit/test_narration.py`: 28 → 32 tests (+4). All pass.
- `scripts/tests/test_manual_helper.py`: 128 → 131 tests (+3 for the new
  CheckRecorderScriptTests.NARRATION_COVERAGE scenarios). All pass.

## 7. Open Questions / Follow-ups (post-v0.5.1)

- Should `check-recorder-script` also check the manual's `### 任务卡`
  count vs. the script's `screenshot` count, to catch the inverse case
  (manual has a task card but the script doesn't record it)?
- Should `build_recorder_template` auto-fill `narration: [...]` from
  the manual's step list? Risk: the LLM gets a wrong "default" voice /
  tone that doesn't match the user's intent.
- Should we add a `--strict-narration` CLI flag to `run_script` (not just
  the `_preflight_narration_coverage` API)?
