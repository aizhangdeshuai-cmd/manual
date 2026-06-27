#!/usr/bin/env python3
"""Validate generated user-manual markdown files against the 19 hard checks.

Usage:
    validate-output.py [--strict] [--json] [--no-unique] [--unique-allow=A,B] [--annotated-relaxed]
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

v1.1.0 — promoted the "screenshot unique" check from opt-in to
 default. The recorder is supposed to screenshot distinct steps, and
 byte-identical PNGs across distinct filenames is always a bug (or a
 brand-asset reuse that should be whitelisted via --unique-allow).
 Pass --no-unique to opt out for legacy reasons.
v1.1.0 — added the 9th check: "screenshot_uses_annotated". Closes
 the gap where alt text describes a red box / arrow but the
 referenced image is the bare (unannotated) PNG. The recorder
 always writes both `<name>.png` and `<name>.annotated.png`; the
 new check fires when an `![alt](path.png)` reference has a
 `<stem>.annotated.png` sibling on disk AND the alt text matches
 "红框" / "箭头" / "高亮" / "圈出" / "标注" / "看到:". Default
 FAIL. Use --annotated-relaxed to downgrade to a warning.
v0.4.0 — added the 8th check: "screenshot unique" (now default
 since v1.1.0; pre-1.1.0 was opt-in via --unique).
v1.1.0 — added the HARD GATE pre-flight: `_check_recording_phase_actually_ran`.
v1.2.0 — added two post-gate checks: `manifest_disk_consistency` (manifest
 asset inventory must match disk state; FAIL on manifest-only paths) and
 `file_type_sanity` (catch the 'manual.md is actually HTML' failure
 mode that bypassed v1.1.0 in the 2026-06 ehr audit).
v1.3.0 — internal cleanup: `screenshot unique` is now unconditionally
 on by default; the only opt-out is `--no-unique`. The check
 semantics are unchanged from v1.1.0 (already default-on); this
 release just makes the inverted-polarity flag name explicit
 (`UNIQUE_CHECK_SKIP` instead of `UNIQUE_CHECK_ENABLED`) so the
 call site reads naturally. Behaviour: `validate-output.py <file>`
 without flags runs the check. `validate-output.py --no-unique
 <file>` skips it. ehr 2026-06 audit round 3 reference: the 4
 groups of byte-identical screenshots (e.g. report-list-{toolbar,
 status-filter}.png) are now caught by the v1.1.0 default and
 reported as `screenshot unique (no duplicate content) FAIL`
 without any flag.
 The gate reads `docs/user-manual/recording_manifest.json` (written by the
 recorder skill via `manual_helper write-recording-manifest`). Without that
 file (or with a manifest that says dev server was unreachable, or recorder
 exit != 0, or 0 screenshots), validate-output prints a pause banner and
 exits 2 — even without --strict. Pass --no-hard-gate as an escape hatch
 for tests / CI maintenance.
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





# v2.3.0: GitHub-flavored markdown anchor slug. Mirrors GFM's
# `slugify` rule used by GitHub's anchor rendering: lowercase, drop
# non-word / non-CJK characters, replace runs of dropped chars with
# single `-`, trim leading/trailing `-`. Chinese (CJK Unified
# Ideographs U+4E00-U+9FFF) is kept verbatim — the LLM-written
# manuals depend on Chinese characters in the anchor.
def _gh_anchor_slug(title: str) -> str:
    s = title.strip().lower()
    # Replace any run of non-word, non-CJK characters with a single `-`.
    # `\w` is unicode-aware in Python 3 and includes CJK by default.
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", s, flags=re.UNICODE)
    return s.strip("-")


# v2.3.0: extract every internal `#anchor` reference from a markdown
# document, ignoring links to URLs (those start with `http`, a path
# component, or a non-`#` scheme). Excludes pure-anchor links of the
# form `<a name="x">` and inline code-fence mentions.
_INTERNAL_ANCHOR_RE = re.compile(r"\]\(#([^)\s]+)\)")


def _check_broken_anchors(text: str) -> dict:
    """v2.3.0: detect broken internal anchor references. LLM-written
    manuals frequently get the heading-slug wrong on links to other
    sections (most often: a heading "### 任务卡 1: 创建" and a link
    `[任务卡 1:创建](#任务卡-1创建)` where the LLM dropped the space
    after the colon, or vice versa). §3 says TOC links should resolve
    but until v2.3.0 the validator never actually checked.

    Rules:
      - Slug from heading text via GitHub-flavored slugify (lowercase,
        drop non-word, collapse runs to `-`).
      - Anchor from `](#slug)` capture group.
      - Ignore code-fence anchors (so the LLM can still show
        "before/after" examples in the SKILL doc).
      - Also check the user-facing `## 目录` section: every link in it
        MUST resolve (or the reader gets a dead TOC).
    """
    import re as _re
    # 1. Collect every heading slug in the doc (h1-h4 only — the LLM
    # uses h3/h4 for task cards and step blocks).
    headings: dict[str, str] = {}
    for m in _re.finditer(r"^(#{1,4})\s+(.+?)\s*$", text, _re.MULTILINE):
        level = len(m.group(1))
        title = m.group(2).strip()
        slug = _gh_anchor_slug(title)
        if slug:
            headings[slug] = title

    # 2. Walk every `](#slug)` and flag any missing target. Skip
    # anchors inside fenced code blocks.
    offenders: list[dict] = []
    for m in _INTERNAL_ANCHOR_RE.finditer(text):
        ref = m.group(1).strip()
        if not ref:
            continue
        # Compute line number
        line_no = text[: m.start()].count("\n") + 1
        # Skip if the position is inside a fenced code block
        in_code = False
        line_count = 0
        for line in text.split("\n"):
            line_count += 1
            if line_count == line_no:
                break
            if line.lstrip().startswith("```"):
                in_code = not in_code
        if in_code:
            continue
        if ref not in headings:
            offenders.append(
                {"ref": ref, "line": line_no}
            )

    # Convention: `hits` = offender count (matches audience_leak /
    # unfilled_template_terms / video_outside_steps). `headings_indexed`
    # is a side stat for diagnostics.
    return {
        "name": "broken_anchors (§3 TOC + 相关任务 internal links)",
        "hits": len(offenders),
        "threshold": 0,
        "comparison": "eq",
        "ok": (len(offenders) == 0),
        "flagged": len(offenders),
        "headings_indexed": len(headings),
        "offenders": offenders[:5],
    }


# v2.3.0: filename / URL patterns that signal the LLM emitted a
# placeholder asset instead of a real recorder output. Each pattern
# is matched against the literal path string that appears in:
#   - markdown image links `![alt](path)`
#   - markdown video links `[VIDEO: x](path)`
#   - raw `<img src=...>` / `<video src=...>` / `<source src=...>` tags
# This is a different concern from `_check_placeholder_alt` (which
# scans alt TEXT for laziness) and `_check_screenshot_files_exist`
# (which only fires for local relative paths). This check fires on
# the URL/path regardless of the markdown / HTML surface it's on.
_PLACEHOLDER_URL_PATTERNS = [
    (re.compile(r"^https?://placeholder\.invalid/", re.IGNORECASE),
     "placeholder.invalid 域占位 URL"),
    (re.compile(r"^https?://(?:example|todo|lorem)\.(?:com|invalid|org)/", re.IGNORECASE),
     "通用占位域名"),
    (re.compile(r"<(?:TODO|你的|your)[-_:：]", re.IGNORECASE),
     "未替换的 <TODO: / your- 模板"),
    (re.compile(r"^[\w./-]*<your-[^>]+>[\w./-]*$", re.IGNORECASE),
     "<your-...> 路径模板"),
]


def _check_placeholder_url(text: str) -> dict:
    """v2.3.0: detect asset paths that are obviously placeholders
    (placeholder.invalid, example.com, <TODO:>, <your-...>). The
    ehr manual audited in 2026-06 shipped with 6 image references
    pointing at `https://placeholder.invalid/screenshots/...` and 0
    real PNGs on disk — `_check_screenshot_files_exist` was bypassed
    because it only checks local relative paths. This check fires on
    the path string directly, regardless of whether it would resolve
    to a real file.

    Skips code-fence matches so the SKILL doc can still show
    positive/negative examples.
    """
    offenders: list[dict] = []

    # Sources to scan: markdown image / video links, plus raw HTML
    # src= attributes (the standalone HTML viewer uses inline HTML
    # after `convertVideoLinksInMd`).
    sources: list[tuple[str, re.Pattern[str]]] = [
        ("md-image", re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")),
        ("md-video", re.compile(r"\[VIDEO:[^\]]*\]\(([^)\s]+)\)")),
        ("md-video-ext", re.compile(r"\[VIDEO:[^\]]*\]\[([^\]]+)\]")),
        ("html-img", re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)),
        ("html-video", re.compile(r"<video[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)),
        ("html-source", re.compile(r"<source[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)),
    ]

    line_no = 1
    in_code = False
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("\u0060\u0060\u0060"):
            in_code = not in_code
            line_no += 1
            continue
        if not in_code:
            for src_label, src_re in sources:
                for m in src_re.finditer(line):
                    path = m.group(1).strip()
                    for pat_re, reason in _PLACEHOLDER_URL_PATTERNS:
                        if pat_re.search(path):
                            offenders.append({
                                "path": path[:120],
                                "reason": reason,
                                "source": src_label,
                                "line": line_no,
                            })
                            break
        line_no += 1

    return {
        "name": "placeholder_url (§2.7.1 类 5 录屏占位 + §16 路径规范)",
        "hits": len(offenders),
        "threshold": 0,
        "comparison": "eq",
        "ok": (len(offenders) == 0),
        "flagged": len(offenders),
        "offenders": offenders[:5],
    }


# v2.3.0: heading-block extractor. Returns a list of
# `(level, title, body_text, start_offset)` for every heading in
# the doc. Used to bound the body of each `### 任务卡 N:` block so
# we can count its `#### 步骤` subsections.
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)


# Fix _split_by_headings to do hierarchical splitting: a block at
# level L ends at the next heading with level <= L (not the next
# heading of any level, which would chop a task-card body right at
# its first `#### 步骤` child).
import re as _re


def _split_by_headings(text: str) -> list[dict]:
    """Slice `text` into hierarchical blocks. A block at level L
    ends at the next heading with level ≤ L (or end of doc).
    Returns a list of dicts:
      {level, title, body, start_line, end_line}.

    The hierarchical boundary is what makes the per-task-card body
    include all of its `#### 步骤` / `#### 成功后看到` etc. children
    — otherwise the body of `### 任务卡 1: …` would end at the first
    `#### 步骤`, and `_check_task_card_steps_count` would always
    see 0 steps.
    """
    matches = list(_re.finditer(r"^(#{1,4})\s+(.+?)\s*$", text, _re.MULTILINE))
    if not matches:
        return []
    out: list[dict] = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        start = m.end()
        end = len(text)
        for j in range(i + 1, len(matches)):
            if len(matches[j].group(1)) <= level:
                end = matches[j].start()
                break
        body = text[start:end]
        start_line = text[: m.start()].count("\n") + 1
        end_line = text[:end].count("\n") + 1
        out.append({
            "level": level,
            "title": title,
            "body": body,
            "start_line": start_line,
            "end_line": end_line,
        })
    return out



def _check_task_card_steps_count(text: str) -> dict:
    """v2.3.0: each `### 任务卡 N:` block should contain exactly one
    `#### 步骤` subsection. §2.1 says "one task card = one specific
    operation" but the LLM often splits a card into multiple `####
    步骤` blocks (e.g. "### 任务卡 9: 发布/停用" with separate step
    blocks for each verb). That defeats the navigation contract:
    the viewer left-TOC shows one "步骤" node per card, not N.

    The check is per-card. Cards with 0 `#### 步骤` (which is fine
    if the card uses `#### 演示视频` only) are not flagged here —
    that's covered by the existing 7-field hits check.
    """
    blocks = _split_by_headings(text)
    # find task-card headings (3rd-level `### 任务卡 N: ...`)
    tc_re = re.compile(r"^任务卡\s+\d+[:：]\s*.+$")
    # Match `#### 步骤` with optional trailing text — covers the
    # `#### 步骤(发布)` / `#### 步骤: foo` variants the LLM emits.
    steps_re = re.compile(r"^####\s+步骤.*$", re.MULTILINE)
    offenders: list[dict] = []
    well_count = 0
    total_cards = 0
    for blk in blocks:
        if blk["level"] != 3:
            continue
        if not tc_re.match(blk["title"]):
            continue
        total_cards += 1
        steps = steps_re.findall(blk["body"])
        if len(steps) == 1:
            well_count += 1
        elif len(steps) > 1:
            offenders.append({
                "card": blk["title"],
                "line": blk["start_line"],
                "steps_count": len(steps),
            })

    return {
        "name": "task_card_steps_count (§2.1 一卡一操作)",
        "hits": well_count,
        "threshold": 0,
        "comparison": "ge",
        "ok": (len(offenders) == 0),
        "flagged": len(offenders),
        "well_formed_count": well_count,
        "total_task_cards": total_cards,
        "offenders": offenders[:5],
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


# v1.1.0: hard gate. A "finished" user-manual must have a
# recording_manifest.json next to it (sibling of docs/user-manual/manual/
# or at docs/user-manual/recording_manifest.json) that proves the
# recorder skill drove a real browser against a reachable dev server.
# Without this file, the LLM agent almost certainly hand-drew 80x60
# grey PNGs as "screenshots" and is trying to pass them off as real
# assets. The ehr 2026-06 manual shipped exactly this failure mode:
# alt text was perfect, files existed on disk, every prior check
# passed. The manual looked finished. It was not. This hard gate
# closes that gap.
def _check_recording_phase_actually_ran(md_path: Path) -> dict:
    """Read docs/user-manual/recording_manifest.json and verify it is
    a real, complete manifest. Used as a pre-flight gate in
    validate_file(); if it fails, validate_file returns early and
    main() prints the pause banner and exits 2.
    """
    # Search up for docs/user-manual/ from the .md file.
    candidates: list[Path] = []
    cur = md_path.resolve().parent
    while cur != cur.parent:
        candidates.append(cur / "recording_manifest.json")
        if cur.name == "user-manual":
            break
        cur = cur.parent
    manifest = next((c for c in candidates if c.exists()), None)
    if manifest is None:
        return {
            "ok": False,
            "name": "recording_phase_actually_ran (v1.1.0 hard gate)",
            "reason": "no_manifest",
            "manifest_path": None,
            "detail": (
                "no recording_manifest.json found. The LLM agent that "
                "wrote this manual did not run SKILL.md \u00a714 (the "
                "recording phase) end-to-end, and the markdown was "
                "submitted as a deliverable without real screenshots."
            ),
        }
    try:
        import json as _json
        data = _json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "name": "recording_phase_actually_ran (v1.1.0 hard gate)",
            "reason": "manifest_unreadable",
            "manifest_path": str(manifest),
            "detail": f"manifest exists but is unreadable: {type(e).__name__}: {e}",
        }
    # Schema check
    if data.get("schema_version") != "1.0":
        return {
            "ok": False,
            "name": "recording_phase_actually_ran (v1.1.0 hard gate)",
            "reason": "schema_mismatch",
            "manifest_path": str(manifest),
            "detail": (
                f"manifest schema_version is {data.get('schema_version')!r}, "
                "expected '1.0'. Re-run the recorder (it writes the current "
                "schema)."
            ),
        }
    if int(data.get("recorder_cli_exit", 1)) != 0:
        return {
            "ok": False,
            "name": "recording_phase_actually_ran (v1.1.0 hard gate)",
            "reason": "recorder_failed",
            "manifest_path": str(manifest),
            "detail": (
                f"recorder_cli_exit={data.get('recorder_cli_exit')!r}, expected 0. "
                "Re-run the recorder and verify it exits 0."
            ),
        }
    totals = data.get("totals", {}) or {}
    shots = int(totals.get("screenshots", 0))
    if shots <= 0:
        return {
            "ok": False,
            "name": "recording_phase_actually_ran (v1.1.0 hard gate)",
            "reason": "no_screenshots",
            "manifest_path": str(manifest),
            "detail": (
                "manifest.totals.screenshots == 0. The recorder ran but wrote "
                "no PNGs. Either the recorder script had no screenshot steps, "
                "or every step failed silently. Re-run with verbose output."
            ),
        }
    if not data.get("dev_server", {}).get("reachable", False):
        return {
            "ok": False,
            "name": "recording_phase_actually_ran (v1.1.0 hard gate)",
            "reason": "dev_server_unreachable",
            "manifest_path": str(manifest),
            "detail": (
                f"manifest.dev_server.readiness_status="
                f"{data.get('dev_server', {}).get('readiness_status')!r}; "
                "expected 'green'. The recorder ran against an unreachable dev "
                "server and the screenshots are likely of an error page. Start "
                "the dev server and re-run \u00a714."
            ),
        }
    return {
        "ok": True,
        "name": "recording_phase_actually_ran (v1.1.0 hard gate)",
        "reason": "ok",
        "manifest_path": str(manifest),
        "detail": (
            f"manifest verified: {shots} screenshots, "
            f"{totals.get('videos', 0)} videos, dev server "
            f"{data.get('dev_server', {}).get('readiness_status', 'n/a')}"
        ),
    }


# v1.2.0: manifest_disk_consistency. The manifest is a snapshot
# of disk state at recording time. If a `recording_manifest.json`
# says "we wrote screenshot X" but X is no longer on disk (someone
# rm'd it, or it was overwritten by a different agent run), the
# manual is referencing a ghost. Conversely, if the disk has
# screenshots that the manifest never claimed, the agent that
# recorded them bypassed the manifest contract — the recorder
# phase did not run cleanly.
#
# Found in the 2026-06 ehr audit (post-v1.1.0): manifest listed
# `screenshots/blacklist/blacklist-nav.png` (and ~17 other files),
# but `screenshots/blacklist/` was entirely empty on disk. The
# manifest was stale; markdown references were broken; the manual
# still passed every v1.1.0 check because the gate only validated
# manifest *content*, not *consistency with disk*.
def _check_manifest_disk_consistency(md_path: Path, text: str) -> dict:
    """v1.2.0: verify the manifest's asset inventory matches disk.

    Two failure modes:
      - `manifest_only`: path is in the manifest but NOT on disk.
        Manual will fail the screenshot files exist check too, but
        we surface it here with the manifest contract angle.
      - `disk_only`: path is on disk but NOT in the manifest. Likely
        an LLM agent (or human) wrote extra PNGs without going
        through the recorder skill. We do not fail on this; we just
        report it. Treat as WARN (not FAIL) — the manual itself
        may still be valid; this is a process-hygiene signal.
    """
    import json as _json
    # Find manifest (same logic as _check_recording_phase_actually_ran)
    manifest = None
    cur = md_path.resolve().parent
    while cur != cur.parent:
        c = cur / "recording_manifest.json"
        if c.exists():
            manifest = c
            break
        if cur.name == "user-manual":
            break
        cur = cur.parent
    if manifest is None:
        # No manifest; v1.1.0 hard gate would have already blocked.
        # Be a soft no-op so this check can run independently.
        return {
            "name": "manifest_disk_consistency (v1.2.0)",
            "hits": 0,
            "threshold": 0,
            "comparison": "eq",
            "ok": True,
            "manifest_path": None,
            "manifest_only": [],
            "disk_only": [],
            "note": "no manifest present; pre-flight gate owns this case",
        }
    try:
        data = _json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {
            "name": "manifest_disk_consistency (v1.2.0)",
            "hits": 0,
            "threshold": 0,
            "comparison": "eq",
            "ok": True,
            "manifest_path": str(manifest),
            "manifest_only": [],
            "disk_only": [],
            "note": "manifest unreadable; pre-flight gate owns this case",
        }
    # Collect manifest asset paths (relative to manifest dir).
    manifest_dir = manifest.parent
    manifest_paths: set[Path] = set()
    for kind in ("screenshots", "videos", "ai_annotated"):
        for rel in data.get("assets", {}).get(kind, []) or []:
            manifest_paths.add((manifest_dir / rel).resolve())
    # On-disk paths in the screenshots/ tree.
    screenshots_dir = manifest_dir / "screenshots"
    disk_paths: set[Path] = set()
    if screenshots_dir.exists():
        for p in screenshots_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm"}:
                disk_paths.add(p.resolve())
    manifest_only = sorted(str(p.relative_to(manifest_dir)) for p in manifest_paths - disk_paths)
    disk_only = sorted(str(p.relative_to(manifest_dir)) for p in disk_paths - manifest_paths)
    return {
        "name": "manifest_disk_consistency (v1.2.0)",
        "hits": len(manifest_paths & disk_paths),
        "threshold": len(manifest_paths),
        "comparison": "ge",
        # FAIL if any manifest-listed path is missing on disk.
        "ok": (len(manifest_only) == 0),
        "manifest_path": str(manifest),
        "manifest_only": manifest_only[:5],
        "disk_only": disk_only[:5],
        "manifest_only_count": len(manifest_only),
        "disk_only_count": len(disk_only),
    }


# v1.2.0: file_type_sanity. The markdown file passed to validator
# must actually be a markdown file, not an HTML viewer template,
# SVG, or some other format that happened to be renamed .md.
#
# Found in the 2026-06 ehr audit (post-v1.1.0): `manual/user-manual.md`
# was overwritten with the full HTML viewer template
# (`<!DOCTYPE html>...<script>...</html>`, 4722 lines, 116KB).
# The hard gate didn't catch it (manifest existed; the HTML was
# happily "validated" as if it were markdown). This check is a
# cheap first-line defense.
def _check_file_type_sanity(md_path: Path, text: str) -> dict:
    """v1.2.0: catch the 'manual/<x>.md is actually HTML' failure mode.

    A valid user-manual .md must start with either a YAML
    frontmatter block (`---\n`), a top-level heading (`# ...`),
    or a few blank lines / copyright lines, then `# ...`. Anything
    that looks like a full document of another type is a red flag.
    """
    head = text[:2000]
    # Heuristics (cheap, deterministic, no parsing).
    looks_like_html = any(s in head[:200] for s in (
        "<!DOCTYPE", "<html", "<head>", "<body>", "<svg",
    ))
    looks_like_xml = head.lstrip().startswith("<?xml")
    looks_like_json = head.lstrip().startswith("{") and '"' in head[:100]
    looks_like_pdf = head.startswith("%PDF-")
    looks_like_binary = any(b in head.encode("utf-8", errors="replace")[:200] for b in (b"\x00",))
    has_frontmatter = head.startswith("---\n")
    has_h1 = any(line.startswith("# ") for line in head.splitlines()[:50])
    if looks_like_html or looks_like_xml or looks_like_json or looks_like_pdf or looks_like_binary:
        return {
            "name": "file_type_sanity (v1.2.0)",
            "hits": 0,
            "threshold": 1,
            "comparison": "ge",
            "ok": False,
            "reason": "not_markdown",
            "detail": (
                f"this file does not look like markdown. "
                f"html={looks_like_html} xml={looks_like_xml} "
                f"json={looks_like_json} pdf={looks_like_pdf} "
                f"binary={looks_like_binary}. The .md extension was "
                "probably applied to a non-markdown document. "
                "Restore from git or regenerate."
            ),
        }
    if not has_frontmatter and not has_h1:
        return {
            "name": "file_type_sanity (v1.2.0)",
            "hits": 0,
            "threshold": 1,
            "comparison": "ge",
            "ok": False,
            "reason": "no_frontmatter_or_h1",
            "detail": (
                "no YAML frontmatter (---\n) and no top-level "
                "# heading in the first 50 lines. This may not be a "
                "user-manual markdown file."
            ),
        }
    return {
        "name": "file_type_sanity (v1.2.0)",
        "hits": 1,
        "threshold": 1,
        "comparison": "ge",
        "ok": True,
        "detail": "looks like markdown (frontmatter or H1 present)",
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



def _check_screenshot_uses_annotated(md_path: Path, text: str) -> dict:
    """v1.1.0: catch the gap where alt text describes a red box / arrow /
    highlight, but the referenced image is the bare (unannotated) PNG.

    Recorder always writes both `<name>.png` (raw) and
    `<name>.annotated.png` (with red box / arrow / caption drawn on top).
    If the manual references the bare PNG while the alt text claims
    "红框:..." or "箭头:...", the reader sees an unannotated image and
    the alt text becomes a lie.

    Resolution rules:
      - Path resolved relative to md_path.parent.
      - Only fires when the alt text matches one of the "red box / arrow /
        highlight" keywords (case-insensitive) AND the bare path has an
        `.annotated` sibling on disk.
      - v1.1.0 default: FAIL (the manual is shipping broken image refs).
      - Pass --annotated-relaxed to downgrade to a warning (still listed
        in `flagged` but `ok=True`).
    """
    RELAXED = globals().get("ANNOTATED_RELAXED", False)
    keywords = re.compile(r"红框|箭头|高亮|圈出|标注|看到[:：]", re.IGNORECASE)
    image_paths = _extract_image_paths(text)
    md_dir = md_path.parent
    offenders: list[dict] = []
    for ref in image_paths:
        target = (md_dir / ref).resolve()
        if not target.exists() or not target.is_file():
            continue
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        if target.stem.endswith(".annotated"):
            continue
        annotated_sibling = target.with_name(f"{target.stem}.annotated{target.suffix}")
        if not annotated_sibling.exists():
            continue
        # We have a bare PNG that has an annotated sibling on disk.
        # Look at the alt text on this reference.
        escaped = re.escape(ref)
        # match the exact `![alt](ref)` form (with optional query/fragment)
        alt_re = re.compile(rf"!\[(?P<alt>[^\]]*)\]\({escaped}(?:[?#][^)]*)?\)", re.IGNORECASE)
        m = alt_re.search(text)
        if not m:
            continue
        alt = m.group("alt") or ""
        if not keywords.search(alt):
            continue
        offenders.append({
            "ref": ref,
            "annotated_sibling": str(annotated_sibling.relative_to(md_dir)) if annotated_sibling.is_relative_to(md_dir) else str(annotated_sibling),
            "alt": alt,
        })
    flagged = len(offenders)
    # if relaxed, the check is informational only
    ok = (flagged == 0) or RELAXED
    return {
        "name": "screenshot_uses_annotated (alt text matches annotated sibling)",
        "hits": flagged,
        "threshold": 0,
        "comparison": "eq",
        "ok": ok,
        "flagged": flagged,
        "offenders": offenders[:10],
        "relaxed": RELAXED,
    }


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
    # v1.1.0 hard gate: pre-flight. Runs BEFORE any other check.
    # On failure: return a stub with preflight_blocked=True so
    # main() prints the pause banner and exits 2 without running
    # the (more expensive) regex checks.
    # On success: stash the gate check on a closure var so we
    # can prepend it to results below (so users see the gate
    # passed, not just "the other 11 checks ran").
    preflight_gate_check = None
    if not globals().get("HARD_GATE_DISABLED", False):
        gate = _check_recording_phase_actually_ran(path)
        if not gate["ok"]:
            return {
                "file": str(path),
                "ok": False,
                "checks": [{
                    "name": gate["name"],
                    "hits": 0,
                    "threshold": 1,
                    "comparison": "ge",
                    "ok": False,
                    "reason": gate["reason"],
                    "manifest_path": gate["manifest_path"],
                    "detail": gate["detail"],
                }],
                "preflight_blocked": True,
                "preflight_reason": gate["reason"],
            }
        preflight_gate_check = {
            "name": gate["name"],
            "hits": 1,
            "threshold": 1,
            "comparison": "ge",
            "ok": True,
            "reason": gate["reason"],
            "manifest_path": gate["manifest_path"],
            "detail": gate["detail"],
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    text_for_prose = _strip_code(text)
    results = []
    if preflight_gate_check is not None:
        results.append(preflight_gate_check)
    # v1.1.0: if pre-flight was disabled, start True; if it ran and
    # passed, start True; only start False if it ran and blocked (which
    # would have returned early above, so this is just defensive).
    all_ok = preflight_gate_check is None or preflight_gate_check.get("ok", False)
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
    all_ok = all_ok and vsteps_check["ok"]
    # v2.3.0: §3 internal anchor integrity. Headings vs links must agree,
    # otherwise the TOC and "相关任务" navigation is dead. Found in the
    # 2026-06 ehr audit: 8 broken anchors in the overview manual because
    # the LLM dropped the space after `:` in one of the two places.
    anchor_check = _check_broken_anchors(text)
    results.append({
        "name": anchor_check["name"],
        "hits": anchor_check["hits"],
        "threshold": anchor_check["threshold"],
        "comparison": anchor_check["comparison"],
        "ok": anchor_check["ok"],
        "flagged": anchor_check["flagged"],
        "headings_indexed": anchor_check["headings_indexed"],
        "offenders": anchor_check["offenders"],
    })
    all_ok = all_ok and anchor_check["ok"]
    # v2.3.0: §16 asset-path rule. The ehr manual shipped 6 references
    # to https://placeholder.invalid/... and 0 real PNGs on disk;
    # _check_screenshot_files_exist was bypassed because it only
    # matches local relative paths. This new check fires on the URL
    # string regardless of whether it would resolve.
    purl_check = _check_placeholder_url(text)
    results.append({
        "name": purl_check["name"],
        "hits": purl_check["hits"],
        "threshold": purl_check["threshold"],
        "comparison": purl_check["comparison"],
        "ok": purl_check["ok"],
        "flagged": purl_check["flagged"],
        "offenders": purl_check["offenders"],
    })
    all_ok = all_ok and purl_check["ok"]
    # v2.3.0: §2.1 "one task card = one operation" + §4 template
    # contract. Each `### 任务卡 N:` block must contain exactly one
    # `#### 步骤` subsection. The ehr manual's report task card 9
    # had two (one for "发布", one for "停用"), defeating the
    # viewer's left-TOC navigation.
    tcs_check = _check_task_card_steps_count(text)
    results.append({
        "name": tcs_check["name"],
        "hits": tcs_check["hits"],
        "threshold": tcs_check["threshold"],
        "comparison": tcs_check["comparison"],
        "ok": tcs_check["ok"],
        "flagged": tcs_check["flagged"],
        "well_formed_count": tcs_check["well_formed_count"],
        "total_task_cards": tcs_check["total_task_cards"],
        "offenders": tcs_check["offenders"],
    })
    all_ok = all_ok and tcs_check["ok"]
    # v1.2.0: manifest asset inventory must match disk state.
    mdc_check = _check_manifest_disk_consistency(path, text)
    results.append({
        "name": mdc_check["name"],
        "hits": mdc_check["hits"],
        "threshold": mdc_check["threshold"],
        "comparison": mdc_check["comparison"],
        "ok": mdc_check["ok"],
        "manifest_path": mdc_check.get("manifest_path"),
        "manifest_only": mdc_check.get("manifest_only", []),
        "disk_only": mdc_check.get("disk_only", []),
        "manifest_only_count": mdc_check.get("manifest_only_count", 0),
        "disk_only_count": mdc_check.get("disk_only_count", 0),
    })
    all_ok = all_ok and mdc_check["ok"]
    # v1.2.0: ensure the .md is actually a markdown file.
    fts_check = _check_file_type_sanity(path, text)
    results.append({
        "name": fts_check["name"],
        "hits": fts_check["hits"],
        "threshold": fts_check["threshold"],
        "comparison": fts_check["comparison"],
        "ok": fts_check["ok"],
        "reason": fts_check.get("reason", ""),
        "detail": fts_check.get("detail", ""),
    })
    all_ok = all_ok and fts_check["ok"]
    # v1.3.0 cleanup: --no-unique is the ONLY opt-out. The check
    # is on by default (since v1.1.0). Flag is named UNIQUE_CHECK_SKIP
    # to make the inverted polarity explicit at the call site.
    if not globals().get("UNIQUE_CHECK_SKIP", False):
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
    # v1.1.0: alt-text-vs-annotated-sibling consistency. Catches the
    # "alt says 红框, image has no red box" gap that the ehr manual
    # shipped on every task card.
    ann_check = _check_screenshot_uses_annotated(path, text)
    results.append({
        "name": ann_check["name"],
        "hits": ann_check["hits"],
        "threshold": ann_check["threshold"],
        "comparison": ann_check["comparison"],
        "ok": ann_check["ok"],
        "flagged": ann_check["flagged"],
        "offenders": ann_check["offenders"],
        "relaxed": ann_check.get("relaxed", False),
    })
    all_ok = all_ok and ann_check["ok"]
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
                elif c["name"] == "screenshot_uses_annotated (alt text matches annotated sibling)":
                    offenders = c.get("offenders", [])
                    rendered = "; ".join(
                        "{}(alt={!r})".format(o["ref"], o.get("alt", ""))
                        for o in offenders
                    ) or "(no offenders)"
                    relaxed = " [RELAXED: warning only]" if c.get("relaxed") else ""
                    lines.append(
                        "        - {}: {}/{} flagged ({}); e.g. {}{}".format(
                            c["name"], c["hits"], c["threshold"],
                            c.get("flagged", 0), rendered, relaxed,
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
    # v1.1.0: --unique is now the default (was opt-in pre-1.1.0). The
    # recorder should not be producing byte-identical screenshots
    # anyway, so this catches a real bug every time. Pass --no-unique
    # to disable; pass --unique-allow to whitelist a shared asset
    # (e.g. a logo PNG that legitimately appears on many pages).
    unique = "--no-unique" not in args
    # --unique-allow logo.png,branding.png -> whitelist
    unique_allow: set = set()
    for a in list(args):
        if a.startswith("--unique-allow="):
            unique_allow = {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
            args.remove(a)
        elif a == "--unique-allow":
            args.remove(a)
        elif a == "--no-unique":
            args.remove(a)
    # v1.1.0: --annotated-relaxed downgrades the new
    # screenshot_uses_annotated check to a warning (still listed in
    # offenders, but does not flip `ok=False`). Use when you have a
    # legitimate reason to reference bare PNGs even though annotated
    # siblings exist (e.g. you want to show the original UI alongside
    # the annotated version in a side-by-side comparison).
    annotated_relaxed = "--annotated-relaxed" in args
    # v1.1.0: --no-hard-gate is an escape hatch for tests / CI
    # maintenance. It disables the recording_manifest.json pre-flight
    # gate. DO NOT pass this when validating a deliverable.
    hard_gate_disabled = "--no-hard-gate" in args
    args = [a for a in args if not a.startswith("--")]
    # Stash on module globals so validate_file can pick up.
    globals()["UNIQUE_CHECK_SKIP"] = not unique  # v1.3.0: invert polarity
    globals()["UNIQUE_CHECK_ALLOW"] = unique_allow
    globals()["ANNOTATED_RELAXED"] = annotated_relaxed
    globals()["HARD_GATE_DISABLED"] = hard_gate_disabled
    if not args:
        print(__doc__.strip())
        return 0
    results = [validate_file(Path(a)) for a in args]
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(render_human(results))
    # v1.1.0: pre-flight pause banner. If any file was blocked at the
    # recording-phase gate, print a loud "stop and run \u00a714" message
    # and exit 2 (regardless of --strict). This is the contract that
    # forces the LLM agent to actually drive the recorder, not just
    # hand-draw placeholders and submit.
    blocked = [r for r in results if r.get("preflight_blocked")]
    if blocked:
        if not as_json:
            _print_hard_gate_pause_banner(blocked)
        return 2
    if strict and not all(r["ok"] for r in results):
        return 1
    return 0


def _print_hard_gate_pause_banner(blocked: list[dict]) -> None:
    """v1.1.0: print the "STOP, run \u00a714 end-to-end" message when the
    pre-flight recording-phase gate fails. Multi-line, intentional: the
    whole point is to make the LLM agent (or human reviewer) stop and
    think before pushing the manual as a deliverable.
    """
    print("", file=sys.stderr)
    print("\u26d4  HARD GATE FAILED: recording phase did not actually run", file=sys.stderr)
    print("-" * 64, file=sys.stderr)
    print("", file=sys.stderr)
    for r in blocked:
        check = r["checks"][0]
        print(f"  file: {r['file']}", file=sys.stderr)
        print(f"  reason: {check.get('reason', '?')}", file=sys.stderr)
        print(f"  manifest: {check.get('manifest_path') or '(none)'}", file=sys.stderr)
        print(f"  detail: {check.get('detail', '')}", file=sys.stderr)
        print("", file=sys.stderr)
    print("  What the LLM agent should have done (in order):", file=sys.stderr)
    print("    1. python3 -m manual_helper check-recording-readiness", file=sys.stderr)
    print("         -> expected: \u2705 GREEN or \u26a0\ufe0f  WARNING. If", file=sys.stderr)
    print("            \ud83d\udd34 BLOCKED, fix env first.", file=sys.stderr)
    print("    2. python3 -m manual_helper scan-recording-placeholders docs/user-manual/manual/<x>.md", file=sys.stderr)
    print("    3. python3 -m manual_helper build-recorder-template ...  -> emits script.json", file=sys.stderr)
    print("    4. (you fill in selectors) -> python3 -m recorder_plugin.cli run <script>.json", file=sys.stderr)
    print("    5. python3 -m manual_helper apply-recording-mapping ...  -> replaces placeholders", file=sys.stderr)
    print("    6. python3 -m manual_helper write-recording-manifest ...  -> emits the gate file", file=sys.stderr)
    print("    7. python3 -m manual_helper validate-output ...  -> this script", file=sys.stderr)
    print("", file=sys.stderr)
    print("  Stopping here. The manual's markdown is still on disk, but it", file=sys.stderr)
    print("  is not a valid deliverable until \u00a714 is run end-to-end.", file=sys.stderr)
    print("", file=sys.stderr)
    print("  If a previous run wrote hand-drawn placeholder PNGs to", file=sys.stderr)
    print("  screenshots/ (e.g. 80x60 grey stubs) to pass the file-existence", file=sys.stderr)
    print("  check, delete them so a real \u00a714 run can write real ones", file=sys.stderr)
    print("  without hash collisions:  rm -rf docs/user-manual/screenshots/*", file=sys.stderr)
    print("", file=sys.stderr)
    print("  (Escape hatch: pass --no-hard-gate to skip this gate. CI should", file=sys.stderr)
    print("   never pass that flag.)", file=sys.stderr)
    print("-" * 64, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
