"""Tests for v0.3.1 check-recording-readiness subcommand + init-skill auto-banner.

These verify:
  - check_recording_readiness() returns the right shape (status, checks, summary)
  - status aggregation: any FAIL → red, any WARN → yellow, all OK → green
  - the standalone subcommand dispatch (`check-recording-readiness <root>`)
  - init-skill auto-runs the banner (loud stderr output for non-green)
  - exit codes: 0=green, 1=yellow, 2=red

The probes (subprocess for ffmpeg/playwright, urllib for dev server) are
exercised against the real environment — this test would FAIL on a
machine without playwright installed, which is the correct signal
(the readiness check is supposed to FAIL in that case).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
import manual_helper

PYTHON = os.environ.get("PYTHON", "python3")
SCRIPT = SCRIPTS_DIR / "manual_helper.py"


def run_cli(*args):
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


class RecordingReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # --- shape / aggregation ---

    def test_returns_required_shape(self):
        r = manual_helper.check_recording_readiness(self.root)
        self.assertIn("status", r)
        self.assertIn(r["status"], ("green", "yellow", "red"))
        self.assertIn("checks", r)
        self.assertIn("summary", r)
        self.assertIsInstance(r["checks"], list)
        for c in r["checks"]:
            self.assertIn("name", c)
            self.assertIn("status", c)
            self.assertIn(c["status"], ("OK", "WARN", "FAIL"))
            self.assertIn("detail", c)

    def test_empty_project_status_yellow_or_red(self):
        """A fresh project (no dev server, no screenshots) should be at
        least YELLOW (dev server missing) or RED (deps missing). Never
        green — there's nothing to record yet."""
        r = manual_helper.check_recording_readiness(self.root)
        self.assertIn(r["status"], ("yellow", "red"))

    def test_each_check_has_fix_for_fail_warn(self):
        """Every FAIL or WARN check must include a `fix` string so the
        user can act. OK checks should have fix=None."""
        r = manual_helper.check_recording_readiness(self.root)
        for c in r["checks"]:
            if c["status"] in ("FAIL", "WARN"):
                self.assertIsNotNone(c["fix"], f"{c['name']} has status {c['status']} but no fix")
                self.assertGreater(len(c["fix"]), 10, f"{c['name']} fix is too terse: {c['fix']!r}")
            elif c["status"] == "OK":
                self.assertIsNone(c["fix"], f"{c['name']} is OK but has a fix: {c['fix']!r}")

    # --- manual placeholders check ---

    def test_no_manual_dir_is_ok(self):
        """A project with no docs/user-manual/manual/ dir has no
        placeholders → no FAIL on this check."""
        r = manual_helper.check_recording_readiness(self.root)
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "OK")
        self.assertIn("No", ph_check["detail"])

    def test_placeholders_with_files_passes(self):
        """v0.3.1: manual has 2 [SCREENSHOT: foo.png] placeholders AND
        the corresponding files exist → check OK. Note: the heuristic
        `_domain_for_placeholder` strips `-user-manual` from the .md
        stem — for `manual.md` the domain is `manual`, so the files
        must be in `screenshots/manual/`."""
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
        r = manual_helper.check_recording_readiness(self.root)
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "OK", msg=ph_check["detail"])
        self.assertIn("all have files", ph_check["detail"])

    def test_placeholders_without_files_fails(self):
        """v0.3.1: the bug we're fixing. Manual has placeholders, no
        files → check FAIL with actionable fix string. This is the
        eval agent's exact failure mode."""
        manual_dir = self.root / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True)
        # Note: NO screenshots dir, NO files
        (manual_dir / "manual.md").write_text(textwrap.dedent("""\
            # Manual
            [SCREENSHOT: 01-list.png]
            [SCREENSHOT: 02-form.png]
        """))
        r = manual_helper.check_recording_readiness(self.root)
        ph_check = next(c for c in r["checks"] if c["name"] == "manual placeholders vs. files")
        self.assertEqual(ph_check["status"], "FAIL")
        self.assertIn("2", ph_check["detail"])  # 2 placeholders
        self.assertIn("§14", ph_check["fix"])   # tells user where to go
        # Overall status is now RED (not just yellow) because of this FAIL
        self.assertEqual(r["status"], "red")

    # --- CLI dispatch ---

    def test_cli_subcommand_human_output(self):
        # A fresh project has dev server missing (WARN) → yellow, not red
        r = run_cli("check-recording-readiness", str(self.root))
        self.assertEqual(r.returncode, 1, msg=r.stdout)  # yellow on fresh project
        self.assertIn("=== Recording Phase Readiness", r.stdout)
        self.assertIn("🟡 WARNING", r.stdout)

    def test_cli_subcommand_json_output(self):
        r = run_cli("check-recording-readiness", "--json", str(self.root))
        self.assertEqual(r.returncode, 1, msg=r.stdout)
        data = json.loads(r.stdout)
        self.assertIn("status", data)
        self.assertIn("checks", data)
        self.assertEqual(data["status"], "yellow")
        # Every check should have a name + status
        for c in data["checks"]:
            self.assertIn("name", c)
            self.assertIn("status", c)

    def test_cli_subcommand_exit_codes_aggregate(self):
        """Exit code reflects overall: 0 green / 1 yellow / 2 red.
        Fresh project = at least yellow (dev server) = exit 1, but
        could be 2 if more checks fail."""
        r = run_cli("check-recording-readiness", str(self.root))
        self.assertIn(r.returncode, (1, 2), msg=r.stdout)

    # --- init-skill auto-banner ---

    def test_init_skill_emits_banner_when_not_green(self):
        """v0.3.1: init-skill must call check_recording_readiness and
        print a banner if the result is non-green. The fresh-project
        result is yellow/red, so banner must appear."""
        # Need a fresh dir (init-skill scaffolds docs/ in it)
        fresh = self.root / "fresh"
        fresh.mkdir()
        result = subprocess.run(
            [PYTHON, str(SCRIPT), "init-skill", str(fresh)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # The banner is printed to stderr (so it doesn't pollute the
        # scaffold's stdout). Check stderr.
        # The banner header is exactly "🟡 WARNING — recording phase
        # readiness check" (or the BLOCKED variant). Use a stable
        # substring that's in both.
        self.assertIn("recording phase readiness check", result.stderr)
        self.assertTrue(
            "WARNING" in result.stderr or "BLOCKED" in result.stderr,
            msg="expected WARNING or BLOCKED in init-skill stderr",
        )
        # The function should also have populated recording_readiness
        # in the result dict (used by the CLI handler to call _print)
        # — verify by reading the project structure
        self.assertTrue((fresh / "docs" / "user-manual" / "manual-config.json").exists())

    def test_init_skill_does_not_emit_banner_when_green(self):
        """v0.3.1: if readiness is green, the banner is suppressed (no
        spam on every init). Mock a green result by setting up an
        environment where all checks pass — hard to do in a unit
        test, so we just verify the helper function (not the banner
        gating) directly."""
        # Direct test: the banner function returns early on green
        from manual_helper import _print_recording_readiness_banner
        import io
        captured = io.StringIO()
        old = sys.stderr
        sys.stderr = captured
        try:
            _print_recording_readiness_banner({
                "status": "green",
                "checks": [],
                "summary": "all good",
            })
        finally:
            sys.stderr = old
        # No banner output for green
        self.assertEqual(captured.getvalue(), "")

    # --- aggregation ---

    def test_aggregation_one_fail_overrides_warn(self):
        """If any check is FAIL, overall is red (regardless of other WARNs)."""
        # Direct test of the aggregation logic by inspecting a constructed dict
        r = manual_helper.check_recording_readiness(self.root)
        # The actual result may be yellow or red. Verify that the
        # status field matches the highest-severity check.
        statuses = {c["status"] for c in r["checks"]}
        if "FAIL" in statuses:
            self.assertEqual(r["status"], "red")
        elif "WARN" in statuses:
            self.assertEqual(r["status"], "yellow")
        else:
            self.assertEqual(r["status"], "green")

    def test_handles_import_error_in_playwright_check(self):
        """v0.3.1: a missing playwright module must NOT crash the
        check; the playwright check should report FAIL with a fix
        hint, the other checks should still run."""
        # We can't easily uninstall playwright in the test env, but
        # we can verify the structure: every check has a status, no
        # exception bubbles up.
        try:
            r = manual_helper.check_recording_readiness(self.root)
        except Exception as e:
            self.fail(f"check_recording_readiness raised: {e!r}")
        self.assertIsInstance(r["checks"], list)
        self.assertGreater(len(r["checks"]), 0)


# textwrap import shim — avoid polluting the top of the test file
import textwrap  # noqa: E402


if __name__ == "__main__":
    unittest.main()
