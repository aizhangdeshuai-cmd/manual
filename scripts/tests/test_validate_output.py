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
    # v1.1.0: hard gate is on by default. Old unit tests (98 of 115)
    # were written before the gate existed and don't seed a manifest;
    # auto-inject --no-hard-gate so they keep testing what they
    # actually test (the per-check logic) and not the pre-flight.
    # New RecordingPhaseActuallyRanTests pass `_raw=True` to opt out
    # of the auto-injection so they can exercise the gate itself.
    inject = True
    if isinstance(args, list) and len(args) > 0 and args[0] == "_raw":
        args = args[1:]
        inject = False
    elif isinstance(args, list):
        for a in args:
            if isinstance(a, str) and (a == "--no-hard-gate" or a.startswith("--no-hard-gate=")):
                inject = False
                break
    if inject:
        if "--no-hard-gate" not in args:
            args = ["--no-hard-gate", *args]
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        capture_output=True, text=True, input=stdin,
    )


def run_raw(args, stdin=None):
    """v1.1.0: bypass the auto --no-hard-gate injection in run().
    Used by RecordingPhaseActuallyRanTests to exercise the hard
    gate itself."""
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        capture_output=True, text=True, input=stdin,
    )


GOOD = """\
---
title: 测试手册
module: 测试
description: 测试手册搜索摘要 — 描述本册面向谁、做什么
---

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

### 任务卡 1: 测试任务卡

> ⚠️ **操作前必看**
> - 必须登录

#### 步骤
1. 打开页面
2. 点击按钮

#### 成功后看到
- 成功提示

## 目录
- [适用角色](#适用角色)
- [前置条件](#前置条件)
- [操作前必看](#操作前必看)
- [步骤](#步骤)
- [成功后看到](#成功后看到)
- [字段说明](#字段说明)
- [角色与权限速查](#角色与权限速查)

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
            # v1.1.0: --unique is now default, so test fixtures must use
            # distinct content for each PNG (same name = same hash, even
            # with distinct filenames, fails the unique check).
            (img_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"a")
            (img_dir / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"b")
            f = Path(d) / "good.md"
            f.write_text(GOOD)
            r = run([str(f)])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertIn("[OK", r.stdout)
            for needle in (
                "7-field hits=21",  # v1.0.1: 目录 + new 任务卡 1 fixture
                "操作前必看 blocks=6",  # v1.0.1: 目录 (2) + new task card (1) added to original 3
                "visual anchors=4",  # v1.0.1: new task card adds ⚠️
                "appendix-A 6-col table=2",
                "role-permission matrix=1",
                "screenshot count=2",
                # v0.3.1: new file-existence check rendered as present/total
                "screenshot files exist=2/2",
                # v1.0.1: directory_anchors check
                "directory_anchors (§3 row 4 hard gate)=7",
                # v1.0.1: task_card_headings check
                "task_card_headings (§4 strict format)=1",
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
            # v0.5.4: 8 checks now (added placeholder_alt).
            # v1.0.1: 9 checks now (added directory_anchors).
            # v1.0.1: 10 checks now (added task_card_headings).
            # v1.1.0: 11 checks now (added audience_leak per SKILL §2.7.1).
            # v1.2.0: 13 checks now (added frontmatter_description +
            # unfilled_template_terms).
            # v2.2.0: 14 checks now (added video_outside_steps).
            # v1.1.0: --unique is default + new screenshot_uses_annotated
            # check added; total now 16 (was 14 pre-1.1.0).
            # v2.3.0: 19 checks now (added broken_anchors + placeholder_url + task_card_steps_count).
            # v1.2.0: 21 checks now (added manifest_disk_consistency + file_type_sanity).
            self.assertEqual(len(data[0]["checks"]), 21)
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
            (img_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"a")
            (img_dir / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"b")
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
            (img_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"a")
            (img_dir / "b.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"b")
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
    def test_placeholder_alt_flags_lazy_alt_text(self):
        """v0.5.4: detect LLM-lazy alt patterns (占位:/<TODO:>/system screenshot/description)."""
        with tempfile.TemporaryDirectory() as d:
            # Create real PNG files for the markdown to reference
            for name in ("good.png", "lazy1.png", "lazy2.png", "lazy3.png", "lazy4.png"):
                (Path(d) / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
            md = Path(d) / "lazy.md"
            md.write_text(
                "# Manual\n\n"
                "![红框:点保存](good.png)\n"  # OK
                "![占位:指标列表](lazy1.png)\n"  # 占位: stub
                "![<TODO: alt>](lazy2.png)\n"  # TODO stub
                "![系统截图](lazy3.png)\n"  # generic word
                "![详情页面截图,显示了所有字段](lazy4.png)\n"  # description-style
            )
            r = run(["--json", str(md)])
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            data = json.loads(r.stdout)
            checks = {c["name"]: c for c in data[0]["checks"]}
            self.assertIn("placeholder_alt (lazy alt-text)", checks)
            alt = checks["placeholder_alt (lazy alt-text)"]
            self.assertEqual(alt["hits"], 5)
            self.assertEqual(alt["flagged"], 4)
            self.assertFalse(alt["ok"])
            offenders = alt["offenders"]
            self.assertEqual(len(offenders), 4)
            # First offender is the 占位: one
            self.assertTrue(offenders[0]["alt"].startswith("占位"))


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

    # === v0.3.2: PNG dimension check + unreplaced placeholder check ===

    def test_png_smaller_than_50x50_is_placeholder(self):
        """v0.3.2: a PNG file that exists but is < 50×50 px is treated
        as a placeholder (LLM-generated stub) and reported separately
        from missing files. The check stays ok=False even though the
        file is on disk — a 1×1 gray PNG is not a real asset."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            # 32x32 stub
            stub = Image.new("RGB", (32, 32), "gray")
            stub.save(img_dir / "tiny.png")
            # 1280x800 real
            real = Image.new("RGB", (1280, 800), "white")
            real.save(img_dir / "real.png")
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ![tiny](img/tiny.png)
                ![real](img/real.png)
            """))
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["present"], 1, msg=f"only the real one should count as present: {check}")
            self.assertEqual(check["placeholder_png_count"], 1)
            self.assertEqual(check["missing_count"], 1)
            self.assertFalse(check["ok"])

    def test_png_50x50_boundary_is_real(self):
        """v0.3.2: a 50×50 PNG is the boundary — at exactly 50, count
        as real (≥ 50x50). At 49, count as placeholder."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            Image.new("RGB", (50, 50), "white").save(img_dir / "fifty.png")
            Image.new("RGB", (49, 50), "white").save(img_dir / "fortynine.png")
            f = Path(d) / "manual.md"
            f.write_text("![50](img/fifty.png)\n![49](img/fortynine.png)\n")
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["present"], 1)
            self.assertEqual(check["placeholder_png_count"], 1)

    def test_unreplaced_scrennshot_placeholder_counts_as_missing(self):
        """v0.3.2: `[SCREENSHOT: foo.png]` text still in the manual
        (not replaced with `![alt](path)`) is a missing asset. v0.3.1
        only scanned `![alt](path)` links; this catches the half-fix
        where the LLM writes the placeholder syntax but never
        records a real asset."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                [SCREENSHOT: login-sso.png]
                [VIDEO: demo-flow.mp4]
                [AI ANNOTATE: hero]
            """))
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            # 3 placeholders, all unreplaced. AI ANNOTATE is also
            # counted by this regex (matches `[AI ANNOTATE: x]`) but the
            # AI ANNOTATE entry's "name" won't have a `.ext`, so
            # it's still treated as unreplaced.
            self.assertGreaterEqual(check["unreplaced_placeholder_count"], 2,
                                    msg=f"expected ≥2 unreplaced placeholders, got {check}")
            self.assertFalse(check["ok"])

    def test_unreplaced_placeholder_in_code_fence_ignored(self):
        """v0.3.2: `[SCREENSHOT: x]` text inside a fenced code block
        (a doc example showing the syntax) must NOT count."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ```
                [SCREENSHOT: doc-example.png]
                [VIDEO: another.mp4]
                ```
            """))
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["unreplaced_placeholder_count"], 0)

    def test_combined_image_link_and_placeholder_aggregation(self):
        """v0.3.2: total = image links + unreplaced placeholders. A
        manual with both kinds of references reports the right counts
        and the right total."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            Image.new("RGB", (1280, 800), "white").save(img_dir / "ok.png")
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ![ok](img/ok.png)
                [SCREENSHOT: not-yet.png]
            """))
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            check = next(c for c in data[0]["checks"] if c["name"] == "screenshot files exist")
            self.assertEqual(check["present"], 1)
            self.assertEqual(check["unreplaced_placeholder_count"], 1)
            self.assertEqual(check["threshold"], 2)
            # 1 image link + 1 placeholder = 2 total
            # 1 present + 1 unreplaced = 2 accounted for, but present (1)
            # != total (2), so ok=False
            self.assertFalse(check["ok"])

    def test_human_output_shows_breakdown(self):
        """v0.3.2: human output breaks down the 3 failure modes
        (missing / placeholder / unreplaced) so the user can see WHY."""
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            Image.new("RGB", (1, 1), "gray").save(img_dir / "stub.png")
            f = Path(d) / "manual.md"
            f.write_text(textwrap.dedent("""\
                # Manual
                ![stub](img/stub.png)
                [SCREENSHOT: missing.png]
            """))
            r = run([str(f)])
            # Breakdown should mention both 1x1 placeholder PNGs AND
            # unreplaced [SCREENSHOT:]/[VIDEO:]
            self.assertIn("1×1 placeholder PNGs", r.stdout)
            self.assertIn("unreplaced", r.stdout)


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


