"""Declarative JSON script runner. Validates schema, walks steps, dispatches to module handlers."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from recorder_plugin.core import Recorder, AssetRef
from recorder_plugin.wait import WaitSpec, dispatch_wait
from recorder_plugin.retry import SelectorResolver
from recorder_plugin.state import RecorderState
from recorder_plugin.annotate import Annotation, annotate_image
from recorder_plugin.mask import mask_image_pillow
from recorder_plugin.login import LoginStep, perform_login
from recorder_plugin.video import slice_video

ALLOWED_STEP_ACTIONS = {
    "navigate", "click", "type", "wait_for", "screenshot",
    "login", "video_start", "video_stop", "set_viewport",
    "ai_annotate",  # v1.1
}


def _step_hash(step: dict, script_hash: str) -> str:
    payload = json.dumps({"s": script_hash, "step": step}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _to_kebab(name: str) -> str:
    """Convert '01 List' or '01List' to '01-list' for filename consistency."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "unnamed"


def _resolve_creds(d: dict, env: dict) -> dict:
    """Recursively replace $VAR with os.environ[VAR] in string leaves of d."""
    from recorder_plugin.login import resolve_credential
    if isinstance(d, str):
        return resolve_credential(d, env)
    if isinstance(d, dict):
        return {k: _resolve_creds(v, env) for k, v in d.items()}
    if isinstance(d, list):
        return [_resolve_creds(x, env) for x in d]
    return d


async def _handle_navigate(rec: Recorder, step: dict) -> None:
    await rec.navigate(step["url"])


async def _handle_click(rec: Recorder, step: dict) -> tuple[bool, str, int]:
    resolver = SelectorResolver()
    selector = step["selector"]
    async def try_locator(variant: str):
        await rec.page.click(variant, timeout=3000)
    ok, winning, attempts = await resolver.attempt_async(selector, try_locator)
    return ok, winning, attempts


async def _handle_type(rec: Recorder, step: dict) -> None:
    await rec.page.fill(step["selector"], step["text"])
    if step.get("press_enter"):
        await rec.page.keyboard.press("Enter")


async def _handle_wait(rec: Recorder, step: dict) -> int:
    spec = WaitSpec.from_dict(step)
    return await dispatch_wait(rec.page, spec)


async def _handle_screenshot(
    rec: Recorder, step: dict, output_dir: Path
) -> AssetRef:
    name = _to_kebab(step["name"])
    raw_annotate = step.get("annotate") or []
    annotations = [Annotation.from_dict(a) for a in raw_annotate]
    raw_mask = step.get("mask") or []
    out_path = output_dir / f"{name}.png"
    ref = await rec.screenshot(name=name, annotate=annotations, mask=raw_mask, output_path=out_path)

    if raw_mask:
        # Apply mask to the original
        masked_path = output_dir / f"{name}.masked.png"
        mask_image_pillow(out_path, masked_path, raw_mask)
        # Reassign the original to the masked version
        shutil.move(masked_path, out_path)

    if annotations:
        annotated_path = output_dir / f"{name}.annotated.png"
        annotate_image(out_path, annotated_path, annotations)
        ref.path = annotated_path
        ref.annotated = True
        ref.caption_hint = annotations[0].label or None

    return ref


async def _handle_login(rec: Recorder, step: dict, env: dict) -> bool:
    resolved = _resolve_creds(step, env)
    login = LoginStep.from_dict(resolved)
    return await perform_login(rec, login)


