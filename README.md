# User Manual

一个**项目无关**的 Claude / Codex skill,用于为任意项目自动生成并增量维护面向**业务用户**(运营 / 专员 / 主管 / 审批人 / 外部协作方)的操作手册。

> **风格范式**:飞书 / 钉钉用户手册范式 — 细颗粒任务卡、截图驱动 + 口语化图说、"操作前必看"前置块、极简短句、Q&A 单独成节、视频与截图并行。

## 特性

- **项目无关**:同一份 skill 适用于任何项目,只需填写 `manual-config.json` + `personas.json`
- **增量更新**:基于 superpowers artifacts 的 SHA256 引用,重跑只折叠新增/变更的部分
- **多栈支持**:开箱支持 SPA + JPA + RDBMS;非 JPA 栈可改写 helper;无 RBAC 栈走 LLM-only 模式
- **结构化数据抽取**:5 个 helper 抽取任务/字段/路由/角色/OpenAPI 元数据
- **自包含 HTML viewer**:支持 dashboard 模式 + 离线双击打开模式

## 快速开始

1. 在你的项目根目录创建 `docs/user-manual/`
2. 填写 `manual-config.json`(项目元信息)与 `personas.json`(用户角色)
3. 对 Claude / Codex 说:`/user-manual` 或 "生成用户手册"
4. 增量更新:`/user-manual` 或 "更新用户手册"

## 文件结构

```
user-manual/
├── SKILL.md              # 完整执行规范(LLM agent 必读,12 段)
├── INTEGRATION.md        # 30 分钟首次接入指南
├── CONTRIBUTING.md       # 改动流程 + 风格约束
├── LICENSE               # MIT
├── scripts/
│   ├── extract-tasks.py        # 任务候选抽取(扫 superpowers specs)
│   ├── extract-fields.py       # 表单字段(Vue Element Plus / naive-ui + JPA DTO)
│   ├── extract-routes.py       # 前端路由(Vue Router 4)
│   ├── extract-roles.py        # RBAC 角色权限(@PreAuthorize / v-permission)
│   ├── extract-openapi.py      # OpenAPI 3.x 元数据(fallback)
│   ├── manual_helper/         # orchestrator package (v2.0.0 split), 15 个子命令(SKILL.md §7)
│   ├── validate-output.py      # 6 项必跑校验,失败阻断 commit
│   ├── tests/                  # 100 个 stdlib unittest,无外部依赖
├── templates/
│   └── user-manual.html  # 自包含 dashboard(版本号:25)
├── examples/
│   ├── db-backend/       # 完整 FastAPI + Postgres + S3 例子
│   ├── custom-helper/    # Tier 2 适配指南 + drop-in 代码片段
│   ├── personas.template.json
│   └── dryrun-sys-user-manual.md  # 示范输出(LLM 按 §2.8 干跑生成)
└── .github/
    └── workflows/test.yml  # CI:Python 3.10/3.11/3.12 跑 unittest
```

## 跑测试

```bash
cd scripts
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

CI 会在 push / PR 时自动跑同样的命令。

## 详细文档

- **[SKILL.md](./SKILL.md)** — 完整的 skill 规范(给执行方 LLM 阅读)
- **[INTEGRATION.md](./INTEGRATION.md)** — 与 superpowers 框架的集成
- **[CONTRIBUTING.md](./CONTRIBUTING.md)** — 想改 helper / 加 CI / 升模板版本号看这里
- **[examples/db-backend/](./examples/db-backend/)** — db 模式后端参考实现
- **[examples/custom-helper/](./examples/custom-helper/)** — Tier 2/3 适配 recipe

## 触发词

`/user-manual` · "生成用户手册" · "创建用户手册" · "更新用户手册" · "刷新手册"

## License

[MIT](./LICENSE)
