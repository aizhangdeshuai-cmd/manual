# Recorder Sub-Skill — Design Spec

**Status:** Draft v1 (awaiting user review)
**Date:** 2026-06-11
**Owner:** user-manual skill maintainer
**Repo:** `aizhangdeshuai-cmd/manual`
**Path:** `recorder/` (opt-in plugin, NOT core sub-skill)

---

## 1. Context

The `user-manual` skill produces task-card-based business-user manuals (Feishu/DingTalk style). SKILL.md §1, §2.2, and §2.6 require every task card to have screenshots, and key steps to have videos. Currently these assets are produced **manually** by a human running their screen recorder while clicking through the UI.

This is the bottleneck that blocks shipping user manuals at scale. Manual recording also has consistency issues: human screenshots drift in framing, captions are missed, and updates after UI changes require re-recording by hand.

**Goal:** An LLM agent invoking the `user-manual` skill should be able to drive the UI itself, capture screenshots and videos, annotate them, and emit assets ready to drop into task cards — with zero human intervention.

## 2. Goals (v1)

- LLM agent reads the recorder's `SKILL.md` and produces all required assets for a user manual task card without human action.
- Asset output names follow user-manual's existing convention: `<domain>-<task>-<element>.png` (kebab-case lowercase), aligning with the dryrun example `dict-add-type-btn.png`.
- Idempotent: re-running a recorder script for the same target skips steps whose outputs are still valid; only changed inputs trigger re-recording.
- Recorder is invoked in two ways: (a) **declarative JSON script** (saved, replayable, CI-runnable) and (b) **MCP tool calls** (imperative, agent-driven). Both share the same underlying register.
- Recorder handles the hard cases: login (incl. TOTP 2FA), iframe/Shadow DOM selectors, dynamic content / SPA hydration waits, retry on stale selectors, optional privacy masking.
- Recorder integrates with user-manual's existing `upload-asset` subcommand for S3 push, so video files do not bloat the git repo.

## 3. Non-Goals (v1 explicit)

| Out of scope for v1 | Why |
|---|---|
| Desktop screen recording (macOS/Windows GUI) | No CDP, requires platform-specific drivers; defer to v2 |
| iOS / Android screen recording | Different infra; user-manual v1 is Web-first per the agent reviews |
| Multi-user collaborative recording (multiple LLMs recording in parallel against one app) | Locking / conflict semantics not designed; v2 |
| ffmpeg-based video **concatenation** of N clips into one MP4 | 10-second slices are already independently playable; the manifest can list N video URLs. Concat is "for nicer docs", not "for the skill to work" — cut from MVP |
| Cross-browser abstraction (Firefox, WebKit) | Playwright is the only driver; recorder locks to **Chromium-only**. This is a deliberate scope choice, not a "we'll abstract later" promise |
| AI-driven screenshot annotation (e.g. LLM vision models drawing red boxes) | Annotations come from declared selectors and labels in the script. AI vision annotation is v2 territory |
| `custom_js` arbitrary JavaScript in `wait_for` | Security: any untrusted script in a JSON file is a remote code execution surface. v1 ships a **whitelist** of predicates only |

## 4. Architecture: Opt-In Plugin (Not Sub-Skill)

**Why this matters:** `CONTRIBUTING.md` §"Style constraints" states the user-manual skill is `stdlib only, zero pip install, any Python 3.10+ environment`. Adding `playwright` (~1.5GB Chromium download), `Pillow`, `mcp SDK`, plus the system binary `ffmpeg`, **breaks this core promise** if treated as a core sub-skill.

**Decision:** `recorder/` is an **opt-in plugin** living at the repository root, not a core sub-skill under `scripts/`. It is installed and run explicitly; the main user-manual skill works without it. The main `CONTRIBUTING.md` stdlib promise remains intact.

