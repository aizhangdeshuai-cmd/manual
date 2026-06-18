# Install recorder

## Pip dependencies

```bash
cd recorder
pip install -e ".[test]"
```

This installs: `playwright >= 1.40, < 2.0`, `Pillow >= 10.0`, `mcp >= 1.0`, `edge-tts >= 6.1, < 8.0` (for v0.3.2 narration), plus test deps `pytest`, `pytest-asyncio`.

> **v0.3.2 narration requires network access** to the Microsoft Edge TTS service (`api.msedgeservices.com`). The recorder gracefully degrades to a silent video if edge-tts fails — see recorder/SKILL.md "Narration" section. For air-gapped environments, install `piper-tts` and adapt `recorder_plugin/tts.py` to use it as the backend.

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
python3 -m recorder_plugin.cli --version       # → 0.2.4
ffmpeg -version | head -1                       # → ffmpeg 4.4+
# v0.2.4 audit round 3 (C5): the previous verify command called
# sync_playwright().__enter__() but never invoked p.chromium.launch(),
# so it passed silently on a machine where Chromium was never
# downloaded. This actually launches headless Chromium, navigates to
# about:blank, and closes — if this fails with "Executable doesn't
# exist" you forgot step 3 above.
python3 -c "
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        await page.goto('about:blank')
        await b.close()
        print('chromium ok')
asyncio.run(main())
"
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
