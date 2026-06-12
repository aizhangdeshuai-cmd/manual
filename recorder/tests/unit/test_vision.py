"""Tests for recorder_plugin.vision — agent-mediated request/response protocol.

v0.2.4: vision is fulfilled by the agent loop, NOT by the recorder.
This test verifies the request/response protocol only — no LLM mocking.
"""
import json
from pathlib import Path
import pytest
from PIL import Image
from recorder_plugin.vision import (
    write_request, list_pending, response_path_for, read_response,
    parse_response_boxes, denormalize_boxes, apply_response,
    REQUEST_PREFIX, RESPONSE_PREFIX,
)


# ---------- Pure-function protocol tests (no PIL, no files) ----------

def test_request_response_path_mapping():
    req = Path(f"/tmp/{REQUEST_PREFIX}demo.json")
    resp = response_path_for(req)
    assert resp.name == f"{RESPONSE_PREFIX}demo.json"
    assert resp.parent == req.parent


def test_parse_response_boxes_happy_path():
    response = {
        "step_name": "demo",
        "boxes": [
            {"label": "新增", "x": 100, "y": 200, "w": 50, "h": 30},
            {"label": "Save", "x": 200, "y": 200, "w": 80, "h": 40},
        ],
    }
    boxes = parse_response_boxes(response)
    assert len(boxes) == 2
    assert boxes[0]["label"] == "新增"
    assert boxes[1]["label"] == "Save"


def test_parse_response_boxes_skips_invalid():
    response = {
        "boxes": [
            {"label": "ok", "x": 0, "y": 0, "w": 10, "h": 10},          # valid
            {"label": "missing_fields", "x": 0},                          # invalid (no y, w, h)
            "not a dict",                                                 # invalid (not dict)
            {"x": 0, "y": 0, "w": 5, "h": 5},                            # valid, no label
        ]
    }
    boxes = parse_response_boxes(response)
    assert len(boxes) == 2


def test_parse_response_boxes_empty_list():
    assert parse_response_boxes({}) == []
    assert parse_response_boxes({"boxes": []}) == []


def test_denormalize_scales_to_pixel_coords():
    boxes = [{"x": 500, "y": 250, "w": 100, "h": 50, "label": "X"}]
    out = denormalize_boxes(boxes, img_w=2000, img_h=1000)
    assert out[0]["x"] == 1000
    assert out[0]["y"] == 250
    assert out[0]["w"] == 200
    assert out[0]["h"] == 50


def test_denormalize_caps_label_length():
    boxes = [{"x": 0, "y": 0, "w": 10, "h": 10, "label": "X" * 100}]
    out = denormalize_boxes(boxes, 100, 100)
    assert len(out[0]["label"]) == 15


# ---------- File-based protocol tests ----------

def test_write_request_creates_file_with_schema(tmp_path):
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    req = write_request(tmp_path, "demo", img, "Find the primary button")
    assert req.exists()
    data = json.loads(req.read_text())
    assert data["step_name"] == "demo"
    assert data["image_path"] == str(img)
    assert data["prompt"] == "Find the primary button"
    assert data["coord_base"] == 1000
    assert "prompt_hint" in data
    assert data["schema_version"] == 1


def test_list_pending_finds_request_files(tmp_path):
    img = tmp_path / "x.png"
    Image.new("RGB", (10, 10), "white").save(img)
    write_request(tmp_path, "a", img, "p1")
    write_request(tmp_path, "b", img, "p2")
    pending = list_pending(tmp_path)
    assert len(pending) == 2
    names = {p.name for p in pending}
    assert f"{REQUEST_PREFIX}a.json" in names
    assert f"{REQUEST_PREFIX}b.json" in names


def test_list_pending_empty_when_dir_missing():
    assert list_pending(Path("/tmp/this/does/not/exist/anywhere")) == []


def test_read_response_returns_none_when_missing(tmp_path):
    assert read_response(tmp_path / "nope.json") is None


def test_read_response_parses_valid_json(tmp_path):
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"step_name": "x", "boxes": []}))
    data = read_response(f)
    assert data is not None
    assert data["step_name"] == "x"