```
aizhangdeshuai-cmd/manual                       # single repo, single release tag
├── SKILL.md                                    # user-manual orchestrator (existing)
├── CONTRIBUTING.md                             # amended with §"Opt-in plugins" section
├── scripts/                                    # core: stdlib only (unchanged)
│   ├── manual_helper.py
│   ├── extract-*.py
│   ├── validate-output.py
│   └── tests/                                  # 33 stdlib unittest tests
├── recorder/                                   # NEW — opt-in plugin
│   ├── SKILL.md                                # recorder's own frontmatter + agent-facing doc
│   ├── README.md                               # human install + usage
│   ├── INSTALL.md                              # explicit dep list + install commands
│   ├── VERSION                                 # text file, starts at "0.1.0"
│   ├── CHANGELOG.md
│   ├── pyproject.toml                          # declares playwright, Pillow, mcp deps
│   ├── recorder/
│   │   ├── __init__.py
│   │   ├── core.py                             # Playwright session: navigate/click/type/wait/screenshot
│   │   ├── script.py                           # declarative JSON script runner
│   │   ├── mcp_server.py                       # MCP tool register (shared with cli.py)
│   │   ├── cli.py                              # CLI entry; shares register() with mcp_server.py
│   │   ├── annotate.py                         # PIL-based annotation (red box, arrow, number, highlight)
│   │   ├── video.py                            # Playwright video recording + 10s slicing + state-tracking
│   │   ├── mask.py                             # ffmpeg boxblur filter invocation (NOT PIL video frames)
│   │   ├── retry.py                            # selector retry policy
│   │   ├── state.py                            # idempotency state via atomic rename + flock
│   │   ├── login.py                            # login step + stdlib TOTP
│   │   └── wait.py                             # wait_for strategy whitelist
│   ├── tests/
│   │   ├── fixtures/static_site/               # DAY-1 deliverable: index + 2 sub-pages + login + iframe + shadow DOM
│   │   │   ├── index.html
│   │   │   ├── page-a.html
│   │   │   ├── page-b.html
│   │   │   ├── login.html
│   │   │   └── styles.css
│   │   ├── unit/                               # mock Playwright interface; test logic
│   │   │   ├── test_script.py
│   │   │   ├── test_annotate.py
│   │   │   ├── test_retry.py
│   │   │   ├── test_state.py
│   │   │   ├── test_login.py
│   │   │   ├── test_wait.py
│   │   │   └── test_mask.py
│   │   ├── integration/                        # runs against fixtures/static_site via headless Chromium
│   │   │   ├── test_end_to_end.py
│   │   │   └── test_video.py
│   │   └── conftest.py
│   ├── examples/
│   │   ├── sample_script.json                  # full declarative script example
│   │   └── dryrun-recorder.md                  # end-to-end demonstration output
│   └── scripts/
│       └── run.sh                              # convenience wrapper
├── .github/workflows/
│   ├── test.yml                                # existing: core skill CI (stdlib)
│   └── recorder-ci.yml                         # NEW: recorder CI (Ubuntu, installs ffmpeg + Playwright deps)
└── docs/
    └── superpowers/specs/                      # this directory
        └── 2026-06-11-recorder-skill-design.md
```

**CONTRIBUTING.md amendment** (text to be added):

> **Opt-in plugins.** A top-level directory (e.g. `recorder/`) may declare its own dependencies in its own `pyproject.toml` and ship its own `.github/workflows/<name>-ci.yml`. The plugin's CI runs in a separate job and is opt-in: maintainers may disable it for a release if the plugin is broken. The plugin's `INSTALL.md` must list every pip package and system binary it requires. The plugin's `SKILL.md` frontmatter must declare it as `requires: [recorder]` so the parent user-manual skill knows it is optional.

## 5. Component Design

### 5.1 `core.py` — Playwright session

The single browser session. Owns the Playwright `BrowserContext` (cookies, local storage, viewport). All other modules call into `core.py`; no other module imports Playwright directly.

