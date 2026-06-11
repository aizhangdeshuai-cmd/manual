# 集成指南 — 把 user-manual skill 接到新项目

> 适用对象:在新项目里第一次用 `user-manual` skill 生成操作手册的开发者
> 预计耗时:30-60 分钟(填 config + personas + 跑 skill + 补截图)
> 不适用:已经跑过本 skill 的项目(直接看 SKILL.md)

## 0. 前置要求

新项目需要满足以下**任一**条件:

- `docs/superpowers/{specs,plans,findings,reviews}/` 至少一个目录有内容(优先级最高)
- **或** `frontend/src/router/index.ts`(或同类路由文件)存在
- **或** `openapi.yaml` / `openapi.json` 存在(无 spec 时的 fallback)
- **或** 后端有权限注解(`@PreAuthorize` 等)或前端有 `v-permission` 等指令

**强烈推荐**:**前三项至少满足 2 项**。只有 1 项时,生成的"字段参考"、"角色权限速查"会缺角。

## 1. 把 skill 装到项目里

### 1.1 安装

```bash
# 方式 A:从用户级 skills 目录 symlink(推荐,改动会随 canonical 自动同步)
ln -s ~/.agents/skills/user-manual docs/user-manual/skill-template

# 方式 B:复制一份到项目内
cp -R ~/.agents/skills/user-manual docs/user-manual/skill-template
```

### 1.2 一键 bootstrap

```bash
# 在项目根目录
python3 docs/user-manual/skill-template/scripts/manual_helper.py init-skill .
```

会创建:
- `docs/user-manual/manual/` — 手册 .md 存放处
- `docs/user-manual/assets/` — 图片 / 视频资源
- `docs/user-manual/screenshots/` — 任务卡截图(按 domain 分目录)
- `docs/user-manual/manual-config.json` — **占位符 config**,需要你编辑
- `docs/user-manual/manual-index.json` — viewer 用的索引
- `docs/user-manual/personas.json` — **你需要从模板复制并填值**

⚠️ **init-skill 会硬性要求 personas.json 存在**;不存在时打印模板路径后报错退出。
这是设计:防止技能在没有 personas 的项目里跑出"无角色"空手册。

## 2. 填 `manual-config.json`

打开 `docs/user-manual/manual-config.json`,逐项替换 `<your-...>` 占位符:

| 字段 | 填什么 | 示例 |
|---|---|---|
| `project.name` | 项目短名(用于 commit message / 路径) | `<your-project-slug>` |
| `project.display_name` | 项目全名(用于手册标题 / 文档说明) | `<Your Project Display Name>` |
| `project.stack` | 技术栈(可任意命名) | `vue3 / spring-boot / postgresql` |
| `project.repo_layout` | 前/后端根目录(相对项目根) | `frontend / backend / docs` |
| `project.build_commands.frontend_dev` | 启前端命令 | `cd frontend && npm run dev` |
| `project.build_commands.backend_dev_module` | 启后端命令,`{module}` 是占位 | `cd backend && mvn spring-boot:run -pl {module}` |
| `project.build_commands.backend_default_module` | 默认后端模块 | `<your-default-module>` |
| `project.build_commands.backend_default_port` | 后端端口(字符串) | `<your-backend-port>` |
| `project.build_commands.gateway_port` | 网关端口(字符串) | `<your-gateway-port>` |
| `project.deploy.default_url` | 默认访问 URL | `<http://your-default-url>` |
| `project.deploy.auth` | 认证方式 | `jwt` / `oauth2` / `sso` / `none` |
| `business_objectives` | 业务目标类别(动词),可按项目覆盖 | `["创建", "查询", "修改", "删除", "审批", "导出"]` |
| `inputs[].kind` | 输入源类型,可选 `superpowers` / `frontend_pages` / `backend_dtos` / `router` / `openapi` | 见 §3 |
| `screenshots_dir` | 截图目录(相对项目根) | `docs/user-manual/screenshots` |
| `storage` | `file`(默认)或 `db` | `file` |

**最小可用模板** (5 角色,Vue 3 + Spring Boot,无 OpenAPI):

