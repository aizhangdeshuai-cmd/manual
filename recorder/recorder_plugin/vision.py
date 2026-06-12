"""AI vision annotation — request/response coordinator.

v0.2.4 refactor: this module USED TO make direct Anthropic SDK calls.
It no longer does. Recorder is provider-agnostic; vision is fulfilled by
the agent loop using whatever LLM the harness has access to (Claude in
Claude Code, GPT-4o in Codex, Llama-3.2-vision in Ollama, etc.).

Protocol (request/response):
  1. Recorder script hits an `ai_annotate` step. We write:
        <output_dir>/.ai_annotation_request_<name>.json
     with {image_path, prompt, step_name, requested_at}.
  2. Recorder does NOT call any LLM. Returns a "pending" marker in the
     script's output dict (`pending_ai_annotations: [...]`).
  3. The LLM agent loop sees the pending request, reads the image, calls
     its own multimodal model, and writes:
        <output_dir>/.ai_annotation_response_<name>.json
     with {step_name, boxes: [{x, y, w, h, label}, ...]}.
  4. Recorder reads the response, applies Pillow annotations, writes
     `<name>.ai-annotated.png`, deletes the request file.

This module is now pure stdlib + Pillow (already a recorder dep). Zero
LLM-specific code. Zero provider lock-in.
"""
from __future__ import annotations
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from recorder_plugin.annotate import Annotation


# How many pixels the agent's "1000" coordinate maps to (normalization base).
# Agents are told to use this in their prompt (see REQUEST_FILE_PROMPT_HINT).
COORD_BASE = 1000

REQUEST_PREFIX = ".ai_annotation_request_"
RESPONSE_PREFIX = ".ai_annotation_response_"

# A hint the agent's prompt will use to format its response.
# Kept here so it's identical between write + apply paths.
REQUEST_FILE_PROMPT_HINT = (
    f"Return a JSON object {{\"step_name\": \"<name>\", \"boxes\": [...]}} where each "
    f"box is {{\"label\": \"<≤15 chars>\", \"x\": <0-{COORD_BASE}>, \"y\": <0-{COORD_BASE}>, "
    f"\"w\": <pixels>, \"h\": <pixels>}}. Image origin (0,0) is top-left; coordinates "
    f"normalized to {COORD_BASE}×{COORD_BASE} (the recorder will denormalize to "
    f"actual pixel dimensions)."
)


def write_request(
    output_dir: Path,
    step_name: str,
    image_path: Path,
    prompt: str,
) -> Path:
    """Write a vision-annotation request file. Returns the request file path.

    The recorder emits this when an `ai_annotate` step is reached. The agent
    loop picks it up, fulfills it, and writes a matching response file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    req_path = output_dir / f"{REQUEST_PREFIX}{step_name}.json"
    req_path.write_text(json.dumps({
        "step_name": step_name,
        "image_path": str(image_path),
        "image_exists": image_path.exists(),
        "prompt": prompt,
        "coord_base": COORD_BASE,
        "prompt_hint": REQUEST_FILE_PROMPT_HINT,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return req_path


def list_pending(output_dir: Path) -> list[Path]:
    """Return all pending AI annotation request files in output_dir."""
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return []
    return sorted(output_dir.glob(f"{REQUEST_PREFIX}*.json"))


def response_path_for(request_path: Path) -> Path:
    """Map a request file path to the expected response file path."""
    return request_path.with_name(
        request_path.name.replace(REQUEST_PREFIX, RESPONSE_PREFIX, 1)
    )


def read_response(response_path: Path) -> dict | None:
    """Read a response file. Returns None if not found or invalid."""
    if not response_path.exists():
        return None
    try:
        return json.loads(response_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def parse_response_boxes(response: dict) -> list[dict[str, Any]]:
    """Extract and validate the boxes list from a response dict.

    Returns list of {x, y, w, h, label} dicts (normalized 0-1000 coords).
    """
    boxes = response.get("boxes", [])
    if not isinstance(boxes, list):
        return []
    out = []
    for b in boxes:
        if not isinstance(b, dict):
            continue
        if not {"x", "y", "w", "h"}.issubset(b):
            continue
        out.append({
            "label": str(b.get("label", ""))[:15],
            "x": int(b["x"]),
            "y": int(b["y"]),
            "w": int(b["w"]),
            "h": int(b["h"]),
        })
    return out


def denormalize_boxes(boxes: list[dict], img_w: int, img_h: int) -> list[dict]:
    """Convert 0-COORD_BASE normalized coords to actual pixel coords."""
    out = []
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


def apply_response(
    request_path: Path,
    response_path: Path,
    output_dir: Path,
) -> dict:
    """Apply a fulfilled AI annotation response to produce the annotated PNG.

    Returns:
      {"status": "applied"|"skipped", "step_name": str, "annotations_count": int,
       "annotated_path": Path|None, "reason": str|None}

    Removes the request file on success. Leaves it in place on failure
    so the agent can retry by overwriting the response.
    """
    from recorder_plugin.annotate import annotate_image

    request = json.loads(request_path.read_text(encoding="utf-8"))
    step_name = request["step_name"]
    image_path = Path(request["image_path"])
    annotated_path = output_dir / f"{step_name}.ai-annotated.png"

    if not image_path.exists():
        return {"status": "skipped", "step_name": step_name, "annotations_count": 0,
                "annotated_path": None, "reason": f"image not found: {image_path}"}

    response = read_response(response_path)
    if response is None:
        return {"status": "skipped", "step_name": step_name, "annotations_count": 0,
                "annotated_path": None, "reason": f"response missing or invalid: {response_path}"}

    boxes_norm = parse_response_boxes(response)
    if not boxes_norm:
        # No boxes: passthrough copy
        shutil.copy(image_path, annotated_path)
        request_path.unlink(missing_ok=True)
        return {"status": "applied", "step_name": step_name, "annotations_count": 0,
                "annotated_path": annotated_path, "reason": "no boxes; passthrough"}

    img_w, img_h = get_image_size(image_path)
    boxes_px = denormalize_boxes(boxes_norm, img_w, img_h)
    annotations = [
        Annotation(shape="box", x=b["x"], y=b["y"], w=b["w"], h=b["h"], label=b["label"])
        for b in boxes_px
    ]
    annotate_image(image_path, annotated_path, annotations)
    request_path.unlink(missing_ok=True)
    return {"status": "applied", "step_name": step_name, "annotations_count": len(annotations),
            "annotated_path": annotated_path, "reason": None}


# ---- Public functions re-exported for testability ----

def write_request_for_test(output_dir, step_name, image_path, prompt):
    """Test-only export."""
    return write_request(output_dir, step_name, image_path, prompt)


def denormalize_boxes_for_test(boxes, img_w, img_h):
    """Test-only export."""
    return denormalize_boxes(boxes, img_w, img_h)


def parse_response_boxes_for_test(response):
    """Test-only export."""
    return parse_response_boxes(response)