```python
# Public surface (excerpt)
class Recorder:
    def __init__(self, viewport: Viewport, headless: bool, record_video: bool, video_dir: Path): ...
    async def navigate(self, url: str, wait_for: WaitSpec | None) -> None: ...
    async def click(self, selector: str, retry: RetryPolicy = "auto") -> None: ...
    async def type(self, selector: str, text: str, press_enter: bool = False) -> None: ...
    async def wait_for(self, spec: WaitSpec) -> None: ...
    async def screenshot(self, name: str, annotate: list[Annotation] | None, mask: list[MaskRegion] | None) -> AssetRef: ...
    async def video_start(self, name: str) -> None: ...
    async def video_stop(self, name: str) -> AssetRef: ...
    async def close(self) -> None: ...
```

Browser is launched with the flags: `--no-sandbox --disable-notifications --disable-popup-blocking --no-first-run --disable-features=Translate,InfiniteSessionRestore`. (GitHub Actions runners require `--no-sandbox`. The other three prevent OS-level popups from corrupting recordings.)

### 5.2 `script.py` — Declarative JSON runner

Parses a JSON file, walks the `steps` array, dispatches each step to the corresponding `Recorder` method. Validates the script against a JSON schema before execution; rejects unknown step types at parse time, not mid-recording.

Step types: `navigate`, `click`, `type`, `wait_for`, `screenshot`, `mask`, `login`, `video_start`, `video_stop`, `set_viewport`, `set_retry_policy`. Note: `screenshot` accepts inline `annotate` and `mask` parameters; there are no separate `annotate` or `mask` step types.

### 5.3 `mcp_server.py` + `cli.py` — Shared register

Both modules call `register_tools(registry)` which populates a `Tool` registry from a single source of truth. CLI is a thin `argparse`-free wrapper that parses `sys.argv` and invokes the same handlers. The MCP server exposes those handlers over the MCP protocol. **One set of handlers, two entry points.**

### 5.4 `annotate.py` — Image annotation

Pillow-based. Produces annotated copies of screenshots; original PNGs are kept untouched. Supported shapes:

| Shape | Args | Renders |
|---|---|---|
| `box` | `selector`, `label` | 3px red rectangle around element bbox + label badge top-left |
| `arrow` | `from_xy`, `to_xy`, `label` | Red arrow + label |
| `number` | `selector`, `n` | Filled red circle with white digit `n`, centered on element |
| `highlight` | `selector`, `label` | Yellow 30%-opacity fill + label |
| `composite` | list of above | Multiple annotations on one image |

### 5.5 `video.py` — Recording with 10-second slices

Playwright records a continuous webm stream; recorder slices it into 10-second chunks via `ffmpeg -ss / -t / -c copy`. Each chunk is `ffprobe`-validated (must be playable, duration ≥ 9s for a 10s slice) before being added to the state file. **Codec params are locked at recording start** (`-r 30 -pix_fmt yuv420p -g 60 -b:v 2M`) so chunks can be cross-played and (in v2) concatenated without re-encode.

**Cross-process resume:** the state file records the last fully validated chunk. A crashed recording can be resumed by reading the state, slicing the partial stream up to the last good chunk, and starting fresh from there. v1's resume is **same-process only**; cross-process resume is documented as a v2 follow-up.

### 5.6 `mask.py` — Privacy masking

Two implementations, one for screenshots, one for video.

- **Screenshots:** Pillow `ImageFilter.GaussianBlur` on the region. Output: original PNG + masked PNG (both kept).
- **Video:** ffmpeg `boxblur` filter applied during chunk slicing. The `boxblur` filter is GPU-friendly and ~50x faster than decoding every frame to Pillow.

Default: masking is **opt-in** (no regions declared → no masking). Mask regions are declared inline on a `screenshot` step:

```json
{"action": "screenshot", "name": "private-form",
 "annotate": [{"shape": "box", "selector": "button", "label": "保存"}],
 "mask": [{"x": 100, "y": 200, "w": 300, "h": 40, "blur_pixels": 12}]}
```

