import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "extract-fields.py"


class ExtractFieldsTests(unittest.TestCase):
    def test_vue_el_form_item(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "UserForm.vue"
            f.write_text(textwrap.dedent("""\
                <template>
                  <el-form :model="form" :rules="rules">
                    <el-form-item prop="name" label="姓名">
                      <el-input v-model="form.name" placeholder="请输入姓名" />
                    </el-form-item>
                    <el-form-item prop="email" label="邮箱">
                      <el-input v-model="form.email" />
                    </el-form-item>
                  </el-form>
                </template>
                <script>
                export default {
                  data() { return { form: { name: '', email: '' } } },
                  rules: {
                    name: [{ required: true, message: '必填' }],
                  }
                }
                </script>
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            fields = json.loads(r.stdout)
            self.assertGreaterEqual(len(fields), 2)
            by_name = {f["name"]: f for f in fields}
            self.assertIn("name", by_name)
            self.assertEqual(by_name["name"]["label"], "姓名")
            self.assertTrue(by_name["name"]["required"])
            self.assertEqual(by_name["name"]["placeholder"], "请输入姓名")

    def test_vue_naive(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "Form.vue"
            f.write_text(textwrap.dedent("""\
                <n-form>
                  <n-form-item path="userId" label="用户 ID">
                    <n-input v-model:value="form.userId" />
                  </n-form-item>
                </n-form>
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            fields = json.loads(r.stdout)
            self.assertGreaterEqual(len(fields), 1)
            self.assertEqual(fields[0]["name"], "userId")

    def test_java_dto(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "UserDTO.java"
            f.write_text(textwrap.dedent("""\
                package com.example.dto;

                import jakarta.validation.constraints.*;

                public class UserDTO {
                    @NotBlank
                    @Size(min = 1, max = 50)
                    private String name;

                    @NotNull
                    @Email
                    private String email;

                    private Integer age;
                }
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "--java", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            fields = json.loads(r.stdout)
            self.assertEqual(len(fields), 3)
            by_name = {f["name"]: f for f in fields}
            self.assertTrue(by_name["name"]["required"])
            self.assertIn("Size", by_name["name"]["validators"])
            self.assertEqual(by_name["age"]["required"], False)

    def test_java_with_schema_description(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "UserDTO.java"
            f.write_text(textwrap.dedent("""\
                public class UserDTO {
                    /**
                     * 用户姓名
                     */
                    @Schema(description = "用户姓名,必填")
                    private String name;
                }
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "--java", str(f)], capture_output=True, text=True)
            fields = json.loads(r.stdout)
            self.assertEqual(fields[0]["description"], "用户姓名,必填")

    def test_type_inference(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "F.vue"
            f.write_text('<el-form-item prop="d" label="日期"></el-form-item>\n<el-form-item prop="st" label="状态"></el-form-item>\n', encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            fields = {f["name"]: f for f in json.loads(r.stdout)}
            self.assertEqual(fields["d"]["type"], "日期")
            self.assertEqual(fields["st"]["type"], "下拉选择")


if __name__ == "__main__":
    unittest.main()
