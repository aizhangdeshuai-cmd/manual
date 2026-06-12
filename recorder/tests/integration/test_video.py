"""v0.2.1 integration test: video_start/video_stop end-to-end with page-close flush.

Bug fixed: in v0.1.0/v0.2.0, the webm file was created in rec_dir only when the
*page* closed, but the script runner's `async with Recorder` kept the context
(and page) open until the script ended — so video_stop at step N found zero
webm files, returned an empty AssetRef, and the video was completely broken.

v0.2.1 fix: video_stop closes the recording page to flush the webm, processes
it, then opens a fresh page for any subsequent steps.
"""
import asyncio
import json
from pathlib import Path
import pytest
from recorder_plugin.script import run_script


@pytest.mark.asyncio
async def test_video_stop_flushes_webm_by_closing_page(fixture_url, tmp_path):
    script = {
        "name": "video-flush-test",
        "url": fixture_url,
        "viewport": {"width": 800, "height": 600},
        "output_dir": str(tmp_path),
        "steps": [
            {"action": "navigate", "url": fixture_url + "/index.html"},
            {"action": "wait_for", "strategy": "selector", "selector": "h1", "state": "visible"},
            {"action": "video_start", "name": "demo"},
            {"action": "wait_for", "strategy": "timeout", "ms": 500},
            {"action": "video_stop", "name": "demo"},
            # After video_stop, a new page should exist for these steps:
            {"action": "screenshot", "name": "after-video"},
        ],
    }
    spath = tmp_path / "script.json"
    spath.write_text(json.dumps(script))
    out = await run_script(spath)
    # The video must have produced a real MP4 (not a 0-byte placeholder)
    assert len(out["videos"]) == 1, f"expected 1 video, got {out['videos']}"
    v = out["videos"][0]
    assert v["size_bytes"] > 1000, f"video MP4 should be > 1KB, got {v['size_bytes']} bytes"
    assert Path(v["path"]).exists(), f"video path missing: {v['path']}"
    # Slice filenames should use the step name (kebab-case), NOT a random UUID
    slices = sorted((tmp_path / "demo").glob("demo.*.webm"))
    assert len(slices) >= 1, f"expected demo.NNNN.webm slices, got {list((tmp_path / 'demo').glob('*'))}"
    for s in slices:
        assert "demo." in s.name, f"slice has wrong name: {s.name}"
    # The screenshot AFTER video_stop should have worked (proves new page was created)
    after_video = [s for s in out["screenshots"] if "after-video" in str(s.get("path", ""))]
    assert len(after_video) == 1, (
        f"screenshot after video_stop should have run on new page; "
        f"got screenshots: {[s.get('path') for s in out['screenshots']]}"
    )
    assert Path(after_video[0]["path"]).exists()
    assert Path(after_video[0]["path"]).stat().st_size > 1000


@pytest.mark.asyncio
async def test_video_stop_naming_no_random_uuid(fixture_url, tmp_path):
    """Regression: v0.2.0 produced 'page@<uuid>.webm' instead of step name."""
    script = {
        "name": "naming-test",
        "url": fixture_url,
        "viewport": {"width": 800, "height": 600},
        "output_dir": str(tmp_path),
        "steps": [
            {"action": "navigate", "url": fixture_url + "/index.html"},
            {"action": "wait_for", "strategy": "timeout", "ms": 100},
            {"action": "video_start", "name": "create-flow"},
            {"action": "wait_for", "strategy": "timeout", "ms": 300},
            {"action": "video_stop", "name": "create-flow"},
        ],
    }
    spath = tmp_path / "script.json"
    spath.write_text(json.dumps(script))
    out = await run_script(spath)
    # All slice files under target_dir should start with the step name
    target_dir = tmp_path / "create-flow"
    for f in target_dir.iterdir():
        assert f.name.startswith("create-flow"), f"unexpected name: {f.name}"
        # No Playwright random UUID pattern (page@<hex>)
        assert "@" not in f.name, f"found random UUID pattern in {f.name}"