This keeps mask regions semantically tied to the screenshot they belong to, avoiding the contradiction of a separate `mask` step whose output file is ambiguous.

### 5.7 `retry.py` — Selector retry policy

Order: `testid / aria-label` → `text` → `role` → `partial text`. Each tier has a configurable max-attempt budget (default: 2 per tier). Failure after all tiers: step is marked failed, the error recorded in the output JSON `errors[]`, the script continues (configurable `fail_fast: true` to abort instead).

Rationale: agents in the first review proposed `role → partial text` first, but real-world enterprise apps have low ARIA coverage. `testid/aria-label` is the most stable identifier when present; falling back to text is the second-best signal.

### 5.8 `state.py` — Idempotency state

`.recorder_state.json` (gitignored, lives in `output_dir`):

```json
{
  "script_name": "create-employee-account",
  "content_hash": "sha256:...",
  "steps": {
    "3": {"input_hash": "sha256:...", "output_path": "...", "mtime": "2026-06-11T...", "validated": true}
  }
}
```

`input_hash` = `sha256(step_definition || script_content_hash)`. Re-run skips a step if its `output_path` exists on disk, its mtime is unchanged, and its `input_hash` matches. **No chained "upstream change invalidates downstream" semantics in v1** — those were considered and rejected as over-engineering; full re-run if script content changes.

Concurrency: writes go through a `flock`-protected atomic rename (`write to .tmp`, `os.replace`).

### 5.9 `login.py` — Login step + TOTP

```json
{
  "action": "login",
  "url": "https://app.example.com/login",
  "user_field": "input[name='email']",
  "user": "$AUTH_USER",
  "pass_field": "input[name='password']",
  "pass": "$AUTH_PASS",
  "submit_selector": "button[type='submit']",
  "totp_secret": "$AUTH_TOTP_SECRET",
  "totp_drift_seconds": 30
}
```

TOTP is computed in stdlib (`hmac` + `base32` + `struct`), no `pyotp` dep. `totp_drift_seconds` handles the case where a recording crosses a 30-second TOTP window: the script tries the current code first, and if the server rejects, retries with the previous and next windows.

Credentials are read from environment variables by default; an explicit `auth.json` file path is also supported. Both are gitignored. The recorder never logs credentials.

### 5.10 `wait.py` — Whitelisted wait predicates

`wait_for` strategies (v1 whitelist):

| Strategy | Args | Predicate |
|---|---|---|
| `selector` | `selector`, `state: visible\|hidden\|attached` | Playwright `locator.wait_for()` |
| `text` | `text`, `exact: bool` | `expect(locator).to_have_text()` |
| `networkidle` | (none) | `page.wait_for_load_state("networkidle")` |
| `timeout` | `ms` | Hard sleep, last-resort fallback |

`custom_js` is **not** supported in v1. The agent review surfaced this as a security risk: a JSON script with arbitrary JS is equivalent to remote code execution. If v2 needs custom predicates, the v1 whitelist will be extended with named, audited predicates only (e.g., `dom_contains`, `cookie_equals`).

## 6. I/O Contracts

### 6.1 Declarative script (JSON)

