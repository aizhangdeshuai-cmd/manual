#!/usr/bin/env python3
"""Extract user tasks / user stories from superpowers spec markdown files.

Input:  one or more markdown file paths (typically docs/superpowers/specs/*.md)
Output: JSON array to stdout, each entry:
        {source, task_name, persona, prerequisites, steps, raw_section}

Scanning rules (priority order):
  1. Headings starting with 用户故事 / User Story / 操作流程 / 用户视角 / 任务清单
  2. Bullet lists immediately under a heading containing 用户 / 操作 / 任务 / 流程
  3. Numbered lists of the form "1. 用户做 X" inside any section
  4. Fallback: every H2/H3 becomes a candidate task (LLM will refine later)

If no tasks found, emits a single informational entry so the LLM knows to
fall back to .vue + route-based task inference.

Output schema (JSON array; one entry per task candidate):
  [
    {
      "source": "docs/superpowers/specs/sys.md",
      "heading_line": 42,
      "task_name": "创建新用户",
      "persona": "系统管理员",
      "prerequisites": [],
      "steps": [
        "打开用户管理",
        "点击新增",
        "填入用户名、密码、角色",
        "提交"
      ],
      "raw_section_excerpt": "在用户管理页面..."
    }
  ]

Field reference:
- source: spec file path (str)
- heading_line: 1-based line number of the task heading (int)
- task_name: stripped heading text (str)
- persona: detected role noun from heading/body, or null (str|null)
- prerequisites: usually empty; reserved for future cross-ref (list)
- steps: bullet/numbered list items, in order (list of str)
- raw_section_excerpt: first 600 chars of body for LLM context (str)

Empty array [] is valid (no user-story headings and no H2/H3-with-bullets found).
Orchestrator (SKILL.md section 5.2) should fall back to .vue + router-based
task inference.

"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

USER_TASK_HEADING_RE = re.compile(
    r"^\s*(#{1,6})\s*"
    r"(?:用户故事|用户视角|操作流程|任务清单|任务卡|User Story|Task|Job to be done|Use Case)\b",
    re.IGNORECASE,
)
GENERIC_HEADING_RE = re.compile(r"^\s*(#{1,6})\s*(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")

# v0.2.2: action-verb filter for fallback mode. A "task" should have an actionable
# verb, not just any bullet. Recognized Chinese and English verbs, plus
# User-Story and BDD style starters.
ACTION_VERB_RE = re.compile(
    r"^\s*(?:"
    # Chinese action verbs
    r"创建|添加|删除|修改|更新|打开|关闭|点击|输入|选择|提交|保存|取消|"
    r"登录|登出|导入|导出|查看|启用|禁用|重置|搜索|筛选|排序|打印|"
    r"下载|上传|编辑|设置|配置|发布|审批|审核|复核|分配|转移|处理|"
    r"解决|回复|登记|注册|绑定|解绑|关联|取消关联|开始|结束|暂停|恢复|"
    r"查询|检索|刷新|确认|取消确认|启用|停用|同步|异步|激活|"
    # English action verbs (lowercased in IGNORECASE)
    r"create|add|delete|remove|update|modify|open|close|click|type|select|submit|save|cancel|"
    r"login|logout|sign|import|export|view|enable|disable|reset|search|filter|sort|print|"
    r"download|upload|edit|set|configure|configure|publish|approve|review|assign|transfer|process|"
    r"resolve|reply|register|bind|unbind|link|unlink|start|end|stop|resume|refresh|"
    # User Story and BDD style
    r"As\s+a\s+|I\s+want\s+to\s+|I\s+can\s+|Given\s+|When\s+|Then\s+"
    r")",
    re.IGNORECASE,
)

MIN_BULLETS_FOR_FALLBACK = 3  # Don't pick sections with only 1-2 bullets


def _strip_markdown(s: str) -> str:
    """Remove bold/italic/code markers from a line, keep plain text."""
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    return s.strip()


def _parse_steps(section_text: str) -> list[str]:
    """Extract steps from a section as a bullet/numbered list."""
    steps: list[str] = []
    in_code = False
    for raw in section_text.splitlines():
        if raw.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = BULLET_RE.match(raw) or NUMBERED_RE.match(raw)
        if m:
            text = _strip_markdown(m.group(1))
            if text and len(text) >= 2:
                steps.append(text)
    return steps


def _has_action_verb(body_lines: list[str]) -> bool:
    """v0.2.2: True if at least one bullet/numbered item starts with an action verb.

    This filter dramatically reduces false positives in fallback mode — sections
    like "Architecture" (bullets: 'Uses React', 'Why we chose Postgres') or
    "Data Model" (bullets: 'User has many Posts', 'Each Post belongs to a User')
    will be filtered out because none of their bullets start with an action verb.
    """
    for bl in body_lines:
        m = BULLET_RE.match(bl) or NUMBERED_RE.match(bl)
        if m and ACTION_VERB_RE.match(m.group(1)):
            return True
    return False


def _count_bullets(body_lines: list[str]) -> int:
    """Count bullet + numbered list items in body_lines (excluding code fences)."""
    n = 0
    in_code = False
    for bl in body_lines:
        if bl.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if BULLET_RE.match(bl) or NUMBERED_RE.match(bl):
            n += 1
    return n


def _detect_persona(text: str) -> str | None:
    """Best-effort persona detection: search for known role nouns.

    Returns the matched role string or None.
    """
    roles = [
        "管理员", "运营", "操作员", "业务专员", "业务主管", "法务", "财务",
        "审计", "合规", "用户", "客户", "管理员", "审批人", "复核人",
        "admin", "operator", "user", "auditor", "manager", "reviewer",
    ]
    lower = text.lower()
    for r in roles:
        if r.lower() in lower:
            return r
    return None


def extract_from_file(path: Path) -> list[dict]:
    """Return a list of task candidates from a single spec file."""
    if not path.exists():
        return [{"source": str(path), "error": "file not found"}]
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Find headings that look like user-task sections
    sections: list[tuple[int, str, str]] = []  # (line_idx, heading, body)
    matches: list[tuple[int, str, int]] = []  # (line_idx, heading, level)
    for i, line in enumerate(lines):
        m = USER_TASK_HEADING_RE.match(line)
        if m:
            matches.append((i, _strip_markdown(m.group(2) if m.lastindex and m.lastindex >= 2 else line), len(m.group(1))))

    # If no explicit user-task headings, fall back: H2/H3 with bullets, BUT
    # v0.2.2 — apply two filters to cut noise:
    #   1. require >= MIN_BULLETS_FOR_FALLBACK bullets (no "Architecture: see X" as task)
    #   2. require at least one bullet to start with an action verb (no "Data
    #      Model: User has many Posts" as task)
    if not matches:
        for i, line in enumerate(lines):
            m = GENERIC_HEADING_RE.match(line)
            if not m:
                continue
            level = len(m.group(1))
            if level not in (2, 3):
                continue
            heading = _strip_markdown(m.group(2))
            body_lines = []
            for j in range(i + 1, min(i + 80, len(lines))):
                lm = GENERIC_HEADING_RE.match(lines[j])
                if lm and len(lm.group(1)) <= level:
                    break
                body_lines.append(lines[j])
            bullet_count = _count_bullets(body_lines)
            if bullet_count >= MIN_BULLETS_FOR_FALLBACK and _has_action_verb(body_lines):
                matches.append((i, heading, level))

    # Slice body for each match
    for idx, (i, heading, level) in enumerate(matches):
        # Body runs until next heading of same or shallower level
        body_lines = []
        for j in range(i + 1, len(lines)):
            lm = GENERIC_HEADING_RE.match(lines[j])
            if lm and len(lm.group(1)) <= level:
                break
            body_lines.append(lines[j])
        sections.append((i, heading, "\n".join(body_lines)))

    out: list[dict] = []
    for i, heading, body in sections:
        steps = _parse_steps(body)
        if not steps:
            # Heading alone is a candidate; LLM will flesh out
            steps = []
        persona = _detect_persona(heading + " " + body[:400])
        out.append({
            "source": str(path),
            "heading_line": i + 1,
            "task_name": heading,
            "persona": persona,
            "prerequisites": [],  # Filled in by LLM or via cross-references
            "steps": steps,
            "raw_section_excerpt": body[:600],
        })
    return out


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: extract-tasks.py <spec.md> [more.md ...]", file=sys.stderr)
        print("       extract-tasks.py <specs-dir-glob>", file=sys.stderr)
        return 0
    paths: list[Path] = []
    for arg in argv:
        p = Path(arg)
        if p.is_dir():
            paths.extend(sorted(p.glob("**/*.md")))
        elif "*" in arg or "?" in arg:
            import glob
            for g in sorted(glob.glob(arg)):
                paths.append(Path(g))
        else:
            paths.append(p)
    if not paths:
        print(json.dumps([{"warning": "no input files matched"}], ensure_ascii=False, indent=2))
        return 0
    all_tasks: list[dict] = []
    for p in paths:
        all_tasks.extend(extract_from_file(p))
    json.dump(all_tasks, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
