
from __future__ import annotations
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .common import (
    ET,
    now_et,
    TEMPLATE,
    CITATIONS_BLOCK,
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_LINES,
)

from .readiness import (
    check_recording_readiness,
    _print_recording_readiness_banner,
)

# _is_dev_server_red_only and _auto_install_recorder_deps are defined
# in this module (init.py), not in readiness.py — they are init-skill
# specific helpers that orchestrate the recording-readiness flow.

def now_et() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")


def init(path: Path) -> bool:
    """Create the scaffold file if missing. Returns True if it created it.

    Citations section is appended only if the project's manual-config.json
    has include_citations=true. Per SKILL.md §3 row 12 + §6, Citations is
    an internal SHA-tracking tool and is OFF by default.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    body = TEMPLATE
    # Walk up to find the project root (where manual-config.json lives).
    proj = path
    while proj != proj.parent:
        proj = proj.parent
        if (proj / "manual-config.json").exists() or (proj / "docs" / "user-manual" / "manual-config.json").exists():
            break
    config_path = proj / "manual-config.json"
    if not config_path.exists():
        config_path = proj / "docs" / "user-manual" / "manual-config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if cfg.get("include_citations") is True:
                body = body + CITATIONS_BLOCK
        except (OSError, json.JSONDecodeError):
            pass
    path.write_text(body, encoding="utf-8")
    return True


def _detect_project_layout(project_root: Path) -> dict:
    """Probe the project tree and return suggested repo_layout + inputs.

    Detection rules (in priority order):
      - frontend: look for `src/router/index.{ts,js}`,
                 `src/views/**/*.vue`, `frontend/...`, `app/...`
      - backend:  look for `pom.xml`, `build.gradle`, `*Application.java`
                 or `backend/`, `server/`
      - superpowers: look for `docs/superpowers/{specs,plans,findings,reviews}/`
      - openapi:  look for `openapi.{yaml,yml,json}`

    Returns a dict with `repo_layout` and `inputs` keys (both lists/dicts
    ready to drop into manual-config.json). The LLM can override any
    field after init.
    """
    layout: dict = {"frontend_root": "frontend", "backend_root": "backend", "docs_root": "docs"}
    inputs: list[dict] = []

    # Superpowers artifacts (highest priority for SKILL.md)
    if (project_root / "docs" / "superpowers").is_dir():
        inputs.append({"kind": "superpowers", "path": "docs/superpowers"})

    # Frontend detection. Walk into candidate frontend roots and check
    # for views/ or router/ inside their src/ subdir. We support two
    # layouts:
    #   (a) <root>/src/views or <root>/src/router  -> frontend_root = "."
    #   (b) <root>/<sub>/src/views or <root>/<sub>/src/router  -> frontend_root = "<sub>"
    # The check looks INSIDE <candidate>/src, not at the candidate root,
    # so a directory called "frontend" that has no src/ subdir is not
    # mistakenly treated as a frontend root.
    frontend_root = None
    if (project_root / "src" / "views").is_dir() or (project_root / "src" / "router").is_dir():
        frontend_root = "."
    else:
        for candidate in ("frontend", "app", "web", "client"):
            c = project_root / candidate
            if not c.is_dir():
                continue
            if (c / "src" / "views").is_dir() or (c / "src" / "router").is_dir():
                frontend_root = candidate
                break
            # Some projects put views/ directly under the frontend dir
            # (e.g. <root>/frontend/pages), accept that too.
            if (c / "views").is_dir() or (c / "router").is_dir() or (c / "pages").is_dir():
                frontend_root = candidate
                break
    if frontend_root is not None:
        layout["frontend_root"] = frontend_root
        if frontend_root == ".":
            inputs.append({"kind": "frontend_pages", "path": "src/views", "include_globs": ["**/*.vue"]})
            for ext in ("ts", "js", "mjs"):
                if (project_root / "src" / "router" / f"index.{ext}").exists():
                    inputs.append({"kind": "router", "path": f"src/router/index.{ext}"})
                    break
        else:
            # monorepo: check <root>/<sub>/src/views OR <root>/<sub>/views
            if (project_root / frontend_root / "src" / "views").is_dir():
                views_path = f"{frontend_root}/src/views"
                router_prefix = f"{frontend_root}/src/router"
            else:
                views_path = f"{frontend_root}/views"
                router_prefix = f"{frontend_root}/router"
            inputs.append({"kind": "frontend_pages", "path": views_path, "include_globs": ["**/*.vue"]})
            for ext in ("ts", "js", "mjs"):
                if (project_root / router_prefix / f"index.{ext}").exists():
                    inputs.append({"kind": "router", "path": f"{router_prefix}/index.{ext}"})
                    break

    # Backend detection
    backend_root = None
    for candidate in ("backend", "server", "api", "src"):
        c = project_root / candidate
        if not c.is_dir():
            continue
        if (c / "pom.xml").exists() or (c / "build.gradle").exists() or (c / "build.gradle.kts").exists():
            backend_root = candidate
            break
        if any(c.rglob("*Application.java")) or any(c.rglob("*Application.kt")):
            backend_root = candidate
            break
    if backend_root is not None:
        layout["backend_root"] = backend_root
        inputs.append({"kind": "backend_dtos", "path": backend_root, "include_globs": ["**/dto/**/*.java"]})

    # OpenAPI fallback
    for fname in ("openapi.yaml", "openapi.yml", "openapi.json"):
        if (project_root / fname).exists():
            inputs.append({"kind": "openapi", "path": fname})
            break

    return {"repo_layout": layout, "inputs": inputs}


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
        # P6: detect project layout and pre-fill repo_layout + inputs
        # with concrete values (not <PLACEHOLDER>) so the LLM doesn't
        # have to re-derive them. The DEFAULT_CONFIG is the fallback.
        detected = _detect_project_layout(root)
        if detected["inputs"]:
            # Build a fresh config: parse DEFAULT_CONFIG as JSON, then
            # overwrite repo_layout + inputs with detected values. The
            # other placeholders (project.name, build_commands) are left
            # as <PLACEHOLDER> for the LLM to fill.
            try:
                base = json.loads(DEFAULT_CONFIG)
            except json.JSONDecodeError:
                base = {}
            base["project"]["repo_layout"] = detected["repo_layout"]
            base["inputs"] = detected["inputs"]
            config_text = json.dumps(base, ensure_ascii=False, indent=2) + "\n"
        else:
            config_text = DEFAULT_CONFIG
        cfg.write_text(config_text, encoding="utf-8")
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
            Path(__file__).parent.parent.parent / "examples" / "personas.template.json",
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


