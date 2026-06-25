"""Tests for v0.3.2 fill-citation-shas subcommand (P1 #9 from eval report)."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
PYTHON = os.environ.get("PYTHON", "python3")
SCRIPT = SCRIPTS_DIR / "manual_helper"


def run(*args, cwd=None):
    return subprocess.run(
        [PYTHON, "-m", "manual_helper", *args],
        capture_output=True, text=True, cwd=cwd or str(SCRIPTS_DIR),
    )


class FillCitationShasTests(unittest.TestCase):
    """P1 #9: an LLM agent writing a manual has no way to know the
    real SHA256 of cited artifacts, so it writes '(auto)' as a
    placeholder. fill-citation-shas closes that loop by reading
    scan-artifacts output and emitting a corrected Citations table.
    """

    def _write_artifact(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def test_fills_auto_placeholder_with_real_sha(self):
        """v0.3.2: a manual with `(auto)` citations gets those replaced
        by the real SHA256 from scan-artifacts. Output is a corrected
        Citations table the agent can paste in."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # Create an artifact
            sha = self._write_artifact(root / "docs/specs/x.md", "# X spec content")
            # Manual with (auto) SHA for that artifact
            manual = root / "docs/user-manual/manual/m.md"
            manual.parent.mkdir(parents=True)
            manual.write_text(
                "## Citations\n\n"
                "### Project artifacts\n\n"
                "| Path | Kind | Title | SHA256 (content) | First cited (ET) | Last seen (ET) |\n"
                "|---|---|---|---|---|---|\n"
                "| [docs/specs/x.md](docs/specs/x.md) | spec | X | (auto) | 2026-06-13T00:00:00-04:00 | 2026-06-13T00:00:00-04:00 |\n",
                encoding="utf-8",
            )
            r = run("fill-citation-shas", str(manual), str(root))
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            data = json.loads(run("fill-citation-shas", "--json", str(manual), str(root)).stdout)
            self.assertEqual(len(data["replacements"]), 1)
            self.assertEqual(data["replacements"][0]["path"], "docs/specs/x.md")
            self.assertEqual(data["replacements"][0]["oldsha"], "(auto)")
            self.assertEqual(data["replacements"][0]["newsha"], sha)
            # The unresolved list is empty (artifact exists)
            self.assertEqual(data["unresolved"], [])

    def test_marks_unresolved_when_artifact_missing(self):
        """v0.3.2: a cited path that doesn't exist on disk is
        reported as unresolved with the current SHA preserved. The
        agent loop can then fix the path or remove the citation."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manual = root / "docs/user-manual/manual/m.md"
            manual.parent.mkdir(parents=True)
            manual.write_text(
                "## Citations\n\n"
                "### Project artifacts\n\n"
                "| Path | Kind | Title | SHA256 (content) | First cited (ET) | Last seen (ET) |\n"
                "|---|---|---|---|---|---|\n"
                "| [docs/does-not-exist.md](docs/does-not-exist.md) | spec | Y | (auto) | 2026-06-13 | 2026-06-13 |\n",
                encoding="utf-8",
            )
            r = run("fill-citation-shas", "--json", str(manual), str(root))
            self.assertEqual(r.returncode, 0)
            data = json.loads(r.stdout)
            self.assertEqual(data["replacements"], [])  # no real SHA to use
            self.assertEqual(len(data["unresolved"]), 1)
            self.assertEqual(data["unresolved"][0]["path"], "docs/does-not-exist.md")
            self.assertEqual(data["unresolved"][0]["current_sha"], "(auto)")

    def test_no_replacement_when_sha_already_correct(self):
        """v0.3.2: if the existing SHA in the manual matches the real
        one, no replacement is emitted (avoids noise / spurious diffs
        the agent would have to inspect)."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            content = "# Real content"
            sha = self._write_artifact(root / "docs/x.md", content)
            manual = root / "docs/user-manual/manual/m.md"
            manual.parent.mkdir(parents=True)
            manual.write_text(
                "## Citations\n\n"
                "### Project artifacts\n\n"
                "| Path | Kind | Title | SHA256 (content) | First cited (ET) | Last seen (ET) |\n"
                "|---|---|---|---|---|---|\n"
                f"| [docs/x.md](docs/x.md) | spec | X | {sha} | 2026-06-13 | 2026-06-13 |\n",
                encoding="utf-8",
            )
            data = json.loads(run("fill-citation-shas", "--json", str(manual), str(root)).stdout)
            self.assertEqual(data["replacements"], [])
            self.assertEqual(data["unresolved"], [])

    def test_human_output_shows_replacement_count(self):
        """v0.3.2: human-form output says how many were replaced
        and lists them, so the agent can spot-check."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write_artifact(root / "docs/x.md", "X")
            self._write_artifact(root / "docs/y.md", "Y")
            manual = root / "docs/user-manual/manual/m.md"
            manual.parent.mkdir(parents=True)
            manual.write_text(
                "## Citations\n\n"
                "### Project artifacts\n\n"
                "| Path | Kind | Title | SHA256 (content) | First cited (ET) | Last seen (ET) |\n"
                "|---|---|---|---|---|---|\n"
                "| [docs/x.md](docs/x.md) | spec | X | (auto) | 2026-06-13 | 2026-06-13 |\n"
                "| [docs/y.md](docs/y.md) | spec | Y | (auto) | 2026-06-13 | 2026-06-13 |\n",
                encoding="utf-8",
            )
            r = run("fill-citation-shas", str(manual), str(root))
            self.assertEqual(r.returncode, 0)
            self.assertIn("Replaced 2 placeholder/stale SHAs", r.stdout)
            self.assertIn("docs/x.md", r.stdout)
            self.assertIn("docs/y.md", r.stdout)


if __name__ == "__main__":
    unittest.main()
