
## 1.4.0 (2026-06-27) — regenerate_standalone_if_stale: detect stale inlined blocks, force rebuild

The ehr 2026-06 standalone HTML shipped WITHOUT `data-title`
attributes on the inline `<script>` blocks, even though the
wrapper template had been upgraded to v25 (which corresponds
to the v2.3.1 viewer fix that added the attribute). The cause:
`regenerate_html_if_stale()` only checks the wrapper template
version; the inlined blocks are produced by a separate
`build_standalone()` call and have no version marker of their
own. So the wrapper upgrade (template v24 -> v25) was
correctly detected, but the inlined body — built with the OLD
`build_standalone()` that did not write `data-title` — was
left untouched.

Net effect: dashboard cards rendered `user-manual.md`,
`report-user-manual.md`, `blacklist-user-manual.md` instead of
the Chinese frontmatter titles, because the viewer's
`extractTitle()` regex couldn't match the inline markdown
(its `^---` anchor failed on the leading `\n` that
`build_standalone` writes after the `<script>` tag).

### What changed

- `scripts/manual_helper/html.py`:
  - New `regenerate_standalone_if_stale(html_out, md_paths,
    template_path=None) -> str`. Returns "created" | "unchanged"
    | "regenerated: <reason>". Three staleness signals:
      1. wrapper template version older than bundled template
         (mirrors the existing `regenerate_html_if_stale` check)
      2. any source .md has been modified after the inlined HTML
      3. the inlined `<script type="text/markdown">` blocks
         lack `data-title` (precise regex anchored to the block
         opening tag, so a `data-title="${...}"` in the viewer
         template's own code does not count as a satisfied
         contract)
- `scripts/manual_helper/cli.py`:
  - New subcommand `regenerate-standalone-if-stale` with the
    standard `<html-out> <md-path> [more...]` shape.
- `scripts/manual_helper/__init__.py`: re-export
  `regenerate_standalone_if_stale`.
- `scripts/tests/test_manual_helper.py`:
  - New `RegenerateStandaloneIfStaleTests` (6 cases):
    creates when missing, unchanged when fresh, inlined no
    data-title triggers rebuild, md newer than html triggers
    rebuild, wrapper stale triggers rebuild, CLI subcommand
    rebuilds.
- `SKILL.md`:
  - §16.15 new: documents the failure mode (wrapper and
    inlined body versions can drift apart), the three
    staleness signals, the agent's §14 closing sequence now
    has an 8th step (regenerate-standalone-if-stale between
    write-recording-manifest and validate-output), and the
    relationship to v2.3.1 (v2.3.1 fixes the BUILDER to
    write data-title; v1.4.0 detects the OUT-OF-DATE OUTPUT
    and forces a rebuild).
- `CHANGELOG.md`: v1.4.0 entry.

### Why this is a real release, not "just an upgrade check"

The drift between wrapper-version-current and inlined-body-stale
is a failure mode that the existing `regenerate_html_if_stale`
function is structurally unable to detect (it only reads the
wrapper marker). Without v1.4.0, the only way to recover was
for the LLM agent to remember to manually `build-standalone`
after every template upgrade. That is a contract the agent
will forget, exactly as the ehr 2026-06 build demonstrates.
v1.4.0 makes the staleness detection automatic and adds it to
the standard CLI surface so CI can run it.

### Suite: 177 -> 183 tests, all green.

### Also in this release: backfill v2.3.1 viewer fix

v2.3.1 (the `data-title` attribute + `extractTitle` regex fix)
was prepared in the ehr 2026-06 audit but never landed in
this branch. v1.4.0 backfills it: the v2.3.1 patches that
apply cleanly (0005 viewer regex, 0007 build_standalone,
0008 viewer data-title preference) are now committed. The
two that don't apply (0006 CHANGELOG, 0009 SKILL.md) are
absorbed into the v1.4.0 CHANGELOG and SKILL.md updates
above; their substantive content is preserved.

## 1.3.0 (2026-06-27) — screenshot unique: invert-polarity flag, force default-on

Cosmetic / internal cleanup. Behaviour is unchanged from v1.1.0
(where `screenshot unique` was already the documented default).
This release fixes the flag-naming so the call site reads naturally
and so audit runs that drop `--unique` still get the check.

### What changed

- `scripts/validate-output.py`:
  - Module flag `UNIQUE_CHECK_ENABLED` renamed to
    `UNIQUE_CHECK_SKIP` (inverted polarity: True means skip).
  - main() now sets `UNIQUE_CHECK_SKIP = not unique` from
    `--no-unique`. Default is `False` (do not skip), so the
    check runs unconditionally without any flag.
  - Call site changed to `if not globals().get("UNIQUE_CHECK_SKIP",
    False):` — reads as a positive statement of intent.
  - Docstring bumped: 22nd check listed; v1.3.0 entry in the
    version history.