```json
{
  "project": {
    "name": "<your-name>",
    "display_name": "<Your Project>",
    "stack": {"frontend": "vue3", "backend": "spring-boot", "db": "postgresql"},
    "repo_layout": {"frontend_root": "frontend", "backend_root": "backend", "docs_root": "docs"},
    "build_commands": {
      "frontend_dev": "cd frontend && npm run dev",
      "backend_dev_module": "cd backend && mvn spring-boot:run -pl {module}",
      "backend_default_module": "<your-module>",
      "backend_default_port": "<your-port>",
      "gateway_port": "<your-gateway-port>"
    },
    "deploy": {"default_url": "<your-url>", "auth": "jwt"}
  },
  "business_objectives": ["创建", "查询", "修改", "删除", "审批", "导出"],
  "personas_path": "docs/user-manual/personas.json",
  "inputs": [
    {"kind": "superpowers", "path": "docs/superpowers"},
    {"kind": "frontend_pages", "path": "frontend/src/views", "include_globs": ["**/*.vue"]},
    {"kind": "router", "path": "frontend/src/router/index.ts"}
  ],
  "screenshots_dir": "docs/user-manual/screenshots",
  "storage": "file",
  "viewer": {
    "template": "docs/user-manual/skill-template/templates/user-manual.html",
    "out": "docs/user-manual/user-manual.html",
    "standalone_out": "docs/user-manual/user-manual-standalone.html"
  }
}
```

## 3. 写 `personas.json`

从 skill 模板复制领域中性模板:

```bash
cp docs/user-manual/skill-template/examples/personas.template.json \
   docs/user-manual/personas.json
```

按项目实际角色编辑。**强约束**(validate-config 会校验):

- 至少 3 个 personas
- 每个 persona 有 `id` / `name` / `daily_tasks`(≥1 个)
- 所有 persona 的 `covers_objectives` 跨 ≥ 2 个不同的业务目标类别

**5 角色起步模板**(已写在 personas.template.json,直接覆盖 5/6 业务目标):
- `operator` — 一线运营
- `specialist` — 业务专员
- `manager` — 业务主管
- `auditor` — 审计 / 合规
- `external_collaborator` — 外部协作者

如果项目方只想要 3 个角色,删 `auditor` + `external_collaborator` 即可,但 `covers_objectives` 要重新分摊到剩下 3 个。

## 3.5 viewer 卡片元数据预期(给集成方 + viewer v2.1 升级路径)

**当前 viewer v2(`docs/user-manual/skill-template/assets/viewer/*`)** 只从每篇 .md 的 frontmatter 解析两个字段:

| 字段 | 用途 | 解析器位置 |
|---|---|---|
| `module` | 顶部"业务域"标签 | `assets/viewer/js/parser.js` `extractFrontmatter()` |
| `description` | 搜索结果摘要 | 同上 |

**新增字段 `audience` / `task` / `prerequisites` / `related` / `version` 当前被 viewer 解析器忽略** — 文件内保留,但 UI 不展示。

**为什么保留**:
- 这些字段是给 Q&A AI(v2.1 规划)用的机器可读元数据
- 与"卡片元数据应显示 audience/task 标签"相关的需求,需在 v2.1 bump version 24 → 25 时一并改:
  1. `extractFrontmatter()` 返回完整 frontmatter 对象(不止 module/description)
  2. `renderCard()` 在 metadata 区加 audience/task 标签 chip
  3. `validate-output.py` 第 7 项检查加 frontmatter 字段必填校验

**对当前集成方的影响**:你看到生成的 .md 有 `audience: 系统管理员` 但 viewer 不显示,这是设计 — 不要在 .md 里删掉,前端 v2.1 会用上。

## 4. 校验

```bash
python3 docs/user-manual/skill-template/scripts/manual_helper.py validate-config
```

**期望**:`OK: manual-config.json + personas.json valid.`

**不通过时**:
- `manual-config.json ... missing required key: X` → 补字段
- `personas.json must have >= 3 personas` → 加 persona
- `personas 覆盖的业务目标类别不足(<2)` → 调整 `covers_objectives`
- `project.name still a placeholder` → 替换 `<your-...>`

## 5. 跑 skill 写第一本手册

skill 本身是给 LLM 用的提示词 — 你需要让 LLM 读 SKILL.md,按 §5 流程跑:

```bash
# 让 LLM 执行 SKILL.md §5.1 跑这 4 个 helper,生成 /tmp/*.json
python3 docs/user-manual/skill-template/scripts/manual_helper.py extract-tasks docs/superpowers/specs/*.md > /tmp/tasks.json
python3 docs/user-manual/skill-template/scripts/manual_helper.py extract-fields frontend/src/views > /tmp/fields.json
python3 docs/user-manual/skill-template/scripts/manual_helper.py extract-routes frontend/src/router/index.ts > /tmp/routes.json
python3 docs/user-manual/skill-template/scripts/manual_helper.py extract-roles backend frontend/src > /tmp/roles.json
# 然后让 LLM 按 §5.3 模板合成 markdown
```

