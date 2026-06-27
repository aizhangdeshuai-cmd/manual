---
name: user-manual
description: Generate and incrementally maintain a per-project user manual at `<project>/docs/user-manual/manual/*.md` plus a self-contained HTML viewer, by analyzing the project's superpowers artifacts (`docs/superpowers/{specs,plans,findings,reviews}/`) and fortifying with web search. Trigger on `/user-manual`, "generate user manual", "create user manual", "update the user manual", "refresh the manual", "build a manual from the specs and plans", or any phrase asking for end-user / operator documentation drawn from project specs and plans. Idempotent across runs (the optional `## Citations` section, off by default, records the SHA256 of every cited artifact when `manual-config.json` sets `include_citations: true`; the LLM generating the markdown MUST NOT add a `## Citations` section unless `include_citations: true` is explicitly set — even if other context suggests it; only new or changed artifacts are folded in on subsequent runs). Targets business users as the primary audience (operations / specialist / manager / approver / external collaborators), and writes in the **Feishu / DingTalk-style** user-guide tradition: granular task cards (one task card = one specific operation, not a user journey), screenshot-driven with colloquial captions, "操作前必看" preamble per task card, ultra-short imperative sentences, embedded Q&A section, video support alongside screenshots. Frontmatter reserves `audience / task / prerequisites / related` fields for future Q&A AI integration. Project-agnostic core + project-layer config — same skill works on any project that fills in `manual-config.json` + `personas.json`. **v1.0.0 hard requirements**: (a) every deliverable MUST contain real screenshots and narrated videos (alt text cannot be `占位:` / `<TODO:>`; `[SCREENSHOT: x]` / `[VIDEO: x]` placeholders cannot remain in the final text); (b) do NOT add a `## Citations` section to any user-facing manual unless `manual-config.json` explicitly sets `include_citations: true` — Citations are an internal SHA-tracking tool for code review, not for end users. There is no skip/draft mode — if the recording phase cannot run, the skill exits with an error and the LLM must fix the environment (start dev server, install deps) before re-running. When the `recorder/` opt-in plugin is installed, screenshots and videos are produced automatically by the recorder's LLM agent invoking Playwright; the plugin's design lives in `recorder/SKILL.md` and install steps in `recorder/INSTALL.md`. Do not invoke for purely internal / developer-facing READMEs that aren't drawn from superpowers artifacts.
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

**v0.5.4: alt 文本禁止模式**(遇到 LLM 会完量跳过):
- ❌ `占位:指标列表` / `占位:新增` / `占位:表单` — LLM 看到截图不在事就用“占位:”拼出来的冗余 alt。v1.0.0 不允许这种 alt 存在 — 要么走 record 模式拍真图,要么删掉这个引用。
- ❌ `系统截图` / `screenshot` / `img1` — 沉默占位,要么补出真实地位描述,要么删除引用
- ❌ `这个页面显示了 X` / `详情页面截图包含 Y` — 描述式 alt(上面 §2.2 反例),> 15 字
- ❌ alt 直接拷负文件名 `指标列表.png` — 读画面的人看不懂

`validate-output.py --strict` 在 v0.5.4 会检查上述禁止模式(匹配上述 4 种兴行),出现任一个则报 `placeholder_alt` 与代。

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

**v0.4.0 硬约束**:**每类至少 3 个 Q**(全分册 ≥ 12 Q)。少于 3 个说明该类问题没梳理透,会让最终用户卡住没地方查。模板示例里只有 2 个 Q 是**反例**,不是目标。

### 2.6 视频与截图并行

**v2.2.0 硬门**:每个任务卡的录屏视频放在独立的 `#### 演示视频` 段,**位于 `#### 步骤` 之前**(紧跟在"操作前必看"块和 7 字段硬模板之后)。**步骤段(`#### 步骤` 内部)只放步骤说明 + `![alt](path.png)` 截图,禁止 `[VIDEO: x](path.mp4)`** —— `validate-output.py` 第 14 项 `video_outside_steps` 会卡这个。

格式:
```markdown
#### 演示视频

[VIDEO: <task>-demo.mp4](<path>.mp4)  一段 1 分钟左右的演示

#### 步骤

1. <动词开头,≤ 30 字>![<口语化图说>](<step>.png)
2. <动词开头,≤ 30 字>![<口语化图说>](<step>.png)
```

**为什么放演示视频段、而不是塞到步骤里**:读者先看一段完整演示理解整个流程,再按步骤一步步跟做。视频塞进某一步会打断阅读节奏、还让 viewer 把视频渲染到段落中间,view 在屏幕中央贴一行 `<video>` 卡片,体感奇怪。

缺视频时(没录过或录失败)不写 `#### 演示视频` 段即可,不必留 `[VIDEO NEEDED]` 占位 —— `validate-output.py` 已经把"步骤段内出现 `.mp4)` 引用"判 FAIL,所以这一步要改就改对,占位符混进去比"不录"更糟。截图同理:步骤段里出现 `[SCREENSHOT:` 占位也会被 `screenshot files exist` 检查抓。

**视频由 viewer 渲染**:`[VIDEO: title](path.mp4)` 在 viewer(`templates/user-manual.html`,dashboard v25)中被 `convertVideoLinksInMd` 转成可播放的 `<video controls>` 卡片,详见 §8。frontmatter 的 `narration` 是录屏配音输入(§2.6.1),与 viewer 渲染是两条独立链路。

### 2.7 视觉锚点词汇表(任务卡内固定使用)

| 锚点 | 用途 | 示例 |
|---|---|---|
| `> ⚠️ 注意:` | 重要警示,操作前必读 | `> ⚠️ 注意:删除后无法恢复` |
| `> 💡 提示:` | 经验性技巧,新手可跳但老手会爱 | `> 💡 提示:按 Ctrl+S 快速保存` |
| `> ❌ 禁止:` | 反模式,做了会出错 | `> ❌ 禁止:不要在生产环境用 admin 账号调试` |
| `> 📌 备注:` | 上下文补充,不影响主流程 | `> 📌 备注:此功能 v2.1 上线,当前灰度中` |

**仅这 4 种锚点**,不在此 4 类的内容用普通段落,不用其他 emoji。

### 2.7.1 业务用户文档禁列项(v1.1.0 新增,v1.1.1 扩)

> 业务用户(运营 / 专员 / 主管 / 审批人 / 外部协作方)读这份手册时,看到的应该是**操作内容**,不是**生成过程**也不是**开发信息**。
> 任何让用户看到"这文档是怎么写出来的"或"代码长什么样"的内容都属于创作痕迹,**禁止写入**。
> 规则不能靠"换措辞绕开"——下表是**模式**匹配(代码 + 含义),LLM 不能用同义词 / 缩写 / 上下文跳转 / 中文转英文来绕过。类 1/2/3/4/5/7 由 `validate-output.py` 的 `audience_leak` 检查(§verification-8)硬强制;类 6(事实性禁估算)与类 7a(术语必译)是**软约束**,validator 不卡(详见各类尾部标注)。

**6 类禁列项**:

1. **`> 数据源:` 类元注释** — 任何形如 `> 数据源:...` 的引用块,说明"这段内容从哪里抽出来的"。
   - ❌ `> 数据源:LLM 静态读取 report-admin-ui/src/types/report.ts + utils/fieldType.ts。`
   - ❌ `> 数据源:manual-config.json.auto_extracted + LLM 静态读取。`
   - ❌ `> 数据来自 ehr-report/.../common/ErrorCode.java`
   - ✅ 改用:不写。需要解释时,放 LLM 内部 prompt,不放用户文档。

2. **后端 API endpoint(任何上下文)** — 业务用户不需要看后端 `/report/...` 接口。
   - ❌ 任何 4+ 列的"方法 / 路径 / 用途 / 鉴权"API 表
   - ❌ bulleted list / Q&A 块 / "如果你卡住了" 答案里出现 `/report/field/validate-expr`、`/report/config/{code}/disable` 这类 endpoint
   - ✅ 改用:任务卡步骤里直接说"提交保存"(用户视角),不提具体路径。
   - ✅ **路由保留**(`/report/list` / `/report/{c}/designer/{c}` 是用户访问的浏览器 URL,与 API endpoint 区分)
   - 例外:技术附录(面向开发),不属于本 skill 范围。

3. **源码文件路径(任何上下文)** — 业务用户不需要知道代码在哪。
   - ❌ 任何"模块 / 路径"形式的文件清单(`report-admin-ui/src/...` / `ehr-report/...`)
   - ❌ Q&A / bulleted list / 备注 里出现具体文件名(如 `ReportConfigController.java`)
   - ✅ 改用:不写。开发同学自己看 IDE / Git。

4. **仓库 / 目录结构引用(任何上下文)** — 业务用户不需要知道后端 / 前端 / 文档各放哪个仓库。
   - ❌ 列表项 / 句子出现 `ehr-report/` / `report-admin-ui/` / `docs/user-manual/`
   - ❌ "(项目根 `ehr/`)" / "项目根: `my-app/`" / "repo root `xxx/`" / "代码根目录 `xxx/`" / "项目仓库 `xxx/`" 任何形式
   - ✅ 改用:附录 B 联系支持只列 3 类角色:**平台管理员**、**报表配置员 / 业务专员**、**数据 / HR 业务接口人**。代码 / 部署问题不写,开发同学有内部渠道。

