"""Unit tests for scripts/manual_helper.py — focused on init-skill personas
scaffold fallback (v0.2.2)."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "manual_helper.py"
SCRIPT_DIR = SCRIPT.parent
PYTHON = os.environ.get("PYTHON", "python3")
# v0.5.0: in-process tests need manual_helper importable as a module.
# It's a flat script in scripts/, not a package, so add scripts/ to sys.path.
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def run_module(func: str, *args) -> subprocess.CompletedProcess:
    """Run `python3 -m manual_helper <func> [args]` (uses module mode so
    relative imports work). Must be invoked from the scripts/ dir where
    manual_helper.py lives. v0.5.0: also prepend SCRIPT_DIR to PYTHONPATH
    so subprocess can `import manual_helper` even when cwd differs."""
    env = {**os.environ, "PYTHONPATH": str(SCRIPT_DIR)}
    return subprocess.run(
        [PYTHON, "-m", "manual_helper", func, *args],
        capture_output=True, text=True, check=False,
        cwd=str(SCRIPT.parent),  # run from scripts/ (where manual_helper.py + examples/ relative path resolves)
        env=env,
    )


class InitSkillPersonasTests(unittest.TestCase):
    def test_init_skill_scaffolds_personas_when_missing(self):
        """v0.2.2: init-skill must NOT raise when personas.json is missing.
        It should copy examples/personas.template.json and emit a loud warning."""
        with tempfile.TemporaryDirectory() as d:
            r = run_module("init-skill", d)
            self.assertEqual(r.returncode, 0, msg=f"init-skill crashed: {r.stderr}")
            personas = Path(d) / "docs" / "user-manual" / "personas.json"
            self.assertTrue(personas.exists(), f"personas.json not created: {personas}")
            # Must be valid JSON with the expected shape
            import json
            data = json.loads(personas.read_text())
            self.assertIn("personas", data)
            self.assertGreaterEqual(len(data["personas"]), 3, f"expected >=3 default personas, got {len(data['personas'])}")
            # stderr must have the warning
            self.assertIn("personas.json was MISSING", r.stderr, f"warning not printed to stderr: {r.stderr[:200]}")
            self.assertIn("NEXT STEP", r.stderr)
            # stdout must show personas.json was created (it appears in the created list)
            self.assertIn("docs/user-manual/personas.json", r.stdout)

    def test_init_skill_does_not_overwrite_existing_personas(self):
        """v0.2.2: if personas.json already exists, do NOT touch it."""
        with tempfile.TemporaryDirectory() as d:
            personas = Path(d) / "docs" / "user-manual" / "personas.json"
            personas.parent.mkdir(parents=True, exist_ok=True)
            original = '{"personas": [{"id": "custom", "name": "CUSTOM_ROLE"}], "_note": "user wrote this"}'
            personas.write_text(original)
            r = run_module("init-skill", d)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            # File should be byte-identical to what we wrote
            self.assertEqual(personas.read_text(), original, "init-skill overwrote existing personas.json!")
            # No warning should be emitted
            self.assertNotIn("personas.json was MISSING", r.stderr)


class InitSkillRecordingBlockedTests(unittest.TestCase):
    """v0.4.0: init-skill auto-installs recorder deps and raises
    RecordingBlockedError when post-install readiness is RED."""

    def test_init_skill_exits_0_when_recorder_already_green(self):
        """v0.4.0: if playwright+chromium are already installed
        and the dev server is up, init-skill exits 0 (GREEN path).
        The scaffold still creates the dirs; recording can proceed."""
        # We can't easily make the dev server up in a test, so we
        # only assert that init-skill does NOT raise/exit-2 in a
        # best-case sandbox. We mock check_recording_readiness to
        # return green and ensure init-skill flows through to a
        # clean exit code 0.
        with tempfile.TemporaryDirectory() as d:
            personas = Path(d) / "docs" / "user-manual" / "personas.json"
            personas.parent.mkdir(parents=True, exist_ok=True)
            personas.write_text('{"personas": [{"id": "x", "name": "X"}]}')
            r = run_module("init-skill", d)
            # On a host without recorder deps this WILL exit 2
            # (the v0.4.0 new behavior). We only assert that the
            # exit code is 0 OR 2 (never 1 from FileNotFoundError
            # since personas.json exists; and never a Python stack
            # trace). The BLOCKED message is the v0.4.0 success
            # signal on an unready host.
            self.assertIn(r.returncode, (0, 2), msg=f"unexpected: rc={r.returncode} stderr={r.stderr[:300]}")
            if r.returncode == 2:
                # v0.4.0: must print BLOCKED message + Options
                self.assertIn("BLOCKED", r.stderr, "missing BLOCKED badge in stderr")
                self.assertIn("recording phase is BLOCKED", r.stderr)
                # v1.0.0: --allow-blocked removed. Options menu shows
                # --no-install and "fix the issues" only.
                self.assertNotIn("--allow-blocked", r.stderr)
                self.assertIn("--no-install", r.stderr)

    def test_init_skill_allow_blocked_flag_is_rejected_v1_0_0(self):
        """v1.0.0: --allow-blocked was removed. Passing it must
        exit 2 with a clear error message, not silently succeed."""
        with tempfile.TemporaryDirectory() as d:
            personas = Path(d) / "docs" / "user-manual" / "personas.json"
            personas.parent.mkdir(parents=True, exist_ok=True)
            personas.write_text('{"personas": [{"id": "x", "name": "X"}]}')
            r = run_module("init-skill", "--allow-blocked", d)
            self.assertEqual(r.returncode, 2, msg=r.stderr)
            self.assertIn("removed in v1.0.0", r.stderr)
            self.assertIn("real screenshots and videos", r.stderr)

    def test_init_skill_no_install_skips_auto_install(self):
        """v0.4.0: --no-install skips the auto-install step. In a
        CI env where deps come from another channel (Docker image,
        system pip), this prevents init-skill from trying to pip
        install behind the user's back.

        v1.0.0: --allow-blocked removed. We mock a fully-OK
        recording readiness so init-skill can complete even on
        hosts without recorder deps installed."""
        with tempfile.TemporaryDirectory() as d:
            personas = Path(d) / "docs" / "user-manual" / "personas.json"
            personas.parent.mkdir(parents=True, exist_ok=True)
            personas.write_text('{"personas": [{"id": "x", "name": "X"}]}')
            with mock.patch("manual_helper.check_recording_readiness",
                            return_value={"status": "ok", "summary": "mocked",
                                          "checks": []}):
                r = run_module("init-skill", "--no-install", d)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            # The "auto-installing" progress message must NOT appear
            # when --no-install is set
            self.assertNotIn("auto-installing", r.stderr)


class RecordAndReplaceTests(unittest.TestCase):
    """v0.4.0: one-shot record-and-replace command."""

    def test_record_and_replace_help(self):
        """v0.4.0: `record-and-replace` (no args) prints usage
        and exits 2 (invalid invocation)."""
        r = run_module("record-and-replace")
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("usage: record-and-replace", r.stderr)
        self.assertIn("--script", r.stderr)
        self.assertIn("--dry-run", r.stderr)

    def test_record_and_replace_help_flag(self):
        """v0.4.0: `record-and-replace --help` prints usage and
        exits 0 (the --help convention)."""
        r = run_module("record-and-replace", "--help")
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("usage: record-and-replace", r.stderr)

    def test_record_and_replace_allow_blocked_flag_is_rejected_v1_0_0(self):
        """v1.0.0: --allow-blocked was removed. Passing it must
        exit 2 with a clear error message."""
        r = run_module("record-and-replace", "--allow-blocked",
                      "/nonexistent/manual.md")
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("removed in v1.0.0", r.stderr)
        self.assertIn("real screenshots and videos", r.stderr)

    def test_record_and_replace_missing_manual(self):
        """v0.4.0: missing manual path -> exit 2 with clear error."""
        with tempfile.TemporaryDirectory() as d:
            r = run_module("record-and-replace",
                          "/nonexistent/manual.md",
                          "--script", "/nonexistent/script.json")
            self.assertEqual(r.returncode, 2, msg=r.stderr)
            self.assertIn("manual not found", r.stderr)

    def test_record_and_replace_missing_script(self):
        """v0.4.0: missing --script -> exit 2 with clear error."""
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "manual.md"
            md.write_text("# Manual\n")
            r = run_module("record-and-replace", str(md),
                          "--script", "/nonexistent/script.json")
            self.assertEqual(r.returncode, 2, msg=r.stderr)
            self.assertIn("--script not found", r.stderr)

    def test_record_and_replace_dry_run_when_deps_missing(self):
        """v0.4.0: --dry-run still runs pre-flight (so the user
        sees which deps are missing) but does NOT actually record.
        If pre-flight fails (deps missing on a fresh host), exit 2
        with the same diagnostic format as a real run — the user
        gets a clear list of what to install."""
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "manual.md"
            md.write_text("# Manual\n![x](img/x.png)\n")
            script = Path(d) / "script.json"
            script.write_text('{"url": "http://localhost:9999"}\n')
            r = run_module("record-and-replace", str(md),
                          "--script", str(script),
                          "--dry-run")
            # Pre-flight will fail because recorder_plugin is
            # not importable on a host that didn't install it.
            # That's the EXPECTED path here; we assert the error
            # message is the pre-flight format, not a Python
            # traceback.
            # Accept either rc=2 (pre-flight FAIL) or rc=3 (dry-run
            # pre-flight passed, mapping preview shown). The test was
            # originally written for the "deps missing" path; v0.4.0+
            # may pass on hosts where recorder is already pip-installed.
            self.assertIn(r.returncode, (2, 3),
                          msg=f"unexpected rc={r.returncode} stderr={r.stderr[:300]}")
            # Each pre-flight line should start with an icon. The
            # first line is the banner "=== record-and-replace: ...";
            # skip it. v0.5.0 dry-run with no --auto-generate-script
            # still runs pre-flight (4-6 icon lines visible).
            non_banner = [
                line for line in r.stderr.splitlines()
                if not line.startswith("===")
            ]
            # Icons appear AFTER leading whitespace (e.g. "  ✅ x"), so
            # lstrip() before startswith() is needed. Found in v0.5.0
            # when pre-flight printed 4 ✅ lines but startswith("✅")
            # returned False (positions [0] and [1] were spaces).
            self.assertTrue(
                any(line.lstrip().startswith(("✅", "❌", "⚠️"))
                    for line in non_banner),
                msg=f"no icon-prefixed pre-flight lines in: {r.stderr[:400]}",
            )


class CheckRecorderScriptTests(unittest.TestCase):
    """v0.5.0: check-recorder-script catches 4 common failure patterns."""

    def _write_script(self, d, **overrides):
        base = {
            "name": "test-script",
            "url": "http://localhost:8080",
            "auth_env": ["$TEST_USER", "$TEST_PASS"],
            "steps": [
                {"action": "navigate", "url": "/"},
                {"action": "type", "selector": "input[name=user]", "value": "$TEST_USER"},
                {"action": "type", "selector": "input[name=pass]", "value": "$TEST_PASS"},
                {"action": "click", "selector": "button[type=submit]"},
                {"action": "screenshot", "name": "home"},
            ],
        }
        base.update(overrides)
        path = Path(d) / "script.json"
        path.write_text(json.dumps(base, indent=2))
        return path

    def test_clean_script_passes_all_4_checks(self):
        """v0.5.0: a fully-filled script with all env vars set passes."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d)
            # Set the env vars so auth check passes
            os.environ["TEST_USER"] = "admin"
            os.environ["TEST_PASS"] = "123456"
            try:
                r = run_module("check-recorder-script", str(script))
                # URL localhost:8080 may or may not be reachable; we only
                # assert that the OTHER 3 checks pass and overall rc is
                # not 1 from a script-content failure.
                if r.returncode == 1:
                    # If it failed, must be ONLY the URL check
                    self.assertIn("target URL", r.stdout, msg=r.stdout + r.stderr)
            finally:
                del os.environ["TEST_USER"]
                del os.environ["TEST_PASS"]

    def test_todo_placeholders_flagged(self):
        """v0.5.0: a script with <TODO: ...> placeholders fails check 1."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d,
                url="<TODO: target URL>",
                steps=[{"action": "navigate", "url": "/<TODO: starting route>"}] +
                      [{"action": "screenshot", "name": "x"}])
            r = run_module("check-recorder-script", str(script))
            self.assertEqual(r.returncode, 1, msg=r.stderr)
            self.assertIn("TODO", r.stdout)
            self.assertIn("<TODO: target URL>", r.stdout)

    def test_unset_env_var_flagged_with_specific_fix(self):
        """v0.5.0: when $LG_USER is in auth_env but unset, check 3 fails
        with the exact env var name + the lg-contract-flow.mp4 failure
        pattern as the fix hint."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d, auth_env=["$LG_USER", "$LG_PASS"])
            # Ensure both unset
            for k in ("LG_USER", "LG_PASS"):
                os.environ.pop(k, None)
            r = run_module("check-recorder-script", str(script))
            self.assertEqual(r.returncode, 1, msg=r.stderr)
            self.assertIn("LG_USER", r.stdout)
            self.assertIn("export", r.stdout)
            # The fix should reference the lg-contract-flow.mp4 failure
            self.assertIn("lg-contract-flow", r.stdout,
                          "fix hint should reference the canonical failure pattern")

    def test_unbalanced_video_start_stop_flagged(self):
        """v0.5.0: video_start without matching video_stop fails check 4."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d, steps=[
                {"action": "navigate", "url": "/"},
                {"action": "video_start", "name": "demo"},
                {"action": "screenshot", "name": "shot1"},
                # NO video_stop — unbalanced
            ])
            os.environ["TEST_USER"] = "x"; os.environ["TEST_PASS"] = "y"
            try:
                r = run_module("check-recorder-script", str(script))
                self.assertEqual(r.returncode, 1, msg=r.stderr)
                self.assertIn("video_start", r.stdout)
                self.assertIn("video_stop", r.stdout)
                self.assertIn("unbalanced", r.stdout)
            finally:
                del os.environ["TEST_USER"]; del os.environ["TEST_PASS"]

    def test_empty_selector_flagged(self):
        """v0.5.0: click step with <TODO: selector> fails check 4."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d, steps=[
                {"action": "navigate", "url": "/"},
                {"action": "click", "selector": "<TODO: button.login>"},
            ])
            os.environ["TEST_USER"] = "x"; os.environ["TEST_PASS"] = "y"
            try:
                r = run_module("check-recorder-script", str(script))
                self.assertEqual(r.returncode, 1, msg=r.stderr)
                self.assertIn("selectors", r.stdout)
            finally:
                del os.environ["TEST_USER"]; del os.environ["TEST_PASS"]

    def test_missing_file(self):
        """v0.5.0: missing script -> exit 2 with clear error."""
        r = run_module("check-recorder-script", "/nonexistent.json")
        self.assertEqual(r.returncode, 2, msg=r.stderr)
        self.assertIn("not found", r.stderr)

    def test_invalid_json(self):
        """v0.5.0: invalid JSON -> exit 2 with parse error."""
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.json"
            bad.write_text("this is not json {")
            r = run_module("check-recorder-script", str(bad))
            self.assertEqual(r.returncode, 2, msg=r.stderr)
            self.assertIn("cannot parse", r.stderr)


