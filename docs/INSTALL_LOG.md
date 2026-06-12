# Install / Download Manifest

Tracks every package, binary, asset, or external resource installed or downloaded for the user-manual skill (including the recorder opt-in plugin). Use this to uninstall/remove later.

> **Why this file exists:** user granted `--dangerously-skip-permissions` on 2026-06-11 with the instruction "要下载东西，要记录好，方便我让你删除" (record everything you install so I can ask you to remove it). This is the deletion inventory.

---

## Format

Each entry: what, where, how installed, how to remove, date added.

---

## pip packages

### 2026-06-11 — recorder v0.1.0 setup (actual install state)

| Package | Version pin | Installed version | Where used | Install cmd | Remove cmd | Status |
|---|---|---|---|---|---|---|
| `playwright` | `>=1.40,<2.0` | **1.60.0** | `recorder/recorder/core.py`, `video.py` | `pip install "playwright>=1.40,<2.0"` | `pip uninstall playwright` | ✅ already installed |
| `Pillow` | `>=10.0` | **12.2.0** | `recorder/recorder/annotate.py`, `mask.py` | `pip install "Pillow>=10.0"` | `pip uninstall Pillow` | ✅ already installed |
| `mcp` | `>=1.0` | **1.27.2** | `recorder/recorder_plugin/mcp_server.py` | `pip install "mcp>=1.0"` | `pip uninstall mcp` | ✅ installed this session |
| `pyee` | (transitive) | 13.0.1 | playwright dep | (auto) | (auto) | ✅ auto |
| `greenlet` | (transitive) | 3.5.0 | playwright dep | (auto) | (auto) | ✅ auto |

### Test-only deps (installed this session)

| Package | Version pin | Installed version | Where | Install | Remove |
|---|---|---|---|---|---|
| `pytest` | `>=7.0` | **9.0.3** | `recorder/tests/` | `pip install "pytest>=7.0"` | `pip uninstall pytest` |
| `pytest-asyncio` | `>=0.21` | **1.4.0** | `recorder/tests/integration/` | `pip install "pytest-asyncio>=0.21"` | `pip uninstall pytest-asyncio` |
| `pydantic` | (transitive) | 2.13.4 | mcp dep | (auto) | (auto) |
| `pydantic-settings` | (transitive) | 2.14.1 | mcp dep | (auto) | (auto) |
| `httpx-sse` | (transitive) | 0.4.3 | mcp dep | (auto) | (auto) |
| `jsonschema` | (transitive) | 4.26.0 | mcp dep | (auto) | (auto) |
| `cryptography` | (transitive) | 48.0.1 | mcp dep | (auto) | (auto) |
| `starlette` | (transitive) | 1.3.0 | mcp dep | (auto) | (auto) ⚠️ conflicts with fastapi<0.36 (pre-existing, not ours) |
| `sse-starlette` | (transitive) | 3.4.4 | mcp dep | (auto) | (auto) |

> **Note on pydantic 2.13 + starlette 1.3 conflict with fastapi 0.109:** this is a pre-existing project dependency issue in user-manual's example db-backend (FastAPI), NOT introduced by the recorder. The recorder itself does not use FastAPI; the conflict is harmless for recorder functionality.

---

## System binaries

### macOS (current box)

| Binary | Version | Status | Install | Remove |
|---|---|---|---|---|
| `ffmpeg` | **8.1.1** | ✅ already installed | `brew install ffmpeg` | `brew uninstall ffmpeg` |
| CJK fonts | system-level | ✅ already installed (system fonts incl. STKaiti, Libian) | (system) | n/a |

> **noto-cjk skipped:** macOS has system-level CJK fonts (STKaiti, Libian, etc. found via fc-list). The recorder's `_font()` in annotate.py falls back to PIL's default font when noto is not present, so this is acceptable. Linux CI still installs `fonts-noto-cjk` per the workflow.

### Linux (apt) — for CI

| Binary / package | Why | Install | Remove |
|---|---|---|---|
| `ffmpeg` | Video slicing + boxblur | `sudo apt-get install -y ffmpeg` | `sudo apt-get remove ffmpeg` |
| `fonts-noto-cjk` | CJK rendering on minimal CI image | `sudo apt-get install -y fonts-noto-cjk` | `sudo apt-get remove fonts-noto-cjk` |
| `libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2` | Playwright Chromium system deps | `sudo apt-get install -y <list>` | `sudo apt-get remove <list>` |

---

## Browser downloads (via Playwright)

| Asset | Status | Install | Remove | Disk location |
|---|---|---|---|---|
| Chromium 148.0.7778.96 | ⏳ installing (background) | `python3 -m playwright install chromium` | `python3 -m playwright uninstall` | `/Users/zhangdanyang/Library/Caches/ms-playwright/chromium-1223/` |

> **Path note:** macOS Chromium installs to `~/Library/Caches/ms-playwright/`, NOT `~/.cache/ms-playwright/`. The latter is the Linux path. Documented here for clean uninstall.
>
> **CLI quirk:** the `playwright` binary in `$PATH` (npm-global install) silently no-ops on `install chromium` and exits 0. Use `python3 -m playwright install chromium` instead. The pip-installed Playwright is the active one.

**Note:** Firefox and WebKit are NOT installed (recorder is Chromium-only by design).

---

## External GitHub resources

| Resource | URL | Why | License | How cloned/installed | Remove |
|---|---|---|---|---|---|
| _none — WebSearch / WebFetch to github.com blocked by network policy_ | | | | | |

---

## Disk footprint (estimate, current)

- pip deps (recorder): ~30MB
- Chromium binary (after install): ~150MB
- ffmpeg (system, pre-existing): ~50MB
- Source code: ~50KB

**Total: ~230MB on disk for the recorder to function.**

---

## Uninstallation (full cleanup, current best knowledge)

To remove the recorder entirely:

```bash
# 1. Remove the plugin source
rm -rf /Users/zhangdanyang/.agents/skills/user-manual/recorder

# 2. Revert CONTRIBUTING.md and SKILL.md changes (when they exist)
cd /Users/zhangdanyang/.agents/skills/user-manual
git revert <commit-sh-that-amended-CONTRIBUTING-and-SKILL>

# 3. Remove CI workflow
rm .github/workflows/recorder-ci.yml

# 4. Uninstall pip packages added/used by recorder

# Direct deps (the ones the user explicitly asked for)
pip uninstall playwright Pillow mcp pytest pytest-asyncio

# Transitives (auto-installed by `pip install -e .[test]`)
# v0.2.4 audit round 3 (M3): use pip-autoremove to purge transitives
# in one command, rather than listing 7+ packages individually. The
# user's hard rule is "record everything so I can remove it cleanly"
# — this satisfies that rule without making the log brittle to
# version drift.
if command -v pip-autoremove >/dev/null 2>&1; then
    pip-autoremove playwright Pillow mcp pytest pytest-asyncio -y
else
    # Fallback: list the transitives we know about. Version-pinned
    # paths are intentionally not used; we uninstall by package name.
    pip uninstall -y pydantic pydantic-settings httpx-sse jsonschema \
        cryptography starlette sse-starlette typing-extensions \
        annotated-types 2>/dev/null || true
fi

# 5. Remove Chromium browser
python3 -m playwright uninstall chromium
rm -rf /Users/zhangdanyang/Library/Caches/ms-playwright
# (Linux: rm -rf ~/.cache/ms-playwright)

# 6. ffmpeg and fonts were pre-existing system packages — DO NOT remove unless user wants to
```

---

_Last updated: 2026-06-11 (mid-execution)_

