# Contributing

Thanks for considering a change to `user-manual`. This skill is intentionally
minimal — the goal is to keep the core tiny and let per-project adaptations
live in user projects, not here.

## Repo layout

```
SKILL.md            # full spec (orchestrator)
INTEGRATION.md      # 30-min setup guide for first-time users
scripts/
  extract-*.py      # 5 deterministic extractors (one per artifact type)
  manual_helper/   # orchestrator package (v2.0.0 split from manual_helper.py), run via `cd scripts && python3 -m manual_helper <cmd>`
  validate-output.py# 6 must-pass checks before commit
  tests/            # 27 stdlib unittest tests, no external deps
templates/
  user-manual.html  # self-contained dashboard (version-tagged)
examples/
  db-backend/       # full FastAPI + Postgres + S3 demo (db mode)
  custom-helper/    # Tier 2/3 adaptation recipes (drop-in snippets)
  personas.template.json
  dryrun-sys-user-manual.md  # reference output (LLM-generated, §2.8 style)
```

## How to add or change an extractor

1. **Read the existing one first.** Open `scripts/extract-<name>.py` end-to-end.
   Match its style: stdlib only, `pathlib.Path`, type hints, `extract_from_*`
   function + thin `main(argv)` shell.

2. **Add a test in `scripts/tests/test_extract_<name>.py`.** Use stdlib
   `unittest` + `tempfile.TemporaryDirectory`. Test at minimum:
   - typical input (the happy path)
   - empty / missing input
   - at least one dedup or edge case from the spec

3. **Run the suite locally**:
   ```bash
   cd scripts && python3 -m unittest discover -s tests -p 'test_*.py' -v
   ```
   All tests must pass before you open a PR. CI on GitHub Actions runs the
   same command on Python 3.10/3.11/3.12.

4. **Document in SKILL.md.** If you added a new extractor, mention it in
   §0 (栈支持矩阵) and §5.1 (数据采集). If you changed a subcommand, update
   §7 (Helper 子命令).

5. **Update `validate-output.py` if you changed output shape.** The 6 checks
   in `CHECKS = [...]` are the contract every generated manual must satisfy —
   if your extractor feeds into them, make sure the regex still matches.

## How to update the HTML template

The dashboard template is versioned. The version is the first `N` in:

```html
<!-- user-manual-dashboard-version: N -->
```

When you change anything inside `templates/user-manual.html`:

1. Bump `N` (it's just a monotonically increasing integer — the existing
   comment is at line 7).
2. The next time `regenerate-html-if-stale` runs, it will copy the new
   template to `<project>/docs/user-manual/user-manual.html` automatically
   (it diffs template version vs on-disk version).
3. Add a short entry to your commit message explaining the UI change.

Do not bundle the HTML into a self-contained file unless you also know how
to rebuild the standalone version (see `build_standalone()` in
`manual_helper/` package — run via `cd scripts && python3 -m manual_helper <subcommand>`).

## Code style

- **Stdlib only.** No `requests`, no `pydantic`, no `pytest`. The skill
  must work in any Python 3.10+ environment with zero `pip install`.
  **Exception:** top-level opt-in plugin directories (see next section) may
  declare their own dependencies.
- **Type hints everywhere** (function signatures at minimum).
- **Match the existing structure** of the file you are editing — do not
  refactor or "modernize" adjacent code in the same PR. Surgical changes
  are easier to review and revert.
- **No comments explaining what the code does** (the code does that).
  Comments are for non-obvious *why* (hidden constraints, workarounds).

## Opt-in plugins

Opt-in plugins are SKILLs that live **outside** the user-manual repo
and are installed separately. The first such plugin was the `recorder`
skill (extracted from user-manual in v2.0.0 — it now lives at
`~/.agents/skills/recorder` as a standalone repo with its own
`pyproject.toml`, `INSTALL.md`, `SKILL.md`, and CI).

A plugin's `SKILL.md` frontmatter must declare it as
`requires: [user-manual]` so the parent user-manual skill knows it is
optional. The plugin's `INSTALL.md` must list every pip package and
system binary it requires. The plugin's CI is independent of the
user-manual CI (lives in its own repo).

The `stdlib only` style constraint above applies to files under `scripts/`,
not to opt-in plugin directories.

## Commit messages

```
<type>(<scope>): <one-line summary>

<body explaining why, not what>

Co-Authored-By: ...
```

`type` ∈ `feat / fix / refactor / docs / test / chore`.
`scope` ∈ `extract-* / helper / validate / template / docs / ci`.

Example:
```
feat(extract-fields): add Ant Design Vue form-item pattern
```

## PR checklist

- [ ] Tests pass locally: `cd scripts && python3 -m unittest discover`
- [ ] New extractor / behavior has a test
- [ ] SKILL.md / INTEGRATION.md / README.md updated if user-visible
- [ ] No new third-party dependencies
- [ ] Commit message follows the format above