# ---------- End-to-end: write_request → fake agent response → apply_response ----------

def test_apply_response_produces_annotated_png(tmp_path):
    """The full v0.2.4 flow: recorder writes request, agent writes response,
    recorder applies Pillow annotation."""
    img = tmp_path / "demo.png"
    # Make a non-trivial source image (white + a black square for blur tests)
    src = Image.new("RGB", (1000, 800), "white")
    src.save(img)
    # Recorder writes the request
    req = write_request(tmp_path, "demo", img, "Find the top-left button")
    # Simulated agent: reads image, "decides" there's a button at (10, 10) - (200, 50)
    response_path = response_path_for(req)
    response_path.write_text(json.dumps({
        "step_name": "demo",
        "boxes": [
            {"label": "primary-btn", "x": 10, "y": 10, "w": 200, "h": 50},
        ],
    }))
    # Recorder applies the response
    result = apply_response(req, response_path, tmp_path)
    assert result["status"] == "applied"
    assert result["step_name"] == "demo"
    assert result["annotations_count"] == 1
    # The annotated file must exist and be larger than the source
    annotated = Path(result["annotated_path"])
    assert annotated.exists()
    assert annotated.stat().st_size > 1000
    # Request file removed on success
    assert not req.exists()


def test_apply_response_no_boxes_passthrough(tmp_path):
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    req = write_request(tmp_path, "demo", img, "find nothing")
    response_path = response_path_for(req)
    response_path.write_text(json.dumps({"step_name": "demo", "boxes": []}))
    result = apply_response(req, response_path, tmp_path)
    assert result["status"] == "applied"
    assert result["annotations_count"] == 0
    # Passthrough copy must exist and be byte-identical to source
    annotated = Path(result["annotated_path"])
    assert annotated.exists()
    assert img.read_bytes() == annotated.read_bytes()
    # Request file still removed
    assert not req.exists()


def test_apply_response_skipped_when_response_missing(tmp_path):
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    req = write_request(tmp_path, "demo", img, "x")
    # No response file written
    result = apply_response(req, response_path_for(req), tmp_path)
    assert result["status"] == "skipped"
    assert "response missing" in result["reason"]
    # Request file preserved (so the agent can retry)
    assert req.exists()


def test_apply_response_skipped_when_image_missing(tmp_path):
    req = tmp_path / f"{REQUEST_PREFIX}demo.json"
    req.write_text(json.dumps({
        "step_name": "demo",
        "image_path": str(tmp_path / "does-not-exist.png"),
        "prompt": "x",
        "coord_base": 1000,
        "prompt_hint": "...",
    }))
    response_path = tmp_path / f"{RESPONSE_PREFIX}demo.json"
    response_path.write_text(json.dumps({"step_name": "demo", "boxes": []}))
    result = apply_response(req, response_path, tmp_path)
    assert result["status"] == "skipped"
    assert "image not found" in result["reason"]


def test_apply_response_with_invalid_json_response(tmp_path):
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    req = write_request(tmp_path, "demo", img, "x")
    response_path = response_path_for(req)
    response_path.write_text("not json at all{")
    result = apply_response(req, response_path, tmp_path)
    assert result["status"] == "skipped"
    assert "invalid" in result["reason"]


# ---------- v0.2.4 audit: 境界 (boundary) tests ----------

def test_parse_response_boxes_silently_skips_non_list_boxes(tmp_path):
    """v0.2.4 audit: schema mismatch — boxes is not a list — must NOT silently
    succeed. parse_response_boxes returns [] for non-list, so the result is
    'no boxes, passthrough' (test_verify_silent_skip below). Documenting
    the current graceful-degrade behavior; a future stricter mode would
    raise instead of returning []."""
    response = {"step_name": "demo", "boxes": "not a list"}
    boxes = parse_response_boxes(response)
    assert boxes == []  # current behavior: silent skip

