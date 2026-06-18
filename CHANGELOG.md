# Changelog

Top-level changelog for the user-manual skill. The recorder opt-in
plugin (`recorder/`) has its own changelog at `recorder/CHANGELOG.md` —
versioned in lockstep with the main skill.

## 0.3.2 (2026-06-18) — video narration (TTS voiceover)

### Hotfix: `tts.synthesize` now refuses to be called from a running event loop

v0.3.2 initial release had a silent bug: `synthesize()` inside a running loop
returned a non-awaited `asyncio.Task` (fire-and-forget), so the mp3 files
were never on disk when downstream code tried to read them. The error was
swallowed by `try/except` in `script._apply_narration` and surfaced as a
"WARNING: narration failed for video 'demo-flow' (FileNotFoundError: ...)"
on stderr — silent enough to miss in casual review.

**Fix** (recorder commit, same release):
- `tts.synthesize` is now strict: raises `RuntimeError` loudly if called from
  inside a running loop, with hint to use `await tts.asynthesize(...)` instead.
- `tts.asynthesize` (new) is the async API that recorder uses internally.
- `tts.new_semaphore(value=N)` returns a fresh `asyncio.Semaphore` for callers
  that want cross-call concurrency control.

**New tests** (regression coverage for the bug):
- `TestTTSAsync.test_asynthesize_writes_mp3` — happy path of async API
- `TestTTSAsync.test_synthesize_from_running_loop_raises` — guards the bug
- `TestTTSAsync.test_synthesize_outside_loop_still_works` — sync API preserved
- `TestTTSAsync.test_new_semaphore_returns_usable_semaphore` — semaphore usable

End-to-end pipeline now verified: real Playwright recording + `narration`
field → mp4 with H264 + AAC voiceover, narration_seconds=3 segments,
narration_gap_s=1.5, silent backup preserved, stderr empty.


### recorder 插件:edge-tts + ffmpeg mux

The recorder can now add **Chinese / English voiceover** to a recorded video
automatically. Add a `narration` list to your `video_stop` step:

```json
{"action": "video_stop", "name": "create-employee",
 "narration": ["打开系统管理。", "点击新增用户。", "点击保存。"]}
```

The recorder synthesizes each segment with `edge-tts` (Microsoft Edge online
TTS, no API key, no auth), concatenates them with configurable silence gaps
(default 2.0s), then muxes the audio onto the recorded video with ffmpeg. The
output is one mp4 with synchronized voiceover.

**Failure modes (designed, not accidental):**
- `edge-tts` not installed → recorder logs warning, keeps silent video
- Network down / Edge TTS rate-limited → retries 5x with exponential backoff
- Recording longer than narration → video tail trimmed (`-t audio_dur`)
- Recording shorter than narration → video looped (`-stream_loop -1`)

**New CLI subcommands** (also available standalone):
- `python3 -m recorder_plugin.cli tts-synth <text> --out PATH`
- `python3 -m recorder_plugin.cli concat-narration <seg1> <seg2> [...] --out PATH`
- `python3 -m recorder_plugin.cli mux-audio <video> <audio> --out PATH`

**SKILL.md changes:**
- §2.6.1 new: "操作旁白(narration)" — field reference + 完整示例
- §4 task card template: optional 9th field `narration` documented
- §7 helper table: 3 new recorder subcommands

**New dependencies** (recorder-only, per CONTRIBUTING.md opt-in exemption):
- `edge-tts >= 6.1, < 8.0` (rany2, 11k+ stars, MIT, no API key)

**New tests:** `tests/unit/test_narration.py` — 19 cases covering TTS synthesize,
voice override, silence gap generation, concat with/without gaps, mux with
audio-longer/audio-shorter, error paths, CLI subcommand dispatch.

**Lessons learned** (v0.3.2 round 2):
- `-stream_loop -1 + -shortest` produces unpredictable durations (10s+ for 8s/5s pair).
  Fix: drop `-shortest`, use `-t <audio_dur>` explicitly. Both "long" and "short"
  audio cases converge to exactly `audio_dur` output.


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


## 0.3.1 (2026-06-13) — validate-output stops lying + §14 early-fail

### validate-output 真查文件存在

The 6th check ("screenshot count") only counted `![alt](path.png)`
mentions in the markdown text. An LLM agent could pass with 26
placeholder references pointing to non-existent files — which is
exactly what the eval agent's grc_claude2_副本 did, returning
"6/6 OK" with 0 actual screenshots.

Added a 7th check **"screenshot files exist"** that resolves each
`![alt](path.png)` reference to an absolute path (relative to the
manual file) and verifies the file is on disk. Reports
`present/total (X missing: [...])`. Skips http(s)/data URIs and
strips query strings. With `--strict`, missing files cause exit 1.

### `check-recording-readiness` subcommand + init-skill 自动 banner

The previous "validate-output catches missing files" was a reaction.
The new check is **proactive**: at `init-skill` time (and via
`python3 -m manual_helper check-recording-readiness [root]`),
probe 5 things:

1. `playwright` Python module importable
2. `ffmpeg` on PATH
3. Playwright Chromium downloaded
4. Dev server reachable on any of `[8080, 5173, 3000, 4200, 8000, 80]`
5. Manual `[SCREENSHOT:]/[VIDEO:]` placeholders have files on disk

Status aggregation: any FAIL → red (exit 2), any WARN → yellow
(exit 1), all OK → green (exit 0). Each non-OK check carries a
`fix` string telling the user what to do. init-skill auto-prints
the banner to stderr when readiness is yellow/red (silent on green).

