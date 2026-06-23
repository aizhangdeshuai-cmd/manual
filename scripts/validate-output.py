#!/usr/bin/env python3
"""Validate generated user-manual markdown files against the 8 hard checks.

Usage:
    validate-output.py [--strict] [--json] [--unique] [--unique-allow=A,B]
                       <file.md> [...]

The 6 checks come from the user-manual skill style guide (see SKILL.md
section 5.4 and the task-card prompt). For each input .md, prints a one-line
summary in human form, or a JSON object with --json. Exits 0 unless --strict
is set and any file failed at least one check.

v0.2.2 — checks are more forgiving of LLM natural-language variance:
  - 7-field and 操作前必看 patterns use re.IGNORECASE
  - 操作前必看 count EXCLUDES occurrences inside fenced code blocks
    (so a documentation example "### 操作前必看" inside a code fence
    doesn't count toward the threshold)
  - role-permission matrix heading accepts Chinese synonyms
    (角色与权限速查 / 角色权限速查 / 角色与权限 / 角色/权限) and English
    (Role Quick Reference / Role Permissions / Role Quick Ref)
  - visual anchors and screenshot regex unchanged (those are stable)

v0.3.1 — added the 7th check: "screenshot files exist". Previous "screenshot
count" only counted `![alt](path.png)` mentions in the markdown text; an
LLM agent could pass with 26 placeholder references pointing to
non-existent files. The new check resolves each path relative to the
markdown file's directory and verifies the file is on disk. A `[SCREENSHOT:
x]` placeholder that the agent forgot to replace with a real recorder
asset now flags the manual as incomplete instead of silently passing.

v0.4.0 — added the 8th check: "screenshot unique" (opt-in via
 --unique). The recorder does not require an intervening
 click/type/wait_for between two screenshot steps, so an LLM agent
 can produce two byte-identical PNGs under different filenames
 (e.g. dashboard-home.png and module-map.png both showing the
 same dashboard). v0.4.0 reads the SHA256 of every referenced
 PNG and flags any hash referenced by 2+ distinct filenames.
 Default OFF to avoid breaking manuals that intentionally reuse
 a logo/branding image. The new check also accepts
 --unique-allow <basename,...> to whitelist shared assets.
"""
import json
import re
import sys
from pathlib import Path

# Strip markdown fenced code blocks so we don't count things in code samples.
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def _strip_code(text: str) -> str:
    """Remove fenced and inline code so regexes only match prose."""
    text = FENCE_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    return text


# v0.3.1: extract just the path part of an image link (used by the
# file-existence check). Same extension whitelist as the OLD "screenshot
# count" check (so the new check covers the same set of references).
IMAGE_LINK_PATH_RE = re.compile(
    r"!\[[^\]]*\]\(([^)]+\.(?:png|jpg|jpeg|webp)(?:\?[^)]*)?)\)",
    re.IGNORECASE,
)


def _extract_image_paths(text: str) -> list[str]:
    """Return image paths referenced by `![alt](path)` markdown image links.

    Skips http(s):// and data: URIs. Strips query strings and fragments.
    """
    out: list[str] = []
    for m in IMAGE_LINK_PATH_RE.finditer(text):
        path = m.group(1).strip()
        if path.startswith(("http://", "https://", "data:")):
            continue
        if "?" in path:
            path = path.split("?", 1)[0]
        if "#" in path:
            path = path.split("#", 1)[0]
        out.append(path)
    return out


# v0.3.2: pattern for unreplaced `[SCREENSHOT: x]` / `[VIDEO: x]`
# placeholders (not yet replaced with `![alt](path)` markdown image).
# Same shape as manual_helper._PLACEHOLDER_RE but only for the two
# kinds that map to asset files (not [AI ANNOTATE: x], which is a
# §15 vision-annotation marker, not a missing asset).
_UNREPLACED_PLACEHOLDER_RE = re.compile(
    r"\[(?P<kind>SCREENSHOT|VIDEO)(?:\s+NEEDED)?\s*:\s*"
    r"(?P<name>[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*)"
    r"(?:\.(?P<ext>png|mp4|jpg|jpeg|webm))?\]"
)


