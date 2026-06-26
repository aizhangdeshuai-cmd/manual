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


# v0.5.4: extract just the alt text from an `![alt](path)` markdown
# image link. Used by the placeholder_alt check to look for LLM-lazy
# alt patterns (占位:/TODO:/img*/screenshot/etc).
ALT_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+\.(?:png|jpg|jpeg|webp)(?:\?[^)]*)?)\)",
    re.IGNORECASE,
)

# v0.5.4: alt-text forbidden patterns. Each tuple is
# (regex, human-readable reason). Match = LLM wrote a lazy alt that
# the LLM agent produced without actually viewing the page.
# v0.5.4 §2.2 hard rule: LLM must NOT emit “占位:...” style
# alts; instead either write a real description OR remove the link.
_ALT_FORBIDDEN_PATTERNS = [
    (re.compile("^\\s*占位[:：]"), "alt starts with placeholder (LLM lazy stub)"),
    (re.compile("^\\s*<TODO[:：]", re.IGNORECASE), "alt is a <TODO: ...> stub"),
    (re.compile("^\\s*(screenshot|img\\d*|系统截图|截图|页面截图)\\s*$", re.IGNORECASE), "alt is a generic placeholder word"),
    (re.compile("详情页面|详情|这个页面|包含", re.IGNORECASE), "alt is a description-style sentence (> 15 chars prose)"),
]


# v1.0.1: detect the LLM-leaves-toc-empty failure pattern. The
# skill says §3 row 4 requires a `## 目录` section with ≥ 5
# anchor links. v0.5.2 documented the rule but the LLM kept
# emitting `<!-- toc -->` placeholders or just empty headings.
# This check finds the `## 目录` section and counts the
# markdown anchor links under it. If < 5, fail the manual.
_TOC_HEADING_RE = re.compile(r"^##\s*目录\s*$", re.MULTILINE)
_TOC_ANCHOR_RE = re.compile(r"^\s*-\s+\[[^\]]+\]\([^)]+\)", re.MULTILINE)


# v1.0.1: enforce the strict task-card heading format from
# SKILL.md §4. The LLM keeps dropping the `任务卡 N:` prefix,
# e.g. writing `### 创建合同` instead of
# `### 任务卡 1: 创建合同`. This check finds
# every H3 in the document, splits them into "task card" and "other"
# buckets, and requires:
#   1. The first task-card heading must be `### 任务卡 1: ...`
#   2. Task-card numbers must be sequential (1, 2, 3, ...)
#   3. There must be ≥ 1 task card (otherwise it's not a manual)
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """Return frontmatter keys/values as a dict (values trimmed + unquoted).

    Returns {} when the file has no frontmatter. Used by the
    description_required check (INTEGRATION.md §3.5: viewer v2 parses
    frontmatter `description` for the search-result excerpt — a manual
    without it gives empty search snippets, which the skill must not
    ship).
    """
    m = _FRONTMATTER_RE.search(text)
    if not m:
        return {}
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


# v2.1.0: terms the LLM sometimes leaves as literal placeholder prose
# when it copy-pastes the skill's own template text into the deliverable.
# These never resolve to real content for a business user — `对应地址/`
# opens nothing, `起静态站服务 8088` is a command's display-name stub
# (not a runnable command). audience_leak §2.7.1 类 1/8 territory:
# these are "how the manual was generated" residue, not operation steps.
#
# IMPORTANT: these three CJK tokens are scanned on RAW text (incl.
# inside backticks). The ehr manual shipped them backtick-wrapped
# (`对应地址/`, `手册所在目录/`, `起静态站服务`) which LOOKS like
# code/paths but resolves to nothing — backticks mask empty prose,
# the same trick §2.2 bans for alt text. A scan that strips code
# first would miss every one of them. None of these tokens is ever a
# valid literal value, so no real command collides.
#
# Each tuple: (regex, human reason). Match = unfilled template term.
_UNFILLED_TERM_PATTERNS = [
    # `对应地址` used as a literal URL/path component the user must open.
    # Allow trailing `/` (e.g. `对应地址/`) and Chinese full-width slash.
    (re.compile(r"对应地址(?![\w-])"), "未替换模板话术 「对应地址」(应为真实访问地址)"),
    # `手册所在目录` used as a literal path the user must type/cd into.
    (re.compile(r"手册所在目录"), "未替换模板话术 「手册所在目录」(应为真实目录路径)"),
    # `起静态站服务` is the skill's own subcommand display-name; if it
    # appears bare the agent pasted template text verbatim — the real
    # command is `python3 -m http.server`. Scanned raw (incl. backticks).
    (re.compile(r"起静态站服务"), "未替换模板话术 「起静态站服务」(子命令名当成命令,应为真实启动命令)"),
    # Unfilled `<your-...>` placeholders that survived validate-config.
    (re.compile(r"<your-[a-z-]+>"), "未替换占位符 <your-...>(validate-config 应已拦截)"),
]