async def _handle_ai_annotate(
    step: dict, output_dir: Path
) -> AssetRef | None:
    """v1.1: take a fresh screenshot, send to Claude vision, apply annotations.

    The step may EITHER:
    - Reference an existing screenshot by name: {"action": "ai_annotate", "screenshot": "01-list", "prompt": "..."}
    - Take a fresh screenshot first: {"action": "ai_annotate", "name": "01-list", "prompt": "...", "fresh": true}

    Returns the annotated AssetRef, or None if the source screenshot doesn't exist.
    """
    from recorder_plugin.vision import ai_annotate_and_save
    prompt = step.get("prompt") or step.get("description") or "Find notable UI elements"
    name = _to_kebab(step.get("screenshot") or step.get("name") or "ai-annotated")
    src = output_dir / f"{name}.png"
    if not src.exists():
        return None
    dst = output_dir / f"{name}.ai-annotated.png"
    annotations = ai_annotate_and_save(src, prompt, dst)
    return AssetRef(
        path=dst, kind="screenshot", size_bytes=dst.stat().st_size,
        annotated=True,
        caption_hint=f"AI-annotated ({len(annotations)} boxes): {prompt[:30]}",
    )


async def _handle_video_start(rec: Recorder, step: dict, name_to_path: dict) -> None:
    # v1: recording is started by Recorder() with record_video_dir. We just remember the name.
    name = _to_kebab(step["name"])
    name_to_path[f"_video_{name}"] = {"started_at": time.monotonic()}