def _extract_unreplaced_placeholders(text: str) -> list[dict]:
    """v0.3.2: find `[SCREENSHOT: x]` / `[VIDEO: x]` placeholders that
    are still in the manual text (not replaced with `![alt](path)`
    markdown image). Each one represents a missing asset — the agent
    should have either recorded a real screenshot/video OR replaced
    the placeholder with a `![alt](path)` link.

    Skips occurrences inside fenced code blocks (so doc examples
    showing the placeholder syntax don't count).
    """
    out: list[dict] = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for m in _UNREPLACED_PLACEHOLDER_RE.finditer(line):
            kind = m.group("kind").lower()
            name = m.group("name")
            ext = m.group("ext") or ""
            full = f"{name}.{ext}" if ext else name
            out.append({"kind": kind, "name": full, "raw": m.group(0)})
    return out


def _is_placeholder_png(path: Path) -> bool:
    """v0.3.2: a PNG file is a 'placeholder' if its dimensions are < 50x50.
    Real screenshots are 1280x800+; 1×1 or 32×32 etc. means the LLM
    agent generated an empty stub to "satisfy" the file-existence
    check (or copy-pasted from a test fixture). Either way, it's not
    a real asset and should be reported as missing.

    Returns False for non-PNG files (videos, JPEGs aren't gated by
    size — the recorder could legitimately produce a 100×100 video
    thumbnail that we don't want to false-positive on).
    """
    if path.suffix.lower() != ".png":
        return False
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
        return w < 50 or h < 50
    except Exception:
        # Unreadable image — don't false-positive. Other checks
        # (validate-output's "screenshot files exist") already cover
        # the existence case; the user will see the file as present
        # and can investigate manually.
        return False


def _check_screenshot_files_exist(md_path: Path, text: str) -> dict:
    """For each `![alt](path)` image link in `text`, verify the file exists
    on disk relative to the markdown file's directory, AND has real
    dimensions (≥ 50×50 px). Also count any `[SCREENSHOT: x]` /
    `[VIDEO: x]` placeholders still in the text — those count as
    missing assets too.

    v0.3.1 → v0.3.2 evolutions:
      - 1×1 / 32×32 placeholder PNGs (LLM-generated stubs) used
        to pass; now reported as placeholder_png.
      - `[SCREENSHOT: x]` text placeholders used to be invisible
        to this check; now counted as unreplaced_placeholder.

    Returns the standard check-shaped dict plus:
      - present: image links with a real-sized file
      - placeholder_png_count: image links whose file exists but is < 50×50
      - unreplaced_placeholder_count: `[SCREENSHOT:]/[VIDEO:]` text in manual
      - missing_count: present - (total of all 3 categories)
      - missing_paths: first 5 issues (mix of file-missing and placeholder)
    """
    image_paths = _extract_image_paths(text)
    placeholders = _extract_unreplaced_placeholders(text)
    md_dir = md_path.parent
    present = 0
    placeholder_png_count = 0
    missing_paths: list[str] = []
    for ref in image_paths:
        target = (md_dir / ref).resolve()
        if not target.exists():
            missing_paths.append(ref)
        elif _is_placeholder_png(target):
            placeholder_png_count += 1
            missing_paths.append(f"{ref} (1×1 placeholder PNG)")
        else:
            present += 1
    # Add unreplaced placeholders to the missing list
    for ph in placeholders:
        missing_paths.append(f"[{ph['kind'].upper()}: {ph['name']}]")
    total = len(image_paths) + len(placeholders)
    missing_count = total - present
    return {
        "name": "screenshot files exist",
        "hits": present,
        "threshold": total,
        "comparison": "ge",
        # ok only when ALL categories pass: present == total AND no
        # placeholder PNGs AND no unreplaced placeholders. Since
        # present == total - missing_count, this simplifies to
        # missing_count == 0 AND placeholder_png_count == 0.
        "ok": (missing_count == 0 and placeholder_png_count == 0),
        "present": present,
        "missing_count": missing_count,
        "missing_paths": missing_paths[:5],
        "placeholder_png_count": placeholder_png_count,
        "unreplaced_placeholder_count": len(placeholders),
    }