def _check_unfilled_template_terms(text: str) -> dict:
    """v2.1.0: catch template prose the LLM forgot to fill in.

    Two classes, run on RAW text (not code-stripped):
      - The three skill-internal stub tokens (`对应地址`, `手册所在目录`,
        `起静态站服务` as a pseudo-command) are NEVER valid literal
        values, even inside backticks. The ehr manual shipped them
        backtick-wrapped (`` `对应地址/` ``) which looks "codey" but
        resolves to nothing for a business user — backticks here mask
        empty prose, exactly the §2.2 placeholder_alt failure mode. We
        scan raw text so the backtick disguise does not hide them.
       - `<your-...>` placeholders (validate-config residue) are also
        scanned raw.

    Real backtick commands that happen to be long/indented are fine —
    none of them are these three literal CJK tokens.

    Returns a check-shaped dict (threshold 0, ok iff no matches).
    """
    offenders: list[dict] = []
    for pat, reason in _UNFILLED_TERM_PATTERNS:
        for m in pat.finditer(text):
            line = text[: m.start()].count("\n") + 1
            offenders.append({"match": m.group(0), "reason": reason, "line": line})
    return {
        "name": "unfilled_template_terms (含未替换模板话术)",
        "hits": len(offenders),
        "threshold": 0,
        "comparison": "eq",
        "ok": (len(offenders) == 0),
        "flagged": len(offenders),
        "offenders": offenders[:5],
    }


def _check_frontmatter_description(text: str) -> dict:
    """v2.1.0: INTEGRATION.md §3.5 says viewer v2 parses the frontmatter
    `description` into the search-result excerpt. SKILL §3 row 1 now
    lists it as required, but the LLM kept omitting it (the ehr manual
    shipped three manuals with empty `description`, rendering viewer
    search useless). This check FAILs any manual whose frontmatter is
    missing `description` or has it empty/placeholder.

    Tolerant parse (same shape as html._parse_frontmatter): non-empty
    after stripping quotes counts as filled; `占位`/`<TODO:>`/`xxx`
    stubs count as empty.
    """
    meta = _parse_frontmatter(text)
    raw = meta.get("description", "").strip()
    if raw and not re.fullmatch(r"(?:<TODO[:：][^>]*>|占位[:：]?|xxx|<[^>]+>)", raw, re.IGNORECASE):
        return {
            "name": "frontmatter_description (INTEGRATION §3.5 搜索摘要)",
            "hits": 1,
            "threshold": 1,
            "comparison": "ge",
            "ok": True,
            "has_field": True,
            "reason": "",
        }
    return {
        "name": "frontmatter_description (INTEGRATION §3.5 搜索摘要)",
        "hits": 0,
        "threshold": 1,
        "comparison": "ge",
        "ok": False,
        "has_field": bool(meta.get("description", "").strip()),
        "reason": "frontmatter 缺 description 或为占位(viewer 搜索摘要会空)",
    }


