import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "extract-routes.py"


class ExtractRoutesTests(unittest.TestCase):
    def test_basic_routes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "router.ts"
            f.write_text(textwrap.dedent("""\
                export const routes = [
                  { path: '/login', name: 'Login', component: () => import('@/views/Login.vue'), meta: { requiresAuth: false, title: '登录' } },
                  { path: '/', component: MainLayout, meta: { requiresAuth: true },
                    children: [
                      { path: 'user', name: 'UserList', component: () => import('@/views/user/List.vue'), meta: { title: '用户管理' } },
                      { path: 'role', name: 'RoleList', component: () => import('@/views/role/List.vue') }
                    ]
                  }
                ]
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            routes = json.loads(r.stdout)
            self.assertGreaterEqual(len(routes), 4)
            paths = {rt["path"] for rt in routes}
            self.assertIn("/login", paths)
            self.assertIn("/user", paths)
            self.assertIn("/role", paths)

    def test_perms_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "router.ts"
            f.write_text(textwrap.dedent("""\
                export const routes = [
                  { path: '/admin', name: 'Admin', component: () => import('@/a.vue'), meta: { perms: ['sys:user:list', 'sys:user:edit'], title: '管理员' } }
                ]
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            routes = json.loads(r.stdout)
            self.assertEqual(routes[0]["perms"], ["sys:user:list", "sys:user:edit"])
            self.assertEqual(routes[0]["title"], "管理员")

    def test_module_inference(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "router.ts"
            f.write_text(textwrap.dedent("""\
                export const routes = [
                  { path: '/sys/user', component: () => import('@/a.vue') },
                  { path: '/lg/contract', component: () => import('@/b.vue') },
                  { path: '/login', component: () => import('@/c.vue') }
                ]
            """), encoding="utf-8")
            r = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
            routes = json.loads(r.stdout)
            by_path = {rt["path"]: rt for rt in routes}
            self.assertEqual(by_path["/sys/user"]["module"], "sys")
            self.assertEqual(by_path["/lg/contract"]["module"], "lg")
            self.assertEqual(by_path["/login"]["module"], "login")


if __name__ == "__main__":
    unittest.main()
