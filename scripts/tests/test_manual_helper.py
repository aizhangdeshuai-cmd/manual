"""Unit tests for scripts/manual_helper.py — focused on init-skill personas
scaffold fallback (v0.2.2)."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "manual_helper.py"
PYTHON = os.environ.get("PYTHON", "python3")


def run_module(func: str, *args) -> subprocess.CompletedProcess:
    """Run `python3 -m manual_helper <func> [args]` (uses module mode so
    relative imports work). Must be invoked from the scripts/ dir where
    manual_helper.py lives."""
    return subprocess.run(
        [PYTHON, "-m", "manual_helper", func, *args],
        capture_output=True, text=True, check=False,
        cwd=str(SCRIPT.parent),  # run from scripts/ (where manual_helper.py + examples/ relative path resolves)
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


if __name__ == "__main__":
    unittest.main()
