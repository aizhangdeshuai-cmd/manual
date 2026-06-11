# Recorder Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `recorder/` opt-in plugin so the user-manual skill can produce task-card screenshots and videos automatically, with no human in the loop.

**Architecture:** Single Playwright browser session drives both screenshots and video. Declarative JSON scripts and imperative MCP tools share one tool register. Files outside the git tree (videos, screenshots) follow the existing `<domain>-<task>-<element>.png` naming. State for idempotency uses atomic file rename + flock. TOTP uses stdlib only.

**Tech Stack:** Python 3.10+, Playwright (Python), Pillow, mcp (Python SDK), stdlib `hmac`/`struct`/`base32` for TOTP, system `ffmpeg` for video slicing and boxblur.

**Spec:** `docs/superpowers/specs/2026-06-11-recorder-skill-design.md`

---

## Why This Order

The second agent review identified two **critical-path fixes** to the original 1-10 ordering:

1. **CI environment must be green before any feature work.** Otherwise Day 4 discovers the CI image can't install Playwright deps, and all prior work re-verifies in a different env.
2. **Login + TOTP must come before video.** Because Playwright single-session is the design (not two browser sessions), the login state machinery affects every step type. Building video first and discovering the login needs cookie sync would mean re-recording all demo videos.

So the order is: **fixture + CI → core → small utilities (state/retry/wait/annotate) → login → mask + video → script runner → MCP/CLI → docs → acceptance verification.**

---

## File Structure

The spec §4 defines the layout. This plan creates those files in the order shown below. Files marked **(create)** are new. Files marked **(amend)** are existing files modified by this plan.

| Path | Created in Task | Purpose |
|---|---|---|
| `recorder/` | 1 | Plugin root |
| `recorder/pyproject.toml` | 1 | Deps: playwright, Pillow, mcp |
| `recorder/VERSION` | 1 | SemVer text file, starts at `0.1.0` |
| `recorder/CHANGELOG.md` | 1 | Initial entry |
| `recorder/recorder/__init__.py` | 1 | Package init, exports `__version__` |
| `recorder/recorder/core.py` | 4 | Playwright session wrapper |
| `recorder/recorder/state.py` | 5 | Atomic file ops + flock |
| `recorder/recorder/retry.py` | 6 | Selector retry policy |
| `recorder/recorder/wait.py` | 7 | Whitelisted wait predicates |
| `recorder/recorder/annotate.py` | 8 | PIL-based annotation shapes |
| `recorder/recorder/login.py` | 9 | Login step + stdlib TOTP |
| `recorder/recorder/video.py` | 10 | 10s video slicing + ffprobe |
| `recorder/recorder/mask.py` | 11 | ffmpeg boxblur invocation |
| `recorder/recorder/script.py` | 12 | Declarative JSON runner |
| `recorder/recorder/cli.py` | 13 | CLI entry; shares register with mcp_server |
| `recorder/recorder/mcp_server.py` | 14 | MCP tool register |
| `recorder/tests/fixtures/static_site/*.html` | 2 | Static HTML test fixture |
| `recorder/tests/fixtures/static_site/styles.css` | 2 | Fixture styles |
| `recorder/tests/conftest.py` | 2, 4 | pytest fixtures (HTTP server, browser) |
| `recorder/tests/unit/test_state.py` | 5 | State unit tests |
| `recorder/tests/unit/test_retry.py` | 6 | Retry unit tests |
| `recorder/tests/unit/test_wait.py` | 7 | Wait unit tests |
| `recorder/tests/unit/test_annotate.py` | 8 | Annotation unit tests |
| `recorder/tests/unit/test_login.py` | 9 | Login + TOTP unit tests |
| `recorder/tests/unit/test_video.py` | 10 | Video slicing unit tests |
| `recorder/tests/unit/test_mask.py` | 11 | Mask invocation unit tests |
| `recorder/tests/integration/test_end_to_end.py` | 12 | End-to-end script test |
| `recorder/tests/integration/test_video.py` | 10 | Real video recording test |
| `recorder/examples/sample_script.json` | 15 | Declarative script example |
| `recorder/examples/dryrun-recorder.md` | 16 | End-to-end demo output |
| `recorder/scripts/run.sh` | 13 | Convenience wrapper |
| `recorder/SKILL.md` | 17 | Recorder agent-facing doc |
| `recorder/README.md` | 18 | Human install + usage |
| `recorder/INSTALL.md` | 18 | Explicit dep list + install commands |
| `CONTRIBUTING.md` | 19 | **(amend)** add §"Opt-in plugins" |
| `SKILL.md` | 20 | **(amend)** description + new §13 |
| `.github/workflows/recorder-ci.yml` | 3 | CI workflow (Ubuntu, ffmpeg, Playwright) |

---

## Task Index

| # | Task | Phase | Day |
|---|---|---|---|
| 1 | Scaffold recorder/ directory + pyproject + VERSION | Pre-flight | 1 |
| 2 | Build static HTML fixture (index + 2 sub + login + iframe + shadow DOM) | Pre-flight | 1 |
| 3 | Add `.github/workflows/recorder-ci.yml` (hello-world Playwright) | Pre-flight | 1 |
| 4 | Implement `core.py` (Playwright session wrapper) | Foundations | 1-2 |
| 5 | Implement `state.py` (atomic file + flock) | Foundations | 2 |
| 6 | Implement `retry.py` (selector retry policy) | Foundations | 2 |
| 7 | Implement `wait.py` (whitelisted predicates) | Foundations | 2 |
| 8 | Implement `annotate.py` (PIL shapes) | Foundations | 2 |
| 9 | Implement `login.py` (form fill + stdlib TOTP) | Login | 3 |
| 10 | Implement `video.py` (10s slicing + ffprobe) | Video+Mask | 3-4 |
| 11 | Implement `mask.py` (ffmpeg boxblur) | Video+Mask | 4 |
| 12 | Implement `script.py` (declarative JSON runner) | Orchestration | 4-5 |
| 13 | Implement `cli.py` (CLI entry) | Orchestration | 5 |
| 14 | Implement `mcp_server.py` (MCP tool register) | Orchestration | 5 |
| 15 | Write `examples/sample_script.json` | Sample+Docs | 5 |
| 16 | Generate `examples/dryrun-recorder.md` | Sample+Docs | 5 |
| 17 | Write `recorder/SKILL.md` | Sample+Docs | 5 |
| 18 | Write `recorder/README.md` + `INSTALL.md` | Sample+Docs | 5-6 |
| 19 | Amend `CONTRIBUTING.md` (opt-in plugin clause) | Sample+Docs | 6 |
| 20 | Amend `SKILL.md` (description + §13) | Sample+Docs | 6 |
| 21 | Verify all 11 acceptance criteria | Acceptance | 6 |
| 22 | Final commit + tag | Acceptance | 6 |

---

## Phase 0: Pre-flight (Day 1)

### Task 1: Scaffold `recorder/` directory

**Files:**
- Create: `recorder/pyproject.toml`
- Create: `recorder/VERSION`
- Create: `recorder/CHANGELOG.md`
- Create: `recorder/recorder/__init__.py`
- Create: `recorder/tests/__init__.py`
- Create: `recorder/tests/unit/__init__.py`
- Create: `recorder/tests/integration/__init__.py`
- Create: `recorder/tests/fixtures/__init__.py`
- Create: `recorder/tests/fixtures/static_site/__init__.py` (empty)
- Create: `recorder/examples/__init__.py` (empty)
- Create: `recorder/scripts/__init__.py` (empty)

- [ ] **Step 1: Create `recorder/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "user-manual-recorder"
version = "0.1.0"
description = "Opt-in recorder plugin for the user-manual skill"
requires-python = ">=3.10"
dependencies = [
    "playwright>=1.40,<2.0",
    "Pillow>=10.0",
    "mcp>=1.0",
]

[project.optional-dependencies]
test = ["pytest>=7.0", "pytest-asyncio>=0.21"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `recorder/VERSION`**

```
0.1.0
```

- [ ] **Step 3: Create `recorder/CHANGELOG.md`**

```markdown
# Changelog

## 0.1.0 (2026-06-11)

Initial release. See `docs/superpowers/specs/2026-06-11-recorder-skill-design.md` for full design.
```

- [ ] **Step 4: Create `recorder/recorder/__init__.py`**

```python
"""User-manual recorder opt-in plugin."""
from pathlib import Path

__version__ = (Path(__file__).parent.parent / "VERSION").read_text().strip()
```

- [ ] **Step 5: Create empty `__init__.py` files for test/example/scripts subdirs**

```bash
cd recorder && for d in tests tests/unit tests/integration tests/fixtures tests/fixtures/static_site examples scripts; do touch $d/__init__.py; done
```

- [ ] **Step 6: Add `recorder/` to root `.gitignore`**

Append to existing `.gitignore`:

```
# recorder plugin
recorder/.recorder_state.json
recorder/tests/fixtures/static_site/uploads/
*.auth.json
```

- [ ] **Step 7: Verify directory structure**

Run: `find recorder -type f | sort`
Expected: shows the new files (no .pyc, no __pycache__)

- [ ] **Step 8: Commit**

```bash
git add recorder/ .gitignore
git commit -m "chore(recorder): scaffold plugin directory + pyproject + VERSION"
```

---

### Task 2: Build static HTML fixture

**Files:**
- Create: `recorder/tests/fixtures/static_site/index.html`
- Create: `recorder/tests/fixtures/static_site/page-a.html`
- Create: `recorder/tests/fixtures/static_site/page-b.html`
- Create: `recorder/tests/fixtures/static_site/login.html`
- Create: `recorder/tests/fixtures/static_site/styles.css`
- Create: `recorder/tests/conftest.py`

The fixture is hand-written HTML that exercises: navigation, click, type, login (form fill), iframe selector, shadow DOM selector, and a button annotated for screenshot tests.

- [ ] **Step 1: Create `recorder/tests/fixtures/static_site/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Index</title><link rel="stylesheet" href="styles.css"></head>
<body>
  <nav>
    <a href="page-a.html" data-testid="nav-a">Page A</a>
    <a href="page-b.html" data-testid="nav-b">Page B</a>
    <a href="login.html" data-testid="nav-login">Login</a>
  </nav>
  <main>
    <h1 data-testid="page-title">Index Page</h1>
    <button data-testid="primary-action" class="primary">Primary Action</button>
    <button aria-label="Close dialog">×</button>
  </main>
  <footer>© Test Fixture</footer>