class ScreenshotUniqueTests(unittest.TestCase):
    """v0.4.0: opt-in --unique check for content-hash duplicates."""

    def _write_png(self, path: Path, payload: bytes = b"\x00" * 32) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Use a valid PNG header so PIL doesn't choke if loaded. We
        # only need a stable hash for the check; size doesn't matter.
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + payload)

    def _make_manual(self, d: str, refs: list[str]) -> Path:
        f = Path(d) / "manual.md"
        lines = ["# Manual", ""]
        for ref in refs:
            lines.append(f"![x]({ref})")
        f.write_text("\n".join(lines))
        return f

    def test_unique_passes_when_all_files_distinct(self):
        """v0.4.0: when 3 referenced PNGs have 3 distinct SHA256,
        --unique reports 0 duplicates, ok=True."""
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "img"
            self._write_png(img / "a.png", b"a" * 32)
            self._write_png(img / "b.png", b"b" * 32)
            self._write_png(img / "c.png", b"c" * 32)
            f = self._make_manual(d, ["img/a.png", "img/b.png", "img/c.png"])
            r = run(["--json", "--unique", str(f)])
            data = json.loads(r.stdout)
            check = next(
                c for c in data[0]["checks"]
                if c["name"] == "screenshot unique (no duplicate content)"
            )
            self.assertTrue(check["ok"])
            self.assertEqual(check["duplicate_count"], 0)
            self.assertEqual(check["unique_hashes"], 3)

    def test_unique_fails_when_two_files_share_content(self):
        """v0.4.0: dashboard-home.png and module-map.png both
        pointing at the same PNG bytes → ok=False, duplicate group
        contains both filenames."""
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "img"
            # Same bytes = same SHA256 = bug we're catching.
            self._write_png(img / "dashboard-home.png", b"X" * 32)
            self._write_png(img / "module-map.png", b"X" * 32)
            self._write_png(img / "real-other.png", b"Y" * 32)
            f = self._make_manual(
                d,
                ["img/dashboard-home.png", "img/module-map.png", "img/real-other.png"],
            )
            r = run(["--json", "--unique", str(f)])
            data = json.loads(r.stdout)
            check = next(
                c for c in data[0]["checks"]
                if c["name"] == "screenshot unique (no duplicate content)"
            )
            self.assertFalse(check["ok"])
            self.assertEqual(check["duplicate_count"], 1)
            self.assertEqual(set(check["duplicates"][0]["files"]),
                             {"dashboard-home.png", "module-map.png"})
            self.assertEqual(check["duplicates"][0]["occurrences"], 2)
            # Overall file should be FAIL even without --strict
            # (--unique flips its own ok=False).
            self.assertFalse(data[0]["ok"])

    def test_unique_on_by_default(self):
        """v1.1.0: --unique is now DEFAULT. Use --no-unique to opt out.
        A file with duplicate-content images fails the unique check
        by default (use --unique-allow to whitelist shared assets)."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "a.png", b"X" * 32)
            self._write_png(img_dir / "b.png", b"X" * 32)
            f = Path(d) / "good.md"
            f.write_text(GOOD)
            r = run(["--json", str(f)])  # no flags
            data = json.loads(r.stdout)
            names = [c["name"] for c in data[0]["checks"]]
            # v1.1.0: --unique is now in the default check set
            self.assertIn("screenshot unique (no duplicate content)", names)
            # And it actually catches the duplicate -> ok=False
            self.assertFalse(data[0]["ok"])

    def test_unique_no_unique_flag(self):
        """v1.1.0: --no-unique explicitly disables the unique check
        (backwards compat with v0.3.x / v0.4.x behavior)."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "a.png", b"X" * 32)
            self._write_png(img_dir / "b.png", b"X" * 32)
            f = Path(d) / "good.md"
            f.write_text(GOOD)
            r = run(["--json", "--no-unique", str(f)])
            data = json.loads(r.stdout)
            names = [c["name"] for c in data[0]["checks"]]
            self.assertNotIn(
                "screenshot unique (no duplicate content)", names,
                "unique check should be off when --no-unique is passed"
            )

    def test_unique_allow_whitelist(self):
        """v0.4.0: --unique-allow=logo.png,branding.png lets you
        intentionally reuse a shared asset without flagging.

        Setup: 3 PNGs sharing ONE hash, but logo.png is whitelisted.
        Without --unique-allow: 3-way duplicate (FAIL).
        With --unique-allow=logo.png: 2-way duplicate (still FAIL,
        proves filter only excluded the one whitelisted name).
        With --unique-allow=logo.png,header.png,branding.png:
        1 hash with 0 non-whitelisted references (PASS).
        """
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "img"
            self._write_png(img / "logo.png", b"X" * 32)
            self._write_png(img / "header.png", b"X" * 32)
            self._write_png(img / "branding.png", b"X" * 32)
            self._write_png(img / "real.png", b"Y" * 32)
            f = self._make_manual(
                d, ["img/logo.png", "img/header.png",
                    "img/branding.png", "img/real.png"]
            )
            # Case A: whitelist excludes ALL 3 colliders -> PASS
            r = run([
                "--json", "--unique",
                "--unique-allow=logo.png,header.png,branding.png",
                str(f),
            ])
            data = json.loads(r.stdout)
            check = next(
                c for c in data[0]["checks"]
                if c["name"] == "screenshot unique (no duplicate content)"
            )
            self.assertTrue(
                check["ok"],
                msg=f"all 3 colliders whitelisted should PASS, got: {check}",
            )
            # Case B: whitelist excludes only 1 -> still 2-way FAIL
            r = run([
                "--json", "--unique",
                "--unique-allow=logo.png",
                str(f),
            ])
            data = json.loads(r.stdout)
            check = next(
                c for c in data[0]["checks"]
                if c["name"] == "screenshot unique (no duplicate content)"
            )
            self.assertFalse(
                check["ok"],
                msg=f"2 remaining colliders should FAIL, got: {check}",
            )
            self.assertEqual(
                set(check["duplicates"][0]["files"]),
                {"header.png", "branding.png"},
            )

    def test_unique_ignores_missing_files(self):
        """v0.4.0: when a referenced PNG doesn't exist on disk,
        _check_screenshot_unique skips it (file-existence is
        check #7's job; we shouldn't double-report)."""
        with tempfile.TemporaryDirectory() as d:
            # Don't create the file
            f = self._make_manual(d, ["img/missing.png"])
            r = run(["--json", "--unique", str(f)])
            data = json.loads(r.stdout)
            check = next(
                c for c in data[0]["checks"]
                if c["name"] == "screenshot unique (no duplicate content)"
            )
            # 0 unique hashes, 0 duplicates, ok=True
            self.assertTrue(check["ok"])
            self.assertEqual(check["unique_hashes"], 0)


