---
name: user-manual
description: Generate and incrementally maintain a per-project user manual at `<project>/docs/user-manual/manual/*.md` plus a self-contained HTML viewer, by analyzing the project's superpowers artifacts (`docs/superpowers/{specs,plans,findings,reviews}/`) and fortifying with web search. Trigger on `/user-manual`, "generate user manual", "create user manual", "update the user manual", "refresh the manual", "build a manual from the specs and plans", or any phrase asking for end-user / operator documentation drawn from project specs and plans. Idempotent across runs via a Citations section that records the SHA256 of every cited artifact — only new or changed artifacts are folded in on subsequent runs. Targets business users as the primary audience (operations / specialist / manager / approver / external collaborators), and writes in the **Feishu / DingTalk-style** user-guide tradition: granular task cards (one task card = one specific operation, not a user journey), screenshot-driven with colloquial captions, "操作前必看" preamble per task card, ultra-short imperative sentences, embedded Q&A section, video support alongside screenshots. Frontmatter reserves `audience / task / prerequisites / related` fields for future Q&A AI integration. Project-agnostic core + project-layer config — same skill works on any project that fills in `manual-config.json` + `personas.json`. When the optional `recorder/` opt-in plugin is installed, screenshots and videos are produced automatically by the recorder's LLM agent invoking Playwright; the plugin's design lives in `recorder/SKILL.md` and install steps in `recorder/INSTALL.md`. Do not invoke for purely internal / developer-facing READMEs that aren't drawn from superpowers artifacts.
---

# User Manual

A **project-agnostic** skill for generating, maintaining, and serving a high-quality **business user operation manual** for any project. The output is structured for real users (operations / specialist / manager / approver / external collaborator) — not developers, not architects, not sysadmins.

