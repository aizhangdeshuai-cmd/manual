"""Comprehensive end-to-end self-test for recorder v0.2.1.

Simulates what a real LLM agent would do: build a script, run it, inspect
the output, verify the v0.2.1 bug fixes are working, test idempotency, and
check the CLI / MCP / module surface.

This is the test the feedback agent will run. If it passes here, the
recorder is shippable from a functional standpoint.

Run from inside the recorder/ directory:
    python3 -m pytest tests/integration/test_self_test.py -v -s
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
import pytest

# Make the package importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# === Imports first — catches ImportError for any module ===

def test_all_modules_importable():
    """Every recorder_plugin module imports cleanly."""
    from recorder_plugin import __version__
    assert __version__ == "0.2.1", f"expected version 0.2.1, got {__version__}"

    import recorder_plugin.core
    import recorder_plugin.state
    import recorder_plugin.retry
    import recorder_plugin.wait
    import recorder_plugin.annotate
    import recorder_plugin.login
    import recorder_plugin.video
    import recorder_plugin.mask
    import recorder_plugin.script
    import recorder_plugin.cli
    import recorder_plugin.mcp_server
    import recorder_plugin.vision  # v1.1
    # No exceptions = pass


def test_cli_help_and_version():
    """CLI works without Playwright initialization."""
    out_help = subprocess.run(
        [sys.executable, "-m", "recorder_plugin.cli", "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "recorder CLI" in out_help.stdout
    assert "recorder_plugin.cli run" in out_help.stdout

    out_ver = subprocess.run(
        [sys.executable, "-m", "recorder_plugin.cli", "--version"],
        capture_output=True, text=True, check=True,
    )
    assert out_ver.stdout.strip() == "0.2.1"


def test_mcp_tools_count():
    """MCP server exposes all 8 tools per spec §6.3."""
    from recorder_plugin.mcp_server import list_tools
    tools = list_tools()
    expected = {
        "recorder_navigate", "recorder_click", "recorder_type",
        "recorder_wait_for", "recorder_screenshot",
        "recorder_video_start", "recorder_video_stop", "recorder_run_script",
    }
    actual = {t["name"] for t in tools}
    assert actual == expected, f"mismatch: missing={expected-actual}, extra={actual-expected}"
    assert len(tools) == 8


# === End-to-end script run (the meat) ===

@pytest.mark.asyncio
async def test_self_test_full_workflow(fixture_url, tmp_path):
    """Simulate a real LLM agent workflow: build + run + inspect a script
    that exercises every important v0.2.1 feature."""
    script = {
        "name": "self-test-full-workflow",
        "url": fixture_url,
        "viewport": {"width": 1024, "height": 768},
        "output_dir": str(tmp_path),
        "auth_env": [],  # We won't actually log in; just exercise the path
        "steps": [
            # 1. Navigate to index
            {"action": "navigate", "url": fixture_url + "/index.html"},
            {"action": "wait_for", "strategy": "selector", "selector": "h1", "state": "visible"},
            # 2. Screenshot with annotation
            {"action": "screenshot", "name": "01-index",
             "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50, "label": "header"}]},
            # 3. Click nav
            {"action": "click", "selector": "[data-testid='nav-a']"},
            {"action": "wait_for", "strategy": "text", "text": "Page A"},
            # 4. Screenshot after click
            {"action": "screenshot", "name": "02-page-a"},
            # 5. Try a bad selector (should fail gracefully)
            {"action": "click", "selector": "button:has-text('NonExistent')"},
            # 6. Start video
            {"action": "video_start", "name": "demo-flow"},
            # 7. Screenshot during recording
            {"action": "screenshot", "name": "03-during-video"},
            {"action": "wait_for", "strategy": "timeout", "ms": 500},
            # 8. Stop video — v0.2.1 fix should flush webm
            {"action": "video_stop", "name": "demo-flow"},
            # 9. Screenshot after video_stop (proves new page works)
            {"action": "screenshot", "name": "04-after-video"},
        ],
    }
    spath = tmp_path / "script.json"
    spath.write_text(json.dumps(script))
    out = await _run_script_async(spath)

    # === Verify output structure ===
    assert out["script"] == "self-test-full-workflow"
    assert "screenshots" in out
    assert "videos" in out
    assert "errors" in out
    assert "skipped_steps" in out
    assert "warnings" in out

    # === Verify screenshots ===
    screenshot_names = [s.get("path", "").rsplit("/", 1)[-1] for s in out["screenshots"]]
    print(f"\nScreenshots produced: {screenshot_names}")
    # All 4 screenshot steps should have produced files
    for expected in ["01-index", "02-page-a", "03-during-video", "04-after-video"]:
        matching = [s for s in out["screenshots"] if expected in s["path"]]
        assert len(matching) == 1, f"missing {expected}: got {[s['path'] for s in out['screenshots']]}"
        # Annotated 01-index should have a caption_hint
        if expected == "01-index":
            assert matching[0].get("caption_hint") == "header"
        # File must exist and be non-trivial
        p = Path(matching[0]["path"])
        assert p.exists()
        assert p.stat().st_size > 1000, f"{expected} is suspiciously small: {p.stat().st_size}"

    # === Verify the v0.2.1 video fix (the critical bug from feedback) ===
    assert len(out["videos"]) == 1, f"expected 1 video, got {len(out['videos'])}"
    v = out["videos"][0]
    print(f"Video produced: {v['path']} ({v['size_bytes']} bytes)")
    assert v["size_bytes"] > 1000, f"VIDEO STILL BROKEN: {v['size_bytes']} bytes (v0.2.0 bug returns 0)"
    assert Path(v["path"]).exists()
    # The MP4 should be h264
    from recorder_plugin.video import get_video_info
    info = get_video_info(Path(v["path"]))
    assert info["codec"] == "h264", f"expected h264, got {info['codec']}"
    assert info["duration_s"] > 0, f"MP4 has no duration: {info}"

    # === Verify the v0.2.1 slice naming fix ===
    target_dir = tmp_path / "demo-flow"
    slice_files = list(target_dir.glob("*.webm")) + list(target_dir.glob("*.mp4"))
    print(f"Files in target dir: {[f.name for f in slice_files]}")
    for f in slice_files:
        # All files must start with "demo-flow" — no random UUIDs allowed
        assert f.name.startswith("demo-flow"), (
            f"SLICE NAMING BROKEN: {f.name} doesn't start with step name (v0.2.0 bug)"
        )
        assert "@" not in f.name, f"SLICE NAMING BROKEN: {f.name} contains random UUID (v0.2.0 bug)"

    # === Verify graceful failure on bad selector ===
    click_errors = [e for e in out["errors"] if e.get("action") == "click"]
    assert len(click_errors) >= 1, "bad selector should have logged a click error"
    assert "not found" in click_errors[0]["error"].lower()
    # The script should still complete (fail_fast=False by default)
    assert out["status"] == "partial", f"expected partial status with bad selector, got {out['status']}"

    # === Verify all post-video actions ran (page swap worked) ===
    after_video = [s for s in out["screenshots"] if "04-after-video" in s["path"]]
    assert len(after_video) == 1, "screenshot after video_stop should have run on new page"


async def _run_script_async(script_path: Path) -> dict:
    """Run a script via the public API."""
    from recorder_plugin.script import run_script
    return await run_script(script_path)


# === Idempotency self-test ===

@pytest.mark.asyncio
async def test_self_test_idempotency(fixture_url, tmp_path):
    """Run the same script twice; the second run should skip validated steps."""
    script = {
        "name": "idempotency-test",
        "url": fixture_url,
        "viewport": {"width": 800, "height": 600},
        "output_dir": str(tmp_path),
        "steps": [
            {"action": "navigate", "url": fixture_url + "/index.html"},
            {"action": "wait_for", "strategy": "selector", "selector": "h1", "state": "visible"},
            {"action": "screenshot", "name": "01-only"},
        ],
    }
    spath = tmp_path / "script.json"
    spath.write_text(json.dumps(script))

    from recorder_plugin.script import run_script
    out1 = await run_script(spath)
    out2 = await run_script(spath)

    # Second run should skip the validated step
    assert len(out1["skipped_steps"]) == 0
    assert len(out2["skipped_steps"]) > 0, (
        f"second run should skip steps; got skipped_steps={out2['skipped_steps']}"
    )
    # The skipped step should be the screenshot
    skipped_actions = [s for s in out2["skipped_steps"] if "exists and hash matches" in s.get("reason", "")]
    assert len(skipped_actions) >= 1


# === AI vision module self-test (no actual API call) ===

def test_self_test_vision_module_loads():
    """vision module + anthropic SDK import successfully (no API call)."""
    from recorder_plugin.vision import (
        ai_annotate_image, ai_annotate_and_save,
        _encode_image_b64, _build_user_prompt,
        DEFAULT_MODEL,
    )
    # Model should be a Claude vision model
    assert "claude" in DEFAULT_MODEL.lower()
    # Should raise RuntimeError if API key not set (not silently no-op)
    from pathlib import Path
    import tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "s.png"
        Image.new("RGB", (100, 100), "white").save(p)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            ai_annotate_image(p, "test", api_key=None)  # no env, no explicit


# === wait strategy whitelist self-test ===

def test_self_test_wait_strategies_whitelisted():
    """Only the 4 whitelisted strategies are accepted; custom_js is rejected."""
    from recorder_plugin.wait import WaitSpec

    # All 4 whitelisted should parse
    for s in [{"strategy": "selector", "selector": "h1"},
             {"strategy": "text", "text": "Saved"},
             {"strategy": "networkidle"},
             {"strategy": "timeout", "ms": 1000}]:
        spec = WaitSpec.from_dict(s)
        assert spec.strategy == s["strategy"]

    # custom_js rejected with helpful error
    with pytest.raises(ValueError, match="custom_js is not supported"):
        WaitSpec.from_dict({"strategy": "custom_js", "js": "alert(1)"})

    # Unknown strategy rejected
    with pytest.raises(ValueError, match="Unknown wait strategy"):
        WaitSpec.from_dict({"strategy": "potato"})


# === Install manifest self-test ===

def test_self_test_install_log_mentions_anthropic():
    """The user must be able to track what was installed (per their '要下载东西要记录好' rule)."""
    # INSTALL_LOG.md is at the user-manual repo root, NOT inside recorder/
    # recorder/tests/integration/X.py → up 3 = recorder, up 4 = user-manual
    install_log = Path(__file__).resolve().parents[3] / "docs" / "INSTALL_LOG.md"
    text = install_log.read_text()
    assert "anthropic" in text, "anthropic not in INSTALL_LOG — user can't uninstall"


# === Versioning self-test ===

def test_self_test_changelog_documents_v021():
    """CHANGELOG must include v0.2.1 entry so user can trace upgrade path."""
    cl = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
    text = cl.read_text()
    assert "0.2.1" in text
    assert "video" in text.lower()  # at least mentions the video fix
    assert "naming" in text.lower() or "slice" in text.lower()  # or naming fix