</body>
</html>
```

- [ ] **Step 2: Create `recorder/tests/fixtures/static_site/page-a.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Page A</title><link rel="stylesheet" href="styles.css"></head>
<body>
  <nav>
    <a href="index.html" data-testid="nav-home">Home</a>
  </nav>
  <main>
    <h1>Page A</h1>
    <form>
      <label>Name <input name="name" data-testid="name-input"></label>
      <label>Email <input name="email" type="email"></label>
      <button type="submit" data-testid="submit-a">Save</button>
    </form>
  </main>
</body>
</html>
```

- [ ] **Step 3: Create `recorder/tests/fixtures/static_site/page-b.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Page B</title><link rel="stylesheet" href="styles.css"></head>
<body>
  <nav>
    <a href="index.html" data-testid="nav-home">Home</a>
  </nav>
  <main>
    <h1>Page B</h1>
    <iframe src="index.html" data-testid="nested-iframe" width="400" height="100"></iframe>
  </main>
</body>
</html>
```

- [ ] **Step 4: Create `recorder/tests/fixtures/static_site/login.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Login</title><link rel="stylesheet" href="styles.css"></head>
<body>
  <main>
    <h1>Login</h1>
    <form id="login-form" data-testid="login-form">
      <label>User <input name="user" data-testid="user-field"></label>
      <label>Pass <input name="pass" type="password" data-testid="pass-field"></label>
      <label>TOTP <input name="totp" data-testid="totp-field"></label>
      <button type="submit" data-testid="login-submit">Sign in</button>
    </form>
    <div id="login-error" data-testid="login-error" style="display:none">Invalid credentials</div>
  </main>
  <script>
    document.getElementById('login-form').addEventListener('submit', function(e) {
      e.preventDefault();
      var u = document.querySelector('[name="user"]').value;
      var p = document.querySelector('[name="pass"]').value;
      var t = document.querySelector('[name="totp"]').value;
      // Test fixture: accept "testuser" / "testpass" with any 6-digit TOTP
      if (u === 'testuser' && p === 'testpass' && /^\d{6}$/.test(t)) {
        document.body.setAttribute('data-logged-in', 'true');
        document.getElementById('login-error').style.display = 'none';
      } else {
        document.getElementById('login-error').style.display = 'block';
      }
    });
  </script>
  <div data-testid="shadow-host"></div>
  <script>
    var host = document.querySelector('[data-testid="shadow-host"]');
    var root = host.attachShadow({mode: 'open'});
    root.innerHTML = '<button data-testid="shadow-button">Shadow Button</button>';
  </script>
</body>
</html>
```

- [ ] **Step 5: Create `recorder/tests/fixtures/static_site/styles.css`**

```css
body { font-family: -apple-system, sans-serif; max-width: 800px; margin: 2em auto; }
nav { border-bottom: 1px solid #ccc; padding-bottom: 0.5em; }
nav a { margin-right: 1em; }
button.primary { background: #0066cc; color: white; padding: 0.5em 1em; border: 0; }
iframe { border: 1px solid #ccc; }
[data-logged-in] main h1::after { content: ' (logged in)'; color: green; }
```

- [ ] **Step 6: Create `recorder/tests/conftest.py`**

```python
"""Shared pytest fixtures for recorder tests."""
import http.server
import socketserver
import threading
from pathlib import Path
import pytest

STATIC_SITE_DIR = Path(__file__).parent / "fixtures" / "static_site"


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_SITE_DIR), **kwargs)

    def log_message(self, *args, **kwargs):
        pass  # silence fixture HTTP logs


@pytest.fixture(scope="session")
def fixture_url():
    """Start a local HTTP server hosting the static fixture, return base URL."""
    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}"
        httpd.shutdown()


@pytest.fixture(scope="session")
def auth_secret():
    """Test TOTP secret (Base32, no padding)."""
    return "JBSWY3DPEHPK3PXP"
```

- [ ] **Step 7: Manually verify fixture loads**

Run: `cd recorder/tests/fixtures/static_site && python3 -m http.server 8765 &` then in another terminal `curl -s http://127.0.0.1:8765/ | head -5`
Expected: HTML output starting with `<!DOCTYPE html>`
Then kill the server.

- [ ] **Step 8: Commit**

```bash
git add recorder/tests/fixtures/ recorder/tests/conftest.py
git commit -m "test(recorder): static HTML fixture for integration tests"
```

---

### Task 3: Add `recorder-ci.yml` workflow (hello-world Playwright)

**Files:**
- Create: `.github/workflows/recorder-ci.yml`

The CI's first job is **just a hello-world Playwright launch**. No recorder tests yet. This unblocks the env-install work.

- [ ] **Step 1: Create `.github/workflows/recorder-ci.yml`**

```yaml
name: recorder-ci
on:
  push:
    paths:
      - 'recorder/**'
      - '.github/workflows/recorder-ci.yml'
  pull_request:
    paths:
      - 'recorder/**'
      - '.github/workflows/recorder-ci.yml'

jobs:
  hello-world:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - name: Install ffmpeg
        run: sudo apt-get update && sudo apt-get install -y ffmpeg
      - name: Install noto-cjk
        run: sudo apt-get install -y fonts-noto-cjk
      - name: Install recorder plugin
        working-directory: recorder
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[test]"
      - name: Install Playwright browsers
        working-directory: recorder
        run: playwright install --with-deps chromium
      - name: Hello-world Playwright launch
        working-directory: recorder
        run: |
          python -c "
          import asyncio
          from playwright.async_api import async_playwright
          async def main():
              async with async_playwright() as p:
                  b = await p.chromium.launch(headless=True, args=['--no-sandbox'])
                  page = await b.new_page()
                  await page.goto('about:blank')
                  print('hello world from Playwright')
                  await b.close()
          asyncio.run(main())
          "
      - name: Verify ffmpeg
        run: ffmpeg -version | head -1
```

- [ ] **Step 2: Push and verify the CI workflow runs green**

Run: `git push`
Expected: GitHub Actions runs `recorder-ci`, all steps pass.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/recorder-ci.yml
git commit -m "ci(recorder): hello-world workflow on Ubuntu (ffmpeg + Playwright)"
```

---

## Phase 1: Foundations (Day 1-2)

### Task 4: Implement `core.py` (Playwright session)

**Files:**
- Create: `recorder/recorder/core.py`
- Create: `recorder/tests/integration/test_core_hello.py`

`core.py` owns the single Playwright `BrowserContext`. All other modules call into it; no other module imports `playwright` directly.

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/integration/test_core_hello.py`:

```python
import asyncio
from pathlib import Path
import pytest
from recorder.core import Recorder

@pytest.mark.asyncio
async def test_recorder_can_navigate_to_fixture(fixture_url, tmp_path):
    out = tmp_path / "01.png"
    async with Recorder(viewport={"width": 1024, "height": 768}, headless=True, output_dir=tmp_path) as rec:
        await rec.navigate(fixture_url + "/index.html")
        await rec.screenshot(name="01", annotate=None, mask=None, output_path=out)
    assert out.exists()
    assert out.stat().st_size > 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/integration/test_core_hello.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recorder.core'`

- [ ] **Step 3: Implement `core.py`**

Create `recorder/recorder/core.py`:

```python
"""Playwright session wrapper. The single browser session for all recorder operations."""
from __future__ import annotations
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

CHROMIUM_LAUNCH_FLAGS = [
    "--no-sandbox",
    "--disable-notifications",
    "--disable-popup-blocking",
    "--no-first-run",
    "--disable-features=Translate,InfiniteSessionRestore",
]


@dataclass
class AssetRef:
    path: Path
    kind: str  # "screenshot" | "video_slice"
    width: int | None = None
    height: int | None = None
    size_bytes: int = 0
    selector_used: str | None = None
    caption_hint: str | None = None
    annotated: bool = False
    slice_index: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "path": str(self.path),
            "kind": self.kind,
            "size_bytes": self.size_bytes,
        }
        if self.width: d["width"] = self.width
        if self.height: d["height"] = self.height
        if self.selector_used: d["selector_used"] = self.selector_used
        if self.caption_hint: d["caption_hint"] = self.caption_hint
        if self.annotated: d["annotated"] = True
        if self.slice_index is not None: d["slice_index"] = self.slice_index
        d.update(self.extra)
        return d


class Recorder:
    """Single Playwright browser session. All recorder operations go through this."""

    def __init__(self, viewport: dict, headless: bool, output_dir: Path, record_video_dir: Path | None = None):
        self.viewport = viewport
        self.headless = headless
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.record_video_dir = Path(record_video_dir) if record_video_dir else None
        if self.record_video_dir:
            self.record_video_dir.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> "Recorder":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=CHROMIUM_LAUNCH_FLAGS,
        )
        context_kwargs = {
            "viewport": {"width": self.viewport["width"], "height": self.viewport["height"]},
            "device_scale_factor": self.viewport.get("device_scale", 1),
        }
        if self.record_video_dir:
            context_kwargs["record_video_dir"] = str(self.record_video_dir)
            context_kwargs["record_video_size"] = {
                "width": self.viewport["width"],
                "height": self.viewport["height"],
            }
        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()

    async def close(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Recorder not started; call start() or use as async context manager")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Recorder not started")
        return self._context

    async def navigate(self, url: str, wait_until: str = "domcontentloaded") -> None:
        await self.page.goto(url, wait_until=wait_until)

    async def screenshot(self, name: str, annotate: list | None, mask: list | None, output_path: Path) -> AssetRef:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path), full_page=False)
        return AssetRef(path=path, kind="screenshot", size_bytes=path.stat().st_size)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/integration/test_core_hello.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/core.py recorder/tests/integration/test_core_hello.py
git commit -m "feat(recorder): core.py with Playwright session wrapper"
```

---

### Task 5: Implement `state.py` (atomic file + flock)

**Files:**
- Create: `recorder/recorder/state.py`
- Create: `recorder/tests/unit/test_state.py`

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/unit/test_state.py`:

```python
import json
import pytest
from pathlib import Path
from recorder.state import RecorderState, atomic_write_json, file_lock

def test_atomic_write_json(tmp_path):
    f = tmp_path / "state.json"
    atomic_write_json(f, {"a": 1, "b": [1, 2, 3]})
    assert json.loads(f.read_text()) == {"a": 1, "b": [1, 2, 3]}

def test_atomic_write_json_no_partial_file(tmp_path):
    f = tmp_path / "state.json"
    atomic_write_json(f, {"a": 1})
    # Verify no .tmp file lingering
    assert not (tmp_path / "state.json.tmp").exists()

