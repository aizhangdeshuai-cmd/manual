"""Tests for manual_helper.html_on_disk_version()."""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import manual_helper


class HtmlOnDiskVersionTests(unittest.TestCase):
    def test_reads_existing_marker(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manual.html"
            p.write_text(
                "<!-- user-manual-dashboard-version: 24 -->\n<html></html>",
                encoding="utf-8",
            )
            self.assertEqual(manual_helper.html_on_disk_version(p), 24)

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.html"
            with self.assertRaises(FileNotFoundError):
                manual_helper.html_on_disk_version(p)

    def test_no_marker_raises_value_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manual.html"
            p.write_text("<html><body>no version marker</body></html>", encoding="utf-8")
            with self.assertRaises(ValueError):
                manual_helper.html_on_disk_version(p)

    def test_larger_version_number(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manual.html"
            p.write_text(
                "<!-- user-manual-dashboard-version: 100 -->\nstuff",
                encoding="utf-8",
            )
            self.assertEqual(manual_helper.html_on_disk_version(p), 100)

    def test_cli_dispatch_prints_version(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manual.html"
            p.write_text(
                "<!-- user-manual-dashboard-version: 7 -->\n", encoding="utf-8"
            )
            rc = manual_helper.main(
                ["manual_helper", "html-on-disk-version", str(p)]
            )
            self.assertEqual(rc, 0)

    def test_cli_missing_file_exits_1(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.html"
            rc = manual_helper.main(
                ["manual_helper", "html-on-disk-version", str(p)]
            )
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
