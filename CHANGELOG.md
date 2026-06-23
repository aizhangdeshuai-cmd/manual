# Changelog

Top-level changelog for the user-manual skill. The recorder opt-in
plugin (`recorder/`) has its own changelog at `recorder/CHANGELOG.md` —
versioned in lockstep with the main skill.

## 1.0.2 (2026-06-23) — file:// images and videos now actually load

Followup to v1.0.1: the build_standalone output contained real
`<img src="../screenshots/foo.png">` and `<source src="../videos/
foo.mp4">` tags, but when the .html file is double-clicked
(`file://` mode), browsers **refuse to load relative-path images
and videos** for security. Users saw a "manual with no images,
no videos" even though the file was technically correct.

v1.0.2 adds `_inline_assets_to_data_urls()` to
`build_standalone`. It walks the inlined .md blocks, finds every
`![alt](path.png)` markdown image and every `<source>/<video>/
<img> src="path.mp4"` tag emitted by `_convert_video_links_to_html`,
reads the file, and rewrites the path as a `data:image/png;base64,...`
or `data:video/mp4;base64,...` URI. The .html now contains the
binary inline, so it works under `file://` and offline.

### What changed

- `scripts/manual_helper.py: _inline_assets_to_data_urls()` new helper.
  Resolves paths relative to the .md file's directory, with fallbacks
  to `screenshots/` and `videos/` subdirs (since the build_standalone
  output is in `<project>/docs/user-manual/` and .md files reference
  `../screenshots/...`).
- `build_standalone()` calls it AFTER `_convert_video_links_to_html`
  so the freshly-emitted `<source src=...>` tags also get inlined.

### Manual probes (grc project)

- Before: 0 data: URLs in user-manual-standalone.html. 28 broken
  relative-path image refs. 28 broken relative-path video refs.
- After: 42 data:image URLs + 6 data:video URLs in
  user-manual-standalone.html. All 28 PNG + 6 MP4 references
  resolve to inline base64. The file is now self-contained and
  works under `file://`.

### Tests

- 59/59 pass in `scripts/tests/{test_manual_helper,test_validate_output}.py`
  (no test changes needed; existing fixtures don't exercise
  build_standalone with assets).

## 1.0.1 (2026-06-23) — hard-gate the things the LLM kept forgetting

Audit of grc project (regenerated 2026-06-23 with v1.0.0) found
three quality issues that v0.5.x documented as "rules" but the
LLM kept ignoring. v1.0.1 promotes all three to top-level
`validate-output.py` hard-gates so the LLM cannot silently degrade
the deliverable.

### What changed

1. **P0: 视频在 viewer 中可播放** (§2.6). v1.0.0
   declared `必须有真视频加旁白` but the
   template never rendered the markdown `[VIDEO: x](path.mp4)`
   form into an HTML5 `<video controls>` element — the user
   saw dead text. v1.0.1 adds a `convertVideoLinksInMd()` step
   in the template + a `_convert_video_links_to_html()` step in
   `build_standalone` so the `.html` file contains real
   `<video controls><source src="..."></video>` tags literally
   (no JS required to see the player).

2. **P1: 目录空 (§3 row 4).** v0.5.2 said
   `§目录 必须填 5-10 个错点链接`,
   but the LLM kept emitting `<!-- toc -->` placeholders. v1.0.1
   adds `validate-output.py` 9th check (`directory_anchors`):
   the `## 目录` section must contain ≥ 5
   `- [<title>](#<anchor>)` lines, otherwise the manual FAILS.
   SKILL.md §3 row 4 upgraded to a v1.0.1 hard-gate callout.

3. **P1: 任务卡 heading 格式 (§4).** v0.5.2 said
   `### 任务卡 N: <title>`, but the LLM kept writing
   `### 创建合同` without the prefix. v1.0.1 adds
   `validate-output.py` 10th check (`task_card_headings`): the
   manual must have ≥ 1 well-formed `任务卡 N:` heading
   AND the numbers must be sequential (1, 2, 3, ...). SKILL.md
   §4 upgraded to a v1.0.1 hard-gate callout.

### Tests

- 27/27 in `scripts/tests/test_validate_output.py` pass
  (after GOOD fixture updated to include §目录 + 任务卡 1:).
- 86/86 in `scripts/tests/{test_validate_output,test_manual_helper,
  test_record_manual}.py` (the 5 `test_recording_readiness.py`
  fails predate v1.0.0 — recorder deps are installed on this host
  so readiness is green, not yellow/red as those tests expect).