- `SKILL.md`:
  - §16.14 new: documents the cleanup, references the ehr
    2026-06 audit round 3 (4 groups of byte-identical
    screenshots: report-list-{toolbar,status-filter}, report-
    column-{drawer-open,list}, report-designer-{base,fields,
    filters,scope-card,scope-states} all SHA `b750cb64f25e`,
    report-viewer-{pager,sort} + report-viewer all SHA
    `d15a000fff84`), and gives the recorder-script fix recipe.
- `CHANGELOG.md`: v1.3.0 entry.

### Why this is its own release (vs. an unreleased edit)

The flag was already documented as default-on in v1.1.0, but
the implementation made the default depend on main() having
been called first. Test harnesses that imported
`validate-output.py` as a module and called `validate_file()`
directly would silently skip the check (UNIQUE_CHECK_ENABLED
uninitialized → False → branch skipped). The ehr audit ran
via the CLI subprocess so this didn't bite that audit, but
it would have bitten any test framework that exercised
`validate_file()` in-process.

The fix inverts the polarity so the uninitialized-flag case
behaves correctly (default = run, opt-out = skip). No
behaviour change for CLI users; in-process callers now get
the documented default.

### What v1.3.0 does NOT do

- Does not delete `--no-unique` (still a valid escape hatch
  for legacy reasons).
