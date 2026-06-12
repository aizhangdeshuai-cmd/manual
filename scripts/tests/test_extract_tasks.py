"""Tests for extract-tasks.py. Run: python3 -m unittest scripts.tests.test_extract_tasks"""
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "extract-tasks.py"


class ExtractTasksTests(unittest.TestCase):
    def test_user_story_heading(self):
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "spec.md"
            spec.write_text(textwrap.dedent("""\
                # 字典管理设计

                ## 背景
                这是一段说明文字。

                ## 用户故事: 创建字典分类
                作为系统管理员,我希望创建字典分类,以便管理枚举值。

                ### 步骤
                - 打开字典管理页
                - 点击「新增分类」
                - 填写分类名称
                - 提交

                ## 下一节
                其他内容。
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(spec)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            tasks = json.loads(r.stdout)
            self.assertEqual(len(tasks), 1, msg=f"got {len(tasks)} tasks: {tasks}")
            t = tasks[0]
            self.assertIn("创建字典分类", t["task_name"])
            self.assertEqual(len(t["steps"]), 4)
            self.assertEqual(t["steps"][0], "打开字典管理页")

    def test_fallback_to_h2_with_bullets(self):
        """v0.2.2: fallback still works but requires >=3 bullets per section
        AND at least one bullet starting with an action verb. Sections like
        "Architecture" (bullets: 'Uses React', 'Why we chose Postgres') are
        filtered out because none of their bullets start with an action verb."""
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "spec.md"
            spec.write_text(textwrap.dedent("""\
                # 设计

                ## 创建字典分类
                这是个普通 H2,没"用户故事"前缀。

                - 打开字典管理
                - 点击「新增分类」
                - 填写分类名称
                - 提交

                ## 另一节
                - 打开另一节管理
                - 点击「新增项」
                - 提交另一节数据
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(spec)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            tasks = json.loads(r.stdout)
            # Both sections have 3+ bullets and start with action verbs → both picked up
            self.assertGreaterEqual(len(tasks), 2, f"expected >=2 task candidates, got {len(tasks)}: {tasks}")

    def test_fallback_filters_non_task_sections(self):
        """v0.2.2 regression: 'Architecture' / 'Data Model' sections with non-action
        bullets must NOT become task candidates in fallback mode."""
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "spec.md"
            spec.write_text(textwrap.dedent("""\
                # 设计

                ## Architecture
                We chose these tools.

                - Uses React for the frontend
                - Postgres for persistence
                - Why we chose Redis for caching

                ## Data Model
                The schema looks like this.

                - User has many Posts
                - Each Post belongs to a User
                - Categories form a tree

                ## 创建字典分类
                Real task below.

                - 打开字典管理
                - 点击「新增分类」
                - 填写分类名称
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(spec)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            tasks = json.loads(r.stdout)
            task_names = [t["task_name"] for t in tasks]
            # Architecture and Data Model should be filtered out (no action verbs)
            assert "Architecture" not in task_names, f"Architecture should be filtered: {task_names}"
            assert "Data Model" not in task_names, f"Data Model should be filtered: {task_names}"
            # Only the real task survives
            assert any("创建字典分类" in n for n in task_names), f"real task missing: {task_names}"

    def test_persona_detection(self):
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "spec.md"
            spec.write_text(textwrap.dedent("""\
                # 流程

                ## 用户故事: 业务专员审批合同
                作为业务专员,我应该能审批合同。

                - 打开待办
                - 审核
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(spec)], capture_output=True, text=True)
            tasks = json.loads(r.stdout)
            self.assertEqual(tasks[0]["persona"], "业务专员")

    def test_empty_input(self):
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "empty.md"
            spec.write_text("# 只有标题\n\n没有用户故事节。\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(spec)], capture_output=True, text=True)
            tasks = json.loads(r.stdout)
            # No explicit task headings, no bullets — 0 tasks
            self.assertEqual(len(tasks), 0)

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.md").write_text(textwrap.dedent("""\
                ## 用户故事: 创建 A
                - 步骤 1
            """), encoding="utf-8")
            (d / "b.md").write_text(textwrap.dedent("""\
                ## 用户故事: 创建 B
                - 步骤 1
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(d / "a.md"), str(d / "b.md")], capture_output=True, text=True)
            tasks = json.loads(r.stdout)
            self.assertEqual(len(tasks), 2)

    def test_glob_input(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "spec1.md").write_text("## 用户故事: T1\n- 步骤\n", encoding="utf-8")
            (d / "spec2.md").write_text("## 用户故事: T2\n- 步骤\n", encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(d / "*.md")], capture_output=True, text=True)
            tasks = json.loads(r.stdout)
            self.assertEqual(len(tasks), 2)


if __name__ == "__main__":
    unittest.main()