def _doc_with_frontmatter(description: str = "", body: str = "") -> str:
    fm = "---\ntitle: T\nmodule: m\n"
    if description is not None:
        fm += f"description: {description}\n"
    fm += "---\n\n"
    return fm + body + "\n"


class FrontmatterDescriptionTests(unittest.TestCase):
    """v1.2.0: frontmatter `description` is required + non-empty
    (INTEGRATION §3.5 viewer search excerpt)."""

    def _desc_check(self, text: str) -> dict:
        r = run(["--json", "-"])
        # write to a temp file (validate_file needs a path; frontmatter
        # check does not touch the filesystem, so path is nominal)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
            path = f.name
        try:
            data = json.loads(run(["--json", path]).stdout)
        finally:
            os.unlink(path)
        return next(c for c in data[0]["checks"]
                   if c["name"].startswith("frontmatter_description"))

    def test_filled_description_passes(self):
        c = self._desc_check(_doc_with_frontmatter(
            description="本册面向报表配置员,讲怎么新建和发布报表"))
        self.assertTrue(c["ok"])
        self.assertTrue(c["has_field"])

    def test_missing_description_fails(self):
        text = "---\ntitle: T\nmodule: m\n---\n\n# hi\n"
        c = self._desc_check(text)
        self.assertFalse(c["ok"])
        self.assertFalse(c["has_field"])

    def test_empty_description_fails(self):
        c = self._desc_check(_doc_with_frontmatter(description="", body="# hi"))
        self.assertFalse(c["ok"])

    def test_placeholder_description_fails(self):
        for stub in ("占位", "<TODO: fill>", "xxx", "<your-desc>"):
            c = self._desc_check(_doc_with_frontmatter(description=stub))
            self.assertFalse(c["ok"], msg=f"stub {stub!r} should FAIL")


