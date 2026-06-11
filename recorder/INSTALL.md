# Install recorder

## Pip dependencies

```bash
cd recorder
pip install -e ".[test]"
```

This installs: `playwright >= 1.40, < 2.0`, `Pillow >= 10.0`, `mcp >= 1.0`, plus test deps `pytest`, `pytest-asyncio`.

## System binaries

### macOS

```bash
brew install ffmpeg
# CJK fonts are system-installed on macOS; no extra install needed
```

### Linux (Ubuntu LTS)

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg fonts-noto-cjk libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
```

The `lib*` packages are Playwright's system dependencies for headless Chromium. `playwright install --with-deps chromium` will install them automatically on most systems, but listing them explicitly avoids surprises on minimal CI images.

## Playwright browser

```bash
# Use `python3 -m playwright` (the pip-installed one) — the npm-global `playwright`
# binary in $PATH silently no-ops on `install chromium` on macOS.
python3 -m playwright install chromium
```

Do not install Firefox or WebKit — recorder v1 is Chromium-only.

## Verify the install

```bash
python3 -m recorder_plugin.cli --version       # → 0.1.0
ffmpeg -version | head -1                       # → ffmpeg 4.4+
python3 -c "from playwright.sync_api import sync_playwright; sync_playwright().__enter__()"  # no error
```

## Run the bundled fixture

```bash
cd recorder
pytest tests/ -v
```

## Run the example script

```bash
cd recorder
python3 -m recorder_plugin.cli run examples/sample_script.json
```

(Will fail without a real target URL; the script uses `https://app.example.com` as a placeholder. Replace with your project's URL.)