```json
{
  "name": "create-employee-account",
  "url": "https://app.example.com",
  "viewport": {"width": 1440, "height": 900, "device_scale": 1, "is_mobile": false},
  "output_dir": "docs/user-manual/screenshots/sys",
  "auth_env": ["AUTH_USER", "AUTH_PASS"],
  "retry_policy": "auto",
  "fail_fast": false,
  "steps": [
    {"action": "set_viewport", "viewport": {"width": 1440, "height": 900}},
    {"action": "navigate", "url": "/system/users"},
    {"action": "wait_for", "strategy": "networkidle"},
    {"action": "screenshot", "name": "01-list",
     "annotate": [{"shape": "box", "selector": "button:has-text('新增用户')", "label": "点这个按钮"}]},
    {"action": "click", "selector": "button:has-text('新增用户')"},
    {"action": "login", "url": "https://app.example.com/login", "user_field": "input[name='email']",
     "user": "$AUTH_USER", "pass_field": "input[name='password']", "pass": "$AUTH_PASS",
     "submit_selector": "button[type='submit']", "totp_secret": "$AUTH_TOTP_SECRET"},
    {"action": "wait_for", "strategy": "selector", "selector": "form#user-form", "state": "visible"},
    {"action": "video_start", "name": "create-flow"},
    {"action": "screenshot", "name": "02-form",
     "annotate": [
       {"shape": "box", "selector": "input[name='name']", "label": "填姓名"},
       {"shape": "box", "selector": "input[name='empId']", "label": "填工号"}
     ]},
    {"action": "type", "selector": "input[name='name']", "text": "张三"},
    {"action": "type", "selector": "input[name='empId']", "text": "E001"},
    {"action": "click", "selector": "button:has-text('保存')"},
    {"action": "wait_for", "strategy": "text", "text": "张三"},
    {"action": "screenshot", "name": "03-saved",
     "annotate": [{"shape": "highlight", "selector": "td:has-text('张三')", "label": "看到新员工"}]},
    {"action": "video_stop", "name": "create-flow"}
  ]
}
```

### 6.2 Output (JSON to stdout)

```json
{
  "script": "create-employee-account",
  "status": "ok",
  "started_at": "2026-06-11T19:00:00Z",
  "completed_at": "2026-06-11T19:02:14Z",
  "duration_s": 134,
  "screenshots": [
    {"step": 3, "name": "01-list", "path": "docs/user-manual/screenshots/sys/01-list.png",
     "width": 1440, "height": 900, "annotated": true, "selector_used": "button:has-text('新增用户')",
     "caption_hint": "点这个按钮", "retries": 0}
  ],
  "videos": [
    {"name": "create-flow", "path": "docs/user-manual/screenshots/sys/create-flow/create-flow.0000.webm",
     "duration_s": 10, "size_bytes": 1843212, "validated": true, "slice_index": 0}
  ],
  "skipped_steps": [],
  "warnings": [],
  "errors": [],
  "upload_hints": [
    {"asset": "docs/user-manual/screenshots/sys/01-list.png",
     "upload_command": "python3 scripts/manual_helper.py upload-asset sys 01-list.png --caption '点这个按钮'",
     "note": "video files are sliced into 10s chunks; upload each or transcode first"}
  ]
}
```

### 6.3 MCP tools

| Tool | Args | Returns |
|---|---|---|
| `recorder_navigate` | `url`, `wait_for?` | `{ok, status}` |
| `recorder_click` | `selector`, `retry?` | `{ok, retries}` |
| `recorder_type` | `selector`, `text`, `press_enter?` | `{ok}` |
| `recorder_wait_for` | `strategy`, `...` | `{ok, elapsed_ms}` |
| `recorder_screenshot` | `name`, `annotate?`, `mask?` | `AssetRef` |
| `recorder_video_start` | `name` | `{ok, slice_path}` |
| `recorder_video_stop` | `name` | `{ok, validated_slices: int}` |
| `recorder_run_script` | `path` | full output JSON (shape 6.2) |

## 7. Critical Mechanisms (Baked-In Fixes)

