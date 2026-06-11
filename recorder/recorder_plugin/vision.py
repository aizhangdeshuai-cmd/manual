"""AI vision annotation. Uses Anthropic Claude with vision to identify UI elements in
a screenshot and return bounding boxes as Annotations.

v1.1 design (per docs/superpowers/specs/2026-06-11-recorder-skill-design.md):
- The LLM agent is already Claude (the user is using Claude Code). For "AI annotation"
  we send the screenshot back to Claude vision and ask for bounding boxes.
- The function `ai_annotate_image` returns a list[Annotation] in the same format as
  selector-based annotation, so the script runner can apply them identically.
- Requires `ANTHROPIC_API_KEY` env var. The recorder gracefully reports a config
  error if the key is missing.
- Model: claude-3-5-sonnet-20241022 (vision-capable, current at v1.1 design time).
"""
from __future__ import annotations
import base64
import json
import os
import re
from pathlib import Path
from typing import Any
import anthropic
from recorder_plugin.annotate import Annotation


# Default model — override with $VISION_MODEL env var
DEFAULT_MODEL = os.environ.get("VISION_MODEL", "claude-3-5-sonnet-20241022")

# How many pixels Claude's "1000" coordinate maps to (image normalization base)
COORD_BASE = 1000


def _encode_image_b64(path: Path) -> tuple[str, str]:
    """Read an image file and return (base64_data, media_type)."""
    suffix = path.suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")
    data = path.read_bytes()
    return base64.standard_b64encode(data).decode("ascii"), media_type


def _build_user_prompt(prompt: str) -> str:
    """Build the user message: ask Claude to return bounding boxes as JSON."""
    return (
        f"{prompt}\n\n"
        f"For every UI element relevant to the request, return its bounding box.\n"
        f"Use the coordinate system where (0,0) is the top-left and the image is "
        f"normalized to {COORD_BASE}×{COORD_BASE} pixels.\n\n"
        f"Return ONLY a JSON array (no prose, no markdown fences) of objects with "
        f"this exact shape:\n"
        f'[{{"label": "short caption", "x": 0, "y": 0, "w": 100, "h": 50}}, ...]\n\n'
        f"Each entry's (x, y) is the top-left corner of the bounding box, "
        f"(w, h) is width and height. Keep labels ≤ 15 characters, colloquial Chinese "
        f"or English to match the surrounding manual. Return [] if nothing matches."
    )


def _parse_claude_response(text: str) -> list[dict[str, Any]]:
    """Extract the JSON array from Claude's text response, tolerating common wrappers."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        # Find first newline, then last ```
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # Locate the first [ and last ]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict) and {"x", "y", "w", "h"}.issubset(it)]


def _denormalize(boxes: list[dict], img_w: int, img_h: int) -> list[dict]:
    """Convert Claude's 0-1000 normalized coords to pixel coords for the given image."""
    out: list[dict] = []
    for b in boxes:
        out.append({
            "label": str(b.get("label", ""))[:15],
            "x": int(b["x"] * img_w / COORD_BASE),
            "y": int(b["y"] * img_h / COORD_BASE),
            "w": int(b["w"] * img_w / COORD_BASE),
            "h": int(b["h"] * img_h / COORD_BASE),
        })
    return out


def get_image_size(path: Path) -> tuple[int, int]:
    """Return (width, height) of an image file."""
    from PIL import Image
    with Image.open(path) as img:
        return img.size


def ai_annotate_image(
    image_path: Path,
    prompt: str,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> list[Annotation]:
    """Send an image + prompt to Claude vision; return Annotations in recorder's native format.

    Requires ANTHROPIC_API_KEY env var (or pass api_key explicitly).

    Coordinates from Claude are on a 0-1000 normalized grid; we denormalize to the
    image's actual pixel dimensions before returning.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"ai_annotate_image: {image_path} not found")

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ai_annotate_image: ANTHROPIC_API_KEY env var is not set. "
            "Set it (e.g. `export ANTHROPIC_API_KEY=sk-ant-...`) or pass api_key explicitly."
        )

    img_b64, media_type = _encode_image_b64(image_path)
    img_w, img_h = get_image_size(image_path)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": img_b64},
                },
                {"type": "text", "text": _build_user_prompt(prompt)},
            ],
        }],
    )
    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    raw_boxes = _parse_claude_response(text)
    denorm = _denormalize(raw_boxes, img_w, img_h)
    return [
        Annotation(shape="box", x=b["x"], y=b["y"], w=b["w"], h=b["h"], label=b["label"])
        for b in denorm
    ]


def ai_annotate_and_save(
    image_path: Path,
    prompt: str,
    output_path: Path,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> list[Annotation]:
    """Convenience: call ai_annotate_image, save the annotated PNG, return the annotations."""
    import shutil
    annotations = ai_annotate_image(image_path, prompt, model=model, api_key=api_key)
    from recorder_plugin.annotate import annotate_image
    if annotations:
        annotate_image(image_path, output_path, annotations)
    else:
        # No boxes: passthrough copy
        shutil.copy(image_path, output_path)
    return annotations


def parse_claude_response_for_test(text: str) -> list[dict[str, Any]]:
    """Test-only export of _parse_claude_response."""
    return _parse_claude_response(text)


def denormalize_for_test(boxes: list[dict], img_w: int, img_h: int) -> list[dict]:
    """Test-only export of _denormalize."""
    return _denormalize(boxes, img_w, img_h)