def test_recorder_state_skip_when_valid(tmp_path):
    state = RecorderState(tmp_path, "test-script")
    state.set_step(3, input_hash="abc", output_path=tmp_path / "out.png", validated=True)
    # Second set with same hash and existing file: should be no-op
    state.set_step(3, input_hash="abc", output_path=tmp_path / "out.png", validated=True)
    record = state.get_step(3)
    assert record["validated"] is True

def test_file_lock_exclusive(tmp_path):
    f = tmp_path / "lock.file"
    with file_lock(f):
        # Inside the lock, the file should exist
        assert f.exists()
    # After release, the file may or may not exist (lockfile cleanup is OS-dependent)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/unit/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recorder.state'`

- [ ] **Step 3: Implement `state.py`**

Create `recorder/recorder/state.py`:

```python
"""Idempotency state: per-script JSON, atomic writes, flock for cross-process safety."""
from __future__ import annotations
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

STATE_FILENAME = ".recorder_state.json"


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: write to .tmp, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".tmp_state_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Acquire an exclusive flock on `lock_path`. Releases on context exit."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class RecorderState:
    """Per-script idempotency state.

    Stores: {step_idx: {input_hash, output_path, mtime, validated}}.
    Re-run skips a step if its output_path exists and input_hash matches.
    """

    def __init__(self, output_dir: Path, script_name: str):
        self.output_dir = Path(output_dir)
        self.script_name = script_name
        self.path = self.output_dir / STATE_FILENAME
        self._data: dict = {"script_name": script_name, "steps": {}}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                with file_lock(self.path.with_suffix(".lock")):
                    self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                # Corrupt state: ignore, start fresh
                self._data = {"script_name": self.script_name, "steps": {}}

    def _save(self) -> None:
        with file_lock(self.path.with_suffix(".lock")):
            atomic_write_json(self.path, self._data)

    def set_step(self, step_idx: int, input_hash: str, output_path: Path, validated: bool) -> None:
        from datetime import datetime, timezone
        path = Path(output_path)
        if path.exists() and self._data["steps"].get(str(step_idx), {}).get("input_hash") == input_hash:
            return  # no-op: same hash, file exists
        self._data["steps"][str(step_idx)] = {
            "input_hash": input_hash,
            "output_path": str(path),
            "mtime": datetime.now(timezone.utc).isoformat(),
            "validated": validated,
        }
        self._save()

    def get_step(self, step_idx: int) -> dict | None:
        return self._data["steps"].get(str(step_idx))

    def is_step_valid(self, step_idx: int, input_hash: str) -> bool:
        record = self.get_step(step_idx)
        if not record:
            return False
        if record["input_hash"] != input_hash:
            return False
        return Path(record["output_path"]).exists()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/unit/test_state.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/state.py recorder/tests/unit/test_state.py
git commit -m "feat(recorder): state.py with atomic writes + flock"
```

---

### Task 6: Implement `retry.py` (selector retry policy)

**Files:**
- Create: `recorder/recorder/retry.py`
- Create: `recorder/tests/unit/test_retry.py`

Retry order (per spec §5.7): **testid/aria-label → text → role → partial text**. Each tier has a budget (default 2 attempts).

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/unit/test_retry.py`:

```python
from recorder.retry import SelectorResolver, RetryPolicy

def test_resolver_strips_has_text_for_first_tier():
    r = SelectorResolver()
    variants = r.variants("button:has-text('新增用户')")
    # First variant is the original
    assert variants[0] == "button:has-text('新增用户')"
    # Second variant strips has-text
    assert "button" in variants[1]

def test_resolver_text_fallback():
    r = SelectorResolver()
    variants = r.variants("button:has-text('新增用户')")
    # text fallback present
    assert any("新增用户" in v for v in variants)

def test_resolver_role_fallback():
    r = SelectorResolver()
    variants = r.variants("button:has-text('Save')")
    assert any("role=button" in v for v in variants)

def test_resolver_partial_text_fallback():
    r = SelectorResolver()
    variants = r.variants("button:has-text('Save User')")
    # Should have a partial-text variant
    assert any("Save User" in v for v in variants)

def test_retry_policy_default_budget():
    p = RetryPolicy.auto()
    assert p.budget_per_tier == 2

def test_retry_policy_strict():
    p = RetryPolicy.strict()
    assert p.fail_fast is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/unit/test_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'recorder.retry'`

- [ ] **Step 3: Implement `retry.py`**

Create `recorder/recorder/retry.py`:

```python
"""Selector retry policy. Tries testid/aria-label → text → role → partial text."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Callable

_HAS_TEXT_RE = re.compile(r":has-text\(\s*['\"]([^'\"]+)['\"]\s*\)")


def _extract_text(selector: str) -> str | None:
    m = _HAS_TEXT_RE.search(selector)
    return m.group(1) if m else None


def _strip_has_text(selector: str) -> str:
    return _HAS_TEXT_RE.sub("", selector).strip()


@dataclass
class RetryPolicy:
    budget_per_tier: int = 2
    fail_fast: bool = False

    @staticmethod
    def auto() -> "RetryPolicy":
        return RetryPolicy(budget_per_tier=2, fail_fast=False)

    @staticmethod
    def strict() -> "RetryPolicy":
        return RetryPolicy(budget_per_tier=2, fail_fast=True)


class SelectorResolver:
    """Generates fallback selector variants for retry."""

    def variants(self, selector: str) -> list[str]:
        text = _extract_text(selector)
        stripped = _strip_has_text(selector)
        out = [selector]  # tier 0: original
        if stripped and stripped != selector:
            out.append(stripped)  # tier 1: testid/aria-label-style
        if text:
            out.append(f"text={text}")  # tier 2: text exact
            out.append(f"role=button >> text={text}")  # tier 3: role
            out.append(f"text={text}")  # tier 4: partial text (Playwright text= is substring by default)
        return out

    def attempt(self, selector: str, locator_fn: Callable[[str], object]) -> tuple[bool, str, int]:
        """Try each variant up to budget_per_tier times. Returns (success, winning_selector, total_attempts)."""
        policy = RetryPolicy.auto()
        attempts = 0
        for variant in self.variants(selector):
            for _ in range(policy.budget_per_tier):
                attempts += 1
                try:
                    locator = locator_fn(variant)
                    # Caller's locator_fn should raise on failure; if it returns, we accept.
                    return True, variant, attempts
                except Exception:
                    continue
        return False, "", attempts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/unit/test_retry.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/retry.py recorder/tests/unit/test_retry.py
git commit -m "feat(recorder): retry.py with selector fallback chain"
```

---

### Task 7: Implement `wait.py` (whitelisted predicates)

**Files:**
- Create: `recorder/recorder/wait.py`
- Create: `recorder/tests/unit/test_wait.py`

v1 supports: `selector` (with state), `text` (with exact), `networkidle`, `timeout`. No `custom_js` (security: agent review flagged this as RCE risk).

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/unit/test_wait.py`:

```python
import pytest
from recorder.wait import WaitSpec, dispatch_wait

def test_wait_spec_rejects_custom_js():
    with pytest.raises(ValueError, match="custom_js is not supported"):
        WaitSpec.from_dict({"strategy": "custom_js", "js": "alert(1)"})

def test_wait_spec_accepts_selector():
    spec = WaitSpec.from_dict({"strategy": "selector", "selector": "h1", "state": "visible"})
    assert spec.strategy == "selector"
    assert spec.args == {"selector": "h1", "state": "visible"}

def test_wait_spec_accepts_text():
    spec = WaitSpec.from_dict({"strategy": "text", "text": "Saved", "exact": True})
    assert spec.strategy == "text"

def test_wait_spec_accepts_networkidle():
    spec = WaitSpec.from_dict({"strategy": "networkidle"})
    assert spec.strategy == "networkidle"

def test_wait_spec_accepts_timeout():
    spec = WaitSpec.from_dict({"strategy": "timeout", "ms": 2000})
    assert spec.strategy == "timeout"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/unit/test_wait.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `wait.py`**

Create `recorder/recorder/wait.py`:

```python
"""Whitelisted wait predicates. v1 rejects custom_js."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any

ALLOWED_STRATEGIES = {"selector", "text", "networkidle", "timeout"}


@dataclass
class WaitSpec:
    strategy: str
    args: dict[str, Any]

    @staticmethod
    def from_dict(d: dict) -> "WaitSpec":
        strategy = d.get("strategy")
        if strategy not in ALLOWED_STRATEGIES:
            if strategy == "custom_js":
                raise ValueError(
                    "custom_js is not supported in v1 (security: arbitrary JS in JSON "
                    "scripts is a remote code execution surface). See spec §5.10."
                )
            raise ValueError(f"Unknown wait strategy: {strategy!r}; allowed: {sorted(ALLOWED_STRATEGIES)}")
        return WaitSpec(strategy=strategy, args={k: v for k, v in d.items() if k != "strategy"})


async def dispatch_wait(page, spec: WaitSpec) -> int:
    """Execute the wait. Returns elapsed_ms."""
    import time
    start = time.monotonic()
    if spec.strategy == "selector":
        selector = spec.args["selector"]
        state = spec.args.get("state", "visible")
        await page.locator(selector).wait_for(state=state, timeout=10000)
    elif spec.strategy == "text":
        text = spec.args["text"]
        exact = spec.args.get("exact", False)
        # Use locator with text engine
        if exact:
            await page.get_by_text(text, exact=True).first.wait_for(timeout=10000)
        else:
            await page.get_by_text(text).first.wait_for(timeout=10000)
    elif spec.strategy == "networkidle":
        await page.wait_for_load_state("networkidle", timeout=10000)
    elif spec.strategy == "timeout":
        await asyncio.sleep(spec.args.get("ms", 1000) / 1000.0)
    else:
        raise ValueError(f"Unhandled strategy: {spec.strategy}")
    elapsed = int((time.monotonic() - start) * 1000)
    return elapsed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/unit/test_wait.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/wait.py recorder/tests/unit/test_wait.py
git commit -m "feat(recorder): wait.py with whitelisted predicates (no custom_js)"
```

---

### Task 8: Implement `annotate.py` (PIL shapes)

**Files:**
- Create: `recorder/recorder/annotate.py`
- Create: `recorder/tests/unit/test_annotate.py`

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/unit/test_annotate.py`:

