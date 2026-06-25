
from __future__ import annotations
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from .recording import scan_recording_placeholders
from .common import _candidate_paths_for_placeholder

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