Real-world proof on eval agent's grc_claude2_副本:
```
=== Recording Phase Readiness (🔴 BLOCKED) ===
  ✅  playwright Python module: playwright is importable
  ✅  ffmpeg binary: ffmpeg 8.1.1
  ✅  Playwright Chromium: Chromium found in playwright cache
  ⚠️   dev server: None of [8080, 5173, ...] responded
  ❌  manual placeholders vs. files: 26 placeholders, 26 missing
```

## 0.3.0 (2026-06-12) — mapping `alt` 字段

v0.2.x mapping values were always bare strings, and the alt text
inside `![...](path)` defaulted to the mapping key — so `01-list`
produced `![01-list](screenshots/01-list.png)`. Screen readers read
out the kebab-case identifier, terrible for a11y.

v0.3.0 accepts a dict form with explicit alt text:
```json
{"01-list": {"path": "screenshots/01-list.png",
             "alt": "任务列表页（带分页器）"}}
```

**Backward compat**: bare string values still accepted, alt falls
back to the key. String + dict values can be mixed in the same
file. Invalid values (neither string nor `{path, alt}` dict) are
now reported in the missing list with a clear reason, not silently
producing `![key](None)`.

## 0.2.4 (2026-06-12) — agent-mediated vision + 3-party audit fixes

### Architectural refactor: agent-mediated vision, zero LLM deps

The recorder no longer calls any LLM API directly. AI vision annotation
is fulfilled by the agent loop using whatever model the harness
provides (Claude in Claude Code, GPT-4o in Codex, Llama-3.2-vision
in Ollama, etc.). Zero provider lock-in, zero double-billing.

- Removed: `anthropic` SDK calls, `ANTHROPIC_API_KEY` requirement,
  `anthropic` pip dep.
- Added: `recorder_plugin.vision` request/response protocol —
  recorder writes `.ai_annotation_request_*.json`, the agent
  fulfills via its own LLM, recorder applies Pillow annotation.
- New CLI subcommand: `apply-ai-responses <output-dir>`.

### 3-party audit round 2 (15 must-fix items)

After the v0.2.4 release, a 3-party review (hostile code-reviewer
+ end-to-end operator-reviewer + recorder owner) iterated on the
implementation. Round 1 produced 16+13=29 findings; round 2
(convergence) yielded 15 must-fix items, all addressed:

- F1: `count=1` only replaced first placeholder occurrence (multi-instance bug)
- F2: AI ANNOTATE plain-name mapping silently dropped
- F3: TODO prompt warning needed `import sys` (lost warning)
- F5: CI hello-world Playwright was insufficient — added real `pytest tests/unit/`
- F6/I8: CHANGELOG corrected dot-prefix `.ai_annotation_response_`
- F7: deleted unused `image_exists` field
- F8: `get_image_size` catches `UnidentifiedImageError`
- F9: `--apply-mapping` writes via tmp + rename (POSIX-atomic)
- F10: `schema_version` actually checked (refuses unknown/missing)
- I7: SKILL.md "12 step actions" → "10" (matches actual code)
- I9: `apply_response` reports `skipped_invalid_count`
- I11: placeholder regex supports multi-segment names (`v1.2-heatmap`)
- I12: `skipped_missing_response` vs `skipped_invalid_response` distinct
- I14: report distinguishes unique mapping keys from instance count
- N5: CHANGELOG test count updated to actual

### 3-party audit round 3 (C1-C6, H1-H5, M1-M4, L1-L4)

- **C1**: `import sys` in script.py (TODO-prompt warning was NameError'd)
- **C2**: `os.fsync` in `state.atomic_write_json` (power-loss durability)
- **C3**: webm aliasing fix (back-to-back video sessions)
- **C4**: `set_viewport` dispatch (previously in ALLOWED_STEP_ACTIONS but no elif branch)
- **C5**: INSTALL.md verify command now actually launches Chromium
- **C6**: CI uses `python -m playwright install` (not bare npm-global)
- **H1**: `validate_slice` logs warnings on failure (was silent False)
- **H2**: `recording_page.close()` timeout (was hangable)
- **H3**: SKILL.md playwright version range corrected
- **H4**: TOTP drift override documented
- **H5**: `apply-ai-responses` status contract documented
- **L2-L4**: stale version refs and broken Python range fixed

## 0.2.3 (2026-06-11) — §14 recording phase

Added the recording phase as a first-class skill section. The
recorder opt-in plugin (Playwright + Pillow + ffmpeg) is now
documented in `recorder/SKILL.md` with a 10-step action schema
(navigate / click / type / wait_for / screenshot / login /
video_start / video_stop / set_viewport / ai_annotate).

Added `scripts/manual_helper.py record-manual` subcommand with
three deterministic primitives:
- `record-manual <manual.md>` — scan and report placeholders
- `--generate-template <out>` — emit recorder script template
- `--apply-mapping <json>` — replace placeholders with real assets

## 0.2.2 (2026-06-11) — forgiving validate, smarter extract, scaffold personas

- `validate-output.py` 6 hard checks made more forgiving of LLM
  natural-language variance (case-insensitive, code-fence-aware,
  Chinese + English role-matrix synonyms)
- `extract-tasks.py` smarter: distinguishes real task candidates
  from "current issues" / "future ideas" sections
- `init-skill` scaffolds default `personas.json` from a template
  (was: hard-fail if missing) — friendly first-run, with a
  prominent stderr reminder to customize

## 0.2.0 and earlier

See git history: `git log --oneline -- docs/` and the recorder
plugin's own changelog at `recorder/CHANGELOG.md`.
