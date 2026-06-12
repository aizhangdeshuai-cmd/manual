#!/usr/bin/env python3
"""Deterministic helpers for the user-manual skill.

The skill itself does the heavy lifting (reading artifacts, writing prose,
elaborating jargon, fortifying with web search) — this script handles the
few primitives that are easy to get wrong in prose:

  * `now-et`                          — current timestamp in `YYYY-MM-DD HH:MM ET`
  * `init <md-path>`                  — create the empty manual scaffold if missing
  * `init-skill [project-root]`       — one-shot bootstrap: create docs/user-manual/{manual,assets,screenshots}/,
  *                                        write manual-config.json (v2 schema with <PLACEHOLDER> values),
  *                                        hard-fail if personas.json missing. See SKILL.md section 1 + 7.
  * `validate-config [project-root]`  — validate manual-config.json + personas.json,
  *                                        business_objectives coverage >= 2, exit non-zero on errors.
  *                                        `validate-config --json` for machine-readable output.
  * `extract-tasks <spec.md> [...]`     — run scripts/extract-tasks.py over given spec files.
  * `extract-fields [--vue|--java] <p>` — run scripts/extract-fields.py.
  * `extract-routes <router-file>`      — run scripts/extract-routes.py.
  * `extract-roles <be> [<fe>]`         — run scripts/extract-roles.py.
  * `extract-openapi <openapi-file>`    — run scripts/extract-openapi.py (D3).
  * `scan-artifacts <project-root>`   — list every superpowers artifact with a
                                        sha256 of its content (JSON to stdout)
  * `parse-citations <md-path>`       — read the existing manual's Citations
                                        table and emit the path -> hash mapping
                                        as JSON
  * `diff-artifacts <project-root> <md-path>`
                                      — combine the two: tell the skill which
                                        artifacts are NEW (not yet cited),
                                        CHANGED (cited but content changed),
                                        UNCHANGED (skip), or MISSING (cited
                                        but file no longer on disk)
  * `html-template-version`           — print the bundled template version
  * `regenerate-html-if-stale <html-path>`
        — write the bundled HTML template to the path if the file is missing
          or its embedded version is older than the template's. No-ops
          otherwise. Prints `created` / `regenerated` / `unchanged`.
  * `write-index <html-dir> <md-path> [more-md-paths...]`
        — scan the given .md files and emit a `manual-index.json` next to
          the viewer HTML. Titles come from frontmatter `title:` or first
          H1; descriptions from frontmatter `description:`. Paths in the
          index are relative to <html-dir>, so .md files in subdirectories
          work (e.g. `fr/finance.md` — module is auto-prefixed). Prints `wrote: <path>` or
          `updated: <path>`.
  * `build-standalone <html-template> <html-out> <md-path> [more...]`
        — read <html-template>, embed each .md file inline as
          `<script type="text/markdown" data-file="..." id="md-{slug}">`,
          embed the index as a JSON script, and write to <html-out>. The
          resulting html is fully self-contained: opening via `file://`
          works without a server. Prints `wrote: <path>`.
  * `read-config`                      — print the effective manual-config.json
                                         (project-level, takes precedence over defaults).
  * `init-db`                          — apply schema.sql to the configured Postgres DB.
  * `upsert-manual <md-path>`          — push a .md file to the API (db mode).
  * `upload-asset <manual-file> <path> [--caption TEXT]`
                                      — upload an image/video to object store,
                                         register it under the manual, print
                                         the public URL + md-insert hint.
  * `record-manual <manual.md> [--generate-template <out.json>] [--apply-mapping <mapping.json>]`
                                      — v0.2.3 recording phase. Default: scan
                                         the manual for [SCREENSHOT: x] and
                                         [VIDEO: x] placeholders and report
                                         what needs recording. --generate-template:
                                         emit a recorder script template (the
                                         LLM agent fills in selectors and runs
                                         it via the recorder opt-in plugin).
                                         --apply-mapping: read a {placeholder:
                                         real_path} JSON and replace placeholders
                                         in the manual with real asset paths.
                                         See SKILL.md §14 for the full workflow.

Pure stdlib. Python 3.9+ (zoneinfo).

Invoke as `python3 manual_helper.py <subcommand> [args]`.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HTML_VERSION_RE = re.compile(r"<!--\s*user-manual-dashboard-version:\s*(\d+)\s*-->")
TEMPLATE_HTML_PATH = Path(__file__).resolve().parent.parent / "templates" / "user-manual.html"

# The four superpowers subdirectories the skill knows about. Order matters
# only for human-readability of the scan output.
SUPERPOWERS_KINDS = ("specs", "plans", "findings", "reviews")

TEMPLATE = """# User Manual

