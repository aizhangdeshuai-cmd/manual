
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

from .common import (
    SUPERPOWERS_KINDS,
    CITATIONS_HEADING,
    ARTIFACTS_SUBHEADING,
    EXTERNAL_SUBHEADING,
)

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


# ---------- Fill in citation SHAs from scan-artifacts (v0.3.2) ----------


def fill_citation_shas(manual_path: Path, project_root: Path) -> dict:
    """v0.3.2 (P1 #9 from eval report): the LLM agent often writes
    `(auto)` or an empty string as the SHA in the Citations table,
    because it doesn't have the real SHA256. This subcommand closes
    that loop: read the existing Citations, cross-reference with
    scan-artifacts (which has real SHAs), and emit a corrected
    table the agent just pastes in.

    Returns:
      {
        "replacements": [{"path": ..., "oldsha": ..., "newsha": ...}, ...],
        "unresolved":   [{"path": ..., "current_sha": ...}, ...],
        "markdown_table": "## Citations\n\n### Project artifacts\n| ... |"
      }

    `replacements` = citations that were updated (had a placeholder
    or stale SHA; we have a real one now).
    `unresolved`   = citations where the on-disk artifact doesn't
    exist (file path typo, or the file was deleted). The agent must
    investigate these manually.
    `markdown_table` = the corrected table fragment (human form)
    or absent if --json was used.
    """
    cited = parse_citations(manual_path)["artifacts"]
    scanned = scan_artifacts(project_root)
    scanned_by_path = {s["path"]: s for s in scanned}

    replacements: list[dict] = []
    unresolved: list[dict] = []
    for entry in cited:
        path = entry["path"]
        old_sha = entry.get("hash", "")
        scan_entry = scanned_by_path.get(path)
        new_sha: str | None = None
        if scan_entry is not None:
            new_sha = scan_entry.get("hash", "")
        else:
            # v0.3.2 fallback: scan_artifacts only walks
            # docs/superpowers/{kind}/*.md, but manuals can cite
            # arbitrary project files (docs/design/, backend/...).
            # If the cited path exists on disk, hash it directly.
            abs_path = (project_root / path).resolve()
            if abs_path.exists() and abs_path.is_file():
                try:
                    raw = abs_path.read_bytes()
                    # Full 64-char SHA (not the 16-char prefix that
                    # scan_artifacts uses for compactness in the
                    # citation table — for the fill-in we want the
                    # authoritative value).
                    new_sha = hashlib.sha256(raw).hexdigest()
                except OSError:
                    pass
        if new_sha is None:
            # File referenced in citations but not on disk (or unreadable)
            unresolved.append({"path": path, "current_sha": old_sha})
            continue
        # Only emit a replacement if the SHA actually changed (avoids
        # no-op diffs that the agent would have to inspect)
        if old_sha == new_sha:
            continue
        replacements.append({
            "path": path,
            "oldsha": old_sha,
            "newsha": new_sha,
        })

    markdown_table = _render_filled_citations_table(manual_path, replacements, unresolved)
    return {
        "replacements": replacements,
        "unresolved": unresolved,
        "markdown_table": markdown_table,
    }


def _render_filled_citations_table(
    manual_path: Path,
    replacements: list[dict],
    unresolved: list[dict],
) -> str:
    """Render a corrected Citations table fragment. Reads the original
    manual, finds the Citations section, and replaces the SHA cell
    for any path in `replacements`. Unresolved paths are left as-is
    but tagged with a stderr-style comment so the agent notices.

    If the manual has no Citations section yet (scaffold-only), this
    returns a template the agent can paste in.
    """
    if not manual_path.exists():
        return ""
    text = manual_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find the Citations section
    cite_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == CITATIONS_HEADING:
            cite_idx = idx
            break
    if cite_idx is None:
        return ""  # No citations section; nothing to fix

    # Build a lookup path -> newsha (only the ones that changed)
    path_to_new_sha = {r["path"]: r["newsha"] for r in replacements}
    unresolved_paths = {r["path"] for r in unresolved}

    # Walk the table under "### Project artifacts" and rewrite SHA cells
    in_artifacts = False
    for idx in range(cite_idx, len(lines)):
        stripped = lines[idx].strip()
        if stripped == ARTIFACTS_SUBHEADING:
            in_artifacts = True
            continue
        if in_artifacts and (stripped.startswith("## ") or stripped.startswith("### ")):
            break  # Left the artifacts subtable
        if not in_artifacts:
            continue
        if not stripped.startswith("|"):
            continue
        # Try to identify a path on this row and rewrite its SHA
        cells = _split_table_row(lines[idx])
        if len(cells) < 4:
            continue
        path_cell = cells[0].strip()
        m = re.match(r"^\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)$", path_cell)
        bare_path = m.group("target") if m else path_cell
        # Normalize to project-root-relative for lookup
        normalized = _normalize_artifact_path(bare_path, manual_path)
        if normalized in path_to_new_sha:
            new_sha = path_to_new_sha[normalized]
            # Replace the hash cell (index 3). Preserve backticks
            # if the original had them.
            old_cell = cells[3]
            wrapped = old_cell.startswith("`") and old_cell.endswith("`")
            replacement = f"`{new_sha}`" if wrapped else new_sha
            # Rebuild the line: same number of | separators
            new_cells = cells[:3] + [replacement] + cells[4:]
            lines[idx] = "|" + "|".join(new_cells) + "|"
        elif normalized in unresolved_paths:
            # Tag unresolved with a trailing `⚠️ unresolved` so the
            # agent sees it
            if "⚠️" not in cells[3]:
                cells[3] = cells[3] + " ⚠️ unresolved"
                lines[idx] = "|" + "|".join(cells) + "|"

    return "\n".join(lines[cite_idx:])


def _cmd_fill_citation_shas(args: list[str]) -> int:
    """v0.3.2 CLI: emit the corrected Citations table with real SHAs."""
    # Filter out flag args before counting positionals
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) < 1 or len(positional) > 2:
        print("usage: manual_helper.py fill-citation-shas [--json] <manual.md> [project-root]",
              file=sys.stderr)
        return 2
    manual_path = Path(positional[0])
    project_root = Path(positional[1]) if len(positional) == 2 else _infer_project_root(manual_path)
    if not manual_path.exists():
        print(f"error: {manual_path} not found", file=sys.stderr)
        return 1
    result = fill_citation_shas(manual_path, project_root)
    if "--json" in args:
        # Drop the markdown_table from JSON (it's noisy for machines)
        out = {k: v for k, v in result.items() if k != "markdown_table"}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not result["replacements"] and not result["unresolved"]:
            print("OK: all citation SHAs are already up-to-date.")
            return 0
        print(f"=== Citation SHA Fill-In ({manual_path}) ===")
        print()
        if result["replacements"]:
            print(f"  Replaced {len(result['replacements'])} placeholder/stale SHAs:")
            for r in result["replacements"]:
                old = r["oldsha"] or "(empty)"
                print(f"    {r['path']}")
                print(f"      {old!r}  →  {r['newsha'][:16]}...")
        if result["unresolved"]:
            print()
            print(f"  Unresolved ({len(result['unresolved'])} cited paths not on disk):")
            for u in result["unresolved"]:
                print(f"    {u['path']}  (current SHA: {u['current_sha']!r})")
        print()
        print("--- Corrected Citations table (paste into your manual) ---")
        print(result["markdown_table"])
    return 0


def _infer_project_root(manual_path: Path) -> Path:
    """Best-effort: if the manual is at docs/user-manual/manual/*.md,
    assume project_root is the cwd. Otherwise return cwd as-is."""
    return Path.cwd()


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