5. **录屏 / 截图占位段** — 业务用户读手册时不应看到"待录 / 脚本就绪 / 录屏骨架"。
   - ❌ `<!-- video-pending: v7 ... -->` HTML 注释
   - ❌ `⏳ **视频录屏待补**:...` 提示段
   - ❌ `recorder-scripts/vN-*.json` 引用
   - ❌ 任何"待录" / "已写脚本,跑 X 命令即可生成" / 指向内部开发脚本的链接
   - ✅ 改用:录屏真实存在时,直接 `<video src="...">` 内联;不存在时,**任务卡正常交付,没有视频就行**,不要告诉用户"待补"。

6. **事实性内容禁估算(v1.1.1 新增)** — 用户按手册操作,涉及数字 / 列表 / 错误码 / 函数名 时,必须**从代码抽**而不是 LLM 估算。
   - ❌ 凭印象写"22 个函数"(实际 19 个,差 3 个就是误导)
   - ❌ 凭印象写错误码 2001="必填项缺失"(实际 2001="无权限访问该公司数据")
   - ❌ 凭印象写"支持 3 种筛选",实际有 6 种
   - ✅ 改用:用 §5.1 列出的 5 个 extract helper 抽(`extract-tasks` / `extract-fields` / `extract-routes` / `extract-roles` / `extract-openapi`),数字和列表必须从代码读。
   - ✅ Tier 3(LLM-only mode)例外:helper 不可用时,在手册末尾用 1 行 `[LLM-ESTIMATED]` 标注哪些内容是估算的(让用户知道可信度)。
   - ⚠️ **本类是软约束**:无可靠模式匹配,`validate-output.py` 不强制。靠 LLM 行为规范 + 人工审查 / CI 抽检兜底。建议在不放心的数字处落地一个确定性交叉校验(错误码表 ↔ `extract-roles` 输出、筛选项数 ↔ `extract-fields` 输出)。

7a. **业务概念术语必译(v1.1.3 新增)** — 业务用户手册面向**业务用户**(运营 / 专员 / 主管),不面向开发者。文档中**所有业务概念性质的英文术语必须译为中文**;**代码标识符 / 函数名 / API endpoint / 后端类名保留英文**(因为翻译就找不到了)。

   - **必译**(业务概念 / 通用 UI 术语):
     - `mock` → 演示 / 演示环境
     - `localStorage` → 本地存储(或保留为术语,首次出现用"浏览器本地存储 `localStorage`")
     - `sessionStorage` / `cookie` → 同上
     - `toast` → 顶部提示 / 提示框
     - `drawer` → 抽屉
     - `modal` / `dialog` → 弹窗 / 对话框
     - `skeleton` → 骨架屏
     - `spinner` → 加载中
     - `Q:` / `A:` → 保留(中英文 Q&A 都用)
     - `token` → 登录身份(用户不知道 token 是什么)
     - `hidden` (作为状态描述) → 隐藏
     - `group` (作为功能描述) → 分组
     - `mock` / `fake` / `stub` → 演示 / 假数据
     - 通用 UI 英文词:`enabled` `disabled` `default` `required` `optional` `nullable` `readonly`
   - **保留英文**(代码标识符 / 业务不可改的命名):
     - 后端字段名:`att.clock_in` / `emp.emp_no` / `work_duration`
     - 报表编码:`att_raw_default` / `monthly_att`
     - 函数名:`IF` / `COALESCE` / `TIMEDIFF` / `LIKE` / `CONCAT` / `EXCEL` 公式语法
     - 操作符:`=` / `>` / `<` / `IN` / `BETWEEN`
     - 字段类型值:`STRING` / `NUMBER` / `DATE` / `DATETIME` / `DURATION` / `BOOLEAN` / `UPSTREAM` / `EXPR` / `CONST`
     - 键名 / 路径 / 端口号(用户访问的浏览器 URL 保留)
   - **改名 / 删**:
     - 后端类名(对用户无意义):`ReportQueryGuard` / `ErrorCode` / `ReportConfigController` 等 → 删
     - 后端文件名:`ErrorCode.java` / `ReportConfigController.java` 等 → 删
     - 已在类 3(源码路径)覆盖
   - ⚠️ **本类是软约束**(语义判断、模式匹配误伤率高),`validate-output.py` 不强制,靠 LLM 行为规范 + 人工审查。

7. **架构 / 部署信息禁列(v1.1.2 新增)** — 业务用户进手册是来"做操作"的,不是来"看架构图 / 部署拓扑"的。这类信息对**开发 / 运维**有用,对业务用户没有应用价值。
   - ❌ 后端 URL / 端口号:`http://localhost:9001/`、`http://api.example.com/v2`
   - ❌ 后端技术栈版本:`Spring Boot 2.7`、`H2 in-memory`、`Vue 2.7 + Element UI`、`Node.js 18`、`PostgreSQL 14`
   - ❌ 架构提示:"3 个核心页面用**同一套后端 API**"、"前后端用 RESTful 通信"、"前端是 SPA 单页应用"
   - ❌ 模块地图(路由列表 + 用途说明):"报表列表 `/report/list` — 找报表、版本治理"
   - ❌ 部署 / 启动命令:`mvn spring-boot:run`、`npm run serve`、`launchd 加载 com.local.ehr-backend`
   - ✅ **前端 URL 保留**:`http://localhost:8088/` 是用户访问的入口,业务用户需要。
   - ✅ **改用用户视角**:"3 个核心页面用**同一份数据**" 替代 "用同一套后端 API";"改完字段要看效果" 替代 "前端调 RESTful 接口"。
   - ✅ 路由(`/report/list`、`/report/{c}/designer/{c}`)作为"操作入口"在任务卡里出现 OK,作为"模块地图"列出禁。

> 写给 LLM 的提示:你(LLM)在 §5.3 合成 markdown 时,生成的输出里**不应该**包含上述 6 类内容;如果发现已经在脑里浮现了,删掉再写。`validate-output.py` 会卡住你。
> 关键:**规则是模式匹配**,不是关键词列表。改同义词 / 改英文 / 改上下文位置 / 把表改成 bullet / 把 bullet 改成段落——**都不能绕过**。

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
A: 看浏览器右上角网络图标 — 红色断线 = 网络问题,黄色 = 慢。再看后端日志:tail -f /var/log/<your-project>/app.log | grep ERROR。

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

### 2.6.1 操作旁白(narration,v0.3.2+)

任务卡若配套 **recorder 插件** 录制,可在每张卡的步骤旁加 **`narration`(可选)**:一句口语化旁白,LLM 用作 TTS 文本,通过 `edge-tts` 合成后由 ffmpeg 合并进录屏视频。

**目的**:
- 用户看视频时,听到与步骤同步的语音(无需读字幕)
- 录屏时长 < 旁白时长 → 视频自动 loop;录屏时长 > 旁白时长 → 视频尾部被裁(以旁白为准)
- 段间自动插入静音(默认 2.0s),让用户"看完一步、听下一步"

**模板** —— 在任务卡内(可选,放在 `### 字段说明` 之后或作为 frontmatter 字段):

```yaml
---
narration: # 数组,每段一段文字,顺序对应任务卡的步骤
  - 打开系统管理,点击用户管理。
  - 点击新增用户,填写工号和手机号。
  - 核对信息无误后,点击保存。
narration_gap: 2.0   # 段间静音秒数(可选,默认 2.0)
narration_voice: zh-CN-XiaoxiaoNeural  # 可选,Edge TTS 音色 ID
narration_rate: "+0%"  # 可选,语速调节
---
```

**约束**:
- narration 是**可选字段**,不写就不配音,录屏走原流程
  - **v0.5.1:** 缺 `narration` 字段的 video_stop 在运行时会有 stderr WARNING 提示
    (例:`WARNING: 3 video session(s) have NO \`narration\` field; output videos
    will be SILENT. ...`),并在 recorder 端`recorder_plugin.cli run`preflight 报 FAIL,免得
    "录完才发现没声音"才回头查
  - 需要 CI 强制要求?在 v0.5.1 之后会再加 `--strict-narration` flag 让
    `_preflight_narration_coverage(force=True)` 抛错退出
- 旁白文案要**口语化、动词开头、≤ 30 字 / 段**,与步骤文字保持同步
- 不需要重复步骤里的细节(用户已经看到画面),只补充"在做什么、为什么"
- edge-tts 离线不可用时,recorder 跳过 narration(降级不报错),产物仍是无声视频。
  这是**第二种 silent 失败场景**:① 字段缺失 ② TTS 不可用。两者都会产生无声视频,
  区别是 ① 走 preflight WARNING,② 走 runtime `WARNING: narration failed` 并
  保留 .silent.mp4 备份

**示例 — 完整任务卡 + narration**:

```markdown
### 创建新员工账号

> ⚠️ **操作前必看**
> - 需要"系统管理员"角色
> - 员工姓名 / 工号 / 手机号 必填
> - 创建后默认密码 = 工号后 6 位

**适用角色**:`sys_admin`
**前置条件**:员工已在 EHR 入职
**入口**:`系统管理 → 用户管理 → 新增用户`
**narration**:
- 打开系统管理菜单,进入用户管理页面。
- 点击右上角"新增用户"按钮,弹出表单。
- 填写工号、姓名、手机号三个必填字段。
- 点击"保存"按钮,列表里出现新员工。

#### 步骤
1. 打开系统管理 → 用户管理[SCREENSHOT: nav-user-mgmt.png]
2. 点「新增用户」[SCREENSHOT: user-add-btn.png]
3. 填工号 / 姓名 / 手机号[SCREENSHOT: user-form.png]
4. 点「保存」[SCREENSHOT: user-save-btn.png]
5. 列表里出现新员工

#### 成功后看到
- 列表顶部出现新员工的一行
- 默认密码弹窗提示"工号后 6 位"

#### 如果你卡住了
- **Q: 提示"工号已存在"?**
  A: 换一个工号,或在「用户管理」里搜该工号确认是否建过。
- **Q: 看不到"新增用户"按钮?**
  A: 检查账号是否有"用户管理"权限,联系系统管理员申请。

**视频**:`[VIDEO: create-employee.mp4]` — 含 4 段旁白,段间 2 秒静音



## 3. 章节结构(11 段 + 附录)

每本分册严格按以下顺序组织:

| # | 章节 | 内容 | 自动 / LLM |
|---|---|---|---|
| 1 | 封面信息(frontmatter) | title / module / module_code / **description** / version / version_date / audience / task / prerequisites / related | LLM |
| 2 | 文档说明 | 本分册面向谁、范围、不包含什么、与其他分册的关系 | LLM |
| 3 | **读法指南** | 本分册怎么读、各章节定位、视觉锚点说明、Q&A 怎么用 | LLM |
| 4 | 目录 | **v1.0.1 (硬门):** 写完 §2-§9 之后, **立刻回头** 用 `## 目录` 段把 5-10 个 H2/H3 标题列成 `[<标题>](#<anchor>)` 链接(an anchor 形式)。**禁止** 留 `<!-- toc -->` 占位 / 留空 / 只写"见右侧"。`validate-output.py` 9th check 会强制: `## 目录` 段后必须有 ≥ 5 行 `- [` 链接,否则整本 FAIL。**为什么硬门:** 之前的 v0.5.2 规则被 LLM 反复忽略,viewer 左侧导航就空了,用户读不到结构。例:<br>`## 目录`<br>`- [文档说明](#文档说明)`<br>`- [读法指南](#读法指南)`<br>`- [任务卡 1:登录](#任务卡-1登录)`<br>`- [任务卡 2:切换分册](#任务卡-2切换分册)`<br>`- [常见问题](#常见问题)` | LLM |
| 5 | 修订历史 | 独立小节,frontmatter `revision_history` 字段同步 | LLM |
| 6 | 术语表 | 项目专属术语 + 业务领域缩写,首次出现展开 | LLM |
| 7 | 系统概述 | 运行环境、浏览器、登录入口、关键模块地图 | LLM |
| 8 | 快速开始 | 假定环境就绪,1 句话 + 1 张任务卡链 | LLM |
| 9 | **任务卡** | 按 personas 派生,**每张卡 7 字段硬模板 + "操作前必看"块** | LLM |
| 10 | 字段参考 | 用 `extract-fields.py` 聚合,按模块分组 | 自动 |
| 11 | 配置参考 + 故障速查(场景化) + 联系支持 | 配置项;故障速查按 4 类(权限/网络/数据/操作);联系支持 | LLM |
| 12 | **Citations**(v0.5.2 opt-in) | **默认不写**。仅当 `manual-config.json: include_citations: true` 才生成,内部两张子表(Project artifacts / External references)用于代码审查的 SHA 跟踪。**不要**给最终用户看,他们是 noise | LLM(条件) |
| 附录 A | 错误码速查(6 列硬结构) | HTTP 状态 / 业务错误码 / 症状 / 原因 / 解法 / 找谁 | LLM |
| 附录 B | 联系方式 / 技术支持 | 团队 / 邮箱 / 工单系统 | LLM |

**删除**(v1 旧结构):
- ❌ `## Architecture and Internals` — 移入分册附录,只留 1 个数据流图
- ❌ `## Daily Usage`(被"任务卡"替代)
- ❌ `## Concepts and Glossary`(被"术语表"替代,位置调整到第 6 段)

## 4. 任务卡硬模板(7 字段 + "操作前必看")

> **v0.3.2: 写完每张任务卡前**——LLM 写 manual 前先**自己**跑一遍 `validate-output.py <your.md>` 自检。下面是 7 项检查**精确**的 regex / 关键字，写卡时**目标**就是触发这些：
>
> | # | 检查名 | 触发条件（LLM 自检时数一下）| 阈值 |
> |---|---|---|---|
> | 1 | `7-field hits` | 含 `适用角色` / `前置条件` / `操作前必看` / `### 步骤` / `### 成功后看到` / `### 字段说明` / `### 如果你卡住了` / `### 相关任务` 的数量 | ≥ 6 |
> | 2 | `操作前必看 blocks` | 含 `操作前必看` 字样的次数（**不含** fenced code 块内）| ≥ 3 |
> | 3 | `visual anchors` | 含 4 个 emoji 锚点（⚠️ / 💡 / ❌ / 📌）的总次数 | ≥ 3 |
> | 4 | `appendix-A 6-col table` | 含 6 列 markdown 表格（`| --- | --- | ... |` 共 6 个 `---` 单元格）| ≥ 1 |
> | 5 | `role-permission matrix` | 含 `## 角色与权限速查` / `角色权限速查` / `角色与权限` / `Role Quick Reference` 等（同义）| ≥ 1 |
> | 6 | `screenshot count` | 含 `![alt](path.png)` / `![alt](path.jpg)` 链接次数 | ≥ 2 |
> | 7 | `screenshot files exist` | **每条** `![alt](path.png)` 对应文件 ≥ 50×50 px（**不**是 1×1 占位）+ 文本里没有未替换的 `[SCREENSHOT: x]` / `[VIDEO: x]` 占位 | 全部 |
| 8 (v0.4.0, opt-in) | `screenshot unique` | 所有引用 PNG 的 SHA256 中,没有 2+ 不同文件名指向同一 hash(防 recorder 重复截图) | 全部(传 `--unique` 才检查) |
> | 9 (v1.0.1) | `directory_anchors` | `## 目录` 段后 ≥ 5 行 `- [标题](#锚)` 链接 | ≥ 5 |
> | 10 (v1.0.1) | `task_card_headings` | 所有 `### 任务卡 N: ...` 编号从 1 起连续无跳号 | 连续 |
> | 11 (v1.1.0) | `audience_leak` | 业务用户文档不含数据源/API路径/源码路径/仓库树/录屏占位/后端URL端口/技术栈版本 | 0 |
> | 12 (v2.1.0) | `frontmatter_description` | frontmatter 含非空非占位 `description`(viewer 搜索摘要靠它) | ≥ 1 |
> | 13 (v2.1.0) | `unfilled_template_terms` | 正文 / 反引号里都没有 `对应地址` / `手册所在目录` / `起静态站服务`(子命令名当命令) / `<your-...>` 这类未替换模板话术 | 0 |
> | 14 (v2.2.0) | `video_outside_steps` | `#### 步骤` 段内**禁止**出现 `.mp4` 引用(视频必须在 `#### 演示视频` 段,放在步骤前) | 0 |
>
> **LLM 写作 checklist**（写完一张卡就 grep 一遍）：
> - [ ] 这张卡 7 字段全（适用角色 / 前置条件 / 操作前必看 / 步骤 / 成功后看到 / 字段说明 / 如果你卡住了 / 相关任务）
> - [ ] 有 ≥ 1 个 `操作前必看` 块（不在代码块里）
> - [ ] 至少 1 个视觉锚点 emoji（⚠️ / 💡 / ❌ / 📌）
> - [ ] 引用的图都是**真实文件**（≥ 50×50 PNG），不是 1×1 灰
> - [ ] 没有任何未替换的 `[SCREENSHOT: xxx.png]` / `[VIDEO: xxx.mp4]` 占位
> - [x] **必跑** `python3 -m manual_helper fill-citation-shas <this.md>` 把 `(auto)` 替换成真 SHA(不跑则 validate FAIL)
>
> 跑完两套检查(都必须 exit 0):

```bash
# 检查 1: §5.4 手写 bash 7 项(任务卡格式)
bash §5.4 里的 bash 脚本 docs/user-manual/manual/<name>.md

# 检查 2: validate-output.py §8 项(含本地文件系统 + placeholder_alt)
python3 scripts/validate-output.py docs/user-manual/manual/<name>.md --strict
```

**v0.5.4 硬门**: 任一个 FAIL 都不能宣布手册完成。LLM 代理人在 commit 前 **必须**把两个检查的输出(含 `hits=N/threshold=M` 数字)贴到 commit message 或 输出里。`validate-output.py --strict` 走 `placeholder_alt` 会报任何项目里的 `占位:` alt (grc 项目审计时是 98 个)(§2.2 禁止模式) — 这些是 LLM 代理人 “草稿当成品” 的典型忠冲。