# v2.2.0: a `#### 步骤` (or `### 步骤`) section must contain ONLY step
# descriptions + `![alt](.png)` screenshots. Videos belong in a separate
# `#### 演示视频` section placed BEFORE the steps (SKILL §4 / §2.6).
# Permitting `[VIDEO:](.mp4)` inside the steps block led the LLM to
# interleave videos into individual step lines, which made the viewer
# render a video inline mid-prose and broke the "watch the demo, then
# follow the steps" reading order. This check scans every steps block
# delimited by a `步骤` heading up to the next heading (H2/H3/H4) or
# EOF, and flags any `.mp4)` reference found within.
_STEP_HEADING_RE = re.compile(r"^#{2,4}\s*步骤\s*$", re.MULTILINE)
_HEADING_LINE_RE = re.compile(r"^#{2,4}\s+", re.MULTILINE)
_MP4_LINK_RE = re.compile(r"\]\([^)]*\.mp4\)", re.IGNORECASE)


def _check_video_outside_steps(text: str) -> dict:
    """v2.2.0: every `#### 步骤` / `### 步骤` block must NOT contain a
    `.mp4)` video reference (markdown link form `[VIDEO: x](path.mp4)`
    or any `](...mp4)`). Videos belong in `#### 演示视频`, before steps.
    """
    offenders: list[dict] = []
    for m in _STEP_HEADING_RE.finditer(text):
        start = m.end()
        nxt = _HEADING_LINE_RE.search(text, start)
        block = text[start: nxt.start()] if nxt else text[start:]
        for vm in _MP4_LINK_RE.finditer(block):
            line = text[: m.start() + vm.start()].count("\n") + 1
            offenders.append({"line": line, "match": vm.group(0)[:80]})
    return {
        "name": "video_outside_steps (§2.6 视频仅在演示视频段)",
        "hits": len(offenders),
        "threshold": 0,
        "comparison": "eq",
        "ok": (len(offenders) == 0),
        "flagged": len(offenders),
        "offenders": offenders[:5],
    }


_TASK_CARD_HEADING_RE = re.compile(r"^###\s+任务卡\s+(\d+):\s*(.+?)\s*$", re.MULTILINE)
_ANY_H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)


def _check_task_card_headings(text: str) -> dict:
    """v1.0.1: §4 strict task-card heading format.

    Returns a check-shaped dict with:
      - hits: count of well-formed `任务卡 N: title` headings
      - threshold: 1
      - ok: ≥ 1 well-formed heading AND numbers are sequential
      - missing_prefix_count: how many H3s lack `任务卡 N:` prefix
      - non_sequential: list of (got, expected) tuples if gaps detected
      - offenders: list of raw H3 lines that lack the prefix
    """
    well = [(int(m.group(1)), m.group(2)) for m in _TASK_CARD_HEADING_RE.finditer(text)]
    all_h3 = [m.group(1).strip() for m in _ANY_H3_RE.finditer(text)]
    well_titles = {title for _, title in well}
    offenders = [h for h in all_h3 if h not in well_titles and not h.startswith("任务卡 ")]

    # Check sequential numbering
    non_sequential = []
    expected = 1
    for n, _ in well:
        if n != expected:
            non_sequential.append((n, expected))
        expected = n + 1

    ok = (len(well) >= 1 and not non_sequential)
    return {
        "name": "task_card_headings (§4 strict format)",
        "hits": len(well),
        "threshold": 1,
        "comparison": "ge",
        "ok": ok,
        "well_formed_count": len(well),
        "missing_prefix_count": len(offenders),
        "non_sequential": non_sequential[:5],
        "offenders": offenders[:5],
    }


