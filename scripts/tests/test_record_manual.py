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
                self.assertIn("replaced: 2 placeholders", r.stdout)
                self.assertIn("placeholders still missing: 1", r.stdout)
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


if __name__ == "__main__":
    unittest.main()