**输出位置**:`docs/user-manual/manual/<module>-user-manual.md`(每 persona 一本,或按业务域分册)

**每个分册跑完后**,跑 §5.4 的 output validation:

```bash
F="docs/user-manual/manual/$1-user-manual.md"
# 6 项检查(7 字段命中、操作前必看、视觉锚点、6 列表、角色权限速查、截图)
# 详见 SKILL.md §5.4
```

## 6. 补截图(可选,D3)

skill 不会自动生成截图。它会在任务卡里放 `[SCREENSHOT NEEDED: path]` 占位符,你需要:

1. 跑项目 → 启动前端
2. 手动跑每个任务卡流程,用截图工具(snipaste / cleanShot 等)截 UI
3. 存到 `<screenshots_dir>/<module>/<task>/<step>.png`
4. 任务卡里把 `[SCREENSHOT NEEDED: ...]` 替换成 `![红框:XXX](<path>.png)`

**视频同理**:`[VIDEO: <path>.mp4]` 占位,录屏后放同目录。

## 7. 提交 + push

```bash
git add docs/user-manual/
git commit -m "docs(user-manual): bootstrap user manuals for v2"
git push
```

**commit message 规范**:见项目 `CLAUDE.md` 的 `<type>(<scope>): <desc>`。本 skill 用 `docs(user-manual)` scope。**完整示例**:

| 场景 | commit message |
|---|---|
| **新增手册** | `docs(user-manual): bootstrap user manuals for v2 (1 overview + 3 domain manuals)` |
| **改写 skill** | `docs(user-manual-skill): refactor to project-agnostic core (D1) → add 4 extract helpers (D2) → add openapi helper + INTEGRATION (D3)` |
| **修 bug** | `fix(user-manual-viewer): lightbox image-zoom now closes on backdrop click (v2.1.3)` |
| **杂项** | `chore(user-manual): rebuild standalone.html after v2.1.2 template bump` |

**何时用哪个 scope**:
- `docs(user-manual)` — 项目内 `docs/user-manual/` 下的产物(手册 md / 截图 / config)
- `docs(user-manual-skill)` — `docs/user-manual/skill-template/` 下的 skill 本身改动(SKILL.md / helpers / templates)
- `fix(user-manual-viewer)` — `user-manual-standalone.html` / `assets/viewer/*` 的 bug
- `chore(user-manual)` — 构建脚本触发(template bump / 截图重新生成)


## 8. 跨栈适配 (Tier 2 / Tier 3)

如果你的项目不是 Vue 3 + Spring Boot(Tier 1),见:
- `docs/user-manual/skill-template/examples/custom-helper/README.md` — Tier 2 改写 helper 指南
- SKILL.md §0 栈支持矩阵

## 9. dry-run checklist

跑一遍这 10 项,确保集成完整:

- [ ] `docs/user-manual/skill-template/` 存在(方式 A 或 B)
- [ ] `docs/user-manual/manual-config.json` 占位符全部替换
- [ ] `docs/user-manual/personas.json` 从模板复制并按项目编辑
- [ ] `validate-config` 输出 `OK`
- [ ] 4 个 extract helper 跑通(都有 ≥1 个输出)
- [ ] 第一本分册 `.md` 写完
- [ ] §5.4 output validation 6 项检查全部通过
- [ ] 截图 / 视频占位填了至少 1 个分册的 ≥ 50%
- [ ] 浏览器打开 `user-manual-standalone.html` 能看到手册
- [ ] `git add docs/user-manual/ && git commit` 一笔提交

**全勾 = 集成完成**。有 ❌ 时回到对应步骤排查。

## 10. 后续维护

- **新增模块** → 跑 skill,产出新分册(增量更新,只动新 spec 关联章节)
- **修改业务规则** → 改 spec / plan → 跑 skill → §5.4 校验 → commit
- **截图过期** → 重新跑流程,覆盖 PNG → viewer 立即生效(路径不变时)
- **模板升级** → `skill-template/` 自带 `<!-- user-manual-dashboard-version: N -->` 注释;N 变了 viewer 才会 regen
- **配置变更** → 改 `manual-config.json` → 跑 skill 重写相关章节(Citations 表的 hash 不变)
