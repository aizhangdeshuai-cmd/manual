import asyncio
import json
from pathlib import Path
import pytest
from recorder_plugin.script import run_script


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
    assert out["status"] == "ok", f"errors: {out['errors']}"
    assert len(out["screenshots"]) == 2
    for s in out["screenshots"]:
        assert Path(s["path"]).exists(), f"missing: {s['path']}"
        assert Path(s["path"]).stat().st_size > 1000
    # The annotated screenshot should be a separate file
    annotated = [s for s in out["screenshots"] if s.get("annotated")]
    assert len(annotated) == 1
    assert "annotated" in str(annotated[0]["path"])


@pytest.mark.asyncio
async def test_run_script_fails_gracefully_on_bad_selector(fixture_url, tmp_path):
    script = {
        "name": "bad-selector",
        "url": fixture_url,
        "viewport": {"width": 800, "height": 600},
        "output_dir": str(tmp_path),
        "fail_fast": False,
        "steps": [
            {"action": "navigate", "url": fixture_url + "/index.html"},
            {"action": "click", "selector": "button:has-text('ThisDoesNotExist')"},
        ],
    }
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps(script))
    out = await run_script(script_path)
    assert out["status"] == "partial"
    click_errors = [e for e in out["errors"] if e.get("action") == "click"]
    assert len(click_errors) >= 1