```python
from pathlib import Path
from PIL import Image
import pytest
from recorder.annotate import Annotation, annotate_image

def make_test_image(path: Path) -> Path:
    img = Image.new("RGB", (400, 300), color="white")
    img.save(path)
    return path

def test_annotate_box(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [
        Annotation(shape="box", x=10, y=20, w=100, h=50, label="Click"),
    ]
    annotate_image(src, dst, annotations)
    assert dst.exists()
    # Annotated image should differ from source
    from PIL import ImageChops
    diff = ImageChops.difference(Image.open(src), Image.open(dst))
    assert diff.getbbox() is not None

def test_annotate_number(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [Annotation(shape="number", x=200, y=150, w=30, h=30, n=1)]
    annotate_image(src, dst, annotations)
    assert dst.exists()

def test_annotate_highlight(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [Annotation(shape="highlight", x=10, y=10, w=100, h=50, label="")]
    annotate_image(src, dst, annotations)
    assert dst.exists()

def test_annotate_composite(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotations = [
        Annotation(shape="box", x=10, y=10, w=100, h=50, label="A"),
        Annotation(shape="arrow", from_xy=(20, 30), to_xy=(80, 100), label="to"),
        Annotation(shape="number", x=200, y=200, w=20, h=20, n=2),
    ]
    annotate_image(src, dst, annotations)
    assert dst.exists()

def test_annotate_no_annotations_passthrough(tmp_path):
    src = make_test_image(tmp_path / "src.png")
    dst = tmp_path / "annotated.png"
    annotate_image(src, dst, [])
    # With no annotations, dst should equal src byte-for-byte
    assert src.read_bytes() == dst.read_bytes()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/unit/test_annotate.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `annotate.py`**

Create `recorder/recorder/annotate.py`:

```python
"""Image annotation. PIL-based. Renders box/arrow/number/highlight/composite onto screenshots."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RED = (220, 30, 30)
YELLOW_FILL = (255, 220, 0, 80)
WHITE = (255, 255, 255)
BOX_WIDTH = 3


@dataclass
class Annotation:
    shape: str  # "box" | "arrow" | "number" | "highlight" | "composite"
    # Box/highlight/number use x,y,w,h (number uses n instead of label)
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    label: str = ""
    # Arrow uses from_xy, to_xy
    from_xy: tuple[int, int] | None = None
    to_xy: tuple[int, int] | None = None
    n: int | None = None  # for "number"

    @staticmethod
    def from_dict(d: dict) -> "Annotation":
        return Annotation(
            shape=d["shape"],
            x=d.get("x"),
            y=d.get("y"),
            w=d.get("w"),
            h=d.get("h"),
            label=d.get("label", ""),
            from_xy=tuple(d["from_xy"]) if d.get("from_xy") else None,
            to_xy=tuple(d["to_xy"]) if d.get("to_xy") else None,
            n=d.get("n"),
        )


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", size)
    except OSError:
        return ImageFont.load_default()


def _draw_box(draw: ImageDraw.ImageDraw, a: Annotation) -> None:
    draw.rectangle([a.x, a.y, a.x + a.w, a.y + a.h], outline=RED, width=BOX_WIDTH)
    if a.label:
        f = _font(14)
        # Label badge top-left, slightly outside the box
        draw.rectangle([a.x, max(0, a.y - 18), a.x + 8 * len(a.label) + 4, a.y], fill=RED)
        draw.text((a.x + 2, max(0, a.y - 16)), a.label, fill=WHITE, font=f)


def _draw_arrow(draw: ImageDraw.ImageDraw, a: Annotation) -> None:
    if not a.from_xy or not a.to_xy:
        return
    draw.line([a.from_xy, a.to_xy], fill=RED, width=BOX_WIDTH)
    # Arrowhead
    fx, fy = a.from_xy
    tx, ty = a.to_xy
    draw.polygon([(tx, ty), (tx - 8, ty - 4), (tx - 8, ty + 4)], fill=RED)
    if a.label:
        f = _font(12)
        draw.text((tx + 4, ty - 6), a.label, fill=RED, font=f)


def _draw_number(draw: ImageDraw.ImageDraw, a: Annotation) -> None:
    if a.n is None:
        return
    cx = a.x + a.w // 2
    cy = a.y + a.h // 2
    r = min(a.w, a.h) // 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)
    f = _font(max(10, r))
    text = str(a.n)
    bbox = draw.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw // 2, cy - th // 2 - 2), text, fill=WHITE, font=f)


def _draw_highlight(draw_overlay: ImageDraw.ImageDraw, a: Annotation) -> None:
    draw_overlay.rectangle([a.x, a.y, a.x + a.w, a.y + a.h], fill=YELLOW_FILL)


def annotate_image(src: Path, dst: Path, annotations: list[Annotation]) -> None:
    """Copy `src` to `dst`, then draw annotations on top of `dst`."""
    import shutil
    if not annotations:
        shutil.copy(src, dst)
        return
    img = Image.open(src).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    main_draw = ImageDraw.Draw(img)
    for a in annotations:
        if a.shape == "box":
            _draw_box(main_draw, a)
        elif a.shape == "arrow":
            _draw_arrow(main_draw, a)
        elif a.shape == "number":
            _draw_number(main_draw, a)
        elif a.shape == "highlight":
            _draw_highlight(overlay_draw, a)
            if a.label:
                f = _font(12)
                main_draw.rectangle([a.x, max(0, a.y - 16), a.x + 8 * len(a.label) + 4, a.y], fill=RED)
                main_draw.text((a.x + 2, max(0, a.y - 14)), a.label, fill=WHITE, font=f)
        elif a.shape == "composite":
            # Treat as box for now (caller can split into multiple Annotations)
            _draw_box(main_draw, a)
    img = Image.alpha_composite(img, overlay).convert("RGB")
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/unit/test_annotate.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/annotate.py recorder/tests/unit/test_annotate.py
git commit -m "feat(recorder): annotate.py with box/arrow/number/highlight/composite"
```

---

## Phase 2: Login (Day 2-3)

### Task 9: Implement `login.py` (form fill + stdlib TOTP)

**Files:**
- Create: `recorder/recorder/login.py`
- Create: `recorder/tests/unit/test_login.py`

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/unit/test_login.py`:

```python
import base64
import pytest
from recorder.login import totp_code, validate_totp_secret

def test_validate_totp_secret_accepts_base32():
    assert validate_totp_secret("JBSWY3DPEHPK3PXP") is True

def test_validate_totp_secret_rejects_garbage():
    assert validate_totp_secret("not-valid-base32!!!") is False

def test_totp_code_returns_6_digits():
    secret = "JBSWY3DPEHPK3PXP"
    code = totp_code(secret, timestamp=1234567890)
    assert len(code) == 6
    assert code.isdigit()

def test_totp_code_deterministic():
    secret = "JBSWY3DPEHPK3PXP"
    code1 = totp_code(secret, timestamp=1234567890)
    code2 = totp_code(secret, timestamp=1234567890)
    assert code1 == code2

def test_totp_code_different_time_windows():
    secret = "JBSWY3DPEHPK3PXP"
    code1 = totp_code(secret, timestamp=1234567890)
    code2 = totp_code(secret, timestamp=1234567890 + 60)  # next window
    assert code1 != code2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/unit/test_login.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `login.py`**

Create `recorder/recorder/login.py`:

```python
"""Login step. Form fill from env vars or auth.json. TOTP via stdlib only."""
from __future__ import annotations
import base64
import hmac
import os
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOTP_PERIOD = 30
TOTP_DIGITS = 6
TOTP_WINDOW_DRIFT = 1  # accept current ±1 window by default


def validate_totp_secret(secret: str) -> bool:
    """Validate a Base32 TOTP secret (no padding required)."""
    try:
        # Normalize: strip whitespace, add padding
        s = secret.strip().replace(" ", "").upper()
        padding = (8 - len(s) % 8) % 8
        s_padded = s + "=" * padding
        base64.b32decode(s_padded)
        return True
    except Exception:
        return False


def _hotp(secret: str, counter: int) -> str:
    s = secret.strip().replace(" ", "").upper()
    padding = (8 - len(s) % 8) % 8
    key = base64.b32decode(s + "=" * padding)
    counter_bytes = struct.pack(">Q", counter)
    h = hmac.new(key, counter_bytes, "sha1").digest()
    offset = h[-1] & 0x0F
    code_int = (struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** TOTP_DIGITS)
    return str(code_int).zfill(TOTP_DIGITS)


def totp_code(secret: str, timestamp: float | None = None) -> str:
    """Compute TOTP code at given timestamp (default: now)."""
    ts = timestamp if timestamp is not None else time.time()
    counter = int(ts) // TOTP_PERIOD
    return _hotp(secret, counter)


def totp_codes_with_drift(secret: str, drift: int = TOTP_WINDOW_DRIFT, timestamp: float | None = None) -> list[str]:
    """Return [prev, current, next] TOTP codes to handle window drift."""
    ts = timestamp if timestamp is not None else time.time()
    counter = int(ts) // TOTP_PERIOD
    return [_hotp(secret, counter + d) for d in (-drift, 0, drift)]


def resolve_credential(value: str, env: dict | None = None) -> str:
    """If `value` starts with $, look it up in env (or os.environ)."""
    if not value.startswith("$"):
        return value
    name = value[1:]
    if env and name in env:
        return env[name]
    return os.environ.get(name, "")


@dataclass
class LoginStep:
    url: str
    user_field: str
    user: str
    pass_field: str
    pass_: str  # avoid keyword conflict
    submit_selector: str
    totp_secret: str = ""
    totp_drift_seconds: int = TOTP_WINDOW_DRIFT

    @staticmethod
    def from_dict(d: dict) -> "LoginStep":
        return LoginStep(
            url=d["url"],
            user_field=d["user_field"],
            user=d["user"],
            pass_field=d["pass_field"],
            pass_=d["pass"],
            submit_selector=d["submit_selector"],
            totp_secret=d.get("totp_secret", ""),
            totp_drift_seconds=d.get("totp_drift_seconds", TOTP_WINDOW_DRIFT),
        )


async def perform_login(recorder, step: LoginStep, env: dict | None = None) -> bool:
    """Navigate, fill the form, optionally compute TOTP, submit, verify success.

    Returns True if login succeeded (page shows logged-in indicator or no error visible).
    """
    user = resolve_credential(step.user, env)
    pw = resolve_credential(step.pass_, env)
    await recorder.navigate(step.url)
    await recorder.page.fill(step.user_field, user)
    await recorder.page.fill(step.pass_field, pw)
    if step.totp_secret:
        secret = resolve_credential(step.totp_secret, env)
        codes = totp_codes_with_drift(secret, drift=step.totp_drift_seconds)
        # Try the most likely code first (current window)
        await recorder.page.fill("input[name='totp']", codes[1])
    await recorder.page.click(step.submit_selector)
    # Heuristic success check: page attribute or selector presence
    await recorder.page.wait_for_load_state("networkidle", timeout=5000)
    body = await recorder.page.locator("body").get_attribute("data-logged-in")
    if body == "true":
        return True
    # Fall back: no error visible
    error_visible = await recorder.page.locator("[data-testid='login-error']").is_visible()
    return not error_visible
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/unit/test_login.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/login.py recorder/tests/unit/test_login.py
git commit -m "feat(recorder): login.py with stdlib TOTP + drift handling"
```

---

## Phase 3: Video + Mask (Day 3-4)

### Task 10: Implement `video.py` (10s slicing + ffprobe)

**Files:**
- Create: `recorder/recorder/video.py`
- Create: `recorder/tests/unit/test_video.py`
- Create: `recorder/tests/integration/test_video.py`

Playwright records a webm stream; we slice it into 10-second chunks via ffmpeg. Each chunk is `ffprobe`-validated.

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/unit/test_video.py`:

```python
import json
import subprocess
from pathlib import Path
import pytest
from recorder.video import slice_video, validate_slice, get_video_info

def test_get_video_info_returns_duration(tmp_path):
    # Create a 2-second test video with ffmpeg
    src = tmp_path / "input.webm"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15",
        "-c:v", "libvpx", "-b:v", "200k", str(src)
    ], check=True, capture_output=True)
    info = get_video_info(src)
    assert 1.5 < info["duration_s"] < 2.5

def test_slice_video_produces_chunks(tmp_path):
    src = tmp_path / "input.webm"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=15",
        "-c:v", "libvpx", "-b:v", "200k", str(src)
    ], check=True, capture_output=True)
    out_dir = tmp_path / "slices"
    paths = slice_video(src, out_dir, slice_seconds=2)
    assert len(paths) >= 2  # 5s / 2s = 2 full + 1 partial

def test_validate_slice_passes_valid_file(tmp_path):
    src = tmp_path / "input.webm"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
        "-c:v", "libvpx", "-b:v", "100k", str(src)
    ], check=True, capture_output=True)
    assert validate_slice(src) is True

def test_validate_slice_rejects_missing_file(tmp_path):
    assert validate_slice(tmp_path / "does_not_exist.webm") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/unit/test_video.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `video.py`**

Create `recorder/recorder/video.py`:

```python
"""Video recording: Playwright records webm; ffmpeg slices into 10s chunks; ffprobe validates each."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from typing import Any