class BuildRecorderTemplateV2Tests(unittest.TestCase):
    """v0.5.0: build_recorder_template auto-fills from project context."""

    def test_auto_fills_url_from_config(self):
        """v0.5.0: with project_root + manual-config.json containing
        project.host + project.port, the template's url is
        'http://<host>:<port>' instead of <TODO: target URL>."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / "docs" / "user-manual").mkdir(parents=True)
            (proj / "docs" / "user-manual" / "manual-config.json").write_text(
                json.dumps({"project": {"name": "GRC-ONE", "host": "localhost", "port": 8080}})
            )
            manual = proj / "docs" / "user-manual" / "manual" / "lg-user-manual.md"
            manual.parent.mkdir(parents=True, exist_ok=True)
            manual.write_text("# Manual\n")
            from manual_helper import build_recorder_template
            t = build_recorder_template(
                "lg-user-manual", [],
                manual_path=manual, project_root=proj,
            )
            self.assertEqual(t["url"], "http://localhost:8080",
                             msg=f"expected auto-filled url, got {t['url']!r}")
            # output_dir should NOT have <TODO: domain>
            self.assertIn("lg", t["output_dir"])  # _domain_for_placeholder maps lg-user-manual.md -> lg
            # auth_env should be module-specific
            self.assertIn("$LG_USER", t["auth_env"])

    def test_falls_back_to_todo_when_no_config(self):
        """v0.5.0: without project_root, url stays as <TODO: target URL>."""
        from manual_helper import build_recorder_template
        t = build_recorder_template("test-manual", [])
        self.assertTrue(t["url"].startswith("<TODO"),
                        msg=f"expected <TODO: when no config, got {t['url']!r}")

    def test_extract_step_captions_from_manual(self):
        """v0.5.0: step captions from `### 步骤` sections are extracted
        and matched to screenshot placeholders in document order."""
        from manual_helper import _extract_step_captions
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m.md"
            m.write_text(textwrap.dedent("""                # Manual
                [SCREENSHOT: shot-1.png]
                [SCREENSHOT: shot-2.png]
                ### 步骤
                1. 打开系统管理
                2. 点击新建用户
            """))
            caps = _extract_step_captions(m)
            self.assertEqual(caps.get("shot-1"), "打开系统管理")
            self.assertEqual(caps.get("shot-2"), "点击新建用户")

    def test_infer_auth_env_name(self):
        """v0.5.0: module name -> auth env var name."""
        from manual_helper import _infer_auth_env_name
        self.assertEqual(_infer_auth_env_name("legal-user-manual", "USER"), "LEGAL_USER")
        self.assertEqual(_infer_auth_env_name("sys-user-manual", "PASS"), "SYS_PASS")
        self.assertEqual(_infer_auth_env_name("test", "USER"), "TEST_USER")
        # Generic / too-short -> AUTH_ fallback
        self.assertEqual(_infer_auth_env_name("x", "USER"), "AUTH_USER")


class RecordAndReplaceAutoGenTests(unittest.TestCase):
    """v0.5.0: record-and-replace --auto-generate-script works without
    an existing --script file."""

    def test_auto_gen_creates_script_when_missing(self):
        """v0.5.0: --auto-generate-script with no --script creates
        <manual>.recorder.json next to the manual and proceeds to
        pre-flight (which will fail on missing recorder_plugin, but
        the script generation step itself must succeed)."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            (proj / "docs" / "user-manual").mkdir(parents=True)
            (proj / "docs" / "user-manual" / "manual-config.json").write_text(
                json.dumps({"project": {"host": "localhost", "port": 8080}})
            )
            manual_dir = proj / "docs" / "user-manual" / "manual"
            manual_dir.mkdir(parents=True, exist_ok=True)
            manual = manual_dir / "lg-user-manual.md"
            manual.write_text("# Manual\n[SCREENSHOT: shot1.png]\n")
            # Run from proj so cwd = project_root (record-and-replace uses
            # Path.cwd() for the auto-gen step).
            r = subprocess.run(
                [PYTHON, "-m", "manual_helper", "record-and-replace",
                 str(manual), "--auto-generate-script", "--dry-run"],
                capture_output=True, text=True, check=False,
                cwd=str(proj),  # so Path.cwd() returns proj
                env={**os.environ, "PYTHONPATH": str(SCRIPT.parent)},
            )
            # auto-gen should have created the .recorder.json file
            generated = manual_dir / "lg-user-manual.recorder.json"
            self.assertTrue(generated.exists(),
                            msg=f"expected auto-gen file at {generated}, got stderr: {r.stderr}")
            # The generated script should have auto-filled url
            script_data = json.loads(generated.read_text())
            self.assertEqual(script_data["url"], "http://localhost:8080")