### Manual probes

- 5/5 grc project manuals now FAIL `validate-output.py --strict`
  on `directory_anchors` and `task_card_headings` checks, as
  expected (these are now hard gates, not soft guidance).
- `build_standalone` on grc project emits 31 `<video controls>`
  tags (vs 0 before), one per task-card video reference.

## 1.0.0 (2026-06-23) — BREAKING: drafts are no longer a deliverable

**User requirement (2026-06-23)**: "运行这个技能后，生成的手册要有图片要有视频（加旁白）".

v0.5.4 introduced a `skip` mode that allowed LLM agents to deliver a
manual with `待补资产清单` (asset checklist) at
the bottom instead of recording real assets. In practice every
project used it, producing manuals with 100% broken image refs.
v1.0.0 removes the option entirely. There is no longer any way to
deliver a user-manual skill artifact that lacks real screenshots
or narrated videos.

### Breaking changes

1. **§14 `skip` mode removed.** Only `record` and `screenshot-only`
   are valid recording modes. The `待补资产清单` section
   and its corresponding `validate-output.py` logic are gone.
2. **`init-skill --allow-blocked` removed.** The flag is now an
   error. If the dev server is unreachable after auto-install,
   `init-skill` exits 2 with a "fix the environment" menu.
3. **`record-and-replace --allow-blocked` removed.** Same error
   path. URL-unreachable in preflight is a hard FAIL, not WARN.
4. **SKILL.md description** updated to declare the hard requirement
   that every deliverable contains real screenshots + narrated
   videos, with no draft/skip opt-out.

### Preserved from v0.5.4

- §2.2 alt-text forbidden patterns (4 patterns, validated by
  `_check_placeholder_alt`).
- §5.4 double-gate (bash 7-check + `validate-output.py --strict`,
  both must exit 0 before LLM can claim the manual is complete).
- The 272-test suite (now 271 after removing the obsolete
  `test_init_skill_allow_blocked_exits_0`).

### Upgrade notes for existing projects

- Re-running this skill on a project that previously used
  `--allow-blocked` will now fail at the recording preflight. The
  user must start the dev server (or fix the recorder deps) and
  re-run.
- Manuals with `待补资产清单` sections from v0.5.4
  are obsolete: the section is no longer recognized as a valid
  finish state. The next run will replace the placeholders with
  real assets (or fail the recording preflight).

## 0.5.4 (2026-06-23) — 草稿不再当成品: skip-mode 待补资产清单 + alt 禁橢模式 + 硬门

Audit of grc project (2026-06-23) showed that v0.5.3-stamped manuals
were delivered as “finished” while still full of broken
`![占位:...]` references and 100% missing image files. Root
cause: the skill’s preflight checks treated URL-unreachable as
WARN, the alt-text had no anti-pattern gate, and §5.4’s bash
checks didn’t actually run `validate-output.py --strict` (which is
the only one that catches missing files). v0.5.4 closes all three
loopholes with one rule: **a manual with placeholders is not
finished** — either record, or write a `待补资产清单` section.

### What changed

1. **P2-A: §14 `skip` mode now mandates `待补资产清卑` section.**
   When the LLM agent picks option 3 (skip recording), the manual
   MUST end with `## 待补资产清单` listing every
   unreplaced `[SCREENSHOT:]`, `[VIDEO:]`, `![占位:...](path)`
   reference. `validate-output.py --strict` will FAIL the manual
   otherwise. The agent must also surface this in its final reply.

2. **P2-B: §2.2 alt 禁橢模式 + `validate-output.py` 8th check.**
   Added `_check_placeholder_alt` to `scripts/validate-output.py`:
   it scans all `![占位:...]` / `![<TODO: ...>]` /
   `![系统截图]` / description-style alts and flags
   them. SKILL.md §2.2 hard rule updated with the 4 forbidden
   patterns. §5.4 bash 验证 6 now also runs the same check
   inline so LLMs running only the bash gate also catch it.