```markdown
### 任务卡 1: <动词开头任务名,如"创建新员工账号">

> ⚠️ **操作前必看**
> - <权限要求 / 必备前提 / 重要后果 / 时间窗口>

**适用角色**:`<persona_id>`(从 personas.json 取)
**前置条件**:<bullet 列表,从 prerequisites 派生>
**入口**:`<path>`,对应后端 `<api_path>`

#### 演示视频

> 💡 **本段在 `#### 步骤` 之前**(v2.2.0 硬门)。任务卡若配套录屏视频,
> 放在这个独立 `#### 演示视频` 段里,跟"操作前必看"块前后相邻。
> **步骤段内禁止视频**(`[VIDEO: x](path.mp4)` 不能出现在 `#### 步骤` 里)
> —— 步骤段只放步骤说明 + `![alt](path.png)` 截图。理由:读者期望先看一段
> 完整演示理解全流程,再按步骤一步步跟做;视频塞进某一步会打断节奏。
> 缺视频时不写本段即可;`validate-output.py` 第 14 项硬门会卡"步骤段
> 出现 .mp4 引用"。

[VIDEO: <task>-demo.mp4](path/to/<task>-demo.mp4)  一段 1 分钟左右的演示

#### 步骤

1. <动词开头,≤ 30 字>![<口语化图说>](path/to/<step>.png)
2. <动词开头,≤ 30 字>![<口语化图说>](path/to/<step>.png)
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

**v0.5.2 (v1.0.1 硬门):** 任务卡 heading **必须**是 `### 任务卡 N: <title>`,§任务卡 N 从 1 开始按文档顺序递增。`validate-output.py` 第 10 项检查会强制:文档中所有 `### 任务卡 N:` heading 必须顺序且连续(N=1,2,3,...),否则整本 FAIL。这样:
- 任务卡与 Q&A 等其他 H3 段(`### 权限类` / `### 词汇表`)在 viewer 左侧 TOC 视觉上分组明显
- 数字编号让"读法指南"里的"看任务卡 3"和"相关任务"链接可点击跳转
- 失败反例(LLM 容易写错):`### 创建合同`(无编号)、`### 任务卡 创建合同`(空格不是冒号)、`### 任务卡1:创建合同`(冒号前无空格)

**v0.5.2: 步骤块必须用 `#### 步骤` 包裹** —— 失败反例:直接写 `1. 步骤 1\n2. 步骤 2` 数字行(无标题),这样在 viewer 左侧 TOC 里看不到"步骤"节点,且 §2.4 "极简语法"检查识别不到。成功格式:空行 → `#### 步骤` 标题 → 数字列表 → 空行 → `#### 成功后看到`。

**必含字段**:7 个(`适用角色 / 前置条件 / 入口 / 步骤 / 成功后看到 / 字段说明 / 如果你卡住了`)+ `相关任务`(可选,推荐) = 实际 8 字段。