def _check_screenshot_unique(
    md_path: Path, text: str, allow_paths: set | None = None
) -> dict:
    """v0.4.0: SHA256 every referenced PNG; flag any hash that 2+
    distinct filenames share. See docstring v0.4.0 for rationale.
    """
    image_paths = _extract_image_paths(text)
    md_dir = md_path.parent
    allow_paths = allow_paths or set()
    by_hash: dict = {}
    for ref in image_paths:
        target = (md_dir / ref).resolve()
        if not target.exists() or not target.is_file():
            continue
        if Path(ref).name in allow_paths:
            continue
        try:
            h = _sha256_file(target)
        except OSError:
            continue
        by_hash.setdefault(h, []).append((Path(ref).name, str(ref)))
    duplicates: list = []
    for h, refs in by_hash.items():
        unique_names = sorted({name for name, _ in refs})
        if len(unique_names) < 2:
            continue
        duplicates.append({
            "sha256": h,
            "files": unique_names,
            "occurrences": len(refs),
        })
    duplicates.sort(key=lambda d: d["sha256"])
    total = len(by_hash)
    dup_count = len(duplicates)
    return {
        "name": "screenshot unique (no duplicate content)",
        "hits": total - dup_count,
        "threshold": total,
        "comparison": "ge",
        "ok": (dup_count == 0),
        "unique_hashes": total,
        "duplicate_count": dup_count,
        "duplicates": duplicates[:5],
    }


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()



# Each check: (name, regex, threshold, comparison, exclude_code?)
# comparison is 'ge' (>=) or 'le' (<=).
CHECKS = [
    (
        "7-field hits",
        re.compile(
            r"适用角色|前置条件|操作前必看|^(?:###|####)\s*步骤|^(?:###|####)\s*成功后看到|^(?:###|####)\s*字段说明|^(?:###|####)\s*如果你卡住了|^(?:###|####)\s*相关任务",
            re.MULTILINE | re.IGNORECASE,
        ),
        6,
        "ge",
        True,
    ),
    (
        "操作前必看 blocks",
        re.compile(r"操作前必看", re.IGNORECASE),
        3,
        "ge",
        True,  # EXCLUDE code fences/inline-code occurrences
    ),
    (
        "visual anchors",
        re.compile(r"(⚠️|💡|❌|📌)"),
        3,
        "ge",
        False,
    ),
    (
        "appendix-A 6-col table",
        re.compile(r"^\| .* \| .* \| .* \| .* \| .* \| .* \|", re.MULTILINE),
        1,
        "ge",
        False,
    ),
    (
        "role-permission matrix",
        # Accept Chinese variants and English variants. Multi-line ^## matches
        # both ## and ### (role-permission matrix may be a sub-section).
        re.compile(
            r"^#{2,4}\s*"
            r"(?:"
            r"角色与权限\s*速查"        # 角色与权限速查
            r"|角色权限速查"             # 角色权限速查
            r"|角色与权限\b"             # 角色与权限 (truncated)
            r"|角色\s*[/／]\s*权限"      # 角色/权限
            r"|Role\s*Quick\s*Ref(?:erence)?"  # Role Quick Reference
            r"|Role\s*Permissions?(?:\s*Matrix)?"  # Role Permission(s) / Permission Matrix
            r")",
            re.MULTILINE | re.IGNORECASE,
        ),
        1,
        "ge",
        False,
    ),
    (
        "screenshot count",
        re.compile(
            r"!\[[^\]]*\]\([^)]+\.(?:png|jpg|jpeg|webp)(?:\?[^)]*)?\)",
            re.IGNORECASE,
        ),
        2,
        "ge",
        False,
    ),
]


