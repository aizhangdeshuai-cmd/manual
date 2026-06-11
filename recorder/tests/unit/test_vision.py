"""Tests for recorder_plugin.vision — AI annotation via Anthropic Claude.

The Anthropic API is mocked at the `anthropic.Anthropic` boundary via monkeypatch.
"""
import base64
import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PIL import Image
from recorder_plugin.vision import (
    ai_annotate_image, ai_annotate_and_save,
    parse_claude_response_for_test, denormalize_for_test,
    _encode_image_b64, _build_user_prompt,
)


# ---------- pure-function tests (no API) ----------

def test_parse_claude_response_plain_json():
    text = '[{"label": "Add", "x": 100, "y": 200, "w": 50, "h": 30}]'
    out = parse_claude_response_for_test(text)
    assert len(out) == 1
    assert out[0]["label"] == "Add"


def test_parse_claude_response_with_markdown_fences():
    text = '```json\n[{"label": "Save", "x": 0, "y": 0, "w": 100, "h": 50}]\n```'
    out = parse_claude_response_for_test(text)
    assert len(out) == 1
    assert out[0]["label"] == "Save"


def test_parse_claude_response_with_prose_around():
    text = 'Here are the boxes:\n[{"label": "X", "x": 1, "y": 2, "w": 3, "h": 4}]\nHope that helps!'
    out = parse_claude_response_for_test(text)
    assert len(out) == 1


def test_parse_claude_response_empty_array():
    assert parse_claude_response_for_test("[]") == []


def test_parse_claude_response_invalid_json():
    assert parse_claude_response_for_test("not json") == []


def test_parse_claude_response_missing_fields():
    text = '[{"label": "X", "x": 1}, {"label": "Y", "x": 1, "y": 2, "w": 3, "h": 4}]'
    out = parse_claude_response_for_test(text)
    # Only the second one has all required fields
    assert len(out) == 1
    assert out[0]["label"] == "Y"


def test_denormalize_scales_to_pixel_coords():
    boxes = [{"x": 500, "y": 250, "w": 100, "h": 50, "label": "X"}]
    out = denormalize_for_test(boxes, img_w=2000, img_h=1000)
    # 500/1000 * 2000 = 1000
    assert out[0]["x"] == 1000
    assert out[0]["y"] == 250
    assert out[0]["w"] == 200
    assert out[0]["h"] == 50


def test_denormalize_caps_label_length():
    boxes = [{"x": 0, "y": 0, "w": 10, "h": 10, "label": "X" * 100}]
    out = denormalize_for_test(boxes, 100, 100)
    assert len(out[0]["label"]) == 15  # capped at 15


def test_encode_image_b64_png(tmp_path):
    img = Image.new("RGB", (50, 50), "red")
    p = tmp_path / "x.png"
    img.save(p)
    b64, media_type = _encode_image_b64(p)
    assert media_type == "image/png"
    decoded = base64.b64decode(b64)
    assert decoded.startswith(b"\x89PNG")


def test_encode_image_b64_jpg(tmp_path):
    img = Image.new("RGB", (50, 50), "blue")
    p = tmp_path / "x.jpg"
    img.save(p)
    b64, media_type = _encode_image_b64(p)
    assert media_type == "image/jpeg"


def test_build_user_prompt_mentions_15_char_limit():
    p = _build_user_prompt("Find the Add button")
    assert "1000" in p  # coordinate base
    assert "15" in p  # label length cap


# ---------- mocked API call ----------

class _FakeTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _FakeMessage:
    def __init__(self, text: str):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_call = None

    def create(self, model, max_tokens, messages):
        self.last_call = {"model": model, "max_tokens": max_tokens, "messages": messages}
        return _FakeMessage(self.response_text)


class _FakeAnthropic:
    def __init__(self, response_text: str, api_key=None):
        self.messages = _FakeMessages(response_text)
        self.api_key = api_key


@pytest.fixture
def fake_anthropic(monkeypatch):
    """Patch recorder_plugin.vision.anthropic.Anthropic with a fake.

    Returns a dict with the last call's api_key under ['api_key'].
    """
    holder: dict = {"api_key": None, "call_count": 0}
    response = '[{"label": "新增", "x": 100, "y": 200, "w": 50, "h": 30}]'

    def factory(api_key=None):
        holder["api_key"] = api_key
        holder["call_count"] += 1
        return _FakeAnthropic(response, api_key=api_key)

    import recorder_plugin.vision as vision_mod
    monkeypatch.setattr(vision_mod.anthropic, "Anthropic", factory)
    return holder


def test_ai_annotate_image_returns_annotations(tmp_path, monkeypatch, fake_anthropic):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    img = Image.new("RGB", (1000, 1000), "white")
    p = tmp_path / "screenshot.png"
    img.save(p)
    out = ai_annotate_image(p, "Find the Add button")
    assert len(out) == 1
    assert out[0].shape == "box"
    assert out[0].label == "新增"
    # Verify denormalized to 1000x1000 (so coords are pixel-for-pixel)
    assert out[0].x == 100
    assert out[0].y == 200
    assert out[0].w == 50
    assert out[0].h == 30


def test_ai_annotate_image_uses_passed_api_key(tmp_path, monkeypatch, fake_anthropic):
    img = Image.new("RGB", (100, 100), "white")
    p = tmp_path / "s.png"
    img.save(p)
    ai_annotate_image(p, "x", api_key="explicit-key")
    assert fake_anthropic["api_key"] == "explicit-key"


def test_ai_annotate_image_missing_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    img = Image.new("RGB", (100, 100), "white")
    p = tmp_path / "s.png"
    img.save(p)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        ai_annotate_image(p, "x")


def test_ai_annotate_image_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with pytest.raises(FileNotFoundError):
        ai_annotate_image(tmp_path / "nonexistent.png", "x")


def test_ai_annotate_image_empty_response(tmp_path, monkeypatch):
    fake = _FakeAnthropic("[]")
    import recorder_plugin.vision as vision_mod
    monkeypatch.setattr(vision_mod.anthropic, "Anthropic", lambda api_key=None: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    img = Image.new("RGB", (100, 100), "white")
    p = tmp_path / "s.png"
    img.save(p)
    out = ai_annotate_image(p, "Find something")
    assert out == []


def test_ai_annotate_and_save_creates_annotated_file(tmp_path, monkeypatch, fake_anthropic):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    img = Image.new("RGB", (500, 500), "white")
    p = tmp_path / "src.png"
    img.save(p)
    out = tmp_path / "annotated.png"
    annotations = ai_annotate_and_save(p, "Find the button", out)
    assert out.exists()
    assert out.stat().st_size > 0
    assert len(annotations) == 1


def test_ai_annotate_and_save_no_boxes_passthrough(tmp_path, monkeypatch):
    fake = _FakeAnthropic("[]")
    import recorder_plugin.vision as vision_mod
    monkeypatch.setattr(vision_mod.anthropic, "Anthropic", lambda api_key=None: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    img = Image.new("RGB", (100, 100), "white")
    p = tmp_path / "src.png"
    img.save(p)
    out = tmp_path / "out.png"
    ai_annotate_and_save(p, "find something", out)
    assert out.exists()
    # No boxes → passthrough copy: should be byte-identical to source
    assert p.read_bytes() == out.read_bytes()