3. **P2-C: `--allow-blocked` flag on `record-and-replace`.**
   v0.4.0 made URL-unreachable a WARN, which LLMs ignored. v0.5.4
   makes it a hard FAIL with an explicit next-step menu
   (start dev server / pass --allow-blocked / switch to skip mode).
   The new `--allow-blocked` flag downgrades the FAIL to WARN so
   the agent can deliberately write a draft manual. The draft
   must then include `§14 选项 3” 待补资产清单”.

4. **P2-D: §5.4 “double-gate” hard rule.** The bash 7 项
   (任务卡格式与内容质量) and
   `validate-output.py --strict` (文件系统 + alt 质量)
   are BOTH required to exit 0 before the LLM can claim the manual
   is complete. The agent must paste the `hits=N/threshold=M` numbers
   in its final reply / commit message.

### Why

The v0.5.0–v0.5.3 skill let an LLM agent produce 5 manuals with
**98 broken image refs** and call them done. v0.5.4 makes that
impossible: either record (placeholders become real files), or
declare a draft (the `待补资产清单` section
makes the gap explicit and blocks validate-output from passing).
The grc project’s existing manuals are still drafts; they need a
re-run of the skill to pick up the new gates.

### Tests

- 272/272 pass (133 scripts + 139 recorder unit; +1 vs v0.5.3 for
  the new `test_placeholder_alt_flags_lazy_alt_text`).
- Manual probes:
  - 4 forbidden alt patterns all caught by `_check_placeholder_alt`
  - `record-and-replace --allow-blocked` continues past preflight FAIL
  - `record-and-replace` without flag exits 2 with explicit menu
  - §5.4 bash 验证 6 catches `占位:` alts in addition to validate-output.py

## 0.5.3 (2026-06-23) — audit fix pass: regex + null host + narration type

Three P1 bugs surfaced by independent skill review on 2026-06-23:

- `scripts/validate-output.py`: `7-field hits` regex now matches BOTH
  `### 步骤` (legacy) and `#### 步骤` (current SKILL.md §4 template).
  Before, manuals strictly following v0.5.2 §4 only got 4 hits instead
  of the required ≥ 6, and only passed because the OTHER 5 keywords
  happened to be over-represented.
- `scripts/manual_helper.py:_infer_target_url`: handles `host: null` /
  empty / 0 by falling back to `<TODO: host>`. Before, it produced
  `http://None:8080` and the recorder would try to connect to a
  non-resolvable hostname.
- `recorder/recorder_plugin/script.py:_preflight_narration_coverage`:
  now rejects `narration: "string"` (a non-list truthy value) as
  missing. Before, the preflight was OK but `_apply_narration` silently
  skipped via `isinstance(narration_segs, list)`, producing silent
  video — exactly the failure mode v0.5.1 was supposed to fix.