| Risk from review | Mitigation in v1 |
|---|---|
| chrome_browser MCP cannot record video | Recorder uses Playwright only. Single browser session. |
| Two browser sessions → login broken | Single Playwright session for both screenshot and video. |
| CONTRIBUTING stdlib promise | Recorder is opt-in plugin, separate pyproject, separate CI job. |
| `sample_flow.html` doesn't exist | `tests/fixtures/static_site/` is a day-1 deliverable. |
| CI apt/Playwright install is fragile | CI workflow is a day-1 deliverable: hello-world runs first, features added after env is green. |
| ffmpeg concat codec mismatch | ffmpeg concat removed from MVP. Slices are independently playable. |
| Pillow CPU-bound on video frames | Mask uses ffmpeg `boxblur` filter for video. |
| TOTP window drift | `totp_drift_seconds` field, retry on previous/next windows. |
| `custom_js` security hole | Removed; whitelisted predicates only. |
| State corruption under concurrency | `flock` + atomic rename. |
| Partial video file on crash | Slicing + per-slice `ffprobe` validation + state records validated slices. |
| Video assertion in CI is brittle | CI asserts: `ffprobe parses + frame_count ≥ expected * 0.9`. **Not** pixel diff. |
| Annotation drift in style | Output naming forced to `<domain>-<task>-<element>.png` kebab-case. |
| Cross-platform not promised | Recorder ships for macOS and Linux only. Windows is v2. |

## 8. Integration with user-manual skill

### 8.1 user-manual `SKILL.md` amendments

- **Description (frontmatter)**: append "When the target project has the `recorder` plugin installed, assets are produced automatically by an LLM agent invoking the recorder's MCP tools or declarative scripts (see `recorder/SKILL.md`)."
- **§13 (new)**: "Automated recording via the `recorder` opt-in plugin. The recorder is **not** part of the core user-manual skill. To enable, install the plugin per `recorder/INSTALL.md` and ensure the project's LLM agent can invoke the recorder's MCP tools. The recorder produces files matching the `<domain>-<task>-<element>.png` naming convention in §1 above; these files drop directly into task card `[SCREENSHOT: ...]` slots. For video, the recorder emits a list of 10-second slices; the task card references the manifest."

### 8.2 Asset handoff

The user-manual skill already has a `upload-asset` subcommand (`scripts/manual_helper.py upload-asset`) that pushes a file to S3/MinIO. The recorder's output JSON includes `upload_hints[]` with the exact command line to invoke. The LLM agent (or CI) is expected to run those commands; the recorder does not push to S3 itself (separation of concerns: recorder produces assets, user-manual skill handles distribution).

## 9. Versioning & Release

- `recorder/VERSION` is a text file containing a SemVer string (e.g. `0.1.0`). Independent of the user-manual skill's versioning, which uses the inline `user-manual-dashboard-version: N` integer in the HTML template.
- The repository is released under a single git tag (e.g. `manual-v0.3.0`) that covers both. The `recorder/CHANGELOG.md` and the main `CHANGELOG.md` are both updated on each release, regardless of which sub-system changed.
- A release with only recorder changes: tag the same repo, bump `recorder/VERSION` and `recorder/CHANGELOG.md`, leave the user-manual template version untouched. The `recorder-ci.yml` job runs in addition to the core CI.
- A release with only user-manual changes: bump the inline template version, update main CHANGELOG, do not touch recorder files. The `recorder-ci.yml` job still runs (smoke check that the plugin's interface hasn't broken).

## 10. Testing Strategy

### 10.1 Unit tests (`tests/unit/`)

- Pure logic, mock the Playwright interface. Test step parsing, retry policy ordering, state file atomicity, TOTP math, mask region math, annotation shape rendering, wait strategy dispatch.
- Goal: catch logic regressions without needing a browser. ~70% of test count.

### 10.2 Integration tests (`tests/integration/`)

- Run against `tests/fixtures/static_site/` via headless Chromium (Playwright launches it).
- Test fixtures include: index, two sub-pages, login form, an iframe, a shadow-DOM element. Together they exercise: navigation, click, type, login, iframe selector, shadow DOM selector, annotation rendering, video recording start/stop, video slice validation, state re-run skipping.
- Goal: catch real browser/protocol issues. ~20% of test count.

### 10.3 Smoke / CI

