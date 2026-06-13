"""Unit tests for scripts/validate-output.py."""
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "validate-output.py"
PYTHON = os.environ.get("PYTHON", "python3")


def run(args, stdin=None):
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        capture_output=True, text=True, input=stdin,
    )


GOOD = """\
# Test manual

## 适用角色
- 管理员

## 前置条件
- 已登录

### 操作前必看
在操作前你需要知道以下几点。

### 操作前必看
第二段必看。

### 操作前必看
第三段必看。

### 步骤
1. 打开页面
2. 点击按钮

### 步骤
1. 打开
2. 点击

### 步骤
1. 第三组
2. 第四组

### 成功后看到
- 成功提示

### 字段说明
- 用户名

### 如果你卡住了
联系 IT。

### 相关任务
参见 X。

## 角色与权限速查
| 模块 | 角色 | 读 | 写 | 删 | 备注 |
| --- | --- | --- | --- | --- | --- |

📌 备注：重要
💡 提示：操作建议
⚠️ 注意：风险

![a](img/a.png)
![b](img/b.png)
"""


BAD = """\
# Empty
- nothing
"""


class ValidateOutputTests(unittest.TestCase):
    def test_good_file_passes_human(self):
        with tempfile.TemporaryDirectory() as d:
            # v0.3.1: the new "screenshot files exist" check resolves
            # `![a](img/a.png)` relative to the markdown's directory. The
            # GOOD fixture's images must exist on disk for the check
            # to pass.
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            (img_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            (img_dir / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
            f = Path(d) / "good.md"
            f.write_text(GOOD)
            r = run([str(f)])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertIn("[OK", r.stdout)
            for needle in (
                "7-field hits=12",
                "操作前必看 blocks=3",
                "visual anchors=3",
                "appendix-A 6-col table=2",
                "role-permission matrix=1",
                "screenshot count=2",
                # v0.3.1: new file-existence check rendered as present/total
                "screenshot files exist=2/2",
            ):
                self.assertIn(needle, r.stdout, msg="missing " + needle)

    def test_bad_file_fails_human(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(BAD)
            path = f.name
        try:
            r = run([path])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            self.assertIn("[FAIL", r.stdout)
            self.assertIn("7-field hits", r.stdout)
        finally:
            os.unlink(path)

    def test_strict_exits_1_on_fail(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(BAD)
            path = f.name
        try:
            r = run(["--strict", path])
            self.assertEqual(r.returncode, 1, msg=r.stdout)
        finally:
            os.unlink(path)

    def test_json_mode(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(GOOD)
            path = f.name
        try:
            r = run(["--json", path])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            data = json.loads(r.stdout)
            self.assertEqual(len(data), 1)
            # The new file-existence check will FAIL here (images don't
            # exist on disk), so the file-level ok is False.
            self.assertFalse(data[0]["ok"])
            # v0.3.1: 7 checks now (was 6).
            self.assertEqual(len(data[0]["checks"]), 7)
            names = [c["name"] for c in data[0]["checks"]]
            self.assertIn("screenshot files exist", names)
        finally:
            os.unlink(path)

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as d:
            # v0.3.1: create the real image files good.md references so
            # the new "screenshot files exist" check passes for good.md
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            (img_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            (img_dir / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            p1 = Path(d) / "good.md"
            p2 = Path(d) / "bad.md"
            p1.write_text(GOOD)
            p2.write_text(BAD)
            r = run([str(p1), str(p2)])
            self.assertEqual(r.returncode, 0)
            self.assertIn("[OK", r.stdout)
            self.assertIn("[FAIL", r.stdout)

    # === v0.2.2: forgiving regex tests ===

    def test_code_fence_操作前必看_does_not_count(self):
        """v0.2.2: 操作前必看 occurrences inside fenced code blocks must NOT
        count toward the threshold (was: count was inflated by doc examples)."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            # Only 2 real 操作前必看 (the threshold is 3), but 5 inside code fences.
            # Must FAIL because real count is below threshold.
            f.write(textwrap_and_nowrite(
                "### 操作前必看\nA\n\n### 操作前必看\nB\n\n```\n### 操作前必看\nC\n```\n\n```\n### 操作前必看\nD\n```\n\n```markdown\n### 操作前必看\nE\n```\n"
            ))
            path = f.name
        try:
            r = run([path])
            data = json.loads(run(["--json", path]).stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "操作前必看 blocks")
            # Real count = 2 (below threshold 3) — must FAIL
            self.assertEqual(check["hits"], 2, f"expected 2 real hits, got {check['hits']}")
            self.assertFalse(check["ok"])
        finally:
            os.unlink(path)

    def test_role_permission_synonyms_accepted(self):
        """v0.2.2: role-permission heading accepts Chinese variants
        (角色权限速查, 角色与权限) and English (Role Quick Reference)."""
        variants = [
            "## 角色与权限速查\n",
            "## 角色权限速查\n",
            "## 角色与权限\n",  # truncated but still has 角色与权限 keyword
            "## 角色/权限速查\n",
            "## Role Quick Reference\n",
            "## Role Quick Ref\n",
            "## Role Permissions\n",
        ]
        for heading in variants:
            with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
                f.write(make_minimal_doc(heading))
                path = f.name
            try:
                r = run(["--json", path])
                data = json.loads(r.stdout)
                check = next(c for c in data[0]["checks"] if c["name"] == "role-permission matrix")
                self.assertGreaterEqual(check["hits"], 1, f"heading {heading!r} should pass; got hits={check['hits']}")
                self.assertTrue(check["ok"], f"heading {heading!r} should pass")
            finally:
                os.unlink(path)

    def test_7_field_case_insensitive(self):
        """v0.2.2: 7-field check uses re.IGNORECASE so English synonyms
        for the field headings also pass (forward-compat for i18n)."""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            # Use English-cased "Prerequisites" and "Roles" — should still match
            # 适用角色 / 前置条件 because of IGNORECASE plus pattern alternation.
            f.write(make_minimal_doc("### Prerequisites\nx\n\n### Roles\ny\n\n### operation before\nz\n\n### Steps\n1. open\n\n### Steps\n2. click\n\n### Steps\n3. submit"))
            path = f.name
        try:
            data = json.loads(run(["--json", path]).stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "7-field hits")
            # Should count at least the 操作前必看, 适用角色 (matches "Roles"), and 步骤 matches
            self.assertGreaterEqual(check["hits"], 3, f"got {check['hits']}")
        finally:
            os.unlink(path)

    # === v0.3.1: screenshot files exist check ===

    def test_screenshot_files_exist_passes_when_all_files_present(self):
        """v0.3.1: when every `![alt](path.png)` reference points to an
        existing file, the check is ok=True."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            (img_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            (img_dir / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            (img_dir / "c.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 8)
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ![a](img/a.png)
                ![b](img/b.png)
                ![c](img/c.jpg)
            """))
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["present"], 3)
            self.assertEqual(check["threshold"], 3)
            self.assertEqual(check["missing_count"], 0)
            self.assertTrue(check["ok"])

    def test_screenshot_files_exist_fails_when_files_missing(self):
        """v0.3.1: missing files → check ok=False, present < threshold,
        missing_paths lists the offenders. The OLD check ("screenshot
        count" = mentions) STILL passes — this is the bug the eval
        agent exploited: 26 placeholders, 0 real files, validate
        passed. With this fix it FAILS."""
        with tempfile.TemporaryDirectory() as d:
            # Don't create any image files
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ![hero](img/hero.png)
                ![list](img/list.png)
                ![detail](img/detail.png)
            """))
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["present"], 0)
            self.assertEqual(check["threshold"], 3)
            self.assertEqual(check["missing_count"], 3)
            self.assertFalse(check["ok"])
            # All 3 paths are listed (we cap at 5; 3 fits)
            for ref in ("img/hero.png", "img/list.png", "img/detail.png"):
                self.assertIn(ref, check["missing_paths"])
            # The OLD check still passes (count=3 >= 2) — the eval
            # agent's exact failure pattern
            old_check = next(c for c in data[0]["checks"] if c["name"] == "screenshot count")
            self.assertTrue(old_check["ok"])
            # But the file-level ok is now False (one check failed)
            self.assertFalse(data[0]["ok"])

    def test_screenshot_files_exist_human_output_shows_missing(self):
        """v0.3.1: human-form output should show present/total + missing
        paths so the operator can see at a glance which references are
        placeholders."""
        with tempfile.TemporaryDirectory() as d:
            # Create only ONE of the two referenced images
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            (img_dir / "present.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ![p](img/present.png)
                ![m](img/missing.png)
            """))
            r = run([str(f)])
            # 1 of 2 present, 1 missing — the missing path appears in output
            self.assertIn("screenshot files exist=1/2 (1 missing)", r.stdout)
            self.assertIn("img/missing.png", r.stdout)
            # The OK/FAIL header should be FAIL (file-level ok is false)
            self.assertIn("[FAIL", r.stdout)

    def test_screenshot_files_exist_strict_exits_1(self):
        """v0.3.1: with --strict, missing files cause exit 1 (so CI
        gates on this)."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "manual.md"
            f.write_text("![x](img/x.png)\n")
            r = run(["--strict", str(f)])
            self.assertEqual(r.returncode, 1, msg=r.stdout)

    def test_screenshot_files_exist_ignores_http_urls(self):
        """v0.3.1: external image URLs (CDN, GitHub raw) must NOT be
        checked for local existence. The user might link to
        https://example.com/hero.png legitimately."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ![local](img/local.png)
                ![cdn](https://cdn.example.com/img.png)
            """))
            # Don't create img/local.png — should be missing
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            # Only the LOCAL ref is checked; the CDN URL is excluded
            self.assertEqual(check["present"], 0)
            self.assertEqual(check["threshold"], 1)
            self.assertEqual(check["missing_count"], 1)
            self.assertNotIn("https://cdn.example.com/img.png", check["missing_paths"])

    def test_screenshot_files_exist_strips_query_strings(self):
        """v0.3.1: paths like `img/x.png?v=123` should be checked as
        `img/x.png` (the query string is a cache-buster, not part of
        the file path)."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            (img_dir / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            f = Path(d) / "manual.md"
            f.write_text("![x](img/x.png?v=123)\n")
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["present"], 1)
            self.assertTrue(check["ok"])

    def test_screenshot_files_exist_zero_refs_is_ok(self):
        """v0.3.1: a manual with NO image references is vacuously OK for
        the file-existence check (the OTHER checks like "screenshot
        count >= 2" still apply, so this won't accidentally pass a
        barebones manual)."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "manual.md"
            f.write_text("# Manual\nNo images here.\n")
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["present"], 0)
            self.assertEqual(check["threshold"], 0)
            self.assertTrue(check["ok"])


def textwrap_and_nowrite(s: str) -> str:
    """Helper: identity function to make code-fence tests readable."""
    return s


def make_minimal_doc(extra_heading: str) -> str:
    """Build a minimal doc that satisfies all 6 checks (for role-permission synonym tests)."""
    return f"""# Test

## 适用角色
- admin

## 前置条件
- 已登录

### 操作前必看
A

### 操作前必看
B

### 操作前必看
C

### 步骤
1. 打开

### 步骤
2. 点击

### 步骤
3. 提交

### 成功后看到
- ok

### 字段说明
- name

### 如果你卡住了
- call IT

### 相关任务
- none

{extra_heading}
| 模块 | 角色 | 读 | 写 | 删 | 备注 |
| --- | --- | --- | --- | --- | --- |

⚠️ 注意：A
💡 提示：B
📌 备注：C

![a](img/a.png)
![b](img/b.png)
"""


if __name__ == "__main__":
    unittest.main()
