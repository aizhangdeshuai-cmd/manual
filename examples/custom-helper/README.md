# Custom Helper 适配指南 — Tier 2 / Tier 3 项目

> 适用对象:项目栈不是 Vue 3 + Spring Boot(Tier 1),需要重写 1-2 个 extract helper
> 工作量:半天到 1 天
> 不适用:Tier 1 项目(直接用默认 helper)

## 0. 哪些 helper 需要改

| Helper | Tier 1 默认行为 | Tier 2 / 3 需要改吗 |
|---|---|---|
| `extract-tasks.py` | 扫 `docs/superpowers/specs/*.md` | **不需要改** — 只读 markdown,跟栈无关 |
| `extract-fields.py --vue` | 扫 Element Plus / naive-ui 表单 | **需要改** — 你的 UI 库不同 |
| `extract-fields.py --java` | 扫 JSR-303 注解 | **Tier 2 改** — 换 DTO 框架(Django / .NET / Go 等) |
| `extract-fields.py --java` | 同上 | **Tier 3 不需要** — 项目无 DTO,关掉 `--java` 模式 |
| `extract-routes.py` | 扫 Vue Router 4 | **需要改** — 你用别的路由方案 |
| `extract-roles.py` | 扫 `@PreAuthorize` + `v-permission` | **需要改** — 你的 RBAC 注解不同 |
| `extract-openapi.py` | 扫 OpenAPI 3.x | **不需要改** — 标准 OpenAPI 通用 |

## 1. 改 `extract-fields.py` 适配新 UI 库

### 1.1 找到原 UI 库的 form-item 标记

Element Plus: `<el-form-item prop="X" label="Y">`
naive-ui: `<n-form-item path="X" label="Y">`
Ant Design Vue: `<a-form-item name="X" label="Y">`
Vuetify: `<v-text-field v-model="X" label="Y">`(无 prop,靠 v-model 推断)
Quasar: `<q-input v-model="X" label="Y">`

### 1.2 改 regex 模式

打开 `extract-fields.py`,找到 `EL_FORM_ITEM_RE` / `NAIVE_FORM_ITEM_RE`,**加新库的模式**:

```python
# 例:Ant Design Vue
A_FORM_ITEM_RE = re.compile(
    r'<a-form-item[^>]*?name="(?P<name>[^"]+)"[^>]*?label="(?P<label>[^"]+)"',
    re.IGNORECASE,
)
```

在 `extract_from_vue()` 里加一个 `for m in A_FORM_ITEM_RE.finditer(text):` 块,逻辑跟 EL 一样。

### 1.3 测试

```bash
# 用你项目的 .vue 文件跑
python3 scripts/extract-fields.py frontend/src/views/some/SomeForm.vue | jq 'length'
# 期望:≥ 5(若 < 5,regex 没匹配上,改)
```

## 2. 改 `extract-fields.py --java` 适配 DTO 框架

### 2.1 不同框架的校验注解

| 框架 | 注解 |
|---|---|
| Spring/Jakarta (默认) | `@NotNull / @NotBlank / @NotEmpty / @Size / @Pattern / @Email` |
| Django | `models.CharField(max_length=N, blank=False)` / `models.EmailField()` |
| .NET | `[Required] / [StringLength(N)] / [RegularExpression] / [EmailAddress]` |
| Go (validator) | `validate:"required,email,max=10"` tag |
| Node (class-validator) | `@IsNotEmpty() / @IsEmail() / @MinLength(2)` |

### 2.2 改 DTO 模式分支

最简单:在 `extract_from_java` 里加一个**新函数** `extract_from_django(root)` / `extract_from_dotnet(root)`,根据文件后缀分发:

```python
def extract_by_extension(path: Path) -> list[dict]:
    if path.suffix == ".vue":
        return extract_from_vue(path)
    elif path.suffix == ".java":
        return extract_from_java(path)
    elif path.suffix == ".py":  # Django models
        return extract_from_django(path)
    elif path.suffix == ".cs":  # .NET
        return extract_from_dotnet(path)
    # ... 其它
```

`extract_from_django` 示例:

```python
def extract_from_django(root: Path) -> list[dict]:
    fields = []
    for f in root.rglob("models.py"):
        text = f.read_text(encoding="utf-8", errors="replace")
        # 简易 regex:Django 字段声明 `name = models.CharField(max_length=50, blank=False)`
        for m in re.finditer(
            r"^\s*(?P<name>\w+)\s*=\s*models\.(?P<type>\w+)\((?P<args>[^)]*)\)",
            text, re.MULTILINE
        ):
            args = m.group("args")
            required = "blank=False" in args or "null=False" in args
            fields.append({
                "name": m.group("name"),
                "django_type": m.group("type"),
                "required": required,
                "source": str(f),
            })
    return fields
```