def test_apply_response_with_non_list_boxes_passthrough(tmp_path):
    """End-to-end: agent wrote boxes as wrong type (string not list).
    Recorder must apply_response successfully (as a passthrough) so the
    agent loop doesn't get stuck. The annotation count is 0, but the
    status is 'applied' (no error) — passthrough to a copy of the source."""
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    req = write_request(tmp_path, "demo", img, "x")
    response_path = response_path_for(req)
    response_path.write_text(json.dumps({
        "step_name": "demo",
        "boxes": "wrong type",  # agent schema error
    }))
    result = apply_response(req, response_path, tmp_path)
    assert result["status"] == "applied"
    assert result["annotations_count"] == 0
    # Passthrough copy must be byte-identical to source
    annotated = Path(result["annotated_path"])
    assert annotated.exists()
    assert img.read_bytes() == annotated.read_bytes()


def test_apply_responses_handles_multiple_requests_in_dir(tmp_path):
    """v0.2.4 audit: multi-request — when output_dir has many pending requests,
    apply-ai-responses processes them all. Already-applied ones have their
    request files deleted (so re-runs are no-ops)."""
    from recorder_plugin.vision import list_pending
    img = tmp_path / "shared.png"
    Image.new("RGB", (200, 200), "white").save(img)
    names = ["a", "b", "c"]
    for n in names:
        # Each request references the same source image (simplest case)
        req = write_request(tmp_path, n, img, f"find {n}")
        # Each gets its own response with one box
        resp = response_path_for(req)
        resp.write_text(json.dumps({
            "step_name": n,
            "boxes": [{"label": n, "x": 10, "y": 10, "w": 50, "h": 30}],
        }))
    # Confirm all 3 are pending
    pending = list_pending(tmp_path)
    assert len(pending) == 3
    # Apply each
    from recorder_plugin.vision import apply_response
    for req in pending:
        r = apply_response(req, response_path_for(req), tmp_path)
        assert r["status"] == "applied"
    # All request files should be removed
    assert list_pending(tmp_path) == []
    # All 3 annotated PNGs should exist
    for n in names:
        assert (tmp_path / f"{n}.ai-annotated.png").exists()


def test_stale_request_is_listed_for_agent_to_clean_up(tmp_path):
    """v0.2.4 audit: stale request — agent never wrote a response.
    apply-ai-responses must return status='skipped' so the agent loop
    knows to debug. Request file is preserved (so the agent can retry by
    writing the response)."""
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    req = write_request(tmp_path, "demo", img, "x")
    response_path = response_path_for(req)
    # No response written
    result = apply_response(req, response_path, tmp_path)
    assert result["status"] == "skipped"
    assert "response missing" in result["reason"]
    # Request file preserved for retry
    assert req.exists()
    # list_pending still finds it
    from recorder_plugin.vision import list_pending
    assert req in list_pending(tmp_path)


def test_cli_apply_ai_responses_exits_1_when_any_skipped(tmp_path):
    """v0.2.4 audit: apply-ai-responses must exit 1 if any request was skipped.
    Old bug: all([]) == True in Python, so all-skipped → exit 0 (silent fail).
    """
    import subprocess
    import sys
    cli = Path(__file__).resolve().parents[2] / "recorder_plugin" / "cli.py"
    # Create one stale request (no response)
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    write_request(tmp_path, "demo", img, "x")
    r = subprocess.run(
        [sys.executable, "-m", "recorder_plugin.cli", "apply-ai-responses", str(tmp_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert r.returncode == 1, f"expected exit 1 for skipped request, got {r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    # Output must list the skipped request
    assert "skipped" in r.stdout


def test_cli_apply_ai_responses_exits_0_when_all_applied(tmp_path):
    """v0.2.4 audit: happy path — all applied → exit 0."""
    import subprocess
    import sys
    cli = Path(__file__).resolve().parents[2] / "recorder_plugin" / "cli.py"
    img = tmp_path / "demo.png"
    Image.new("RGB", (100, 100), "white").save(img)
    req = write_request(tmp_path, "demo", img, "x")
    response_path_for(req).write_text(json.dumps({
        "step_name": "demo",
        "boxes": [{"label": "x", "x": 10, "y": 10, "w": 50, "h": 30}],
    }))
    r = subprocess.run(
        [sys.executable, "-m", "recorder_plugin.cli", "apply-ai-responses", str(tmp_path)],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}\nstderr: {r.stderr}"
