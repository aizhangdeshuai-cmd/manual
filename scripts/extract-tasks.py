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

    # If no explicit user-task headings, fall back: every H2/H3 with bullets anywhere in body
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
            body = "\n".join(body_lines)
            if any(BULLET_RE.match(bl) or NUMBERED_RE.match(bl) for bl in body_lines):
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
