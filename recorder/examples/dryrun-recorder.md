# Recorder Dryrun — Creating a User Account

This dryrun demonstrates the recorder's output. It walks through one task card with annotated screenshot references, showing what assets the recorder produces and how they slot into a task card.

The full declarative script that produces these assets is at `examples/sample_script.json`.

## Task Card: 创建新员工账号

> ⚠️ **操作前必看**
> - 你需要是"系统管理员"角色
> - 员工姓名、工号、手机号 3 个字段必填
> - 创建后默认密码 = 工号后 6 位,首次登录强制改密

### 步骤

1. 打开系统管理 → 用户管理
2. 点「新增用户」按钮 ![红框:点这个按钮](docs/user-manual/screenshots/sys/01-list.annotated.png)
3. 在登录态下,系统显示员工创建表单 ![红框:填姓名](docs/user-manual/screenshots/sys/02-form.annotated.png)
4. 填姓名 "张三"、工号 "E001"
5. 点「保存」
6. 看到列表里出现新员工 ![highlight:看到新员工](docs/user-manual/screenshots/sys/03-saved.annotated.png)

### 录屏

完整流程录屏(10秒切片,位于同目录下):
- `[VIDEO: create-flow.0000.webm]`
- `[VIDEO: create-flow.0001.webm]`
- `[VIDEO: create-flow.0002.webm]`

## Recorder Output JSON (excerpt)

```json
{
  "script": "create-employee-account",
  "status": "ok",
  "duration_s": 134,
  "screenshots": [
    {"step": 3, "name": "01-list", "path": "docs/user-manual/screenshots/sys/01-list.annotated.png",
     "annotated": true, "caption_hint": "点这个按钮"},
    {"step": 9, "name": "02-form", "path": "docs/user-manual/screenshots/sys/02-form.annotated.png",
     "annotated": true, "caption_hint": "填姓名"},
    {"step": 15, "name": "03-saved", "path": "docs/user-manual/screenshots/sys/03-saved.annotated.png",
     "annotated": true, "caption_hint": "看到新员工"}
  ],
  "videos": [
    {"step": 16, "name": "create-flow",
     "path": "docs/user-manual/screenshots/sys/create-flow/create-flow.0000.webm",
     "duration_s": 10, "slice_index": 0, "validated": true}
  ],
  "errors": []
}
```
