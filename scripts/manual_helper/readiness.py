from __future__ import annotations
import subprocess
import sys
from pathlib import Path

from .recording import scan_recording_placeholders
from .common import _candidate_paths_for_placeholder


# ---------------------------------------------------------------------------
# Individual probes.
#
# Each probe returns a list of check dicts (most return exactly one; the
# dev-server probe may return per-port OK rows plus a single WARN if no
# common port is alive). Extracting them as named callables lets tests
# inject controlled outcomes via the `host_probes` kwarg of
# `check_recording_readiness` instead of depending on the host environment
# (review P1-4: tests were binding "machine state" not "why").
# ---------------------------------------------------------------------------

def _probe_playwright_module() -> list[dict]:
    try:
        import playwright  # noqa: F401
        return [{
            "name": "playwright Python module",
            "status": "OK",
            "detail": "playwright is importable",
            "fix": None,
        }]
    except ImportError as e:
        return [{
            "name": "playwright Python module",
            "status": "FAIL",
            "detail": f"ImportError: {e}",
            "fix": ("pip install playwright  (or  pip install -e recorder/[test]  "
                    "per recorder/INSTALL.md)"),
        }]


def _probe_ffmpeg() -> list[dict]:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        first_line = (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else "(no output)"
        return [{
            "name": "ffmpeg binary",
            "status": "OK",
            "detail": first_line[:80],
            "fix": None,
        }]
    except FileNotFoundError:
        return [{
            "name": "ffmpeg binary",
            "status": "FAIL",
            "detail": "ffmpeg not found on PATH",
            "fix": "brew install ffmpeg  (macOS)  /  sudo apt-get install -y ffmpeg  (Ubuntu)",
        }]
    except subprocess.TimeoutExpired:
        return [{
            "name": "ffmpeg binary",
            "status": "WARN",
            "detail": "ffmpeg -version timed out (>5s) - hung?",
            "fix": "Check ffmpeg install:  ffmpeg -version",
        }]
    except Exception as e:
        return [{
            "name": "ffmpeg binary",
            "status": "WARN",
            "detail": f"{type(e).__name__}: {e}",
            "fix": "Check ffmpeg install:  ffmpeg -version",
        }]


def _probe_chromium() -> list[dict]:
    try:
        import urllib.request  # noqa: F401  (kept for parity with old inline imports)
        r = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=10,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or "is already installed" not in out and "is installed" not in out:
            import os
            cache_candidates = [
                Path.home() / "Library" / "Caches" / "ms-playwright",  # macOS
                Path.home() / ".cache" / "ms-playwright",              # Linux
                Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")),   # custom
            ]
            has_chromium = any(
                c.exists() and any(c.glob("chromium-*")) for c in cache_candidates if str(c)
            )
            if has_chromium:
                return [{
                    "name": "Playwright Chromium",
                    "status": "OK",
                    "detail": "Chromium found in playwright cache",
                    "fix": None,
                }]
            return [{
                "name": "Playwright Chromium",
                "status": "FAIL",
                "detail": "Chromium not downloaded",
                "fix": "python3 -m playwright install chromium",
            }]
        return [{
            "name": "Playwright Chromium",
            "status": "OK",
            "detail": "Chromium already installed (per `playwright install --dry-run`)",
            "fix": None,
        }]
    except FileNotFoundError:
        return [{
            "name": "Playwright Chromium",
            "status": "WARN",
            "detail": "python3 -m playwright not available (playwright module missing?)",
            "fix": "pip install playwright  then  python3 -m playwright install chromium",
        }]
    except subprocess.TimeoutExpired:
        return [{
            "name": "Playwright Chromium",
            "status": "WARN",
            "detail": "playwright install --dry-run timed out (>10s)",
            "fix": "python3 -m playwright install chromium",
        }]
    except Exception as e:
        return [{
            "name": "Playwright Chromium",
            "status": "WARN",
            "detail": f"{type(e).__name__}: {e}",
            "fix": "python3 -m playwright install chromium",
        }]


def _probe_dev_server() -> list[dict]:
    """Probe common dev-server ports. A missing dev server is a WARN
    (not FAIL): the user may use a different port or run it in a way our
    probe can't see."""
    import urllib.request
    common_ports = [8080, 5173, 3000, 4200, 8000, 80]
    checks: list[dict] = []
    for port in common_ports:
        try:
            req = urllib.request.Request(f"http://localhost:{port}/", method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as resp:
                checks.append({
                    "name": f"dev server :{port}",
                    "status": "OK",
                    "detail": f"HTTP {resp.status}",
                    "fix": None,
                })
        except Exception:
            pass
    if not any(c["name"].startswith("dev server") and c["status"] == "OK" for c in checks):
        checks.append({
            "name": "dev server (any common port)",
            "status": "WARN",
            "detail": (f"None of {common_ports} responded to HEAD. "
                       f"Recorder has nothing to drive if your app isn't running."),
            "fix": "Start your dev server (e.g.  cd frontend && npm run dev) and re-run this check.",
        })
    return checks


def _probe_manual_placeholders(project_root: Path) -> list[dict]:
    """The §14 gap that motivated this check: a manual with
    [SCREENSHOT:]/[VIDEO:] placeholders but no files on disk means the
    recorder hasn't been run. This probe depends only on the project
    (not the host), so it always runs for real — tests exercise it
    with real fixture files."""
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
                ext = ".mp4" if p["kind"] == "video" else ".png"
                candidates = _candidate_paths_for_placeholder(
                    md_file, p["name"], project_root
                )
                candidates = [c.with_suffix(ext) for c in candidates]
                if not any(c.exists() for c in candidates):
                    missing_file_count += 1
    if placeholder_count == 0:
        return [{
            "name": "manual placeholders vs. files",
            "status": "OK",
            "detail": "No [SCREENSHOT:]/[VIDEO:]/[AI ANNOTATE:] placeholders in the manual",
            "fix": None,
        }]
    if missing_file_count == 0:
        return [{
            "name": "manual placeholders vs. files",
            "status": "OK",
            "detail": f"{placeholder_count} placeholder(s), all have files on disk",
            "fix": None,
        }]
    return [{
        "name": "manual placeholders vs. files",
        "status": "FAIL",
        "detail": (f"{placeholder_count} [SCREENSHOT:]/[VIDEO:] placeholders in the "
                   f"manual, {missing_file_count} have no file on disk. This is the "
                   f"§14 gap — recorder hasn't been run, or the mapping wasn't applied."),
        "fix": ("Run §14:  (1) start your dev server, (2) install the recorder plugin "
                "if not yet (recorder/INSTALL.md), (3) invoke the recorder to capture "
                "screenshots/videos, (4) run `record-manual <manual> --apply-mapping <json>` "
                "to wire the assets in."),
    }]


_DEFAULT_HOST_PROBES = (
    _probe_playwright_module,
    _probe_ffmpeg,
    _probe_chromium,
    _probe_dev_server,
)


def check_recording_readiness(project_root: Path, *, host_probes=None) -> dict:
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
        "checks": [ {"name":..., "status":"OK|WARN|FAIL", "detail":..., "fix":...}, ... ],
        "summary": "<one-line human summary>",
      }

    Status aggregation:
      - any FAIL -> "red"   (recording CANNOT run)
      - any WARN -> "yellow" (recording MIGHT work, but verify)
      - all OK   -> "green" (recording is ready)

    `host_probes` (review P1-4 fix): optional iterable of callables,
    each returning a list of check dicts. Used by tests to inject
    controlled host-state outcomes so assertions bind *why the status
    is what it is*, not the ambient machine state (deps installed,
    a dev server running on localhost). The manual-placeholders probe
    is always run for real (it's project-only, never host-dependent).
    """
    probes = tuple(host_probes) if host_probes is not None else _DEFAULT_HOST_PROBES

    checks: list[dict] = []
    for probe in probes:
        try:
            checks.extend(probe())
        except Exception as e:  # never let one probe crash the others
            checks.append({
                "name": getattr(probe, "__name__", repr(probe)),
                "status": "WARN",
                "detail": f"{type(e).__name__}: {e}",
                "fix": None,
            })
    # The manual-placeholders probe always runs for real (project-only).
    checks.extend(_probe_manual_placeholders(project_root))

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