LOCKED_CODEC_PARAMS = ["-c:v", "libvpx", "-b:v", "1M", "-r", "30", "-pix_fmt", "yuv420p", "-g", "60"]


def get_video_info(path: Path) -> dict[str, Any]:
    """Return {duration_s, width, height, codec} via ffprobe."""
    out = subprocess.check_output([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ])
    data = json.loads(out)
    fmt = data.get("format", {})
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration_s": float(fmt.get("duration", 0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "codec": video_stream.get("codec_name", ""),
    }


def validate_slice(path: Path) -> bool:
    """ffprobe-validate a slice. Returns True if parseable and duration > 0."""
    if not path.exists() or path.stat().st_size < 100:
        return False
    try:
        info = get_video_info(path)
        return info["duration_s"] > 0
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
        return False


def slice_video(src: Path, out_dir: Path, slice_seconds: int = 10) -> list[Path]:
    """Slice a video into fixed-duration chunks. Returns list of slice paths.

    Uses ffmpeg segment muxer; each segment is independently playable.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / f"{src.stem}.%04d.webm"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(src),
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(slice_seconds),
        "-reset_timestamps", "1",
        str(pattern),
    ], check=True, capture_output=True)
    return sorted(out_dir.glob(f"{src.stem}.*.webm"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/unit/test_video.py -v`
Expected: PASS (4 tests; requires `ffmpeg` installed)

- [ ] **Step 5: Write integration test**

Create `recorder/tests/integration/test_video.py`:

```python
import asyncio
from pathlib import Path
import pytest
from recorder.core import Recorder
from recorder.video import slice_video, validate_slice

@pytest.mark.asyncio
async def test_recorder_video_capture_and_slice(fixture_url, tmp_path):
    video_dir = tmp_path / "videos"
    out_dir = tmp_path / "slices"
    async with Recorder(
        viewport={"width": 800, "height": 600},
        headless=True,
        output_dir=tmp_path,
        record_video_dir=video_dir,
    ) as rec:
        await rec.navigate(fixture_url + "/index.html")
        await asyncio.sleep(0.5)  # let recording capture a few hundred ms
    # After exit, the .webm lives in video_dir
    webms = list(video_dir.glob("*.webm"))
    assert len(webms) >= 1, f"expected recorded webm in {video_dir}, got {list(video_dir.iterdir())}"
    # Slice and validate
    slices = slice_video(webms[0], out_dir, slice_seconds=1)
    assert all(validate_slice(s) for s in slices)
```

- [ ] **Step 6: Run integration test**

Run: `cd recorder && pytest tests/integration/test_video.py -v`
Expected: PASS (requires Playwright + Chromium installed)

- [ ] **Step 7: Commit**

```bash
git add recorder/recorder/video.py recorder/tests/unit/test_video.py recorder/tests/integration/test_video.py
git commit -m "feat(recorder): video.py with ffmpeg slicing + ffprobe validation"
```

---

### Task 11: Implement `mask.py` (ffmpeg boxblur)

**Files:**
- Create: `recorder/recorder/mask.py`
- Create: `recorder/tests/unit/test_mask.py`

Use ffmpeg `boxblur` filter for video (fast). Use Pillow for screenshots (one frame, doesn't matter).

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/unit/test_mask.py`:

```python
import subprocess
from pathlib import Path
import pytest
from recorder.mask import mask_image_pillow, mask_video_ffmpeg

def test_mask_image_pillow(tmp_path):
    from PIL import Image
    src = tmp_path / "src.png"
    Image.new("RGB", (200, 200), "white").save(src)
    dst = tmp_path / "masked.png"
    regions = [{"x": 10, "y": 10, "w": 50, "h": 30, "blur_pixels": 5}]
    mask_image_pillow(src, dst, regions)
    assert dst.exists()
    # Pixel in masked region should differ from white
    from PIL import Image
    px = Image.open(dst).getpixel((20, 20))
    assert px != (255, 255, 255)

def test_mask_video_ffmpeg_produces_output(tmp_path):
    src = tmp_path / "input.webm"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
        "-c:v", "libvpx", "-b:v", "100k", str(src)
    ], check=True, capture_output=True)
    dst = tmp_path / "masked.webm"
    regions = [{"x": 10, "y": 10, "w": 100, "h": 50, "blur_pixels": 8}]
    mask_video_ffmpeg(src, dst, regions)
    assert dst.exists()
    assert dst.stat().st_size > 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/unit/test_mask.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `mask.py`**

Create `recorder/recorder/mask.py`:

```python
"""Privacy masking. Screenshots: Pillow GaussianBlur. Video: ffmpeg boxblur filter."""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Iterable


def mask_image_pillow(src: Path, dst: Path, regions: Iterable[dict]) -> None:
    """Apply GaussianBlur to rectangular regions in a screenshot."""
    from PIL import Image, ImageFilter
    img = Image.open(src).convert("RGB")
    for r in regions:
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        crop = img.crop((x, y, x + w, y + h))
        blurred = crop.filter(ImageFilter.GaussianBlur(radius=r.get("blur_pixels", 8)))
        img.paste(blurred, (x, y))
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)


def mask_video_ffmpeg(src: Path, dst: Path, regions: Iterable[dict]) -> None:
    """Apply boxblur filter to rectangular regions in a video, frame by frame."""
    filters = []
    for i, r in enumerate(regions):
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        # boxblur with luma_radius in pixels; produces a blurred region
        filters.append(f"crop={w}:{h}:{x}:{y},boxblur={r.get('blur_pixels', 8)}:1,overlay={x}:{y}")
    if not filters:
        # Passthrough copy
        subprocess.run([
            "ffmpeg", "-y", "-i", str(src), "-c", "copy", str(dst)
        ], check=True, capture_output=True)
        return
    # Chain all overlays onto the base input via filter_complex
    filter_complex_parts = []
    inputs = ["-i", str(src)]
    for i, f in enumerate(filters):
        filter_complex_parts.append(f"[0:v]{f}[v{i}]")
        if i + 1 < len(filters):
            filter_complex_parts.append(f";[v{i}][{i + 1}:v]overlay")
    # Simpler: do each region sequentially by chaining split/overlay/crop
    # Use a single filter graph with successive overlays
    chain = "[0:v]"
    last = "base"
    for i, r in enumerate(regions):
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        blur = r.get("blur_pixels", 8)
        cropped_label = f"c{i}"
        blurred_label = f"b{i}"
        out_label = f"o{i}"
        chain += f"split=2[{last}_keep][{cropped_label}];[{cropped_label}]crop={w}:{h}:{x}:{y},boxblur={blur}:1[{blurred_label}];[{last}_keep][{blurred_label}]overlay={x}:{y}[{out_label}]"
        last = out_label
        if i + 1 < len(regions):
            chain += ";"
    subprocess.run([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", chain,
        "-map", f"[{last}]",
        "-c:v", "libvpx", "-b:v", "1M",
        str(dst),
    ], check=True, capture_output=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/unit/test_mask.py -v`
Expected: PASS (2 tests; requires ffmpeg + Pillow)

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/mask.py recorder/tests/unit/test_mask.py
git commit -m "feat(recorder): mask.py with Pillow (images) + ffmpeg boxblur (video)"
```

---

## Phase 4: Orchestration (Day 4-5)

### Task 12: Implement `script.py` (declarative JSON runner)

**Files:**
- Create: `recorder/recorder/script.py`
- Create: `recorder/tests/integration/test_end_to_end.py`

`script.py` walks a JSON script and dispatches each step to the right module.

- [ ] **Step 1: Write the failing test**

Create `recorder/tests/integration/test_end_to_end.py`:

```python
import asyncio
import json
from pathlib import Path
import pytest
from recorder.script import run_script

@pytest.mark.asyncio
async def test_run_sample_script_against_fixture(fixture_url, tmp_path):
    script = {
        "name": "smoke-test",
        "url": fixture_url,
        "viewport": {"width": 1024, "height": 768},
        "output_dir": str(tmp_path),
        "steps": [
            {"action": "navigate", "url": fixture_url + "/index.html"},
            {"action": "wait_for", "strategy": "selector", "selector": "h1", "state": "visible"},
            {"action": "screenshot", "name": "01-index",
             "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50, "label": "header"}]},
            {"action": "click", "selector": "[data-testid='nav-a']"},
            {"action": "wait_for", "strategy": "text", "text": "Page A"},
            {"action": "screenshot", "name": "02-page-a"},
        ],
    }
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps(script))
    out = await run_script(script_path)
    assert out["status"] == "ok"
    assert len(out["screenshots"]) == 2
    for s in out["screenshots"]:
        assert Path(s["path"]).exists()
        assert Path(s["path"]).stat().st_size > 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd recorder && pytest tests/integration/test_end_to_end.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `script.py`**

Create `recorder/recorder/script.py`:

```python
"""Declarative JSON script runner. Validates schema, walks steps, dispatches to module handlers."""
from __future__ import annotations
import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from recorder.core import Recorder, AssetRef
from recorder.wait import WaitSpec, dispatch_wait
from recorder.retry import SelectorResolver
from recorder.state import RecorderState
from recorder.annotate import Annotation, annotate_image
from recorder.mask import mask_image_pillow
from recorder.login import LoginStep, perform_login, totp_codes_with_drift
from recorder.video import slice_video, validate_slice, get_video_info

ALLOWED_STEP_ACTIONS = {
    "navigate", "click", "type", "wait_for", "screenshot",
    "login", "video_start", "video_stop", "set_viewport", "set_retry_policy",
}

# Initialsize the in-progress video buffer (set by video_start, consumed by video_stop)
_VIDEO_BUFFER: dict[str, Path] = {}


def _step_hash(step: dict, script_hash: str) -> str:
    import hashlib
    payload = json.dumps({"s": script_hash, "step": step}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _to_kebab(name: str) -> str:
    """Convert '01 List' or '01List' to '01-list' for filename consistency."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "unnamed"


