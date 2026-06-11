"""Unit tests for scripts/validate-output.py."""
import json
import os
import subprocess
import tempfile
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
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(GOOD)
            path = f.name
        try:
            r = run([path])
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertIn("[OK", r.stdout)
            for needle in (
                "7-field hits=12",
                "操作前必看 blocks=3",
                "visual anchors=3",
                "appendix-A 6-col table=2",
                "role-permission matrix=1",
                "screenshot count=2",
            ):
                self.assertIn(needle, r.stdout, msg="missing " + needle)
        finally:
            os.unlink(path)

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
            self.assertTrue(data[0]["ok"])
            self.assertEqual(len(data[0]["checks"]), 6)
        finally:
            os.unlink(path)

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = Path(d) / "good.md"
            p2 = Path(d) / "bad.md"
            p1.write_text(GOOD)
            p2.write_text(BAD)
            r = run([str(p1), str(p2)])
            self.assertEqual(r.returncode, 0)
            self.assertIn("[OK", r.stdout)
            self.assertIn("[FAIL", r.stdout)


if __name__ == "__main__":
    unittest.main()