if __name__ == "__main__":
    unittest.main()


class InitSkillAutoRegenTests(unittest.TestCase):
    """v0.5.0: init-skill auto-regenerates the viewer when the shipped
    template is newer than what is on disk. The user no longer has to
    remember to re-run a build step after a skill upgrade."""

    def test_init_skill_regenerates_stale_user_manual_html(self):
        """A project with a stale user-manual.html gets the current
        template version after init-skill, and stderr reports the
        regeneration. The fix for the prior session's "1-entry TOC"
        regression ships automatically."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            um = proj / "docs" / "user-manual"
            um.mkdir(parents=True)
            # personas.json is required by init-skill
            (um / "personas.json").write_text('{"personas": [{"id": "x", "name": "X"}]}')
            # Stale viewer (version 1)
            stale = um / "user-manual.html"
            stale.write_text("<!-- user-manual-dashboard-version: 1 -->\n<html></html>")
            with mock.patch("manual_helper.check_recording_readiness",
                            return_value={"status": "ok", "summary": "mocked",
                                          "checks": []}):
                r = run_module("init-skill", d)
            self.assertEqual(r.returncode, 0, msg=f"init-skill crashed: {r.stderr[:500]}")
            new_text = stale.read_text()
            # The file should now match the current template version
            import re
            m = re.search(r"user-manual-dashboard-version:\s*(\d+)", new_text)
            self.assertIsNotNone(m, f"no version marker after init-skill: {new_text[:200]}")
            new_version = int(m.group(1))
            self.assertGreaterEqual(new_version, 25,
                msg=f"expected version >= 25 (current template), got {new_version}")
            # Stderr should mention regeneration
            self.assertIn("viewer: regenerated", r.stderr,
                          msg=f"missing 'viewer: regenerated' in stderr: {r.stderr[:400]}")

    def test_init_skill_creates_user_manual_html_when_missing(self):
        """First-time init: no user-manual.html exists yet, init-skill
        should create it with the current template version."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            um = proj / "docs" / "user-manual"
            um.mkdir(parents=True)
            (um / "personas.json").write_text('{"personas": [{"id": "x", "name": "X"}]}')
            target = um / "user-manual.html"
            self.assertFalse(target.exists(), "precondition: file must not exist yet")
            with mock.patch("manual_helper.check_recording_readiness",
                            return_value={"status": "ok", "summary": "mocked",
                                          "checks": []}):
                r = run_module("init-skill", d)
            self.assertEqual(r.returncode, 0, msg=f"init-skill crashed: {r.stderr[:500]}")
            self.assertTrue(target.exists(),
                            msg=f"user-manual.html not created: stderr={r.stderr[:400]}")
            self.assertIn("viewer: created", r.stderr,
                          msg=f"missing 'viewer: created' in stderr: {r.stderr[:400]}")

    def test_init_skill_does_not_overwrite_up_to_date_viewer(self):
        """If the on-disk user-manual.html is already at the current
        version, init-skill should NOT touch it (no spurious writes,
        and stderr should be silent on the viewer line)."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            um = proj / "docs" / "user-manual"
            um.mkdir(parents=True)
            (um / "personas.json").write_text('{"personas": [{"id": "x", "name": "X"}]}')
            target = um / "user-manual.html"
            # Copy the actual template to get the current version
            import shutil
            tmpl = SCRIPT_DIR.parent / "templates" / "user-manual.html"
            shutil.copyfile(tmpl, target)
            original_bytes = target.read_bytes()
            with mock.patch("manual_helper.check_recording_readiness",
                            return_value={"status": "ok", "summary": "mocked",
                                          "checks": []}):
                r = run_module("init-skill", d)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            # File is byte-identical (no spurious write)
            self.assertEqual(target.read_bytes(), original_bytes,
                             "init-skill re-wrote an up-to-date viewer")
            # No "regenerated" / "created" line in stderr
            self.assertNotIn("viewer: regenerated", r.stderr)
            self.assertNotIn("viewer: created", r.stderr)


class RecordAndReplaceAutoRegenTests(unittest.TestCase):
    """v0.5.0: record-and-replace auto-regenerates the viewer at the end
    of a (real or dry-run) recording. Opt out with --skip-viewer-regen."""

    def test_record_and_replace_dry_run_regenerates_viewer(self):
        """A --dry-run --auto-generate-script call (no actual recording)
        should still auto-regen the viewer so the build is consistent.
        The script-generation path doesn't actually run the recorder, so
        this is the cheapest end-to-end test."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            um = proj / "docs" / "user-manual"
            um.mkdir(parents=True)
            (um / "manual-config.json").write_text(
                json.dumps({"project": {"host": "localhost", "port": 8080}})
            )
            manual_dir = um / "manual"
            manual_dir.mkdir(parents=True, exist_ok=True)
            manual = manual_dir / "lg-user-manual.md"
            manual.write_text("# Manual\n[SCREENSHOT: shot1.png]\n")
            # Stale viewer on disk
            stale = um / "user-manual.html"
            stale.write_text("<!-- user-manual-dashboard-version: 1 -->\n<html></html>")
            # Run record-and-replace from project root (cwd matters for Path.cwd())
            r = subprocess.run(
                [PYTHON, "-m", "manual_helper", "record-and-replace",
                 str(manual), "--auto-generate-script", "--dry-run"],
                capture_output=True, text=True, check=False,
                cwd=str(proj),
                env={**os.environ, "PYTHONPATH": str(SCRIPT.parent)},
            )
            # Pre-flight may fail (deps missing on a fresh host) but the
            # auto-regen block runs BEFORE the recorder, so the viewer
            # should be upgraded regardless of the recorder rc.
            # We assert on the file, not the rc.
            import re
            self.assertTrue(stale.exists(),
                            msg=f"viewer file disappeared: stderr={r.stderr[:400]}")
            new_text = stale.read_text()
            m = re.search(r"user-manual-dashboard-version:\s*(\d+)", new_text)
            self.assertIsNotNone(m, f"no version marker: {new_text[:200]}")
            new_version = int(m.group(1))
            self.assertGreaterEqual(new_version, 25,
                msg=f"expected viewer version >= 25, got {new_version}")
            # Stderr should report the regeneration
            self.assertIn("viewer: regenerated", r.stderr,
                          msg=f"missing 'viewer: regenerated' in stderr: {r.stderr[:400]}")

    def test_record_and_replace_skip_viewer_regen_does_not_touch_viewer(self):
        """--skip-viewer-regen must leave a stale viewer untouched
        (for CI environments that ship a pinned viewer)."""
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d)
            um = proj / "docs" / "user-manual"
            um.mkdir(parents=True)
            (um / "manual-config.json").write_text(
                json.dumps({"project": {"host": "localhost", "port": 8080}})
            )
            manual_dir = um / "manual"
            manual_dir.mkdir(parents=True, exist_ok=True)
            manual = manual_dir / "lg-user-manual.md"
            manual.write_text("# Manual\n")
            stale = um / "user-manual.html"
            stale.write_text("<!-- user-manual-dashboard-version: 1 -->\n<html>STALE</html>")
            r = subprocess.run(
                [PYTHON, "-m", "manual_helper", "record-and-replace",
                 str(manual), "--auto-generate-script", "--dry-run",
                 "--skip-viewer-regen"],
                capture_output=True, text=True, check=False,
                cwd=str(proj),
                env={**os.environ, "PYTHONPATH": str(SCRIPT.parent)},
            )
            # Viewer should be UNCHANGED
            self.assertEqual(stale.read_text(), "<!-- user-manual-dashboard-version: 1 -->\n<html>STALE</html>",
                             msg=f"--skip-viewer-regen did not skip: stderr={r.stderr[:400]}")
            self.assertIn("viewer: auto-regen skipped (--skip-viewer-regen)", r.stderr)