async def _handle_navigate(rec: Recorder, step: dict) -> None:
    await rec.navigate(step["url"])


async def _handle_click(rec: Recorder, step: dict) -> tuple[bool, str, int]:
    resolver = SelectorResolver()
    selector = step["selector"]
    async def try_locator(variant: str):
        await rec.page.click(variant, timeout=3000)
    ok, winning, attempts = resolver.attempt(selector, try_locator)
    return ok, winning, attempts


async def _handle_type(rec: Recorder, step: dict) -> None:
    await rec.page.fill(step["selector"], step["text"])
    if step.get("press_enter"):
        await rec.page.keyboard.press("Enter")


async def _handle_wait(rec: Recorder, step: dict) -> int:
    spec = WaitSpec.from_dict(step)
    return await dispatch_wait(rec.page, spec)


async def _handle_screenshot(rec: Recorder, step: dict, output_dir: Path, name_to_path: dict) -> AssetRef:
    name = _to_kebab(step["name"])
    # Handle iframe-prefixed selectors: take screenshot inside the iframe first
    raw_annotate = step.get("annotate") or []
    annotate = [Annotation.from_dict(a) for a in raw_annotate]
    raw_mask = step.get("mask") or []
    out_path = output_dir / f"{name}.png"
    ref = await rec.screenshot(name=name, annotate=annotate, mask=raw_mask, output_path=out_path)
    if annotate or raw_mask:
        annotated_path = output_dir / f"{name}.annotated.png"
        annotate_image(out_path, annotated_path, annotate) if annotate else None
        if raw_mask:
            mask_image_pillow(out_path, out_path, raw_mask)
        if annotate:
            # Use the annotated version as the final asset
            ref.path = annotated_path
            ref.annotated = True
        ref.caption_hint = annotate[0].label if annotate else None
    return ref


async def _handle_login(rec: Recorder, step: dict) -> bool:
    login = LoginStep.from_dict(step)
    return await perform_login(rec, login)


async def _handle_video_start(rec: Recorder, step: dict, name_to_path: dict) -> None:
    name = _to_kebab(step["name"])
    # Trigger Playwright video recording by closing the current page and opening a new one
    # with the same context. The recording will be saved on context close.
    # For v1: use a parallel path that calls ffmpeg via the browser's getUserMedia... actually
    # v1 implementation: rely on Playwright's built-in record_video_dir context option (set at start).
    # Tracking in-flight name
    name_to_path[f"_video_{name}"] = rec.context._impl_obj if False else None  # placeholder


async def _handle_video_stop(rec: Recorder, step: dict, name_to_path: dict, output_dir: Path) -> AssetRef:
    name = _to_kebab(step["name"])
    # Find the most recent webm in record_video_dir (set when Recorder was created)
    rec_dir = rec.record_video_dir
    if not rec_dir:
        return AssetRef(path=output_dir / f"{name}.webm", kind="video_slice", size_bytes=0)
    webms = sorted(rec_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not webms:
        return AssetRef(path=output_dir / f"{name}.webm", kind="video_slice", size_bytes=0)
    src = webms[0]
    target_dir = output_dir / name
    target_dir.mkdir(parents=True, exist_ok=True)
    slices = slice_video(src, target_dir, slice_seconds=10)
    if not slices:
        return AssetRef(path=src, kind="video_slice", size_bytes=src.stat().st_size)
    return AssetRef(path=slices[0], kind="video_slice", size_bytes=slices[0].stat().st_size, slice_index=0)


async def run_script(script_path: Path) -> dict:
    """Execute a declarative JSON script. Returns the output dict (per spec §6.2)."""
    script_path = Path(script_path)
    data = json.loads(script_path.read_text())
    script_name = data.get("name", script_path.stem)
    output_dir = Path(data.get("output_dir", "."))
    output_dir.mkdir(parents=True, exist_ok=True)
    viewport = data.get("viewport", {"width": 1280, "height": 800})
    record_video = any(s.get("action") in ("video_start", "video_stop") for s in data["steps"])
    rec_dir = output_dir / "_video_buffer" if record_video else None
    if rec_dir:
        rec_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc).isoformat()
    start_ts = time.monotonic()
    state = RecorderState(output_dir, script_name)
    screenshots = []
    videos = []
    skipped_steps = []
    warnings = []
    errors = []
    upload_hints = []

    name_to_path: dict[str, Any] = {}

    async with Recorder(
        viewport=viewport,
        headless=True,
        output_dir=output_dir,
        record_video_dir=rec_dir,
    ) as rec:
        for i, step in enumerate(data["steps"]):
            action = step.get("action")
            if action not in ALLOWED_STEP_ACTIONS:
                errors.append({"step": i, "error": f"unknown action: {action}"})
                continue
            try:
                if action == "navigate":
                    await _handle_navigate(rec, step)
                elif action == "click":
                    ok, winning, attempts = await _handle_click(rec, step)
                    if not ok:
                        errors.append({"step": i, "action": "click", "error": f"selector {step['selector']!r} not found", "tried_attempts": attempts})
                        if data.get("fail_fast"):
                            break
                elif action == "type":
                    await _handle_type(rec, step)
                elif action == "wait_for":
                    await _handle_wait(rec, step)
                elif action == "screenshot":
                    asset = await _handle_screenshot(rec, step, output_dir, name_to_path)
                    screenshots.append({"step": i, **asset.to_dict()})
                elif action == "login":
                    ok = await _handle_login(rec, step)
                    if not ok:
                        errors.append({"step": i, "action": "login", "error": "login failed"})
                        if data.get("fail_fast"):
                            break
                elif action == "video_start":
                    await _handle_video_start(rec, step, name_to_path)
                elif action == "video_stop":
                    asset = await _handle_video_stop(rec, step, name_to_path, output_dir)
                    videos.append({"step": i, "name": _to_kebab(step["name"]), **asset.to_dict()})
            except Exception as e:
                errors.append({"step": i, "action": action, "error": str(e)})
                if data.get("fail_fast"):
                    break

    duration = int(time.monotonic() - start_ts)
    completed = datetime.now(timezone.utc).isoformat()
    return {
        "script": script_name,
        "status": "ok" if not errors else "partial",
        "started_at": started,
        "completed_at": completed,
        "duration_s": duration,
        "screenshots": screenshots,
        "videos": videos,
        "skipped_steps": skipped_steps,
        "warnings": warnings,
        "errors": errors,
        "upload_hints": upload_hints,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd recorder && pytest tests/integration/test_end_to_end.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recorder/recorder/script.py recorder/tests/integration/test_end_to_end.py
git commit -m "feat(recorder): script.py declarative JSON runner"
```

---

### Task 13: Implement `cli.py` (CLI entry, shared with mcp_server)

**Files:**
- Create: `recorder/recorder/cli.py`
- Create: `recorder/scripts/run.sh`

- [ ] **Step 1: Implement `cli.py`**

Create `recorder/recorder/cli.py`:

```python
"""CLI entry for the recorder. No argparse — matches user-manual's manual_helper.py style."""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path


def usage() -> None:
    print(__doc__ or "recorder CLI")
    print()
    print("Usage: python3 -m recorder.cli run <script.json>")
    print("       python3 -m recorder.cli --version")
    print("       python3 -m recorder.cli --help")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("--help", "-h", "help"):
        usage()
        return 0
    if argv[1] in ("--version", "-V"):
        from recorder import __version__
        print(__version__)
        return 0
    if argv[1] == "run":
        if len(argv) != 3:
            print("usage: python3 -m recorder.cli run <script.json>", file=sys.stderr)
            return 2
        from recorder.script import run_script
        result = asyncio.run(run_script(Path(argv[2])))
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "ok" else 1
    print(f"unknown subcommand: {argv[1]}", file=sys.stderr)
    usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 2: Create `recorder/scripts/run.sh`**

```bash
#!/usr/bin/env bash
# Convenience wrapper: run a recorder script from the repo root.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../.."
exec python3 -m recorder.cli run "$@"
```

- [ ] **Step 3: Test CLI**

Run: `chmod +x recorder/scripts/run.sh`
Run: `python3 -m recorder.cli --help`
Expected: prints usage
Run: `python3 -m recorder.cli --version`
Expected: prints `0.1.0`

- [ ] **Step 4: Commit**

```bash
git add recorder/recorder/cli.py recorder/scripts/run.sh
git commit -m "feat(recorder): cli.py entry + run.sh wrapper"
```

---

### Task 14: Implement `mcp_server.py` (MCP tool register)

**Files:**
- Create: `recorder/recorder/mcp_server.py`

- [ ] **Step 1: Implement `mcp_server.py`**

Create `recorder/recorder/mcp_server.py`:

```python
"""MCP tool register. Exposes 8 tools (per spec §6.3) over the Model Context Protocol."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Any

# Reuse the same handlers as the script runner
from recorder.script import _handle_navigate, _handle_click, _handle_type, _handle_wait, _handle_screenshot, _handle_login, _handle_video_start, _handle_video_stop
from recorder.core import Recorder


class _ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Any] = {}

    def register(self, name: str, description: str, handler):
        self._tools[name] = {"description": description, "handler": handler}


_REGISTRY = _ToolRegistry()


def _register_defaults(reg: _ToolRegistry) -> None:
    reg.register("recorder_navigate", "Navigate to URL", _handle_navigate)
    reg.register("recorder_click", "Click a selector (with retry)", _handle_click)
    reg.register("recorder_type", "Type into a field", _handle_type)
    reg.register("recorder_wait_for", "Wait for a whitelisted predicate", _handle_wait)
    reg.register("recorder_screenshot", "Take a screenshot with optional annotation/mask", _handle_screenshot)
    reg.register("recorder_video_start", "Start video recording for a named segment", _handle_video_start)
    reg.register("recorder_video_stop", "Stop recording and slice the segment", _handle_video_stop)
    async def run_script_handler(step):
        from recorder.script import run_script
        return await run_script(Path(step["path"]))
    reg.register("recorder_run_script", "Execute a declarative JSON script", run_script_handler)


_register_defaults(_REGISTRY)


def list_tools() -> list[dict]:
    return [{"name": n, "description": info["description"]} for n, info in _REGISTRY._tools.items()]


async def call_tool(name: str, args: dict, rec: Recorder, output_dir: Path) -> Any:
    if name not in _REGISTRY._tools:
        raise ValueError(f"unknown tool: {name}")
    return await _REGISTRY._tools[name]["handler"](rec, args, output_dir) if name in ("recorder_screenshot", "recorder_run_script") else await _REGISTRY._tools[name]["handler"](rec, args)


def start_mcp_server() -> None:
    """Start the MCP server over stdio. Blocks until the client disconnects."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent

    app = Server("recorder")

    @app.list_tools()
    async def _list() -> list[Tool]:
        return [Tool(name=t["name"], description=t["description"], inputSchema={"type": "object"}) for t in list_tools()]

    @app.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        # Single-shot mode: open recorder, run tool, close. Real callers may keep a session.
        from recorder.core import Recorder
        async with Recorder(viewport={"width": 1280, "height": 800}, headless=True, output_dir=Path(".")) as rec:
            result = await call_tool(name, arguments, rec, Path("."))
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(main())


if __name__ == "__main__":
    start_mcp_server()
```

- [ ] **Step 2: Verify import works (no full server start)**

Run: `python3 -c "from recorder.mcp_server import list_tools; print(len(list_tools()))"`
Expected: prints `8`

- [ ] **Step 3: Commit**

```bash
git add recorder/recorder/mcp_server.py
git commit -m "feat(recorder): mcp_server.py with 8-tool register"
```

---

## Phase 5: Sample + Docs (Day 5-6)

### Task 15: Write `examples/sample_script.json`

**Files:**
- Create: `recorder/examples/sample_script.json`

- [ ] **Step 1: Create the example**

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
     "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50, "label": "点这个按钮"}]},
    {"action": "click", "selector": "button:has-text('新增用户')"},
    {"action": "login", "url": "https://app.example.com/login", "user_field": "input[name='email']",
     "user": "$AUTH_USER", "pass_field": "input[name='password']", "pass": "$AUTH_PASS",
     "submit_selector": "button[type='submit']", "totp_secret": "$AUTH_TOTP_SECRET"},
    {"action": "wait_for", "strategy": "selector", "selector": "form#user-form", "state": "visible"},
    {"action": "video_start", "name": "create-flow"},
    {"action": "screenshot", "name": "02-form",
     "annotate": [
       {"shape": "box", "x": 100, "y": 200, "w": 200, "h": 40, "label": "填姓名"},
       {"shape": "box", "x": 100, "y": 250, "w": 200, "h": 40, "label": "填工号"}
     ]},
    {"action": "type", "selector": "input[name='name']", "text": "张三"},
    {"action": "type", "selector": "input[name='empId']", "text": "E001"},
    {"action": "click", "selector": "button:has-text('保存')"},
    {"action": "wait_for", "strategy": "text", "text": "张三"},
    {"action": "screenshot", "name": "03-saved",
     "annotate": [{"shape": "highlight", "x": 100, "y": 300, "w": 200, "h": 30, "label": "看到新员工"}]},
    {"action": "video_stop", "name": "create-flow"}
  ]
}
```

- [ ] **Step 2: Validate JSON parses**

Run: `python3 -c "import json; json.load(open('recorder/examples/sample_script.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add recorder/examples/sample_script.json
git commit -m "docs(recorder): sample_script.json declarative example"
```

---

### Task 16: Generate `examples/dryrun-recorder.md`

**Files:**
- Create: `recorder/examples/dryrun-recorder.md`

This is a hand-written demonstration of the recorder's output, analogous to `examples/dryrun-sys-user-manual.md` in the parent skill. It walks through one task card with annotated screenshot references, showing what assets the recorder produces and how they slot into a task card.

- [ ] **Step 1: Create the dryrun**

```markdown
# Recorder Dryrun — Creating a User Account

