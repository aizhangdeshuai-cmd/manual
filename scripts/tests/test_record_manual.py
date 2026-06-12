"""Tests for record-manual subcommand (v0.2.3 recording phase)."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SCRIPTS_DIR / "manual_helper.py"
PYTHON = os.environ.get("PYTHON", "python3")


def run(args, stdin=None, cwd=None):
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        capture_output=True, text=True, input=stdin, cwd=cwd or str(SCRIPTS_DIR),
    )


class RecordManualTests(unittest.TestCase):
    def test_scan_no_placeholders(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Manual\n\nNo placeholders here.\n")
            path = f.name
        try:
            r = run(["record-manual", path])
            self.assertEqual(r.returncode, 0)
            self.assertIn("NO_RECORDING_NEEDED", r.stdout)
        finally:
            os.unlink(path)

    def test_scan_with_placeholders(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: 01-list.png]
                [VIDEO: demo-flow.mp4]
                [SCREENSHOT: 02-form.png]
                [VIDEO NEEDED: missing-flow]
            """))
            path = f.name
        try:
            r = run(["record-manual", path])
            self.assertEqual(r.returncode, 0)
            self.assertIn("RECORDING_NEEDED", r.stdout)
            self.assertIn("screenshots: 2", r.stdout)
            self.assertIn("videos: 2", r.stdout)
            # All 4 placeholder names appear in the report
            for name in ("01-list", "demo-flow", "02-form", "missing-flow"):
                self.assertIn(name, r.stdout)
        finally:
            os.unlink(path)

    def test_generate_template_writes_recorder_script(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# X\n[SCREENSHOT: 01-list.png]\n[VIDEO: demo.mp4]\n")
            md = f.name
        try:
            template_path = md + ".template.json"
            try:
                r = run(["record-manual", md, "--generate-template", template_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                self.assertTrue(os.path.exists(template_path))
                data = json.loads(Path(template_path).read_text())
                self.assertIn("steps", data)
                self.assertEqual(data["name"], Path(md).stem)
                # Should have navigate + screenshot + video_start + video_stop
                actions = [s.get("action") for s in data["steps"]]
                self.assertIn("navigate", actions)
                self.assertIn("screenshot", actions)
                self.assertIn("video_start", actions)
                self.assertIn("video_stop", actions)
            finally:
                if os.path.exists(template_path):
                    os.unlink(template_path)
        finally:
            os.unlink(md)

    def test_apply_mapping_replaces_placeholders(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: 01-list.png]
                [VIDEO: demo-flow.mp4]
                [SCREENSHOT: 02-form.png]
            """))
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "01-list": "screenshots/01-list.png",
                    "demo-flow": "videos/demo-flow.mp4",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # I14: report now distinguishes unique mappings from instance count
                self.assertIn("replaced: 2 unique mappings (2 placeholder instances)", r.stdout)
                self.assertIn("placeholders still missing: 1", r.stdout)
                # G: missing list now carries status ("no_mapping" for plain [...: x])
                self.assertIn("(no_mapping)", r.stdout)
                # Read the updated manual
                new_text = Path(md).read_text()
                self.assertIn("![01-list](screenshots/01-list.png)", new_text)
                self.assertIn("![demo-flow](videos/demo-flow.mp4)", new_text)
                self.assertIn("[SCREENSHOT: 02-form.png]", new_text)  # not replaced
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_apply_mapping_does_not_overwrite_existing_images(self):
        """v0.2.3: only [SCREENSHOT: x] / [VIDEO: x] placeholders are replaced;
        existing ![alt](path) markdown image references are untouched."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                ![hero](images/hero.png)
                [SCREENSHOT: 01-list.png]
                [VIDEO: demo.mp4]
            """))
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "01-list": "screenshots/01-list.png",
                    "demo": "videos/demo.mp4",
                }))
                run(["record-manual", md, "--apply-mapping", mapping_path])
                new_text = Path(md).read_text()
                self.assertIn("![hero](images/hero.png)", new_text)  # preserved
                self.assertIn("![01-list](screenshots/01-list.png)", new_text)  # replaced
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_scan_ignores_placeholder_inside_code_block(self):
        """v0.2.3: code-fenced placeholders (e.g. inside a documentation example
        showing the syntax) must not be counted."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: real-01.png]

                ```markdown
                Use the syntax: [SCREENSHOT: 01-list.png]
                ```
            """))
            path = f.name
        try:
            r = run(["record-manual", path])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            # Only "real-01" should be in the report, not "01-list"
            self.assertIn("real-01", r.stdout)
            # The text in the output should NOT mention "01-list" as a screenshot
            # (it's inside a code fence — documentation example)
            self.assertNotIn("[SCREENSHOT: 01-list.png]", r.stdout)
        finally:
            os.unlink(path)

    # === v0.2.4: AI ANNOTATE placeholder support ===

    def test_scan_recognizes_ai_annotate_placeholder(self):
        """v0.2.4: [AI ANNOTATE: <name>] is a first-class placeholder kind
        (agent-mediated vision annotation, see SKILL.md §15)."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: 01-list.png]
                [AI ANNOTATE: 01-list]
            """))
            path = f.name
        try:
            r = run(["record-manual", path])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("RECORDING_NEEDED", r.stdout)
            self.assertIn("screenshots: 1", r.stdout)
            # The AI ANNOTATE marker should NOT inflate the screenshot count
            # (it produces a different output, see SKILL.md §15)
            self.assertIn("ai_annotates: 1", r.stdout)
        finally:
            os.unlink(path)

    def test_generate_template_includes_ai_annotate_step(self):
        """v0.2.4: build_recorder_template emits an ai_annotate step for each
        [AI ANNOTATE: <name>] marker."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("[SCREENSHOT: 01-list.png]\n[AI ANNOTATE: 01-list]\n")
            md = f.name
        try:
            template_path = md + ".template.json"
            try:
                run(["record-manual", md, "--generate-template", template_path])
                data = json.loads(Path(template_path).read_text())
                actions = [s.get("action") for s in data["steps"]]
                self.assertIn("screenshot", actions)
                self.assertIn("ai_annotate", actions)
                # The ai_annotate step should reference the screenshot name
                ai_step = next(s for s in data["steps"] if s.get("action") == "ai_annotate")
                self.assertEqual(ai_step["screenshot"], "01-list")
                self.assertIn("prompt", ai_step)
            finally:
                if os.path.exists(template_path):
                    os.unlink(template_path)
        finally:
            os.unlink(md)

    def test_apply_mapping_replaces_ai_annotate_placeholder(self):
        """v0.2.4: --apply-mapping substitutes [AI ANNOTATE: x] placeholders
        with the .ai-annotated.png path produced by apply-ai-responses."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Manual\n[SCREENSHOT: 01-list.png]\n[AI ANNOTATE: 01-list]\n")
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "01-list": "screenshots/01-list.png",
                    "ai-annotated-01-list": "screenshots/01-list.ai-annotated.png",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # I14: 2 unique mapping keys, 2 instance replacements
                self.assertIn("replaced: 2 unique mappings (2 placeholder instances)", r.stdout)
                new_text = Path(md).read_text()
                self.assertIn("![01-list](screenshots/01-list.png)", new_text)
                self.assertIn("![ai-annotated-01-list](screenshots/01-list.ai-annotated.png)", new_text)
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    # === v0.2.4 audit re-review: F1/F2/F3 regression tests ===

    def test_apply_mapping_replaces_all_occurrences_of_same_placeholder(self):
        """F1 fix: 2+ same-name placeholders in the manual (e.g. same
        screenshot referenced in 2 task cards) must ALL be replaced.
        Previous count=1 only replaced the first occurrence."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                ## 任务卡 1
                [SCREENSHOT: 01-list.png]
                ## 任务卡 2
                [SCREENSHOT: 01-list.png]
            """))
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "01-list": "screenshots/01-list.png",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # I14: 1 unique key, but 2 placeholder instances were replaced
                self.assertIn("replaced: 1 unique mappings (2 placeholder instances)", r.stdout)
                new_text = Path(md).read_text()
                # Both occurrences must be replaced (not just the first)
                self.assertNotIn("[SCREENSHOT: 01-list.png]", new_text)
                self.assertEqual(new_text.count("![01-list](screenshots/01-list.png)"), 2,
                                 f"expected 2 replacements, got {new_text.count('![01-list]')}")
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_ai_annotate_missing_when_only_plain_mapping_exists(self):
        """F2 fix: AI ANNOTATE placeholder requires the `ai-annotated-` prefix
        mapping. If only a plain-name mapping exists for the same name,
        that's a config error and the AI ANNOTATE is reported in missing
        (with explicit reason) instead of being silently dropped."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: 01-list.png]
                [AI ANNOTATE: 01-list]
            """))
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                # Only plain name, NO `ai-annotated-` prefix
                Path(mapping_path).write_text(json.dumps({
                    "01-list": "screenshots/01-list.png",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # I14: 1 unique key, 1 instance replaced
                self.assertIn("replaced: 1 unique mappings (1 placeholder instances)", r.stdout)
                # The AI ANNOTATE is in missing (not silently dropped)
                self.assertIn("placeholders still missing: 1", r.stdout)
                # G: missing entries now have a `status` field. AI ANNOTATE
                # with plain-name mapping → status="wrong_mapping_type"
                self.assertIn("(wrong_mapping_type)", r.stdout)
                # Explicit reason: AI ANNOTATE requires ai-annotated- prefix
                self.assertIn("ai-annotated-01-list", r.stdout)
                # The AI ANNOTATE marker is still in the manual
                new_text = Path(md).read_text()
                self.assertIn("[AI ANNOTATE: 01-list]", new_text)
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_ai_annotate_missing_when_no_mapping_at_all(self):
        """F2 fix: AI ANNOTATE with no mapping entry at all → in missing with
        a clear 'add ai-annotated-NAME' instruction."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("[AI ANNOTATE: solo]\n")
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({}))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertIn("placeholders still missing: 1", r.stdout)
                self.assertIn("solo", r.stdout)
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_ai_annotate_missing_with_prefix_is_satisfied(self):
        """F2 fix: happy path — AI ANNOTATE + `ai-annotated-` prefix mapping
        is correctly replaced and NOT in missing."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("[AI ANNOTATE: happy]\n")
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "ai-annotated-happy": "screenshots/happy.ai-annotated.png",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # I14: 1 unique key, 1 instance replaced
                self.assertIn("replaced: 1 unique mappings (1 placeholder instances)", r.stdout)
                self.assertNotIn("placeholders still missing", r.stdout)
                new_text = Path(md).read_text()
                self.assertIn("![ai-annotated-happy](screenshots/happy.ai-annotated.png)", new_text)
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    # === v0.2.4 audit re-review: C / I11 / G / F9 tests ===

    def test_recorder_template_uses_dollar_prefix_for_auth_env(self):
        """C: auth_env entries must be '$AUTH_USER' (env var ref), not bare.
        Bare entries get passed to the login form as the literal string."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("[SCREENSHOT: 01-list.png]\n")
            md = f.name
        try:
            template_path = md + ".template.json"
            try:
                run(["record-manual", md, "--generate-template", template_path])
                data = json.loads(Path(template_path).read_text())
                for entry in data["auth_env"]:
                    self.assertTrue(
                        entry.startswith("$"),
                        f"auth_env entry {entry!r} missing $ prefix (would be "
                        f"submitted to login form as the literal env var name)",
                    )
            finally:
                if os.path.exists(template_path):
                    os.unlink(template_path)
        finally:
            os.unlink(md)

    def test_scan_supports_multi_segment_placeholder_names(self):
        """I11: placeholder names with multiple dot-segments (e.g. v1.2-heatmap)
        must be recognized. The trailing extension (.png / .mp4) is stripped."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: v1.2-heatmap.png]
                [VIDEO: settings.modal.flow.mp4]
                [SCREENSHOT: simple.png]
            """))
            md = f.name
        try:
            r = run(["record-manual", md])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("RECORDING_NEEDED", r.stdout)
            self.assertIn("screenshots: 2", r.stdout)
            self.assertIn("v1.2-heatmap", r.stdout)
            self.assertIn("settings.modal.flow", r.stdout)
            self.assertIn("simple", r.stdout)
        finally:
            os.unlink(md)

    def test_apply_mapping_handles_multi_segment_placeholder_name(self):
        """I11: end-to-end — multi-segment placeholder gets matched and
        replaced. The mapping key is the bare name (extension stripped)."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("[SCREENSHOT: v1.2-heatmap.png]\n[VIDEO: settings.modal.flow.mp4]\n")
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "v1.2-heatmap": "screenshots/v1.2-heatmap.png",
                    "settings.modal.flow": "videos/settings.modal.flow.mp4",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                self.assertIn("replaced: 2 unique mappings (2 placeholder instances)", r.stdout)
                new_text = Path(md).read_text()
                self.assertIn("![v1.2-heatmap](screenshots/v1.2-heatmap.png)", new_text)
                self.assertIn("![settings.modal.flow](videos/settings.modal.flow.mp4)", new_text)
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_missing_list_reports_user_declared_needed_status(self):
        """G: placeholders written with the [... NEEDED: x] form get a
        different status from plain [...: x]. The agent loop uses this
        to prioritize user-explicit needs."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: 01-list.png]
                [SCREENSHOT NEEDED: 02-form.png]
                [VIDEO NEEDED: demo.mp4]
            """))
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                # Map only the plain one
                Path(mapping_path).write_text(json.dumps({
                    "01-list": "screenshots/01-list.png",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # The plain one got replaced; the two NEEDED ones are missing
                self.assertIn("placeholders still missing: 2", r.stdout)
                # The NEEDED placeholders get user_declared_needed status
                self.assertIn("(user_declared_needed)", r.stdout)
                # The plain placeholder is replaced (no missing for it)
                self.assertNotIn("[SCREENSHOT: 01-list.png]", r.stdout.split("placeholders still missing")[0] or "")
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_apply_mapping_writes_atomically_via_tmp_rename(self):
        """F9: a crash mid-write used to truncate the manual to a
        half-applied state. Now --apply-mapping writes to a .tmp file
        in the same dir and atomically renames (POSIX-atomic).
        """
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Manual\n[SCREENSHOT: 01-list.png]\n")
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "01-list": "screenshots/01-list.png",
                }))
                # Pre-condition: no .tmp file exists
                tmp_path = Path(md + ".tmp")
                self.assertFalse(tmp_path.exists())
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # Post-condition: .tmp file was cleaned up by the rename
                self.assertFalse(tmp_path.exists(),
                                 f"stray .tmp file left behind: {tmp_path}")
                # And the manual was actually updated
                new_text = Path(md).read_text()
                self.assertIn("![01-list](screenshots/01-list.png)", new_text)
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    def test_report_distinguishes_unique_mappings_from_instance_count(self):
        """I14: a single mapping key that replaces 2 same-name placeholders
        is reported as '1 unique mappings (2 placeholder instances)' —
        not just '1 placeholders' (which was misleading)."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(textwrap.dedent("""\
                # Manual
                ## Task 1
                [SCREENSHOT: hero.png]
                ## Task 2
                [SCREENSHOT: hero.png]
                ## Task 3
                [SCREENSHOT: hero.png]
            """))
            md = f.name
        try:
            mapping_path = md + ".mapping.json"
            try:
                Path(mapping_path).write_text(json.dumps({
                    "hero": "screenshots/hero.png",
                }))
                r = run(["record-manual", md, "--apply-mapping", mapping_path])
                self.assertEqual(r.returncode, 0, msg=r.stderr)
                # 1 unique mapping, 3 placeholder instances
                self.assertIn("replaced: 1 unique mappings (3 placeholder instances)", r.stdout)
            finally:
                if os.path.exists(mapping_path):
                    os.unlink(mapping_path)
        finally:
            os.unlink(md)

    # === v0.2.4 audit round 3: M2 (record-manual usage on bad flag) ===

    def test_record_manual_unknown_flag_prints_usage(self):
        """M2: a bad flag on record-manual must print a usage line on
        stderr (matching the other subcommands at line 1307, 1335, 1363)."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("# Manual\n")
            md = f.name
        try:
            r = run(["record-manual", md, "--bogus-flag"])
            # M2: exit 2 (bad arg) and stderr must mention usage
            self.assertEqual(r.returncode, 2)
            self.assertIn("usage: record-manual", r.stderr)
            self.assertIn("--bogus-flag", r.stderr)
        finally:
            os.unlink(md)

    def test_record_manual_help_flag_prints_usage(self):
        """M2: --help on record-manual prints usage, exits 0."""
        r = run(["record-manual", "--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage: record-manual", r.stderr)


if __name__ == "__main__":
    unittest.main()