- Does not touch `screenshot_uses_annotated`'s `--annotated-
  relaxed` opt-out. That check has legitimate "I want the
  bare PNG AND the annotated one in a side-by-side" use cases
  that the relaxed flag serves. The ehr audit's screenshots
  are not offenders of this check (the alt texts do not match
  the "红框/箭头/..." keywords for the byte-identical groups;
  the alt texts describe distinct actions that the LLM thought
  were happening on different screens, which is itself a
  different bug — see `record_real.py` fix recipe in §16.14).
- Does not add a new "same image, different alt" detector.
  That would be v1.4.x work; for now, the byte-equality check
  + the alt-text keyword check + manual review of
  `report_recorder.py` are the right combination.

Suite: 177 → 177 tests (no test changes needed; behavior was
already correct under the CLI invocation path). Re-ran to
confirm: 177/177 green.

## 1.2.0 (2026-06-27) — manifest_disk_consistency + file_type_sanity post-gate checks

A second review of the ehr-generated manual surfaced two more
failure modes the v1.1.0 hard gate did NOT catch:

1. **Manifest lied about disk state.** The manifest listed 18
   screenshot paths but the corresponding files had been deleted
   from disk (rm -rf mistake, between v1.1.0 audit and this run).
   v1.1.0 only validated manifest *content* (schema_version,
   dev_server.reachable, totals.screenshots > 0) — never checked
   the actual asset inventory against `docs/user-manual/screenshots/`.
2. **The manual.md was actually HTML.** A copy/paste or rename
   misstep replaced `manual/user-manual.md` with the viewer's
   HTML template (4722 lines, 116KB). v1.1.0 hard gate passed
   (manifest existed; the gate doesn't read the .md content).
   v1.1.0's other regex-based checks happily matched `<h1>` as
   if it were markdown. The "manual" was invalid but every check
   said OK.

This release adds two post-gate checks that are cheap to run and
catch both failure modes at first sight.

### What changed

- `scripts/validate-output.py`:
  - New `_check_manifest_disk_consistency(md_path, text)`: reads
    `recording_manifest.json`, walks `assets.screenshots` /
    `videos` / `ai_annotated`, and verifies every path exists on
    disk. FAIL on `manifest_only` (manifest lies). WARN on
    `disk_only` (orphans — not a hard fail, but reported).
  - New `_check_file_type_sanity(md_path, text)`: cheap heuristic
    on the first 200 / 50 lines. Rejects HTML / XML / JSON /
    PDF / binary content masquerading as .md; also requires
    either YAML frontmatter or a top-level H1.
  - 21st and 22nd checks wired into `validate_file()`.
  - Docstring bump.
- `scripts/tests/test_validate_output.py`:
  - New `ManifestDiskConsistencyTests` (4 cases): manifest_only
    blocks, disk_only is warn-not-fail, consistent manifest
    passes, no-manifest is no-op (pre-flight gate owns that
    case).
  - New `FileTypeSanityTests` (4 cases): HTML blocks, valid
    markdown passes, no frontmatter-or-H1 blocks, XML blocks.
  - `test_json_mode` updated to expect 21 checks (was 19).
- `SKILL.md`:
  - §16.13 new: explains both checks, the ehr 2026-06 failure
    mode they each close, and the design trade-off (cheap
    defensive check vs. deeper content review that validator
    can't do).
- Suite: 169 → 177 tests, all green.

### What this does NOT catch (open for v1.3.x)

- LLM-generated "fake" Chinese that sounds right but describes
  the wrong UI affordance.
- Hallucinated permission matrices, fake error codes, wrong
  field types. v2.2.0 unfilled_template_terms catches the
  *obvious* template leftovers, but a sophisticated LLM can
  write prose that *looks* template-filled but is wrong.
- Markdown structure that follows the §3 / §4 contract but
  the prose is nonsense. §2.7.1 audience_leak catches
  developer-leak patterns; not the inverse (over-eager LLM
  writing plausible business text that isn't true).

These need human review on a sample basis. The skill is not
going to grow full coverage of "the LLM wrote something
wrong" — that is fundamentally a generation-quality problem,
not a contract problem.

## 1.1.0 (2026-06-27) — hard gate: recording phase must produce recording_manifest.json

A user audited the ehr-generated manual (`/Users/zhangdanyang/ehr/docs/user-manual/`)
and pointed out that every screenshot was a hand-drawn 80x60 grey PNG.
The markdown had correct alt text, the files existed on disk, every
existing validator check passed. The manual looked finished. It was
not. §14 ("recording phase") had been silently skipped — the LLM
agent writing the manual never drove a real browser, and there was
no machine-readable way to tell.

This release makes "§14 actually ran" a **machine-checked hard gate**.

### What changed

- `scripts/manual_helper/recording.py`:
  - New `write_recording_manifest(md_path, *, dev_server_url,
    screenshots_written, videos_written, recorder_cli_exit,
    recording_readiness_at_run, recorder_session_id) -> Path`.
    Emits `docs/user-manual/recording_manifest.json` containing
    schema_version, ran_at, manual path, recorder CLI exit code,
    dev server reachability + readiness status, and the full asset
    inventory (screenshots / videos / ai_annotated). See §16.11.
  - 2 new imports (`socket`, `datetime`/`timezone`).
- `scripts/manual_helper/__init__.py`: re-export `write_recording_manifest`.
- `scripts/manual_helper/cli.py`:
  - New subcommand `write-recording-manifest` with `--dev-url`,
    `--session-id`, `--recorder-exit`, `--screenshot` (repeatable),
    `--video` (repeatable). Probes readiness at run time and embeds
    the result in the manifest.
- `scripts/validate-output.py`:
  - New pre-flight `_check_recording_phase_actually_ran(md_path)`.
    Runs before any other check; on failure `validate-output`
    returns `{"preflight_blocked": True, ...}` and the CLI prints a
    multi-line pause banner (see §16.12) and `exit 2` — even without
    `--strict`. The banner enumerates the 6 §14 steps the LLM agent
    should have done, plus the `rm -rf docs/user-manual/screenshots/*`
    cleanup hint.
  - New `--no-hard-gate` escape hatch (tests / CI maintenance only).
    Documented as "CI should never pass this flag."
  - Docstring bump: 20th check listed.
- `scripts/tests/test_validate_output.py`:
  - New `RecordingPhaseActuallyRanTests` class (9 cases) covering:
    no manifest blocks (exit 2), --strict vs not, --no-hard-gate
    escape hatch, valid manifest passes pre-flight, zero-screenshots
    manifest blocks, non-zero recorder exit blocks, unreachable dev
    server blocks, wrong schema_version blocks, unreadable JSON
    blocks, banner enumerates the 6 recovery steps.
- `scripts/tests/test_manual_helper.py`:
  - New `WriteRecordingManifestTests` class (8 cases) covering the
    function and the CLI subcommand.
- `SKILL.md`:
  - §14末尾加 "v1.1.0 hard gate" 段(机器兜底,不是自觉)。
  - §16.11 新增:recording_manifest.json schema + 6 步收尾流程。
  - §16.12 新增:validator 硬闸 — 缺 manifest 直接 exit 2,暂停
    banner 全内容,`--no-hard-gate` escape hatch,以及"为什么
    §16.10 / §16.9 不够"的设计 rationale。
- Suite: 98 → 115 tests, all green.

### Why a hard gate (and not just better docs)

- §14 "no opt-out" was in the docstring since v1.0.0. The LLM agent
  that wrote the ehr 2026-06 manual read it, acknowledged it, and
  still skipped §14 because the markdown it produced LOOKED finished
  (correct alt text, 80x60 PNGs on disk, all existing checks green).
  A doc-only contract is enforceable by humans, not by tools.
- The other "image" checks (placeholder_url, placeholder_alt,
  screenshot files exist) cannot tell the difference between
  "recorder ran, here is a real screenshot" and "LLM drew a 100-byte
  grey PNG, here is a placeholder". They are necessary but not
  sufficient.
- `recording_manifest.json` bundles the missing signal: dev server
  was reachable at run time, recorder CLI exited 0, ≥1 screenshot
  was actually written, and the asset inventory is timestamped and
  namespaced to the persona. The validator can read it
  deterministically and refuse to call the manual a deliverable
  without it.

### Migration

- Existing projects: next `validate-output` run will FAIL at the
  pre-flight until §14 is run end-to-end. Plan for one
  recording-pass per persona, or pass `--no-hard-gate` for legacy
  CI maintenance only.
- The recorder skill is unchanged (it has always returned a status
  JSON on stdout). The LLM agent's job is to take that status,
  collect the asset paths, and feed them to `write-recording-manifest`.

## 2.3.0 (2026-06-26) — ehr audit round 2: anchor integrity, placeholder URL, task-card steps count

Audited the ehr-generated manual a second time and surfaced three more
defects that `validate-output.py` was not catching. The skill is
deployed to multiple projects now and the ehr project keeps being
the most honest reviewer. v2.3.0 hardens the contract on three
specific failure modes.

### Defects found in the ehr manual (validator previously said OK)

- **8 broken internal anchors in `user-manual.md`**: heading
  `### 任务卡 1: 确认当前公司` (space after colon) was paired with
  TOC link `#任务卡-1确认当前公司` (no space). The 4 task cards'
  TOC entries and 4 in-prose "相关任务" references all resolved to
  dead anchors. The user opens the viewer, clicks TOC, and lands on
  an empty `#` URL bar with no scroll. 8 anchors broken in one doc.
- **6 `https://placeholder.invalid/...` image references across 3
  manuals**: the ehr audit's `draft-for-review` mode used a remote
  placeholder URL for screenshots. `_check_screenshot_files_exist`
  silently skipped these because it only checks local relative paths
  (correct behavior for legitimate CDN URLs, wrong behavior for
  obvious placeholders). The manual shipped with 0 real PNGs and
  6 placeholders; no check caught it.
- **1 task card with 2 `#### 步骤` blocks**: report task card 9
  ("发布 / 停用报表") combined two operations into one card and
  used two step subsections. Defeats the viewer left-TOC navigation
  contract — the card shows up once, but renders two "步骤" nodes,
  each with its own screenshot set, without the LLM labeling them
  as separate operations.

### What changed

- `validate-output.py`:
  - New check 15 `broken_anchors`: collects all H1-H4 heading slugs
    via GFM slugify, scans all `](#slug)` references, flags any that
    don't resolve. Skips code-fence mentions so the SKILL doc can
    show failure examples.
  - New check 16 `placeholder_url`: scans `![alt](path)` /
    `[VIDEO: x](path)` / `<img src=...>` / `<video src=...>` /
    `<source src=...>`, flags any path matching `placeholder.invalid`
    / `example.com` / `todo.com` / `<TODO:>` / `<your-...>`.
    Skips code-fence mentions. Skips the `http://localhost:8088/`
    user-facing URL (per §2.7.1 类 7 whitelist).
  - New check 17 `task_card_steps_count`: per `### 任务卡 N:`
    block, count `#### 步骤` subsections; flag cards with != 1.
    Refactored `_split_by_headings` to do hierarchical splitting
    (block at level L ends at next heading with level ≤ L) so that
    the body of a card includes all its `#### 步骤` children.
  - Check count is now 19 (was 16).
- `SKILL.md`:
  - §16.9: anchor slug rules (GFM-style) + why the ehr audit broke
    8 anchors. Includes a slug table for the most common heading
    patterns so LLM agents can verify their TOC by hand.
  - §16.10: placeholder URL rule + the legitimate-vs-placeholder
    distinction. Explicitly allows `http://localhost:8088/` (the
    user-facing frontend URL per §2.7.1 类 7).
  - §2.1: clarified "one task card = one operation" with a
    cross-reference to §16 / check 17.
- `tests/test_validate_output.py`:
  - 12 new tests across `BrokenAnchorTests`, `PlaceholderUrlTests`,
    `TaskCardStepsCountTests` (4 tests each).
  - `test_json_mode` count updated 16 → 19.
  - Suite: 53 → 65, all green.

### Why these three and not more

The user reported 7 improvement items in the audit round. Of those,
items 1-2 (P0: broken anchors, placeholder URL) and item 4
(task card steps count) were strictly validators and got fixed.
Items 3 (Q&A H3 categories) and 5 (screenshot density per card)
are stylistic — the SKILL doc already prescribes them, and the
existing 7-field hits + visual-anchor checks catch the worst
violations. Forcing them with new strict-mode checks would
generate noise on otherwise-valid manuals. Left for v2.4 if a
project actually ships a Q&A-without-H3 manual that the current
rules don't catch.

Item 6 (screenshot density per card) is left as documentation in
§16.6, not as a check, because the legitimate use case is the
总览分册 (overview manual) which §2.6.1 explicitly allows to skip
screenshots and videos. A density check would need a per-module
opt-out and the value isn't worth the rule complexity.
## 2.2.0 (2026-06-26) — task-card video must live in `#### 演示视频`, never inside `#### 步骤`

Auditing the ehr manual alongside the recorder changes surfaced one more
structural issue: the LLM placed `[VIDEO: x](path.mp4)` *inline on a
step line* (e.g. `2. 点按钮 [VIDEO: 演示](flow.mp4)`), so the viewer
rendered a `<video>` card mid-paragraph, breaking the "watch the demo,
then follow the steps" reading order. v2.2.0 hardens the contract.

### What changed

- `validate-output.py`:
  - New check `video_outside_steps` (14th): scans every `###/#### 步骤`
    block delimited by the next heading and FAILs if any `](.mp4)`
    reference is found within.
  - Check count is now 14.
- `SKILL.md`:
  - §2.6 rewrote "任务卡中关键步骤配视频" to: each task card's video
    lives in a dedicated `#### 演示视频` section placed **before**
    `#### 步骤`; the steps block itself contains step prose + `![alt](png)`
    screenshots only.
  - §4 task-card template now shows the new `#### 演示视频` block.
  - §5.4 self-check table: row 14 added.

### Tests

- `test_validate_output.py`: +4 tests (`VideoOutsideStepsTests`),
  `test_json_mode` count 13 → 14. Suite: 125 → 129, all green.

### Proof on the ehr manual

The check was authored against the ehr manual as the failing case: 3
step-line videos in `report-config`, 3 in `report-viewer` (6 offenders
total). After moving each into its task's `#### 演示视频` section (and
fixing a `[ ideo:` typo in the process), all three manuals pass 14/14.

Audited the ehr-generated manual against the skill's own toolchain and
found three defects that `validate-output.py` was not catching — the
manual shipped fine under the old 11 checks but the deliverable was
wrong. v1.2.0 hardens the contract so the same degeneration cannot ship
again.

### Why

- **Empty `description` × 3 manuals**: INTEGRATION §3.5 says viewer v2
  parses frontmatter `description` into the search-result excerpt.
  SKILL §3 row 1 and the §5 output-format line never listed it, so the
  LLM omitted it on every manual — viewer search was silently dead.
- **15 unfilled template terms in the overview**: `对应地址/`,
  `手册所在目录`, `起静态站服务` (a subcommand display-name used as a
  real command) survived into the deliverable. They were all
  backtick-wrapped, so they looked "codey" — exactly the disguise
  §2.2 bans for alt text.
- **6 `.silent.mp4` backups (~2.9MB) committed**: recorder keeps a
  pre-narration silent copy next to the narrated video (recorder/SKILL.md
  §narration). Only the narrated `.mp4` is ever referenced; the silent
  copy stayed in `screenshots/` and got committed.

### What changed

- `validate-output.py`:
  - New check `frontmatter_description` (12th, FAIL when `description`
    is missing / empty / `<TODO:>` / `占位` / `<your-...>`). Sourced from
    a tolerant frontmatter parser shared in shape with `html._parse`.
  - New check `unfilled_template_terms` (13th, FAIL when raw text
    contains `对应地址` / `手册所在目录` / `起静态站服务` /
    `<your-...>`). Scanned on RAW text incl. inside backticks — the
    three stub tokens are never valid literals, so backticks cannot
    mask them (the failure mode that hid the ehr defects).
  - Check count is now 13 (was 11). `--json` consumers that pinned the
    count must update.
- `manual_helper/recording.py`:
  - New `prune_silent_backups(screenshots_dir, manual_paths, apply=)`
    deletes `.silent.mp4` files whose narrated sibling is referenced by
    a manual. Default is dry-run; `--apply` writes to disk. Orphan
    silent files (no in-use narrated sibling) are kept, never auto-deleted.
  - New CLI subcommand `prune-silent-backups <screenshots-dir>
    [--manual <md>...] [--apply]`. Without `--manual`, auto-discovers
    `<screenshots-dir>/../manual/*.md`.
- `SKILL.md`:
  - §3 row 1 and §5 output-format line: `description` listed as required.
  - §5.4 self-check table: rows 9-13 added (directory_anchors,
    task_card_headings, audience_leak, frontmatter_description,
    unfilled_template_terms).
  - §7 subcommand table: `prune-silent-backups` added.

### Tests

- `test_validate_output.py`: +12 tests (`FrontmatterDescriptionTests`,
  `UnfilledTemplateTermsTests`), GOOD fixture frontmatter + description,
  `test_json_mode` count bumped 11 → 13.
- `test_manual_helper.py`: +6 tests (`PruneSilentBackupsTests`) covering
  dry-run vs apply, orphan keeping, unreferenced-narrated keeping, CLI
  dry-run default, CLI auto-discovery.
- Suite: 104 → 122 tests, all green.

### Proof on the ehr manual

The three ehr manuals (`customer/docs/user-manual/manual/*.md`) were the
audit input. Before the fix they passed the 11-check suite; with v1.2.0
they surfaced 3× empty-description + 15 unfilled-template-term defects.
After re-editing the overview and adding `description` to all three,
they pass all 13 checks. `prune-silent-backups --apply` then freed
2,916,508 bytes by deleting the 6 silent backups (0 kept).

### Recorder viewport now configurable + full-screen by default

The auditor also flagged that recorded videos were 1440×900 (a hard-coded
viewport in `build_recorder_template`), which recorded fine but showed
letterboxed against a real operator screen. v2.1.0:

- `build_recorder_template` reads `manual-config.json` `recording.viewport:
  {width, height}` (new top-level config field, not under `project`).
  Default raised 1440×900 → **1920×1080** so videos match a common desktop
  logical resolution out of the box ("full screen" recording without a
  headed/maximize mode, which Playwright headless cannot reproduce
  deterministically).
- New `_infer_viewport(config)` with non-positive / non-int guard.
- +3 tests (`test_viewport_default_is_full_screen`,
  `test_viewport_read_from_config`, `test_viewport_ignores_garbage`).
- SKILL §13 recorder section documents the new config field.

The recording phase has been a single-package subsystem of user-manual
since v0.2.3. Over time it grew to ~3700 lines (≈56KB) inside
`scripts/manual_helper.py` and gained its own dependency tree
(playwright, ffmpeg, Pillow, edge-tts). v2.0.0 extracts it into a
standalone skill at `~/.agents/skills/recorder` and slims the
user-manual package down to its actual job: writing and validating
markdown manuals.

### What moved to the recorder skill

- The browser-driven recording pipeline (Playwright + Chromium + webm
  slicing + TTS + muxing) is now its own package: `recorder_plugin/`
  with its own CLI (`python3 -m recorder_plugin.cli run` /
  `apply-ai-responses` / `tts-synth` / `concat-narration` /
  `mux-audio`), MCP server, and 19 unit + 4 integration tests.
- The `recorder/` directory under `user-manual/` was deleted; the
  standalone skill is identical, just relocated.

### What changed in user-manual

- `scripts/manual_helper.py` (3709 lines, 56KB) was split into a
  12-file `manual_helper/` package (~3270 lines, similar total but
  each file 50-500 lines).
- Three recorder-side CLI subcommands were **removed** from
  `manual_helper`:
  - `record-manual <md>` — replaced by the Python function
    `manual_helper.scan_recording_placeholders(text)`.
  - `record-manual <md> --generate-template` — replaced by
    `manual_helper.build_recorder_template(manual_name, placeholders, ...)`.
  - `record-manual <md> --apply-mapping` — replaced by
    `manual_helper.apply_recording_mapping(text, mapping)`.
  - `record-and-replace <md>` — replaced by the LLM agent invoking
    `recorder_plugin.cli run` + `apply_recording_mapping` in sequence.
  - `check-recorder-script` — moved into `recorder_plugin.cli run`
    preflight.
- The Python functions that DO belong in user-manual (markdown-level
  primitives: `scan_recording_placeholders`, `build_recorder_template`,
  `apply_recording_mapping`, plus their internal helpers) are still
  importable as `from manual_helper import …` and re-exported in
  `manual_helper/__init__.py`.
- `init-skill` no longer depends on `subprocess` for the recorder; the
  `RecordingBlockedError` and `check_recording_readiness` flow is
  unchanged, so `init-skill` still auto-installs deps and still exits
  2 on a red env.
- 45 unit tests were deleted (they tested the removed CLI subcommands).
  Net test count: 147 → 100. The 5 pre-existing fixture failures in
  `test_recording_readiness.py` (machine has playwright+ffmpeg, so
  readiness returns green not yellow) are unchanged.

### Migration

| v1.x (old CLI) | v2.0.0 (new) |
|---|---|
| `manual_helper record-manual foo.md` | `from manual_helper import scan_recording_placeholders; scan_recording_placeholders(Path("foo.md").read_text())` |
| `manual_helper record-manual foo.md --generate-template s.json` | `from manual_helper import build_recorder_template; json.dump(build_recording_template(…), open("s.json","w"))` |
| `manual_helper record-manual foo.md --apply-mapping m.json` | `from manual_helper import apply_recording_mapping; Path("foo.md").write_text(apply_recording_mapping(text, json.load(open("m.json")))[0])` |
| `manual_helper record-and-replace foo.md --script s.json` | Run `recorder_plugin.cli run s.json` then call `apply_recording_mapping` |
| `manual_helper check-recorder-script s.json` | Use `recorder_plugin.cli run --dry-run s.json` (or just `run`; preflight errors are surfaced in the run output) |

### Why this is better

- **Smaller install surface**: projects that don't need recording
  (CLI tools, pure APIs, no-UI manuals) no longer pull in
  playwright/ffmpeg/Pillow just to write a manual.
- **Faster skill load**: `manual_helper` is now 12 small files
  instead of one 3700-line monolith; the package imports in
  <50ms on a cold cache.
- **Recorder can evolve independently**: the recorder skill
  shipped v0.3.11 (humanized cursor motion, frame-accurate trim,
  bezier bow) without touching user-manual, because the recorder
  is no longer part of user-manual.
- **No more "agent skipped step 3-5"**: §14 used to have a 5-step
  workflow that agents routinely skipped. v2.0.0 collapses this
  to: scan + build-template (Python) → run recorder (one CLI
  command) → apply mapping (Python). Three steps, each with a
  hard error if the previous one didn't complete.

## 1.1.x (2026-06-25) — backfill: SKILL.md v1.1+ rules + helper coverage

This entry backfills changes that landed in `SKILL.md` and the scripts
between 2026-06-24 (v1.0.4) and today but were never recorded in the
changelog. The first 4 items are SKILL.md content; the next 3 are helper
behavior changes. Going forward, rule additions must come with a
changelog entry in the same commit.

### SKILL.md additions (rule tightening for business-user manuals)

- **§2.7.1 业务用户文档禁列项** (v1.1.0): 6 classes of anti-patterns
  the LLM must not emit. Validated by `validate-output.py` §verification-8.
  - 类 1: `> 数据源:` 元注释
  - 类 2: 后端 API endpoint 表格 / 列表 / 散落引用
  - 类 3: 源码文件路径(任何上下文)
  - 类 4: 仓库 / 目录结构引用
  - 类 5: 录屏 / 截图占位段(`<!-- video-pending -->` /
    `⏳ **视频录屏待补**` / `recorder-scripts/vN-*.json`)
- **§2.7.1 类 6** (v1.1.1): 事实性内容禁估算。helper 抽得到的数字
  / 错误码 / 函数名必须从代码读,不允许 LLM 凭印象写。Tier 3 例外。
- **§2.7.1 类 7a** (v1.1.3): 业务概念术语必译(`mock` / `toast` /
  `drawer` / `token` / 等),代码标识符保留英文。

### Helper behavior changes

- **extract-roles.py** (v1.1.x): 增加了 RuoYi / vue-element-admin 派系
  的指令支持,具体在 `yangzongzhuan/RuoYi-Vue3` 上验证(60 个角色 /
  权限命中,旧版本为 0):
  - 前端指令 `v-hasPermi` / `v-hasRole`
  - 路由对象顶层 `roles: [...]` / `permissions: [...]` (RuoYi 风格,
    在 `meta: {}` 外)
  - 路由 `meta: {}` 内的 `roles` / `permissions` (vue-element-admin 风格)
  - 修复: `_extract_quoted` 路径中 `startswith(("[", "["))` 是恒真
    元组导致所有值都按列表解析
- **extract-routes.py** (v1.1.x): 增加了对 `meta.icon` 和顶层
  `permissions: [...]` / `roles: [...]` 的解析(`perms` 字段自动合并
  两个来源)。在 RuoYi 上验证 `perms` 命中从 0 提升到 25。

### init scaffold changes (v1.1.x)

- 删除 `## Daily Usage` / `## Architecture and Internals` /
  `## Concepts and Glossary` 三个 §3 v1 标记为"已废弃"的章节
- `## Citations` 现在按 `manual-config.json: include_citations` 条件
  生成(默认 OFF,与 §6 行为一致)

# Changelog

## 1.0.4 (2026-06-24) — recorder v0.3.9: human-looking cursor

Followup to v1.0.3. The v0.3.8 cursor was visible but had
five "demo" tells that made the video look robotic instead
of recorded:

1. Cursor teleported on every mousemove (no interpolation
   between positions).
2. Cursor stayed visible after page navigation at the last
   position from the old page (Playwright headless doesn't
   fire mousemove after navigation).
3. Click ripple stayed red and visible in the new page's
   empty space.
4. No idle behavior — a frozen cursor looked pasted on.
5. Keystroke HUD was bottom-center 80vw — too intrusive.

v0.3.9 fixes all five:

- **CSS transition on the cursor** (`transform 0.08s
  ease-out`): every `setCursorPos()` still snaps but the
  GPU interpolates — the way a real OS cursor glides.
- **Visibility gating**: cursor is opacity 0 by default,
  reveals on first mousemove of the page. On pagehide
  it fades back to 0; new page's first mousemove
  re-reveals at the new position.
- **Idle fade**: 700ms of no movement → cursor fades
  to opacity 0. Handles the "post-login cursor floats
  in empty space" case.
- **Outer pulse ring** behind the cursor: 26px circle
  pulsing every 1.8s. Makes a stationary cursor feel
  "alive".
- **Ripple recolored red → blue** (`rgba(59,130,246,0.7)`).
  Blue says "action here" and matches app button accents.
- **Keystroke HUD moved to bottom-right**, narrower (28vw),
  smaller chips, 85% opacity.

In script.py: a new `move` action (for explicit cursor
moves without clicking, with optional `duration_ms` and
`dwell_ms`), post-click hover dwell (350-550ms, the
"look at what just happened" pause), and
`__recMoveCursorTo(x,y)` global that's called before every
click/type to snap the overlay cursor to the target
*before* the cubic-ease glide.

**Inspiration**: CSS transition trick from
tecnomanu/video-docs-builder (MIT, 2026). `move` action
and addInitScript split still from snomiao/demowright
(MIT, 2026).

**What changed in the skill itself**: zero. This is a
recorder-only fix. The recorder/SKILL.md v0.3.9 sub-section
covers the new `move` step.

**Versions**: skill 1.0.3 → 1.0.4; recorder 0.3.8 → 0.3.9;
recorder unit tests 168 → 175.

### Manual probes (test-app, fresh recording)

- Login flow: cursor glides to account field, types with
  keystroke HUD `a d m i n`, glides to password, types
  (HUD shows `a d m i n a d m i n`), glides to login
  button, post-click hover dwell 350-550ms, page route
  changes to dashboard, cursor idle-fades within 700ms.
  No more ghost cursor in the dashboard's empty area.
- Dashboard view: cursor at sidebar's "全部" with blue
  pulse ring. Click "待办" → cursor glides → list filters.
  No teleport, no ripple-in-empty-space.

### What changed in the skill itself

- `recorder/recorder_plugin/cursor.py` — rewritten (519
  lines, was 342). CSS transition, pagehide/pageshow,
  idle-fade, pulse ring, blue ripple, repositioned HUD.
- `recorder/recorder_plugin/script.py` — adds `_handle_move`,
  registers `move` action, calls `__recMoveCursorTo`
  before click/type, adds post-click hover dwell.
- `recorder/tests/unit/test_cursor.py` — 18 tests (was 11).
  7 new tests covering transition, visibility gating,
  pagehide cleanup, listener events, ripple color, idle
  fade, idle reset.

## 1.0.3 (2026-06-24) — recorder v0.3.8: cursor actually follows the mouse

Followup to v1.0.2. The recorder's "visible cursor" feature
(introduced as a side-effect of v1.0.2's `file://` fix chain,
released as recorder v0.3.7) was actually broken: the cursor
overlay appeared but stayed frozen at 50%/50% of the viewport.
The user reported "鼠标箭头不动" — and was right.

Recorder v0.3.8 fixes this by splitting the cursor subsystem
into two pieces:

- A **listener** registered via `context.add_init_script()`
  BEFORE any page is created. It only updates a state object
  on `window.__recHud` — never touches the DOM. Safe to run
  before `<body>` exists.
- A **DOM injector** that runs as `page.evaluate` after
  navigation. It creates the cursor element and wires it to
  the listener's state via a callback, so the cursor's
  `transform: translate(x, y)` updates on every `mousemove`.

The split is the key insight: addInitScript must run as plain
statements (Playwright double-wraps its input), and a listener
that touches the DOM before the body exists will silently fail.
The split also fixes a regression that prevented the listener
from registering at all on the *first* page navigation.

v0.3.8 also adds a **keystroke HUD** (5-key trail at the
bottom of the screen) and **click ripples** (200ms expanding
ring at click point) so the user can follow the demo
even when the password field is masked. Pattern adapted from
[snomiao/demowright](https://github.com/snomiao/demowright)
(MIT, 2026) — see `recorder/CHANGELOG.md` for full credits.

**What changed in the skill itself**: zero. This is a
recorder-only fix; no SKILL.md workflow or manual-helper
changes. The only file that mentions v0.3.7 in the main
SKILL.md is the "recorder gotchas" section, which still
applies (v0.3.7 introduced the cursor concept; v0.3.8 makes
it actually work).

**Upgrade note**: clear `.recorder_state.json` + the
`_video_buffer/` + the per-flow `sys/<flow>/` directories
after pulling v0.3.8, otherwise `is_video_session_valid()`
will reuse the v0.3.7 (broken-cursor) mp4s. See
`recorder/CHANGELOG.md` for the exact commands.

### What changed

- `recorder/recorder_plugin/cursor.py` — rewritten (342 lines)
  with the addInitScript + DOM-injector split.
- `recorder/recorder_plugin/script.py` — `video_start`
  simplified to just `inject_overlay` (install is now
  context-level).
- `recorder/recorder_plugin/core.py` — `Recorder.start()`
  calls `self._context.add_init_script(LISTENER_JS)` BEFORE
  `new_context` returns.
- `recorder/tests/unit/test_cursor.py` — 11 tests, includes
  the regression test for the addInitScript-as-plain-statements
  gotcha.

### Manual probes (test-app)

- Before: cursor at (50%, 50%) frozen, no click ripples, no
  keystroke badges.
- After: cursor follows real mouse, ripple at click point,
  keystroke chips at bottom (last 5 keys, 1.5s fade).

### Versions

- Skill: 1.0.2 → 1.0.3.
- Recorder: 0.3.7 → 0.3.8.
- Recorder unit tests: 158 → 168.

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