Also:
- §5/§10/§11 of SKILL.md updated to clarify Citations is opt-in
  (v0.5.2 was documented but the prompt flow still said "always
  update Citations"). §3 chapter table now lists Citations as row 12
  (opt-in).
- example/dryrun-sys-user-manual.md `## 目录` filled with 13 anchor
  links (was: empty + comment).

## 0.5.2 (2026-06-23) — strict task-card format, opt-in Citations, filled 目录

Audit 2026-06-23 of grc project's regenerated manuals found 4
recurring quality issues that the LLM kept reintroducing. All
four are 'format' issues, not content — fix them in the skill's
markdown templates so the next LLM run gets them right.

1. **Task card heading format (P1#2)**: LLMs were emitting
   `### 创建合同` instead of `### 任务卡 1: 创建合同`. The
   section §4 template used `### <动词开头任务名, 如"...">`
   which left room for the LLM to drop the '任务卡 N:' prefix.
   Fixed: §4 template now uses `### 任务卡 1: <title>` as the
   literal template, plus a new 'v0.5.2: 任务卡 heading 严格格式'
   block listing 3 failure anti-patterns.
2. **Opt-in Citations**: User reported on 2026-06-23 that
   the '## Citations' section was noise at the bottom of every
   page (it tracks artifact SHAs for code review, not end-user
   reference). Fixed: §6 now says Citations is OFF by default,
   turned on by setting `include_citations: true` in
   `manual-config.json`.
3. **目录 must be filled**: §3 chapter table said
   'viewer 自动生成, 文档内标注即可' which let the LLM emit
   an empty `## 目录` heading. Fixed: §3 row now says LLM must
   fill 5-10 anchor links.
4. **#### 步骤 wrapper**: Some LLM runs dropped the
   `#### 步骤` heading and just used bare `1. 2. 3.' lists.
   Fixed: §4 adds a 'v0.5.2: 步骤块必须用 #### 步骤 包裹'
   block with success/failure examples.

Test: 271/271 (132 scripts + 139 recorder). All pass.

## 0.5.1 (2026-06-23) — surface missing narration field (no more silent videos)

Audit 2026-06-23 found that recorder script's 'narration' field is
opt-in, and the 'opt-in' framing was indistinguishable from 'silent
failure' in practice. When an LLM agent forgot the field, the
recorder silently produced a silent mp4 with no warning, no exit
code change, and no signal of why.

This change makes the silent-failure case loud at three layers:
1. Runtime preflight in `run_script()` (`recorder/script.py:417`).
2. Skill-side check in `cmd_check_recorder_script` (new check #5 NARRATION COVERAGE).
3. `_apply_narration` end-to-end test coverage (4 new tests).

## 0.5.0 (2026-06-23) — auto-generate recorder scripts + TOC for lazy chunks

### Headline: close the "recorder script is broken" loop

Two production bugs that v0.4.0 didn't catch:

1. **build_recorder_template emitted `<TODO: ...>` everywhere** —
   the LLM agent had to hand-fill URL, output_dir, captions,
   auth_env names, click selectors. In practice, agents shipped
   the template with TODOs unfilled, ran the recorder, and
   produced useless videos (e.g. lg-contract-flow.mp4 = 4.88s of
   login page + 28s of looped frames).

2. **buildToc() in the HTML viewer only saw the first H2** —
   `els.article.querySelectorAll("h2, h3")` only matched the
   first chunk's headings; subsequent chunks were replaced with
   `<div class="chunk-placeholder">` and their H2s/H3s were
   stuck in `pendingChunks` (lazy-rendered on scroll). The
   sidebar TOC showed only 1 entry.

v0.5.0 fixes both.

### Added — auto-fill recorder template from project context

`build_recorder_template(manual_name, placeholders, manual_path=..., project_root=...)`
now auto-fills from project context when given:

- **`url`**: read from `manual-config.json` `project.host + project.port`
- **`output_dir`**: domain inferred from `manual_path` filename
- **`auth_env`**: env var names inferred from manual_name (`legal-user-manual` -> `$LEGAL_USER`, `$LEGAL_PASS`)
- **step `navigate.url`**: per-domain conventional default (`/contracts` for legal, `/users` for sys, etc.)
- **step captions**: real captions extracted from each task card's `### 步骤` numbered list

Still TODO (agent must fill): click selectors — we cannot infer
CSS selectors from spec text. The fix hint printed by
`check-recorder-script` tells the agent what to do.

### Added — `check-recorder-script` subcommand

New helper that validates a recorder script JSON before the
agent invokes the recorder. 4 checks:

1. **No `<TODO>` placeholders** — FAIL if any remain
2. **Target URL reachable** — HEAD probe
3. **Auth env vars set** — FAIL if any `$VAR` in `auth_env`
   is unset, with the exact env var name + the
   `lg-contract-flow.mp4` failure pattern as the fix hint
4. **Steps have real content** — empty selector / url /
   video_start/video_stop imbalance all FAIL

`record-and-replace` runs this automatically before recording
(skip with `--skip-script-check`).

### Added — `record-and-replace --auto-generate-script`

When no `--script` is given, generates a v0.5.0 template from
the manual + project_root (= cwd) and continues with that
script. The auto-generated file lives at
`<manual>.recorder.json` next to the manual.

Use case: agent says `python3 -m manual_helper
record-and-replace <manual.md> --auto-generate-script` and
gets a working scaffold without hand-writing JSON.

### Changed — viewer TOC includes headings from pendingChunks

`buildToc()` now merges:
- (a) DOM headings from the first rendered chunk
- (b) Virtual H2/H3 entries from `pendingChunks` (extracted
  from chunk tokens; same data the chunks will render when
  scrolled into view)

Click handler for virtual H2 entries: `requestAnimationFrame`
wrapper around `getElementById` so the real (DOM-rendered)
h2 is targeted after `placeholder.replaceWith(wrap)` settles.

### Tests

`scripts/tests/test_manual_helper.py`: 110 → 128 tests
(+18 new for CheckRecorderScriptTests / BuildRecorderTemplateV2Tests
/ RecordAndReplaceAutoGenTests / InitSkillAutoRegenTests
/ RecordAndReplaceAutoRegenTests). All pass.

### Migration

- v0.4.x manuals: keep using `validate-output.py` without
  `--unique` — no behavior change.
- New runs: pass `--auto-generate-script` to
  `record-and-replace` and skip the hand-template step
  entirely.
- The viewer template changed (TOC fix) — but you do NOT
  need to manually re-build standalone.html after upgrading.
  Both `init-skill` and `record-and-replace` now auto-regenerate
  `<proj>/docs/user-manual/user-manual.html` if the shipped
  template is newer than what's on disk. Opt out with
  `--skip-viewer-regen` on `record-and-replace` (e.g. CI
  environments that ship a pinned viewer).

### Added — auto-regenerate viewer on `init-skill` and `record-and-replace`

`init-skill` and `record-and-replace` both call
`regenerate_html_if_stale(<proj>/docs/user-manual/user-manual.html)`
after their main work. Behavior:

- **template version newer than on-disk** → copy template over,
  log `viewer: regenerated <path> (template v<N>)` to stderr
- **on-disk missing** → create from template, log
  `viewer: created <path> (template v<N>)` to stderr
- **on-disk up-to-date** → no-op, no log line
- **failure** (read-only project root, malformed version
  marker) → log `viewer: auto-regen skipped (<ErrorType>: <msg>)`,
  continue without aborting the command

This is the fix for the previous session's "1-entry sidebar TOC"
regression: the user no longer has to remember to re-build the
viewer after a skill upgrade that includes template fixes. The
new buildToc() + auto-regen pair means upgrades Just Work.

`record-and-replace` also accepts `--skip-viewer-regen` for
CI environments that ship a pinned viewer.



### Headline: catch "looks fine, isn't fine" outputs automatically + force recorder to run

The eval report from 2026-06-13 flagged 3 P0/P1 issues that the LLM
kept re-introducing on each run:

1. **Citations table filled with `(auto)` placeholders** — the
   `fill-citation-shas` helper exists in `manual_helper.py` but the
   LLM agent kept skipping it, leaving 14 lines of `(auto)` per
   manual.
2. **Same screenshot bytes referenced by 2+ filenames** — recorder's
   `_handle_screenshot` doesn't require an intervening `click` step
   between two `screenshot` actions, so back-to-back screenshots of
   the same page produce byte-identical PNGs (e.g. `dashboard-home.png`
   == `module-map.png` in the overview manual).
3. **Q&A sections too short** — typical 2-5 Qs per manual, no
   category hit the recommended 3-per-class minimum.
4. **(NEW) Recorder §14 was a 5-step manual flow that the LLM agent
   consistently skipped in practice.** The agent would write the
   manual with placeholder-style `![xxx](path.png)` references that
   "look right" but never invoke the recorder, never run the
   mapping, never produce real assets. The user only noticed at
   the end, when the manual had no real screenshots despite the
   LLM claiming completion.

v0.4.0 hardens all four with **automated checks + a one-shot
command** so the LLM cannot silently produce a "passes validate
but is actually broken / unrecorded" output.

### Added — `validate-output.py` 8th check (opt-in `--unique`)

### Headline: catch "looks fine, isn't fine" outputs automatically

The eval report from 2026-06-13 flagged 3 P0/P1 issues that the LLM
kept re-introducing on each run:

1. **Citations table filled with `(auto)` placeholders** — the
   `fill-citation-shas` helper exists in `manual_helper.py` but the
   LLM agent kept skipping it, leaving 14 lines of `(auto)` per
   manual.
2. **Same screenshot bytes referenced by 2+ filenames** — recorder's
   `_handle_screenshot` doesn't require an intervening `click` step
   between two `screenshot` actions, so back-to-back screenshots of
   the same page produce byte-identical PNGs (e.g. `dashboard-home.png`
   == `module-map.png` in the overview manual).
3. **Q&A sections too short** — typical 2-5 Qs per manual, no
   category hit the recommended 3-per-class minimum.

v0.4.0 hardens all three with **automated checks** so the LLM
can't silently produce a "passes validate but is actually broken"
output.

### Added — `validate-output.py` 8th check (opt-in `--unique`)

- New flag: `python3 scripts/validate-output.py --unique <file.md>`
  runs the 8th check `screenshot unique (no duplicate content)`.
- Default OFF: existing manuals that intentionally reuse assets
  (e.g. logo) are not retroactively broken.
- New flag: `--unique-allow=logo.png,branding.png` — whitelist
  intentionally shared files by basename.
- The check SHA256s every referenced PNG, groups them by hash,
  and flags any hash referenced by 2+ distinct filenames.
- Performance: ~100ms for 50 images, no external deps.
- 5 new unit tests cover: distinct pass, duplicate fail, opt-out,
  whitelist, missing-file skip.

### Added — `validate-output.py` regression: `(auto)` Citations

- SKILL.md §5.4 now treats `(auto)` in the SHA256 column as a
  hard FAIL. The shell snippet for §5.4 got a 7th grep:

  ```bash
  AUTO=$(grep -c "(auto)" "$F")
  [ "$AUTO" -eq 0 ] || { echo "FAIL: Citations 仍有 $AUTO 个 (auto) 占位"; exit 1; }
  ```

- LLM writing checklist now marks `fill-citation-shas` as
  **必跑** (was optional before).

### Changed — SKILL.md §2.5 Q&A minimums

- Each Q&A category now requires **≥ 3 questions** (was implicit).
- The total Q&A per manual target is now **≥ 12 questions** across
  4 categories (was 2-5 typical, sometimes 8).

### Tests

- `scripts/tests/test_validate_output.py`: 98 → 103 tests
  (+5 for the new unique check class)
- All other test suites untouched and passing.

### Why these changes

The 2026-06-13 evaluation report (file:
`grc_claude2_副本/docs/user-manual/SKILL_EVALUATION_REPORT.md`)
found that **"everything passes validate, but the user still gets
a broken manual"** was the dominant failure mode. The fixes above
shift three quality bars from "review must catch" to "validate
must catch" — closing the loop on the eval report's top 3
remaining issues.

### Migration

- Existing v0.3.x manuals: keep using `validate-output.py` without
  `--unique` — no behavior change. The 7 base checks still pass.
- New runs / CI: pass `--unique` after generation to catch
  duplicate-content screenshots.
- Citations `(auto)` is now a hard FAIL — run
  `manual_helper fill-citation-shas` on existing manuals once
  to bring them up to spec.

### Added — `record-and-replace` (v0.4.0 — §14 in one command)

`SKILL.md §14` used to be 5 manual steps the LLM agent had to
remember to run in order:

  1. record-manual <md>                           # scan placeholders
  2. record-manual <md> --generate-template       # emit recorder script
  3. python3 -m recorder_plugin.cli run <script>  # ACTUAL RECORDING
  4. (build mapping JSON by hand)
  5. record-manual <md> --apply-mapping <json>    # wire assets in

In practice, agents skipped 3-5 ("the manual is already written,
just commit it"). v0.4.0 collapses the whole flow to:

```bash
python3 -m manual_helper record-and-replace <manual.md> \
    --script <recorder-script.json>
```

Internals:
- **6 pre-flight checks** (recorder_plugin importable, playwright
  module, Chromium downloaded, ffmpeg, target URL reachable, env
  vars set) — fails loudly with the exact fix command for any miss
- **Runs the recorder** (subprocess, 600s timeout, stderr streamed)
- **Auto-builds the mapping** by walking the recorder's output dir
  and matching filename stems to placeholder names
- **Applies the mapping** via `record-manual --apply-mapping`
- **Runs `validate-output.py --unique`** to surface any duplicate-
  content screenshots the recorder produced (catches the v0.4.0 8th
  check failure pattern)
- Returns 0 (clean) / 1 (validate failed) / 2 (recorder failed) /
  3 (dry-run). One command, one exit code, no step to forget.

Use `--dry-run` to preview the mapping without actually recording
(useful in CI before the dev server is up).

### Changed — `init-skill` now exits 1 on unrecordable projects

Previously, `init-skill` ran the readiness check but **printed it
informationally** and always returned 0. The LLM agent would then
write the manual anyway, with placeholders, and the user would only
discover the recorder is broken at the end of §14.

v0.4.0:
- `init-skill` AUTO-INSTALLS missing deps (`pip install playwright` +
  `python3 -m playwright install chromium`) — single command brings
  a fresh project to "ready"
- If post-install readiness is still RED and `--allow-blocked` is
  not passed, exits **2** (RED) with a loud error explaining the
  user has 3 options (fix issues, `--allow-blocked`, `--no-install`)
- New CLI flags: `--no-install` (CI environments with deps via
  other channels) and `--allow-blocked` (intentional "write manual
  first, record later")
- Dev-server-only RED is **not** auto-installed (we can't start
  the user's app server) but is surfaced clearly so the user knows
  the recorder is ready, only the dev server is not

### Tests

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