async def _handle_video_stop(
    rec: Recorder, step: dict, name_to_path: dict, output_dir: Path
) -> AssetRef:
    """v1.1: slice the recorded webm, concat into one MP4, return reference.

    The MP4 is the new canonical asset; individual slices are still kept for reference.
    """
    from recorder_plugin.video import concat_slices_to_mp4, validate_slice, get_video_info
    name = _to_kebab(step["name"])
    rec_dir = rec.record_video_dir
    if not rec_dir:
        return AssetRef(path=output_dir / f"{name}.mp4", kind="video_slice", size_bytes=0)
    webms = sorted(rec_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not webms:
        return AssetRef(path=output_dir / f"{name}.mp4", kind="video_slice", size_bytes=0)
    src = webms[0]
    target_dir = output_dir / name
    target_dir.mkdir(parents=True, exist_ok=True)
    slices = slice_video(src, target_dir, slice_seconds=10)
    if not slices:
        return AssetRef(path=src, kind="video_slice", size_bytes=src.stat().st_size)
    if not validate_slice(slices[0]):
        return AssetRef(path=slices[0], kind="video_slice", size_bytes=slices[0].stat().st_size)
    # v1.1: concat all valid slices into one MP4
    valid_slices = [s for s in slices if validate_slice(s)]
    if valid_slices:
        mp4_path = target_dir / f"{name}.mp4"
        try:
            concat_slices_to_mp4(valid_slices, mp4_path, audio=False)
            return AssetRef(
                path=mp4_path, kind="video_slice",
                size_bytes=mp4_path.stat().st_size, slice_index=0,
                extra={"duration_s": get_video_info(mp4_path)["duration_s"]},
            )
        except Exception:
            pass  # fall through to first slice
    return AssetRef(
        path=slices[0], kind="video_slice",
        size_bytes=slices[0].stat().st_size, slice_index=0,
    )


async def run_script(script_path: Path) -> dict:
    """Execute a declarative JSON script. Returns the output dict (per spec §6.2)."""
    script_path = Path(script_path)
    data = json.loads(script_path.read_text())
    script_name = data.get("name", script_path.stem)
    output_dir = Path(data.get("output_dir", "."))
    output_dir.mkdir(parents=True, exist_ok=True)
    viewport = data.get("viewport", {"width": 1280, "height": 800})
    record_video = any(s.get("action") in ("video_start", "video_stop") for s in data["steps"])
    rec_dir = output_dir / "_video_buffer" if record_video else None
    if rec_dir:
        rec_dir.mkdir(parents=True, exist_ok=True)
    env = dict(data.get("auth_env", []))

    started = datetime.now(timezone.utc).isoformat()
    start_ts = time.monotonic()
    script_content_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    state = RecorderState(output_dir, script_name)
    screenshots: list[dict] = []
    videos: list[dict] = []
    skipped_steps: list[dict] = []
    warnings: list[dict] = []
    errors: list[dict] = []
    upload_hints: list[dict] = []

    name_to_path: dict[str, Any] = {}

    async with Recorder(
        viewport=viewport, headless=True,
        output_dir=output_dir, record_video_dir=rec_dir,
    ) as rec:
        for i, step in enumerate(data["steps"]):
            action = step.get("action")
            if action not in ALLOWED_STEP_ACTIONS:
                errors.append({"step": i, "error": f"unknown action: {action}"})
                continue
            step_h = _step_hash(step, script_content_hash)
            if state.is_step_valid(i, step_h):
                skipped_steps.append({"step": i, "reason": "output exists and hash matches"})
                continue
            try:
                if action == "navigate":
                    await _handle_navigate(rec, step)
                elif action == "click":
                    ok, winning, attempts = await _handle_click(rec, step)
                    if not ok:
                        errors.append({
                            "step": i, "action": "click",
                            "error": f"selector {step['selector']!r} not found",
                            "tried_attempts": attempts,
                        })
                        if data.get("fail_fast"):
                            break
                elif action == "type":
                    await _handle_type(rec, step)
                elif action == "wait_for":
                    await _handle_wait(rec, step)
                elif action == "screenshot":
                    asset = await _handle_screenshot(rec, step, output_dir)
                    asset_dict = asset.to_dict()
                    asset_dict["step"] = i
                    screenshots.append(asset_dict)
                    state.set_step(i, step_h, asset.path, validated=True)
                elif action == "login":
                    ok = await _handle_login(rec, step, env)
                    if not ok:
                        errors.append({"step": i, "action": "login", "error": "login failed"})
                        if data.get("fail_fast"):
                            break
                elif action == "video_start":
                    await _handle_video_start(rec, step, name_to_path)
                elif action == "video_stop":
                    # v1.1: cross-process resume — if the state already has a
                    # validated session for this name, reuse it instead of re-recording.
                    name = _to_kebab(step["name"])
                    if state.is_video_session_valid(name):
                        existing = state.get_video_session(name)
                        asset = AssetRef(
                            path=Path(existing["output_path"]),
                            kind="video_slice",
                            size_bytes=0,
                            slice_index=0,
                            extra={"reused": True},
                        )
                        asset_dict = asset.to_dict()
                        asset_dict["step"] = i
                        asset_dict["name"] = name
                        videos.append(asset_dict)
                        skipped_steps.append({
                            "step": i, "action": "video_stop",
                            "reason": "video session already validated; reused",
                        })
                        continue
                    asset = await _handle_video_stop(rec, step, name_to_path, output_dir)
                    asset_dict = asset.to_dict()
                    asset_dict["step"] = i
                    asset_dict["name"] = name
                    videos.append(asset_dict)
                    state.set_video_session(name, asset.path, validated=True)
                elif action == "ai_annotate":
                    asset = await _handle_ai_annotate(step, output_dir)
                    if asset is None:
                        errors.append({
                            "step": i, "action": "ai_annotate",
                            "error": f"source screenshot not found: {step.get('screenshot') or step.get('name')}",
                        })
                    else:
                        asset_dict = asset.to_dict()
                        asset_dict["step"] = i
                        screenshots.append(asset_dict)
            except Exception as e:
                errors.append({"step": i, "action": action, "error": str(e)})
                if data.get("fail_fast"):
                    break

    duration = int(time.monotonic() - start_ts)
    completed = datetime.now(timezone.utc).isoformat()
    return {
        "script": script_name,
        "status": "ok" if not errors else "partial",
        "started_at": started,
        "completed_at": completed,
        "duration_s": duration,
        "screenshots": screenshots,
        "videos": videos,
        "skipped_steps": skipped_steps,
        "warnings": warnings,
        "errors": errors,
        "upload_hints": upload_hints,
    }