def _check_directory_anchors(text: str) -> dict:
    """v1.0.1: §3 row 4 hard gate. 强制 `## 目录` segment
    contains ≥ 5 markdown anchor links of the form `- [<title>](#<anchor>)`.
    Returns a check-shaped dict with:
      - hits: count of anchor links under the 目录 heading
      - threshold: 5
      - ok: hits >= 5
      - has_toc_heading: bool
      - sample_links: first 3 anchor links
    """
    m = _TOC_HEADING_RE.search(text)
    if not m:
        return {
            "name": "directory_anchors (§3 row 4 hard gate)",
            "hits": 0,
            "threshold": 5,
            "comparison": "ge",
            "ok": False,
            "has_toc_heading": False,
            "sample_links": [],
            "reason": "no '## 目录' heading found",
        }
    # Find end of toc section: next H2 or end of file
    after = text[m.end():]
    next_h2 = re.search(r"^##\s+", after, re.MULTILINE)
    toc_body = after if not next_h2 else after[:next_h2.start()]
    links = _TOC_ANCHOR_RE.findall(toc_body)
    return {
        "name": "directory_anchors (§3 row 4 hard gate)",
        "hits": len(links),
        "threshold": 5,
        "comparison": "ge",
        "ok": (len(links) >= 5),
        "has_toc_heading": True,
        "sample_links": links[:3],
        "reason": "" if len(links) >= 5 else f"only {len(links)} anchor links under §目录 (need ≥ 5)",
    }


def _check_placeholder_alt(text: str) -> dict:
    """v0.5.4: detect lazy alt text patterns. LLM agents that don't
    run the recorder (or run it on a blocked dev server) tend to
    emit “占位:指标列表” style alts. These
    are LLM-generated stubs, not real captions — readers get
    zero information from them. SKILL.md §2.2 explicitly bans them.

    Returns a check-shaped dict with:
      - hits: number of image links scanned
      - flagged: count of links matching any forbidden pattern
      - offenders: list of {alt, path, reason} for the first 5
    """
    offenders: list[dict] = []
    hits = 0
    for m in ALT_RE.finditer(text):
        alt = m.group("alt").strip()
        path = m.group("path").strip()
        hits += 1
        for pat, reason in _ALT_FORBIDDEN_PATTERNS:
            if pat.search(alt):
                offenders.append({"alt": alt, "path": path, "reason": reason})
                break
    return {
        "name": "placeholder_alt (lazy alt-text)",
        "hits": hits,
        "threshold": hits,
        "comparison": "eq",
        "ok": (len(offenders) == 0),
        "flagged": len(offenders),
        "offenders": offenders[:5],
    }