- The CI workflow's first run is **a hello-world Playwright launch** before any feature tests. If the hello-world cannot start in CI, the env-install work blocks all subsequent test development.
- The CI workflow installs `ffmpeg` (apt: `ffmpeg`), `noto-cjk` (for fixture fonts), and Playwright system deps (`playwright install-deps chromium`).
- Video tests in CI assert `ffprobe` parseability and frame count only — **no visual diff**, no pixel match, no LLM vision comparison.

### 10.4 Cross-platform scope

- **Supported:** macOS, Linux (Ubuntu LTS).
- **Not supported:** Windows. Documented in `INSTALL.md`.
- CI runs on `ubuntu-latest`. Manual macOS verification is part of the release checklist.

## 11. Acceptance Criteria

The recorder v1 is shippable when:

1. `recorder/INSTALL.md` install instructions work on a fresh macOS dev box and on `ubuntu-latest` GitHub Actions.
2. The recorder's own CI workflow runs green (`.github/workflows/recorder-ci.yml`).
3. The example `examples/sample_script.json` runs end-to-end against `tests/fixtures/static_site/`, producing both annotated screenshots and a validated 10-second video slice.
4. Re-running the same script skips all steps whose outputs exist and are still valid; the output JSON's `skipped_steps[]` reflects this.
5. A script with a deliberately wrong selector fails gracefully: the error appears in `errors[]`, the script continues, and the output is still valid JSON.
6. A script that logs in (with TOTP) against the fixture login form completes and the post-login screenshot reflects the authenticated state.
7. `python3 recorder/recorder/cli.py --help` and `--version` work; the CLI does not require Playwright to be installed for `--help` to succeed.
8. The `recorder/recorder/mcp_server.py` registers all 8 tools listed in §6.3; the MCP server starts and accepts a tool-list query when Playwright is installed.
9. `CONTRIBUTING.md` is amended per §4 above.
10. `user-manual/SKILL.md` description and §13 are updated per §8.1.
11. The recorder's output for `examples/sample_script.json` matches the shape documented in §6.2 (verified by a test that loads the JSON and asserts the schema).

## 12. Open Risks

- **Playwright version drift:** Playwright's API has breaking changes between minor versions. The recorder's `pyproject.toml` pins a minor range (e.g. `>=1.40,<2.0`). Update cadence: every minor release of recorder re-tests against the latest Playwright.
- **ffmpeg CLI surface varies:** macOS (`brew install ffmpeg`) and Ubuntu (`apt install ffmpeg`) ship different ffmpeg versions. The recorder uses only stable flags from ffmpeg 4.4+ (released 2021). Documented in `INSTALL.md`.
- **TOTP replay attacks:** the recorder's TOTP math is single-use per session. If a recording is replayed, the TOTP code is stale. Documented: scripts with TOTP are single-use; re-recording requires a fresh secret rotation or a script edit.
- **Selector brittleness in test fixtures:** fixtures are hand-written HTML; if they break, integration tests break. Mitigated by treating fixtures as code: any change to `tests/fixtures/static_site/` requires a corresponding test update.
- **File size of videos in CI artifacts:** GitHub Actions caps artifact upload at 2GB per workflow run. Recorder tests upload only the smallest valid slice (a single 10s chunk) to keep CI artifacts small.

## 13. Out of Scope (Acknowledged, Deferred)

- Desktop screen recording (macOS/Windows GUI)
- iOS / Android device recording
- Multi-user concurrent recording sessions
- ffmpeg video concatenation into one MP4 (slices are independently playable; manifest lists N URLs)
- AI vision-based annotation
- Windows support
- Cross-process video resume (same-process only in v1)
- Chained input-hash invalidation in state (full re-run on script content change is the v1 behavior)
- Custom JavaScript predicates in `wait_for`

---

**Reviewer:** please read end-to-end and flag:
- Any wording that is ambiguous or could be read two ways
- Any acceptance criterion that cannot be objectively verified
- Any open risk that should actually block v1 shipping
