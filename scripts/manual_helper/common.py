#!/usr/bin/env python3
"""Shared constants and helpers for the user-manual skill.

This module is imported by every other module in the package; it must NOT
import any of them (would cause circular imports).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")
HTML_VERSION_RE = re.compile(r"<!--\s*user-manual-dashboard-version:\s*(\d+)\s*-->")
SUPERPOWERS_KINDS = ("specs", "plans", "findings", "reviews")


def _template_html_path() -> Path:
    """Resolve the bundled HTML template. __init__.py is at
    manual_helper/__init__.py, so the template is one level up from the
    package directory.
    """
    return Path(__file__).resolve().parent.parent.parent / "templates" / "user-manual.html"


TEMPLATE_HTML_PATH = _template_html_path()


def now_et() -> str:
    """Current ET timestamp formatted as `YYYY-MM-DD HH:MM ET`."""
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


TEMPLATE = """# User Manual

_Maintained by the [`user-manual`](https://github.com/photoenthu/user-manual-skill) skill. Generated and updated from the project's `docs/superpowers/` artifacts. Re-run the skill after writing new specs / plans / findings / reviews to fold them in._

> **Manual status:** scaffold only. Run the `user-manual` skill to populate this file from the project's superpowers artifacts.

## 文档说明

_Will be populated by the skill on its first real run._

## 读法指南

_Will be populated by the skill on its first real run._

## 目录

_Will be populated by the skill on its first real run._

## 修订历史

_Will be populated by the skill on its first real run._

## 术语表

_Will be populated by the skill on its first real run._

## 系统概述

_Will be populated by the skill on its first real run._

## 快速开始

_Will be populated by the skill on its first real run._

## 任务卡

_Will be populated by the skill on its first real run._

## 字段参考

_Will be populated by the skill on its first real run._

## 配置参考

_Will be populated by the skill on its first real run._

## 故障速查

_Will be populated by the skill on its first real run._

## 联系支持

_Will be populated by the skill on its first real run._

## 常见问题

_Will be populated by the skill on its first real run._
"""



CITATIONS_BLOCK = """## Citations

### Project artifacts

This table is the skill's idempotency ledger. Every superpowers artifact the
skill has folded into the manual appears here with a content hash. On the next
run, artifacts whose hash matches this table are skipped; new or changed
artifacts are processed.

| Path | Kind | Title | SHA256 (content) | First cited (ET) | Last seen (ET) |
|---|---|---|---|---|---|

### External references

Web pages and external docs the skill cited while fortifying the manual. Not
used for idempotency — the skill may re-fetch these on future runs to keep
elaborations current.

| URL | Title | Cited from section | Last fetched (ET) |
|---|---|---|---|
"""

# Pulled out so callers can verify the exact section header before parsing.
CITATIONS_HEADING = "## Citations"
ARTIFACTS_SUBHEADING = "### Project artifacts"
EXTERNAL_SUBHEADING = "### External references"


def now_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def init(path: Path) -> bool:
    """Create the scaffold file if missing. Returns True if it created it.

    Citations section is appended only if the project's manual-config.json
    has include_citations=true. Per SKILL.md §3 row 12 + §6, Citations is
    an internal SHA-tracking tool and is OFF by default.
    """



DEFAULT_CONFIG_LINES = [
    '{',
    '  "project": {',
    '    "name": "<your-project-name>",',
    '    "display_name": "<your-project-display-name>",',
    '    "stack": {',
    '      "frontend": "vue3",',
    '      "backend": "spring-boot",',
    '      "db": "postgresql"',
    '    },',
    '    "repo_layout": {',
    '      "frontend_root": "frontend",',
    '      "backend_root": "backend",',
    '      "docs_root": "docs"',
    '    },',
    '    "build_commands": {',
    '      "frontend_dev": "cd <frontend_root> && npm run dev",',
    '      "backend_dev_module": "cd <backend_root> && <your-backend-start-cmd> -pl {module}",',
    '      "backend_default_module": "<your-default-module>",',
    '      "backend_default_port": "<your-backend-port>",',
    '      "gateway_port": "<your-gateway-port>"',
    '    },',
    '    "deploy": {',
    '      "default_url": "<your-default-url>",',
    '      "auth": "jwt"',
    '    }',
    '  },',
    '  "business_objectives": ["创建", "查询", "修改", "删除", "审批", "导出"],',
    '  "personas_path": "docs/user-manual/personas.json",',
    '  "inputs": [',
    '    {"kind": "superpowers", "path": "docs/superpowers"},',
    '    {"kind": "frontend_pages", "path": "<frontend_root>/src/views", "include_globs": ["**/*.vue"]},',
    '    {"kind": "backend_dtos", "path": "<backend_root>", "include_globs": ["**/dto/**/*.java"]},',
    '    {"kind": "router", "path": "<frontend_root>/src/router/index.ts"}',
    '  ],',
    '  "screenshots_dir": "docs/user-manual/screenshots",',
    '  "storage": "file",',
    '  "viewer": {',
    '    "template": "docs/user-manual/skill-template/templates/user-manual.html",',
    '    "out": "docs/user-manual/user-manual.html",',
    '    "standalone_out": "docs/user-manual/user-manual-standalone.html"',
    '  }',
    '}',
    '',
]
DEFAULT_CONFIG = "\n".join(DEFAULT_CONFIG_LINES)



# Citation subheadings — extracted to common so any module that
# parses citations tables can use them without circular imports.
CITATIONS_HEADING = "## Citations"
ARTIFACTS_SUBHEADING = "### Project artifacts"
EXTERNAL_SUBHEADING = "### External references"


__all__ = [
    "ET",
    "HTML_VERSION_RE",
    "TEMPLATE_HTML_PATH",
    "SUPERPOWERS_KINDS",
    "now_et",
    "TEMPLATE",
    "CITATIONS_BLOCK",
    "DEFAULT_CONFIG_LINES",
    "DEFAULT_CONFIG",
]


# ---------- Screenshot / video path helpers (used by readiness + recording) ----------

def _domain_for_placeholder(md_file: Path, name: str) -> str:
    """Best-effort guess of the screenshots/<domain>/ subdir for a
    placeholder. Heuristic: use the markdown file's stem (e.g.
    `contract-user-manual.md` -> `contract`). Falls back to 'misc'.
    """
    stem = md_file.stem
    for suffix in ("-user-manual", "_user_manual", "-manual", "_manual"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem or "misc"


def _candidate_paths_for_placeholder(
    md_file: Path, name: str, project_root: Path
) -> list:
    """v0.3.2: for a `[SCREENSHOT: <name>]` / `[VIDEO: <name>]` placeholder
    inside `md_file`, return the list of candidate on-disk paths where
    the asset might live, in priority order. ANY of these existing
    counts as "asset present".

    Paths tried, in order:
      1. Canonical from init-skill:  <root>/docs/user-manual/screenshots/<domain>/<name>.<ext>
      2. Relative-to-md bare:        <md_dir>/<name>.<ext>
      3. Relative-to-md with dir:    <md_dir>/screenshots/<domain>/<name>.<ext>
      4. Alt relative:               <md_dir>/../screenshots/<name>.<ext>
    """
    md_dir = md_file.parent
    domain = _domain_for_placeholder(md_file, name)
    return [
        project_root / "docs" / "user-manual" / "screenshots" / domain / f"{name}.png",
        md_dir / f"{name}.png",
        md_dir / "screenshots" / domain / f"{name}.png",
        md_dir / ".." / "screenshots" / f"{name}.png",
    ]