def _check_audience_leak(text: str) -> dict:
    """v1.1.0: §2.7.1 audience-leak check. Business users should never
    see content that reveals how the manual was generated (data source
    comments, internal API tables, source file paths, repo directory
    trees, or "video pending" placeholders). Each match is a
    degradation of the end-user document and gets rejected.

    Five patterns enforced (see SKILL.md §2.7.1 for examples):
      1. `> 数据源:` 引用块 — meta-comment about provenance
      2. 后端 API 路径表 — 4+ column tables where path column starts
         with `/api/`, `/report/`, `/hr/`, etc.
      3. 源码文件路径 — anything matching `report-admin-ui/src/...`,
         `ehr-report/...`, `<stack>-<stack>/.../...Controller.java`,
         or generic `<dir>/src/{views,components,types,utils}/...`
      4. 仓库目录树 — bullet items with `ehr-report/`, `report-admin-ui/`,
         `docs/user-manual/` as standalone paths
      5. 录屏占位 — `<!-- video-pending:`, `⏳ **视频录屏待补**`,
         `recorder-scripts/`, or `[VIDEO NEEDED]` / `[SCREENSHOT NEEDED]`

    Code-fence skip: matches inside ``` fenced blocks are not flagged
    (so LLM can still show positive/negative examples that quote the
    forbidden text inside code blocks for instructional purposes).
    """
    import re
    offenders: list[dict] = []

    def is_in_code(s: str, pos: int) -> bool:
        """Check whether byte position `pos` in s falls inside a
        fenced code block (``` ... ```)."""
        line_no = s.count("\n", 0, pos) + 1
        lines = s.split("\n")
        in_code = False
        for i, line in enumerate(lines, 1):
            if i == line_no:
                return in_code
            if line.lstrip().startswith("```"):
                in_code = not in_code
        return in_code

    # Pattern 1: `> 数据源:` blockquote
    pat1 = re.compile(r"^>\s*数据源[:：].*$", re.MULTILINE)
    # P0-1 (review fix): HTML-comment provenance annotations like
    # `<!-- source: extract-X.py, file: Y -->` are the same kind of
    # 创作痕迹 as `> 数据源:` blockquotes (§2.7.1 类 1) and also leak
    # source file paths (类 3). §5.3 no longer instructs the LLM to
    # add them inline, but guard so any survivors are flagged.
    pat_source = re.compile(r"<!--\s*source\s*:\s*extract-", re.IGNORECASE)
    # Pattern 2: API endpoints (NOT routes, NOT images, NOT links).
    # Business users should never see backend endpoint paths
    # ANYWHERE in the manual — not in tables, not in bulleted lists,
    # not in Q&A blocks. Allowed:
    #   - User-facing routes: `/report/list`,
    #     `/report/:companyId/designer/:code` (typed in browser bar)
    #   - Image links: `../screenshots/sys/01.png` (no API verbs)
    # Blocked:
    #   - API endpoint segments: /report/config, /report/field,
    #     /report/query, /report/export, /report/rollback, etc.
    # Logic: match `/report/<verb>/...` or `/api/...` or `/hr/...`,
    # but only when the path is inside backticks (rendered as code)
    # AND does NOT end with an image extension.
    pat2 = re.compile(
        r"`[^`]*?(?:"
        r"/report/(?:config|field|query|export|rollback|versions|enable|disable|upstream|gray)(?:/[^`]*?)?"
        r"|/api/[\w/-]+"
        r"|/hr/[\w/-]+"
        r")[^`]*?`",
    )
    # Pattern 3: source file paths
    pat3 = re.compile(
        r"report-admin-ui/(src|dist)/[\w./-]+\.(vue|ts|tsx|js|jsx|scss|css)"
        r"|ehr-report/[\w./-]+\.java"
        r"|\b[a-z][\w-]+-ui/src/(views|components|types|utils)/[\w./-]+\.(vue|ts)"
    )
    # Pattern 4: repo directory references. Matches any list item
    # or sentence that points the reader at code repositories or
    # project roots. Two flavors:
    #   (a) "- <text>: `ehr-report/`" / `report-admin-ui/` /
    #       `docs/user-manual/` (subdirectory bullets)
    #   (b) "(项目根 `ehr/`)" / "项目目录: `my-app/`" /
    #       "repo root `xxx/`" (project root references)
    #   (c) Inline backtick paths like `<word>/` preceded by repo
    #       markers "项目根", "项目目录", "repo root", "代码仓库",
    #       "代码根目录", "项目仓库" in any context (sentence, list
    #       item, Q&A).
    pat4 = re.compile(
        r"(?:"
        # (a) Subdirectory bullets: any list item mentioning a known
        # subdirectory path.
        r"^\s*(?:[-*]|\d+\.)\s+.*?(?:ehr-report|report-admin-ui|docs/user-manual)/\S*"
        # (b) Project root: "项目根" / "项目目录" / "repo root" /
        # "代码根目录" / "代码仓库" / "项目仓库" followed (within 30
        # chars) by a backtick-quoted path ending in `/`.
        r"|(?:项目\s*根|项目\s*目录|repo\s+root|代码\s*根目录|代码\s*仓库|项目\s*仓库)[^`]{0,40}`[\w.-]+/`"
        # (c) Standalone "项目根: `xxx/`" or similar.
        r"|(?:项目\s*根|项目\s*目录|repo\s+root)\s*[:：]\s*`[\w.-]+/`"
        r")",
        re.MULTILINE | re.IGNORECASE,
    )
    # Pattern 5: recording scaffolding
    pat5 = re.compile(
        r"<!--\s*video-pending"
        r"|⏳\s*\*\*视频录屏待补"
        r"|recorder-scripts/"
        r"|\[VIDEO NEEDED\]"
        r"|\[SCREENSHOT NEEDED\]"
    )

    # Pattern 6 (v1.1.2 §2.7.1 类 7): backend URLs / port numbers.
    # User-facing frontend URLs (e.g. http://localhost:8088/) are
    # allowed (users need them to open the app). Backend URLs on
    # non-frontend ports (anything not 80/443/8080/8088) are blocked.
    # We approximate by matching URLs with non-frontend ports.
    pat6 = re.compile(
        r"\bhttps?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\w[\w.-]*\.\w+)"
        r":(?!80\b|443\b|8080\b|8088\b)\d{2,5}\b"
    )

    # Pattern 7 (v1.1.2 §2.7.1 类 7): tech-stack versions and
    # architecture hints users don't need. Backtick-wrapped or
    # bare mentions of common backend tech versions, plus
    # "用同一套后端 API" / "前后端通信" / "SPA 单页应用" / "RESTful".
    pat7 = re.compile(
        r"(?:"
        r"\b(?:Spring\s+Boot|SpringMVC|Node\.js|Express|Django|Flask|"
        r"Vue\s*2|Vue\s*3|React|Angular|Element\s*UI|Element\s*Plus|"
        r"PostgreSQL|MySQL|H2\s*in-memory|H2\s*数据库|"
        r"Redis|Kafka|RabbitMQ|Docker|Kubernetes|"
        r"maven|mvn|npm\s+run|npm\s+install|yarn|pnpm|spring-boot:run|gradle)"
        r"\b[\s,，]*(?:\d+(?:\.\d+){0,2})?"
        r"|"
        r"(?:同一套|同一组|共\s*用)\s*后端\s*(?:API|接口|RESTful)"
        r"|"
        r"前后端\s*(?:用|通过|基于)\s*(?:RESTful|REST|HTTP|JSON|API)"
        r"|"
        r"(?:前端是|SPA\s*单页|单页应用)"
        r")"
    )

    patterns = [
        (pat1, "数据源 元注释 (SKILL §2.7.1 类 1)"),
        (pat_source, "HTML 源信息注释 <!-- (SKILL §2.7.1 类 1/3)"),
        (pat2, "后端 API 路径表 (SKILL §2.7.1 类 2)"),
        (pat3, "源码文件路径 (SKILL §2.7.1 类 3)"),
        (pat4, "仓库/目录结构列表 (SKILL §2.7.1 类 4)"),
        (pat5, "录屏占位段 (SKILL §2.7.1 类 5)"),
        (pat6, "后端 URL/端口 (SKILL §2.7.1 类 7)"),
        (pat7, "技术栈版本/架构提示 (SKILL §2.7.1 类 7)"),
    ]

    for pat, reason in patterns:
        for m in pat.finditer(text):
            if is_in_code(text, m.start()):
                continue
            line = text[: m.start()].count("\n") + 1
            offenders.append({
                "match": m.group(0)[:120],
                "reason": reason,
                "line": line,
            })

    return {
        "name": "audience_leak (v1.1.0 §2.7.1 业务用户文档禁列项)",
        "hits": len(offenders),
        "threshold": 0,
        "comparison": "eq",
        "ok": (len(offenders) == 0),
        "flagged": len(offenders),
        "offenders": offenders[:5],
    }


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
    # v0.5.4: placeholder_alt check (lazy alt-text pattern). File-existence
    # check covers the file side; this covers the markdown side. Together
    # they catch both “file not on disk” and “file on disk but alt is LLM garbage”.
    alt_check = _check_placeholder_alt(text)
    results.append({
        "name": alt_check["name"],
        "hits": alt_check["hits"],
        "threshold": alt_check["threshold"],
        "comparison": alt_check["comparison"],
        "ok": alt_check["ok"],
        "flagged": alt_check["flagged"],
        "offenders": alt_check["offenders"],
    })
    all_ok = all_ok and alt_check["ok"]
    # v1.0.1: §3 row 4 hard gate. LLM kept leaving `<!-- toc -->`
    # or empty 目录 heading. This is now a top-level check that
    # runs alongside file-existence and placeholder_alt.
    toc_check = _check_directory_anchors(text)
    results.append({
        "name": toc_check["name"],
        "hits": toc_check["hits"],
        "threshold": toc_check["threshold"],
        "comparison": toc_check["comparison"],
        "ok": toc_check["ok"],
        "has_toc_heading": toc_check["has_toc_heading"],
        "sample_links": toc_check["sample_links"],
        "reason": toc_check.get("reason", ""),
    })
    all_ok = all_ok and toc_check["ok"]
    # v1.0.1: §4 task-card heading strict format. Catches the
    # pattern where the LLM writes `### 创建合同` instead
    # of `### 任务卡 1: 创建合同`. Now
    # enforced by validate-output — no more silent degradation.
    tc_check = _check_task_card_headings(text)
    results.append({
        "name": tc_check["name"],
        "hits": tc_check["hits"],
        "threshold": tc_check["threshold"],
        "comparison": tc_check["comparison"],
        "ok": tc_check["ok"],
        "well_formed_count": tc_check["well_formed_count"],
        "missing_prefix_count": tc_check["missing_prefix_count"],
        "non_sequential": tc_check["non_sequential"],
        "offenders": tc_check["offenders"],
    })
    all_ok = all_ok and tc_check["ok"]
    # v1.1.0: §2.7.1 audience-leak check. Reject any manual that
    # contains "how it was generated" markers, internal API tables,
    # source paths, repo trees, or recording-scaffolding placeholders.
    leak_check = _check_audience_leak(text)
    results.append({
        "name": leak_check["name"],
        "hits": leak_check["hits"],
        "threshold": leak_check["threshold"],
        "comparison": leak_check["comparison"],
        "ok": leak_check["ok"],
        "flagged": leak_check["flagged"],
        "offenders": leak_check["offenders"],
    })
    all_ok = all_ok and leak_check["ok"]
    # v2.1.0: INTEGRATION §3.5 — frontmatter `description` feeds the
    # viewer search excerpt. Empty == useless search; FAIL. Runs on
    # the raw text (frontmatter is at file top, not in any code fence).
    desc_check = _check_frontmatter_description(text)
    results.append({
        "name": desc_check["name"],
        "hits": desc_check["hits"],
        "threshold": desc_check["threshold"],
        "comparison": desc_check["comparison"],
        "ok": desc_check["ok"],
        "has_field": desc_check["has_field"],
        "reason": desc_check.get("reason", ""),
    })
    all_ok = all_ok and desc_check["ok"]
    # v2.1.0: unfilled template terms (`对应地址`, `手册所在目录`,
    # `起静态站服务` as a pseudo-command — scanned RAW incl. backticks,
    # because the ehr manual shipped them backtick-wrapped which masks
    # empty prose; see _check_unfilled_template_terms for rationale).
    term_check = _check_unfilled_template_terms(text)
    results.append({
        "name": term_check["name"],
        "hits": term_check["hits"],
        "threshold": term_check["threshold"],
        "comparison": term_check["comparison"],
        "ok": term_check["ok"],
        "flagged": term_check["flagged"],
        "offenders": term_check["offenders"],
    })
    all_ok = all_ok and term_check["ok"]
    # v2.2.0: §2.6 — videos live in a `#### 演示视频` section before the
    # steps, never inside `#### 步骤`. Catches the LLM habit of pasting
    # `[VIDEO:](.mp4)` onto a step line.
    vsteps_check = _check_video_outside_steps(text)
    results.append({
        "name": vsteps_check["name"],
        "hits": vsteps_check["hits"],
        "threshold": vsteps_check["threshold"],
        "comparison": vsteps_check["comparison"],
        "ok": vsteps_check["ok"],
        "flagged": vsteps_check["flagged"],
        "offenders": vsteps_check["offenders"],
    })
    all_ok = all_ok and vsteps_check["ok"]
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
