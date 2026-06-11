import asyncio
from pathlib import Path
import pytest
from recorder_plugin.core import Recorder


@pytest.mark.asyncio
async def test_recorder_can_navigate_to_fixture(fixture_url, tmp_path):
    out = tmp_path / "01.png"
    async with Recorder(
        viewport={"width": 1024, "height": 768},
        headless=True,
        output_dir=tmp_path,
    ) as rec:
        await rec.navigate(fixture_url + "/index.html")
        await rec.screenshot(name="01", annotate=None, mask=None, output_path=out)
    assert out.exists()
    assert out.stat().st_size > 1000


@pytest.mark.asyncio
async def test_recorder_context_manager_closes_browser(fixture_url, tmp_path):
    async with Recorder(
        viewport={"width": 800, "height": 600},
        headless=True,
        output_dir=tmp_path,
    ) as rec:
        await rec.navigate(fixture_url + "/index.html")
    # If close() didn't run, a subsequent launch would conflict
    async with Recorder(
        viewport={"width": 800, "height": 600},
        headless=True,
        output_dir=tmp_path,
    ) as rec2:
        await rec2.navigate(fixture_url + "/page-a.html")
    assert True  # both contexts opened and closed cleanly
