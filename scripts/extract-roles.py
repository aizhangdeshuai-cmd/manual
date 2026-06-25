#!/usr/bin/env python3
"""Extract role/permission references from backend Java + frontend Vue code.

Usage:
  extract-roles.py <backend-root> [<frontend-root>]

Output: JSON array of {role_name, source, framework, example_path}.

Backend (Java) patterns:
  - @PreAuthorize("hasRole('X')") / hasAnyRole
  - @PreAuthorize("hasAuthority('X')") / hasAnyAuthority
  - @Secured({"X", "Y"})
  - @RolesAllowed({"X"})
  - @RequiresPermissions("X")

Frontend (Vue) patterns:
  - v-permission="['X', 'Y']" / v-permission="'X'"
  - v-role="'X'" / v-role="['X']"
  - <RoleGuard :roles="['X']">
  - v-has-permission="'X'"
  - v-hasPermi="['system:user:list']"   (RuoYi / vue-element-admin 派系)
  - v-hasRole="['admin']"               (RuoYi 派系)
  - router meta.roles / meta.permissions (vue-element-admin)
  - route-level roles: / permissions: (RuoYi — outside meta{})

Output schema (JSON array; one entry per RBAC hit):
  [
    {
      "source": "src/views/RiskReport.vue",
      "framework": "vue:v-permission",
      "expression": "['risk.report.read']",
      "roles_or_perms": ["risk.report.read"],
      "context_line": 12
    }
  ]

Field reference:
- source: .vue / .java file path (str)
- framework: java:PreAuthorize / java:Secured / java:RolesAllowed /
             java:RequiresPermissions / vue:v-permission / vue:v-role /
             vue:RoleGuard / vue:v-has-permission /
             vue:v-hasPermi / vue:v-hasRole /
             router:meta-roles / router:meta-permissions (str)
- expression: raw annotation / directive argument (str)
- roles_or_perms: extracted role/permission names (list of str)
- context_line: 1-based line number (int)

Empty array [] is valid (no RBAC annotations found). Orchestrator should
fall back to single-row matrix "system user" or use LLM inference.

"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path


# Java: top-level annotation capture. We capture the full argument string
# (everything between the outer parens' quotes) and then post-process to
# extract role names.
JAVA_ANNOTATIONS = [
    (re.compile(r'@PreAuthorize\s*\(\s*"([^"]*)"'), "java:PreAuthorize"),
    (re.compile(r'@PreAuthorize\s*\(\s*\'([^\']*)\''), "java:PreAuthorize"),
    (re.compile(r'@Secured\s*\(\s*"([^"]*)"'), "java:Secured"),
    (re.compile(r'@Secured\s*\(\s*\'([^\']*)\''), "java:Secured"),
    (re.compile(r'@RolesAllowed\s*\(\s*"([^"]*)"'), "java:RolesAllowed"),
    (re.compile(r'@RolesAllowed\s*\(\s*\'([^\']*)\''), "java:RolesAllowed"),
    (re.compile(r'@RequiresPermissions\s*\(\s*"([^"]*)"'), "java:RequiresPermissions"),
]

# Within a captured argument, extract quoted strings (role/authority names)
QUOTED_STRINGS_RE = re.compile(r"""['"]([^'"]+)['"]""")

# Match: hasRole('X') / hasAnyRole('X', 'Y') etc.
HAS_ROLE_RE = re.compile(r'has(?:Any)?(?:Role|Authority)\s*\(\s*([^)]+?)\s*\)')

# Match: {"X", "Y"}  (array literal in @Secured / @RolesAllowed)
ARRAY_LITERAL_RE = re.compile(r'\{\s*([^}]+)\s*\}')


def _extract_quoted(text: str) -> list[str]:
    return [m.group(1) for m in QUOTED_STRINGS_RE.finditer(text)]


def _extract_from_arg(arg: str) -> list[str]:
    """Given the inner string of a Java annotation, return role names."""
    # Try hasRole/hasAuthority first
    out: list[str] = []
    m = HAS_ROLE_RE.search(arg)
    if m:
        out.extend(_extract_quoted(m.group(1)))
    # Try array literal
    a = ARRAY_LITERAL_RE.search(arg)
    if a:
        out.extend(_extract_quoted(a.group(1)))
    # Fallback: if no hasRole/array but arg itself is a quoted string, take it
    if not out and arg.strip().startswith(("'", '"')) and arg.strip().endswith(("'", '"')):
        out.extend(_extract_quoted(arg))
    # Final fallback: treat the whole arg as a single role name (handles @Secured("AUDITOR"))
    if not out and re.match(r"^[A-Za-z0-9_:.-]+$", arg.strip()):
        out.append(arg.strip())
    return out


def extract_from_java(root: Path) -> list[dict]:
    roles: dict[str, dict] = {}
    if not root.exists():
        return []
    for f in root.rglob("*.java"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for pat, framework in JAVA_ANNOTATIONS:
            for m in pat.finditer(text):
                arg = m.group(1)
                for role_name in _extract_from_arg(arg):
                    if role_name not in roles:
                        roles[role_name] = {
                            "role_name": role_name,
                            "source": str(f),
                            "framework": framework,
                            "example_path": None,
                        }
    return list(roles.values())


# Vue patterns
VUE_PATTERNS = [
    (re.compile(r'v-permission\s*=\s*"\[([^\]]+)\]"'), "vue:v-permission"),
    (re.compile(r'v-permission\s*=\s*\'\[([^\]]+)\]\''), "vue:v-permission"),
    (re.compile(r'v-permission\s*=\s*"([^"]+)"'), "vue:v-permission"),
    (re.compile(r'v-permission\s*=\s*\'([^\']+)\''), "vue:v-permission"),
    (re.compile(r'v-role\s*=\s*"\[([^\]]+)\]"'), "vue:v-role"),
    (re.compile(r'v-role\s*=\s*\'\[([^\]]+)\]\''), "vue:v-role"),
    (re.compile(r'v-role\s*=\s*"([^"]+)"'), "vue:v-role"),
    (re.compile(r'v-role\s*=\s*\'([^\']+)\''), "vue:v-role"),
    (re.compile(r'<RoleGuard[^>]*:roles\s*=\s*"\[([^\]]+)\]"'), "vue:RoleGuard"),
    (re.compile(r'<RoleGuard[^>]*:roles\s*=\s*\'\[([^\]]+)\]\''), "vue:RoleGuard"),
    (re.compile(r'v-has-permission\s*=\s*"([^"]+)"'), "vue:v-has-permission"),
    (re.compile(r'v-has-permission\s*=\s*\'([^\']+)\''), "vue:v-has-permission"),
    # RuoYi 派系 (vue-element-admin 系): v-hasPermi / v-hasRole
    # These take an array like ['system:user:list'] or a single perm string.
    (re.compile(r'v-hasPermi\s*=\s*"\[([^\]]+)\]"'), "vue:v-hasPermi"),
    (re.compile(r'v-hasPermi\s*=\s*\'\[([^\]]+)\]\''), "vue:v-hasPermi"),
    (re.compile(r'v-hasPermi\s*=\s*"([^"]+)"'), "vue:v-hasPermi"),
    (re.compile(r'v-hasPermi\s*=\s*\'([^\']+)\''), "vue:v-hasPermi"),
    (re.compile(r'v-hasRole\s*=\s*"\[([^\]]+)\]"'), "vue:v-hasRole"),
    (re.compile(r'v-hasRole\s*=\s*\'\[([^\]]+)\]\''), "vue:v-hasRole"),
    (re.compile(r'v-hasRole\s*=\s*"([^"]+)"'), "vue:v-hasRole"),
    (re.compile(r'v-hasRole\s*=\s*\'([^\']+)\''), "vue:v-hasRole"),
]


def extract_from_vue(root: Path) -> list[dict]:
    roles: dict[str, dict] = {}
    if not root.exists():
        return []
    for f in root.rglob("*.vue"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for pat, framework in VUE_PATTERNS:
            for m in pat.finditer(text):
                raw = m.group(1)
                # Always extract quoted strings; handles both "X" and ["X","Y"] uniformly
                # If raw contains a comma or starts with [, it is a list literal; extract all quoted strings.
                # Otherwise it is a single quoted/unquoted value; strip surrounding quotes.
                if "," in raw or raw.startswith("["):
                    extracted = _extract_quoted(raw)
                else:
                    extracted = [raw.strip().strip(chr(39) + chr(34))]
                for role_name in extracted:
                    if role_name and role_name not in roles:
                        roles[role_name] = {"role_name": role_name, "source": str(f), "framework": framework, "example_path": None}
    return list(roles.values())


# Router RBAC patterns.
# Two conventions in the wild:
#   (a) Inside `meta: { roles: [...], permissions: [...] }`
#       (vue-element-admin >= 1.x, most custom code)
#   (b) Direct route-level: `{ path, roles: [...], permissions: [...] }`
#       (RuoYi, vue-element-admin legacy)
# We scan for both. To avoid double-counting, we anchor on a path: token
# earlier in the same object block (i.e. this is a route-level RBAC entry).
# Match a route object that contains roles or permissions arrays, where
# the roles/permissions are siblings of `path:` (RuoYi style: top-level
# route property, not inside meta{}). We use a non-greedy match and
# require both 'path:' and '(roles|permissions):' to appear before the
# closing ']' of the array.
# Match a route object whose sibling keys are roles or permissions (RuoYi
# style: top-level route property, not inside meta{}). Non-raw string
# because raw-string + bracket char class trips up py3.15 tokenizer.
# Simple array match: the [\'a\', \'b\'] right after roles: or permissions:.
# We back-link to nearest preceding path: in extract_from_router_files.
ROUTE_PROP_RE = re.compile(
    "(roles|permissions)\\s*:\\s*\\[([^\\]]+)\\]",
)
META_ROLES_RE = re.compile(
    r"meta\s*:\s*\{[^}]*?roles\s*:\s*\[([^\]]+)\]",
    re.DOTALL,
)
META_PERMS_RE = re.compile(
    r"meta\s*:\s*\{[^}]*?permissions\s*:\s*\[([^\]]+)\]",
    re.DOTALL,
)
# When a route has BOTH direct roles/permissions AND meta, both will fire
# (RuoYi puts permissions at route top, plus meta.title etc.). The dedupe
# in main() handles that.
def extract_from_router_files(frontend_root: Path) -> list[dict]:
    """Scan router/index.{ts,js} for meta.roles / meta.permissions arrays.

    RuoYi and vue-element-admin put RBAC on the route itself rather than
    on individual elements, e.g.:

        { path: '/system/user', component: Layout,
          meta: { title: '用户管理', icon: 'user',
                  roles: ['admin', 'common'],
                  permissions: ['system:user:list'] } }

    We treat each hit as one or more (role, framework, source) entries.
    """
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    if not frontend_root or not frontend_root.exists():
        return out
    # Find router files: src/router/index.{ts,js}, src/router/*.ts, router/index.*, etc.
    candidates: list[Path] = []
    for pat in ("router/index.ts", "router/index.js", "router/index.mjs"):
        candidates += list(frontend_root.rglob(pat))
    # Also try top-level router dir files
    for pat in ("router*.ts", "router*.js"):
        candidates += list(frontend_root.rglob(pat))
    # Dedup
    candidates = sorted(set(candidates))
    for f in candidates:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # (a) Inside meta: { ... } — vue-element-admin style
        for m in META_ROLES_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            for role in _extract_quoted(m.group(1)):
                key = (role, "router:meta-roles", str(f))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "role_name": role,
                    "source": str(f),
                    "framework": "router:meta-roles",
                    "example_path": None,
                    "context_line": line,
                })
        for m in META_PERMS_RE.finditer(text):
            line = text[: m.start()].count("\n") + 1
            for perm in _extract_quoted(m.group(1)):
                key = (perm, "router:meta-permissions", str(f))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "role_name": perm,
                    "source": str(f),
                    "framework": "router:meta-permissions",
                    "example_path": None,
                    "context_line": line,
                })
        # (b) Direct route-level: roles: [...], permissions: [...]
        # RuoYi / vue-element-admin legacy. Match each array; the key
        # (roles | permissions) is in group(1). Multiple matches in one
        # file are common (RuoYi dynamicRoutes has 5+), so we iterate.
        for m in ROUTE_PROP_RE.finditer(text):
            key = m.group(1)
            arr_text = m.group(2)
            framework = f"router:route-{key}"
            line = text[: m.start()].count("\n") + 1
            for name in _extract_quoted(arr_text):
                k = (name, framework, str(f))
                if k in seen:
                    continue
                seen.add(k)
                out.append({
                    "role_name": name,
                    "source": str(f),
                    "framework": framework,
                    "example_path": None,
                    "context_line": line,
                })
    return out


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: extract-roles.py <backend-root> [<frontend-root>]", file=sys.stderr)
        return 0
    backend = Path(argv[0]) if argv else None
    frontend = Path(argv[1]) if len(argv) > 1 else None

    out: list[dict] = []
    if backend:
        out.extend(extract_from_java(backend))
    if frontend:
        out.extend(extract_from_vue(frontend))
        # RuoYi / vue-element-admin put RBAC on router meta, not on .vue files.
        # Pass the project root (parent of src/) so the path rglob can find
        # src/router/index.js. If argv[1] already IS the project root, this
        # is a no-op. If argv[1] is "src" or "frontend/src", we also try
        # the parent.
        out.extend(extract_from_router_files(frontend))
        if frontend.parent.exists() and frontend.parent != frontend:
            out.extend(extract_from_router_files(frontend.parent))
    # Dedupe by (role_name, framework, source)
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []
    for r in out:
        key = (r.get("role_name", ""), r.get("framework", ""), r.get("source", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    for r in deduped:
        r["example_path"] = r["source"]
    json.dump(deduped, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
