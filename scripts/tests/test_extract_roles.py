import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "extract-roles.py"


class ExtractRolesTests(unittest.TestCase):
    def test_java_preauthorize(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            java = d / "src"
            java.mkdir()
            (java / "UserController.java").write_text(textwrap.dedent("""\
                @PreAuthorize("hasRole('ADMIN')")
                public class UserController {}

                @PreAuthorize("hasAnyRole('USER', 'MANAGER')")
                public class FooController {}
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(java)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            roles = json.loads(r.stdout)
            names = {x["role_name"] for x in roles}
            self.assertIn("ADMIN", names)
            self.assertIn("USER", names)
            self.assertIn("MANAGER", names)

    def test_java_secured(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            java = d / "src"
            java.mkdir()
            (java / "X.java").write_text('@Secured("AUDITOR")\nclass X {}\n', encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(java)], capture_output=True, text=True)
            roles = json.loads(r.stdout)
            names = {x["role_name"] for x in roles}
            self.assertIn("AUDITOR", names)

    def test_vue_v_permission(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fe = d / "fe"
            fe.mkdir()
            (fe / "A.vue").write_text('<button v-permission="[\'admin\', \'manager\']">X</button>\n', encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(d), str(fe)], capture_output=True, text=True)
            roles = json.loads(r.stdout)
            names = {x["role_name"] for x in roles}
            self.assertIn("admin", names)
            self.assertIn("manager", names)

    def test_vue_role_guard(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            fe = d / "fe"
            fe.mkdir()
            (fe / "A.vue").write_text('<RoleGuard :roles="[\'super\']"><p/></RoleGuard>\n', encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(d), str(fe)], capture_output=True, text=True)
            roles = json.loads(r.stdout)
            names = {x["role_name"] for x in roles}
            self.assertIn("super", names)

    def test_empty_backend(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            r = subprocess.run([sys.executable, str(SCRIPT), str(d)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            roles = json.loads(r.stdout)
            self.assertEqual(roles, [])

    def test_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "A.java").write_text('@PreAuthorize("hasRole(\'X\')")\nclass A {}\n', encoding="utf-8")
            (d / "B.java").write_text('@PreAuthorize("hasRole(\'X\')")\nclass B {}\n', encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(d)], capture_output=True, text=True)
            roles = json.loads(r.stdout)
            self.assertEqual(len(roles), 1)
            self.assertEqual(roles[0]["role_name"], "X")


if __name__ == "__main__":
    unittest.main()