**可选第 9 字段:`narration`** —— 操作旁白数组,详见 [§2.6.1](#261-操作旁白narrationv032)。LLM 写卡时:
- 简单任务(单步操作)可不填 → 录屏走无声原流程
- 复杂任务(多步、有上下文)推荐填 → 视频自动配音,用户体验更好
- 旁白文字应 **口语化、动词开头、≤ 30 字 / 段**,与步骤动作对齐而非重复细节

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
#   ⚠️ `**` 依赖 shell globstar:bash 需 `shopt -s globstar`(zsh 默认开,POSIX sh 不支持)。拿不到文件时改在 Python 里 `Path(backend_root).rglob("**/dto")`(或 `shopt -s globstar` 后再跑)。下同 `--java <...>/**/*`。

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
7. 产物**内部可追溯、对用户不可见**:抽取来的数据若需标注出处,**仅写入 Citations 表**(且仅当 `manual-config.json: include_citations: true` 时才生成该表)。**禁止**在正文 / 任务卡 / `![]()` / Q&A 里散落任何 `<!-- source: ... -->` 或 `> 数据源:` 这类元注释——它们属于 §2.7.1 类 1(创作痕迹)与类 3(源码路径)的禁列项。未开 Citations 时就不标注,追溯靠 `extract-*.json` 与 commit 历史。

## 禁止
- 不要用开发者术语(mvn / POST / 8089 / etc.),读 manual-config.json 取部署信息
- 不要写"在 pom.xml 里改 X"——读者是业务用户
- 不要折叠 WIP / cancelled 制品
- 不要整篇重写——只动你负责的 persona 子集

## 输出格式
- 1 个 markdown 文件
- 文件名:`<module>-user-manual.md`
- 文件开头 frontmatter:title / module / module_code / **description** / version / version_date / audience / task / prerequisites / related
- **`description` 必填且非空**(v2.1.0 硬门):INTEGRATION §3.5 viewer v2 解析此字段做搜索结果摘要。空字符串 / `占位` / `<TODO:>` / `<your-...>` → `validate-output.py` FAIL。写一到两句话:本册面向谁、做什么。**不要**写"详细见正文"这类无信息量摘要。
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

# v0.5.4: alt 禁止模式 §2.2 硬规则(同步到 validate-output.py 的 placeholder_alt 检查)
LAZY=$(grep -cE '!\[\s*(占位[:：]|<TODO|screenshot|img[0-9]*|\u7cfb\u7edf\u622a\u56fe)\]' "$F" 2>/dev/null || echo 0)
[ "$LAZY" -eq 0 ] || { echo "FAIL: alt 出现懒颜色 4 种禁止模式之一(§2.2),$LAZY 条详见 validate-output.py placeholder_alt"; exit 1; }

# 验证 7(v0.3.2): Citations SHA256 必须已填,不能再有 (auto) 占位
AUTO=$(grep -c "(auto)" "$F")
[ "$AUTO" -eq 0 ] || { echo "FAIL: Citations 仍有 $AUTO 个 (auto) 占位 — 跑 fill-citation-shas"; exit 1; }

# 验证 8(v1.1.0): 业务用户文档禁列项 — §2.7.1 前 5 类 audience_leak 模式
# 见 SKILL.md §2.7.1 + validate-output.py audience_leak 检查项
LEAK=$(python3 -c "from scripts.validate_output import _check_audience_leak; import sys; sys.exit(0 if _check_audience_leak(open('$F').read())['clean'] else 1)" 2>/dev/null; echo $?)
[ "$LEAK" = "0" ] || { echo "FAIL: audience_leak — 手册含 §2.7.1 禁列项(数据源注释 / 后端 API 表 / 源码路径表 / 仓库目录 / 录屏占位段)"; exit 1; }

# v0.4.0(opt-in): 截图去重 — 同 SHA256 不应被 2+ 不同文件名引用
# 默认不强制,跑 `validate-output.py --unique` 才生效
# 建议在 CI 中跑,首次生成时必跑;已有手册用 --unique-allow 显式放行

echo "OK: $F"
```

**v0.3.2 补充**: 写完每本手册后,执行方**必须**跑一次:

```bash
python3 -m manual_helper fill-citation-shas docs/user-manual/manual/<name>.md
```

把 Citations 表里的 `(auto)` 占位替换成真实 SHA256 哈希。这一步是 §7 工具表里的 `fill-citation-shas` 子命令,**不跑**则 §5.4 验证 7 直接 FAIL。

**任一 FAIL → 回到 5.3 让 LLM 重写该节,不重写整本**。

## 6. Citations 幂等性账本(内部工具,默认关闭)

> **❌ 业务用户手册禁止出现 `## Citations` 段。** Citations 是给**代码审查者**看的 SHA 跟踪表,不是给最终业务用户看的 — 用户操作手册里出现 SHA256 哈希 + 内部制品路径是 noise,会让手册失信。

**v0.5.2: Citations 段默认关闭,opt-in。** 它是给代码审查 / SHA 跟踪用的,不是给最终用户看的。

- **默认行为**(`manual-config.json` 不写 `include_citations`):LLM **不**在分册末尾生成 `## Citations` 段。skill 端 helper(`fill-citation-shas`)仍然能算 SHA(传入 `<md-path>` 即返回 markdown_table),但 markdown 不渲染。
- **打开方式**:`manual-config.json` 顶层加 `"include_citations": true`(适用做合规审计的项目,需要可追溯到具体 spec SHA)。
- **强制必含**:如果开了,LLM 写完**必须**跑 `python3 -m manual_helper fill-citation-shas <this.md>` 把 `(auto)` 占位替换成真 SHA,否则 validate FAIL。

若项目开了 Citations,每本分册末尾固定有 `## Citations`,两张子表:

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

所有 helper 入口在 `scripts/manual_helper/`(Python 包,v2.0.0 起由单文件 `manual_helper.py` 拆分而来)。**运行方式**:`cd scripts && python3 -m manual_helper <子命令> ...`,或 `PYTHONPATH=scripts python3 -m manual_helper <子命令> ...`。直接在项目根目录跑 `python3 -m manual_helper` 会报 `No module named manual_helper`——模块在 `scripts/` 下,需把它加入 `PYTHONPATH`。

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
| `check-recording-readiness [project-root]` | v0.3.1 pre-flight: dev server / playwright / Chromium / ffmpeg 状态。返回 0=绿 / 1=黄 / 2=红。`init-skill` 自动调用 |

> **recorder 插件的子命令**(opt-in,装 recorder 后才有):
>
> | 子命令 | 用途 |
> |---|---|
> | **`tts-synth <text> --out PATH`** | edge-tts 合成一段旁白 → mp3(可选 `--voice` / `--rate`) |
> | **`concat-narration <seg1> <seg2> [...] --out PATH [--gap S]`** | 多段旁白 mp3 拼接,段间插入静音(默认 2.0s) |
> | **`mux-audio <video> <audio> --out PATH`** | 旁白音轨合并到录屏视频(自动处理时长差,产物 = 旁白长度) |
| **`run <script.json>`** | 驱动 headless Chromium 跑完整录屏脚本,产出 .png / .mp4。返回 JSON 状态报告 |
| **`apply-ai-responses <output-dir>`** | 应用 agent 写的 AI 标注响应(Pillow),产出 `<name>.ai-annotated.png` |
| **`init-db`** | 应用 schema.sql 到 Postgres(idempotent) |
| **`upsert-manual <md-path>`** | POST markdown + frontmatter 到 API(db 模式) |
| **`upload-asset <manual-file> <asset-path>`** | 上传二进制到 S3/MinIO,注册到 `manual_assets` |
| **`prune-silent-backups <screenshots-dir> [--manual <md>...] [--apply]`** | v2.1.0: 删除 recorder 录制后遗留的 `.silent.mp4` 备份(其有声版被 manual 引用才算可删)。默认 dry-run 只报告,`--apply` 写盘。不传 `--manual` 自动发现 `<screenshots-dir>/../manual/*.md` |

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
7. **更新 Citations**(`v0.5.2:` **仅当** `manual-config.json: include_citations: true` 才执行,且**业务用户手册通常应保持关闭**):new / changed / missing 分类处理。**否则必须跳过**,markdown 末尾不写 `## Citations` 段,左侧 TOC 也不列
8. **Regen HTML**:`regenerate-html-if-stale` 触发条件是模板版本号变化
9. **报告**:一行一桶(Manual updated / HTML viewer / Missing artifacts)
10. **问 commit & push**:默认不 commit,等用户确认

## 11. 反模式(避免)

- ❌ 整篇覆盖写:每跑都重写整本,丢用户编辑。**`include_citations: true` 时**用 Citations 账本做幂等;默认关,直接覆盖整本没问题。
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

## 14. 录屏阶段 (recording phase) — v0.2.3 新增 / v0.4.0 升级

**This section is mandatory for the LLM agent.** A manual full of `[SCREENSHOT: x]` placeholders is **not** a finished manual — it's a draft. The recording phase fills those placeholders with real assets.

> **v2.0.0 (skill split)**: The recording phase is now **coordinated by
> the LLM agent**, not by a single `manual_helper` subcommand. v1.x had
> `record-and-replace` and `record-manual` as one-shot CLIs, but the
> recorder is a separate skill at `~/.agents/skills/recorder` (it has
> its own `recorder_plugin` package, MCP server, and CLI). v2.0.0
> removes the CLIs from user-manual and exposes the **markdown-level
> primitives** as Python functions only:
>
> ```python
> from manual_helper import (
>     scan_recording_placeholders,   # find [SCREENSHOT: x] / [VIDEO: x] / [AI ANNOTATE: x]
>     build_recorder_template,        # emit a recorder script template from the manual
>     apply_recording_mapping,        # replace placeholders with real asset paths
> )
> ```
>
> The **browser-level work** (Playwright launch, video recording, TTS,
> muxing) stays in the recorder skill. See `~/.agents/skills/recorder/SKILL.md`
> for the `run` / `apply-ai-responses` / `tts-synth` / `mux-audio` CLI
> subcommands.
>
> **Pre-condition (v1.0.0, unchanged)**: `init-skill` auto-installs the
> recorder dependencies (`playwright` + Chromium) and exits 2 if
> the recording phase cannot run (dev server unreachable, deps
> missing). There is no opt-out: fix the environment and re-run.
> The previous `--allow-blocked` flag was removed in v1.0.0.

### When this section applies

After §5 (write the manual markdown), the agent must run §14 if the project is a **web app** with a runnable dev/staging environment. §14 is **mandatory** for web apps — there is no "skip" option. Web apps without recording do not satisfy v1.0.0. §14 is not needed for:
- Desktop apps, CLI tools, pure APIs (no UI to record).
- Projects where the user explicitly says "screenshots only" (use
  the `screenshot-only` mode in option 2 above).

### The 3-option flow

**v1.0.0: only two valid modes — no skip option.** A user-manual
deliverable without real screenshots and narrated videos is not a
valid deliverable. The LLM agent must ask the user **once** which
mode to use, with a default of "record":

1. **`record`** (default) — record screenshots AND narrated video
   for the key steps. Requires: target URL, login credentials
   (env var names), which steps are "key" (the rest get screenshots
   only). **This is the only mode that produces a valid v1.0.0
   deliverable.**
2. **`screenshot-only`** — record screenshots but skip video.
   Lighter, faster. Use this when the project explicitly does not
   need videos (e.g. CLI tool, no UI animation).

> **No "skip" mode in v1.0.0.** v0.5.4 introduced a `skip` mode
> that required a `待补资产清单` section at the
> bottom of the manual. In practice the LLM agent always picked
> `skip` and shipped 100% broken image refs. v1.0.0 removes the
> option entirely. If the recording phase cannot run, fix the
> environment and re-run; do not deliver a draft.
>
> **评审 / 审计场景的降级(仅限非交付用途)**:当目标只是给人**评审手册结构 / 文案**(不交付给最终业务用户)、dev server 又无法在当前 sandbox 起来时,可临时把分册在 frontmatter 标 `status: draft-for-review`,并在含估算数字的章节末用 §2.7.1 类 6 的 `[LLM-ESTIMATED]` 标注。此标记**不**解除 §14 对最终交付物的硬约束;一旦要交付,必须回到 `record` / `screenshot-only` 模式补齐资产、去掉草稿标记。

### Workflow (mode = `record` or `screenshot-only`)

```
1. LLM agent scans the manual for placeholders (Python import, NOT a CLI):
   from manual_helper import scan_recording_placeholders
   placeholders = scan_recording_placeholders(Path("manual.md").read_text())
   # → list of {"kind", "name", "line", "raw", "needed"} dicts

2. LLM agent asks user for URL + creds, then generates a recorder
   script template (Python import, NOT a CLI):
   from manual_helper import build_recorder_template
   template = build_recorder_template(
       manual_name="sys-user-manual",
       placeholders=placeholders,
       manual_path=Path("manual.md"),
       project_root=Path("."),
   )
   Path("recorder-script.json").write_text(json.dumps(template, indent=2))
   # → the agent fills in TODO selectors / click sequences

   v2.1.0: 录制视口由 `build_recorder_template` 从 `manual-config.json` 的
   `recording.viewport: {width, height}` 读取;未配置时默认 **1920×1080**
   (进 desktop 全屏录制,不再用旧的 1440×900)。想让视频匹配发行业务用户的
   真实屏幕分辨率,就在 manual-config.json 写:
   ```json
   { "recording": { "viewport": { "width": 2560, "height": 1600 } } }
   ```
   (以固定大视口 headless 录制为准 —— deterministic、可 CI 重复;recorder 不开
   headed 真窗口全屏,那种被前台切走会黑屏。)

3. LLM agent invokes the recorder skill (separate CLI, NOT in manual_helper):
   python3 -m recorder_plugin.cli run recorder-script.json
   # → produces real .png / .mp4 files in <output_dir>
   # See ~/.agents/skills/recorder/SKILL.md for full reference.

   ⚠️  v0.2.4: the output JSON's `pending_ai_annotations` field may list
   vision requests. **Do not skip this.** The agent MUST handle it BEFORE
   applying the mapping. See §15 for the full flow.

4. (v0.2.4 only — agent-mediated AI annotation, see §15):
   for each entry in pending_ai_annotations:
     a. read <output_dir>/.ai_annotation_request_<name>.json
     b. use the agent's OWN multimodal LLM to read the image
     c. write <output_dir>/.ai_annotation_response_<name>.json with
        {"step_name": "<name>", "boxes": [{"label": "...", "x": 0, "y": 0,
                                            "w": 100, "h": 50}, ...]}
        (coords normalized to 0-1000 — see §15 for details)
     d. run: python3 -m recorder_plugin.cli apply-ai-responses <output-dir>
     e. exit code: 0 = all applied, 1 = some skipped (the agent must debug)

5. After recording (and AI annotation, if any) finishes, the recorder
   produced real .png / .mp4 files. The LLM agent produces a mapping JSON:
   {
     "01-list": "docs/user-manual/screenshots/sys/01-list.png",
     "demo-flow": "docs/user-manual/screenshots/sys/demo-flow.mp4",
     "ai-annotated-01-list": "docs/user-manual/screenshots/sys/01-list.ai-annotated.png"
   }
   (the `ai-annotated-*` keys are only present if §15 was used)

6. LLM agent applies the mapping (Python import, NOT a CLI):
   from manual_helper import apply_recording_mapping
   text = Path("manual.md").read_text()
   new_text, replaced, missing, total = apply_recording_mapping(text, mapping)
   Path("manual.md").write_text(new_text)
   # → replaces [SCREENSHOT: x] / [VIDEO: x] / [AI ANNOTATE: x] placeholders
   #   with ![x](path) markdown
   # → **v1.0.0**: `missing` MUST be empty. If recorder missed any, fix
   #   the script and re-run. A manual with unreplaced placeholders does
   #   not satisfy the user's requirement (real screenshots + narrated video).
```

### Recording-phase API reference (v2.0.0)

The user-manual skill exposes the **markdown-level primitives** as Python
functions. The browser-level work lives in the recorder skill.

| Python API (in `manual_helper`) | Purpose |
|---|---|
| `scan_recording_placeholders(text: str)` | Scan markdown for `[SCREENSHOT:]` / `[VIDEO:]` / `[AI ANNOTATE:]` markers. Returns list of dicts with `kind`, `name`, `line`, `raw`, `needed`. Excludes placeholders inside fenced code blocks. |
| `build_recorder_template(manual_name, placeholders, manual_path=..., project_root=...)` | Emit a recorder-compatible `script.json` template. Auto-fills `url` from `manual-config.json:project.host/port`; auto-fills `output_dir` from manual name; infers `auth_env` from manual name (e.g. `legal-user-manual` → `LEGAL_USER`/`LEGAL_PASS`). |
| `apply_recording_mapping(text, mapping)` | Replace placeholders with real asset paths. Mapping values may be strings (path only) or `{path, alt}` dicts (v0.3.0+). Returns `(new_text, replaced, missing, total)`. Writes the manual back is the caller's job. |
| `check-recording-readiness` (CLI, still in `manual_helper`) | v0.3.1 pre-flight: dev server, playwright, Chromium, ffmpeg. Returns 0=green / 1=yellow / 2=red. Called by `init-skill` automatically. |
| `init-skill [--no-install]` (CLI) | Bootstrap a fresh project. **v1.0.0**: auto-installs recorder deps (playwright + Chromium) when missing; exits 2 loudly if the dev server is unreachable. **No opt-out** — `--allow-blocked` was removed. |
| **Recorder skill CLI** (in `~/.agents/skills/recorder`) | Purpose |
| `python3 -m recorder_plugin.cli run <script.json>` | Drive a headless Chromium via Playwright per the script; emit .png / .mp4 files in `<output_dir>`. Returns a JSON status report. |
| `python3 -m recorder_plugin.cli apply-ai-responses <output-dir>` | Apply agent-written AI annotation responses via Pillow. Reads `.ai_annotation_request_*.json` + `.ai_annotation_response_*.json`, writes `<name>.ai-annotated.png`. |
| `python3 -m recorder_plugin.cli tts-synth <text> --out PATH` | edge-tts 合成一段旁白 → mp3(可选 `--voice` / `--rate`)。 |
| `python3 -m recorder_plugin.cli concat-narration <seg1> <seg2> [...] --out PATH [--gap S]` | 多段旁白 mp3 拼接,段间插入静音(默认 2.0s)。 |
| `python3 -m recorder_plugin.cli mux-audio <video> <audio> --out PATH` | 旁白音轨合并到录屏视频(自动处理时长差,产物 = 旁白长度)。 |

**v1.1.0 hard gate (machine-readable contract)**: §14 走完后,recording phase 必须额外落一份 `docs/user-manual/recording_manifest.json`(由 `python3 -m manual_helper write-recording-manifest` 生成,见 §16.11)。`validate-output.py` 在跑其他 check 之前先做 pre-flight `_check_recording_phase_actually_ran`(见 §16.12)—— 缺 manifest / dev server 不可达 / recorder exit ≠ 0 / 0 张截图 任一情况,validate-output 直接 exit 2 + 暂停 banner,**不**依赖 LLM agent 自觉跑完 §14。这一步不解决"§14 写进 prompt 但 LLM 跳过"的问题——是机器兜底。

**Removed in v2.0.0** (use the recorder CLI / Python API above instead):
`record-manual`, `record-and-replace`, `check-recorder-script` — these were
internal subcommands that pre-dated the recorder skill split. The recorder
skill has its own preflight, runner, and asset pipeline.

## 15. AI 标注阶段 (v0.2.4 — agent-mediated, provider-agnostic)

This section covers AI vision annotation. **v0.2.4 changed the architecture**: the recorder NO LONGER calls any LLM directly. Vision is fulfilled by the agent loop using whatever model the harness has access to. This means:

- **No `ANTHROPIC_API_KEY` env var** — recorder is provider-agnostic
- **No `anthropic` pip dep** — recorder's only deps are `playwright`, `Pillow`, `mcp`
- **Works in Claude Code, Codex, Cursor, Ollama** — whatever the agent's model is

### How it appears in the manual

The LLM agent writing the manual can include a special placeholder marker:

```markdown
![alt text](screenshots/01-list.png)
[AI ANNOTATE: 01-list]
```

The `[AI ANNOTATE: 01-list]` marker tells the agent: "after recording, run vision annotation on `01-list.png`". It is **optional** — the LLM only emits it when it makes sense (e.g. "auto-find the primary button" rather than "I've already hand-selected the button at coords X,Y").

### How it works at runtime

The recorder's `ai_annotate` step (v0.2.4) **does not** call any LLM. It writes a request file:

```
<output_dir>/.ai_annotation_request_<name>.json
{
  "step_name": "01-list",
  "image_path": "<output_dir>/01-list.png",
  "prompt": "Find the primary action button",
  "coord_base": 1000,
  "prompt_hint": "Return a JSON object {step_name, boxes: [{label, x, y, w, h}, ...]}. Coords normalized to 1000×1000 (the recorder will denormalize).",
  "schema_version": 1
}
```

The script's output JSON includes `pending_ai_annotations: [...]` with the request paths. The agent loop sees these and, for each one:

1. **Read the request file** (image path, prompt, schema)
2. **Read the image** (e.g. via the agent's `read_image` tool or equivalent)
3. **Call the agent's own multimodal LLM** with the image + prompt
4. **Write the response file** at `.ai_annotation_response_<name>.json`:
   ```json
   {
     "step_name": "01-list",
     "boxes": [
       {"label": "primary-btn", "x": 50, "y": 100, "w": 200, "h": 40}
     ]
   }
   ```
   (Coordinates normalized to 0-1000. The recorder will denormalize to actual pixel dimensions.)
5. **Run** `python3 -m recorder_plugin.cli apply-ai-responses <output-dir>`
   - This applies Pillow annotations, writes `<name>.ai-annotated.png`
   - Exits 0 if all applied, **1 if any skipped** (so the agent notices failures — was: 0 due to `all([]) == True` Python gotcha)
6. **Update the apply-mapping JSON** to include the annotated path:
   ```json
   {"ai-annotated-01-list": "screenshots/01-list.ai-annotated.png"}
   ```
   And call `manual_helper.apply_recording_mapping(text, mapping)` to wire it in.

### v0.3.0: mapping values can be `{path, alt}` for human-readable alt text

v0.2.x mapping values were always bare strings, and the alt text inside `![...](path)` defaulted to the mapping key (e.g. `![01-list](screenshots/01-list.png)`). That's machine-readable but **terrible for screen readers** — they read out "zero-one-dash-list" instead of a description.

v0.3.0 accepts a dict form for explicit alt text:

```json
{
  "01-list": {
    "path": "screenshots/01-list.png",
    "alt": "任务列表页（带分页器和搜索框）"
  },
  "ai-annotated-01-list": {
    "path": "screenshots/01-list.ai-annotated.png",
    "alt": "任务列表页（带 AI 红框标注「新增」按钮）"
  }
}
```

**Backward compat**: bare string values are still accepted. The alt falls back to the key. Existing v0.2.x mapping files need no migration.

You can mix string and dict values in the same mapping file.

### Why this is better than the old (v0.2.0) approach

| | v0.2.0 (old) | v0.2.4 (new) |
|---|---|---|
| API calls | recorder calls Anthropic SDK | agent calls its own model |
| Provider lock-in | Claude only | Whatever the harness provides |
| Double-billing | Yes (agent loop + recorder) | No (single LLM call, by the agent) |
| Setup | `ANTHROPIC_API_KEY` env var | None |
| pip deps | `anthropic` | (gone) |
| Harness compat | Claude Code only | Claude Code / Codex / Cursor / Ollama |

### Reference

- `recorder/recorder_plugin/vision.py` — request/response protocol implementation (no LLM calls)
- `recorder/recorder_plugin/cli.py` — `apply-ai-responses` subcommand
- `recorder/SKILL.md` — recorder-side §"ai_annotate" / "Prerequisites" / "MCP tools"
- `recorder/tests/unit/test_vision.py` — 19 tests of the protocol, no SDK mocking
- `recorder/tests/integration/test_self_test.py` — end-to-end self-test (write request → fake-agent response → apply)

### What this section explicitly does NOT do

- It does **not** automatically detect the project's dev environment.
- It does **not** generate a recording script for the LLM (only a template).
- It does **not** run the recorder itself — that's the LLM agent's job.
- It does **not** decide which steps get video vs. screenshot — the LLM agent does that.

### Why deterministic

The recording phase has 3 deterministic primitives (scan, generate-template, apply-mapping) because those are easy to get wrong in prose. The LLM-heavy work (running the recorder, picking selectors, handling login state) stays in the LLM agent loop where it belongs.

代价是结构强约束:手册位置固定,7 段(11 段 + 附录)固定,Citations 格式固定。**正是这种结构让幂等成为可能** — 不固定,每次跑都要重新推导。

## 16. 录制器已知陷阱 (recorder gotchas) — v0.3.3

执行方(LLM agent)在填 `recorder-script.json` 时**必须**避免以下陷阱,否则录像会无声 / 缺帧 / 直接失败:

### 16.1 `navigate` 必须用绝对 URL

Playwright 不解析相对 URL。`{ "action": "navigate", "url": "/" }` 会直接报 `Cannot navigate to invalid URL`。

✅ 正确:`"url": "http://127.0.0.1:3100/"`  
❌ 错误:`"url": "/"` 或 `"url": "settings"`

(v0.3.3 起 `Recorder.navigate` 会用 `urljoin` 把相对 URL 拼成绝对 URL,但脚本作者应**直接**写绝对 URL,避免依赖隐式 base。)

### 16.2 跨 video 段保持登录态(v0.3.5)

`video_stop` 必须关闭当前 page 来 flush Playwright 的 webm 流,这是 Playwright 的硬约束。关掉之后新 page 默认是 about:blank + 内存态清零 — 对于把登录态放在内存的 SPA(Vue / React useState / 各种 zustand pinia),这等于强制每次 `video_stop` 后重新登录。

**v0.3.5 修法**:`preserve_session: true`(opt-in,默认 false)。recorder 在关 page 前用 `page.evaluate` 抓 `localStorage` 全部键值,新 page 起来 + `goto` 到原 URL 后写回 + `reload` 触发 app 重新初始化读 localStorage。

**前置条件**:app 必须把登录态持久化到 `localStorage`(Vue 用 `watch(user, ...)` 写,React 用 effect 写)。如果 app 把登录态纯放内存,这个机制无效 — 修 app,不要指望 skill 兜底。

典型用法(5 段 task-flow 录屏只录 1 次登录):

```json
{
  "name": "myapp",
  "url": "http://127.0.0.1:3000",
  "reopen_page_after_video": true,
  "preserve_session": true,
  "output_dir": "...",
  "steps": [
    {"action": "navigate", "url": "http://127.0.0.1:3000/"},
    {"action": "video_start", "name": "login"},
    {"action": "type", "selector": "input[name=username]", "text": "..."},
    {"action": "type", "selector": "input[name=password]", "text": "..."},
    {"action": "click", "selector": "button[type=submit]"},
    {"action": "wait_for", "selector": ".dashboard"},
    {"action": "video_stop", "name": "login", "narration": ["..."]},
    {"action": "video_start", "name": "create-task"},
    ...                                       // 不需要重新登录
    {"action": "video_stop", "name": "create-task", "narration": ["..."]}
  ]
}
```

**两个 flag 必须一起开**:`reopen_page_after_video: true` 负责新 page `goto` 到正确 URL(否则是 about:blank,localStorage 也写不进去),`preserve_session: true` 负责写回 localStorage 并 reload。

**v0.3.3 时代的旧 workaround**(`video_start` 前手动插入 `navigate` + `type` + `click` + `wait_for` 重新登录)在 v0.3.5 已经**不必要**且**会重复登录** — 看到 5 段 video 开头都在输账号密码就是用旧脚本没升级。要不要这个新行为由 app 是否写 localStorage 决定,不是 skill 能强制的。

### 16.3 多元素 selector 直接抛 strict-mode 异常

`{ "selector": ".task-item" }` 在 3 条任务上 → Playwright `Locator.wait_for` 抛 "strict mode violation: resolved to 3 elements"。

✅ 解决:加 `:first-child` / `:nth-of-type(1)` / 用更具体路径,或用 placeholder / aria-label 等唯一属性。  
❌ 反例:依赖"页面上只有 1 个"的可数 selector,加新数据后立刻炸。

### 16.4 视频产物路径是 `<domain>/<name>/<name>.mp4`,**不是** `<domain>/<name>.mp4`

录制器为每个 `video` 创建子目录存切片 → 合并后的 `mp4` 落在子目录里:

```
screenshots/sys/login-flow/login-flow.mp4     ← 正确
screenshots/sys/login-flow.mp4                ← 错误,validator 会报 missing
```

LLM 写 `[VIDEO: title](path)` 时**必须**含子目录。同理 `narration.mp3` 在 `<domain>/<name>.narration.mp3` 顶层。

### 16.5 截图 selector 跨页面要重新加 `wait_for`

`video_start` 之后第一个交互 step 前**必须**有 `wait_for` 等待目标元素 visible。视频录制过程中 Playwright 会切换 page / 重置 z-index,新 page 上元素可能还在 DOM 但不可见。

### 16.6 `apply-mapping` 后的 path 必须是相对于 .md 文件的

Manual 在 `docs/user-manual/manual/<name>.md`,asset 在 `docs/user-manual/screenshots/<domain>/<name>.png`。
正确的相对 path:`../screenshots/<domain>/<name>.png`(从 manual/ 出发上 1 级再到 screenshots/)。

❌ 错误:`screenshots/<domain>/<name>.png`(validator 会去 `manual/screenshots/...` 找)  
❌ 错误:`<domain>/<name>.png`(validator 会去 `manual/<domain>/...` 找)  
✅ 正确:`../screenshots/<domain>/<name>.png`

### 16.7 `build-standalone` 的 `data:` URL 内联要求

`_inline_assets_to_data_urls`(v1.0.2 起)会把 image / video 文件 base64 内联进 `user-manual-standalone.html`,这样 `file://` 双击能直接打开。**前提**:manual 里的 image / video path 必须能在 disk 上找到对应文件。路径错(16.6)→ 内联失败 → 浏览器看到 `<img src=missing>` 破图。

v1.0.2 起的 inliner 三层:
1. `![alt](path)` 形式的图片
2. `<source src=...>` / `<video src=...>` / `<img src=...>` HTML 标签
3. `[VIDEO: title](path.mp4)` 形式的 markdown 引用 ← v0.3.3 修复:之前只覆盖第 2 层,template 的 `convertVideoLinksInMd` 在浏览器里才转 `<video>`,内联跑在前面,赶不上。

### 16.8 validator 算 screenshot / video 文件存在时只用 path,不查 candidate

`validate-output.py` 第 7 项严格按 `(md_dir / ref).resolve()` 检查,不会去 `_candidate_paths_for_placeholder` 那一堆 fallback。LLM 写 manual 时**必须**严格按 16.6 的 path 规则,不要写"凭直觉能用就行"的相对 path。

### 16.9 内部 anchor 必须与 heading slug 一致 (v2.3.0)

`validate-output.py` 第 15 项 `broken_anchors` 会扫所有 `](#slug)` 内部链接并与 H1-H4 heading 的真实 slug 比对,任何不匹配的链接直接 FAIL。

**为什么加**:2026-06 audit 同一项目总览分册的 4 个任务卡 anchor **全部 broken** — 标题是 `### 任务卡 1: 确认当前公司`(冒号后有空格),目录里写的是 `[任务卡 1:确认当前公司](#任务卡-1确认当前公司)`(无空格),slug 失配 → TOC 完全死链,4 张卡"相关任务"互相跳转也死。

**slug 规则**(GitHub-flavored,validator 内置):

1. `text.strip().lower()`
2. 把所有"非 word + 非 CJK 字符"压成单 `-`(中文 U+4E00-U+9FFF 保留)
3. 去掉首尾 `-`

实测示例:

| heading | slug |
|---|---|
| `### 任务卡 1: 创建合同` | `任务卡-1-创建合同` |
| `### 任务卡 1:创建合同` | `任务卡-1创建合同` |
| `## 角色与权限速查` | `角色与权限速查` |
| `### 任务卡 9: 发布 / 停用报表` | `任务卡-9-发布-停用报表` |

> LLM 写 manual 时,**先写 heading,再在目录里粘贴时,严格用同样字符**(冒号后空格、斜杠、顿号全保留)。要么用工具(`gh-slug.py` 之类)生成,要么手写一致。

### 16.10 远程 placeholder URL 必须本地化 (v2.3.0)

`validate-output.py` 第 16 项 `placeholder_url` 扫所有 image / video path(包含 markdown `![]()` / `[VIDEO:]()` 和 HTML `<img src>` / `<video src>` / `<source src>`),路径里出现 `https://placeholder.invalid/` / `https://example.com/` / `<TODO:>` / `<your-...>` 直接 FAIL。

**为什么加**:`_check_screenshot_files_exist` 第 7 项只对**本地相对路径**做 fs 检查(远程 URL 直接 skip — 因为 §16.8 文档化的"external CDN 合法"规则)。ehr 手册 6 张 `https://placeholder.invalid/screenshots/...` 远程占位 + 0 个本地 PNG,通过 7 项但实际没图。第 16 项专门覆盖这个 gap。

**LLM 写 manual 时的硬规则**:

- ✅ 本地相对:`../screenshots/sys/01-list.png`(validator 跑 fs 检查)
- ✅ 用户访问的前台 URL:`http://localhost:8088/`(白名单,不进本检查)
- ❌ 占位 URL:`https://placeholder.invalid/...` / `https://example.com/...`
- ❌ 模板变量:`<your-image-path>` / `<TODO: 截图>`

**与 §14 recording phase 的协同**:草稿评审场景可以临时把分册标 `status: draft-for-review`,但**不能用 placeholder URL 蒙混** — 第 16 项确保你即使在评审阶段也至少知道"这图是占位"。删掉占位引用 / 跑录屏补真图,二选一。

### 16.11 recording phase 必须落 `recording_manifest.json` (v1.1.0)

§14 的"recording phase 真跑了"在 v1.0.0 是写在 docstring 里的软约束,LLM agent 跳过去不会有机器可读的后果。v1.1.0 改成**硬合同**:recorder skill CLI 跑完,**必须**调 `python3 -m manual_helper write-recording-manifest <md-path> --dev-url URL ...` 落一份 `docs/user-manual/recording_manifest.json`,记录:

```json
{
  "schema_version": "1.0",
  "ran_at": "<ISO-8601 UTC>",
  "manual": "manual/<persona>.md",
  "recorder_session_id": "<recorder CLI stdout>",
  "recorder_cli_exit": 0,
  "dev_server": {
    "url": "<recorder drove against this URL>",
    "reachable": true,
    "readiness_status": "green",
    "probe_host": "<hostname>"
  },
  "assets": {
    "screenshots": ["screenshots/<domain>/01-list.png", ...],
    "videos":     ["screenshots/<domain>/demo.mp4",   ...],
    "ai_annotated": ["screenshots/<domain>/01-list.ai-annotated.png", ...]
  },
  "totals": {"screenshots": <int>, "videos": <int>, "ai_annotated": <int>}
}
```

LLM agent 的 §14 收尾流程相应扩展为 6 步(原 4 步 + 5/6):

1. `python3 -m manual_helper check-recording-readiness` — 拿到 readiness status
2. `python3 -m manual_helper scan-recording-placeholders <md>` — 占位清单
3. `python3 -m manual_helper build-recorder-template ...` — 拿到 script.json(填 selector)
4. `python3 -m recorder_plugin.cli run <script>.json` — 跑录屏
5. `python3 -m manual_helper apply-recording-mapping <md> <mapping.json>` — 替换占位
6. **`python3 -m manual_helper write-recording-manifest <md> --dev-url URL --recorder-exit 0 --screenshot <path>...`** — 落硬合同
7. `python3 -m manual_helper validate-output <md>` — 才进校验

跳过第 6 步 = 校验在 §16.12 闸 1 暂停。

**为什么要有 manifest 而不是看 `[SCREENSHOT:]` 占位符还在不在 md 里**:`apply_recording_mapping` 一跑占位符就消失了,标志物归零。manifest 是**产物侧的证据**:不光说"占位换掉了",还说"换上去的是 recorder 在 dev server reachable 时生成的"。这两件事不一样 —— LLM 完全可能先 apply_recording_mapping、然后手画 80×60 灰 PNG 假装录屏跑过。manifest 把"recorder CLI exit code + dev server readiness + 实际产物清单"绑成一份证据文件,validator 一次读完。

### 16.12 validator 硬闸:缺 manifest 直接 exit 2 (v1.1.0)

`validate-output.py` 在跑任何常规 check 之前,先做 pre-flight `_check_recording_phase_actually_ran(md_path)`:

- 在 `docs/user-manual/recording_manifest.json` 里找 manifest
- 验 `schema_version == "1.0"`
- 验 `recorder_cli_exit == 0`
- 验 `totals.screenshots > 0`
- 验 `dev_server.reachable == true`(等价 `readiness_status == "green"`)

任一不满足 → **不跑其他 check**,`validate-output` 打印暂停 banner 并 `exit 2`,即使没 `--strict`。

banner 内容(多行,故意的 —— 要让 LLM agent / 人类 reviewer 真的停下来):

```
⛔  HARD GATE FAILED: recording phase did not actually run
────────────────────────────────────────────────────────────
  file: <md-path>
  reason: <no_manifest|schema_mismatch|recorder_failed|no_screenshots|dev_server_unreachable|manifest_unreadable>
  manifest: <path> | (none)
  detail: <人类可读解释>

  What the LLM agent should have done (in order):
    1. python3 -m manual_helper check-recording-readiness
    2. python3 -m manual_helper scan-recording-placeholders <md>
    3. python3 -m manual_helper build-recorder-template ...  -> emits script.json
    4. (you fill in selectors) -> python3 -m recorder_plugin.cli run <script>.json
    5. python3 -m manual_helper apply-recording-mapping ...
    6. python3 -m manual_helper write-recording-manifest ...  -> emits the gate file
    7. python3 -m manual_helper validate-output ...  -> this script

  Stopping here. The manual's markdown is still on disk, but it
  is not a valid deliverable until §14 is run end-to-end.

  If a previous run wrote hand-drawn placeholder PNGs to
  screenshots/ (e.g. 80x60 grey stubs) to pass the file-existence
  check, delete them so a real §14 run can write real ones
  without hash collisions:  rm -rf docs/user-manual/screenshots/*

  (Escape hatch: pass --no-hard-gate to skip this gate. CI should
   never pass that flag.)
────────────────────────────────────────────────────────────
```

**escape hatch**:`--no-hard-gate` 跳过 pre-flight。仅供单元测试 / CI 维护期使用,CI 配置里**永远不要**加这个 flag。Skill 测试套件有 `RecordingPhaseActuallyRanTests` 锁住:这个 flag 只 bypass 闸 1,不 bypass §16.10 placeholder_url / §16.9 broken_anchors / placeholder_alt 等其他 check。

**为什么 §16.10 / §16.9 不够**:
- §16.10 placeholder_url 只能抓"远程 URL 还在 md 里",抓不到"手画 80×60 本地 PNG 假装录屏"(ehr 2026-06 真实场景)
- §16.9 broken_anchors 跟录屏无关
- "screenshot files exist"(v0.3.1 引入)只看文件是否在磁盘 + 尺寸 ≥ 50×50,80×60 灰图正好过

manifest 闸 = "录屏真跑" 的唯一可信信号,因为它把 dev server 联通状态、recorder CLI 退出码、产物清单绑一份带 timestamp 的机器可读合同。


### 16.13 v1.2.0 — manifest_disk_consistency + file_type_sanity (post-gate checks)

v1.1.0 的硬闸只验证 manifest 文件**自身**的内容(schema / dev server / recorder exit / screenshot count),但**没**验证 manifest 列出的图是否真的在 disk 上。ehr 2026-06 暴露了这个 gap:当时 manifest 列出 18 张图(来自 §14 跑过的那次),但 14:00→15:09 中间 disk 上 blacklist 目录被清空(可能用户 `rm -rf` 失误),`screenshots/files exist` check 在 blacklist 分册上**还能继续工作**(因为它只看 markdown 引用的图是否存在 — 但 markdown 引用的是 `[SCREENSHOT: blacklist-nav]` 占位符,validator 报"unreplaced",而不是报"manifest 撒谎")。

v1.2.0 加两个**post-gate** check 在硬闸通过后跑:

**`manifest_disk_consistency` (FAIL 模式)**: 读 manifest 列的 `assets.screenshots` 列表,每条 path 在 `docs/user-manual/screenshots/` 下必须实际存在。manifest 列了但 disk 没有 → **FAIL**(manifest 撒谎,manual 引用的图实际不存在)。disk 上有但 manifest 没列的(`_video_buffer/` 临时片段,或 hand-painted extras)→ **WARN**(不是硬失败,但用 `disk_only_count` 字段报告)。

**`file_type_sanity` (FAIL 模式)**: markdown 文件前 200 字符里如果出现 `<!DOCTYPE` / `<html` / `<head>` / `<body>` / `<svg` / `<?xml` / `{` 开头配 JSON 闭合 / `%PDF-` / 任何 NUL byte → **FAIL**。同时要求前 50 行里至少有 YAML frontmatter (`---
`) 或 H1 (`# `)。ehr 2026-06 那次 `manual/user-manual.md` 被覆盖成 viewer 的 HTML 模板(4722 行 116KB),v1.1.0 闸因为 manifest 存在所以**通过**,然后 v1.1.0 的其他 regex check 把 `<h1>` 当 markdown 标题继续跑,看上去 "校验过了" — 但实际手册是 HTML。v1.2.0 这一道把这种破坏**首行就 FAIL**。

**设计上的 trade-off**: 这两个 check 是**便宜的**防御(几十行代码),但覆盖的失败模式**只能 catch 一类破坏**(LLM/脚本把 .md 文件替换成别的东西 / manifest 和 disk 漂移)。更深层的破坏(LLM 写的"假"中文、瞎编的接口路径、错的权限矩阵)v1.2.0 抓不到 — 那些需要 §2.7.1 audience_leak + 人工 review,validator 防不住。

**CI 友好**: 两个 check 都默认开启,无 opt-out flag。manifest 撒谎或 manual.md 是 HTML 在 SKILL §16.12 的硬闸失效时(manifest 还在但内容是 stale),这两道是最后一道防线。