> **范式对标 / Style benchmark**:本手册遵循 **飞书文档 / 钉钉文档** 的操作手册范式 — 任务卡颗粒度细(每张卡 = 一个具体操作,不是用户旅程)、截图驱动 + 口语化图说、"操作前必看"前置块、极简语法(短句、动词开头、避免从句)、Q&A 单独成节、视频与截图并行。详细风格见 [§2 风格基准](#2-风格基准飞书钉钉范式)。

The skill is invoked when the user wants either:

- The first version of a manual (no `manual/*.md` exists yet), **or**
- An incremental update to an existing manual after new specs / plans / findings / reviews have landed.

Both cases use the same routine; the existing-manual case skips artifacts whose hashes haven't changed since the last run, so it stays cheap to re-run frequently.

## 0. 跨项目复用边界(栈支持矩阵)

| Tier | 适用形态 | helper 支持 | 适配成本 |
|---|---|---|---|
| **Tier 1(开箱即用)** | SPA 前端(框架自选,如 `vue3`)+ JPA 后端 + 关系型 DB | 4 个 extract helper 全栈适用,任务卡 / 字段表 / 路由 / 角色 全部自动抽 | 0 |
| **Tier 2(改写 helper)** | SPA 前端 + 非 JPA 后端(Django / Node / Go / .NET 等) | 需重写 1-2 个 helper(`extract-fields` / `extract-roles` 与框架相关),其他 3 个 helper 通用,SKILL.md / `manual_helper.py` 不用动 | 半天 |
| **Tier 3(LLM-only 模式)** | 静态站 / Serverless / 桌面应用 / 任何无 RBAC 注解的栈 | 关闭自动抽取,`manual-config.json` 设 `"llm_only_mode": true`,所有"字段 / 路由 / 角色"由 LLM 推断 | 0(但 LLM 推断质量下降) |

**栈标识在 `manual-config.json` 的 `project.stack` 字段声明**(默认 `vue3 / spring-boot / postgresql`,项目可改)。

## 0.5 如何执行(给执行方 agent)

**你是 Claude Code / Codex / 其他 LLM agent**。本 skill 通过以下流程被触发和执行:

1. **用户触发**:`/user-manual` 命令,或对话中出现 "更新用户手册" / "生成分册" / "改改 help center" 等关键词
2. **执行方(你)做的事**:
   - 用 Read 工具读 `SKILL.md` 全部内容(本文件即 orchestrator)
   - 按 §5 调用流程跑 12 步:先初始化项目(`manual-config.json` / `personas.json`),再跑 5 个 extract helper 抽结构化数据,再用 LLM 自己合成 markdown
   - 用 Bash 工具跑 helper(extract-tasks / extract-fields / extract-routes / extract-roles / extract-openapi)
   - 用 Edit / Write 工具更新 `.md` 文件
   - 跑 `validate-output.py` 验证产物
3. **不调外部 LLM API** — 你(执行方)自己就是 LLM,直接合成 markdown。prompt 模板在 `SKILL.md` §5.2-5.3 里有完整 copy-paste
4. **降级路径**:helper 全部失败 / 项目无 superpowers 规范 → 切到 LLM-only 模式(`manual-config.json` 设 `llm_only_mode: true`),所有字段由 LLM 推断

**本 skill 的设计原则**:5 个 helper 是 LLM 的"快速数据",不是"权威源"。LLM 拿到结构化数据后,合成的人类可读手册才是最终产物。

## 0.6 示例项目(给 LLM agent 找参考)

`examples/` 目录下有 4 个可直接拿来对照的实现,合成手册前应**先扫一眼**再下笔:

| 文件 / 目录 | 用途 |
|---|---|
| [`examples/db-backend/`](./examples/db-backend/) | 完整可跑的 FastAPI + Postgres + S3/MinIO 后端,演示 db 模式(`init-db` / `upsert-manual` / `upload-asset`)的实际调用 |
| [`examples/custom-helper/`](./examples/custom-helper/) | Tier 2/3 适配指南 + 可直接复制的 drop-in helper(Ant Design Vue / Django / Next.js / 等),含可跑 demo |
| [`examples/dryrun-sys-user-manual.md`](./examples/dryrun-sys-user-manual.md) | **示范输出**:LLM 按 §2.8 风格干跑生成的一份完整 SYS 模块手册(参考最终长什么样) |
| [`examples/personas.template.json`](./examples/personas.template.json) | personas.json 的最小模板,复制到目标项目填实际角色即可 |

## 1. 文件位置与产物形态

- `<git-root>/docs/user-manual/manual-config.json` — 项目级配置(项目元信息 / build_commands / 业务目标 / inputs)
- `<git-root>/docs/user-manual/personas.json` — 用户角色(强校验,缺失 init-skill 报错退出)
- `<git-root>/docs/user-manual/manual/user-manual.md` — 总览分册(≤ 200 行)
- `<git-root>/docs/user-manual/manual/{domain}-user-manual.md` — 业务域分册(每域一册)
- `<git-root>/docs/user-manual/screenshots/{domain}/` — 截图目录(按域分目录,任务卡截图占位对齐)
- `<git-root>/docs/user-manual/user-manual.html` — dashboard / viewer(从模板 regen,模板版本变化时)
- `<git-root>/docs/user-manual/user-manual-standalone.html` — 双击打开版(`build-standalone` 产物)

`git-root` 优先 `git rev-parse --show-toplevel`,失败回退 `pwd`。

## 2. 风格基准(飞书/钉钉范式)

> 本节定义手册的**写作风格硬约束**。任何 LLM 产出的手册必须满足本节,否则视为"风格未统一",重写。

### 2.1 任务卡颗粒度

**一张任务卡 = 一个具体操作**,不是"用户旅程"。

❌ 反例(旅程式):
> ### 完成一次新员工入职
> 包括开通账号、设置权限、领用设备、签合同……

✅ 正例(操作式):
> ### 创建新员工账号
> ### 给员工授予"财务专员"角色
> ### 给员工分配办公设备

每张卡独立,用户可以单独执行其中一步。

### 2.2 截图驱动 + 口语化图说

**每张截图必配 1 句图说**,放 markdown alt 文本(`![...](path)`),格式:`<红框/箭头 + ≤ 15 字口语化描述>`。

❌ 反例(描述式):
> `![合同详情页面截图,显示了合同的所有字段信息](contract-detail.png)`

✅ 正例(口语化):
> `![红框:点右上角"发起审批"](contract-detail-start-approval.png)`

口语化用词参考:
- "点一下 X"(按钮 / 链接 / 菜单)
- "看到 X 出现在 Y 里"(结果反馈)
- "X 变红 / 变灰 / 出现红叉"(异常反馈)
- "弹出一个窗口 / 抽屉 / 全屏"(UI 形态)

### 2.3 "操作前必看"前置块

**每张任务卡开头**必须有一段 `> ⚠️ 操作前必看` 块,放操作前用户需要知道的事:

```markdown
### 创建新员工账号

> ⚠️ **操作前必看**
> - 你需要是"系统管理员"角色
> - 员工姓名、工号、手机号 3 个字段必填
> - 创建后默认密码 = 工号后 6 位,首次登录强制改密

**适用角色**:`sys_admin`
**前置条件**:员工已在 EHR 系统入职(`EHREmployee.status = "active"`)
**入口**:`系统管理 → 用户管理 → 新增用户`

#### 步骤
...
```

"操作前必看"块放 4 类内容之一或多个:
- 权限要求(谁可以操作)
- 必备前提(数据准备 / 审批已通过 / 流程走到某节点)
- 重要后果(操作不可逆 / 触发副作用 / 需通知某人)
- 时间窗口(每月 1-5 日才能操作 / 节假日不处理)

### 2.4 极简语法

- **每步 ≤ 30 字**(飞书/钉钉实测舒适区间)
- **动词开头**:"打开"、"点击"、"选择"、"输入"、"确认"、"取消"
- **避免从句**:"在 X 里" → "打开 X"
- **避免被动语态**:"文件被上传" → "上传文件"
- **避免技术术语**:"调用 POST /api/users" → "提交新增请求"

### 2.5 Q&A 模式(常见问题单独成节)

每个分册必须有一节 `## 常见问题`,**单独成 H2**,不放附录。

结构:
```markdown
## 常见问题

### 权限类

**Q: 我是 X 角色,看不到 Y 按钮?**
A: ... (症状 → 原因 → 解法 3 步)

**Q: 我有 X 权限,但操作时提示 403?**
A: ...

### 数据类

**Q: 列表加载不出来,一直转圈?**
A: ...

### 操作类

**Q: 提交后能不能撤回?**
A: ...
```

按"权限 / 数据 / 操作 / 计费"4 类组织(类别由 LLM 从 personas + extract-roles.py 输出派生)。

### 2.6 视频与截图并行

任务卡中**关键步骤**配视频,其他步骤配截图。

格式:
```markdown
[VIDEO: <task>-<step>.mp4]  视频时长约 1 分钟,演示完整流程
[SCREENSHOT: <task>-<step>.png]  静态截图,标注关键位置
```

缺视频时显式标 `[VIDEO NEEDED]`,缺截图时显式标 `[SCREENSHOT NEEDED]`,汇总到分册末尾"待补视频/截图清单"小节。

**视频支持是 frontmatter 预留,viewer v2 渲染。v1 viewer 不解析 VIDEO 标签,直接显示为文本占位**。

### 2.7 视觉锚点词汇表(任务卡内固定使用)

| 锚点 | 用途 | 示例 |
|---|---|---|
| `> ⚠️ 注意:` | 重要警示,操作前必读 | `> ⚠️ 注意:删除后无法恢复` |
| `> 💡 提示:` | 经验性技巧,新手可跳但老手会爱 | `> 💡 提示:按 Ctrl+S 快速保存` |
| `> ❌ 禁止:` | 反模式,做了会出错 | `> ❌ 禁止:不要在生产环境用 admin 账号调试` |
| `> 📌 备注:` | 上下文补充,不影响主流程 | `> 📌 备注:此功能 v2.1 上线,当前灰度中` |

**仅这 4 种锚点**,不在此 4 类的内容用普通段落,不用其他 emoji。

### 2.8 飞书/钉钉风格 — 完整正反例(LLM 必看)

> 本节是 §2.1-§2.7 的**完整示范**。LLM 写任务卡时遇到不确定,先回这里对一遍。

#### 2.8.1 任务卡标题对比

❌ 反例(旅程式、抽象):
- "完成一次新员工入职"  
- "管理用户和权限"
- "设置系统"

✅ 正例(操作式、动词开头、≤ 15 字):
- "创建新员工账号"
- "给员工授予财务专员角色"
- "停用某员工的临时权限"
- "修改员工手机号"
- "批量导出员工花名册"

#### 2.8.2 步骤对比

❌ 反例(从句、技术词、超长):
1. 在系统管理菜单下找到用户管理子菜单,然后点击新增用户按钮,在弹出的对话框中
2. 调用 POST /api/sys/users 接口,需要 X-Org-Id 请求头
3. 验证 orgId 是不是和 token 的一致,然后将用户信息持久化到数据库中

✅ 正例(动词开头、短句、口语化):
1. 打开系统管理 → 用户管理
2. 点「新增用户」[SCREENSHOT: user-add-btn.png]
3. 填姓名、工号、手机号
4. 点「保存」[SCREENSHOT: user-save-btn.png]
5. 看到列表里出现新员工

#### 2.8.3 截图图说对比

❌ 反例(描述性、超长):
- `![合同详情页面截图,显示了合同的所有字段信息,包括合同编号、名称、签约方、金额、状态、到期日等](contract-detail.png)`
- `![系统截图](img1.png)`

✅ 正例(红框 / 箭头 + ≤ 15 字口语化):
- `![红框:点右上角"发起审批"](contract-detail-start-approval.png)`
- `![箭头:这里填工号](user-form-employee-id.png)`
- `![看到:列表顶部出现"已保存"提示](user-saved-toast.png)`

#### 2.8.4 "操作前必看"块对比

❌ 反例(缺失 / 空洞):
- 没有"操作前必看"块
- "操作前必看:注意" (没内容)

✅ 正例(覆盖 4 类信息):
- `> ⚠️ **操作前必看**`
  `- 你需要是"系统管理员"角色` (权限要求)
  `- 员工姓名、工号、手机号 3 个字段必填` (必备前提)
  `- 创建后默认密码 = 工号后 6 位,首次登录强制改密` (重要后果)
  `- 每个工作日的 9:00-18:00 处理,其它时间提交会延迟到次日` (时间窗口)

#### 2.8.5 字段说明对比

❌ 反例(机械翻译 Java 字段名 / 注解):
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| userName | String | true | userName @NotBlank |
| fileKey | String | false | 字段 fileKey 类型 String |

✅ 正例(用户视角):
| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| 用户名 | 输入框 | 是 | 字母开头,可含数字,4-20 字 |
| 头像 | 文件上传 | 否 | 仅支持 jpg/png,≤ 2MB |
| 角色 | 下拉选择 | 是 | 默认"普通用户",可多选 |
| 备注 | 多行文本 | 否 | ≤ 200 字 |

#### 2.8.6 "如果你卡住了"对比

❌ 反例(空泛):
- 如果遇到问题请联系管理员

✅ 正例(分支处理):
- **Q: 点「保存」没反应?**
  A: 检查网络 — 屏幕右下角如果显示"网络断开"是网络问题;否则看表单红字提示,定位到具体字段。
- **Q: 提示"工号已存在"?**
  A: 换一个工号,或在「用户管理」里搜该工号,确认是否已建过账号。
- **Q: 保存后列表没出现?**
  A: 等 3 秒,刷新页面(F5);如果还看不到,看「操作日志」确认提交是否成功。
- **Q: 提示"权限不足"?**
  A: 找你的角色管理员申请「用户管理」权限。

#### 2.8.7 Q&A(常见问题)对比

❌ 反例(放在附录,2-3 条,含糊):
> 详见附录 FAQ。
> 1. 系统卡顿怎么办?
>    请联系 IT。

✅ 正例(主章节 § 单独成节,按 4 类组织,每条结构化):
```markdown
## 常见问题

### 权限类
**Q: 我是业务主管,看不到「批量导入」按钮?**
A: 业务主管默认没有「批量导入」权限。找系统管理员申请,或先用「新增单个」功能。

**Q: 我有审批权限,但提交时提示"无审批流"?**
A: 说明这个业务类型还没配置审批流。找系统管理员在「审批流配置」里加一条。

### 数据类
**Q: 列表加载不出来,一直转圈?**
A: 看浏览器右上角网络图标 — 红色断线 = 网络问题,黄色 = 慢。再看后端日志:tail -f /var/log/grc/app.log | grep ERROR。

**Q: 搜索"张三"搜不到?**
A: 检查是否包含特殊字符,试试只搜姓"张";确认张三已激活(不是停用状态)。

### 操作类
**Q: 提交后能不能撤回?**
A: 提交后 30 秒内可在「我的待办」撤回;超过 30 秒需联系审批人驳回。

**Q: 批量导入失败,部分成功部分失败?**
A: 失败的行会在导入结果里标红,鼠标悬停看错误原因。常见原因:工号重复 / 手机号格式错 / 邮箱为空。
```

#### 2.8.8 视频 / 截图并行

任务卡中**关键步骤**(一般是"开始"那步 + "最后确认"那步)配视频,中间步骤配截图。

```markdown
#### 步骤

1. 打开合同管理,点「新增合同」[VIDEO: contract-create-step1.mp4 — 演示完整新增流程,约 1 分钟]
2. 填合同基本信息(合同名、签约方、金额)[SCREENSHOT: contract-form-basic.png]
3. 选择合同类型,选择审批流[SCREENSHOT: contract-form-type.png]
4. 提交审批[SCREENSHOT: contract-submit.png]
```

缺视频时:**先不放,标 NEEDED**;后续人工录屏补。


## 3. 章节结构(11 段 + 附录)

每本分册严格按以下顺序组织:

| # | 章节 | 内容 | 自动 / LLM |
|---|---|---|---|
| 1 | 封面信息(frontmatter) | title / module / module_code / version / version_date / audience / task / prerequisites / related | LLM |
| 2 | 文档说明 | 本分册面向谁、范围、不包含什么、与其他分册的关系 | LLM |
| 3 | **读法指南** | 本分册怎么读、各章节定位、视觉锚点说明、Q&A 怎么用 | LLM |
| 4 | 目录 | viewer 自动生成,文档内标注即可 | 自动 |
| 5 | 修订历史 | 独立小节,frontmatter `revision_history` 字段同步 | LLM |
| 6 | 术语表 | 项目专属术语 + 业务领域缩写,首次出现展开 | LLM |
| 7 | 系统概述 | 运行环境、浏览器、登录入口、关键模块地图 | LLM |
| 8 | 快速开始 | 假定环境就绪,1 句话 + 1 张任务卡链 | LLM |
| 9 | **任务卡** | 按 personas 派生,**每张卡 7 字段硬模板 + "操作前必看"块** | LLM |
| 10 | 字段参考 | 用 `extract-fields.py` 聚合,按模块分组 | 自动 |
| 11 | 配置参考 + 故障速查(场景化) + 联系支持 | 配置项;故障速查按 4 类(权限/网络/数据/操作);联系支持 | LLM |
| 附录 A | 错误码速查(6 列硬结构) | HTTP 状态 / 业务错误码 / 症状 / 原因 / 解法 / 找谁 | LLM |
| 附录 B | 联系方式 / 技术支持 | 团队 / 邮箱 / 工单系统 | LLM |

**删除**(v1 旧结构):
- ❌ `## Architecture and Internals` — 移入分册附录,只留 1 个数据流图
- ❌ `## Daily Usage`(被"任务卡"替代)
- ❌ `## Concepts and Glossary`(被"术语表"替代,位置调整到第 6 段)

## 4. 任务卡硬模板(7 字段 + "操作前必看")

```markdown
### <动词开头任务名,如"创建新员工账号">

> ⚠️ **操作前必看**
> - <权限要求 / 必备前提 / 重要后果 / 时间窗口>

**适用角色**:`<persona_id>`(从 personas.json 取)
**前置条件**:<bullet 列表,从 prerequisites 派生>
**入口**:`<path>`,对应后端 `<api_path>`

#### 步骤

1. <动词开头,≤ 30 字>[SCREENSHOT: <name>.png]
2. <动词开头,≤ 30 字>[SCREENSHOT: <name>.png]
3. <动词开头,≤ 30 字>

#### 成功后看到

- <可见的反馈点,UI 元素或状态变化>

#### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| ... | ... | ... | <用户视角说明,不是机械翻译> |

#### 如果你卡住了

- <分支处理:权限 403 / 表单红字 / 网络超时 等>

#### 相关任务

- [另一张任务卡](#...)
```

**必含字段**:7 个(`适用角色 / 前置条件 / 入口 / 步骤 / 成功后看到 / 字段说明 / 如果你卡住了`)+ `相关任务`(可选,推荐) = 实际 8 字段。

**粗检 grep 关键词**:`适用角色 | 前置条件 | 入口 | 步骤 | 成功后看到 | 字段说明 | 如果你卡住了 | 相关任务` — 每张任务卡匹配数 ≥ 6。

## 5. LLM 写手册的 prompt 流程(执行方严格按此走)

### 5.1 数据采集(确定性的,LLM 不参与)

按以下顺序跑 helper,每个跑完输出 JSON 到 stdout,执行方**保留** JSON 给步骤 5.3 用:

```bash
# 5.1.1 抽任务候选(spec 里写"用户故事"才有用;没写就拿空数组)
python3 scripts/extract-tasks.py docs/superpowers/specs/*.md > /tmp/tasks.json

# 5.1.2 抽表单字段(覆盖所有 .vue 页面 + 后端 DTO)
python3 scripts/extract-fields.py <frontend_root>/src/views > /tmp/fields.json
python3 scripts/extract-fields.py --java <backend_root>/**/dto > /tmp/fields-java.json

# 5.1.3 抽路由(知道有哪些页面)
python3 scripts/extract-routes.py <frontend_root>/src/router/index.ts > /tmp/routes.json

# 5.1.4 抽角色权限(知道 RBAC 怎么配的)
python3 scripts/extract-roles.py <backend_root> <frontend_root>/src > /tmp/roles.json

# 5.1.5 (可选) 抽 OpenAPI —— 项目无 superpowers 时的 fallback
python3 scripts/extract-openapi.py openapi.yaml > /tmp/openapi.json
```

**严禁 LLM 自由发挥这些数字**。所有结构化数据从 helper 来,LLM 只做"叙述化"。

### 5.2 personas 路由

对每个 `persona` in `personas.json`:
1. 读 `daily_tasks` — 每个 task 名映射到一个**候选任务卡**(从 /tmp/tasks.json 选最匹配的,或从 routes.json 反推)
2. 读 `covers_objectives` — 该 persona 能做哪些 business_objective(创建 / 查询 / 审批 / 导出 / ...)
3. 产出该 persona 的 `## 任务卡` 子集

**任务卡总数估算**:`sum(persona.daily_tasks.length for persona in personas)`,每个 daily_task 展开 1-3 张卡 = 分册 5-15 张卡。

### 5.3 LLM 合成调用模板(直接套用)

执行方按以下 prompt 模板调用 LLM,**不要改写 prompt 主体**:

```
你是 {{ project.display_name }} 操作手册的撰写助手。
你的读者是 {{ persona.name }}({{ persona.description }}),不是开发者。

# 输入(已为你准备好,不要重新推导)
- 项目元信息:从 manual-config.json 读
- 角色列表:personas.json,共 {{ personas.length }} 个
- 任务候选:/tmp/tasks.json(已聚合 {{ tasks.length }} 个)
- 路由清单:/tmp/routes.json({{ routes.length }} 个)
- 字段参考:/tmp/fields.json + /tmp/fields-java.json({{ fields.length }} 个)
- 角色 / 权限:/tmp/roles.json({{ roles.length }} 个,可能为空)
- OpenAPI(如有):/tmp/openapi.json

# 你的任务:为 {{ persona.name }} 撰写 1 份分册

## 硬约束(违反任何一条 = 失败)
1. 章节结构严格按 SKILL.md §3(11 段 + 附录)
2. 任务卡严格按 §4 模板,7 字段 + "操作前必看"块,缺一不可
3. 飞书/钉钉范式:每张任务卡 = 一个具体操作(非旅程);步骤动词开头 ≤ 30 字;截图图说口语化
4. 视觉锚点用 4 种:`> ⚠️ 注意:` / `> 💡 提示:` / `> ❌ 禁止:` / `> 📌 备注:`,每分册 ≥ 3 处
5. 故障速查按 4 类(权限 / 网络 / 数据 / 操作),附录 A 错误码 6 列硬结构
6. 字段说明用用户视角语言,不要照搬 Java 字段名或 DTO 注解
7. 引用数据时加 `<!-- source: extract-X.py, file: Y -->` 注释(便于追溯)

## 禁止
- 不要用开发者术语(mvn / POST / 8089 / etc.),读 manual-config.json 取部署信息
- 不要写"在 pom.xml 里改 X"——读者是业务用户
- 不要折叠 WIP / cancelled 制品
- 不要整篇重写——只动你负责的 persona 子集

## 输出格式
- 1 个 markdown 文件
- 文件名:`<module>-user-manual.md`
- 文件开头 frontmatter:title / module / module_code / version / version_date / audience / task / prerequisites / related
```

### 5.4 Output validation(必跑,通过才能 commit)

```bash
F="docs/user-manual/manual/$1-user-manual.md"

# 验证 1:7 字段关键词命中数
HITS=$(grep -c "适用角色\|前置条件\|入口\|步骤\|成功后看到\|字段说明\|如果你卡住了\|相关任务" "$F")
[ "$HITS" -ge 6 ] || { echo "FAIL: 任务卡字段缺失 (hits=$HITS)"; exit 1; }

# 验证 2:每张卡都有"操作前必看"
BLOCKS=$(grep -c "操作前必看" "$F")
[ "$BLOCKS" -ge 3 ] || { echo "FAIL: 操作前必看块 < 3"; exit 1; }

# 验证 3:视觉锚点使用率
ANCHORS=$(grep -c "⚠️ 注意\|💡 提示\|❌ 禁止\|📌 备注" "$F")
[ "$ANCHORS" -ge 3 ] || { echo "FAIL: 视觉锚点 < 3"; exit 1; }

# 验证 4:附录 A 6 列硬结构
TABLES=$(grep -c "^| .* | .* | .* | .* | .* | .* |" "$F")
[ "$TABLES" -ge 1 ] || { echo "FAIL: 附录 A 6 列表格缺失"; exit 1; }

# 验证 5:每个分册开头有"## 角色与权限速查"
PERMS=$(grep -c "## 角色与权限速查" "$F")
[ "$PERMS" -ge 1 ] || { echo "FAIL: 角色与权限速查缺失"; exit 1; }

# 验证 6:截图图说(每分册 ≥ 2 张带 alt 的图片)
SHOTS=$(grep -c '!\[' "$F")
[ "$SHOTS" -ge 2 ] || { echo "WARN: 截图 < 2"; }

echo "OK: $F"
```

**任一 FAIL → 回到 5.3 让 LLM 重写该节,不重写整本**。

## 6. Citations 幂等性账本

每本分册末尾固定有 `## Citations`,两张子表:

### 6.1 Project artifacts

| Path | Kind | Title | SHA256 (content) | First cited (ET) | Last seen (ET) |
|---|---|---|---|---|---|

- **New** 制品:加一行,`First cited` 和 `Last seen` 都 = `now-et`
- **Changed** 制品:更新 hash 和 `Last seen`,`First cited` 保留
- **Missing** 制品:标题加 `(deleted)` 后缀,保留行

### 6.2 External references

| URL | Title | Cited from section | Last fetched (ET) |
|---|---|---|---|

外部引用(网络搜索结果)不参与幂等,可重新拉取。

## 7. Helper 子命令

所有 helper 入口在 `scripts/manual_helper.py`,从项目根目录运行:

| 子命令 | 用途 |
|---|---|
| `now-et` | 打印当前 ET 时间戳(Citations 表用) |
| `init <md-path>` | 创建单本手册 scaffold(如不存在) |
| `init-skill [project-root]` | 一次性 bootstrap,创建目录 + 占位 config;**personas.json 缺失则报错退出**(D1 强校验) |
| `scan-artifacts <project-root>` | 列出 `docs/superpowers/` 下所有制品 |
| `parse-citations <md-path>` | 解析已有手册的 Citations 表 |
| `diff-artifacts <project-root> <md-path>` | 返回 `new / changed / unchanged / missing` 桶 |
| `html-template-version` / `html-on-disk-version` | 读 HTML 顶部 `<!-- user-manual-dashboard-version: N -->` 整数 |
| `regenerate-html-if-stale <html-path>` | 模板版本更新时刷新 viewer |
| `write-index <html-dir> <md-path> [more...]` | 写 `manual-index.json` |
| `build-standalone <html-template> <html-out> <md-path> [more...]` | 构建 `file://` 双击版 |
| **`read-config`** | 打印 effective `manual-config.json` |
| **`validate-config`** | 校验 `manual-config.json` + `personas.json` 完整,业务目标覆盖度 ≥ 2 类别 |
| **`init-db`** | 应用 schema.sql 到 Postgres(idempotent) |
| **`upsert-manual <md-path>`** | POST markdown + frontmatter 到 API(db 模式) |
| **`upload-asset <manual-file> <asset-path>`** | 上传二进制到 S3/MinIO,注册到 `manual_assets` |

## 8. HTML viewer

`templates/user-manual.html` 是自包含的 dashboard。每次技能跑只 regen 当模板版本号变化时(由 `<!-- user-manual-dashboard-version: N -->` 整数控制)。

Viewer 支持两种模式:
- **HTTP 模式**:`user-manual.html` 拉取 `manual-index.json`,展示手册卡片,点击进入渲染
- **file:// 模式**:`user-manual-standalone.html`(由 `build-standalone` 产出),所有 md 内联为 `<script type="text/markdown">` 块,双击即用

Viewer 行为:
- 渲染 markdown 为 HTML(headings / 段落 / 列表 / GFM 表格 / fenced code blocks / 引用块 / 链接 / 图片 / 任务列表)
- 视频占位 `[VIDEO: X.mp4]` 渲染为可点击播放卡片(file 模式需手动嵌入)
- 暗 / 亮主题遵循 `prefers-color-scheme`
- 空状态:`抱歉,系统手册正在撰写中,无法为你提供相关帮助`
- 完全自包含 — 无 CDN / 外链 CSS / 外链 JS,离线可用

## 9. 跨模式 / 跨存储后端

Viewer 启动时 `loadRuntimeConfig()` 探测 `/api/config`:

| 模式 | 数据源 | 何时用 |
|---|---|---|
| `file`(默认) | markdown + assets 在本地磁盘(或内联在 standalone) | 单人 / docs 仓库 / 不需要服务端 |
| `db` | Postgres + S3/MinIO | 多用户 / Web 部署 / 不重新部署即可发布 |

db 模式额外:
- `<img src="../assets/...">` 在 markdown 渲染前被改写为 `public_base_url + module_code + basename`
- 资产必须已通过 `upload-asset` 上传

## 10. 调用流程(执行方必读)

1. **解析路径 + 加载现有状态**:`git rev-parse --show-toplevel` 拿项目根,`init` 写 scaffold(如缺)
2. **Diff 制品**:`diff-artifacts` 拿 `new / changed / unchanged / missing` 桶
3. **读 new / changed 制品**:读 markdown,提取标题、缩写、图表、状态标记(SHIPPED / WIP / DEFERRED — **只折叠 SHIPPED**)
4. **Web 搜索补强**:仅用于(1)术语 / 缩写展开、(2)项目外部标准。**不**用于项目内部事实。
5. **跑 helpers 抽数据**:4 个 extract helper 输出 JSON 数组
6. **写手册**:按第 5 节流程合成
7. **更新 Citations**:new / changed / missing 分类处理
8. **Regen HTML**:`regenerate-html-if-stale` 触发条件是模板版本号变化
9. **报告**:一行一桶(Manual updated / HTML viewer / Missing artifacts)
10. **问 commit & push**:默认不 commit,等用户确认

## 11. 反模式(避免)

- ❌ 整篇覆盖写:每跑都重写整本,丢用户编辑。**用 Citations 账本做幂等**。
- ❌ 把制品原文塞进手册:手册是给用户的,不是给开发者的。**综合,不抄**。
- ❌ 链接到 spec 当解释:用户点过去看 600 行 spec = 失败模式。**写解释,然后引用**。
- ❌ 折叠 WIP / cancelled 制品:手册描述当前已交付能力。
- ❌ web 搜索项目内部事实:spec / 代码权威。
- ❌ 跳过术语表:"缩写很显然" — 对用户不显然。
- ❌ 自动 commit:必须问。
- ❌ `git add .` / `git add -A`:只 stage 手册文件。
- ❌ 无故 bump HTML 模板版本号:版本号是全局信号,改了所有项目都被 regen。

## 12. 为什么是这套设计

静态站点生成器(MkDocs / Docusaurus)需要每页有明确作者;这个 skill 不需要 — 团队已经在写 spec / plan,skill 只做"开发者文档 → 用户文档"的翻译,跟制品演进自动同步。

## 13. 自动化录屏 (opt-in)

When the target project has the `recorder` opt-in plugin installed, assets are produced automatically by an LLM agent invoking the recorder's MCP tools or declarative scripts (see `recorder/SKILL.md`). The recorder is **not** part of the core user-manual skill. To enable, install the plugin per `recorder/INSTALL.md` and ensure the project's LLM agent can invoke the recorder's MCP tools.

The recorder produces files matching the `<domain>-<task>-<element>.png` naming convention in §1 above; these files drop directly into task card `[SCREENSHOT: ...]` slots. For video, the recorder emits a list of 10-second slices; the task card references the manifest.

## 14. 录屏阶段 (recording phase) — v0.2.3 新增

**This section is mandatory for the LLM agent.** A manual full of `[SCREENSHOT: x]` placeholders is **not** a finished manual — it's a draft. The recording phase fills those placeholders with real assets.

### When this section applies

After §5 (write the manual markdown), the agent must run §14 if the project is a **web app** with a runnable dev/staging environment. Skip if:
- The project is a desktop app, CLI tool, or pure API (no UI to record).
- The user explicitly says "skip recording" or "manual only".

### The 3-option flow

The LLM agent must ask the user **once** which mode to use, with a default of "record":

1. **`record`** (default) — record screenshots AND video for the key steps. Requires: target URL, login credentials (env var names), which steps are "key" (the rest get screenshots only).
2. **`screenshot-only`** — record screenshots but skip video. Lighter, faster.
3. **`skip`** — leave the placeholders in place. User will fill them later by hand or with another tool.

### Workflow (mode = `record` or `screenshot-only`)

```
1. LLM agent runs:
   python3 -m manual_helper record-manual <path-to-manual.md>
   # → prints: "RECORDING_NEEDED: N screenshots, M videos"

2. (Optional) LLM agent asks user for URL + creds, then runs:
   python3 -m manual_helper record-manual <path> --generate-template <out.json>
   # → emits a recorder script template the agent fills in

3. LLM agent invokes the recorder opt-in plugin to record.
   The recorder (see recorder/SKILL.md) is opt-in — if it's not installed,
   this step fails. The user must `pip install -e recorder/[test]` per
   recorder/INSTALL.md and re-run.

4. After recording finishes, the recorder produced real .png / .mp4 files.
   The LLM agent produces a mapping JSON:
   {
     "01-list": "docs/user-manual/screenshots/sys/01-list.png",
     "demo-flow": "docs/user-manual/screenshots/sys/demo-flow.mp4"
   }

5. LLM agent runs:
   python3 -m manual_helper record-manual <path> --apply-mapping <mapping.json>
   # → replaces [SCREENSHOT: x] / [VIDEO: x] placeholders with ![x](path) markdown
   # → prints "replaced: N placeholders, placeholders still missing: M"
   # → if M > 0, the agent must decide: re-run recorder for missing, or
   #   accept the gap (call them out in the manual's "Open Questions" section)
```

### Helper subcommand reference

| Subcommand | Purpose |
|---|---|
| `record-manual <manual.md>` | Scan and report placeholders. Exits 0 always; never modifies the manual. |
| `record-manual <manual.md> --generate-template <out.json>` | Same, plus emit a recorder script template the LLM agent fills in. |
| `record-manual <manual.md> --apply-mapping <mapping.json>` | Replace placeholders with real paths from the mapping. Writes the manual back. |

### What this section explicitly does NOT do

- It does **not** automatically detect the project's dev environment.
- It does **not** generate a recording script for the LLM (only a template).
- It does **not** run the recorder itself — that's the LLM agent's job.
- It does **not** decide which steps get video vs. screenshot — the LLM agent does that.

### Why deterministic

The recording phase has 3 deterministic primitives (scan, generate-template, apply-mapping) because those are easy to get wrong in prose. The LLM-heavy work (running the recorder, picking selectors, handling login state) stays in the LLM agent loop where it belongs.

代价是结构强约束:手册位置固定,7 段(11 段 + 附录)固定,Citations 格式固定。**正是这种结构让幂等成为可能** — 不固定,每次跑都要重新推导。