def validate_file(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    text_for_prose = _strip_code(text)
    results = []
    all_ok = True
    for name, pattern, threshold, cmp, exclude_code in CHECKS:
        target = text_for_prose if exclude_code else text
        hits = len(pattern.findall(target))
        ok = (hits >= threshold) if cmp == "ge" else (hits <= threshold)
        all_ok = all_ok and ok
        results.append(
            {"name": name, "hits": hits, "threshold": threshold, "comparison": cmp, "ok": ok}
        )
    # v0.3.1: file-existence check. NOT in CHECKS because it depends on
    # the markdown file's directory (filesystem state), not just the text
    # content the regex-based checks need.
    file_check = _check_screenshot_files_exist(path, text)
    results.append({
        "name": file_check["name"],
        "hits": file_check["hits"],
        "threshold": file_check["threshold"],
        "comparison": file_check["comparison"],
        "ok": file_check["ok"],
        "present": file_check["present"],
        "missing_count": file_check["missing_count"],
        "missing_paths": file_check["missing_paths"],
        "placeholder_png_count": file_check["placeholder_png_count"],
        "unreplaced_placeholder_count": file_check["unreplaced_placeholder_count"],
    })
    all_ok = all_ok and file_check["ok"]
    # v0.4.0: opt-in unique-content check. Pop a module-level flag
    # (set by main from --unique) so test harnesses can override.
    if globals().get("UNIQUE_CHECK_ENABLED"):
        unique_check = _check_screenshot_unique(
            path, text, allow_paths=globals().get("UNIQUE_CHECK_ALLOW", set())
        )
        results.append({
            "name": unique_check["name"],
            "hits": unique_check["hits"],
            "threshold": unique_check["threshold"],
            "comparison": unique_check["comparison"],
            "ok": unique_check["ok"],
            "unique_hashes": unique_check["unique_hashes"],
            "duplicate_count": unique_check["duplicate_count"],
            "duplicates": unique_check["duplicates"],
        })
        all_ok = all_ok and unique_check["ok"]
    return {"file": str(path), "ok": all_ok, "checks": results}


def render_human(results):
    lines = []
    for r in results:
        status = "OK  " if r["ok"] else "FAIL"
        parts = []
        for c in r["checks"]:
            if c["name"] == "screenshot files exist":
                # v0.3.2: surface the 3 sub-categories so the user
                # sees WHY the check failed (file missing vs 1x1
                # placeholder PNG vs unreplaced [SCREENSHOT: x]).
                breakdown = []
                if c.get("missing_count", 0) > 0:
                    breakdown.append(f"{c['missing_count']} missing")
                if c.get("placeholder_png_count", 0) > 0:
                    breakdown.append(f"{c['placeholder_png_count']} 1×1 placeholder PNGs")
                if c.get("unreplaced_placeholder_count", 0) > 0:
                    breakdown.append(
                        f"{c['unreplaced_placeholder_count']} unreplaced [SCREENSHOT:]/[VIDEO:]"
                    )
                breakdown_str = ", ".join(breakdown) if breakdown else "0 issues"
                parts.append(
                    "{}={}/{} ({})".format(
                        c["name"], c["hits"], c["threshold"], breakdown_str
                    )
                )
            elif c["name"] == "screenshot unique (no duplicate content)":
                # v0.4.0: surface the duplicate groups so the user
                # sees WHICH PNGs are byte-identical (and to which
                # siblings). Up to 5 groups × ≤ 5 filenames each.
                dups = c.get("duplicates", [])
                if dups:
                    groups = "; ".join(
                        "{" + ", ".join(g["files"]) + "}"
                        for g in dups
                    )
                else:
                    groups = "0 issues"
                parts.append(
                    "{}={}/{} ({})".format(
                        c["name"], c["hits"], c["threshold"], groups
                    )
                )
            else:
                parts.append("{}={}".format(c["name"], c["hits"]))
        lines.append("[{}] {}: {}".format(status, r["file"], ", ".join(parts)))
        # Per-check failure details
        for c in r["checks"]:
            if not c["ok"]:
                if c["name"] == "screenshot files exist":
                    lines.append(
                        "        - {}: {}/{} ({} missing, {} placeholder PNGs, {} unreplaced; e.g. {})".format(
                            c["name"], c["hits"], c["threshold"],
                            c.get("missing_count", 0),
                            c.get("placeholder_png_count", 0),
                            c.get("unreplaced_placeholder_count", 0),
                            ", ".join(c.get("missing_paths", [])) or "(no examples)",
                        )
                    )
                elif c["name"] == "screenshot unique (no duplicate content)":
                    dups = c.get("duplicates", [])
                    rendered = "; ".join(
                        "{" + ", ".join(g["files"]) + "}"
                        for g in dups
                    ) or "(no groups)"
                    lines.append(
                        "        - {}: {}/{} ({} duplicate group(s); e.g. {})".format(
                            c["name"], c["hits"], c["threshold"],
                            c.get("duplicate_count", 0), rendered,
                        )
                    )
                else:
                    lines.append(
                        "        - {}: {} (need {} {})".format(
                            c["name"], c["hits"], c["comparison"], c["threshold"]
                        )
                    )
    return "\n".join(lines)


def main(argv):
    args = list(argv)
    strict = "--strict" in args
    as_json = "--json" in args
    unique = "--unique" in args
    # --unique-allow logo.png,branding.png -> whitelist
    unique_allow: set = set()
    for a in list(args):
        if a.startswith("--unique-allow="):
            unique_allow = {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
            args.remove(a)
        elif a == "--unique-allow":
            args.remove(a)
    args = [a for a in args if not a.startswith("--")]
    # Stash on module globals so validate_file can pick up.
    globals()["UNIQUE_CHECK_ENABLED"] = unique
    globals()["UNIQUE_CHECK_ALLOW"] = unique_allow
    if not args:
        print(__doc__.strip())
        return 0
    results = [validate_file(Path(a)) for a in args]
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(render_human(results))
    if strict and not all(r["ok"] for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
