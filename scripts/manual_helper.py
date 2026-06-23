#!/usr/bin/env python3
"""Deterministic helpers for the user-manual skill.

The skill itself does the heavy lifting (reading artifacts, writing prose,
elaborating jargon, fortifying with web search) — this script handles the
few primitives that are easy to get wrong in prose:

  * `now-et`                          — current timestamp in `YYYY-MM-DD HH:MM ET`
  * `init <md-path>`                  — create the empty manual scaffold if missing
  * `init-skill [project-root]`       — one-shot bootstrap: create docs/user-manual/{manual,assets,screenshots}/,
  *                                        write manual-config.json (v2 schema with <PLACEHOLDER> values),
  *                                        hard-fail if personas.json missing. See SKILL.md section 1 + 7.
  * `validate-config [project-root]`  — validate manual-config.json + personas.json,
  *                                        business_objectives coverage >= 2, exit non-zero on errors.
  *                                        `validate-config --json` for machine-readable output.
  * `check-recording-readiness [root]` — v0.3.1: probe whether the recording
  *                                        phase (§14) can actually run (deps
  *                                        installed, dev server reachable,
  *                                        no missing screenshots). Auto-runs
  *                                        after `init-skill` and prints a
  *                                        BLOCKED banner if recording can't run.
  * `extract-tasks <spec.md> [...]`     — run scripts/extract-tasks.py over given spec files.
  * `extract-fields [--vue|--java] <p>` — run scripts/extract-fields.py.
  * `extract-routes <router-file>`      — run scripts/extract-routes.py.
  * `extract-roles <be> [<fe>]`         — run scripts/extract-roles.py.
  * `extract-openapi <openapi-file>`    — run scripts/extract-openapi.py (D3).
  * `scan-artifacts <project-root>`   — list every superpowers artifact with a
                                        sha256 of its content (JSON to stdout)
  * `parse-citations <md-path>`       — read the existing manual's Citations
                                        table and emit the path -> hash mapping
                                        as JSON
  * `fill-citation-shas <md> [root]`  — v0.3.2: cross-reference the manual's
                                        Citations with scan-artifacts and
                                        emit a corrected table with real
                                        SHA256 values. Closes the
                                        "(auto)" placeholder loop.
  * `diff-artifacts <project-root> <md-path>`
                                      — combine the two: tell the skill which
                                        artifacts are NEW (not yet cited),
                                        CHANGED (cited but content changed),
                                        UNCHANGED (skip), or MISSING (cited
                                        but file no longer on disk)
  * `html-template-version`           — print the bundled template version
  * `regenerate-html-if-stale <html-path>`
        — write the bundled HTML template to the path if the file is missing
          or its embedded version is older than the template's. No-ops
          otherwise. Prints `created` / `regenerated` / `unchanged`.
  * `write-index <html-dir> <md-path> [more-md-paths...]`
        — scan the given .md files and emit a `manual-index.json` next to
          the viewer HTML. Titles come from frontmatter `title:` or first
          H1; descriptions from frontmatter `description:`. Paths in the
          index are relative to <html-dir>, so .md files in subdirectories
          work (e.g. `fr/finance.md` — module is auto-prefixed). Prints `wrote: <path>` or
          `updated: <path>`.
  * `build-standalone <html-template> <html-out> <md-path> [more...]`
        — read <html-template>, embed each .md file inline as
          `<script type="text/markdown" data-file="..." id="md-{slug}">`,
          embed the index as a JSON script, and write to <html-out>. The
          resulting html is fully self-contained: opening via `file://`
          works without a server. Prints `wrote: <path>`.
  * `read-config`                      — print the effective manual-config.json
                                         (project-level, takes precedence over defaults).
  * `init-db`                          — apply schema.sql to the configured Postgres DB.
  * `upsert-manual <md-path>`          — push a .md file to the API (db mode).
  * `upload-asset <manual-file> <path> [--caption TEXT]`
                                      — upload an image/video to object store,
                                         register it under the manual, print
                                         the public URL + md-insert hint.
  * `record-manual <manual.md> [--generate-template <out.json>] [--apply-mapping <mapping.json>]`
                                      — v0.2.3 recording phase. Default: scan
                                         the manual for [SCREENSHOT: x] and
                                         [VIDEO: x] placeholders and report
                                         what needs recording. --generate-template:
                                         emit a recorder script template (the
                                         LLM agent fills in selectors and runs
                                         it via the recorder opt-in plugin).
                                         --apply-mapping: read a {placeholder:
                                         real_path} JSON and replace placeholders
                                         in the manual with real asset paths.
                                         See SKILL.md §14 for the full workflow.

Pure stdlib. Python 3.9+ (zoneinfo).

Invoke as `python3 manual_helper.py <subcommand> [args]`.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
HTML_VERSION_RE = re.compile(r"<!--\s*user-manual-dashboard-version:\s*(\d+)\s*-->")
TEMPLATE_HTML_PATH = Path(__file__).resolve().parent.parent / "templates" / "user-manual.html"

# The four superpowers subdirectories the skill knows about. Order matters
# only for human-readability of the scan output.
SUPERPOWERS_KINDS = ("specs", "plans", "findings", "reviews")

TEMPLATE = """# User Manual

