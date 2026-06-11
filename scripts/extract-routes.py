#!/usr/bin/env python3
"""Extract route definitions from a Vue Router index.ts (or .js / .mjs / .ts).

Usage:
  extract-routes.py <router-file>

Output: JSON array to stdout, each entry:
  {path, name, component, title, requires_auth, perms, module}

Handles:
  - path: '/x' (string)
  - name: 'X' (identifier or string)
  - component: () => import('@/views/...')
  - meta: { title, requiresAuth, perms, icon }
  - nested children: [...] (recurses with parent path prefix)

Output schema (JSON array; one entry per router path):
  [
    {
      "source": "src/router/index.ts",
      "path": "/risk/fraud-detection",
      "name": "FraudDetection",
      "module": "risk",
      "component": "risk/fraud-detection/index.vue",
      "title": "舞弊检测",
      "requiresAuth": true,
      "perms": ["risk.fraud.read"]
    }
  ]

Field reference:
- source: router file path (str)
- path: route path (str)
- name: route name (str)
- module: first non-trivial path segment (str)
- component: import target (str, possibly empty)
- title: meta.title for menu display (str, possibly empty)
- requiresAuth: meta.requiresAuth (bool)
- perms: meta.perms list (list of str)

Empty array [] is valid. Module inference: first non-empty path segment
after stripping /login, /403, /404. Override via meta.title if needed.

"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path


# Match a path: '/x' line, with subsequent context (next 12 lines of object body)
PATH_LINE_RE = re.compile(r"(?m)(?:^|[,{])\s*path:\s*['\"]([^'\"]+)['\"]")
NAME_LINE_RE = re.compile(r"(?m)(?:^|[,{])\s*name:\s*['\"]([^'\"]+)['\"]")
COMPONENT_RE = re.compile(
    r"component:\s*(?:\(\)\s*=>\s*)?import\(['\"]([^'\"]+)['\"]\)",
    re.MULTILINE,
)
COMPONENT_NAME_RE = re.compile(
    r"component:\s*([A-Z][A-Za-z0-9_]*)",
    re.MULTILINE,
)
REQUIRES_AUTH_RE = re.compile(
    r"requiresAuth:\s*(true|false)", re.IGNORECASE
)
PERMS_RE = re.compile(
    r"perms:\s*\[([^\]]*)\]", re.MULTILINE
)
TITLE_RE = re.compile(
    r"title:\s*['\"]([^'\"]+)['\"]", re.MULTILINE
)
CHILDREN_RE = re.compile(
    r"children:\s*\[", re.MULTILINE
)
# Find block boundaries for each path entry
# We walk line-by-line, tracking brace depth
OBJECT_OPEN_RE = re.compile(r"\{\s*$")


def _slice_block(text: str, start_line: int) -> tuple[str, int]:
    """Return the substring of the route-object block starting at start_line,
    and the line index after the closing brace."""
    lines = text.splitlines()
    # Scan from start_line (inclusive); "{ " or "{" anywhere on the line
    i = start_line
    found = -1
    while i < len(lines):
        if "{" in lines[i]:
            found = i
            break
        i += 1
    if found < 0:
        return "", i
    # Compute char offset of the first "{" on the found line
    offset_in_line = lines[found].index("{")
    start = sum(len(l) + 1 for l in lines[:found]) + offset_in_line
    depth = 0
    line_pos = found
    char_pos = offset_in_line
    while line_pos < len(lines):
        line = lines[line_pos]
        while char_pos < len(line):
            ch = line[char_pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = sum(len(l) + 1 for l in lines[:line_pos]) + char_pos + 1
                    return text[start:end], line_pos + 1
            char_pos += 1
        line_pos += 1
        char_pos = 0
    return text[start:], len(lines)


def _stringify_perms(perms_text: str) -> list[str]:
    return [s.strip().strip("'\"") for s in perms_text.split(",") if s.strip()]


def _infer_module(path: str) -> str:
    """Map URL path to module name: /sys/* -> sys, /lg/* -> lg, etc."""
    parts = [p for p in path.split("/") if p and not p.startswith(":")]
    if not parts:
        return "root"
    # Skip layout-ish roots
    if parts[0] in ("login", "403", "404", "500", "index"):
        return parts[0]
    return parts[0]


def extract_from_router(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    routes: list[dict] = []

    # Find every path: 'X' (top-level only — children handled recursively)
    for pm in PATH_LINE_RE.finditer(text):
        # line index of this match
        prefix = text[:pm.start()]
        line_idx = prefix.count("\n")
        # Slice the enclosing object block
        block, _ = _slice_block(text, line_idx)
        if not block:
            continue

        path_val = pm.group(1)
        name_m = NAME_LINE_RE.search(block)
        comp_m = COMPONENT_RE.search(block) or COMPONENT_NAME_RE.search(block)
        auth_m = REQUIRES_AUTH_RE.search(block)
        perms_m = PERMS_RE.search(block)
        title_m = TITLE_RE.search(block)

        rec = {
            "path": path_val,
            "name": name_m.group(1) if name_m else None,
            "component": comp_m.group(1) if comp_m else None,
            "title": title_m.group(1) if title_m else None,
            "requires_auth": auth_m.group(1).lower() == "true" if auth_m else None,
            "perms": _stringify_perms(perms_m.group(1)) if perms_m else [],
            "module": _infer_module(path_val),
            "source": str(path),
        }
        routes.append(rec)

        # Recurse into children
        if CHILDREN_RE.search(block):
            children_start = pm.end() + 50
            children_block = text[children_start:]
            # We can't easily bound "children: [...]" without proper parsing.
            # Fallback: re-run the same loop on the children block.
            for cm in PATH_LINE_RE.finditer(children_block):
                child_prefix = children_block[:cm.start()]
                child_line_idx = child_prefix.count("\n")
                child_block, _ = _slice_block(children_block, child_line_idx)
                if not child_block:
                    continue
                child_path = cm.group(1)
                # Make absolute if relative
                if not child_path.startswith("/"):
                    child_path = path_val.rstrip("/") + "/" + child_path
                cn_m = NAME_LINE_RE.search(child_block)
                cc_m = COMPONENT_RE.search(child_block) or COMPONENT_NAME_RE.search(child_block)
                ca_m = REQUIRES_AUTH_RE.search(child_block)
                cp_m = PERMS_RE.search(child_block)
                ct_m = TITLE_RE.search(child_block)
                routes.append({
                    "path": child_path,
                    "name": cn_m.group(1) if cn_m else None,
                    "component": cc_m.group(1) if cc_m else None,
                    "title": ct_m.group(1) if ct_m else None,
                    "requires_auth": ca_m.group(1).lower() == "true" if ca_m else rec["requires_auth"],
                    "perms": _stringify_perms(cp_m.group(1)) if cp_m else [],
                    "module": _infer_module(child_path),
                    "source": str(path),
                })

    return routes


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: extract-routes.py <router-file>", file=sys.stderr)
        return 0
    out: list[dict] = []
    for a in argv:
        p = Path(a)
        if p.is_dir():
            files = list(p.rglob("router*.ts")) + list(p.rglob("router*.js")) + list(p.rglob("index.ts"))
        else:
            files = [p]
        for f in files:
            out.extend(extract_from_router(f))
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