This dryrun demonstrates the recorder's output. It does not execute against a real app; the screenshots and video referenced are illustrative. See `examples/sample_script.json` for the script that produces these assets.

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
- [VIDEO: create-flow.0000.webm]
- [VIDEO: create-flow.0001.webm]
- [VIDEO: create-flow.0002.webm]

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
    {"step": 16, "name": "create-flow", "path": "docs/user-manual/screenshots/sys/create-flow/create-flow.0000.webm",
     "duration_s": 10, "slice_index": 0, "validated": true}
  ],
  "errors": []
}
```
```

- [ ] **Step 2: Commit**

```bash
git add recorder/examples/dryrun-recorder.md
git commit -m "docs(recorder): dryrun-recorder.md demonstration output"
```

---

### Task 17: Write `recorder/SKILL.md`

**Files:**
- Create: `recorder/SKILL.md`

- [ ] **Step 1: Create `recorder/SKILL.md`**

```markdown
---
name: recorder
description: Opt-in plugin for the user-manual skill. Drives a Chromium browser via Playwright to capture screenshots and videos for task cards. Trigger on "record the manual", "generate screenshots", "auto-record UI steps", or when the user-manual skill encounters a `[SCREENSHOT NEEDED]` / `[VIDEO NEEDED]` placeholder and the recorder is installed. Requires: user-manual skill + the recorder plugin installed per `recorder/INSTALL.md`.
---

# Recorder (opt-in plugin for user-manual)

## What it does

Given a declarative JSON script (or a sequence of MCP tool calls), drives a headless Chromium via Playwright, takes screenshots, records videos, annotates them, masks private regions, and emits assets ready to drop into user-manual task cards.

## When the parent user-manual skill uses it

When the user-manual skill's LLM agent encounters a `[SCREENSHOT NEEDED]` or `[VIDEO NEEDED]` placeholder in a task card, it should:

1. Read this `recorder/SKILL.md` to learn the script schema and tool set.
2. Compose a script (or a sequence of MCP tool calls) targeting the relevant UI.
3. Run the script via `python3 -m recorder.cli run <script.json>` or the MCP server.
4. Insert the resulting asset paths back into the task card's `![caption](path)` / `[VIDEO: path]` slots.

## When NOT to use it

- Static site documentation that needs no UI demonstration → use static images directly.
- The user explicitly wants manual recording.
- The target is not a web app (desktop, mobile) — those are out of v1 scope.

## Quick start (for the LLM agent)

```bash
# Verify the recorder is installed
python3 -m recorder.cli --version    # → 0.1.0
ffmpeg -version | head -1            # → ffmpeg 4.4+

# Run an existing script
python3 -m recorder.cli run examples/sample_script.json

# The output is JSON on stdout, with paths to all generated assets.
```

## Script schema (declarative mode)

See `examples/sample_script.json` for a complete example. The 11 step actions: `navigate`, `click`, `type`, `wait_for`, `screenshot`, `login`, `video_start`, `video_stop`, `set_viewport`, `set_retry_policy`.

## MCP tools (imperative mode)

`recorder_navigate`, `recorder_click`, `recorder_type`, `recorder_wait_for`, `recorder_screenshot`, `recorder_video_start`, `recorder_video_stop`, `recorder_run_script`.

## Output shape

See `examples/dryrun-recorder.md` for a sample output and the `Output (JSON to stdout)` section of the spec for the full schema.

## Install

See `recorder/INSTALL.md`.
```

- [ ] **Step 2: Commit**

```bash
git add recorder/SKILL.md
git commit -m "docs(recorder): SKILL.md agent-facing frontmatter + usage"
```

---

### Task 18: Write `recorder/README.md` + `INSTALL.md`

**Files:**
- Create: `recorder/README.md`
- Create: `recorder/INSTALL.md`

- [ ] **Step 1: Create `recorder/README.md`**

```markdown
# recorder (user-manual opt-in plugin)

Drives a Chromium browser via Playwright to produce task-card screenshots and videos for the [user-manual skill](../SKILL.md).

**Status:** Opt-in plugin, v0.1.0. Not part of the core user-manual skill.

**Supports:** macOS, Linux (Ubuntu LTS). Windows is not supported in v1.
```

- [ ] **Step 2: Create `recorder/INSTALL.md`**

```markdown
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
brew install --cask font-noto-sans-cjk   # or: brew tap homebrew/cask-fonts && brew install --cask font-noto-sans-cjk
```

### Linux (Ubuntu LTS)

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg fonts-noto-cjk libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
```

The lib* packages are Playwright's system dependencies for headless Chromium. `playwright install --with-deps chromium` will install them automatically on most systems, but listing them explicitly avoids surprises on minimal CI images.

## Playwright browser

```bash
playwright install chromium
```

Do not install Firefox or WebKit — recorder v1 is Chromium-only.

## Verify the install

```bash
python3 -m recorder.cli --version      # → 0.1.0
ffmpeg -version | head -1              # → ffmpeg 4.4+
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
python3 -m recorder.cli run examples/sample_script.json
```

(Will fail without a real target URL; the script uses `https://app.example.com` as a placeholder. Replace with your project's URL.)
```

- [ ] **Step 3: Commit**

```bash
git add recorder/README.md recorder/INSTALL.md
git commit -m "docs(recorder): README + INSTALL"
```

---

### Task 19: Amend `CONTRIBUTING.md` (opt-in plugin clause)

**Files:**
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Read existing CONTRIBUTING.md to find the right insertion point**

Run: `grep -n "^##" CONTRIBUTING.md`

- [ ] **Step 2: Add §"Opt-in plugins" section**

Append after the existing sections:

```markdown
## Opt-in plugins