_Maintained by the [`user-manual`](https://github.com/photoenthu/user-manual-skill) skill. Generated and updated from the project's `docs/superpowers/` artifacts. Re-run the skill after writing new specs / plans / findings / reviews to fold them in._

> **Manual status:** scaffold only. Run the `user-manual` skill to populate this file from the project's superpowers artifacts.

## Quick Start

_Will be populated by the skill on its first real run._

## Concepts and Glossary

_Will be populated by the skill on its first real run._

## Daily Usage

_Will be populated by the skill on its first real run._

## Configuration

_Will be populated by the skill on its first real run._

## Troubleshooting and FAQ

_Will be populated by the skill on its first real run._

## Architecture and Internals

_Will be populated by the skill on its first real run._

## Citations

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
    """Create the scaffold file if missing. Returns True if it created it."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return True


# ---------- Skill scaffold (project bootstrap) ----------

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


def init_skill(
    project_root: Path,
    auto_install: bool = True,
) -> dict:
    """One-shot bootstrap for a fresh project (v2 D1, v0.4.0 recorder-on).

    Creates:
      docs/user-manual/manual/             (where the .md lives)
      docs/user-manual/assets/             (where images/videos live)
      docs/user-manual/screenshots/         (per-domain screenshot dirs, v2)
      docs/user-manual/manual-config.json   (v2 schema with <PLACEHOLDER> values)
      docs/user-manual/manual-index.json    (empty starter; regenerated on each build)

    Does NOT create personas.json — that is project-specific and must be authored.
    Skips anything that already exists (no overwrites).

    Hard-fails if personas.json is missing: the skill v2 enforces personas as a
    first-class project input. See SKILL.md section 1 (file location) and
    section 7 (helper subcommands).

    v1.0.0 (BREAKING): the `allow_blocked` parameter was removed.
    The skill now requires every deliverable to contain real
    screenshots and narrated videos. There is no opt-out for
    "write a draft now, record later" — that workflow produced
    manuals with 100% broken image refs in the wild and is no
    longer supported.

    v0.4.0 (recorder-on): after scaffold, runs `check_recording_readiness()`.
    If status is RED and `auto_install=True` (default), AUTO-INSTALLS the
    missing deps (playwright pip + chromium download) so a single
    `init-skill` brings the project to "ready". If still RED after
    auto-install, this function raises `RecordingBlockedError` (the
    CLI catches it and exits 2). The LLM agent must then fix the
    environment (start dev server, install missing deps) and re-run.
    Pass `auto_install=False` for dry-run or CI environments that
    have deps via other channels.

    Returns a dict:
      {
        "created": [...],
        "skipped": [...],
        "personas_required": <path>,
        "recording_readiness": <full readiness dict>,
        "auto_install_attempted": bool,
        "auto_install_ok": bool,
      }

    Raises:
      FileNotFoundError: personas.json missing and no template.
      RecordingBlockedError: post-install readiness is RED and
        allow_blocked=False.
    """
    result = _init_skill_scaffold(project_root)
    readiness = check_recording_readiness(project_root)
    result["recording_readiness"] = readiness

    auto_install_attempted = False
    auto_install_ok = False

    if (
        auto_install
        and readiness["status"] == "red"
        and not _is_dev_server_red_only(readiness)
    ):
        # Auto-install ONLY when a "red" is due to deps we can install
        # (playwright module missing, or Chromium not downloaded). A
        # red caused solely by a missing dev server stays as-is and is
        # surfaced to the user (we can't start their app server).
        auto_install_attempted = True
        auto_install_ok = _auto_install_recorder_deps()
        if auto_install_ok:
            readiness = check_recording_readiness(project_root)
            result["recording_readiness"] = readiness

    result["auto_install_attempted"] = auto_install_attempted
    result["auto_install_ok"] = auto_install_ok

    if readiness["status"] == "red":
        raise RecordingBlockedError(
            f"recording phase is BLOCKED for {project_root}: {readiness['summary']}"
        )
    return result


class RecordingBlockedError(RuntimeError):
    """v0.4.0: raised by init_skill() when post-install readiness is RED
    CLI catches this and exits 2 so the LLM agent cannot claim
    "init done" while the project is unrecordable. v1.0.0 removed
    the previous --allow-blocked opt-out.
    """


def _is_dev_server_red_only(readiness: dict) -> bool:
    """v0.4.0: a "red" readiness is "dev-server-only" if the ONLY
    failing check is the dev-server probe AND every other check
    is OK. In that case auto-install is a no-op (we can't start
    the user's app server) and we should NOT pretend the install
    succeeded.
    """
    failing = [c for c in readiness["checks"] if c["status"] == "FAIL"]
    if not failing:
        return False
    dev_server_failures = [
        c for c in failing
        if c["name"].startswith("dev server") or
           c["name"] == "manual placeholders vs. files"
    ]
    return len(failing) == len(dev_server_failures) and len(dev_server_failures) >= 1


def _auto_install_recorder_deps() -> bool:
    """v0.4.0: best-effort auto-install of recorder deps.

    Tries:
      1. `pip install playwright`  (if module missing)
      2. `python3 -m playwright install chromium`  (if browser missing)

    Returns True if both succeed, False otherwise. Prints a one-line
    progress message per step so the user sees what's happening in
    the same stream as the rest of init-skill.
    """
    import subprocess
    # Step 1: playwright module
    try:
        import playwright  # noqa: F401
        playwright_ok = True
    except ImportError:
        playwright_ok = False
    if not playwright_ok:
        print("", file=sys.stderr)
        print("⏳ auto-installing playwright Python module...", file=sys.stderr)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0:
                print(f"  ❌ pip install playwright failed: {r.stderr[:200]}",
                      file=sys.stderr)
                return False
            print("  ✅ playwright installed", file=sys.stderr)
        except Exception as e:
            print(f"  ❌ pip install playwright errored: {e}", file=sys.stderr)
            return False
    # Step 2: chromium browser
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not (cache.exists() and any(cache.glob("chromium-*"))):
        print("⏳ downloading Chromium for Playwright (this may take a minute)...",
              file=sys.stderr)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=300,
            )
            if r.returncode != 0:
                print(f"  ❌ playwright install chromium failed: {r.stderr[:200]}",
                      file=sys.stderr)
                return False
            print("  ✅ Chromium installed", file=sys.stderr)
        except Exception as e:
            print(f"  ❌ playwright install chromium errored: {e}", file=sys.stderr)
            return False
    return True


def _init_skill_scaffold(project_root: Path) -> dict:
    """Internal: do the actual scaffold work (separate so it can be tested
    in isolation from the readiness check)."""
    root = project_root
    created, skipped = [], []
    paths = [
        root / "docs" / "user-manual",
        root / "docs" / "user-manual" / "manual",
        root / "docs" / "user-manual" / "assets",
        root / "docs" / "user-manual" / "screenshots",
    ]
    for p in paths:
        if p.exists():
            skipped.append(str(p.relative_to(root)))
        else:
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p.relative_to(root)))
    cfg = root / "docs" / "user-manual" / "manual-config.json"
    if cfg.exists():
        skipped.append(str(cfg.relative_to(root)))
    else:
        cfg.write_text(DEFAULT_CONFIG, encoding="utf-8")
        created.append(str(cfg.relative_to(root)))
    idx = root / "docs" / "user-manual" / "manual-index.json"
    if idx.exists():
        skipped.append(str(idx.relative_to(root)))
    else:
        idx.write_text(
            json.dumps({"version": 1, "generated": now_et(), "manuals": []}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        created.append(str(idx.relative_to(root)))
    # v0.2.2: when personas.json missing, scaffold from examples/personas.template.json
    # (was: hard FileNotFoundError — first-time users hit a wall).
    personas_path = root / "docs" / "user-manual" / "personas.json"
    if not personas_path.exists():
        # Try a few candidate locations for the template
        template_candidates = [
            # The user-manual skill's examples/ dir (shipped with the skill)
            Path(__file__).parent.parent / "examples" / "personas.template.json",
            # Legacy path used by older init-skill versions
            root / "docs" / "user-manual" / "skill-template" / "examples" / "personas.template.json",
        ]
        template = next((p for p in template_candidates if p.exists()), None)
        if template is None:
            raise FileNotFoundError(
                "personas.json not found at {} and no template available at:\n  {}".format(
                    personas_path, "\n  ".join(str(p) for p in template_candidates)
                )
            )
        # Scaffold: copy the template, then print a loud warning
        import shutil
        personas_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(template, personas_path)
        created.append(str(personas_path.relative_to(root)))
        # Prominent stderr warning so the user sees it
        print("=" * 70, file=sys.stderr)
        print("⚠️  personas.json was MISSING — scaffolded from template.", file=sys.stderr)
        print("    Created: {}".format(personas_path), file=sys.stderr)
        print("", file=sys.stderr)
        print("    NEXT STEP: edit personas.json to match your project's real", file=sys.stderr)
        print("    roles, then re-run `python3 -m manual_helper validate-config`.", file=sys.stderr)
        print("    (Running with the 5 default personas is fine for a first pass.)", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
    return {"created": created, "skipped": skipped, "personas_scaffolded": str(personas_path.relative_to(root))}


# ---------- Recording readiness check (v0.3.1) ----------


def check_recording_readiness(project_root: Path) -> dict:
    """Probe whether the recording phase (§14) can actually run.

    The recording phase requires: a Python `playwright` module, an
    `ffmpeg` binary on PATH, a Chromium browser downloaded for
    Playwright, and a reachable dev server (so the recorder has
    something to drive). If any of these is missing, an LLM agent
    that follows §14 will silently write placeholders and call the
    manual "done" — which the user only notices at the end.

    This function makes those gaps visible at init-time.

    Returns a dict:
      {
        "status": "green" | "yellow" | "red",
        "checks": [
          {"name": ..., "status": "OK|WARN|FAIL", "detail": ..., "fix": ...},
          ...
        ],
        "summary": "<one-line human summary>",
      }

    The status aggregation rule:
      - any FAIL → "red"   (recording CANNOT run)
      - any WARN → "yellow" (recording MIGHT work, but verify)
      - all OK   → "green" (recording is ready)

    Each individual check is wrapped in try/except so a single probe
    failing doesn't crash the others.
    """
    checks: list[dict] = []

    # 1. Playwright Python module importable
    try:
        import playwright  # noqa: F401
        checks.append({
            "name": "playwright Python module",
            "status": "OK",
            "detail": "playwright is importable",
            "fix": None,
        })
    except ImportError as e:
        checks.append({
            "name": "playwright Python module",
            "status": "FAIL",
            "detail": f"ImportError: {e}",
            "fix": ("pip install playwright  (or  pip install -e recorder/[test]  "
                   "per recorder/INSTALL.md)"),
        })

    # 2. ffmpeg on PATH
    try:
        import subprocess
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        first_line = (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else "(no output)"
        checks.append({
            "name": "ffmpeg binary",
            "status": "OK",
            "detail": first_line[:80],
            "fix": None,
        })
    except FileNotFoundError:
        checks.append({
            "name": "ffmpeg binary",
            "status": "FAIL",
            "detail": "ffmpeg not found on PATH",
            "fix": "brew install ffmpeg  (macOS)  /  sudo apt-get install -y ffmpeg  (Ubuntu)",
        })
    except subprocess.TimeoutExpired:
        checks.append({
            "name": "ffmpeg binary",
            "status": "WARN",
            "detail": "ffmpeg -version timed out (>5s) — hung?",
            "fix": "Check ffmpeg install:  ffmpeg -version",
        })
    except Exception as e:
        checks.append({
            "name": "ffmpeg binary",
            "status": "WARN",
            "detail": f"{type(e).__name__}: {e}",
            "fix": "Check ffmpeg install:  ffmpeg -version",
        })

    # 3. Playwright Chromium downloaded
    # `playwright install --dry-run` lists browsers and their status
    # without downloading; if it's not supported in the installed
    # playwright version, fall back to checking the cache dir.
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=10,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or "is already installed" not in out and "is installed" not in out:
            # Fallback: check the default cache dir
            import os
            cache_candidates = [
                Path.home() / "Library" / "Caches" / "ms-playwright",  # macOS
                Path.home() / ".cache" / "ms-playwright",                # Linux
                Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")),   # custom
            ]
            has_chromium = any(
                c.exists() and any(c.glob("chromium-*")) for c in cache_candidates if str(c)
            )
            if has_chromium:
                checks.append({
                    "name": "Playwright Chromium",
                    "status": "OK",
                    "detail": "Chromium found in playwright cache",
                    "fix": None,
                })
            else:
                checks.append({
                    "name": "Playwright Chromium",
                    "status": "FAIL",
                    "detail": "Chromium not downloaded",
                    "fix": "python3 -m playwright install chromium",
                })
        else:
            checks.append({
                "name": "Playwright Chromium",
                "status": "OK",
                "detail": "Chromium already installed (per `playwright install --dry-run`)",
                "fix": None,
            })
    except FileNotFoundError:
        checks.append({
            "name": "Playwright Chromium",
            "status": "WARN",
            "detail": "python3 -m playwright not available (playwright module missing?)",
            "fix": "pip install playwright  then  python3 -m playwright install chromium",
        })
    except subprocess.TimeoutExpired:
        checks.append({
            "name": "Playwright Chromium",
            "status": "WARN",
            "detail": "playwright install --dry-run timed out (>10s)",
            "fix": "python3 -m playwright install chromium",
        })
    except Exception as e:
        checks.append({
            "name": "Playwright Chromium",
            "status": "WARN",
            "detail": f"{type(e).__name__}: {e}",
            "fix": "python3 -m playwright install chromium",
        })

    # 4. Dev server reachable (probe common ports; this is a WARN, not FAIL,
    # because the user might use a different port or run the dev server
    # in a way our probe can't see)
    common_ports = [8080, 5173, 3000, 4200, 8000, 80]
    for port in common_ports:
        try:
            import urllib.request
            req = urllib.request.Request(f"http://localhost:{port}/", method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as resp:
                # Any HTTP response (even 4xx) means the port is alive
                checks.append({
                    "name": f"dev server :{port}",
                    "status": "OK",
                    "detail": f"HTTP {resp.status}",
                    "fix": None,
                })
        except Exception:
            # Port not reachable — don't add a check; only one port needs
            # to be alive. We add a single WARN for "no common port alive"
            # after the loop.
            pass

    if not any(c["name"].startswith("dev server") and c["status"] == "OK" for c in checks):
        checks.append({
            "name": "dev server (any common port)",
            "status": "WARN",
            "detail": (f"None of {common_ports} responded to HEAD. "
                       f"Recorder has nothing to drive if your app isn't running."),
            "fix": "Start your dev server (e.g.  cd frontend && npm run dev) and re-run this check.",
        })

    # 5. Manual has [SCREENSHOT:] placeholders without files
    # (The §14 gap that motivated this check)
    manual_dir = project_root / "docs" / "user-manual" / "manual"
    placeholder_count = 0
    missing_file_count = 0
    if manual_dir.exists():
        for md_file in manual_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            placeholders = scan_recording_placeholders(text)
            placeholder_count += len(placeholders)
            for p in placeholders:
                # v0.3.2: try multiple candidate paths instead of
                # only the canonical one. The eval agent's manuals
                # used `screenshots/<domain>/<name>.png` relative to
                # the .md file's dir (not the init-skill canonical
                # path), so v0.3.1's single-path check missed them.
                ext = ".mp4" if p["kind"] == "video" else ".png"
                candidates = _candidate_paths_for_placeholder(
                    md_file, p["name"], project_root
                )
                # Replace the default .png ext in candidates with the
                # right one for the placeholder's kind
                candidates = [c.with_suffix(ext) for c in candidates]
                if not any(c.exists() for c in candidates):
                    missing_file_count += 1
    if placeholder_count == 0:
        checks.append({
            "name": "manual placeholders vs. files",
            "status": "OK",
            "detail": "No [SCREENSHOT:]/[VIDEO:]/[AI ANNOTATE:] placeholders in the manual",
            "fix": None,
        })
    elif missing_file_count == 0:
        checks.append({
            "name": "manual placeholders vs. files",
            "status": "OK",
            "detail": f"{placeholder_count} placeholder(s), all have files on disk",
            "fix": None,
        })
    else:
        checks.append({
            "name": "manual placeholders vs. files",
            "status": "FAIL",
            "detail": (f"{placeholder_count} [SCREENSHOT:]/[VIDEO:] placeholders in the "
                       f"manual, {missing_file_count} have no file on disk. This is the "
                       f"§14 gap — recorder hasn't been run, or the mapping wasn't applied."),
            "fix": ("Run §14:  (1) start your dev server, (2) install the recorder plugin "
                    "if not yet (recorder/INSTALL.md), (3) invoke the recorder to capture "
                    "screenshots/videos, (4) run `record-manual <manual> --apply-mapping <json>` "
                    "to wire the assets in."),
        })

    # Aggregate status
    if any(c["status"] == "FAIL" for c in checks):
        overall = "red"
    elif any(c["status"] == "WARN" for c in checks):
        overall = "yellow"
    else:
        overall = "green"

    summary = {
        "green": "Recording phase is READY — deps installed, dev server up, no missing files.",
        "yellow": "Recording phase has WARNINGS — recording might work, but verify the items above.",
        "red": "Recording phase is BLOCKED — recording cannot run until the items above are fixed.",
    }[overall]

    return {
        "status": overall,
        "checks": checks,
        "summary": summary,
    }


def _domain_for_placeholder(md_file: Path, name: str) -> str:
    """Best-effort guess of the screenshots/<domain>/ subdir for a
    placeholder. Heuristic: use the markdown file's stem (e.g.
    `contract-user-manual.md` → `contract`). Falls back to 'misc'."""
    stem = md_file.stem
    # Strip common suffixes
    for suffix in ("-user-manual", "_user_manual", "-manual", "_manual"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return stem or "misc"


def _candidate_paths_for_placeholder(
    md_file: Path, name: str, project_root: Path
) -> list[Path]:
    """v0.3.2: for a `[SCREENSHOT: <name>]` / `[VIDEO: <name>]` placeholder
    inside `md_file`, return the list of candidate on-disk paths where
    the asset might live, in priority order. ANY of these existing
    counts as "asset present" (v0.3.1 only checked path #1 and
    missed all the others — that's the bug the eval exposed).

    Paths tried, in order:
      1. Canonical from init-skill:  <root>/docs/user-manual/screenshots/<domain>/<name>.<ext>
      2. Relative-to-md bare:        <md_dir>/<name>.<ext>
      3. Relative-to-md with dir:    <md_dir>/screenshots/<domain>/<name>.<ext>
         (this is what the eval agent's grc_claude2_副本 actually used —
          manual at docs/user-manual/manual/, asset at docs/user-manual/manual/screenshots/<domain>/)
      4. Alt relative:               <md_dir>/../screenshots/<name>.<ext>

    The extension defaults to .png; .mp4 is the other common one. We
    only try the extension that matches the placeholder's "kind" but
    the caller passes the right one already.
    """
    md_dir = md_file.parent
    domain = _domain_for_placeholder(md_file, name)
    return [
        project_root / "docs" / "user-manual" / "screenshots" / domain / f"{name}.png",
        md_dir / f"{name}.png",
        md_dir / "screenshots" / domain / f"{name}.png",
        md_dir / ".." / "screenshots" / f"{name}.png",
    ]


def _print_recording_readiness_banner(readiness: dict) -> None:
    """Print a one-time banner after init-skill summarizing readiness.

    The banner is printed ONLY if status is yellow or red (green is
    silent — no need to spam "all good" on every init). Each check
    gets one line, with OK/WARN/FAIL prefix and a fix hint for the
    non-OK ones.
    """
    if readiness["status"] == "green":
        return
    print("", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    badge = "🔴 BLOCKED" if readiness["status"] == "red" else "🟡 WARNING"
    print(f"{badge} — recording phase readiness check", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    for c in readiness["checks"]:
        icon = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[c["status"]]
        print(f"  {icon}  {c['name']}: {c['detail']}", file=sys.stderr)
        if c["fix"]:
            print(f"        → {c['fix']}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  {readiness['summary']}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print("  (This is informational — your manual can still be written before", file=sys.stderr)
    print("   recording. Re-run `python3 -m manual_helper check-recording-readiness`", file=sys.stderr)
    print("   any time to see the current state.)", file=sys.stderr)
    print("", file=sys.stderr)


# ---------- Config validation (v2 D1) ----------

def validate_config(project_root: Path) -> dict:
    """Validate manual-config.json + personas.json + business_objectives coverage.

    Returns a dict { ok: bool, errors: [str], warnings: [str], info: dict }.

    Hard rules (errors block validation):
      - manual-config.json exists, valid JSON, has required top-level fields
      - personas.json exists, valid JSON, has granularity + personas (>= 3)
      - Each persona has id, name, daily_tasks (>= 1)
      - business_objectives coverage: union of personas\' covers_objectives
        has >= 2 distinct values from the configured business_objectives list

    Soft rules (warnings only):
      - Personas with no covers_objectives (LLM may struggle to write tasks)
      - project.name still a <PLACEHOLDER> value
      - inputs paths still <PLACEHOLDER> values
    """
    errors, warnings, info = [], [], {}
    root = project_root

    cfg_path = root / "docs" / "user-manual" / "manual-config.json"
    personas_path = root / "docs" / "user-manual" / "personas.json"

    # ---- manual-config.json ----
    if not cfg_path.exists():
        errors.append(f"manual-config.json not found at {cfg_path}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"manual-config.json is not valid JSON: {e}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    info["config_keys"] = sorted(cfg.keys())

    required_cfg_keys = ["project", "business_objectives", "personas_path", "inputs", "storage"]
    for k in required_cfg_keys:
        if k not in cfg:
            errors.append(f"manual-config.json missing required key: {k}")

    # project sub-keys
    proj = cfg.get("project", {})
    for pk in ["name", "display_name", "stack", "build_commands", "deploy"]:
        if pk not in proj:
            errors.append(f"manual-config.json project.* missing: {pk}")
    pn = proj.get("name", "")
    if isinstance(pn, str) and pn.startswith("<your-"):
        warnings.append(f"project.name still a placeholder: {pn!r}")

    # ---- personas.json ----
    if not personas_path.exists():
        errors.append(f"personas.json not found at {personas_path}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    try:
        pdata = json.loads(personas_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"personas.json is not valid JSON: {e}")
        return {"ok": False, "errors": errors, "warnings": warnings, "info": info}

    granularity = pdata.get("granularity")
    if granularity not in ("role_only", "task_only", "role_with_tasks"):
        errors.append(
            f"personas.json granularity must be one of role_only / task_only / role_with_tasks, got {granularity!r}"
        )

    personas = pdata.get("personas", [])
    if not isinstance(personas, list) or len(personas) < 3:
        errors.append(f"personas.json must have >= 3 personas, got {len(personas)}")

    persona_ids = set()
    for i, p in enumerate(personas):
        if not isinstance(p, dict):
            errors.append(f"personas[{i}] is not an object")
            continue
        if "id" not in p or not p["id"]:
            errors.append(f"personas[{i}] missing id")
        else:
            persona_ids.add(p["id"])
        if "name" not in p or not p["name"]:
            errors.append(f"personas[{i}] missing name")
        if "daily_tasks" not in p or not isinstance(p["daily_tasks"], list) or not p["daily_tasks"]:
            errors.append(f"personas[{i}] (id={p.get('id')}) missing or empty daily_tasks")
        if "covers_objectives" not in p or not p["covers_objectives"]:
            warnings.append(
                f"personas[{i}] (id={p.get('id')}) has no covers_objectives; "
                f"LLM may not map this persona to a business objective"
            )

    # ---- business_objectives coverage ----
    business_objectives = cfg.get("business_objectives", [])
    if not business_objectives:
        errors.append("manual-config.json business_objectives must be a non-empty list")
    else:
        covered = set()
        for p in personas:
            for obj in p.get("covers_objectives", []):
                if obj in business_objectives:
                    covered.add(obj)
        if len(covered) < 2:
            errors.append(
                f"personas 覆盖的业务目标类别不足(<2),请调整 personas.json. "
                f"covered={sorted(covered)}, allowed={business_objectives}"
            )
        info["covered_objectives"] = sorted(covered)

    info["persona_ids"] = sorted(persona_ids)
    info["granularity"] = granularity

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


# ---------- Artifact scanning ----------

def _short_hash(content: bytes) -> str:
    """Truncated sha256 — full hash is overkill for citation tracking and
    bloats the table visually. 16 hex chars (64 bits) is collision-resistant
    enough for a per-project artifact set."""
    return hashlib.sha256(content).hexdigest()[:16]


def _extract_title(text: str, fallback: str) -> str:
    """Best-effort H1 extraction from a markdown file. Falls back to the
    filename stem when no H1 is found in the first ~20 lines."""
    for line in text.splitlines()[:20]:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return fallback


def scan_artifacts(project_root: Path) -> list[dict]:
    """Walk `<project-root>/docs/superpowers/{kind}/` and return one dict per
    artifact:
        {
          "path": "docs/superpowers/plans/2026-04-27-foo.md",
          "kind": "plan",
          "title": "Regime-router foundation",
          "hash": "a1b2c3d4e5f60718",
          "size": 12048
        }
    Sorted by (kind, path) for stable output across runs."""
    base = project_root / "docs" / "superpowers"
    out: list[dict] = []
    if not base.exists():
        return out
    for kind in SUPERPOWERS_KINDS:
        kind_dir = base / kind
        if not kind_dir.is_dir():
            continue
        for path in sorted(kind_dir.glob("*.md")):
            try:
                raw = path.read_bytes()
                text = raw.decode("utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(project_root).as_posix()
            out.append({
                "path": rel,
                # Singular: "plan", "spec", etc. — reads better in the citation table.
                "kind": kind.rstrip("s") if kind != "specs" else "spec",
                "title": _extract_title(text, path.stem),
                "hash": _short_hash(raw),
                "size": len(raw),
            })
    return out


# ---------- Citation parsing ----------

def _split_table_row(line: str) -> list[str]:
    """`\\|` -> literal `|` inside a cell, `|` is the column separator. Same
    convention the markdown table uses; mirrors the JS parser in the dashboard."""
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            buf.append("|")
            i += 2
            continue
        if c == "|":
            cells.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    cells.append("".join(buf))
    if cells and cells[0].strip() == "":
        cells.pop(0)
    if cells and cells[-1].strip() == "":
        cells.pop()
    return [c.strip() for c in cells]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.match(r"^:?-+:?$", c) for c in cells)


def _normalize_artifact_path(raw_path: str, manual_md_path: Path) -> str:
    """Citation rows can carry either project-root-relative
    (`docs/superpowers/...`) or markdown-file-relative (`../superpowers/...`)
    paths — both are legitimate in different markdown rendering contexts.
    For the diff/idempotency machinery, everything must come back as
    project-root-relative so it lines up with `scan_artifacts`.

    Strategy: if `raw_path` is already a forward-slash path that starts with
    `docs/` or another known top-level directory, return it as-is; otherwise
    resolve it against the manual's directory and re-express it relative to
    the manual's grandparent (the project root, since the manual lives at
    `docs/user-manual/manual/user-manual.md` by convention)."""
    if not raw_path or raw_path.startswith(("http://", "https://", "/", "#")):
        return raw_path
    if "://" in raw_path:
        return raw_path
    # Heuristic: a project-root-relative path starts with a top-level dir
    # name and never contains `..`. Pass it through untouched.
    if not raw_path.startswith(("./", "../")) and ".." not in raw_path.split("/"):
        return raw_path
    # File-relative — resolve against the manual's directory and re-base
    # on the project root.
    try:
        md_dir = manual_md_path.resolve().parent
        # The manual lives at <root>/docs/user-manual/manual/user-manual.md, so project
        # root is three parents up from the .md file
        # (root / docs / user-manual / manual / file.md).
        project_root = md_dir.parent.parent.parent
        absolute = (md_dir / raw_path).resolve()
        return absolute.relative_to(project_root).as_posix()
    except (OSError, ValueError):
        return raw_path


def parse_citations(path: Path) -> dict:
    """Read the existing manual and pull out:
        {
          "artifacts": [{path, kind, title, hash, first_cited, last_seen}, ...],
          "external":  [{url, title, section, last_fetched}, ...]
        }
    Returns empty lists for both if the file is missing or the Citations
    section isn't there yet (e.g., scaffold-only manual). All artifact
    paths are normalized to project-root-relative regardless of whether
    they were stored project-root-relative or markdown-file-relative."""
    result = {"artifacts": [], "external": []}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find the Citations section first; everything before it is irrelevant.
    cite_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == CITATIONS_HEADING:
            cite_idx = idx
            break
    if cite_idx is None:
        return result

    # Now sub-walk: find each known subheading and collect table rows under it
    # until the next `## ` (or `### `, but only if it's a sibling we don't recognize).
    sub_idx = {ARTIFACTS_SUBHEADING: None, EXTERNAL_SUBHEADING: None}
    for idx in range(cite_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("## ") and stripped != CITATIONS_HEADING:
            break  # Left the Citations section entirely.
        if stripped in sub_idx:
            sub_idx[stripped] = idx

    def _collect_rows(start_idx: int | None) -> list[list[str]]:
        if start_idx is None:
            return []
        rows: list[list[str]] = []
        seen_separator = False
        for idx in range(start_idx + 1, len(lines)):
            line = lines[idx]
            stripped = line.strip()
            if stripped.startswith("## ") or stripped.startswith("### "):
                break
            if not stripped.startswith("|"):
                continue
            cells = _split_table_row(line)
            if _is_separator_row(cells):
                seen_separator = True
                continue
            if not seen_separator:
                # This is the header row; skip it.
                continue
            rows.append(cells)
        return rows

    for cells in _collect_rows(sub_idx[ARTIFACTS_SUBHEADING]):
        if len(cells) < 6:
            continue
        path_cell, kind_cell, title_cell, hash_cell, first_cell, last_cell = cells[:6]
        # The path may be wrapped in a markdown link: `[label](path)` — recover
        # the bare path. Prefer the link target when present.
        m = re.match(r"^\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)$", path_cell)
        bare_path = m.group("target") if m else path_cell
        # Normalize either link convention back to project-root-relative.
        normalized = _normalize_artifact_path(bare_path, path)
        # The hash cell may be wrapped in inline-code backticks — strip them.
        bare_hash = hash_cell.strip("`")
        result["artifacts"].append({
            "path": normalized,
            "kind": kind_cell,
            "title": title_cell,
            "hash": bare_hash,
            "first_cited": first_cell,
            "last_seen": last_cell,
        })

    for cells in _collect_rows(sub_idx[EXTERNAL_SUBHEADING]):
        if len(cells) < 4:
            continue
        url_cell, title_cell, section_cell, fetched_cell = cells[:4]
        m = re.match(r"^\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)$", url_cell)
        bare_url = m.group("target") if m else url_cell
        result["external"].append({
            "url": bare_url,
            "title": title_cell,
            "section": section_cell,
            "last_fetched": fetched_cell,
        })

    return result


# ---------- Fill in citation SHAs from scan-artifacts (v0.3.2) ----------


def fill_citation_shas(manual_path: Path, project_root: Path) -> dict:
    """v0.3.2 (P1 #9 from eval report): the LLM agent often writes
    `(auto)` or an empty string as the SHA in the Citations table,
    because it doesn't have the real SHA256. This subcommand closes
    that loop: read the existing Citations, cross-reference with
    scan-artifacts (which has real SHAs), and emit a corrected
    table the agent just pastes in.

    Returns:
      {
        "replacements": [{"path": ..., "oldsha": ..., "newsha": ...}, ...],
        "unresolved":   [{"path": ..., "current_sha": ...}, ...],
        "markdown_table": "## Citations\n\n### Project artifacts\n| ... |"
      }

    `replacements` = citations that were updated (had a placeholder
    or stale SHA; we have a real one now).
    `unresolved`   = citations where the on-disk artifact doesn't
    exist (file path typo, or the file was deleted). The agent must
    investigate these manually.
    `markdown_table` = the corrected table fragment (human form)
    or absent if --json was used.
    """
    cited = parse_citations(manual_path)["artifacts"]
    scanned = scan_artifacts(project_root)
    scanned_by_path = {s["path"]: s for s in scanned}

    replacements: list[dict] = []
    unresolved: list[dict] = []
    for entry in cited:
        path = entry["path"]
        old_sha = entry.get("hash", "")
        scan_entry = scanned_by_path.get(path)
        new_sha: str | None = None
        if scan_entry is not None:
            new_sha = scan_entry.get("hash", "")
        else:
            # v0.3.2 fallback: scan_artifacts only walks
            # docs/superpowers/{kind}/*.md, but manuals can cite
            # arbitrary project files (docs/design/, backend/...).
            # If the cited path exists on disk, hash it directly.
            abs_path = (project_root / path).resolve()
            if abs_path.exists() and abs_path.is_file():
                try:
                    raw = abs_path.read_bytes()
                    # Full 64-char SHA (not the 16-char prefix that
                    # scan_artifacts uses for compactness in the
                    # citation table — for the fill-in we want the
                    # authoritative value).
                    new_sha = hashlib.sha256(raw).hexdigest()
                except OSError:
                    pass
        if new_sha is None:
            # File referenced in citations but not on disk (or unreadable)
            unresolved.append({"path": path, "current_sha": old_sha})
            continue
        # Only emit a replacement if the SHA actually changed (avoids
        # no-op diffs that the agent would have to inspect)
        if old_sha == new_sha:
            continue
        replacements.append({
            "path": path,
            "oldsha": old_sha,
            "newsha": new_sha,
        })

    markdown_table = _render_filled_citations_table(manual_path, replacements, unresolved)
    return {
        "replacements": replacements,
        "unresolved": unresolved,
        "markdown_table": markdown_table,
    }


def _render_filled_citations_table(
    manual_path: Path,
    replacements: list[dict],
    unresolved: list[dict],
) -> str:
    """Render a corrected Citations table fragment. Reads the original
    manual, finds the Citations section, and replaces the SHA cell
    for any path in `replacements`. Unresolved paths are left as-is
    but tagged with a stderr-style comment so the agent notices.

    If the manual has no Citations section yet (scaffold-only), this
    returns a template the agent can paste in.
    """
    if not manual_path.exists():
        return ""
    text = manual_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find the Citations section
    cite_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == CITATIONS_HEADING:
            cite_idx = idx
            break
    if cite_idx is None:
        return ""  # No citations section; nothing to fix

    # Build a lookup path -> newsha (only the ones that changed)
    path_to_new_sha = {r["path"]: r["newsha"] for r in replacements}
    unresolved_paths = {r["path"] for r in unresolved}

    # Walk the table under "### Project artifacts" and rewrite SHA cells
    in_artifacts = False
    for idx in range(cite_idx, len(lines)):
        stripped = lines[idx].strip()
        if stripped == ARTIFACTS_SUBHEADING:
            in_artifacts = True
            continue
        if in_artifacts and (stripped.startswith("## ") or stripped.startswith("### ")):
            break  # Left the artifacts subtable
        if not in_artifacts:
            continue
        if not stripped.startswith("|"):
            continue
        # Try to identify a path on this row and rewrite its SHA
        cells = _split_table_row(lines[idx])
        if len(cells) < 4:
            continue
        path_cell = cells[0].strip()
        m = re.match(r"^\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)$", path_cell)
        bare_path = m.group("target") if m else path_cell
        # Normalize to project-root-relative for lookup
        normalized = _normalize_artifact_path(bare_path, manual_path)
        if normalized in path_to_new_sha:
            new_sha = path_to_new_sha[normalized]
            # Replace the hash cell (index 3). Preserve backticks
            # if the original had them.
            old_cell = cells[3]
            wrapped = old_cell.startswith("`") and old_cell.endswith("`")
            replacement = f"`{new_sha}`" if wrapped else new_sha
            # Rebuild the line: same number of | separators
            new_cells = cells[:3] + [replacement] + cells[4:]
            lines[idx] = "|" + "|".join(new_cells) + "|"
        elif normalized in unresolved_paths:
            # Tag unresolved with a trailing `⚠️ unresolved` so the
            # agent sees it
            if "⚠️" not in cells[3]:
                cells[3] = cells[3] + " ⚠️ unresolved"
                lines[idx] = "|" + "|".join(cells) + "|"

    return "\n".join(lines[cite_idx:])


def _cmd_fill_citation_shas(args: list[str]) -> int:
    """v0.3.2 CLI: emit the corrected Citations table with real SHAs."""
    # Filter out flag args before counting positionals
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) < 1 or len(positional) > 2:
        print("usage: manual_helper.py fill-citation-shas [--json] <manual.md> [project-root]",
              file=sys.stderr)
        return 2
    manual_path = Path(positional[0])
    project_root = Path(positional[1]) if len(positional) == 2 else _infer_project_root(manual_path)
    if not manual_path.exists():
        print(f"error: {manual_path} not found", file=sys.stderr)
        return 1
    result = fill_citation_shas(manual_path, project_root)
    if "--json" in args:
        # Drop the markdown_table from JSON (it's noisy for machines)
        out = {k: v for k, v in result.items() if k != "markdown_table"}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not result["replacements"] and not result["unresolved"]:
            print("OK: all citation SHAs are already up-to-date.")
            return 0
        print(f"=== Citation SHA Fill-In ({manual_path}) ===")
        print()
        if result["replacements"]:
            print(f"  Replaced {len(result['replacements'])} placeholder/stale SHAs:")
            for r in result["replacements"]:
                old = r["oldsha"] or "(empty)"
                print(f"    {r['path']}")
                print(f"      {old!r}  →  {r['newsha'][:16]}...")
        if result["unresolved"]:
            print()
            print(f"  Unresolved ({len(result['unresolved'])} cited paths not on disk):")
            for u in result["unresolved"]:
                print(f"    {u['path']}  (current SHA: {u['current_sha']!r})")
        print()
        print("--- Corrected Citations table (paste into your manual) ---")
        print(result["markdown_table"])
    return 0


def _infer_project_root(manual_path: Path) -> Path:
    """Best-effort: if the manual is at docs/user-manual/manual/*.md,
    assume project_root is the cwd. Otherwise return cwd as-is."""
    return Path.cwd()


# ---------- Diff: which artifacts need processing on this run? ----------

def diff_artifacts(project_root: Path, manual_path: Path) -> dict:
    """Compare on-disk superpowers artifacts against the manual's existing
    citation table. Returns four buckets:
        {
          "new":       [scan_entry, ...],   # not in citations at all
          "changed":   [scan_entry, ...],   # cited but hash changed
          "unchanged": [scan_entry, ...],   # cited and hash matches (skip)
          "missing":   [citation_entry, ...]  # cited but file is gone
        }
    Each scan_entry has the same shape as `scan-artifacts` output. Missing
    entries are the citation rows themselves (no on-disk presence)."""
    scanned = scan_artifacts(project_root)
    cited = parse_citations(manual_path)["artifacts"]
    cited_by_path = {c["path"]: c for c in cited}
    scanned_paths = {s["path"] for s in scanned}

    new: list[dict] = []
    changed: list[dict] = []
    unchanged: list[dict] = []
    for entry in scanned:
        prior = cited_by_path.get(entry["path"])
        if prior is None:
            new.append(entry)
        elif prior["hash"] != entry["hash"]:
            changed.append(entry)
        else:
            unchanged.append(entry)

    missing = [c for c in cited if c["path"] not in scanned_paths]

    return {"new": new, "changed": changed, "unchanged": unchanged, "missing": missing}


# ---------- HTML template versioning (mirrors product-backlog skill) ----------

def _read_html_version(text: str) -> int | None:
    match = HTML_VERSION_RE.search(text)
    return int(match.group(1)) if match else None


def html_template_version() -> int:
    if not TEMPLATE_HTML_PATH.exists():
        raise FileNotFoundError(
            f"bundled HTML template missing at {TEMPLATE_HTML_PATH}"
        )
    version = _read_html_version(TEMPLATE_HTML_PATH.read_text(encoding="utf-8"))
    if version is None:
        raise ValueError(
            f"template at {TEMPLATE_HTML_PATH} has no "
            f"<!-- user-manual-dashboard-version: N --> marker"
        )
    return version


def html_on_disk_version(html_path: Path) -> int:
    """Read the version marker from a user-generated HTML file on disk.

    Mirrors html_template_version() but for the file the user/skill wrote
    (e.g. <project>/docs/user-manual/user-manual.html), not the bundled
    template. Use to decide whether regenerate_html_if_stale() will copy.

    Raises FileNotFoundError if html_path is missing, ValueError if the file
    exists but has no version marker.
    """
    if not html_path.exists():
        raise FileNotFoundError(f"html file not found: {html_path}")
    version = _read_html_version(html_path.read_text(encoding="utf-8"))
    if version is None:
        raise ValueError(
            f"{html_path} has no <!-- user-manual-dashboard-version: N --> marker"
        )
    return version


def regenerate_html_if_stale(html_path: Path) -> str:
    template_version = html_template_version()
    html_path.parent.mkdir(parents=True, exist_ok=True)

    if not html_path.exists():
        shutil.copyfile(TEMPLATE_HTML_PATH, html_path)
        return "created"

    existing_version = _read_html_version(html_path.read_text(encoding="utf-8"))
    if existing_version is None or existing_version < template_version:
        shutil.copyfile(TEMPLATE_HTML_PATH, html_path)
        return "regenerated"

    return "unchanged"


# ---------- CLI ----------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML-ish frontmatter (--- ... ---) from body. Returns (meta, body).
    Tolerant: if no frontmatter, returns ({}, text).
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _extract_title_from_md(text: str, fallback: str) -> str:
    """Title resolution order: frontmatter title: > first H1 > filename fallback."""
    meta, body = _parse_frontmatter(text)
    if meta.get("title"):
        return meta["title"]
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def write_index(html_dir: Path, md_paths: list[Path]) -> Path:
    """Write manual-index.json into html_dir. Returns the path written."""
    manuals = []
    for p in md_paths:
        if not p.exists():
            print(f"warn: {p} does not exist, skipping", file=sys.stderr)
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        meta, _ = _parse_frontmatter(text)
        rel = p.resolve().relative_to(html_dir.resolve())
        # Use forward slashes for web-safety
        rel_str = str(rel).replace(os.sep, "/")
        title = meta.get("title") or _extract_title_from_md(text, p.stem)
        manuals.append({
            "file": rel_str,
            "title": title,
            "module": meta.get("module", ""),
            "description": meta.get("description", ""),
            "order": int(meta["order"]) if meta.get("order", "").isdigit() else 999,
        })
    manuals.sort(key=lambda m: (m["order"], m["title"]))
    out = {
        "version": 1,
        "generated": now_et(),
        "manuals": manuals,
    }
    out_path = html_dir / "manual-index.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def _slugify_for_id(name: str) -> str:
    """Make a safe DOM id from a filename. e.g. '财务-使用手册.md' -> 'md-xn--wgv4a9ih6f'."""
    import re as _re
    import unicodedata
    # Try to keep ASCII by NFKD-normalizing and dropping non-ASCII
    base = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    nfkd = unicodedata.normalize("NFKD", base)
    ascii_form = nfkd.encode("ascii", "ignore").decode("ascii")
    safe = _re.sub(r"[^A-Za-z0-9_-]", "-", ascii_form).strip("-")
    if not safe:
        # Pure non-ASCII: just hex-encode the original
        safe = "x" + "".join(f"{ord(c):x}" for c in base)[:32]
    return safe



def _convert_video_links_to_html(text: str) -> str:
    """v1.0.1: convert markdown `[VIDEO: title](path.mp4)` to
    a playable HTML5 `<video controls>` element. Mirrors the
    runtime `convertVideoLinksInMd()` in templates/user-manual.html
    so that build-standalone output contains the <video> tag
    literally (no JS required to see the player).
    """
    import re as _re
    pat = _re.compile(
        r'\[VIDEO:\s*([^\]]+)\]\(([^)\s]+\.(?:mp4|webm|mov))'
        r'(\s+"[^"]*")?\)',
        _re.IGNORECASE,
    )
    def _sub(m):
        alt = m.group(1).replace('"', "&quot;")
        src = m.group(2)
        return (
            '<video controls preload="metadata" playsinline '
            'style="max-width:100%;height:auto;display:block;margin:8px 0">'
            f'<source src="{src}" type="video/mp4">'
            '\u672a\u652f\u6301\u89c6\u9891\u6807\u7b7e'
            '</video>'
        )
    return pat.sub(_sub, text)



def _inline_assets_to_data_urls(text, md_path):
    """v1.0.1: for build_standalone output (file:// mode), inline
    all referenced PNG / MP4 / JPG files as base64 `data:` URLs so
    the rendered HTML works when double-clicked (browsers refuse
    to load relative-path images in file:// mode for security).
    """
    import re as _ire, base64
    md_dir = md_path.parent
    IMG_EXTS = ("png", "jpg", "jpeg", "gif", "webp")
    VID_EXTS = ("mp4", "webm", "mov")
    ALL_EXTS = IMG_EXTS + VID_EXTS

    def _resolve(rel_path):
        if rel_path.startswith(("data:", "http://", "https://", "#")):
            return None
        clean = rel_path.split("?")[0].split("#")[0]
        if not any(clean.lower().endswith("." + e) for e in ALL_EXTS):
            return None
        candidates = [
            md_dir / clean,
            md_dir / "screenshots" / Path(clean).name,
            md_dir / "videos" / Path(clean).name,
            md_dir / "assets" / Path(clean).name,
        ]
        for c in candidates:
            try:
                resolved = c.resolve()
            except OSError:
                continue
            if resolved.exists() and resolved.is_file():
                try:
                    data = resolved.read_bytes()
                except OSError:
                    continue
                if clean.lower().endswith(".png"):
                    mime = "image/png"
                elif clean.lower().endswith((".jpg", ".jpeg")):
                    mime = "image/jpeg"
                elif clean.lower().endswith(".gif"):
                    mime = "image/gif"
                elif clean.lower().endswith(".webp"):
                    mime = "image/webp"
                elif clean.lower().endswith(".mp4"):
                    mime = "video/mp4"
                elif clean.lower().endswith(".webm"):
                    mime = "video/webm"
                else:
                    mime = "video/quicktime"
                return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
        return None

    # 1) Markdown image refs: ![alt](path)
    def _md(m):
        prefix_b, alt, paren_b, src, paren_e = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        )
        data_url = _resolve(src)
        if data_url is None:
            return m.group(0)
        return prefix_b + alt + paren_b + data_url + paren_e
    text = _ire.sub(
        r"(!\[)([^\]]*)(\]\()([^\s)]+)(\))",
        _md, text,
    )

    # 2) Tag refs: <source src="path">, <video src="path">, <img src="path">
    def _tag(m):
        full = m.group(0)
        sm = _ire.search(r'src="([^"]+)"', full)
        if not sm:
            return full
        src = sm.group(1)
        data_url = _resolve(src)
        if data_url is None:
            return full
        return full.replace('src="' + src + '"', 'src="' + data_url + '"')
    text = _ire.sub(
        r"<(?:source|video|img)\b[^>]*?\bsrc=\"[^\"]+\"[^>]*>",
        _tag, text,
    )

    # 3) v1.0.2 fix: [VIDEO: title](path.mp4) markdown refs. The template
    # converts these to <video><source src="path"> at runtime in the
    # browser, AFTER the inliner runs. If we don't catch them here, the
    # resulting HTML has <source src="path.mp4"> with a relative path
    # that file:// refuses to load → video shows as broken player.
    def _md_video(m):
        prefix_b, alt, paren_b, src, paren_e = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        )
        data_url = _resolve(src)
        if data_url is None:
            return m.group(0)
        return prefix_b + alt + paren_b + data_url + paren_e
    text = _ire.sub(
        r"(\[VIDEO:\s*)([^\]]*)(\]\()([^\s)]+\.(?:mp4|webm|mov))(\))",
        _md_video, text,
    )
    return text


def build_standalone(html_template_path: Path, html_out_path: Path, md_paths: list[Path]) -> Path:
    """Read the html template, inline all .md files as <script> blocks, write out.

    The output html reads from the inline <script> blocks first (so file:// works),
    falling back to fetch() (so it still works under HTTP if you want to add more
    manuals later).
    """
    html = html_template_path.read_text(encoding="utf-8")
    # Preserve whatever version the template has — don't force a number here,
    # that would silently regress the version on every build.
    # Insert inline markdown blocks right after <body> opens — must be BEFORE
    # the IIFE boot script that reads them. <body> opening tag is more
    # reliable than </head> across templating variations.
    body_open = html.find("<body>")
    if body_open < 0:
        body_open = html.find("<body ")
    if body_open < 0:
        raise ValueError("html template has no <body>")
    body_open_end = html.find(">", body_open) + 1  # position right after >

    inline_blocks = []
    for p in md_paths:
        if not p.exists():
            print(f"warn: {p} not found, skipping", file=sys.stderr)
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        # v1.0.1: pre-render [VIDEO: x](path) -> <video> so the
        # build-standalone output has the <video> tag literally
        # (no JS needed to see the player). Mirrors the runtime
        # convertVideoLinksInMd() in the viewer template.
        text = _convert_video_links_to_html(text)
        # v1.0.1: inline PNG/MP4 references as data: URLs so the
        # standalone .html works under file:// (browsers block
        # relative-path images there). Runs AFTER video conversion
        # so <source src=...> tags from _convert_video_links_to_html
        # also get inlined.
        text = _inline_assets_to_data_urls(text, p)
        # Escape </script> to avoid breaking out of the script tag
        text = text.replace("</script>", "<\\/script>")
        sid = _slugify_for_id(p.name)
        rel = p.name  # already relative to html dir (caller responsibility)
        inline_blocks.append(
            f'<script type="text/markdown" data-file="{rel}" id="md-{sid}">\n'
            f'{text}\n'
            f'</script>'
        )

    # Insert right after <body>, before the IIFE script
    insertion = "\n<!-- INLINE: standalone build, do not edit by hand -->\n" + "\n".join(inline_blocks) + "\n"
    html = html[:body_open_end] + insertion + html[body_open_end:]

    html_out_path.write_text(html, encoding="utf-8")
    return html_out_path




# ---------- Extract subcommand wrappers (v2 D2) ----------

def cmd_extract_tasks(args):
    """extract-tasks <spec.md> [...]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-tasks.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_fields(args):
    """extract-fields [--vue|--java] <path> [...]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-fields.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_routes(args):
    """extract-routes <router-file>"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-routes.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_roles(args):
    """extract-roles <backend-root> [<frontend-root>]"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-roles.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_extract_openapi(args):
    """extract-openapi <openapi.yaml-or-json>"""
    import subprocess
    script = Path(__file__).resolve().parent / "extract-openapi.py"
    r = subprocess.run([sys.executable, str(script)] + list(args), capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def cmd_record_manual(args):
    """v0.2.3: recording phase helper. See SKILL.md §14.

    Usage:
      record-manual <manual.md>                           # scan + report placeholders
      record-manual <manual.md> --generate-template <out>  # emit recorder script template
      record-manual <manual.md> --apply-mapping <json>     # replace placeholders with real paths

    Placeholder syntax (v1 standard):
      [SCREENSHOT: <name>.png]
      [VIDEO: <name>.mp4]   (or [VIDEO NEEDED] / [SCREENSHOT NEEDED] for missing)

    Mapping JSON (for --apply-mapping):
      {
        "01-list": "docs/user-manual/screenshots/sys/01-list.png",
        "demo": "docs/user-manual/screenshots/sys/demo-flow/demo-flow.mp4"
      }
    Keys are the placeholder name (without extension or brackets).
    """
    # M2 fix (v0.2.4 audit round 3): --help prints usage and exits 0
    # BEFORE the manual_path check (so "--help" is not interpreted
    # as a missing-manual path). Matches the help-flag convention
    # of the other subcommands.
    if args and args[0] in ("--help", "-h", "help"):
        print("usage: record-manual <manual.md> [--generate-template <out>] [--apply-mapping <json>]",
              file=sys.stderr)
        return 0

    if not args:
        print("usage: record-manual <manual.md> [--generate-template <out>] [--apply-mapping <json>]",
              file=sys.stderr)
        return 2
    manual_path = Path(args[0])
    if not manual_path.exists():
        print(f"error: {manual_path} not found", file=sys.stderr)
        return 1

    # Parse flags
    gen_template = None
    apply_mapping = None
    i = 1
    while i < len(args):
        if args[i] == "--generate-template" and i + 1 < len(args):
            gen_template = Path(args[i + 1])
            i += 2
        elif args[i] == "--apply-mapping" and i + 1 < len(args):
            apply_mapping = Path(args[i + 1])
            i += 2
        else:
            # M2 fix (v0.2.4 audit round 3): print the usage line on
            # the same stderr message so a user who fat-fingers a
            # flag gets recovery context (matching other subcommands
            # at line 1307, 1335, 1363).
            print(f"error: unknown arg {args[i]!r}", file=sys.stderr)
            print("usage: record-manual <manual.md> [--generate-template <out>] [--apply-mapping <json>]",
                  file=sys.stderr)
            return 2

    text = manual_path.read_text(encoding="utf-8", errors="replace")
    placeholders = scan_recording_placeholders(text)

    # --apply-mapping: replace and write back atomically
    if apply_mapping is not None:
        if not apply_mapping.exists():
            print(f"error: mapping file {apply_mapping} not found", file=sys.stderr)
            return 1
        mapping = json.loads(apply_mapping.read_text())
        new_text, replaced, missing, replaced_instances = apply_recording_mapping(text, mapping)
        # F9 fix (v0.2.4 audit): write to a temp file in the same directory
        # then atomically rename. A crash mid-write used to truncate the
        # manual to half-applied state. tmp in same dir guarantees the
        # rename is on the same filesystem (POSIX rename is atomic).
        tmp_path = manual_path.with_suffix(manual_path.suffix + ".tmp")
        tmp_path.write_text(new_text, encoding="utf-8")
        tmp_path.replace(manual_path)
        print(f"updated: {manual_path}")
        print(f"  replaced: {len(replaced)} unique mappings "
              f"({replaced_instances} placeholder instances)")
        if replaced:
            for k, v in sorted(replaced.items()):
                print(f"    [SCREENSHOT: {k}.*] / [VIDEO: {k}.*]  ->  {v}")
        if missing:
            print(f"  placeholders still missing: {len(missing)}")
            for entry in missing:
                kind_marker = entry["kind"]
                status = entry.get("status", "no_mapping")
                print(f"    [{kind_marker.upper().replace('_', ' ')}: {entry['name']}]  ({status})")
                if entry.get("reason"):
                    print(f"      reason: {entry['reason']}")
        return 0

    # Default: report
    if not placeholders:
        print(f"NO_RECORDING_NEEDED: {manual_path}")
        print(f"  scanned: 1 file, 0 [SCREENSHOT:], 0 [VIDEO:], 0 [AI ANNOTATE:] placeholders")
        return 0
    screens = [p for p in placeholders if p["kind"] == "screenshot"]
    videos = [p for p in placeholders if p["kind"] == "video"]
    ai_anns = [p for p in placeholders if p["kind"] == "ai_annotate"]
    print(f"RECORDING_NEEDED: {manual_path}")
    print(f"  screenshots: {len(screens)}")
    for p in screens:
        print(f"    [SCREENSHOT: {p['name']}.png]")
    print(f"  videos: {len(videos)}")
    for p in videos:
        print(f"    [VIDEO: {p['name']}.mp4]")
    if ai_anns:
        print(f"  ai_annotates: {len(ai_anns)}  (v0.2.4: agent-mediated, see SKILL.md §15)")
        for p in ai_anns:
            print(f"    [AI ANNOTATE: {p['name']}]")
    print()
    print("Next step (LLM agent): see SKILL.md §14 — recording phase.")
    print("  1. Ask the user for: target URL, login credentials, mode (record/screenshot-only/skip).")
    print("  2. If record/screenshot-only: invoke the recorder opt-in plugin.")
    print(f"  3. After recorder produces assets: `record-manual {manual_path} --apply-mapping <json>`")
    if ai_anns:
        print("     (also: handle pending_ai_annotations via §15)")

    # --generate-template: also emit a recorder script template
    if gen_template is not None:
        template = build_recorder_template(manual_path.stem, placeholders)
        gen_template.parent.mkdir(parents=True, exist_ok=True)
        gen_template.write_text(json.dumps(template, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        print(f"  template: {gen_template}")
    return 0


# ---------- v0.4.0: one-shot record-and-replace ----------


def cmd_check_recorder_script(args: list[str]) -> int:
    """v0.5.0: validate a recorder script JSON before running it.

    Catches the failure pattern that produced lg-contract-flow.mp4
    (4.88s of login page, 28s of looped frames): the agent fills a
    template with `<TODO: ...>` placeholders, runs the recorder anyway,
    and the recording silently misses 80% of the intended flow.

    4 checks:
      1. NO TODO PLACEHOLDERS  (FAIL if any "<TODO" string in the script)
      2. URL REACHABLE         (FAIL if --url target is not HEAD-reachable)
      3. AUTH ENV VARS SET     (FAIL if any $VAR in auth_env is unset in env)
      4. STEPS HAVE REAL CONTENT
                                (FAIL if any step has empty selector/text/url,
                                 or if video_start has no matching video_stop)

    Returns:
      0  if all 4 checks pass
      1  if any check fails (with itemized diagnostics)
      2  if the script file is missing or invalid JSON

    Usage:
      python3 -m manual_helper check-recorder-script <script.json> [--json]
    """
    if not args or args[0] in ("--help", "-h", "help"):
        print("usage: check-recorder-script <script.json> [--json]\n\n"
              "Validate a recorder script before running. Catches 4 common\n"
              "failure patterns (TODO placeholders, bad URL, unset env\n"
              "vars, incomplete steps). Returns 0/1/2 like init-skill.", file=sys.stderr)
        return 0 if args else 2

    as_json = "--json" in args
    script_arg = next((a for a in args if not a.startswith("--")), None)
    if script_arg is None:
        print("error: script.json path required", file=sys.stderr)
        return 2
    script_path = Path(script_arg)
    if not script_path.exists():
        print(f"error: {script_path} not found", file=sys.stderr)
        return 2

    # Parse
    try:
        text = script_path.read_text(encoding="utf-8")
        script = json.loads(text)
    except (json.JSONDecodeError, OSError) as e:
        print(f"error: cannot parse {script_path}: {e}", file=sys.stderr)
        return 2

    checks: list[dict] = []
    # Check 1: TODO placeholders anywhere
    todo_count = text.count("<TODO")
    checks.append({
        "name": "no TODO placeholders",
        "status": "OK" if todo_count == 0 else "FAIL",
        "detail": (f"{todo_count} <TODO> placeholders remain in the script"
                   if todo_count else "no <TODO> placeholders"),
        "fix": ("Fill every <TODO: ...> marker. Use the v0.5.0 build_recorder_template\n"
                "       to auto-fill URL/output_dir from manual-config.json, and\n"
                "       run check-recorder-script after every manual edit.") if todo_count else None,
    })

    # Check 2: URL reachable
    url = script.get("url", "")
    if not url or str(url).startswith("<"):
        checks.append({
            "name": "target URL reachable",
            "status": "FAIL",
            "detail": f"url is unset: {url!r}",
            "fix": "Set `url` to e.g. http://localhost:8080 (or whatever the dev server runs on).",
        })
    else:
        try:
            import urllib.request
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=3) as resp:
                checks.append({
                    "name": "target URL reachable",
                    "status": "OK",
                    "detail": f"{url} -> HTTP {resp.status}",
                    "fix": None,
                })
        except Exception as e:
            checks.append({
                "name": "target URL reachable",
                "status": "FAIL",
                "detail": f"{url} not reachable: {type(e).__name__}: {e}",
                "fix": ("Start your dev server (or check the port). \n"
                        "       The recorder will produce a useless video otherwise."),
            })

    # Check 3: auth_env vars all set
    import os
    auth_env = script.get("auth_env", [])
    env_refs = [v.lstrip("$") for v in auth_env if isinstance(v, str) and v.startswith("$")]
    missing = [v for v in env_refs if v not in os.environ]
    if not auth_env:
        checks.append({
            "name": "auth env vars set",
            "status": "WARN",
            "detail": "no auth_env in script; recorder will skip login if your app needs it",
            "fix": ("If the app requires login, add \"auth_env\": [\"$USER\", \"$PASS\"]\n"
                        "       and export those env vars before running."),
        })
    elif missing:
        checks.append({
            "name": "auth env vars set",
            "status": "FAIL",
            "detail": f"env var(s) unset: {missing}",
            "fix": (f"export {missing[0]}=<value> before running the recorder.\n"
                        "       Without it, the login step passes the literal string "
                        f"\"{missing[0]}\" into the form, silently fails,\n"
                        "       and the video stays on the login page forever "
                        "(this is exactly the lg-contract-flow.mp4 bug)."),
        })
    else:
        checks.append({
            "name": "auth env vars set",
            "status": "OK",
            "detail": f"all {len(env_refs)} env var(s) set: {env_refs}",
            "fix": None,
        })

    # Check 4: steps have real content + video_start/video_stop balance
    steps = script.get("steps", [])
    empty_step_count = 0
    video_starts = sum(1 for s in steps if isinstance(s, dict) and s.get("action") == "video_start")
    video_stops = sum(1 for s in steps if isinstance(s, dict) and s.get("action") == "video_stop")
    for s in steps:
        if not isinstance(s, dict):
            empty_step_count += 1
            continue
        action = s.get("action", "")
        if action in ("click", "type"):
            if not s.get("selector") or str(s.get("selector", "")).startswith("<"):
                empty_step_count += 1
        elif action in ("navigate",):
            if not s.get("url") or str(s.get("url", "")).startswith("<"):
                empty_step_count += 1
        elif action == "screenshot":
            if not s.get("name") or str(s.get("name", "")).startswith("<"):
                empty_step_count += 1
    if video_starts != video_stops:
        checks.append({
            "name": "steps have real content",
            "status": "FAIL",
            "detail": (f"video_start ({video_starts}) != video_stop ({video_stops}); "
                       f"unbalanced video sessions will cause recorder to hang or "
                       f"produce empty mp4s"),
            "fix": "Each video_start must have a matching video_stop later in the steps.",
        })
    elif empty_step_count:
        checks.append({
            "name": "steps have real content",
            "status": "FAIL",
            "detail": f"{empty_step_count} step(s) have empty or <TODO: ...> selectors / urls",
            "fix": ("Fill in selectors by inspecting the actual app in a browser.\n"
                        "       e.g. for a login form: input[name=username], button[type=submit]"),
        })
    elif not steps:
        checks.append({
            "name": "steps have real content",
            "status": "FAIL",
            "detail": "no steps at all",
            "fix": ("Add navigate -> login -> click flow -> screenshot/video steps.\n"
                        "       Use build_recorder_template to scaffold, then fill in."),
        })
    else:
        checks.append({
            "name": "steps have real content",
            "status": "OK",
            "detail": f"{len(steps)} steps, video_start/stop balanced ({video_starts}/{video_stops})",
            "fix": None,
        })

    # v0.5.1: check #5 — NARRATION COVERAGE. Without this, an LLM that
    # forgets the `narration` field on video_stop steps gets silent
    # videos with no feedback. Surface the gap at preflight time.
    video_stops_with_narration = [
        s for s in steps
        if s.get("action") == "video_stop" and s.get("narration")
    ]
    video_stops_all = [s for s in steps if s.get("action") == "video_stop"]
    if not video_stops_all:
        checks.append({
            "name": "narration coverage",
            "status": "OK",
            "detail": "no video sessions in this script (n/a)",
            "fix": None,
        })
    elif len(video_stops_with_narration) == len(video_stops_all):
        checks.append({
            "name": "narration coverage",
            "status": "OK",
            "detail": f"all {len(video_stops_all)} video session(s) have narration[]",
            "fix": None,
        })
    elif len(video_stops_with_narration) == 0:
        # The most common silent-failure case. Loud FAIL.
        missing = [s.get("name", f"<step-{steps.index(s)}>") for s in video_stops_all]
        checks.append({
            "name": "narration coverage",
            "status": "FAIL",
            "detail": (f"all {len(video_stops_all)} video session(s) are missing the "
                       f"`narration` field; output videos will be SILENT. "
                       f"Missing: {missing}"),
            "fix": ("Add a `narration` list (one string per task-card step) to each "
                    "video_stop step. One entry per task-card step. The recorder will "
                    "synthesize each segment with edge-tts and mux the audio onto the "
                    "mp4. If you genuinely want silent videos, pass --strict-narration=off "
                    "(future) or remove the video sessions entirely."),
        })
    else:
        missing = [s.get("name", f"<step-{steps.index(s)}>") for s in video_stops_all
                   if not s.get("narration")]
        checks.append({
            "name": "narration coverage",
            "status": "WARN",
            "detail": (f"{len(video_stops_all) - len(video_stops_with_narration)} of "
                       f"{len(video_stops_all)} video session(s) missing narration; "
                       f"will be silent: {missing}"),
            "fix": ("Add `narration: [...]` to each video_stop step listed above."),
        })

    if as_json:
        print(json.dumps({"file": str(script_path), "checks": checks}, ensure_ascii=False, indent=2))
    else:
        # Human output
        badge_map = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}
        print(f"=== Recorder Script Check ({script_path.name}) ===")
        for c in checks:
            icon = badge_map[c["status"]]
            print(f"  {icon}  {c['name']}: {c['detail']}")
            if c["fix"]:
                # Indent multi-line fixes
                for line in c["fix"].splitlines():
                    print(f"        {line}")
        failed = [c for c in checks if c["status"] == "FAIL"]
        warned = [c for c in checks if c["status"] == "WARN"]
        print()
        if failed:
            print(f"❌ {len(failed)} check(s) FAILED. Fix the items above and re-run.")
        elif warned:
            print(f"⚠️  {len(warned)} check(s) WARN. Recording will proceed but may be incomplete.")
        else:
            print("✅ all 4 checks passed — script is ready to run.")

    return 1 if any(c["status"] == "FAIL" for c in checks) else 0


def cmd_record_and_replace(args: list[str]) -> int:
    """v0.4.0: one-shot record + apply-mapping, replacing the 5-step
    manual §14 workflow with a single command.

    The LLM agent runs:
        python3 -m manual_helper record-and-replace <manual.md> \
            --script <recorder-script.json> [--dry-run]

    What this does:
        1. Sanity-check: --script exists, manual exists, recorder deps OK
           (or auto-install via init-skill). Pre-flight check that:
             - recorder_plugin is importable
             - playwright + chromium installed
             - target URL in the script is reachable (HEAD probe)
             - login env vars are set (if script references them)
        2. Run the recorder:  python3 -m recorder_plugin.cli run <script>
        3. Auto-build a mapping JSON from the recorder's output (matches
           step name → screenshots/<domain>/<name>.png/.mp4 by the
           recorder's standard naming convention).
        4. Apply the mapping:  record-manual <manual> --apply-mapping <m>
        5. Run validate-output.py --unique to surface any duplicate-
           content screenshots (catches the §13 eval failure pattern).
        6. Re-run validate (default 7 checks + the v0.4.0 8th).

    Returns:
        0  if all assets recorded and applied (validate passes)
        1  if recording succeeded but validate still fails (mapping
            didn't catch every placeholder; LLM agent must decide
            whether to re-record or accept the gap)
        2  if recorder itself failed (deps missing, URL unreachable, etc.)
        3  if --dry-run (no recording actually happened; just the
            pre-flight + mapping preview)

    The point: by collapsing §14's 5 manual steps into 1, the LLM
    agent cannot "forget step 3" or "stop after step 2" — the single
    command either runs all of them or none, with one exit code.
    """
    # --help / no args
    if not args or args[0] in ("--help", "-h", "help"):
        print(
            "usage: record-and-replace <manual.md> [--script <recorder.json>]\n"
            "       [--auto-generate-script] [--dry-run] [--skip-validate]\n"
            "       [--skip-viewer-regen]\n"
            "       [--skip-script-check] [--target-url URL]\n\n"
            "One-shot: pre-flight check -> run recorder -> apply mapping ->\n"
            "validate. Replaces the 5-step SKILL.md §14 workflow.\n"
            "v0.5.0: --auto-generate-script builds a v0.5.0 template from\n"
            "the manual + manual-config.json when --script is omitted.\n"
            "Runs check-recorder-script before recording (skip with --skip-script-check).\n"
            "Auto-regenerates the viewer (user-manual.html) at the end if the\n"
            "shipped template is newer (skip with --skip-viewer-regen).",
            file=sys.stderr,
        )
        return 0 if args else 2

    # Parse flags
    manual_path = None
    script_path = None
    dry_run = False
    skip_validate = False
    skip_viewer_regen = False
    target_url = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--script" and i + 1 < len(args):
            script_path = Path(args[i + 1])
            i += 2
        elif a == "--dry-run":
            dry_run = True
            i += 1
        elif a == "--skip-validate":
            skip_validate = True
            i += 1
        elif a == "--target-url" and i + 1 < len(args):
            target_url = args[i + 1]
            i += 2
        elif a == "--auto-generate-script":
            # v0.5.0: this is a no-op for the parser; the post-parse
            # block checks argv directly for it.
            i += 1
        elif a == "--skip-script-check":
            # v0.5.0: same as above — parsed by name later.
            i += 1
        elif a == "--skip-viewer-regen":
            # v0.5.0: opt out of auto-regenerating user-manual.html
            # after record-and-replace. For CI / pinned-viewer envs.
            skip_viewer_regen = True
            i += 1
        elif a == "--allow-blocked":
            # v1.0.0: BREAKING. --allow-blocked removed.
            print("ERROR: --allow-blocked was removed in v1.0.0.", file=sys.stderr)
            print("  The skill now requires real screenshots and videos.", file=sys.stderr)
            print("  Start the dev server (or fix the recorder deps) and re-run.", file=sys.stderr)
            return 2
        elif not a.startswith("--") and manual_path is None:
            manual_path = Path(a)
            i += 1
        else:
            print(f"error: unknown arg {a!r}", file=sys.stderr)
            return 2

    if manual_path is None or not manual_path.exists():
        print(f"error: manual not found: {manual_path}", file=sys.stderr)
        return 2
    auto_gen = "--auto-generate-script" in args
    if script_path is None:
        if auto_gen:
            # v0.5.0: no --script given; generate one from the manual +
            # project_root (= cwd), then continue with that script.
            project_root = Path.cwd()
            text = manual_path.read_text(encoding="utf-8", errors="replace")
            placeholders = scan_recording_placeholders(text)
            template = build_recorder_template(
                manual_path.stem, placeholders,
                manual_path=manual_path, project_root=project_root,
            )
            script_path = manual_path.parent / f"{manual_path.stem}.recorder.json"
            script_path.write_text(
                json.dumps(template, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"  auto-generated script: {script_path}", file=sys.stderr)
        else:
            print(f"error: --script required (or pass --auto-generate-script to create one)",
                  file=sys.stderr)
            return 2
    if not script_path.exists():
        print(f"error: --script not found: {script_path}", file=sys.stderr)
        return 2
    # v0.5.0: always run check-recorder-script before recording. If it
    # returns 1, surface the failures but DO NOT block — some projects
    # have intentionally-broken dev servers (CI / prod-only). The user
    # can opt out with --skip-script-check.
    if not dry_run and "--skip-script-check" not in args:
        check_rc = cmd_check_recorder_script([str(script_path)])
        if check_rc == 1:
            print("", file=sys.stderr)
            print("  ⚠️  recorder script has issues (see above). Continuing anyway.",
                  file=sys.stderr)
            print("  (pass --skip-script-check to silence this)", file=sys.stderr)

    print(f"=== record-and-replace: {manual_path.name} ===", file=sys.stderr)
    print(f"  script: {script_path}", file=sys.stderr)
    if dry_run:
        print("  mode: DRY-RUN (no recording, no writes)", file=sys.stderr)

    # v0.5.0: auto-regenerate <proj>/docs/user-manual/user-manual.html
    # BEFORE pre-flight, so the upgrade happens even if the recorder deps
    # are missing (the LLM agent is running on a fresh container). The
    # user gets the latest viewer no matter what the recorder does.
    if skip_viewer_regen:
        print("  viewer: auto-regen skipped (--skip-viewer-regen)", file=sys.stderr)
    else:
        try:
            html_root = None
            for parent in manual_path.parents:
                if parent.name == "user-manual" and (parent / "manual").is_dir():
                    html_root = parent
                    break
                if parent.name == "docs" and (parent / "user-manual").is_dir():
                    html_root = parent / "user-manual"
                    break
            if html_root is None:
                html_root = manual_path.parent
            html_target = html_root / "user-manual.html"
            regen_status = regenerate_html_if_stale(html_target)
            if regen_status == "regenerated":
                print(f"  viewer: regenerated {html_target} (template v{html_template_version()})", file=sys.stderr)
            elif regen_status == "created":
                print(f"  viewer: created {html_target} (template v{html_template_version()})", file=sys.stderr)
        except (FileNotFoundError, ValueError, OSError) as e:
            print(f"  viewer: auto-regen skipped ({type(e).__name__}: {e})", file=sys.stderr)

    # Step 1: pre-flight
    preflight_ok, preflight_msgs = _preflight_recorder(
        script_path, target_url=target_url,
    )
    for line in preflight_msgs:
        print(f"  {line}", file=sys.stderr)
    if not preflight_ok:
        # v1.0.0: hard FAIL. v0.5.4's --allow-blocked branch was removed
        # because in practice the LLM agent would always pass it and
        # deliver a draft. Start the dev server, fix deps, or check the
        # script's --target-url, then re-run.
        print("", file=sys.stderr)
        print("❌ pre-flight FAILED — fix the issues above and retry.", file=sys.stderr)
        print("   (v1.0.0 no longer supports a draft-only deliverable)", file=sys.stderr)
        return 2

    if dry_run:
        # Build the mapping preview without actually recording
        text = manual_path.read_text(encoding="utf-8", errors="replace")
        placeholders = scan_recording_placeholders(text)
        domain = _domain_for_placeholder(manual_path, "")
        preview = {
            "_comment": "dry-run preview; no actual files exist yet",
            **{p["name"]: f"screenshots/{domain}/{p['name']}.png"
               if p["kind"] == "screenshot"
               else f"videos/{domain}/{p['name']}.mp4"
               for p in placeholders},
        }
        print("", file=sys.stderr)
        print("  mapping preview (would be created on real run):", file=sys.stderr)
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return 3

    # Step 2: run the recorder
    print("", file=sys.stderr)
    print("⏳ running recorder (this may take a while)...", file=sys.stderr)
    recorder_rc = _run_recorder(script_path)
    if recorder_rc != 0:
        print(f"❌ recorder exited {recorder_rc}", file=sys.stderr)
        return 2

    # Step 3: build mapping from recorder output
    output_dir = script_path.parent / f"{manual_path.stem}_recording"
    if not output_dir.exists():
        # Try sibling to script
        output_dir = script_path.parent
    mapping = _build_mapping_from_recorder_output(output_dir, manual_path)
    if not mapping:
        print("⚠️  recorder ran but no assets found in", output_dir,
              file=sys.stderr)
        print("  check the recorder script's `output_dir` field", file=sys.stderr)
        return 2

    # Step 4: apply mapping
    mapping_path = output_dir / "mapping.json"
    mapping_path.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  mapping: {mapping_path} ({len(mapping)} entries)", file=sys.stderr)

    apply_rc = _apply_mapping_to_manual(manual_path, mapping_path)
    if apply_rc != 0:
        print(f"❌ --apply-mapping exited {apply_rc}", file=sys.stderr)
        return 1

    # Step 5+6: validate (with --unique to catch duplicate-content)
    if skip_validate:
        print("", file=sys.stderr)
        print("✅ record-and-replace complete (validation skipped).", file=sys.stderr)
        return 0
    print("", file=sys.stderr)
    print("⏳ running validate-output.py --unique ...", file=sys.stderr)
    rc = _run_validate(manual_path, unique=True)
    if rc == 0:
        print("", file=sys.stderr)
        print("✅ record-and-replace complete; manual validates clean.", file=sys.stderr)
    else:
        print("", file=sys.stderr)
        print("⚠️  recording complete but validate reported issues.", file=sys.stderr)
        print("   re-run `manual_helper record-manual <md>` to see what\'s missing.", file=sys.stderr)
    return rc


def _preflight_recorder(script_path: Path, target_url: str | None) -> tuple[bool, list[str]]:
    """v0.4.0: 4 pre-flight checks before invoking the recorder.

    Returns (ok, [human-readable lines]). Each line is prefixed with
    an icon by the caller.
    """
    msgs: list[str] = []
    ok = True

    # Check 1: recorder_plugin importable
    try:
        from recorder_plugin import __version__ as rver
        msgs.append(f"✅ recorder_plugin {rver} importable")
    except ImportError:
        msgs.append("❌ recorder_plugin NOT importable")
        msgs.append("      → pip install -e recorder/[test]  (or  pip install -e ~/.agents/skills/user-manual/recorder)")
        ok = False

    # Check 2: playwright module
    try:
        import playwright  # noqa: F401
        msgs.append("✅ playwright importable")
    except ImportError:
        msgs.append("❌ playwright NOT importable")
        msgs.append("      → pip install playwright")
        ok = False

    # Check 3: chromium downloaded
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if cache.exists() and any(cache.glob("chromium-*")):
        msgs.append("✅ Playwright Chromium installed")
    else:
        msgs.append("❌ Playwright Chromium NOT installed")
        msgs.append("      → python3 -m playwright install chromium")
        ok = False

    # Check 4: ffmpeg
    import subprocess
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        msgs.append("✅ ffmpeg on PATH")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        msgs.append("❌ ffmpeg NOT on PATH")
        msgs.append("      → brew install ffmpeg  (macOS)")
        ok = False

    # Check 5: target URL reachable (if given)
    if target_url:
        try:
            import urllib.request
            req = urllib.request.Request(target_url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as resp:
                msgs.append(f"✅ target URL reachable: {target_url} (HTTP {resp.status})")
        except Exception as e:
            msgs.append(f"⚠️  target URL NOT reachable: {target_url} ({type(e).__name__})")
            msgs.append("      → start your dev server first, then retry")
            # URL-unreachable is a WARN, not a FAIL: the user might
            # know they're going to start the server in a sec.

    # Check 6: script references $ENV vars that are unset
    try:
        import os, re
        script_text = script_path.read_text(encoding="utf-8")
        env_refs = re.findall(r"\$([A-Z_][A-Z0-9_]*)", script_text)
        missing_env = [v for v in env_refs if v not in os.environ]
        if missing_env:
            missing_env_str = ", ".join("$" + v for v in missing_env)
            msgs.append(f"❌ script references {missing_env_str} but env var(s) unset")
        elif env_refs:
            msgs.append(f"✅ all {len(set(env_refs))} env var ref(s) in script are set")
    except Exception:
        pass  # script parse is best-effort

    return ok, msgs


def _run_recorder(script_path: Path) -> int:
    """v0.4.0: invoke recorder in a subprocess, stream stderr to ours."""
    import subprocess
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "recorder_plugin.cli", "run", str(script_path)],
            timeout=600,
        )
        return proc.returncode
    except subprocess.TimeoutExpired:
        print("  ❌ recorder timed out (>600s)", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"  ❌ recorder errored: {e}", file=sys.stderr)
        return 1


def _build_mapping_from_recorder_output(output_dir: Path, manual_path: Path) -> dict:
    """v0.4.0: scan the recorder's output dir for screenshots and
    videos; build a mapping {step_name: relative_path} that
    record-manual --apply-mapping can consume.

    Convention: recorder writes PNGs and MP4s to output_dir directly
    (or in subdirs). We walk all of them, use the filename stem
    (without extension) as the mapping key, and build a path
    relative to the manual's directory.
    """
    mapping: dict[str, str] = {}
    md_dir = manual_path.parent
    if not output_dir.exists():
        return mapping
    for asset in list(output_dir.glob("**/*.png")) + list(output_dir.glob("**/*.mp4")):
        # Map asset path -> path relative to manual dir
        try:
            rel = asset.resolve().relative_to(md_dir.resolve())
        except ValueError:
            # Asset is outside manual dir; use as-is
            rel = asset
        mapping[asset.stem] = str(rel)
    return mapping


def _apply_mapping_to_manual(manual_path: Path, mapping_path: Path) -> int:
    """v0.4.0: wrap cmd_record_manual --apply-mapping in a function
    that returns the exit code. Avoids spawning another Python
    interpreter."""
    return cmd_record_manual([str(manual_path), "--apply-mapping", str(mapping_path)])


def _run_validate(manual_path: Path, unique: bool = False) -> int:
    """v0.4.0: run validate-output.py on a manual. Returns its exit
    code under --strict."""
    import subprocess
    cmd = [sys.executable, str(Path(__file__).parent / "validate-output.py"),
           "--strict"]
    if unique:
        cmd.append("--unique")
    cmd.append(str(manual_path))
    try:
        return subprocess.run(cmd, timeout=60).returncode
    except Exception as e:
        print(f"  ⚠️  validate failed to run: {e}", file=sys.stderr)
        return 0  # don't fail the whole flow on validate crash


# Placeholder syntax:
#   [SCREENSHOT: <name>.png]    [SCREENSHOT NEEDED: <name>.png]
#   [VIDEO: <name>.mp4]         [VIDEO NEEDED: <name>.mp4]
#   [AI ANNOTATE: <name>]        v0.2.4: agent-mediated vision annotation
# All three kinds live in the same scan + apply-mapping pipeline.
#
# I11 fix (v0.2.4 audit): name supports multi-segment identifiers like
# "v1.2" or "settings.modal". An optional trailing image/video extension
# (.png / .mp4 / .jpg / .webm / .gif / .mov) is recognized and stripped
# in scan, so mapping keys stay bare ("01-list", "v1.2-heatmap").
_KNOWN_EXTS = ("png", "mp4", "jpg", "jpeg", "webm", "gif", "mov")
_PLACEHOLDER_RE = re.compile(
    r"\[(?P<kind>SCREENSHOT|VIDEO|AI\s+ANNOTATE)"
    r"(?P<needed>\s+NEEDED)?\s*:\s*"
    r"(?P<name>[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*)"
    r"(?:\.(?P<ext>png|mp4|jpg|jpeg|webm|gif|mov))?"
    r"\]"
)


def _strip_ext(name: str) -> str:
    """Strip a trailing image/video extension if present (I11)."""
    parts = name.split(".")
    if len(parts) > 1 and parts[-1].lower() in _KNOWN_EXTS:
        return ".".join(parts[:-1])
    return name


def scan_recording_placeholders(text: str) -> list[dict]:
    """Find all recording placeholders in text.

    v0.2.3: placeholders inside fenced code blocks (```...```) are
    ignored — those are documentation examples showing the syntax,
    not real recording targets.

    v0.2.4: also recognizes `[AI ANNOTATE: <name>]` markers. These are
    deferred to §15 of SKILL.md — the recorder writes a request file,
    the agent fulfills it via its own LLM, recorder applies Pillow
    annotation on re-run of `apply-ai-responses`.

    v0.2.4 (I11): multi-segment placeholder names like "v1.2-heatmap"
    or "settings.modal" are now supported.

    v0.2.4 (G): each result carries a `needed` boolean (true when the
    user wrote `[... NEEDED: x]`, false for the plain `[...: x]` form).
    Downstream missing-list reports use it to distinguish
    `user_declared_needed` (the user explicitly said "this is missing")
    from `no_mapping` (plain placeholder, may or may not be needed).

    Returns list of {"kind": "screenshot"|"video"|"ai_annotate", "name": str,
                    "line": int, "raw": str, "needed": bool}.
    """
    out = []
    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for m in _PLACEHOLDER_RE.finditer(line):
            kind_raw = m.group("kind").replace(" ", "").lower()
            if kind_raw == "aiannotate":
                kind = "ai_annotate"
            elif kind_raw == "video":
                kind = "video"
            else:
                kind = "screenshot"
            out.append({
                "kind": kind,
                "name": _strip_ext(m.group("name")),
                "line": i,
                "raw": m.group(0),
                "needed": m.group("needed") is not None,
            })
    return out


def build_recorder_template(
    manual_name: str,
    placeholders: list[dict],
    manual_path: Path | None = None,
    project_root: Path | None = None,
) -> dict:
    """v0.5.0: Generate a recorder script template the LLM agent can fill in.

    v0.2.4 — original: stub with `<TODO: ...>` everywhere; agent had to
    hand-fill every field.

    v0.5.0 — auto-fill from project context when given:
      - `manual_path`: read the .md to extract real per-step captions from
        the task card `### 步骤` sections (replaces `<TODO: caption>`).
      - `project_root`: read `docs/user-manual/manual-config.json` to fill
        `url`, `output_dir`, and infer the starting route from the
        module's first route (via extract-routes.py output if cached,
        else a sensible default per module).

    Still emits `<TODO: ...>` markers where the agent MUST intervene:
      - click selectors (we can't infer from spec text)
      - auth_env names (project-specific; defaults to standard set
        of common ones — LG_USER, LG_PASS, etc., inferred from
        manual_name prefix when possible)

    Returns a dict ready to be `json.dumps()`-ed to a .json file.
    """
    config = _read_manual_config(project_root) if project_root else {}
    domain = _domain_for_placeholder(manual_path, "") if manual_path else "<TODO: domain>"
    # domain from _domain_for_placeholder is e.g. "legal" from "legal-user-manual.md"
    inferred_url = _infer_target_url(config, project_root)
    inferred_route = _infer_starting_route(config, domain)
    inferred_user_env = _infer_auth_env_name(manual_name, "USER")
    inferred_pass_env = _infer_auth_env_name(manual_name, "PASS")
    captions = _extract_step_captions(manual_path) if manual_path else {}

    return {
        "_doc": (
            f"Recorder script template generated for {manual_name} (v0.5.0). "
            f"Auto-filled: url={inferred_url!r}, output_dir inferred from domain, "
            f"step captions from the manual's `### 步骤` sections. "
            "Still TODO: click selectors (the agent must read the actual UI), "
            "and verify auth_env names match this project's credential env vars. "
            "Then run `python3 -m recorder_plugin.cli run <this-file>.json`."
        ),
        "name": manual_name,
        "url": inferred_url,
        "viewport": {"width": 1440, "height": 900},
        "output_dir": f"docs/user-manual/screenshots/{domain}/<TODO: subdir>",
        # C fix (v0.2.4 audit): the recorder's resolve_credential() only
        # expands values that start with "$". Bare names like "AUTH_USER"
        # would be passed through as the literal string "AUTH_USER" and
        # submitted to the login form. The $ prefix tells the recorder
        # to look up the env var. Without it, login silently fails.
        # v0.5.0: use module-specific env var names when we can infer them.
        "auth_env": [
            f"${inferred_user_env}",
            f"${inferred_pass_env}",
        ],
        "steps": [
            {"action": "navigate", "url": inferred_route},
            {"action": "wait_for", "strategy": "networkidle"},
            # If we can infer a login step, add a placeholder click for
            # the username / password fields. The agent must fill in the
            # actual selectors.
            {"action": "type",
             "selector": "<TODO: input[name=username], input[type=text], or #username>",
             "value": f"${inferred_user_env}"},
            {"action": "type",
             "selector": "<TODO: input[name=password], input[type=password], or #password>",
             "value": f"${inferred_pass_env}"},
            {"action": "click",
             "selector": "<TODO: button[type=submit], button.login, or [data-test=login-submit]>"},
            {"action": "wait_for", "strategy": "networkidle"},
            *_step_template_lines_v2(placeholders, captions),
        ],
    }


def _step_template_lines_v2(placeholders: list[dict], captions: dict) -> list[dict]:
    """v0.5.0: like _step_template_lines, but uses real captions from
    the manual when available (falls back to <TODO: caption> otherwise).
    """
    out = []
    last_video_started = False
    for p in placeholders:
        if p["kind"] == "screenshot":
            caption = captions.get(p["name"], "<TODO: caption>")
            out.append({
                "action": "screenshot",
                "name": p["name"],
                "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50,
                              "label": caption}],
            })
        elif p["kind"] == "video":
            if not last_video_started:
                out.append({"action": "video_start", "name": p["name"]})
                last_video_started = True
            else:
                out.append({"action": "video_stop", "name": f"<TODO: previous-video>"})
                out.append({"action": "video_start", "name": p["name"]})
        elif p["kind"] == "ai_annotate":
            out.append({
                "action": "ai_annotate",
                "screenshot": p["name"],
                "prompt": "",
            })
    if last_video_started:
        out.append({"action": "video_stop", "name": "<TODO: last-video>"})
    return out


def _read_manual_config(project_root: Path | None) -> dict:
    """v0.5.0: read manual-config.json if present; return empty dict otherwise.
    Catches all errors (missing file, bad JSON) so this is a safe no-op fallback."""
    if project_root is None:
        return {}
    cfg_path = project_root / "docs" / "user-manual" / "manual-config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _infer_target_url(config: dict, project_root: Path | None) -> str:
    """v0.5.0: build the target URL from manual-config.json.

    Config schema (v2): { "project": { "name": ..., "host": ..., "port": ... } }
    Old schema: { "name": ..., "host": ..., "port": ... }

    Returns a URL like "http://localhost:8080" or "<TODO: target URL>" if
    the config is missing or has placeholders.
    """
    if not config:
        return "<TODO: target URL — set in manual-config.json project.host + port>"
    p = config.get("project") or config  # support both v2 nested and flat
    # v0.5.3: use `or` so None / "" / 0 all fall back to the TODO marker.
    # Without this, `host: null` produced `http://None:8080` and the
    # recorder would try to connect to a non-resolvable hostname.
    host = p.get("host") or "<TODO: host>"
    port = p.get("port") or "<TODO: port>"
    if str(host).startswith("<") or str(port).startswith("<"):
        return f"http://{host}:{port}"
    return f"http://{host}:{port}"


def _infer_starting_route(config: dict, domain: str) -> str:
    """v0.5.0: infer a starting route for the recorder.

    Tries config.project.starting_routes[domain], then falls back to
    a per-domain conventional default (e.g. /contracts for legal,
    /employees for sys). Always returns a path starting with /.
    """
    if config:
        p = config.get("project") or config
        routes = p.get("starting_routes") or {}
        if domain in routes:
            r = routes[domain]
            return r if r.startswith("/") else "/" + r
    # Conventional defaults per domain (covers common cases)
    defaults = {
        "sys":     "/users",
        "system":  "/users",
        "legal":   "/contracts",
        "lg":      "/contracts",
        "esg":     "/dashboard",
        "audit":   "/plans",
        "au":      "/plans",
        "overview": "/dashboard",
    }
    return defaults.get(domain, "/<TODO: starting route>")


def _infer_auth_env_name(manual_name: str, suffix: str) -> str:
    """v0.5.0: infer a sensible env var name for credentials.

    e.g. "legal-user-manual" -> "LEGAL_USER" / "LEGAL_PASS".
    Falls back to "AUTH_USER" / "AUTH_PASS" if the name is too generic.
    """
    stem = manual_name.replace("-user-manual", "").replace("_user_manual", "")
    stem = stem.upper().replace("-", "_").strip("_")
    if not stem or len(stem) < 2:
        return f"AUTH_{suffix}"
    return f"{stem}_{suffix}"


def _extract_step_captions(manual_path: Path) -> dict:
    """v0.5.0: scan the manual for `### 步骤` sections under each task
    card, and return {screenshot_name: caption_string}.

    Heuristic: the first text in each numbered list item under
    `### 步骤` becomes a caption. The mapping screenshot_name -> caption
    is built by taking the i-th step caption and matching it to the
    i-th `[SCREENSHOT: <name>]` placeholder in document order.
    """
    try:
        text = manual_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    placeholders = scan_recording_placeholders(text)
    placeholder_names = [p["name"] for p in placeholders if p["kind"] == "screenshot"]

    # Find each `### 步骤` block and extract numbered items
    captions_per_block: list[list[str]] = []
    in_steps = False
    current_block: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("### 步骤"):
            in_steps = True
            current_block = []
            continue
        if in_steps:
            if s.startswith("###") or s.startswith("##"):
                # End of this block
                if current_block:
                    captions_per_block.append(current_block)
                in_steps = False
                continue
            # Numbered list item: "1. xxx", "2. xxx"
            import re
            m = re.match(r"^(\d+)\.\s+(.+)$", s)
            if m:
                current_block.append(m.group(2).strip())
    if current_block:
        captions_per_block.append(current_block)

    # Flatten (one caption per step in document order, matching the
    # first N screenshot placeholders)
    flat = [cap for block in captions_per_block for cap in block]
    return {name: cap for name, cap in zip(placeholder_names, flat)}


def _step_template_lines(placeholders: list[dict]) -> list[dict]:
    """Convert placeholders into ordered recorder step stubs.

    Each screenshot → one `screenshot` step. Each video → a video_start /
    / video_stop pair surrounding the closest preceding screenshot.
    Each AI ANNOTATE → one `ai_annotate` step (with a `screenshot` field
    pointing at the source PNG; agent fulfills via its own LLM in §15).
    """
    out = []
    last_video_started = False
    for p in placeholders:
        if p["kind"] == "screenshot":
            out.append({
                "action": "screenshot",
                "name": p["name"],
                "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50,
                              "label": "<TODO: caption>"}],
            })
        elif p["kind"] == "video":
            if not last_video_started:
                out.append({"action": "video_start", "name": p["name"]})
                last_video_started = True
            else:
                # Multiple videos in a row: stop the previous before starting the next
                out.append({"action": "video_stop", "name": f"<TODO: previous-video>"})
                out.append({"action": "video_start", "name": p["name"]})
        elif p["kind"] == "ai_annotate":
            out.append({
                "action": "ai_annotate",
                "screenshot": p["name"],
                "prompt": "",  # F3 fix: agent MUST fill in. Empty prompt -> script runner warns to stderr.
            })
    if last_video_started:
        out.append({"action": "video_stop", "name": "<TODO: last-video>"})
    return out


def _normalize_mapping_value(v) -> tuple[str, str | None]:
    """v0.3.0 (mapping alt field): mapping values can be either a
    bare string (the path; alt defaults to the key) or a dict
    `{path, alt}` for explicit alt text. Returns (path, alt_or_None).
    Raises ValueError on anything else."""
    if isinstance(v, str):
        return v, None
    if isinstance(v, dict) and "path" in v:
        return v["path"], v.get("alt")
    raise ValueError(
        f"invalid mapping value: {v!r} — must be a string path "
        f"or a dict with 'path' (and optional 'alt')"
    )


def apply_recording_mapping(text: str, mapping: dict) -> tuple[str, dict, list, int]:
    """Replace placeholders in text with real asset paths from mapping.

    Recognizes all 3 placeholder kinds (SCREENSHOT, VIDEO, AI ANNOTATE).

    v0.2.4 naming convention for the mapping keys:
      - Plain name (e.g. "01-list") -> replaces [SCREENSHOT: 01-list.*]
        and [VIDEO: 01-list.*] placeholders. Value is the raw .png / .mp4 path.
      - Prefixed name (e.g. "ai-annotated-01-list") -> replaces only
        [AI ANNOTATE: 01-list] placeholders. Value is the *.ai-annotated.png
        path produced by `apply-ai-responses`.

    This separation lets the agent provide different paths for the raw
    screenshot vs. the AI-annotated version. Documented in SKILL.md Sec 15.

    F1 fix: replace ALL occurrences of each placeholder name (not just
    the first). Previous count=1 left 2nd+ same-name placeholders un-replaced.
    F2 fix: AI ANNOTATE placeholders REQUIRE the `ai-annotated-` prefix
    mapping. If only a plain-name mapping exists for the same name, that's
    a config error and the AI ANNOTATE is reported in missing (with
    explicit reason) instead of being silently dropped.

    I11 fix (v0.2.4 audit): multi-segment placeholder names like
    "v1.2-heatmap" are supported. The pattern uses re.escape(name)
    followed by an optional extension.

    I14 fix (v0.2.4 audit): the 4th tuple element is the count of
    placeholder INSTANCES replaced (not unique mapping keys). One
    mapping key may replace 2+ instances if the placeholder appears
    in multiple task cards.

    G fix (v0.2.4 audit): each missing entry now carries a `status`
    field, one of:
      - "no_mapping": placeholder exists in the manual but no mapping
        key was provided. The user wrote plain `[...: x]` (not NEEDED).
      - "user_declared_needed": user wrote `[... NEEDED: x]`, explicitly
        flagging that this placeholder MUST be replaced. The agent loop
        should prioritize these over plain missing.
      - "wrong_mapping_type": AI ANNOTATE placeholder was given a plain
        name mapping key (should be `ai-annotated-` prefixed).

    Returns: (new_text, replaced, missing, replaced_instances)
      - replaced: {mapping_key: real_path} — unique keys that had at
        least one match
      - missing: list of {name, kind, status, reason} for placeholders
        that survived the substitution
      - replaced_instances: total count of placeholder occurrences
        replaced (can exceed len(replaced) if same key appears 2+ times)
    """
    reemplazado = {}
    missing = []
    replaced_instances = 0
    for key, raw_value in mapping.items():
        # v0.3.0: value can be a string path or a {path, alt} dict
        try:
            real_path, alt_override = _normalize_mapping_value(raw_value)
        except ValueError as e:
            # Surface the bad entry as a missing row so the user sees
            # all mapping problems in one pass instead of one-at-a-time
            missing.append({
                "name": key,
                "kind": "mapping_value",
                "status": "no_mapping",
                "reason": str(e),
            })
            continue
        alt_text = alt_override if alt_override is not None else key
        if key.startswith("ai-annotated-"):
            name = key[len("ai-annotated-"):]
            pattern = re.compile(rf"\[AI\s+ANNOTATE\s*:\s*{re.escape(name)}(?:\.[A-Za-z0-9]+)?\]")
        else:
            name = key
            pattern = re.compile(
                rf"\[(?P<kind>SCREENSHOT|VIDEO)(?:\s+NEEDED)?\s*:\s*{re.escape(name)}(?:\.[A-Za-z0-9]+)?\]"
            )
        if pattern.search(text):
            # v0.3.0: alt text now uses the explicit `alt` field if
            # provided, else falls back to the mapping key (preserves
            # v0.2.x behavior so existing mappings don't need migration).
            new_text, n = pattern.subn(f"![{alt_text}]({real_path})", text)  # count=0: replace all
            text = new_text
            reemplazado[key] = real_path
            replaced_instances += n
    remaining = scan_recording_placeholders(text)
    for p in remaining:
        if p["kind"] == "ai_annotate":
            prefixed_key = f"ai-annotated-{p['name']}"
            # F2 fix: explicit missing detection for AI ANNOTATE
            if prefixed_key in mapping:
                continue
            if p["name"] in mapping:
                missing.append({
                    "name": p["name"],
                    "kind": "ai_annotate",
                    "status": "wrong_mapping_type",
                    "reason": (f"AI ANNOTATE requires mapping key "
                               f"'ai-annotated-{p['name']}', not plain "
                               f"'{p['name']}'. Plain key replaces "
                               f"[SCREENSHOT:] only."),
                })
            else:
                missing.append({
                    "name": p["name"],
                    "kind": "ai_annotate",
                    "status": "no_mapping",
                    "reason": (f"No mapping entry for this AI ANNOTATE. "
                               f"Add 'ai-annotated-{p['name']}' to mapping."),
                })
        else:
            if p["name"] not in mapping:
                # G fix: distinguish no_mapping from user_declared_needed
                status = "user_declared_needed" if p["needed"] else "no_mapping"
                missing.append({
                    "name": p["name"],
                    "kind": p["kind"],
                    "status": status,
                    "reason": (f"No mapping entry for this "
                               f"{p['kind']} placeholder."),
                })
    return text, reemplazado, missing, replaced_instances
def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("--help", "-h", "help"):
        print(__doc__)
        return 0 if len(argv) >= 2 else 2

    cmd = argv[1]

    if cmd == "now-et":
        print(now_et())
        return 0

    if cmd == "init":
        if len(argv) != 3:
            print("usage: manual_helper.py init <md-path>", file=sys.stderr)
            return 2
        target = Path(argv[2])
        created = init(target)
        print(f"{'created' if created else 'exists'}: {target}")
        return 0

    if cmd == "init-skill":
        # v1.0.0: BREAKING. --allow-blocked removed. A manual without
        # real screenshots and videos is not a valid deliverable. If
        # the recording phase cannot run, the LLM must fix the
        # environment (start dev server, install deps) and re-run.
        # --no-install is kept for CI environments that manage deps
        # via other channels.
        auto_install = "--no-install" not in argv
        if "--allow-blocked" in argv:
            print("ERROR: --allow-blocked was removed in v1.0.0.", file=sys.stderr)
            print("  The skill now requires real screenshots and videos.", file=sys.stderr)
            print("  Fix the recording-readiness failures and re-run.", file=sys.stderr)
            return 2
        positionals = [a for a in argv[2:] if not a.startswith("--")]
        proj_root = Path(positionals[0]) if positionals else Path.cwd()
        try:
            result = init_skill(
                proj_root,
                auto_install=auto_install,
            )
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        except RecordingBlockedError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            print("", file=sys.stderr)
            print("  The recording phase (§14) cannot run.", file=sys.stderr)
            print("  The skill v1.0.0 no longer supports a draft-only deliverable.", file=sys.stderr)
            print("  Options:", file=sys.stderr)
            print("    1. Fix the issues above and re-run `init-skill`", file=sys.stderr)
            print("    2. Re-run with --no-install if you manage deps via CI", file=sys.stderr)
            return 2
        print(f"project root: {proj_root}")
        for p in result["created"]:
            print(f"  created: {p}")
        for p in result["skipped"]:
            print(f"  skipped (exists): {p}")
        if "personas_required" in result:
            print(f"  personas: {result['personas_required']} (present)")
        if not result["created"]:
            print("(nothing to do -- already initialized)")
        # v0.4.0: print the readiness badge (OK/WARN/BLOCKED). Default
        # behavior is to fail if BLOCKED (see RecordingBlockedError above).
        _print_recording_readiness_banner(result.get("recording_readiness", {}))
        if result.get("auto_install_attempted"):
            if result.get("auto_install_ok"):
                print("", file=sys.stderr)
                print("✅ auto-install completed; recording phase is ready.", file=sys.stderr)
            else:
                print("", file=sys.stderr)
                print("⚠️  auto-install could not complete; see messages above.", file=sys.stderr)
        # v0.5.0: auto-regenerate <proj>/docs/user-manual/user-manual.html
        # if the shipped template is newer than what is on disk. Keeps
        # the viewer (TOC fix, etc.) in sync without forcing the user
        # to remember to re-build after a skill upgrade. Failures here
        # are non-fatal: the LLM may be running on a read-only project
        # root, or the project may not have a user-manual.html yet.
        try:
            html_target = proj_root / "docs" / "user-manual" / "user-manual.html"
            regen_status = regenerate_html_if_stale(html_target)
            if regen_status == "regenerated":
                print(f"  viewer: regenerated {html_target} (template v{html_template_version()})", file=sys.stderr)
            elif regen_status == "created":
                print(f"  viewer: created {html_target} (template v{html_template_version()})", file=sys.stderr)
        except (FileNotFoundError, ValueError, OSError) as e:
            print(f"  viewer: auto-regen skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return 0

    if cmd == "check-recording-readiness":
        proj_root = Path(argv[2]) if len(argv) == 3 else Path.cwd()
        readiness = check_recording_readiness(proj_root)
        if "--json" in argv:
            print(json.dumps(readiness, ensure_ascii=False, indent=2))
        else:
            badge = {"green": "✅ GREEN", "yellow": "🟡 WARNING", "red": "🔴 BLOCKED"}[readiness["status"]]
            print(f"=== Recording Phase Readiness ({badge}) ===")
            for c in readiness["checks"]:
                icon = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[c["status"]]
                print(f"  {icon}  {c['name']}: {c['detail']}")
                if c["fix"]:
                    print(f"        → {c['fix']}")
            print()
            print(f"  {readiness['summary']}")
        # 0 = green, 1 = yellow, 2 = red. Useful for CI.
        return {"green": 0, "yellow": 1, "red": 2}[readiness["status"]]

    if cmd == "validate-config":
        proj_root = Path(argv[2]) if len(argv) == 3 else Path.cwd()
        result = validate_config(proj_root)
        if "--json" in argv:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result["errors"]:
                print("ERRORS:")
                for e in result["errors"]:
                    print(f"  - {e}")
            if result["warnings"]:
                print("WARNINGS:")
                for w in result["warnings"]:
                    print(f"  - {w}")
            if result["ok"]:
                print("OK: manual-config.json + personas.json valid.")
                print(f"     personas: {len(result['info'].get('persona_ids', []))}")
                print(f"     granularity: {result['info'].get('granularity')}")
                print(f"     covered objectives: {result['info'].get('covered_objectives', [])}")
        return 0 if result["ok"] else 1
    if cmd == "extract-tasks":
        return cmd_extract_tasks(argv[2:])
    if cmd == "extract-fields":
        return cmd_extract_fields(argv[2:])
    if cmd == "extract-routes":
        return cmd_extract_routes(argv[2:])
    if cmd == "extract-roles":
        return cmd_extract_roles(argv[2:])
    if cmd == "extract-openapi":
        return cmd_extract_openapi(argv[2:])

    if cmd == "scan-artifacts":
        if len(argv) != 3:
            print("usage: manual_helper.py scan-artifacts <project-root>", file=sys.stderr)
            return 2
        entries = scan_artifacts(Path(argv[2]))
        json.dump(entries, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "parse-citations":
        if len(argv) != 3:
            print("usage: manual_helper.py parse-citations <md-path>", file=sys.stderr)
            return 2
        result = parse_citations(Path(argv[2]))
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "fill-citation-shas":
        return _cmd_fill_citation_shas(argv[2:])

    if cmd == "diff-artifacts":
        if len(argv) != 4:
            print("usage: manual_helper.py diff-artifacts <project-root> <md-path>", file=sys.stderr)
            return 2
        result = diff_artifacts(Path(argv[2]), Path(argv[3]))
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "record-manual":
        return cmd_record_manual(argv[2:])

    if cmd == "record-and-replace":
        return cmd_record_and_replace(argv[2:])

    if cmd == "check-recorder-script":
        return cmd_check_recorder_script(argv[2:])

    if cmd == "html-template-version":
        print(html_template_version())
        return 0

    if cmd == "html-on-disk-version":
        if len(argv) != 3:
            print(
                "usage: manual_helper.py html-on-disk-version <html-path>",
                file=sys.stderr,
            )
            return 2
        try:
            print(html_on_disk_version(Path(argv[2])))
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0

    if cmd == "regenerate-html-if-stale":
        if len(argv) != 3:
            print(
                "usage: manual_helper.py regenerate-html-if-stale <html-path>",
                file=sys.stderr,
            )
            return 2
        result = regenerate_html_if_stale(Path(argv[2]))
        print(f"{result}: {argv[2]}")
        return 0

    if cmd == "write-index":
        if len(argv) < 4:
            print(
                "usage: manual_helper.py write-index <html-dir> <md-path> [more...]",
                file=sys.stderr,
            )
            return 2
        html_dir = Path(argv[2])
        md_paths = [Path(p) for p in argv[3:]]
        out = write_index(html_dir, md_paths)
        print(f"wrote: {out}")
        return 0

    if cmd == "build-standalone":
        if len(argv) < 5:
            print(
                "usage: manual_helper.py build-standalone <html-template> <html-out> <md-path> [more...]",
                file=sys.stderr,
            )
            return 2
        tmpl = Path(argv[2])
        out = Path(argv[3])
        md_paths = [Path(p) for p in argv[4:]]
        result = build_standalone(tmpl, out, md_paths)
        print(f"wrote: {result}")
        return 0

    if cmd == "read-config":
        cmd_read_config(argv[2:])
        return 0
    if cmd == "init-db":
        rc = cmd_init_db(argv[2:])
        return rc if rc is not None else 0
    if cmd == "upsert-manual":
        rc = cmd_upsert_manual(argv[2:])
        return rc if rc is not None else 0
    if cmd == "upload-asset":
        rc = cmd_upload_asset(argv[2:])
        return rc if rc is not None else 0

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2



# ---------- DB mode: helper subcommands (db backend = FastAPI at MANUAL_API_BASE) ----------

CONFIG_FILENAME = "manual-config.json"
# 配置文件查找路径(按这个顺序)
CONFIG_SEARCH_PATHS = [
    "docs/user-manual/manual-config.json",   # 项目级(<project>/docs/user-manual/ 风格)
    "manual-config.json",                    # 仓库根
]

def find_config(start_dir: Path) -> Path | None:
    """从 start_dir 向上找 manual-config.json(优先近的)。
    额外查找 docs/user-manual/manual-config.json(项目级,GCR 风格)。"""
    cur = start_dir.resolve()
    for parent in [cur, *cur.parents]:
        cand = parent / CONFIG_FILENAME
        if cand.exists():
            return cand
    # 备选: 项目根的 docs/user-manual/ 下面
    for parent in [cur, *cur.parents]:
        cand = parent / "docs" / "user-manual" / CONFIG_FILENAME
        if cand.exists():
            return cand
    return None

def load_config() -> dict:
    """从 cwd 向上找 manual-config.json, 没找到给一个 file 模式默认 config。"""
    cfg_path = find_config(Path.cwd())
    if not cfg_path:
        return {
            "storage": "file",
            "object_store": "minio",
            "object_store_config": {
                "endpoint": "http://localhost:9100",
                "bucket": "manuals",
                "access_key": "minioadmin",
                "secret_key": "minioadmin",
                "public_base_url": "http://localhost:9100/manuals",
            },
            "db": {"dsn": "postgresql://user:CHANGE_ME@localhost:5432/user_manual"},
            "api": {"base_url": "http://localhost:8765"},
            "auth": {"enabled": False, "token": ""},
        }
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)

def api_base_from_config(cfg: dict) -> str:
    return cfg.get("api", {}).get("base_url", "http://localhost:8765").rstrip("/")

def read_md_split(raw_md: str) -> tuple[dict, str]:
    """(frontmatter, body) — 与 _parse_frontmatter 行为一致。"""
    fm, body = _parse_frontmatter(raw_md)
    return fm, body

def http_post_json(url: str, payload: dict, token: str = "") -> dict:
    """POST JSON. 简单实现, 不引外部依赖。"""
    import urllib.request, urllib.error
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} -> {e.code} {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"POST {url} unreachable: {e.reason}") from e

def http_post_multipart(url: str, file_path: Path, caption: str, token: str = "") -> dict:
    """POST multipart/form-data, 单个 file 字段 + caption。"""
    import urllib.request, urllib.error, uuid, mimetypes
    boundary = f"----manual{uuid.uuid4().hex}"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    parts: list[bytes] = []
    def add_field(name: str, value: str):
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    def add_file(name: str, filename: str, content: bytes, mime: str):
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(content)
        parts.append(b"\r\n")
    add_field("caption", caption)
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    add_file("upload", file_path.name, file_path.read_bytes(), mime)
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"POST {url} -> {e.code} {e.read().decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"POST {url} unreachable: {e.reason}") from e

# ---- new subcommands ----

def cmd_read_config(_args):
    cfg = load_config()
    cfg_path = find_config(Path.cwd())
    print(f"# source: {cfg_path or '(defaults, no config file found)'}")
    print(json.dumps(cfg, indent=2, ensure_ascii=False))

def cmd_init_db(args):
    """init-db: 把 schema 推到 DB(创建表, drop existing)。
    schema.sql 路径: <skill_dir>/db/schema.sql, 或 环境变量 MANUAL_DB_SCHEMA。
    """
    import urllib.request
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"WARN: storage={cfg.get('storage')!r}, 仍按 db 模式执行", file=sys.stderr)
    dsn = cfg.get("db", {}).get("dsn") or os.environ.get("MANUAL_DB_DSN", "")
    if not dsn:
        print("error: no db.dsn in config and MANUAL_DB_DSN not set", file=sys.stderr)
        return 1
    # 找 schema.sql
    skill_dir = Path(__file__).resolve().parent.parent  # skill-template/scripts/.. -> skill-template
    schema_candidates = [
        skill_dir / "db" / "schema.sql",
        skill_dir.parent / "user-manual-api" / "schema.sql",  # 项目级 db 旁
        Path.cwd() / "docs" / "user-manual-api" / "schema.sql",
    ]
    schema_path = next((p for p in schema_candidates if p.exists()), None)
    if not schema_path:
        print(f"error: schema.sql not found, tried: {[str(p) for p in schema_candidates]}", file=sys.stderr)
        return 1
    sql = schema_path.read_text(encoding="utf-8")
    # 用 psycopg2 风格? 不引外部依赖, 用 asyncpg 在 subprocess 里跑
    # 简化: 用 docker exec / 直接 psql 都不行(helper 是纯 stdlib)
    # 走 API? schema 推送不走 API(API 不应能 drop)。这里直接 require asyncpg。
    try:
        import asyncpg
    except ImportError:
        print("error: asyncpg required for init-db. install: pip install asyncpg", file=sys.stderr)
        return 1
    async def run():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()
    asyncio.run(run())
    print(f"initialized: {dsn} (schema: {schema_path})")
    return 0

def cmd_upsert_manual(args):
    """upsert-manual <md-path>: 读 md, 拆 frontmatter/body, POST /api/manuals."""
    if len(args) != 1:
        print("usage: manual_helper.py upsert-manual <md-path>", file=sys.stderr)
        return 2
    md_path = Path(args[0])
    if not md_path.exists():
        print(f"error: {md_path} not found", file=sys.stderr)
        return 1
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"error: storage={cfg.get('storage')!r}, db mode only", file=sys.stderr)
        return 1
    raw = md_path.read_text(encoding="utf-8")
    fm, body = read_md_split(raw)
    # module / module_code 双字段:
    # - module:  显示名(可中文,可含空格)
    # - module_code: 机器可读 key(英文/数字/下划线,作 S3 prefix)
    # 没显式给 module_code 时,API 端会用 module 字段兜底(ASCII-slugify,中文 → MISC)
    payload = {
        "file": md_path.name,
        "module": fm.get("module") or fm.get("module_code") or "MISC",
        "module_code": fm.get("module_code") or None,
        "title": fm.get("title") or md_path.stem,
        "description": fm.get("description") or None,
        "order": int(fm["order"]) if str(fm.get("order", "")).isdigit() else 999,
        "version": fm.get("version") or "v0.1",
        "version_date": fm.get("version_date") or None,
        "body_md": body,
        "raw_md": raw,
    }
    url = f"{api_base_from_config(cfg)}/api/manuals"
    token = cfg.get("auth", {}).get("token", "") if cfg.get("auth", {}).get("enabled") else ""
    try:
        r = http_post_json(url, payload, token)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"upserted: {r.get('file')} (id={r.get('id', '?')}, version={r.get('version')})")
    return 0

def cmd_upload_asset(args):
    """upload-asset <manual-file> <asset-path> [--caption TEXT]"""
    if len(args) < 2:
        print("usage: manual_helper.py upload-asset <manual-file-name> <asset-path> [--caption TEXT]", file=sys.stderr)
        return 2
    manual_file = args[0]
    asset_path = Path(args[1])
    caption = ""
    if "--caption" in args:
        i = args.index("--caption")
        if i + 1 < len(args):
            caption = args[i + 1]
    if not asset_path.exists():
        print(f"error: {asset_path} not found", file=sys.stderr)
        return 1
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"error: storage={cfg.get('storage')!r}, db mode only", file=sys.stderr)
        return 1
    # 1) ensure manual exists
    fm_url = f"{api_base_from_config(cfg)}/api/manuals"
    token = cfg.get("auth", {}).get("token", "") if cfg.get("auth", {}).get("enabled") else ""
    # 2) upload
    up_url = f"{api_base_from_config(cfg)}/api/manuals/{manual_file}/assets"
    try:
        r = http_post_multipart(up_url, asset_path, caption, token)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"uploaded: {r['object_key']} -> {r['public_url']} ({r['size']} bytes, {r['kind']})")
    # 3) print md-insert hint
    print(f"# md 引用: ![{caption or asset_path.stem}]({r['public_url']})")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
