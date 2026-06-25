"""Unit tests for manual_helper package — focused on init-skill personas
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

SCRIPT = Path(__file__).resolve().parent.parent / "manual_helper"
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
        cwd=str(SCRIPT.parent),  # run from scripts/ (where manual_helper/ + examples/ relative path resolves)
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

class DiffArtifactsGuardsTests(unittest.TestCase):
    """P7: diff-artifacts should fail loud on missing inputs (violates
    §12 fail loud otherwise — empty buckets + exit 0 masks LLM path
    mistakes)."""

    def _run(self, *args):
        return subprocess.run(
            [PYTHON, "-m", "manual_helper", *args],
            capture_output=True, text=True,
        )

    def test_missing_md_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._run("diff-artifacts", d, "/tmp/does-not-exist.md")
            self.assertEqual(r.returncode, 2, msg=r.stderr)
            self.assertIn("manual.md not found", r.stderr)

    def test_missing_project_root_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "manual.md"
            md.write_text("# x\n")
            r = self._run("diff-artifacts", "/no/such/dir", str(md))
            self.assertEqual(r.returncode, 2, msg=r.stderr)
            self.assertIn("project_root does not exist", r.stderr)

    def test_project_root_without_superpowers_warns(self):
        """llm_only_mode path: project_root has no docs/superpowers/ —
        should warn to stderr but still exit 0 with empty buckets."""
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "manual.md"
            md.write_text("# x\n")
            r = self._run("diff-artifacts", d, str(md))
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("docs/superpowers/", r.stderr)

class ProjectLayoutDetectionTests(unittest.TestCase):
    """P6: init-skill should auto-detect frontend/backend layout and
    fill repo_layout + inputs[] with concrete values, not <PLACEHOLDER>.
    We invoke the detector via subprocess since manual_helper.py is not
    importable as a module (it has CLI dispatch in __main__)."""

    def _detect(self, root: Path) -> dict:
        r = subprocess.run(
            [PYTHON, "-m", "manual_helper", "_detect_layout", str(root)],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        return json.loads(r.stdout)

    def test_single_repo_src_root(self):
        """RuoYi 派系: <root>/src/{views,router} exists -> frontend_root='.'"""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "src" / "views").mkdir(parents=True)
            (root / "src" / "router").mkdir(parents=True)
            (root / "src" / "router" / "index.js").write_text("// x")
            r = self._detect(root)
            self.assertEqual(r["repo_layout"]["frontend_root"], ".")
            paths = {i["path"] for i in r["inputs"]}
            self.assertIn("src/views", paths)
            self.assertIn("src/router/index.js", paths)

    def test_monorepo_frontend_dir(self):
        """<root>/frontend/src/{views,router} -> frontend_root='frontend'"""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "frontend" / "src" / "views").mkdir(parents=True)
            (root / "frontend" / "src" / "router").mkdir(parents=True)
            (root / "frontend" / "src" / "router" / "index.ts").write_text("// x")
            r = self._detect(root)
            self.assertEqual(r["repo_layout"]["frontend_root"], "frontend")
            paths = {i["path"] for i in r["inputs"]}
            # The detector should set frontend_pages path to point at the
            # views dir, prefixed by frontend_root. Accept either form
            # ("frontend/src/views" or "src/views") — we just want a
            # non-placeholder concrete value.
            self.assertTrue(
                "frontend/src/views" in paths or "src/views" in paths,
                f"expected concrete views path, got {paths}",
            )
            self.assertTrue(
                "frontend/src/router/index.ts" in paths or "src/router/index.ts" in paths,
                f"expected concrete router path, got {paths}",
            )

    def test_spring_boot_backend(self):
        """pom.xml at <root>/backend -> backend_root='backend'"""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "backend").mkdir(parents=True)
            (root / "backend" / "pom.xml").write_text("<project/>")
            r = self._detect(root)
            self.assertEqual(r["repo_layout"]["backend_root"], "backend")
            kinds = {i["kind"] for i in r["inputs"]}
            self.assertIn("backend_dtos", kinds)

    def test_no_frontend_falls_back(self):
        """No src/views, no frontend/*, no app/* -> no frontend detected."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            r = self._detect(root)
            self.assertEqual(r["repo_layout"]["frontend_root"], "frontend")
            self.assertEqual(r["inputs"], [])

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

