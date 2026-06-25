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


    def test_ruoyi_v_hasPermi(self):
        """RuoYi派系: v-hasPermi=['system:user:list']"""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "User.vue").write_text(textwrap.dedent("""\
                <template>
                  <el-button v-hasPermi="['system:user:list']">List</el-button>
                  <el-button v-hasPermi="['system:user:edit','system:user:remove']">Edit</el-button>
                </template>
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "/nonexistent", str(d)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            roles = json.loads(r.stdout)
            names = {x["role_name"] for x in roles}
            self.assertIn("system:user:list", names)
            self.assertIn("system:user:edit", names)
            self.assertIn("system:user:remove", names)
            frameworks = {x["framework"] for x in roles}
            self.assertIn("vue:v-hasPermi", frameworks)

    def test_ruoyi_router_top_level_permissions(self):
        """RuoYi派系: 路由对象顶层 permissions: [...] 数组(不在 meta{}里)"""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "router").mkdir()
            (d / "router" / "index.js").write_text(textwrap.dedent("""\
                export const dynamicRoutes = [
                  { path: '/system/user-auth', component: Layout,
                    permissions: ['system:user:edit'],
                    children: [
                      { path: 'role/:userId', component: () => import('@/x') }
                    ]
                  },
                  { path: '/admin', component: Layout, roles: ['admin'] }
                ]
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), "/nonexistent", str(d)], capture_output=True, text=True)
            roles = json.loads(r.stdout)
            perms = [x for x in roles if x["framework"] == "router:route-permissions"]
            rroles = [x for x in roles if x["framework"] == "router:route-roles"]
            self.assertEqual([p["role_name"] for p in perms], ["system:user:edit"])
            self.assertEqual([p["role_name"] for p in rroles], ["admin"])


if __name__ == "__main__":
    unittest.main()
