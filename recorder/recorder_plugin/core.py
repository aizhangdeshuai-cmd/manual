"""Playwright session wrapper. The single browser session for all recorder operations."""
from __future__ import annotations
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
        d: dict[str, Any] = {
            "path": str(self.path),
            "kind": self.kind,
            "size_bytes": self.size_bytes,
        }
        if self.width:
            d["width"] = self.width
        if self.height:
            d["height"] = self.height
        if self.selector_used:
            d["selector_used"] = self.selector_used
        if self.caption_hint:
            d["caption_hint"] = self.caption_hint
        if self.annotated:
            d["annotated"] = True
        if self.slice_index is not None:
            d["slice_index"] = self.slice_index
        d.update(self.extra)
        return d


class Recorder:
    """Single Playwright browser session. All recorder operations go through this."""

    def __init__(
        self,
        viewport: dict,
        headless: bool,
        output_dir: Path,
        record_video_dir: Path | None = None,
    ):
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
        # v0.3.3: track the most recent absolute base URL so _handle_video_stop
        # can re-navigate the post-close fresh page using urljoin. Set on
        # every Recorder.navigate().
        self._last_base_url: str = ""

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
        context_kwargs: dict[str, Any] = {
            "viewport": {"width": self.viewport["width"], "height": self.viewport["height"]},
            "device_scale_factor": self.viewport.get("device_scale", 1),
        }
        if self.record_video_dir:
            context_kwargs["record_video_dir"] = str(self.record_video_dir)
            context_kwargs["record_video_size"] = {
                "width": self.viewport["width"],
                "height": self.viewport["height"],
            }
        # v0.3.8 fix: register the cursor/HUD listener as a context-level
        # addInitScript BEFORE creating any page. The listener then runs in
        # every new document from the very first navigation, including the
        # navigate-to-app step that happens BEFORE video_start. If we
        # registered it on the page AFTER navigate (the v0.3.7 mistake),
        # it would only fire on the NEXT navigation, which never happens
        # in a single video segment — so the cursor overlay would never
        # track the user's interactions.
        from recorder_plugin.cursor import LISTENER_JS
        self._context = await self._browser.new_context(**context_kwargs)
        try:
            await self._context.add_init_script(LISTENER_JS)
        except Exception as e:
            # Don't crash recording on cursor failure — just log and
            # continue without a cursor overlay.
            import sys
            print(
                f"WARNING: cursor listener registration failed "
                f"({type(e).__name__}: {e}); video will not show cursor.",
                file=sys.stderr,
            )
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
        # v0.3.3: Playwright does NOT resolve relative URLs (it errors with
        # "Cannot navigate to invalid URL"). urljoin against the last
        # absolute URL the recorder visited to support "go to /settings" etc.
        from urllib.parse import urljoin
        abs_url = urljoin(self._last_base_url, url) if self._last_base_url else url
        if not (abs_url.startswith("http://") or abs_url.startswith("https://")
                or abs_url.startswith("file://") or abs_url.startswith("about:")):
            raise ValueError(
                f"Recorder.navigate: cannot resolve {url!r} to an absolute URL; "
                f"first navigate must be absolute (got last_base_url={self._last_base_url!r})"
            )
        await self.page.goto(abs_url, wait_until=wait_until)
        self._last_base_url = abs_url

    async def screenshot(self, name: str, annotate: list | None, mask: list | None, output_path: Path) -> AssetRef:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path), full_page=False)
        return AssetRef(path=path, kind="screenshot", size_bytes=path.stat().st_size)
