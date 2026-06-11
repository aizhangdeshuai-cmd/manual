#!/usr/bin/env python3
"""Validate generated user-manual markdown files against the 6 hard checks.

Usage:
    validate-output.py [--strict] [--json] <file.md> [...]

The 6 checks come from the user-manual skill style guide (see SKILL.md
section 5.4 and the task-card prompt). For each input .md, prints a one-line
summary in human form, or a JSON object with --json. Exits 0 unless --strict
is set and any file failed at least one check.
"""
import json
import re
import sys
from pathlib import Path

# (name, regex, min_hits, comparison). comparison is 'ge' (>=) or 'le' (<=).
CHECKS = [
    (
        "7-field hits",
        re.compile(
            r"适用角色|前置条件|操作前必看|^###\s*步骤|^###\s*成功后看到|^###\s*字段说明|^###\s*如果你卡住了|^###\s*相关任务",
            re.MULTILINE,
        ),
        6,
        "ge",
    ),
    (
        "操作前必看 blocks",
        re.compile(r"操作前必看"),
        3,
        "ge",
    ),
    (
        "visual anchors",
        re.compile(r"(⚠️|💡|❌|📌)"),
        3,
        "ge",
    ),
    (
        "appendix-A 6-col table",
        re.compile(r"^\| .* \| .* \| .* \| .* \| .* \| .* \|", re.MULTILINE),
        1,
        "ge",
    ),
    (
        "role-permission matrix",
        re.compile(r"##\s*角色与权限速查"),
        1,
        "ge",
    ),
    (
        "screenshot count",
        re.compile(r"!\[[^\]]*\]\([^)]+\.(?:png|jpg|jpeg|webp)(?:\?[^)]*)?\)", re.IGNORECASE),
        2,
        "ge",
    ),
]


def validate_file(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    results = []
    all_ok = True
    for name, pattern, threshold, cmp in CHECKS:
        hits = len(pattern.findall(text))
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
