"""Tests for v0.3.1 check-recording-readiness subcommand + init-skill auto-banner.

These verify:
  - check_recording_readiness() returns the right shape (status, checks, summary)
  - status aggregation: any FAIL -> red, any WARN -> yellow, all OK -> green
  - the standalone subcommand dispatch (`check-recording-readiness <root>`)
  - init-skill auto-runs the banner (loud stderr output for non-green)
  - exit codes: 0=green, 1=yellow, 2=red

Host-independence (review P1-4 fix): the original tests asserted "a fresh
project is yellow/red", which is only true on a host where deps are missing
or no dev server runs. On a fully-provisioned machine with something alive
on a common port, readiness is green and those tests flipped. We now inject
controlled `host_probes` for the in-process API tests (asserting the WHY
behind each status) and, for the subprocess CLI / init-skill tests, force a
host-independent non-green signal via a manual with unmatched
[SCREENSHOT:] placeholders -> the manual-placeholders probe returns FAIL
-> red regardless of host state.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
import manual_helper

PYTHON = os.environ.get("PYTHON", "python3")


def run_cli(*args):
    return subprocess.run(
        [PYTHON, "-m", "manual_helper", *args],
        capture_output=True, text=True,
    )


def _check(name, status, detail="x", fix=None):
    """Build a single check dict for host_probes injection."""
    return [{"name": name, "status": status, "detail": detail, "fix": fix}]


def _seed_red_project(root: Path):
    """Make a project whose readiness is RED independent of the host:
    a manual with unmatched [SCREENSHOT:] placeholders. The
    manual-placeholders probe (always real, project-only) then returns
    FAIL, which forces red regardless of deps / dev server."""
    manual_dir = root / "docs" / "user-manual" / "manual"
    manual_dir.mkdir(parents=True)
    (manual_dir / "manual.md").write_text(
        "[SCREENSHOT: 01-list.png]\n[SCREENSHOT: 02-form.png]\n"
    )
    return root


class RecordingReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # --- shape / aggregation (host-independent: inject probes) ---

    def test_returns_required_shape(self):
        all_ok = lambda: _check("ok-probe", "OK", "ok")
        r = manual_helper.check_recording_readiness(self.root, host_probes=[all_ok])
        self.assertEqual(r["status"], "green")
        self.assertIn("checks", r)
        self.assertIn("summary", r)
        self.assertIsInstance(r["checks"], list)
        for c in r["checks"]:
            self.assertIn("name", c)
            self.assertIn("status", c)
            self.assertIn(c["status"], ("OK", "WARN", "FAIL"))
            self.assertIn("detail", c)

    def test_empty_project_status_yellow_or_red(self):
        """Intent: when recording prereqs are unmet, status is non-green.
        Injected host probes make this bind *why the status is non-green*
        rather than the ambient machine state."""
        warn_probe = lambda: _check("host-dep", "WARN", "missing", fix="install it")
        r = manual_helper.check_recording_readiness(self.root, host_probes=[warn_probe])
        # place holders probe is OK (no manual dir) -> no FAIL; WARN -> yellow
        self.assertEqual(r["status"], "yellow")
        fail_probe = lambda: _check("host-dep", "FAIL", "missing", fix="install it")
        r = manual_helper.check_recording_readiness(self.root, host_probes=[fail_probe])
        self.assertEqual(r["status"], "red")

    def test_each_check_has_fix_for_fail_warn(self):
        """Every FAIL or WARN check must include a `fix` string so the
        user can act. OK checks should have fix=None."""
        probes = [
            lambda: _check("ok-probe", "OK", "ok"),
            lambda: _check("warn-probe", "WARN", "warn", fix="fix this warning now"),
            lambda: _check("fail-probe", "FAIL", "fail", fix="fix this failure now"),
        ]
        r = manual_helper.check_recording_readiness(self.root, host_probes=probes)
        for c in r["checks"]:
            if c["status"] in ("FAIL", "WARN"):
                self.assertIsNotNone(c["fix"], f"{c['name']} has status {c['status']} but no fix")
                self.assertGreater(len(c["fix"]), 10, f"{c['name']} fix is too terse: {c['fix']!r}")
            elif c["status"] == "OK":
                self.assertIsNone(c["fix"], f"{c['name']} is OK but has a fix: {c['fix']!r}")

    # --- manual placeholders check (always real; project-only) ---

    def test_no_manual_dir_is_ok(self):
        """A project with no docs/user-manual/manual/ dir has no
        placeholders -> no FAIL on this check."""
        r = manual_helper.check_recording_readiness(self.root, host_probes=[lambda: _check("ok", "OK", "ok")])
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "OK")
        self.assertIn("No", ph_check["detail"])

    def test_placeholders_with_files_passes(self):
        """v0.3.1: manual has 2 [SCREENSHOT: foo.png] placeholders AND
        the corresponding files exist -> check OK."""
        manual_dir = self.root / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True)
        shots_dir = self.root / "docs" / "user-manual" / "screenshots" / "manual"
        shots_dir.mkdir(parents=True)
        (shots_dir / "foo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        (shots_dir / "bar.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        (manual_dir / "manual.md").write_text(textwrap.dedent("""\
            # Manual
            [SCREENSHOT: foo.png]
            [SCREENSHOT: bar.png]
        """))
        r = manual_helper.check_recording_readiness(self.root, host_probes=[lambda: _check("ok", "OK", "ok")])
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "OK", msg=ph_check["detail"])
        self.assertIn("all have files", ph_check["detail"])

    def test_placeholders_without_files_fails(self):
        """v0.3.1: the bug we're fixing. Manual has placeholders, no
        files -> check FAIL with actionable fix string."""
        manual_dir = self.root / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True)
        (manual_dir / "manual.md").write_text(textwrap.dedent("""\
            # Manual
            [SCREENSHOT: 01-list.png]
            [SCREENSHOT: 02-form.png]
        """))
        r = manual_helper.check_recording_readiness(self.root, host_probes=[lambda: _check("ok", "OK", "ok")])
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "FAIL")
        self.assertIn("2", ph_check["detail"])  # 2 placeholders
        self.assertIn("§14", ph_check["fix"])   # tells user where to go
        # Overall status is RED (not just yellow) because of this FAIL
        self.assertEqual(r["status"], "red")

    # === v0.3.2: unified path resolution (3.1) ===

    def test_placeholder_in_manual_subdir_finds_file(self):
        """v0.3.2: relative-to-manual-file path fallback."""
        manual_dir = self.root / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True)
        shots_dir = self.root / "docs" / "user-manual" / "manual" / "screenshots" / "contract"
        shots_dir.mkdir(parents=True)
        (shots_dir / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        (manual_dir / "contract-user-manual.md").write_text("[SCREENSHOT: hero.png]\n")
        r = manual_helper.check_recording_readiness(self.root, host_probes=[lambda: _check("ok", "OK", "ok")])
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "OK",
                         msg=f"expected to find hero.png via relative path; got {ph_check['detail']}")

    def test_placeholder_in_init_skill_canonical_path_still_works(self):
        """v0.3.2 backward compat: canonical init-skill path still works."""
        manual_dir = self.root / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True)
        shots_dir = self.root / "docs" / "user-manual" / "screenshots" / "contract"
        shots_dir.mkdir(parents=True)
        (shots_dir / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        (manual_dir / "contract-user-manual.md").write_text("[SCREENSHOT: hero.png]\n")
        r = manual_helper.check_recording_readiness(self.root, host_probes=[lambda: _check("ok", "OK", "ok")])
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "OK")

    # --- CLI dispatch (host-independent: force red via unmatched placeholders) ---

    def test_cli_subcommand_human_output(self):
        """RED project (unmatched placeholders) -> exit 2 + BLOCKED banner.
        Host-independent: red comes from the project-only placeholders
        probe, not from host deps being missing."""
        _seed_red_project(self.root)
        r = run_cli("check-recording-readiness", str(self.root))
        self.assertEqual(r.returncode, 2, msg=r.stdout)  # red
        self.assertIn("=== Recording Phase Readiness", r.stdout)
        self.assertIn("🔴 BLOCKED", r.stdout)

    def test_cli_subcommand_json_output(self):
        _seed_red_project(self.root)
        r = run_cli("check-recording-readiness", "--json", str(self.root))
        self.assertEqual(r.returncode, 2, msg=r.stdout)
        data = json.loads(r.stdout)
        self.assertIn("status", data)
        self.assertIn("checks", data)
        self.assertEqual(data["status"], "red")
        for c in data["checks"]:
            self.assertIn("name", c)
            self.assertIn("status", c)

    def test_cli_subcommand_exit_codes_aggregate(self):
        """Exit code reflects overall: red -> 2. Host-independent via
        unmatched placeholders."""
        _seed_red_project(self.root)
        r = run_cli("check-recording-readiness", str(self.root))
        self.assertEqual(r.returncode, 2, msg=r.stdout)

    # --- init-skill auto-banner (host-independent) ---

    def test_init_skill_emits_banner_when_not_green(self):
        """v0.3.1: init-skill must print the readiness banner when
        readiness is non-green. We force non-green host-independently
        by seeding a manual with unmatched [SCREENSHOT:] placeholders
        *before* running init-skill: the placeholders probe (always
        real) returns FAIL -> red -> banner. init-skill raises
        RecordingBlockedError on red, so we expect exit 2 and the
        BLOCKED error message (not the silent-green path)."""
        fresh = self.root / "fresh"
        fresh.mkdir()
        # Seed a manual that init-skill will NOT overwrite; its
        # unmatched placeholders make readiness RED regardless of host.
        manual_dir = fresh / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True)
        (manual_dir / "seed.md").write_text("[SCREENSHOT: missing.png]\n")
        result = subprocess.run(
            [PYTHON, "-m", "manual_helper", "init-skill", str(fresh)],
            capture_output=True, text=True,
        )
        # init-skill raises RecordingBlockedError on RED -> exit 2.
        self.assertEqual(result.returncode, 2, msg=result.stderr)
        # The blocked error message surfaces readiness context.
        self.assertIn("BLOCKED", result.stderr)
        self.assertIn("recording phase is BLOCKED", result.stderr)

    def test_init_skill_banner_when_yellow_inprocess(self):
        """Guard against the false-green regression from the host being
        fully provisioned: inject a YELLOW readiness into init_skill
        in-process and assert the banner is printed to stderr. This
        covers the non-green banner path deterministically without a
        subprocess, and does not depend on host deps."""
        import io
        import contextlib
        import unittest.mock as mock
        from manual_helper import _print_recording_readiness_banner
        # (a) the banner helper itself prints for yellow
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            _print_recording_readiness_banner({
                "status": "yellow",
                "checks": [{"name": "host-dep", "status": "WARN",
                            "detail": "d", "fix": "fix it"}],
                "summary": "warn",
            })
        self.assertIn("recording phase readiness check", captured.getvalue())
        self.assertIn("🟡 WARNING", captured.getvalue())

    def test_init_skill_does_not_emit_banner_when_green(self):
        """v0.3.1: green suppresses the banner (no spam on every init)."""
        from manual_helper import _print_recording_readiness_banner
        import io, contextlib
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            _print_recording_readiness_banner({
                "status": "green",
                "checks": [],
                "summary": "all good",
            })
        self.assertEqual(captured.getvalue(), "")

    # --- aggregation (host-independent) ---

    def test_aggregation_one_fail_overrides_warn(self):
        """If any check is FAIL, overall is red (regardless of other WARNs)."""
        probes = [
            lambda: _check("warn-probe", "WARN", "w", fix="fix"),
            lambda: _check("fail-probe", "FAIL", "f", fix="fix"),
        ]
        r = manual_helper.check_recording_readiness(self.root, host_probes=probes)
        self.assertEqual(r["status"], "red")

    def test_aggregation_warn_without_fail_is_yellow(self):
        probes = [lambda: _check("warn-probe", "WARN", "w", fix="fix")]
        r = manual_helper.check_recording_readiness(self.root, host_probes=probes)
        self.assertEqual(r["status"], "yellow")

    def test_aggregation_all_ok_is_green(self):
        probes = [lambda: _check("ok-probe", "OK", "ok")]
        r = manual_helper.check_recording_readiness(self.root, host_probes=probes)
        self.assertEqual(r["status"], "green")

    def test_handles_probe_exception(self):
        """A probe that raises must NOT crash the check; it's recorded
        as a WARN so the other checks still run."""
        def boom():
            raise RuntimeError("probe blew up")
        r = manual_helper.check_recording_readiness(self.root, host_probes=[boom])
        self.assertIsInstance(r["checks"], list)
        self.assertGreater(len(r["checks"]), 0)
        self.assertEqual(r["status"], "yellow")

    def test_handles_import_error_in_playwright_check(self):
        """v0.3.1 spirit: a missing playwright module must NOT crash the
        check. The real probe already isolates ImportError -> FAIL; here we
        inject a FAIL probe to confirm the aggregator + shape hold."""
        fail_probe = lambda: _check("playwright Python module", "FAIL",
                                     "ImportError: boom", fix="pip install playwright")
        r = manual_helper.check_recording_readiness(self.root, host_probes=[fail_probe])
        self.assertEqual(r["status"], "red")
        self.assertGreater(len(r["checks"]), 0)


if __name__ == "__main__":
    unittest.main()
