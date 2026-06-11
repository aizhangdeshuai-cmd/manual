# Install / Download Manifest

Tracks every package, binary, asset, or external resource installed or downloaded for the user-manual skill (including the recorder opt-in plugin). Use this to uninstall/remove later.

> **Why this file exists:** user granted `--dangerously-skip-permissions` on 2026-06-11 with the instruction "要下载东西，要记录好，方便我让你删除" (record everything you install so I can ask you to remove it). This is the deletion inventory.

---

## Format

Each entry: what, where, how installed, how to remove, date added.

---

## pip packages

### 2026-06-11 — recorder v0.1.0 setup (planned)

| Package | Version pin | Where used | Install cmd | Remove cmd |
|---|---|---|---|---|
| `playwright` | `>=1.40,<2.0` | `recorder/recorder/core.py`, `video.py` | `pip install "playwright>=1.40,<2.0"` | `pip uninstall playwright` |
| `Pillow` | `>=10.0` | `recorder/recorder/annotate.py`, `mask.py` | `pip install "Pillow>=10.0"` | `pip uninstall Pillow` |
| `mcp` | `>=1.0` | `recorder/recorder/mcp_server.py` | `pip install "mcp>=1.0"` | `pip uninstall mcp` |

### Test-only deps (optional `[test]` extra)

| Package | Version pin | Where | Install | Remove |
|---|---|---|---|---|
| `pytest` | `>=7.0` | `recorder/tests/` | `pip install "pytest>=7.0"` | `pip uninstall pytest` |
| `pytest-asyncio` | `>=0.21` | `recorder/tests/integration/` | `pip install "pytest-asyncio>=0.21"` | `pip uninstall pytest-asyncio` |

---

## System binaries

### macOS (via Homebrew)

| Binary | Why | Install | Remove |
|---|---|---|---|
| `ffmpeg` | Video slicing + boxblur mask | `brew install ffmpeg` | `brew uninstall ffmpeg` |
| `font-noto-sans-cjk` (cask) | Fixture fonts (CJK rendering) | `brew install --cask font-noto-sans-cjk` | `brew uninstall --cask font-noto-sans-cjk` |

### Linux (apt)

| Binary / package | Why | Install | Remove |
|---|---|---|---|
| `ffmpeg` | Video slicing + boxblur | `sudo apt-get install -y ffmpeg` | `sudo apt-get remove ffmpeg` |
| `fonts-noto-cjk` | CJK rendering | `sudo apt-get install -y fonts-noto-cjk` | `sudo apt-get remove fonts-noto-cjk` |
| `libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2` | Playwright Chromium system deps | `sudo apt-get install -y <list>` | `sudo apt-get remove <list>` |

---

## Browser downloads (via Playwright)

| Asset | Why | Install | Remove | Disk |
|---|---|---|---|---|
| Chromium (~150MB) | Headless browser for recorder | `playwright install chromium` | `playwright uninstall` | `~/.cache/ms-playwright/chromium-*` |

**Note:** Firefox and WebKit are NOT installed (recorder is Chromium-only by design).

---

## External GitHub resources

(Populated as discovered.)

| Resource | URL | Why | License | How cloned/installed | Remove |
|---|---|---|---|---|---|
| _none yet_ | | | | | |

---

## Disk footprint (estimate)

- pip deps: ~30MB (playwright is mostly the browser binary, not Python)
- Chromium binary: ~150MB
- CJK fonts: ~50MB
- ffmpeg: ~50MB
- Source code: ~2MB

**Total: ~280MB on disk for the recorder to function.**

---

## Uninstallation (full cleanup)

To remove the recorder entirely:

```bash
# 1. Remove the plugin source
rm -rf /Users/zhangdanyang/.agents/skills/user-manual/recorder

# 2. Revert CONTRIBUTING.md and SKILL.md changes
cd /Users/zhangdanyang/.agents/skills/user-manual
git revert <commit-sh-that-amended-CONTRIBUTING-and-SKILL>
# or:
git checkout HEAD~N -- CONTRIBUTING.md SKILL.md   # if you remember which commit

# 3. Remove CI workflow
rm .github/workflows/recorder-ci.yml

# 4. Uninstall pip packages
pip uninstall playwright Pillow mcp pytest pytest-asyncio

# 5. Remove system binaries
# macOS:
brew uninstall ffmpeg
brew uninstall --cask font-noto-sans-cjk
# Linux:
sudo apt-get remove ffmpeg fonts-noto-cjk libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2

# 6. Remove Playwright browser
playwright uninstall
rm -rf ~/.cache/ms-playwright
```

---

_Last updated: 2026-06-11 (manifest created pre-execution)_