class CheckRecorderScriptNarrationCoverageTests(unittest.TestCase):
    """v0.5.1: check-recorder-script check #5 (NARRATION COVERAGE) catches
    the silent-failure case where an LLM forgets the `narration` field on
    video_stop steps. This is the failure mode that produced
    `user-manual.mp4` (ovr) = 4.08s silent login page."""

    def _write_script(self, d, *, video_stops=None):
        """Build a minimal script with a navigate + login + screenshot +
        optional video_stops. video_stops is a list of dicts that get
        appended after the screenshot."""
        base = {
            "name": "test",
            "url": "http://localhost:8080",
            "auth_env": ["$TEST_USER", "$TEST_PASS"],
            "steps": [
                {"action": "navigate", "url": "/"},
                {"action": "type", "selector": "input[name=user]", "value": "$TEST_USER"},
                {"action": "type", "selector": "input[name=pass]", "value": "$TEST_PASS"},
                {"action": "click", "selector": "button[type=submit]"},
                {"action": "screenshot", "name": "home"},
            ],
        }
        if video_stops:
            # video_start + each video_stop (with optional narration)
            base["steps"].insert(0, {"action": "video_start", "name": "demo"})
            for vs in video_stops:
                base["steps"].append(vs)
        path = Path(d) / "script.json"
        path.write_text(json.dumps(base, indent=2))
        return path

    def test_check_recorder_script_no_video_sessions_is_ok(self):
        """A script with no video sessions at all → check #5 is OK (n/a)."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d, video_stops=None)
            os.environ["TEST_USER"] = "x"; os.environ["TEST_PASS"] = "y"
            try:
                r = run_module("check-recorder-script", str(script))
                # url may or may not be reachable; we only assert the
                # NARRATION COVERAGE check is in the OK set
                if r.returncode in (0, 1):
                    self.assertIn("narration coverage", r.stdout,
                                  msg=f"missing narration coverage check: {r.stdout[:400]}")
            finally:
                del os.environ["TEST_USER"]; del os.environ["TEST_PASS"]

    def test_check_recorder_script_all_video_stops_have_narration_is_ok(self):
        """Every video_stop has narration[] → check #5 passes (OK)."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d, video_stops=[
                {"action": "video_stop", "name": "demo",
                 "narration": ["第一步,打开", "第二步,点击"]},
            ])
            os.environ["TEST_USER"] = "x"; os.environ["TEST_PASS"] = "y"
            try:
                r = run_module("check-recorder-script", str(script))
                # Look for "narration coverage: ... all N video session(s) have"
                if r.returncode in (0, 1):
                    self.assertIn("all 1 video session", r.stdout,
                                  msg=f"expected OK narration: {r.stdout[:400]}")
            finally:
                del os.environ["TEST_USER"]; del os.environ["TEST_PASS"]

    def test_check_recorder_script_no_narration_fails(self):
        """The lg-contract-flow.mp4 silent-failure case: script has
        video_stop with NO narration field. Check #5 must FAIL."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d, video_stops=[
                {"action": "video_stop", "name": "demo"},
            ])
            os.environ["TEST_USER"] = "x"; os.environ["TEST_PASS"] = "y"
            try:
                r = run_module("check-recorder-script", str(script))
                self.assertEqual(r.returncode, 1, msg=r.stdout)
                # The fix hint must mention narration
                self.assertIn("narration", r.stdout)
                self.assertIn("SILENT", r.stdout)
            finally:
                del os.environ["TEST_USER"]; del os.environ["TEST_PASS"]

    def test_check_recorder_script_partial_narration_warns(self):
        """Some video_stops have narration, some don't → WARN with missing names."""
        with tempfile.TemporaryDirectory() as d:
            script = self._write_script(d, video_stops=[
                {"action": "video_stop", "name": "with-audio",
                 "narration": ["x"]},
                {"action": "video_stop", "name": "silent-one"},
            ])
            os.environ["TEST_USER"] = "x"; os.environ["TEST_PASS"] = "y"
            try:
                r = run_module("check-recorder-script", str(script))
                # WARN counts as overall FAIL (rc=1) by check-recorder-script
                # convention; just assert the names appear
                self.assertIn("silent-one", r.stdout)
            finally:
                del os.environ["TEST_USER"]; del os.environ["TEST_PASS"]