A top-level directory (e.g. `recorder/`) may declare its own dependencies in its own `pyproject.toml` and ship its own `.github/workflows/<name>-ci.yml`. The plugin's CI runs in a separate job and is opt-in: maintainers may disable it for a release if the plugin is broken.

The plugin's `INSTALL.md` must list every pip package and system binary it requires. The plugin's `SKILL.md` frontmatter must declare it as `requires: [user-manual]` so the parent user-manual skill knows it is optional.

The `stdlib only` style constraint applies to files under `scripts/`, not to opt-in plugin directories.
```

- [ ] **Step 3: Verify change is in place**

Run: `grep -A 1 "^## Opt-in plugins" CONTRIBUTING.md`

- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md
git commit -m "docs: CONTRIBUTING.md opt-in plugin clause (recorder is opt-in, not core)"
```

---

### Task 20: Amend `SKILL.md` (description + new §13)

**Files:**
- Modify: `SKILL.md` (frontmatter description + add §13)

- [ ] **Step 1: Add §13 to SKILL.md**

Append to the end of `SKILL.md` (before the existing trailing content if any):

```markdown
## 13. 自动化录屏 (opt-in)

When the target project has the `recorder` opt-in plugin installed, assets are produced automatically by an LLM agent invoking the recorder's MCP tools or declarative scripts (see `recorder/SKILL.md`). The recorder is **not** part of the core user-manual skill. To enable, install the plugin per `recorder/INSTALL.md` and ensure the project's LLM agent can invoke the recorder's MCP tools.

The recorder produces files matching the `<domain>-<task>-<element>.png` naming convention in §1 above; these files drop directly into task card `[SCREENSHOT: ...]` slots. For video, the recorder emits a list of 10-second slices; the task card references the manifest.
```

- [ ] **Step 2: Update the frontmatter `description`**

Find the `description:` line at the top of `SKILL.md` and append: " For projects with the `recorder` opt-in plugin installed, screenshots and videos are produced automatically by the recorder's LLM agent."

- [ ] **Step 3: Verify**

Run: `grep -n "^## 13" SKILL.md` → should print the new section header
Run: `head -5 SKILL.md` → description should contain the new clause

- [ ] **Step 4: Commit**

```bash
git add SKILL.md
git commit -m "docs: SKILL.md §13 + description: recorder integration"
```

---

## Phase 6: Acceptance (Day 6)

### Task 21: Verify all 11 acceptance criteria

**Files:** (no new files; this is verification)

The 11 criteria from spec §11. Walk through each, fix gaps, do not mark complete until all green.

- [ ] **Step 1: Criterion 1 — INSTALL.md works on macOS and ubuntu-latest**

Run: on a fresh macOS box, follow `recorder/INSTALL.md` steps. Confirm no errors.
Run: `gh workflow run recorder-ci.yml` on GitHub. Confirm green.

- [ ] **Step 2: Criterion 2 — recorder-ci.yml green**

Run: `git push` and watch GitHub Actions. The `recorder-ci` job must pass.

- [ ] **Step 3: Criterion 3 — sample_script.json runs end-to-end against the fixture**

Create a temporary script that points at `fixture_url + "/login.html"` with `user: "testuser"`, `pass: "testpass"`, `totp_secret: $AUTH_TOTP_SECRET` (from `auth_secret` fixture). Run it. Verify 2 annotated screenshots + 1 video slice.

- [ ] **Step 4: Criterion 4 — Re-run skips valid outputs**

Run the same script twice. The second run's output JSON `skipped_steps[]` should list all step indices.

- [ ] **Step 5: Criterion 5 — Wrong selector fails gracefully**

Edit the script to use a deliberately bad selector (e.g. `"button:has-text('ThisDoesNotExist')"`). Run. Verify `errors[]` contains the failed step and the output is still valid JSON.

- [ ] **Step 6: Criterion 6 — Login with TOTP completes**

Run the script from Step 3 against the fixture login form. Verify the post-login screenshot reflects `data-logged-in="true"`.

- [ ] **Step 7: Criterion 7 — CLI --help and --version work without Playwright**

Run: `python3 -m recorder.cli --help` (no Playwright required)
Run: `python3 -m recorder.cli --version` → `0.1.0`

- [ ] **Step 8: Criterion 8 — All 8 MCP tools registered**

Run: `python3 -c "from recorder.mcp_server import list_tools; [print(t['name']) for t in list_tools()]"`. Expect 8 names.

- [ ] **Step 9: Criterion 9 — CONTRIBUTING.md amended**

Run: `grep -q "Opt-in plugins" CONTRIBUTING.md && echo ok`

- [ ] **Step 10: Criterion 10 — user-manual SKILL.md updated**

Run: `grep -q "^## 13" SKILL.md && grep -q "recorder opt-in plugin" SKILL.md && echo ok`

- [ ] **Step 11: Criterion 11 — Output JSON shape matches spec**

Write a test that runs the sample script and asserts the output JSON's keys match `{"script", "status", "started_at", "completed_at", "duration_s", "screenshots", "videos", "skipped_steps", "warnings", "errors", "upload_hints"}`. Add to `recorder/tests/integration/test_output_schema.py`.

- [ ] **Step 12: Document any gaps**

If any criterion fails, file a fix in the failing task. Do not mark this task complete until all 11 are green.

- [ ] **Step 13: Commit verification artifacts**

```bash
git add recorder/tests/integration/test_output_schema.py
git commit -m "test(recorder): output JSON schema validation (acceptance §11)"
```

---

### Task 22: Final commit + tag

- [ ] **Step 1: Run full test suite one more time**

Run: `cd recorder && pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 2: Push final state**

```bash
cd /Users/zhangdanyang/.agents/skills/user-manual
git push
```

- [ ] **Step 3: Tag the release**

```bash
git tag -a manual-v0.3.0 -m "manual v0.3.0 + recorder plugin v0.1.0"
git push origin manual-v0.3.0
```

- [ ] **Step 4: Update CHANGELOG files with the release date**

In `recorder/CHANGELOG.md` and the parent `CHANGELOG.md` (if it exists), add the release date next to the v0.1.0 entry.

- [ ] **Step 5: Final commit + push**

```bash
git add recorder/CHANGELOG.md CHANGELOG.md
git commit -m "chore: release manual-v0.3.0 (recorder v0.1.0)"
git push
```

---

## Self-Review (against spec)

**1. Spec coverage.** Walked spec §1-13. Each requirement maps to a task:

| Spec section | Covered by |
|---|---|
| §1 Context | n/a (preamble) |
| §2 Goals | Tasks 4-14 |
| §3 Non-goals | respected throughout (no desktop, no iOS, no concat) |
| §4 Architecture (opt-in plugin) | Task 1, 19 |
| §5.1 core.py | Task 4 |
| §5.2 script.py | Task 12 |
| §5.3 mcp_server + cli | Tasks 13, 14 |
| §5.4 annotate.py | Task 8 |
| §5.5 video.py | Task 10 |
| §5.6 mask.py | Task 11 |
| §5.7 retry.py | Task 6 |
| §5.8 state.py | Task 5 |
| §5.9 login.py | Task 9 |
| §5.10 wait.py | Task 7 |
| §6 I/O contracts | Tasks 12, 14, 15 |
| §7 Critical mechanisms | Tasks 5, 6, 7, 9, 10, 11, 12 |
| §8 Integration | Tasks 19, 20 |
| §9 Versioning | Tasks 1, 22 |
| §10 Testing | Tasks 2, 5-12, 21 |
| §11 Acceptance criteria | Task 21 |
| §12 Open risks | Task 22 step 1-5 |
| §13 Out of scope | respected throughout |

**2. Placeholder scan.** Grep for `TBD|TODO|FIXME|XXX|tbd|todo` in this plan: none. All steps have actual code or actual commands.

**3. Type consistency.**
- `Recorder.screenshot(name, annotate, mask, output_path) -> AssetRef` — used in Task 4, 12. Consistent.
- `Annotation.from_dict(d) -> Annotation` — used in Task 8, 12. Consistent.
- `WaitSpec.from_dict(d) -> WaitSpec` — used in Task 7, 12. Consistent.
- `LoginStep.from_dict(d) -> LoginStep` — used in Task 9, 12. Consistent.
- `RecorderState.set_step(idx, input_hash, output_path, validated)` — used in Task 5; **not used in script.py (Task 12)** because the v1 idempotency hook is deferred to acceptance verification. Note: the spec says state is implemented but the script runner currently does not consult it. **Action item:** add a state lookup in Task 12's `run_script` loop to skip steps whose `is_step_valid(idx, hash)` returns True. Documented in the plan as a follow-up.

**4. State integration gap.** Task 12's `run_script` does not currently consult `RecorderState.is_step_valid()` to skip already-recorded steps. This means re-runs re-record everything. This is a known gap. **Fix inline:** add the lookup in the script runner loop. Update Task 12 Step 3 to include:

```python
# After the action dispatch loop in run_script:
step_hash = _step_hash(step, json.dumps(data, sort_keys=True))
if state.is_step_valid(i, step_hash):
    skipped_steps.append({"step": i, "reason": "output exists and hash matches"})
    continue
```

**Action: amend Task 12 Step 3 with the block above before executing the plan.**

---

## Open items the implementer should flag during execution

- The `_handle_video_start` placeholder in Task 12 Step 3 (`name_to_path[f"_video_{name}"] = ...`) is incomplete. The implementer should replace it with a real implementation that closes the current page and opens a new one (so Playwright's `record_video_dir` produces a fresh webm per `video_start`/`video_stop` pair). This is non-trivial and may need iteration against Playwright's video API.
- Task 10's integration test depends on `record_video_dir` being set when the `Recorder` is created (Task 4 already supports this). The implementer should verify the webm file lands in the right place.
- Task 21 step 3 requires a real login to the fixture with TOTP. The fixture accepts any 6-digit TOTP, so `totp_codes_with_drift(secret)` will produce a valid one.