class UnfilledTemplateTermsTests(unittest.TestCase):
    """v1.2.0: catch template prose the LLM left literal in the
    deliverable (`对应地址`, `手册所在目录`, `起静态站服务` as a
    pseudo-command). Real backtick commands must NOT trip it."""

    def _term_check(self, body: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(_doc_with_frontmatter("ok desc", body))
            path = f.name
        try:
            data = json.loads(run(["--json", path]).stdout)
        finally:
            os.unlink(path)
        return next(c for c in data[0]["checks"]
                   if c["name"].startswith("unfilled_template_terms"))

    def test_clean_text_passes(self):
        c = self._term_check("打开 http://localhost:8088/ 进入系统。")
        self.assertTrue(c["ok"], msg=str(c))

    def test_real_command_not_stub_not_flagged(self):
        # The REAL command the stub stands for is fine:
        c = self._term_check("运行 `python3 -m http.server 8088` 然后开浏览器。")
        self.assertTrue(c["ok"], msg=str(c))

    def test_stub_token_in_backticks_STILL_flagged(self):
        # v1.2.0 design: these three stubs are NEVER valid literals,
        # even inside backticks. The ehr manual shipped them
        # backtick-wrapped to disguise empty prose — raw scan must
        # catch them so the disguise does not work.
        c = self._term_check("浏览器开 `对应地址/user-manual.html`")
        self.assertFalse(c["ok"], msg=f"backtick-wrapped stub must still FAIL: {c}")
        c = self._term_check("在 `起静态站服务 8088` 里跑。")
        self.assertFalse(c["ok"], msg=str(c))
        c = self._term_check("进入 `手册所在目录/` 目录。")
        self.assertFalse(c["ok"], msg=str(c))

    def test_bare_对应地址_flagged(self):
        c = self._term_check("浏览器开 对应地址/user-manual.html")
        self.assertFalse(c["ok"], msg=str(c))
        offenders = " ".join(o["match"] for o in c["offenders"])
        self.assertIn("对应地址", offenders)

    def test_bare_手册所在目录_flagged(self):
        c = self._term_check("server 起在 手册所在目录/ 根目录")
        self.assertFalse(c["ok"], msg=str(c))

    def test_bare_起静态站服务_in_prose_flagged(self):
        c = self._term_check("跑 起静态站服务 8088 即可。")
        self.assertFalse(c["ok"], msg=str(c))

    def test_your_placeholder_flagged(self):
        c = self._term_check("地址见 <your-default-url>。")
        self.assertFalse(c["ok"], msg=str(c))

    def test_real_default_url_not_flagged(self):
        # The known user-facing default URL (INTEGRATION ships this
        # literal) must NOT trip the term check.
        c = self._term_check("打开 http://localhost:8088/ 进入系统。")
        self.assertTrue(c["ok"], msg=str(c))


def _md_with_card(steps_body: str, demo_video: str = "") -> str:
    """Build a minimal doc with one task card. `demo_video` becomes a
    `#### 演示视频` block placed before `#### 步骤`. `steps_body` is
    the literal text of the `#### 步骤` block (no leading heading)."""
    demo = (
        f"\n#### 演示视频\n\n{demo_video}\n\n"
        if demo_video else ""
    )
    return f"""---
title: T
module: m
description: ok
---

### 任务卡 1: 测试任务卡

> ⚠️ **操作前必看**
> - 注意

**适用角色**: admin
**前置条件**: x
{demo}#### 步骤

{steps_body}

#### 成功后看到

- ok

#### 字段说明

- x

#### 如果你卡住了

- x

#### 相关任务

- x
"""


class VideoOutsideStepsTests(unittest.TestCase):
    """v2.2.0: §2.6 — videos live in a `#### 演示视频` section before
    `#### 步骤`. The `#### 步骤` block must contain zero `.mp4)`
    references. Catches the LLM habit of pasting `[VIDEO:](path.mp4)`
    onto a step line."""

    def _vs_check(self, text: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
            path = f.name
        try:
            data = json.loads(run(["--json", path]).stdout)
        finally:
            os.unlink(path)
        return next(c for c in data[0]["checks"]
                   if c["name"].startswith("video_outside_steps"))

    def test_video_in_demo_section_passes(self):
        body = "1. 打开页面![x](a.png)\n2. 点按钮![y](b.png)\n"
        demo = "[VIDEO: 演示](flow.mp4)"
        c = self._vs_check(_md_with_card(body, demo))
        self.assertTrue(c["ok"], msg=str(c))
        self.assertEqual(c["flagged"], 0)

    def test_video_inside_steps_fails(self):
        # The bad pattern observed in the ehr manual: LLM pasted the
        # video inline on a step line.
        body = "1. 打开页面![x](a.png)\n2. 点按钮 [VIDEO: 演示](flow.mp4)\n3. 完成![y](c.png)\n"
        c = self._vs_check(_md_with_card(body))
        self.assertFalse(c["ok"], msg=str(c))
        self.assertGreaterEqual(c["flagged"], 1)
        self.assertIn("flow.mp4", c["offenders"][0]["match"])

    def test_steps_without_video_passes(self):
        body = "1. 打开页面![x](a.png)\n2. 点按钮![y](b.png)\n"
        c = self._vs_check(_md_with_card(body))
        self.assertTrue(c["ok"], msg=str(c))

    def test_video_after_steps_passes(self):
        # The step block is delimited by the next heading, so a video
        # placed under `#### 成功后看到` is OUTSIDE the steps block.
        # (Allowed by the rule — section after steps. The check only
        # forbids videos INSIDE the steps block.)
        body = "1. 打开页面![x](a.png)\n2. 点按钮![y](b.png)\n"
        text = _md_with_card(body)
        text = text.replace(
            "#### 成功后看到\n\n- ok",
            "#### 成功后看到\n\n[VIDEO: 回放](replay.mp4)\n\n- ok",
        )
        c = self._vs_check(text)
        self.assertTrue(c["ok"], msg=str(c))




class ScreenshotUsesAnnotatedTests(unittest.TestCase):
    """v1.1.0: alt text "红框:..." / "箭头:..." must reference the
    `.annotated.png` sibling, not the bare `<name>.png`. This check
    catches the ehr-manual gap where alt text claimed a red box but
    the image was the unannotated PNG.
    """

    @staticmethod
    def _write_png(path: Path, content: bytes) -> None:
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + content)

    @staticmethod
    def _make_manual(d: str, body: str) -> Path:
        # Minimal skeleton with all required sections so the OTHER
        # checks pass; we only care about the new check.
        text = """---
title: t
module: m
module_code: m
description: d
version: 1.0.0
version_date: 2026-01-01
audience: x
task: x
prerequisites: x
related: []
---
## 文档说明
## 读法指南
## 目录
- [x](#x)
## 修订历史
## 术语表
## 系统概述
## 快速开始
## 角色与权限速查
| 角色 | 权限 |
| --- | --- |
| x | y |
## 任务卡
""" + body + """
## 字段参考
## 配置参考
## 故障速查
## 常见问题
## 附录 A: 错误码速查
| a | b | c | d | e | f |
| --- | --- | --- | --- | --- | --- |
## 附录 B: 联系支持
"""
        f = Path(d) / "manual.md"
        f.write_text(text)
        return f

    def test_bare_png_with_red_box_alt_fails(self):
        """alt text mentions red box, but image is bare .png and
        the .annotated.png sibling exists on disk -> FAIL."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "01-list.png", b"a" * 32)
            self._write_png(img_dir / "01-list.annotated.png", b"annotated" * 8)
            f = self._make_manual(
                d,
                "### 任务卡 1: x\n\n> ⚠️ 操作前必看\n- x\n\n**适用角色**: x\n**前置条件**: x\n**入口**: x\n\n#### 步骤\n\n1. 点这里![红框:点登录](img/01-list.png)\n",
            )
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            checks = {c["name"]: c for c in data[0]["checks"]}
            ann = checks.get("screenshot_uses_annotated (alt text matches annotated sibling)")
            self.assertIsNotNone(ann)
            self.assertFalse(ann["ok"])
            self.assertEqual(ann["flagged"], 1)
            self.assertEqual(ann["offenders"][0]["ref"], "img/01-list.png")
            self.assertTrue(ann["offenders"][0]["annotated_sibling"].endswith("img/01-list.annotated.png"))
            self.assertIn("红框", ann["offenders"][0]["alt"])

    def test_annotated_png_with_red_box_alt_passes(self):
        """alt text mentions red box AND image is .annotated.png -> pass."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "01-list.annotated.png", b"annotated" * 8)
            f = self._make_manual(
                d,
                "### 任务卡 1: x\n\n> ⚠️ 操作前必看\n- x\n\n**适用角色**: x\n**前置条件**: x\n**入口**: x\n\n#### 步骤\n\n1. 点这里![红框:点登录](img/01-list.annotated.png)\n",
            )
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            checks = {c["name"]: c for c in data[0]["checks"]}
            ann = checks.get("screenshot_uses_annotated (alt text matches annotated sibling)")
            self.assertIsNotNone(ann)
            self.assertTrue(ann["ok"])
            self.assertEqual(ann["flagged"], 0)

    def test_bare_png_with_neutral_alt_passes(self):
        """alt text doesn't mention red box/arrow/etc -> pass even if
        .annotated.png exists (we don't second-guess neutral alts)."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "01-list.png", b"a" * 32)
            self._write_png(img_dir / "01-list.annotated.png", b"annotated" * 8)
            f = self._make_manual(
                d,
                "### 任务卡 1: x\n\n> ⚠️ 操作前必看\n- x\n\n**适用角色**: x\n**前置条件**: x\n**入口**: x\n\n#### 步骤\n\n1. 点这里![截图](img/01-list.png)\n",
            )
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            checks = {c["name"]: c for c in data[0]["checks"]}
            ann = checks["screenshot_uses_annotated (alt text matches annotated sibling)"]
            self.assertTrue(ann["ok"])
            self.assertEqual(ann["flagged"], 0)

    def test_no_annotated_sibling_passes(self):
        """alt mentions red box, but no .annotated.png sibling exists
        (recorder in screenshot-only mode) -> pass (no fix possible)."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "01-list.png", b"a" * 32)
            f = self._make_manual(
                d,
                "### 任务卡 1: x\n\n> ⚠️ 操作前必看\n- x\n\n**适用角色**: x\n**前置条件**: x\n**入口**: x\n\n#### 步骤\n\n1. 点这里![红框:点登录](img/01-list.png)\n",
            )
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            checks = {c["name"]: c for c in data[0]["checks"]}
            ann = checks["screenshot_uses_annotated (alt text matches annotated sibling)"]
            self.assertTrue(ann["ok"])
            self.assertEqual(ann["flagged"], 0)

    def test_annotated_relaxed_flag(self):
        """--annotated-relaxed downgrades the check to a warning
        (ok=True even when offenders exist)."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "01-list.png", b"a" * 32)
            self._write_png(img_dir / "01-list.annotated.png", b"annotated" * 8)
            f = self._make_manual(
                d,
                "### 任务卡 1: x\n\n> ⚠️ 操作前必看\n- x\n\n**适用角色**: x\n**前置条件**: x\n**入口**: x\n\n#### 步骤\n\n1. 点这里![红框:点登录](img/01-list.png)\n",
            )
            r = run(["--json", "--annotated-relaxed", str(f)])
            data = json.loads(r.stdout)
            checks = {c["name"]: c for c in data[0]["checks"]}
            ann = checks["screenshot_uses_annotated (alt text matches annotated sibling)"]
            self.assertTrue(ann["ok"])
            self.assertEqual(ann["flagged"], 1)
            self.assertTrue(ann["relaxed"])

    def test_arrow_keyword(self):
        """箭头 keyword also fires the check."""
        with tempfile.TemporaryDirectory() as d:
            img_dir = Path(d) / "img"
            img_dir.mkdir()
            self._write_png(img_dir / "02-detail.png", b"a" * 32)
            self._write_png(img_dir / "02-detail.annotated.png", b"annotated" * 8)
            f = self._make_manual(
                d,
                "### 任务卡 1: x\n\n> ⚠️ 操作前必看\n- x\n\n**适用角色**: x\n**前置条件**: x\n**入口**: x\n\n#### 步骤\n\n1. 点这里![箭头:点这里](img/02-detail.png)\n",
            )
            r = run(["--json", str(f)])
            data = json.loads(r.stdout)
            checks = {c["name"]: c for c in data[0]["checks"]}
            ann = checks["screenshot_uses_annotated (alt text matches annotated sibling)"]
            self.assertFalse(ann["ok"])
            self.assertEqual(ann["flagged"], 1)




# v2.3.0: anchor-internal-link check
class BrokenAnchorTests(unittest.TestCase):
    """v2.3.0: §3 — every internal `](#slug)` link must resolve to a
    real heading slug. The 2026-06 ehr audit found 8 broken anchors
    in the overview manual (heading "任务卡 1: 确认" with link
    "#任务卡-1确认", missing the space)."""

    def _check(self, text: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
            path = f.name
        try:
            data = json.loads(run(["--json", path]).stdout)
        finally:
            os.unlink(path)
        return next(c for c in data[0]["checks"]
                    if c["name"].startswith("broken_anchors"))

    def test_matching_anchors_pass(self):
        text = """
### 任务卡 1: 创建合同

[link](#任务卡-1-创建合同)

### 任务卡 2: 删除合同

[link](#任务卡-2-删除合同)
"""
        c = self._check(text)
        self.assertTrue(c["ok"], msg=str(c))
        self.assertEqual(c["flagged"], 0)

    def test_missing_space_in_anchor_fails(self):
        # The exact ehr bug: heading has space after `:`,
        # link slug drops the space.
        text = """
### 任务卡 1: 创建合同

[link](#任务卡-1创建合同)
"""
        c = self._check(text)
        self.assertFalse(c["ok"], msg=str(c))
        self.assertEqual(c["flagged"], 1)
        self.assertEqual(c["offenders"][0]["ref"], "任务卡-1创建合同")

    def test_typo_in_anchor_fails(self):
        text = """
### 任务卡 1: 创建合同

[link](#任务卡-1-创建合)
"""
        c = self._check(text)
        self.assertFalse(c["ok"])
        self.assertEqual(c["flagged"], 1)

    def test_code_fence_skipped(self):
        # Anchors in code blocks are example documentation, not real links.
        text = """
### 任务卡 1: 创建合同

```
[link](#nonexistent)
```

[real link](#任务卡-1-创建合同)
"""
        c = self._check(text)
        self.assertTrue(c["ok"], msg=str(c))


# v2.3.0: placeholder URL check
class PlaceholderUrlTests(unittest.TestCase):
    """v2.3.0: §16 — asset paths that look like obvious placeholders
    (placeholder.invalid, example.com, <TODO:>, <your-...>) must be
    rejected. _check_screenshot_files_exist only checks local relative
    paths, so the ehr manual's 6 `https://placeholder.invalid/...`
    references slipped through."""

    def _check(self, text: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
            path = f.name
        try:
            data = json.loads(run(["--json", path]).stdout)
        finally:
            os.unlink(path)
        return next(c for c in data[0]["checks"]
                    if c["name"].startswith("placeholder_url"))

    def test_local_relative_paths_pass(self):
        text = "![a](../screenshots/sys/01.png)\n![b](img/b.jpg)\n"
        c = self._check(text)
        self.assertTrue(c["ok"], msg=str(c))
        self.assertEqual(c["flagged"], 0)

    def test_legit_frontend_url_passes(self):
        # http://localhost:8088/ is the user-facing entry per
        # §2.7.1 类 7 — not a placeholder.
        text = "![a](http://localhost:8088/assets/logo.png)\n"
        c = self._check(text)
        self.assertTrue(c["ok"], msg=str(c))

    def test_placeholder_invalid_fails(self):
        text = "![a](https://placeholder.invalid/screenshots/sys/01.png)\n"
        c = self._check(text)
        self.assertFalse(c["ok"])
        self.assertEqual(c["flagged"], 1)
        self.assertIn("placeholder.invalid", c["offenders"][0]["path"])

    def test_example_com_fails(self):
        text = "![a](https://example.com/foo.png)\n"
        c = self._check(text)
        self.assertFalse(c["ok"])
        self.assertEqual(c["flagged"], 1)

    def test_html_img_with_placeholder_fails(self):
        text = '<img src="https://placeholder.invalid/x.png">\n'
        c = self._check(text)
        self.assertFalse(c["ok"])
        self.assertEqual(c["flagged"], 1)

    def test_html_video_with_placeholder_fails(self):
        text = '<video src="https://placeholder.invalid/flow.mp4"></video>\n'
        c = self._check(text)
        self.assertFalse(c["ok"])
        self.assertEqual(c["flagged"], 1)

    def test_code_fence_skipped(self):
        text = """
```markdown
![doc example](https://placeholder.invalid/foo.png)
```

![real local](img/ok.png)
"""
        c = self._check(text)
        self.assertTrue(c["ok"], msg=str(c))


# v2.3.0: one-task-card-one-operation check
class TaskCardStepsCountTests(unittest.TestCase):
    """v2.3.0: §2.1 — one task card = one specific operation. Each
    `### 任务卡 N:` block must contain exactly one `#### 步骤`
    subsection. The ehr manual's report task card 9 (发布/停用) had
    two `#### 步骤` blocks."""

    def _check(self, text: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(text)
            path = f.name
        try:
            data = json.loads(run(["--json", path]).stdout)
        finally:
            os.unlink(path)
        return next(c for c in data[0]["checks"]
                    if c["name"].startswith("task_card_steps_count"))

    def test_single_steps_block_passes(self):
        text = """
### 任务卡 1: 创建合同

#### 步骤

1. 打开页面
2. 填写表单
"""
        c = self._check(text)
        self.assertTrue(c["ok"], msg=str(c))
        self.assertEqual(c["well_formed_count"], 1)

    def test_two_steps_blocks_fails(self):
        # The exact ehr bug: 发布/停用 packed into one card.
        text = """
### 任务卡 9: 发布 / 停用报表

#### 步骤(发布)

1. 点发布

#### 步骤(停用)

1. 点停用
"""
        c = self._check(text)
        self.assertFalse(c["ok"])
        self.assertEqual(c["flagged"], 1)
        self.assertEqual(c["offenders"][0]["steps_count"], 2)
        self.assertIn("任务卡 9", c["offenders"][0]["card"])

    def test_no_steps_blocks_passes(self):
        # Card uses 演示视频 only — 0 steps is OK.
        text = """
### 任务卡 1: 视频演示

#### 演示视频

[VIDEO: demo](demo.mp4)
"""
        c = self._check(text)
        self.assertTrue(c["ok"], msg=str(c))
        # 0 well-formed because the check only counts cards with
        # exactly 1 steps block, but no offenders either.
        self.assertEqual(c["flagged"], 0)

    def test_mixed_cards(self):
        # 3 cards, 1 well-formed, 1 with 2 step blocks, 1 with 0.
        text = """
### 任务卡 1: well

#### 步骤

1. a

### 任务卡 2: bad

#### 步骤(a)

1. x

#### 步骤(b)

1. y

### 任务卡 3: empty

正文无步骤段。
"""
        c = self._check(text)
        self.assertFalse(c["ok"])
        self.assertEqual(c["well_formed_count"], 1)
        self.assertEqual(c["flagged"], 1)
        self.assertEqual(c["total_task_cards"], 3)


if __name__ == "__main__":
    unittest.main()



# v1.1.0: hard gate. Validate that without a recording_manifest.json the
# validator exits 2 with a pause banner; with a valid manifest the
# pre-flight passes and the other checks run normally. With --no-hard-gate
# the gate is bypassed.
class RecordingPhaseActuallyRanTests(unittest.TestCase):
    """v1.1.0: SKILL.md §14 hard gate. The LLM agent must produce
    docs/user-manual/recording_manifest.json (via the recorder skill
    CLI) or the manual is not a valid deliverable. These tests pin
    that contract.
    """

    def _make_manual_dir(self, tmp: Path, *, with_manifest: bool,
                         manifest: dict | None = None,
                         md_body: str | None = None) -> Path:
        """Create docs/user-manual/manual/<name>.md (+ optional manifest)."""
        manual_dir = tmp / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True, exist_ok=True)
        if md_body is None:
            md_body = (
                "---\n"
                "title: T\n"
                "module: m\n"
                "description: test description for search excerpt\n"
                "---\n"
                "\n# T\n\n## 适用角色\n- x\n"
            )
        (manual_dir / "t.md").write_text(md_body, encoding="utf-8")
        if with_manifest:
            (tmp / "docs" / "user-manual" / "recording_manifest.json").write_text(
                json.dumps(manifest or {
                    "schema_version": "1.0",
                    "ran_at": "2026-06-27T00:00:00+00:00",
                    "manual": "manual/t.md",
                    "recorder_session_id": "sess-test",
                    "recorder_cli_exit": 0,
                    "dev_server": {
                        "url": "http://localhost:8080",
                        "reachable": True,
                        "readiness_status": "green",
                        "probe_host": "test-host",
                    },
                    "assets": {
                        "screenshots": ["screenshots/t/01.png"],
                        "videos": [],
                        "ai_annotated": [],
                    },
                    "totals": {"screenshots": 1, "videos": 0, "ai_annotated": 0},
                }, indent=2),
                encoding="utf-8",
            )
        return manual_dir / "t.md"

    def test_no_manifest_blocks_validate(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = self._make_manual_dir(tmp, with_manifest=False)
            r = run_raw([str(md)])
            self.assertEqual(r.returncode, 2, msg=f"expected exit 2, got {r.returncode}\nstderr: {r.stderr}")
            self.assertIn("HARD GATE FAILED", r.stderr)
            self.assertIn("recording phase did not actually run", r.stderr)
            self.assertIn("recording_manifest.json", r.stderr)

    def test_no_manifest_blocks_even_without_strict(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = self._make_manual_dir(tmp, with_manifest=False)
            # No --strict, but the hard gate still fires (it ignores --strict).
            r = run_raw([str(md)])
            self.assertEqual(r.returncode, 2)

    def test_no_hard_gate_escape_hatch(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = self._make_manual_dir(tmp, with_manifest=False)
            r = run_raw(["--no-hard-gate", str(md)])
            # Without --strict, validate-output exits 0 even with FAILs
            # from the other checks. We only care that the pre-flight
            # banner did NOT print.
            self.assertNotIn("HARD GATE FAILED", r.stderr)
            self.assertNotEqual(r.returncode, 2)

    def test_valid_manifest_passes_preflight(self):
        # v1.1.0 fix: a valid manifest means the pre-flight gate passes
        # (no exit 2, no HARD GATE FAILED banner). Other per-check
        # results are irrelevant to this test — the placeholder md is
        # deliberately minimal so other checks may fail.
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = self._make_manual_dir(tmp, with_manifest=True)
            r = run_raw(["--json", str(md)])
            self.assertNotEqual(r.returncode, 2, msg=f"pre-flight should pass; got exit {r.returncode}; stderr: {r.stderr}")
            self.assertNotIn("HARD GATE FAILED", r.stderr)
            data = json.loads(r.stdout)
            self.assertFalse(data[0].get("preflight_blocked", False))
            gate_check = next(
                (c for c in data[0]["checks"] if c["name"].startswith("recording_phase_actually_ran")),
                None,
            )
            self.assertIsNotNone(gate_check, msg=f"gate check missing in: {data[0]['checks']}")
            self.assertTrue(gate_check["ok"])

    def test_manifest_with_zero_screenshots_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            bad = {
                "schema_version": "1.0",
                "recorder_session_id": "sess-empty",
                "recorder_cli_exit": 0,
                "dev_server": {"url": "http://x", "reachable": True,
                               "readiness_status": "green", "probe_host": "h"},
                "assets": {"screenshots": [], "videos": [], "ai_annotated": []},
                "totals": {"screenshots": 0, "videos": 0, "ai_annotated": 0},
            }
            md = self._make_manual_dir(tmp, with_manifest=True, manifest=bad)
            r = run_raw([str(md)])
            self.assertEqual(r.returncode, 2)
            self.assertIn("no_screenshots", r.stderr)

    def test_manifest_with_recorder_nonzero_exit_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            bad = {
                "schema_version": "1.0",
                "recorder_session_id": "sess-fail",
                "recorder_cli_exit": 1,
                "dev_server": {"url": "http://x", "reachable": True,
                               "readiness_status": "green", "probe_host": "h"},
                "assets": {"screenshots": ["a.png"], "videos": [], "ai_annotated": []},
                "totals": {"screenshots": 1, "videos": 0, "ai_annotated": 0},
            }
            md = self._make_manual_dir(tmp, with_manifest=True, manifest=bad)
            r = run_raw([str(md)])
            self.assertEqual(r.returncode, 2)
            self.assertIn("recorder_failed", r.stderr)

    def test_manifest_with_unreachable_dev_server_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            bad = {
                "schema_version": "1.0",
                "recorder_session_id": "sess-dead",
                "recorder_cli_exit": 0,
                "dev_server": {"url": "http://x", "reachable": False,
                               "readiness_status": "red", "probe_host": "h"},
                "assets": {"screenshots": ["a.png"], "videos": [], "ai_annotated": []},
                "totals": {"screenshots": 1, "videos": 0, "ai_annotated": 0},
            }
            md = self._make_manual_dir(tmp, with_manifest=True, manifest=bad)
            r = run_raw([str(md)])
            self.assertEqual(r.returncode, 2)
            self.assertIn("dev_server_unreachable", r.stderr)

    def test_manifest_with_wrong_schema_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            bad = {"schema_version": "0.9", "recorder_cli_exit": 0}
            md = self._make_manual_dir(tmp, with_manifest=True, manifest=bad)
            r = run_raw([str(md)])
            self.assertEqual(r.returncode, 2)
            self.assertIn("schema_mismatch", r.stderr)

    def test_manifest_unreadable_json_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = self._make_manual_dir(tmp, with_manifest=False)
            (tmp / "docs" / "user-manual" / "recording_manifest.json").write_text(
                "{ this is not json", encoding="utf-8",
            )
            r = run_raw([str(md)])
            self.assertEqual(r.returncode, 2)
            self.assertIn("manifest_unreadable", r.stderr)

    def test_preflight_pause_banner_mentions_seven_steps(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = self._make_manual_dir(tmp, with_manifest=False)
            r = run_raw([str(md)])
            # The banner should enumerate the 6 steps + the
            # validate-output re-run, so the LLM agent can recover.
            for step in [
                "check-recording-readiness",
                "scan-recording-placeholders",
                "build-recorder-template",
                "recorder_plugin.cli run",
                "apply-recording-mapping",
                "write-recording-manifest",
            ]:
                self.assertIn(step, r.stderr, msg=f"banner missing step: {step}")



# v1.2.0: manifest_disk_consistency — manifest must list only files
# that are on disk, and report files on disk that aren't in the
# manifest.
class ManifestDiskConsistencyTests(unittest.TestCase):
    """v1.2.0: post-gate check that catches the 2026-06 ehr failure
    mode where manifest listed ~20 PNGs that no longer existed on
    disk. The v1.1.0 gate only validated manifest *content*; this
    check validates manifest *consistency with disk state*.
    """

    def _setup(self, tmp, *, manifest, on_disk):
        manual_dir = tmp / "docs" / "user-manual" / "manual"
        manual_dir.mkdir(parents=True, exist_ok=True)
        (manual_dir / "x.md").write_text(
            "---\ntitle: X\nmodule: x\ndescription: x for manifest test\n---\n\n# X\n",
            encoding="utf-8",
        )
        for rel in on_disk:
            p2 = tmp / "docs/user-manual" / rel
            p2.parent.mkdir(parents=True, exist_ok=True)
            p2.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
        if manifest is not None:
            (tmp / "docs/user-manual/recording_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8",
            )
        return manual_dir / "x.md"

    def test_manifest_only_path_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mf = {
                "schema_version": "1.0",
                "recorder_cli_exit": 0,
                "dev_server": {"reachable": True, "readiness_status": "green"},
                "assets": {
                    "screenshots": ["screenshots/x/01.png"],  # NOT on disk
                    "videos": [],
                    "ai_annotated": [],
                },
                "totals": {"screenshots": 1, "videos": 0, "ai_annotated": 0},
            }
            md = self._setup(tmp, manifest=mf, on_disk=[])
            r = run_raw(["--no-hard-gate", "--json", str(md)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("manifest_disk_consistency")), None)
            self.assertIsNotNone(check)
            self.assertFalse(check["ok"])
            self.assertIn("screenshots/x/01.png", check["manifest_only"])

    def test_disk_only_path_is_warn_not_fail(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mf = {
                "schema_version": "1.0",
                "recorder_cli_exit": 0,
                "dev_server": {"reachable": True, "readiness_status": "green"},
                "assets": {"screenshots": [], "videos": [], "ai_annotated": []},
                "totals": {"screenshots": 0, "videos": 0, "ai_annotated": 0},
            }
            md = self._setup(tmp, manifest=mf, on_disk=["screenshots/x/orphan.png"])
            r = run_raw(["--no-hard-gate", "--json", str(md)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("manifest_disk_consistency")), None)
            self.assertIsNotNone(check)
            # disk-only is reported but not a hard fail
            self.assertTrue(check["ok"])
            self.assertIn("screenshots/x/orphan.png", check["disk_only"])

    def test_consistent_manifest_passes(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mf = {
                "schema_version": "1.0",
                "recorder_cli_exit": 0,
                "dev_server": {"reachable": True, "readiness_status": "green"},
                "assets": {"screenshots": ["screenshots/x/01.png"], "videos": [], "ai_annotated": []},
                "totals": {"screenshots": 1, "videos": 0, "ai_annotated": 0},
            }
            md = self._setup(tmp, manifest=mf, on_disk=["screenshots/x/01.png"])
            r = run_raw(["--no-hard-gate", "--json", str(md)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("manifest_disk_consistency")), None)
            self.assertIsNotNone(check)
            self.assertTrue(check["ok"])
            self.assertEqual(check["manifest_only"], [])
            self.assertEqual(check["disk_only"], [])

    def test_no_manifest_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            md = self._setup(tmp, manifest=None, on_disk=["screenshots/x/01.png"])
            r = run_raw(["--no-hard-gate", "--json", str(md)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("manifest_disk_consistency")), None)
            self.assertIsNotNone(check)
            # Without a manifest, the pre-flight gate owns the failure case.
            # This check should be a no-op (ok=True) so it can run
            # independently of the gate.
            self.assertTrue(check["ok"])


# v1.2.0: file_type_sanity — catch the "manual.md is actually HTML"
# failure mode that bypassed v1.1.0 in the ehr 2026-06 audit.
class FileTypeSanityTests(unittest.TestCase):
    """v1.2.0: cheap first-line defense against non-markdown files
    being passed as .md. Without this, a file that was overwritten
    with an HTML viewer template would pass every other check
    (the pre-flight gate only validates manifest content; the rest
    of the regex-based checks happily match <h1>...</h1> as if it
    were a markdown heading).
    """

    def _md(self, d, name, body):
        p = Path(d) / name
        p.write_text(body, encoding="utf-8")
        return p

    def test_html_file_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._md(d, "x.md",
                "<!DOCTYPE html>\n<html><head><title>X</title></head>\n"
                "<body><h1>X</h1></body></html>")
            r = run_raw(["--no-hard-gate", "--json", str(f)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("file_type_sanity")), None)
            self.assertIsNotNone(check)
            self.assertFalse(check["ok"])
            self.assertEqual(check["reason"], "not_markdown")

    def test_valid_markdown_passes(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._md(d, "x.md",
                "---\ntitle: X\nmodule: x\ndescription: x\n---\n\n# X\n")
            r = run_raw(["--no-hard-gate", "--json", str(f)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("file_type_sanity")), None)
            self.assertIsNotNone(check)
            self.assertTrue(check["ok"])

    def test_no_frontmatter_or_h1_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._md(d, "x.md", "just some prose\nno structure at all")
            r = run_raw(["--no-hard-gate", "--json", str(f)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("file_type_sanity")), None)
            self.assertIsNotNone(check)
            self.assertFalse(check["ok"])
            self.assertEqual(check["reason"], "no_frontmatter_or_h1")

    def test_xml_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            f = self._md(d, "x.md", "<?xml version=\"1.0\"?>\n<root/>")
            r = run_raw(["--no-hard-gate", "--json", str(f)])
            data = json.loads(r.stdout)
            check = next((c for c in data[0]["checks"]
                          if c["name"].startswith("file_type_sanity")), None)
            self.assertIsNotNone(check)
            self.assertFalse(check["ok"])
