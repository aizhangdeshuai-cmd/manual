#!/usr/bin/env python3
"""Validate generated user-manual markdown files against the 6 hard checks.

Usage:
    validate-output.py [--strict] [--json] <file.md> [...]

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


# Each check: (name, regex, threshold, comparison, exclude_code?)
# comparison is 'ge' (>=) or 'le' (<=).
CHECKS = [
    (
        "7-field hits",
        re.compile(
            r"适用角色|前置条件|操作前必看|^###\s*步骤|^###\s*成功后看到|^###\s*字段说明|^###\s*如果你卡住了|^###\s*相关任务",
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
    return {"file": str(path), "ok": all_ok, "checks": results}


def render_human(results):
    lines = []
    for r in results:
        status = "OK  " if r["ok"] else "FAIL"
        parts = ", ".join(
            "{}={}".format(c["name"], c["hits"]) for c in r["checks"]
        )
        lines.append("[{}] {}: {}".format(status, r["file"], parts))
        for c in r["checks"]:
            if not c["ok"]:
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
    args = [a for a in args if not a.startswith("--")]
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
