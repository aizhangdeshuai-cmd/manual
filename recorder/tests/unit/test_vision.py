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