## 3. 改 `extract-routes.py` 适配路由方案

### 3.1 不同框架的路由声明

Vue Router 4: `path: '/x', name: 'X', component: () => import('@/...')`
React Router 6: `<Route path="/x" element={<X />} />` 或 `createBrowserRouter([{path: '/x', element: <X />}])`
Next.js: 文件名即路由,`pages/x.tsx` 或 `app/x/page.tsx`(无需 regex,扫目录)
Nuxt: 文件名即路由,`pages/x.vue`
Angular: `{ path: 'x', component: XComponent }` in `app-routing.module.ts`

### 3.2 改 router 解析函数

参考 `extract-routes.py` 的实现,加一个 `extract_from_react_router` / `extract_from_nextjs`:

```python
def extract_from_nextjs(root: Path) -> list[dict]:
    """Next.js: pages/ 或 app/ 目录下每个 .tsx/.jsx/.ts/.js 就是一个路由."""
    routes = []
    for sub in ("pages", "app"):
        d = root / sub
        if not d.exists():
            continue
        for f in d.rglob("page.*"):
            rel = f.relative_to(d).with_suffix("")
            path = "/" + str(rel).replace(os.sep, "/")
            if path.endswith("/index"):
                path = path[:-5] or "/"
            routes.append({"path": path, "component": str(f), "module": path.split("/")[1] or "root", "source": str(f)})
    return routes
```

## 4. 改 `extract-roles.py` 适配权限注解

### 4.1 主流框架的 RBAC 注解

| 框架 | 注解 |
|---|---|
| Spring Security (默认) | `@PreAuthorize("hasRole('X')")` / `@Secured("X")` |
| Django (django-guardian / django-rules) | `@permission_required('app.permission_X')` |
| .NET (AuthorizeAttribute) | `[Authorize(Roles = "X")]` / `[Authorize(Policy = "X")]` |
| Casbin (Go / Node) | `c.AddPolicy("alice", "/x", "GET")` in policy.csv |
| 自研前端 | `<RoleGuard>` / `v-permission` / `if (user.hasRole('X'))` |

### 4.2 改 inner regex

参考 `extract-roles.py` 的 `JAVA_ANNOTATIONS` 和 `VUE_PATTERNS`,加新框架模式:

```python
# 例:Django permission_required
DJANGO_PERM_RE = re.compile(
    r"@permission_required\(['\"]([^'\"]+)['\"]\)"
)
```

在 `extract_from_python()` (新函数)里扫 `views.py` / `permissions.py`。

## 5. Tier 3 — LLM-only 模式

如果项目完全没有 RBAC 注解、代码、DTO,**完全靠 LLM 推断**:

```json
{
  "project": {...},
  "llm_only_mode": true,
  ...
}
```

`extract-fields.py` / `extract-routes.py` / `extract-roles.py` 在检测到 `llm_only_mode: true` 时**直接输出空数组**。LLM 在 §5.3 prompt 阶段被告知:"所有结构化数据从 helpers 来,但本项目无 helpers 输出 — 你根据 personas 推断任务卡和字段"。

**质量会下降**,但比"完全不写"强。

## 6. 提交修改

Tier 2 / 3 改完 helper 后:

```bash
# 1. 在项目内的 skill-template/ 改(项目级副本)
# 2. 跑测试
python3 -m unittest docs/user-manual/skill-template/scripts/tests/

# 3. 在你项目内跑 dry-run
python3 docs/user-manual/skill-template/scripts/manual_helper.py extract-fields frontend/src/views > /tmp/fields.json
cat /tmp/fields.json | jq 'length'  # 期望 ≥ 5

# 4. 提交
git add docs/user-manual/skill-template/scripts/
git commit -m "fix(user-manual-skill): adapt extract-fields for Ant Design Vue"
```

**强烈建议**:改动同时 PR 回 `~/.agents/skills/user-manual/`,让其他项目受益。

## 7. 求助

- SKILL.md §0 栈支持矩阵 — 看你的栈是 Tier 1 / 2 / 3
- 项目 `docs/user-manual/INTEGRATION.md` §8 — 跨栈适配入口