_Maintained by the [`user-manual`](https://github.com/photoenthu/user-manual-skill) skill. Generated and updated from the project's `docs/superpowers/` artifacts. Re-run the skill after writing new specs / plans / findings / reviews to fold them in._

> **Manual status:** scaffold only. Run the `user-manual` skill to populate this file from the project's superpowers artifacts.

## Quick Start

_Will be populated by the skill on its first real run._

## Concepts and Glossary

_Will be populated by the skill on its first real run._

## Daily Usage

_Will be populated by the skill on its first real run._

## Configuration

_Will be populated by the skill on its first real run._

## Troubleshooting and FAQ

_Will be populated by the skill on its first real run._

## Architecture and Internals

_Will be populated by the skill on its first real run._

## Citations

### Project artifacts

This table is the skill's idempotency ledger. Every superpowers artifact the
skill has folded into the manual appears here with a content hash. On the next
run, artifacts whose hash matches this table are skipped; new or changed
artifacts are processed.

| Path | Kind | Title | SHA256 (content) | First cited (ET) | Last seen (ET) |
|---|---|---|---|---|---|

### External references

Web pages and external docs the skill cited while fortifying the manual. Not
used for idempotency — the skill may re-fetch these on future runs to keep
elaborations current.

| URL | Title | Cited from section | Last fetched (ET) |
|---|---|---|---|
"""

# Pulled out so callers can verify the exact section header before parsing.
CITATIONS_HEADING = "## Citations"
ARTIFACTS_SUBHEADING = "### Project artifacts"
EXTERNAL_SUBHEADING = "### External references"


def now_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def init(path: Path) -> bool:
    """Create the scaffold file if missing. Returns True if it created it."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return True


# ---------- Skill scaffold (project bootstrap) ----------

DEFAULT_CONFIG_LINES = [
    '{',
    '  "project": {',
    '    "name": "<your-project-name>",',
    '    "display_name": "<your-project-display-name>",',
    '    "stack": {',
    '      "frontend": "vue3",',
    '      "backend": "spring-boot",',
    '      "db": "postgresql"',
    '    },',
    '    "repo_layout": {',
    '      "frontend_root": "frontend",',
    '      "backend_root": "backend",',
    '      "docs_root": "docs"',
    '    },',
    '    "build_commands": {',
    '      "frontend_dev": "cd <frontend_root> && npm run dev",',
    '      "backend_dev_module": "cd <backend_root> && <your-backend-start-cmd> -pl {module}",',
    '      "backend_default_module": "<your-default-module>",',
    '      "backend_default_port": "<your-backend-port>",',
    '      "gateway_port": "<your-gateway-port>"',
    '    },',
    '    "deploy": {',
    '      "default_url": "<your-default-url>",',
    '      "auth": "jwt"',
    '    }',
    '  },',
    '  "business_objectives": ["创建", "查询", "修改", "删除", "审批", "导出"],',
    '  "personas_path": "docs/user-manual/personas.json",',
    '  "inputs": [',
    '    {"kind": "superpowers", "path": "docs/superpowers"},',
    '    {"kind": "frontend_pages", "path": "<frontend_root>/src/views", "include_globs": ["**/*.vue"]},',
    '    {"kind": "backend_dtos", "path": "<backend_root>", "include_globs": ["**/dto/**/*.java"]},',
    '    {"kind": "router", "path": "<frontend_root>/src/router/index.ts"}',
    '  ],',
    '  "screenshots_dir": "docs/user-manual/screenshots",',
    '  "storage": "file",',
    '  "viewer": {',
    '    "template": "docs/user-manual/skill-template/templates/user-manual.html",',
    '    "out": "docs/user-manual/user-manual.html",',
    '    "standalone_out": "docs/user-manual/user-manual-standalone.html"',
    '  }',
    '}',
    '',
]
DEFAULT_CONFIG = "\n".join(DEFAULT_CONFIG_LINES)


def init_skill(project_root: Path) -> dict:
    """One-shot bootstrap for a fresh project (v2 D1).

    Creates:
      docs/user-manual/manual/             (where the .md lives)
      docs/user-manual/assets/             (where images/videos live)
      docs/user-manual/screenshots/         (per-domain screenshot dirs, v2)
      docs/user-manual/manual-config.json   (v2 schema with <PLACEHOLDER> values)
      docs/user-manual/manual-index.json    (empty starter; regenerated on each build)

    Does NOT create personas.json — that is project-specific and must be authored.
    Skips anything that already exists (no overwrites).

    Hard-fails if personas.json is missing: the skill v2 enforces personas as a
    first-class project input. See SKILL.md section 1 (file location) and
    section 7 (helper subcommands).

    Returns a dict { created: [...], skipped: [...], personas_required: <path> }.
    Raises FileNotFoundError if personas.json does not exist.
    """
    root = project_root
    created, skipped = [], []
    paths = [
        root / "docs" / "user-manual",
        root / "docs" / "user-manual" / "manual",
        root / "docs" / "user-manual" / "assets",
        root / "docs" / "user-manual" / "screenshots",
    ]
    for p in paths:
        if p.exists():
            skipped.append(str(p.relative_to(root)))
        else:
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p.relative_to(root)))
    cfg = root / "docs" / "user-manual" / "manual-config.json"
    if cfg.exists():
        skipped.append(str(cfg.relative_to(root)))
    else:
        cfg.write_text(DEFAULT_CONFIG, encoding="utf-8")
        created.append(str(cfg.relative_to(root)))
    idx = root / "docs" / "user-manual" / "manual-index.json"
    if idx.exists():
        skipped.append(str(idx.relative_to(root)))
    else:
        idx.write_text(
            json.dumps({"version": 1, "generated": now_et(), "manuals": []}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append(str(idx.relative_to(root)))
    # v0.2.2: when personas.json missing, scaffold from examples/personas.template.json
    # (was: hard FileNotFoundError — first-time users hit a wall).
    personas_path = root / "docs" / "user-manual" / "personas.json"
    if not personas_path.exists():
        # Try a few candidate locations for the template
        template_candidates = [
            # The user-manual skill's examples/ dir (shipped with the skill)
            Path(__file__).parent.parent / "examples" / "personas.template.json",
            # Legacy path used by older init-skill versions
            root / "docs" / "user-manual" / "skill-template" / "examples" / "personas.template.json",
        ]
        template = next((p for p in template_candidates if p.exists()), None)
        if template is None:
            raise FileNotFoundError(
                "personas.json not found at {} and no template available at:\n  {}".format(
                    personas_path, "\n  ".join(str(p) for p in template_candidates)
                )
            )
        # Scaffold: copy the template, then print a loud warning
        import shutil
        personas_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(template, personas_path)
        created.append(str(personas_path.relative_to(root)))
        # Prominent stderr warning so the user sees it
        print("=" * 70, file=sys.stderr)
        print("⚠️  personas.json was MISSING — scaffolded from template.", file=sys.stderr)
        print("    Created: {}".format(personas_path), file=sys.stderr)
        print("", file=sys.stderr)
        print("    NEXT STEP: edit personas.json to match your project's real", file=sys.stderr)
        print("    roles, then re-run `python3 -m manual_helper validate-config`.", file=sys.stderr)
        print("    (Running with the 5 default personas is fine for a first pass.)", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
    return {"created": created, "skipped": skipped, "personas_scaffolded": str(personas_path.relative_to(root))}


# ---------- Config validation (v2 D1) ----------

def validate_config(project_root: Path) -> dict:
    """Validate manual-config.json + personas.json + business_objectives coverage.

    Returns a dict { ok: bool, errors: [str], warnings: [str], info: dict }.

    Hard rules (errors block validation):
      - manual-config.json exists, valid JSON, has required top-level fields
      - personas.json exists, valid JSON, has granularity + personas (>= 3)
      - Each persona has id, name, daily_tasks (>= 1)
      - business_objectives coverage: union of personas\' covers_objectives
        has >= 2 distinct values from the configured business_objectives list

    Soft rules (warnings only):
      - Personas with no covers_objectives (LLM may struggle to write tasks)
      - project.name still a <PLACEHOLDER> value
      - inputs paths still <PLACEHOLDER> values
    """
    errors, warnings, info = [], [], {}
    root = project_root

    cfg_path = root / "docs" / "user-manual" / "manual-config.json"
    personas_path = root / "docs" / "user-manual" / "personas.json"

    # ---- manual-config.json ----
    if not cfg_path.exists():
        errors.append(f"manual-config.json not found at {cfg_path}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"manual-config.json is not valid JSON: {e}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    info["config_keys"] = sorted(cfg.keys())

    required_cfg_keys = ["project", "business_objectives", "personas_path", "inputs", "storage"]
    for k in required_cfg_keys:
        if k not in cfg:
            errors.append(f"manual-config.json missing required key: {k}")

    # project sub-keys
    proj = cfg.get("project", {})
    for pk in ["name", "display_name", "stack", "build_commands", "deploy"]:
        if pk not in proj:
            errors.append(f"manual-config.json project.* missing: {pk}")
    pn = proj.get("name", "")
    if isinstance(pn, str) and pn.startswith("<your-"):
        warnings.append(f"project.name still a placeholder: {pn!r}")

    # ---- personas.json ----
    if not personas_path.exists():
        errors.append(f"personas.json not found at {personas_path}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    try:
        pdata = json.loads(personas_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"personas.json is not valid JSON: {e}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    granularity = pdata.get("granularity")
    if granularity not in ("role_only", "task_only", "role_with_tasks"):
        errors.append(
            f"personas.json granularity must be one of role_only / task_only / role_with_tasks, got {granularity!r}"
        )

    personas = pdata.get("personas", [])
    if not isinstance(personas, list) or len(personas) < 3:
        errors.append(f"personas.json must have >= 3 personas, got {len(personas)}")

    persona_ids = set()
    for i, p in enumerate(personas):
        if not isinstance(p, dict):
            errors.append(f"personas[{i}] is not an object")
            continue
        if "id" not in p or not p["id"]:
            errors.append(f"personas[{i}] missing id")
        else:
            persona_ids.add(p["id"])
        if "name" not in p or not p["name"]:
            errors.append(f"personas[{i}] missing name")
        if "daily_tasks" not in p or not isinstance(p["daily_tasks"], list) or not p["daily_tasks"]:
            errors.append(f"personas[{i}] (id={p.get('id')}) missing or empty daily_tasks")
        if "covers_objectives" not in p or not p["covers_objectives"]:
            warnings.append(
                f"personas[{i}] (id={p.get('id')}) has no covers_objectives; "
                f"LLM may not map this persona to a business objective"
            )

    # ---- business_objectives coverage ----
    business_objectives = cfg.get("business_objectives", [])
    if not business_objectives:
        errors.append("manual-config.json business_objectives must be a non-empty list")
    else:
        covered = set()
        for p in personas:
            for obj in p.get("covers_objectives", []):
                if obj in business_objectives:
                    covered.add(obj)
        if len(covered) < 2:
            errors.append(
                f"personas 覆盖的业务目标类别不足(<2),请调整 personas.json. "
                f"covered={sorted(covered)}, allowed={business_objectives}"
            )
        info["covered_objectives"] = sorted(covered)

    info["persona_ids"] = sorted(persona_ids)
    info["granularity"] = granularity

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


# ---------- Artifact scanning ----------

def _short_hash(content: bytes) -> str:
    """Truncated sha256 — full hash is overkill for citation tracking and
    bloats the table visually. 16 hex chars (64 bits) is collision-resistant
    enough for a per-project artifact set."""
    return hashlib.sha256(content).hexdigest()[:16]


def _extract_title(text: str, fallback: str) -> str:
    """Best-effort H1 extraction from a markdown file. Falls back to the
    filename stem when no H1 is found in the first ~20 lines."""
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return fallback


def scan_artifacts(project_root: Path) -> list[dict]:
    """Walk `<project-root>/docs/superpowers/{kind}/` and return one dict per
    artifact:
        {
          "path": "docs/superpowers/plans/2026-04-27-foo.md",
          "kind": "plan",
          "title": "Regime-router foundation",
          "hash": "a1b2c3d4e5f60718",
          "size": 12048
        }
    Sorted by (kind, path) for stable output across runs."""
    base = project_root / "docs" / "superpowers"
    out: list[dict] = []
    if not base.exists():
        return out
    for kind in SUPERPOWERS_KINDS:
        kind_dir = base / kind
        if not kind_dir.is_dir():
            continue
        for path in sorted(kind_dir.glob("*.md")):
            try:
                raw = path.read_bytes()
                text = raw.decode("utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(project_root).as_posix()
            out.append({
                "path": rel,
                # Singular: "plan", "spec", etc. — reads better in the citation table.
                "kind": kind.rstrip("s") if kind != "specs" else "spec",
                "title": _extract_title(text, path.stem),
                "hash": _short_hash(raw),
                "size": len(raw),
            })
    return out


# ---------- Citation parsing ----------

def _split_table_row(line: str) -> list[str]:
    """`\\|` -> literal `|` inside a cell, `|` is the column separator. Same
    convention the markdown table uses; mirrors the JS parser in the dashboard."""
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if c == "|":
            cells.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    cells.append("".join(buf))
    if cells and cells[0].strip() == "":
        cells.pop(0)
    if cells and cells[-1].strip() == "":
        cells.pop()
    return [c.strip() for c in cells]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.match(r"^:?-+:?$", c) for c in cells)


def _normalize_artifact_path(raw_path: str, manual_md_path: Path) -> str:
    """Citation rows can carry either project-root-relative
    (`docs/superpowers/...`) or markdown-file-relative (`../superpowers/...`)
    paths — both are legitimate in different markdown rendering contexts.
    For the diff/idempotency machinery, everything must come back as
    project-root-relative so it lines up with `scan_artifacts`.

    Strategy: if `raw_path` is already a forward-slash path that starts with
    `docs/` or another known top-level directory, return it as-is; otherwise
    resolve it against the manual's directory and re-express it relative to
    the manual's grandparent (the project root, since the manual lives at
    `docs/user-manual/manual/user-manual.md` by convention)."""
    if not raw_path or raw_path.startswith(("http://", "https://", "/", "#")):
        return raw_path
    if "://" in raw_path:
        return raw_path
    # Heuristic: a project-root-relative path starts with a top-level dir
    # name and never contains `..`. Pass it through untouched.
    if not raw_path.startswith(("./", "../")) and ".." not in raw_path.split("/"):
        return raw_path
    # File-relative — resolve against the manual's directory and re-base
    # on the project root.
    try:
        md_dir = manual_md_path.resolve().parent
        # The manual lives at <root>/docs/user-manual/manual/user-manual.md, so project
        # root is three parents up from the .md file
        # (root / docs / user-manual / manual / file.md).
        project_root = md_dir.parent.parent.parent
        absolute = (md_dir / raw_path).resolve()
        return absolute.relative_to(project_root).as_posix()
    except (OSError, ValueError):
        return raw_path


def parse_citations(path: Path) -> dict:
    """Read the existing manual and pull out:
        {
          "artifacts": [{path, kind, title, hash, first_cited, last_seen}, ...],
          "external":  [{url, title, section, last_fetched}, ...]
        }
    Returns empty lists for both if the file is missing or the Citations
    section isn't there yet (e.g., scaffold-only manual). All artifact
    paths are normalized to project-root-relative regardless of whether
    they were stored project-root-relative or markdown-file-relative."""
    result = {"artifacts": [], "external": []}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find the Citations section first; everything before it is irrelevant.
    cite_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == CITATIONS_HEADING:
            cite_idx = idx
            break
    if cite_idx is None:
        return result

    # Now sub-walk: find each known subheading and collect table rows under it
    # until the next `## ` (or `### `, but only if it's a sibling we don't recognize).
    sub_idx = {ARTIFACTS_SUBHEADING: None, EXTERNAL_SUBHEADING: None}
    for idx in range(cite_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("## ") and stripped != CITATIONS_HEADING:
            break  # Left the Citations section entirely.
        if stripped in sub_idx:
            sub_idx[stripped] = idx

    def _collect_rows(start_idx: int | None) -> list[list[str]]:
        if start_idx is None:
            return []
        rows: list[list[str]] = []
        seen_separator = False
        for idx in range(start_idx + 1, len(lines)):
            line = lines[idx]
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                break
            if not stripped.startswith("|"):
                continue
            cells = _split_table_row(line)
            if _is_separator_row(cells):
                seen_separator = True
                continue
            if not seen_separator:
                # This is the header row; skip it.
                continue
            rows.append(cells)
        return rows

    for cells in _collect_rows(sub_idx[ARTIFACTS_SUBHEADING]):
        if len(cells) < 6:
            continue
        path_cell, kind_cell, title_cell, hash_cell, first_cell, last_cell = cells[:6]
        # The path may be wrapped in a markdown link: `[label](path)` — recover
        # the bare path. Prefer the link target when present.
        m = re.match(r"^\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)$", path_cell)
        bare_path = m.group("target") if m else path_cell
        # Normalize either link convention back to project-root-relative.
        normalized = _normalize_artifact_path(bare_path, path)
        # The hash cell may be wrapped in inline-code backticks — strip them.
        bare_hash = hash_cell.strip("`")
        result["artifacts"].append({
            "path": normalized,
            "kind": kind_cell,
            "title": title_cell,
            "hash": bare_hash,
            "first_cited": first_cell,
            "last_seen": last_cell,
        })

    for cells in _collect_rows(sub_idx[EXTERNAL_SUBHEADING]):
        if len(cells) < 4:
            continue
        url_cell, title_cell, section_cell, fetched_cell = cells[:4]
        m = re.match(r"^\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)$", url_cell)
        bare_url = m.group("target") if m else url_cell
        result["external"].append({
            "url": bare_url,
            "title": title_cell,
            "section": section_cell,
            "last_fetched": fetched_cell,
        })

    return result


# ---------- Diff: which artifacts need processing on this run? ----------

def diff_artifacts(project_root: Path, manual_path: Path) -> dict:
    """Compare on-disk superpowers artifacts against the manual's existing
    citation table. Returns four buckets:
        {
          "new":       [scan_entry, ...],   # not in citations at all
          "changed":   [scan_entry, ...],   # cited but hash changed
          "unchanged": [scan_entry, ...],   # cited and hash matches (skip)
          "missing":   [citation_entry, ...]  # cited but file is gone
        }
    Each scan_entry has the same shape as `scan-artifacts` output. Missing
    entries are the citation rows themselves (no on-disk presence)."""
    scanned = scan_artifacts(project_root)
    cited = parse_citations(manual_path)["artifacts"]
    cited_by_path = {c["path"]: c for c in cited}
    scanned_paths = {s["path"] for s in scanned}

    new: list[dict] = []
    changed: list[dict] = []
    unchanged: list[dict] = []
    for entry in scanned:
        prior = cited_by_path.get(entry["path"])
        if prior is None:
            new.append(entry)
        elif prior["hash"] != entry["hash"]:
            changed.append(entry)
        else:
            unchanged.append(entry)

    missing = [c for c in cited if c["path"] not in scanned_paths]

    return {"new": new, "changed": changed, "unchanged": unchanged, "missing": missing}


# ---------- HTML template versioning (mirrors product-backlog skill) ----------

def _read_html_version(text: str) -> int | None:
    match = HTML_VERSION_RE.search(text)
    return int(match.group(1)) if match else None


def html_template_version() -> int:
    if not TEMPLATE_HTML_PATH.exists():
        raise FileNotFoundError(
            f"bundled HTML template missing at {TEMPLATE_HTML_PATH}"
        )
    version = _read_html_version(TEMPLATE_HTML_PATH.read_text(encoding="utf-8"))
    if version is None:
        raise ValueError(
            f"template at {TEMPLATE_HTML_PATH} has no "
            f"<!-- user-manual-dashboard-version: N --> marker"
        )
    return version


def html_on_disk_version(html_path: Path) -> int:
    """Read the version marker from a user-generated HTML file on disk.

    Mirrors html_template_version() but for the file the user/skill wrote
    (e.g. <project>/docs/user-manual/user-manual.html), not the bundled
    template. Use to decide whether regenerate_html_if_stale() will copy.

    Raises FileNotFoundError if html_path is missing, ValueError if the file
    exists but has no version marker.
    """
    if not html_path.exists():
        raise FileNotFoundError(f"html file not found: {html_path}")
    version = _read_html_version(html_path.read_text(encoding="utf-8"))
    if version is None:
        raise ValueError(
            f"{html_path} has no <!-- user-manual-dashboard-version: N --> marker"
        )
    return version


def regenerate_html_if_stale(html_path: Path) -> str:
    template_version = html_template_version()
    html_path.parent.mkdir(parents=True, exist_ok=True)

    if not html_path.exists():
        shutil.copyfile(TEMPLATE_HTML_PATH, html_path)
        return "created"

    existing_version = _read_html_version(html_path.read_text(encoding="utf-8"))
    if existing_version is None or existing_version < template_version:
        shutil.copyfile(TEMPLATE_HTML_PATH, html_path)
        return "regenerated"

    return "unchanged"


# ---------- CLI ----------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML-ish frontmatter (--- ... ---) from body. Returns (meta, body).
    Tolerant: if no frontmatter, returns ({}, text).
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _extract_title_from_md(text: str, fallback: str) -> str:
    """Title resolution order: frontmatter title: > first H1 > filename fallback."""
    meta, body = _parse_frontmatter(text)
    if meta.get("title"):
        return meta["title"]
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def write_index(html_dir: Path, md_paths: list[Path]) -> Path:
    """Write manual-index.json into html_dir. Returns the path written."""
    manuals = []
    for p in md_paths:
        if not p.exists():
            print(f"warn: {p} does not exist, skipping", file=sys.stderr)
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        meta, _ = _parse_frontmatter(text)
        rel = p.resolve().relative_to(html_dir.resolve())
        # Use forward slashes for web-safety
        rel_str = str(rel).replace(os.sep, "/")
        title = meta.get("title") or _extract_title_from_md(text, p.stem)
        manuals.append({
            "file": rel_str,
            "title": title,
            "module": meta.get("module", ""),
            "description": meta.get("description", ""),
            "order": int(meta["order"]) if meta.get("order", "").isdigit() else 999,
        })
    manuals.sort(key=lambda m: (m["order"], m["title"]))
    out = {
        "version": 1,
        "generated": now_et(),
        "manuals": manuals,
    }
    out_path = html_dir / "manual-index.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def _slugify_for_id(name: str) -> str:
    """Make a safe DOM id from a filename. e.g. '财务-使用手册.md' -> 'md-xn--wgv4a9ih6f'."""
    import re as _re
    import unicodedata
    # Try to keep ASCII by NFKD-normalizing and dropping non-ASCII
    base = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    nfkd = unicodedata.normalize("NFKD", base)
    ascii_form = nfkd.encode("ascii", "ignore").decode("ascii")
    safe = _re.sub(r"[^A-Za-z0-9_-]", "-", ascii_form).strip("-")
    if not safe:
        # Pure non-ASCII: just hex-encode the original
        safe = "x" + "".join(f"{ord(c):x}" for c in base)[:32]
    return safe


def build_standalone(html_template_path: Path, html_out_path: Path, md_paths: list[Path]) -> Path:
    """Read the html template, inline all .md files as <script> blocks, write out.

    The output html reads from the inline <script> blocks first (so file:// works),
    falling back to fetch() (so it still works under HTTP if you want to add more
    manuals later).
    """
    html = html_template_path.read_text(encoding="utf-8")
    # Preserve whatever version the template has — don't force a number here,
    # that would silently regress the version on every build.
    # Insert inline markdown blocks right after <body> opens — must be BEFORE
    # the IIFE boot script that reads them. <body> opening tag is more
    # reliable than </head> across templating variations.
    body_open = html.find("<body>")
    if body_open < 0:
        body_open = html.find("<body ")
    if body_open < 0:
        raise ValueError("html template has no <body>")
    body_open_end = html.find(">", body_open) + 1  # position right after >

    inline_blocks = []
    for p in md_paths:
        if not p.exists():
            print(f"warn: {p} not found, skipping", file=sys.stderr)
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        # Escape </script> to avoid breaking out of the script tag
        text = text.replace("</script>", "<\\/script>")
        sid = _slugify_for_id(p.name)
        rel = p.name  # already relative to html dir (caller responsibility)
        inline_blocks.append(
            f'<script type="text/markdown" data-file="{rel}" id="md-{sid}">\n'
            f'{text}\n'
            f'</script>'
        )

    # Insert right after <body>, before the IIFE script
    insertion = "\n<!-- INLINE: standalone build, do not edit by hand -->\n" + "\n".join(inline_blocks) + "\n"
    html = html[:body_open_end] + insertion + html[body_open_end:]

    html_out_path.write_text(html, encoding="utf-8")
    return html_out_path




# ---------- Extract subcommand wrappers (v2 D2) ----------

def cmd_extract_tasks(args):
    """extract-tasks <spec.md> [...]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-tasks.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_fields(args):
    """extract-fields [--vue|--java] <path> [...]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-fields.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_routes(args):
    """extract-routes <router-file>"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-routes.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_roles(args):
    """extract-roles <backend-root> [<frontend-root>]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-roles.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_openapi(args):
    """extract-openapi <openapi.yaml-or-json>"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-openapi.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_record_manual(args):
    """v0.2.3: recording phase helper. See SKILL.md §14.

    Usage:
      record-manual <manual.md>                           # scan + report placeholders
      record-manual <manual.md> --generate-template <out>  # emit recorder script template
      record-manual <manual.md> --apply-mapping <json>     # replace placeholders with real paths

    Placeholder syntax (v1 standard):
      [SCREENSHOT: <name>.png]
      [VIDEO: <name>.mp4]   (or [VIDEO NEEDED] / [SCREENSHOT NEEDED] for missing)

    Mapping JSON (for --apply-mapping):
      {
        "01-list": "docs/user-manual/screenshots/sys/01-list.png",
        "demo": "docs/user-manual/screenshots/sys/demo-flow/demo-flow.mp4"
      }
    Keys are the placeholder name (without extension or brackets).
    """
    if not args:
        print("usage: record-manual <manual.md> [--generate-template <out>] [--apply-mapping <json>]",
              file=sys.stderr)
        return 2
    manual_path = Path(args[0])
    if not manual_path.exists():
        print(f"error: {manual_path} not found", file=sys.stderr)
        return 1

    # Parse flags
    gen_template = None
    apply_mapping = None
    i = 1
    while i < len(args):
        if args[i] == "--generate-template" and i + 1 < len(args):
            gen_template = Path(args[i + 1])
            i += 2
        elif args[i] == "--apply-mapping" and i + 1 < len(args):
            apply_mapping = Path(args[i + 1])
            i += 2
        else:
            print(f"error: unknown arg {args[i]!r}", file=sys.stderr)
            return 2

    text = manual_path.read_text(encoding="utf-8", errors="replace")
    placeholders = scan_recording_placeholders(text)

    # --apply-mapping: replace and write back
    if apply_mapping is not None:
        if not apply_mapping.exists():
            print(f"error: mapping file {apply_mapping} not found", file=sys.stderr)
            return 1
        mapping = json.loads(apply_mapping.read_text())
        new_text, replaced, missing = apply_recording_mapping(text, mapping)
        manual_path.write_text(new_text, encoding="utf-8")
        print(f"updated: {manual_path}")
        print(f"  replaced: {len(replaced)} placeholders")
        if replaced:
            for k, v in sorted(replaced.items()):
                print(f"    [SCREENSHOT: {k}.*] / [VIDEO: {k}.*]  ->  {v}")
        if missing:
            print(f"  placeholders still missing: {len(missing)}")
            for name in missing:
                print(f"    [SCREENSHOT: {name}.*] / [VIDEO: {name}.*]  (no mapping)")
        return 0

    # Default: report
    if not placeholders:
        print(f"NO_RECORDING_NEEDED: {manual_path}")
        print(f"  scanned: 1 file, 0 [SCREENSHOT:], 0 [VIDEO:], 0 [AI ANNOTATE:] placeholders")
        return 0
    screens = [p for p in placeholders if p["kind"] == "screenshot"]
    videos = [p for p in placeholders if p["kind"] == "video"]
    ai_anns = [p for p in placeholders if p["kind"] == "ai_annotate"]
    print(f"RECORDING_NEEDED: {manual_path}")
    print(f"  screenshots: {len(screens)}")
    for p in screens:
        print(f"    [SCREENSHOT: {p['name']}.png]")
    print(f"  videos: {len(videos)}")
    for p in videos:
        print(f"    [VIDEO: {p['name']}.mp4]")
    if ai_anns:
        print(f"  ai_annotates: {len(ai_anns)}  (v0.2.4: agent-mediated, see SKILL.md §15)")
        for p in ai_anns:
            print(f"    [AI ANNOTATE: {p['name']}]")
    print()
    print("Next step (LLM agent): see SKILL.md §14 — recording phase.")
    print("  1. Ask the user for: target URL, login credentials, mode (record/screenshot-only/skip).")
    print("  2. If record/screenshot-only: invoke the recorder opt-in plugin.")
    print(f"  3. After recorder produces assets: `record-manual {manual_path} --apply-mapping <json>`")
    if ai_anns:
        print("     (also: handle pending_ai_annotations via §15)")

    # --generate-template: also emit a recorder script template
    if gen_template is not None:
        template = build_recorder_template(manual_path.stem, placeholders)
        gen_template.parent.mkdir(parents=True, exist_ok=True)
        gen_template.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        print(f"  template: {gen_template}")
    return 0


# Placeholder syntax:
#   [SCREENSHOT: <name>.png]    [SCREENSHOT NEEDED: <name>.png]
#   [VIDEO: <name>.mp4]         [VIDEO NEEDED: <name>.mp4]
#   [AI ANNOTATE: <name>]        v0.2.4: agent-mediated vision annotation
# All three kinds live in the same scan + apply-mapping pipeline.
_PLACEHOLDER_RE = re.compile(
    r"\[(?P<kind>SCREENSHOT|VIDEO|AI\s+ANNOTATE)(?:\s+NEEDED)?\s*:\s*(?P<name>[A-Za-z0-9_\-]+)(?:\.\w+)?\]"
)


def scan_recording_placeholders(text: str) -> list[dict]:
    """Find all recording placeholders in text.

    v0.2.3: placeholders inside fenced code blocks (```...```) are
    ignored — those are documentation examples showing the syntax,
    not real recording targets.

    v0.2.4: also recognizes `[AI ANNOTATE: <name>]` markers. These are
    deferred to §15 of SKILL.md — the recorder writes a request file,
    the agent fulfills it via its own LLM, recorder applies Pillow
    annotation on re-run of `apply-ai-responses`.

    Returns list of {"kind": "screenshot"|"video"|"ai_annotate", "name": str,
                    "line": int, "raw": str}.
    """
    out = []
    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for m in _PLACEHOLDER_RE.finditer(line):
            kind_raw = m.group("kind").replace(" ", "").lower()  # "AIANNOTATE" → "aiannotate"
            if kind_raw == "aiannotate":
                kind = "ai_annotate"
            elif kind_raw == "video":
                kind = "video"
            else:
                kind = "screenshot"
            out.append({"kind": kind, "name": m.group("name"), "line": i, "raw": m.group(0)})
    return out


def build_recorder_template(manual_name: str, placeholders: list[dict]) -> dict:
    """Generate a recorder script template the LLM agent can fill in.

    Template fields the LLM must fill:
      - url: target application URL (e.g. https://app.example.com)
      - auth_env: list of env var names for login creds
      - steps: ordered list of {action: ...} dicts

    Screenshots from the manual become explicit "screenshot" steps. Videos
    become "video_start" / "video_stop" pairs surrounding the relevant steps.
    AI ANNOTATE markers become "ai_annotate" steps — the recorder will
    write a request file and yield; the agent fulfills via its own LLM
    (see recorder §15 / SKILL.md §15).
    """
    return {
        "_doc": (
            f"Recorder script template generated for {manual_name}. "
            "The LLM agent must fill in `url`, `auth_env`, and flesh out each "
            "`steps` entry with concrete CSS selectors / text. Then run via "
            "`python3 -m recorder_plugin.cli run <this-file>.json` (requires the "
            "recorder opt-in plugin; see recorder/INSTALL.md). After it finishes, "
            "produce a mapping JSON {placeholder_name: real_asset_path} and run "
            "`record-manual <manual.md> --apply-mapping <mapping.json>`."
        ),
        "name": manual_name,
        "url": "<TODO: target URL>",
        "viewport": {"width": 1440, "height": 900},
        "output_dir": f"docs/user-manual/screenshots/<TODO: domain>",
        "auth_env": ["AUTH_USER", "AUTH_PASS", "AUTH_TOTP_SECRET"],
        "steps": [
            {"action": "navigate", "url": "/<TODO: starting route>"},
            {"action": "wait_for", "strategy": "networkidle"},
            *_step_template_lines(placeholders),
        ],
    }


def _step_template_lines(placeholders: list[dict]) -> list[dict]:
    """Convert placeholders into ordered recorder step stubs.

    Each screenshot → one `screenshot` step. Each video → a video_start /
    / video_stop pair surrounding the closest preceding screenshot.
    Each AI ANNOTATE → one `ai_annotate` step (with a `screenshot` field
    pointing at the source PNG; agent fulfills via its own LLM in §15).
    """
    out = []
    last_video_started = False
    for p in placeholders:
        if p["kind"] == "screenshot":
            out.append({
                "action": "screenshot",
                "name": p["name"],
                "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50,
                              "label": "<TODO: caption>"}],
            })
        elif p["kind"] == "video":
            if not last_video_started:
                out.append({"action": "video_start", "name": p["name"]})
                last_video_started = True
            else:
                # Multiple videos in a row: stop the previous before starting the next
                out.append({"action": "video_stop", "name": f"<TODO: previous-video>"})
                out.append({"action": "video_start", "name": p["name"]})
        elif p["kind"] == "ai_annotate":
            out.append({
                "action": "ai_annotate",
                "screenshot": p["name"],
                "prompt": "",  # F3 fix: agent MUST fill in. Empty prompt -> script runner warns to stderr.
            })
    if last_video_started:
        out.append({"action": "video_stop", "name": "<TODO: last-video>"})
    return out


def apply_recording_mapping(text: str, mapping: dict) -> tuple[str, dict, list]:
    """Replace placeholders in text with real asset paths from mapping.

    Recognizes all 3 placeholder kinds (SCREENSHOT, VIDEO, AI ANNOTATE).

    v0.2.4 naming convention for the mapping keys:
      - Plain name (e.g. "01-list") -> replaces [SCREENSHOT: 01-list.*]
        and [VIDEO: 01-list.*] placeholders. Value is the raw .png / .mp4 path.
      - Prefixed name (e.g. "ai-annotated-01-list") -> replaces only
        [AI ANNOTATE: 01-list] placeholders. Value is the *.ai-annotated.png
        path produced by `apply-ai-responses`.

    This separation lets the agent provide different paths for the raw
    screenshot vs. the AI-annotated version. Documented in SKILL.md Sec 15.

    F1 fix: replace ALL occurrences of each placeholder name (not just
    the first). Previous count=1 left 2nd+ same-name placeholders un-replaced.
    F2 fix: AI ANNOTATE placeholders REQUIRE the `ai-annotated-` prefix
    mapping. If only a plain-name mapping exists for the same name, that's
    a config error and the AI ANNOTATE is reported in missing (with
    explicit reason) instead of being silently dropped.
    """
    reemplazado = {}
    missing = []
    for key, real_path in mapping.items():
        if key.startswith("ai-annotated-"):
            name = key[len("ai-annotated-"):]
            pattern = re.compile(rf"\[AI\s+ANNOTATE\s*:\s*{re.escape(name)}(?:\.\w+)?\]")
        else:
            name = key
            pattern = re.compile(
                rf"\[(?P<kind>SCREENSHOT|VIDEO)(?:\s+NEEDED)?\s*:\s*{re.escape(name)}(?:\.\w+)?\]"
            )
        if pattern.search(text):
            new_text, n = pattern.subn(f"![{key}]({real_path})", text)  # count=0: replace all
            text = new_text
            reemplazado[key] = real_path
    remaining = scan_recording_placeholders(text)
    for p in remaining:
        if p["kind"] == "ai_annotate":
            prefixed_key = f"ai-annotated-{p['name']}"
            # F2 fix: explicit missing detection for AI ANNOTATE
            if prefixed_key in mapping:
                continue
            if p["name"] in mapping:
                missing.append({
                    "name": p["name"],
                    "kind": "ai_annotate",
                    "reason": f"AI ANNOTATE requires mapping key 'ai-annotated-{p['name']}', not plain '{p['name']}'. Plain key replaces [SCREENSHOT:] only.",
                })
            else:
                missing.append({
                    "name": p["name"],
                    "kind": "ai_annotate",
                    "reason": f"No mapping entry for this AI ANNOTATE. Add 'ai-annotated-{p['name']}' to mapping.",
                })
        else:
            if p["name"] not in mapping:
                missing.append({
                    "name": p["name"],
                    "kind": p["kind"],
                    "reason": f"No mapping entry for this {p['kind']} placeholder.",
                })
    return text, reemplazado, missing
def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("--help", "-h", "help"):
        print(__doc__)
        return 0 if len(argv) >= 2 else 2

    cmd = argv[1]

    if cmd == "now-et":
        print(now_et())
        return 0

    if cmd == "init":
        if len(argv) != 3:
            print("usage: manual_helper.py init <md-path>", file=sys.stderr)
            return 2
        target = Path(argv[2])
        created = init(target)
        print(f"{'created' if created else 'exists'}: {target}")
        return 0

    if cmd == "init-skill":
        proj_root = Path(argv[2]) if len(argv) == 3 else Path.cwd()
        try:
            result = init_skill(proj_root)
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(f"project root: {proj_root}")
        for p in result["created"]:
            print(f"  created: {p}")
        for p in result["skipped"]:
            print(f"  skipped (exists): {p}")
        if "personas_required" in result:
            print(f"  personas: {result['personas_required']} (present)")
        if not result["created"]:
            print("(nothing to do -- already initialized)")
        return 0

    if cmd == "validate-config":
        proj_root = Path(argv[2]) if len(argv) == 3 else Path.cwd()
        result = validate_config(proj_root)
        if "--json" in argv:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result["errors"]:
                print("ERRORS:")
                for e in result["errors"]:
                    print(f"  - {e}")
            if result["warnings"]:
                print("WARNINGS:")
                for w in result["warnings"]:
                    print(f"  - {w}")
            if result["ok"]:
                print("OK: manual-config.json + personas.json valid.")
                print(f"     personas: {len(result['info'].get('persona_ids', []))}")
                print(f"     granularity: {result['info'].get('granularity')}")
                print(f"     covered objectives: {result['info'].get('covered_objectives', [])}")
        return 0 if result["ok"] else 1
    if cmd == "extract-tasks":
        return cmd_extract_tasks(argv[2:])
    if cmd == "extract-fields":
        return cmd_extract_fields(argv[2:])
    if cmd == "extract-routes":
        return cmd_extract_routes(argv[2:])
    if cmd == "extract-roles":
        return cmd_extract_roles(argv[2:])
    if cmd == "extract-openapi":
        return cmd_extract_openapi(argv[2:])

    if cmd == "scan-artifacts":
        if len(argv) != 3:
            print("usage: manual_helper.py scan-artifacts <project-root>", file=sys.stderr)
            return 2
        entries = scan_artifacts(Path(argv[2]))
        json.dump(entries, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "parse-citations":
        if len(argv) != 3:
            print("usage: manual_helper.py parse-citations <md-path>", file=sys.stderr)
            return 2
        result = parse_citations(Path(argv[2]))
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "diff-artifacts":
        if len(argv) != 4:
            print("usage: manual_helper.py diff-artifacts <project-root> <md-path>", file=sys.stderr)
            return 2
        result = diff_artifacts(Path(argv[2]), Path(argv[3]))
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "record-manual":
        return cmd_record_manual(argv[2:])

    if cmd == "html-template-version":
        print(html_template_version())
        return 0

    if cmd == "html-on-disk-version":
        if len(argv) != 3:
            print(
                "usage: manual_helper.py html-on-disk-version <html-path>",
                file=sys.stderr,
            )
            return 2
        try:
            print(html_on_disk_version(Path(argv[2])))
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0

    if cmd == "regenerate-html-if-stale":
        if len(argv) != 3:
            print(
                "usage: manual_helper.py regenerate-html-if-stale <html-path>",
                file=sys.stderr,
            )
            return 2
        result = regenerate_html_if_stale(Path(argv[2]))
        print(f"{result}: {argv[2]}")
        return 0

    if cmd == "write-index":
        if len(argv) < 4:
            print(
                "usage: manual_helper.py write-index <html-dir> <md-path> [more...]",
                file=sys.stderr,
            )
            return 2
        html_dir = Path(argv[2])
        md_paths = [Path(p) for p in argv[3:]]
        out = write_index(html_dir, md_paths)
        print(f"wrote: {out}")
        return 0

    if cmd == "build-standalone":
        if len(argv) < 5:
            print(
                "usage: manual_helper.py build-standalone <html-template> <html-out> <md-path> [more...]",
                file=sys.stderr,
            )
            return 2
        tmpl = Path(argv[2])
        out = Path(argv[3])
        md_paths = [Path(p) for p in argv[4:]]
        result = build_standalone(tmpl, out, md_paths)
        print(f"wrote: {result}")
        return 0

    if cmd == "read-config":
        cmd_read_config(argv[2:])
        return 0
    if cmd == "init-db":
        rc = cmd_init_db(argv[2:])
        return rc if rc is not None else 0
    if cmd == "upsert-manual":
        rc = cmd_upsert_manual(argv[2:])
        return rc if rc is not None else 0
    if cmd == "upload-asset":
        rc = cmd_upload_asset(argv[2:])
        return rc if rc is not None else 0

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2



# ---------- DB mode: helper subcommands (db backend = FastAPI at MANUAL_API_BASE) ----------

CONFIG_FILENAME = "manual-config.json"
# 配置文件查找路径(按这个顺序)
CONFIG_SEARCH_PATHS = [
    "docs/user-manual/manual-config.json",   # 项目级(<project>/docs/user-manual/ 风格)
    "manual-config.json",                    # 仓库根
]

def find_config(start_dir: Path) -> Path | None:
    """从 start_dir 向上找 manual-config.json(优先近的)。
    额外查找 docs/user-manual/manual-config.json(项目级,GCR 风格)。"""
    cur = start_dir.resolve()
    for parent in [cur, *cur.parents]:
        cand = parent / CONFIG_FILENAME
        if cand.exists():
            return cand
    # 备选: 项目根的 docs/user-manual/ 下面
    for parent in [cur, *cur.parents]:
        cand = parent / "docs" / "user-manual" / CONFIG_FILENAME
        if cand.exists():
            return cand
    return None

def load_config() -> dict:
    """从 cwd 向上找 manual-config.json, 没找到给一个 file 模式默认 config。"""
    cfg_path = find_config(Path.cwd())
    if not cfg_path:
        return {
            "storage": "file",
            "object_store": "minio",
            "object_store_config": {
                "endpoint": "http://localhost:9100",
                "bucket": "manuals",
                "access_key": "minioadmin",
                "secret_key": "minioadmin",
                "public_base_url": "http://localhost:9100/manuals",
            },
            "db": {"dsn": "postgresql://user:CHANGE_ME@localhost:5432/user_manual"},
            "api": {"base_url": "http://localhost:8765"},
            "auth": {"enabled": False, "token": ""},
        }
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)

def api_base_from_config(cfg: dict) -> str:
    return cfg.get("api", {}).get("base_url", "http://localhost:8765").rstrip("/")

def read_md_split(raw_md: str) -> tuple[dict, str]:
    """(frontmatter, body) — 与 _parse_frontmatter 行为一致。"""
    fm, body = _parse_frontmatter(raw_md)
    return fm, body

def http_post_json(url: str, payload: dict, token: str = "") -> dict:
    """POST JSON. 简单实现, 不引外部依赖。"""
    import urllib.request, urllib.error
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} -> {e.code} {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"POST {url} unreachable: {e.reason}") from e

def http_post_multipart(url: str, file_path: Path, caption: str, token: str = "") -> dict:
    """POST multipart/form-data, 单个 file 字段 + caption。"""
    import urllib.request, urllib.error, uuid, mimetypes
    boundary = f"----manual{uuid.uuid4().hex}"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    parts: list[bytes] = []
    def add_field(name: str, value: str):
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    def add_file(name: str, filename: str, content: bytes, mime: str):
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(content)
        parts.append(b"\r\n")
    add_field("caption", caption)
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    add_file("upload", file_path.name, file_path.read_bytes(), mime)
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"POST {url} -> {e.code} {e.read().decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"POST {url} unreachable: {e.reason}") from e

# ---- new subcommands ----

def cmd_read_config(_args):
    cfg = load_config()
    cfg_path = find_config(Path.cwd())
    print(f"# source: {cfg_path or '(defaults, no config file found)'}")
    print(json.dumps(cfg, indent=2, ensure_ascii=False))

def cmd_init_db(args):
    """init-db: 把 schema 推到 DB(创建表, drop existing)。
    schema.sql 路径: <skill_dir>/db/schema.sql, 或 环境变量 MANUAL_DB_SCHEMA。
    """
    import urllib.request
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"WARN: storage={cfg.get('storage')!r}, 仍按 db 模式执行", file=sys.stderr)
    dsn = cfg.get("db", {}).get("dsn") or os.environ.get("MANUAL_DB_DSN", "")
    if not dsn:
        print("error: no db.dsn in config and MANUAL_DB_DSN not set", file=sys.stderr)
        return 1
    # 找 schema.sql
    skill_dir = Path(__file__).resolve().parent.parent  # skill-template/scripts/.. -> skill-template
    schema_candidates = [
        skill_dir / "db" / "schema.sql",
        skill_dir.parent / "user-manual-api" / "schema.sql",  # 项目级 db 旁
        Path.cwd() / "docs" / "user-manual-api" / "schema.sql",
    ]
    schema_path = next((p for p in schema_candidates if p.exists()), None)
    if not schema_path:
        print(f"error: schema.sql not found, tried: {[str(p) for p in schema_candidates]}", file=sys.stderr)
        return 1
    sql = schema_path.read_text(encoding="utf-8")
    # 用 psycopg2 风格? 不引外部依赖, 用 asyncpg 在 subprocess 里跑
    # 简化: 用 docker exec / 直接 psql 都不行(helper 是纯 stdlib)
    # 走 API? schema 推送不走 API(API 不应能 drop)。这里直接 require asyncpg。
    try:
        import asyncpg
    except ImportError:
        print("error: asyncpg required for init-db. install: pip install asyncpg", file=sys.stderr)
        return 1
    async def run():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()
    asyncio.run(run())
    print(f"initialized: {dsn} (schema: {schema_path})")
    return 0

def cmd_upsert_manual(args):
    """upsert-manual <md-path>: 读 md, 拆 frontmatter/body, POST /api/manuals."""
    if len(args) != 1:
        print("usage: manual_helper.py upsert-manual <md-path>", file=sys.stderr)
        return 2
    md_path = Path(args[0])
    if not md_path.exists():
        print(f"error: {md_path} not found", file=sys.stderr)
        return 1
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"error: storage={cfg.get('storage')!r}, db mode only", file=sys.stderr)
        return 1
    raw = md_path.read_text(encoding="utf-8")
    fm, body = read_md_split(raw)
    # module / module_code 双字段:
    # - module:  显示名(可中文,可含空格)
    # - module_code: 机器可读 key(英文/数字/下划线,作 S3 prefix)
    # 没显式给 module_code 时,API 端会用 module 字段兜底(ASCII-slugify,中文 → MISC)
    payload = {
        "file": md_path.name,
        "module": fm.get("module") or fm.get("module_code") or "MISC",
        "module_code": fm.get("module_code") or None,
        "title": fm.get("title") or md_path.stem,
        "description": fm.get("description") or None,
        "order": int(fm["order"]) if str(fm.get("order", "")).isdigit() else 999,
        "version": fm.get("version") or "v0.1",
        "version_date": fm.get("version_date") or None,
        "body_md": body,
        "raw_md": raw,
    }
    url = f"{api_base_from_config(cfg)}/api/manuals"
    token = cfg.get("auth", {}).get("token", "") if cfg.get("auth", {}).get("enabled") else ""
    try:
        r = http_post_json(url, payload, token)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"upserted: {r.get('file')} (id={r.get('id', '?')}, version={r.get('version')})")
    return 0

def cmd_upload_asset(args):
    """upload-asset <manual-file> <asset-path> [--caption TEXT]"""
    if len(args) < 2:
        print("usage: manual_helper.py upload-asset <manual-file-name> <asset-path> [--caption TEXT]", file=sys.stderr)
        return 2
    manual_file = args[0]
    asset_path = Path(args[1])
    caption = ""
    if "--caption" in args:
        i = args.index("--caption")
        if i + 1 < len(args):
            caption = args[i + 1]
    if not asset_path.exists():
        print(f"error: {asset_path} not found", file=sys.stderr)
        return 1
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"error: storage={cfg.get('storage')!r}, db mode only", file=sys.stderr)
        return 1
    # 1) ensure manual exists
    fm_url = f"{api_base_from_config(cfg)}/api/manuals"
    token = cfg.get("auth", {}).get("token", "") if cfg.get("auth", {}).get("enabled") else ""
    # 2) upload
    up_url = f"{api_base_from_config(cfg)}/api/manuals/{manual_file}/assets"
    try:
        r = http_post_multipart(up_url, asset_path, caption, token)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"uploaded: {r['object_key']} -> {r['public_url']} ({r['size']} bytes, {r['kind']})")
    # 3) print md-insert hint
    print(f"# md 引用: ![{caption or asset_path.stem}]({r['public_url']})")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
