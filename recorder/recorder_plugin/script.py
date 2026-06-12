"""Declarative JSON script runner. Validates schema, walks steps, dispatches to module handlers."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import shutil
import sys
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


async def _handle_set_viewport(rec: Recorder, step: dict) -> None:
    """v0.2.4 audit round 3 (C4): previously a no-op (dispatched through
    ALLOWED_STEP_ACTIONS but no elif branch). Resize the Playwright
    page so subsequent screenshots / clicks use the new viewport."""
    width = int(step.get("width", 1280))
    height = int(step.get("height", 800))
    await rec.page.set_viewport_size({"width": width, "height": height})


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
    step: dict, output_dir: Path, pending_annotations: list
) -> AssetRef | None:
    """v0.2.4: agent-mediated vision annotation (no LLM calls in recorder).

    v0.2.4 protocol: recorder writes a request file and yields control.
    The agent loop reads the request, calls its OWN multimodal LLM
    (Claude in Claude Code, GPT-4o in Codex, etc.), writes a response
    file, then re-invokes recorder's `apply-ai-responses` subcommand.

    The `pending_annotations` list is appended to so the script output
    can surface pending requests to the agent.

    Returns the source image (a passthrough) AssetRef. The actual
    annotated PNG is produced later by `apply-ai-responses`.
    """
    from recorder_plugin.vision import write_request
    prompt = step.get("prompt") or step.get("description") or "Find notable UI elements"
    name = _to_kebab(step.get("screenshot") or step.get("name") or "ai-annotated")
    src = output_dir / f"{name}.png"
    if not src.exists():
        return None
    # F3 fix (v0.2.4 audit re-review): if the prompt is a literal TODO marker
    # (e.g. from an unfilled build_recorder_template), warn loudly. The
    # request file is still written so the agent can debug, but a stderr
    # warning makes the unfilled state visible.
    if "<TODO" in prompt or prompt.strip() == "":
        print(
            f"WARNING: ai_annotate step '{name}' has empty/TODO prompt. "
            f"Agent must fill in step['prompt'] before the request goes to the LLM. "
            f"Writing request with placeholder prompt anyway — agent should re-edit script.",
            file=sys.stderr,
        )
    # Emit the request file. Recorder does NOT call any LLM.
    req_path = write_request(output_dir, name, src, prompt)
    pending_annotations.append({
        "step_name": name,
        "request_file": str(req_path),
        "image_path": str(src),
        "prompt": prompt,
    })
    # Return a passthrough AssetRef pointing at the source image.
    # The annotated file will be produced by apply-ai-responses.
    return AssetRef(
        path=src, kind="screenshot", size_bytes=src.stat().st_size,
        annotated=False,
        caption_hint=f"AI-annotation pending (request emitted): {prompt[:30]}",
    )


async def _handle_video_start(rec: Recorder, step: dict, name_to_path: dict) -> None:
    # v0.2.1: remember the current page so _handle_video_stop can close it
    # to flush Playwright's webm to rec_dir.
    name = _to_kebab(step["name"])
    name_to_path[f"_video_{name}"] = {
        "started_at": time.monotonic(),
        # v0.2.4 audit round 3 (C3): also record wall-clock start time
        # so _handle_video_stop can filter out webms from previous
        # sessions (back-to-back video_start/video_stop in the same
        # script). monotonic() is for duration math; we need wall time
        # to compare against file mtimes.
        "started_wall": time.time(),
        "recording_page": rec.page,
    }


async def _handle_video_stop(
    rec: Recorder, step: dict, name_to_path: dict, output_dir: Path
) -> AssetRef:
    """v0.2.1: slice the recorded webm, concat into one MP4, return reference.

    v0.2.1 timing fix: Playwright writes the webm to rec_dir only when the
    *page* is closed. So we close the page that was active during recording,
    which flushes the webm, then process it. We then open a fresh page for
    any subsequent steps in the script.
    """
    from recorder_plugin.video import (
        concat_slices_to_mp4, validate_slice, get_video_info,
    )
    from recorder_plugin.video import slice_video as slice_v
    name = _to_kebab(step["name"])
    rec_dir = rec.record_video_dir
    if not rec_dir:
        return AssetRef(path=output_dir / f"{name}.mp4", kind="video_slice", size_bytes=0)

    # Flush the webm: close the page that was active during recording.
    name_key = f"_video_{name}"
    session = name_to_path.get(name_key, {})
    recording_page = session.get("recording_page") if isinstance(session, dict) else None
    # v0.2.4 audit round 3 (H2): wrap page close in wait_for so a hung
    # Playwright teardown cannot block the whole script. TimeoutError
    # is logged as a warning — the webm may still flush from the
    # Playwright context teardown at session end.
    if recording_page is not None and not recording_page.is_closed():
        try:
            await asyncio.wait_for(recording_page.close(), timeout=10)
        except (asyncio.TimeoutError, Exception) as e:
            print(
                f"WARNING: recording_page.close() for video '{name}' "
                f"timed out or failed ({type(e).__name__}: {e}); "
                f"webm may flush late via context teardown.",
                file=sys.stderr,
            )

    # v0.2.4 audit round 3 (C3): filter webms by session wall-clock
    # start time to avoid back-to-back session aliasing. Without
    # this, the second video_stop in the same run picked the most
    # recently MODIFIED webm — which could be the previous session's
    # still-flushing file. 1.0s tolerance for clock jitter.
    session_wall = session.get("started_wall", 0) if isinstance(session, dict) else 0
    webms_all = rec_dir.glob("*.webm")
    webms = [p for p in webms_all if p.stat().st_mtime >= session_wall - 1.0]
    webms.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if not webms:
        return AssetRef(path=output_dir / f"{name}.mp4", kind="video_slice", size_bytes=0)
    src = webms[0]
    target_dir = output_dir / name
    target_dir.mkdir(parents=True, exist_ok=True)
    # v0.2.1: use step name as the slice stem, not the random webm UUID
    slices = slice_v(src, target_dir, slice_seconds=10, output_stem=name)
    if not slices:
        return AssetRef(path=src, kind="video_slice", size_bytes=src.stat().st_size)
    if not validate_slice(slices[0]):
        return AssetRef(path=slices[0], kind="video_slice", size_bytes=slices[0].stat().st_size)
    valid_slices = [s for s in slices if validate_slice(s)]
    if valid_slices:
        mp4_path = target_dir / f"{name}.mp4"
        try:
            concat_slices_to_mp4(valid_slices, mp4_path, audio=False)
            asset = AssetRef(
                path=mp4_path, kind="video_slice",
                size_bytes=mp4_path.stat().st_size, slice_index=0,
                extra={"duration_s": get_video_info(mp4_path)["duration_s"]},
            )
        except Exception:
            asset = AssetRef(
                path=slices[0], kind="video_slice",
                size_bytes=slices[0].stat().st_size, slice_index=0,
            )
    else:
        asset = AssetRef(
            path=slices[0], kind="video_slice",
            size_bytes=slices[0].stat().st_size, slice_index=0,
        )

    # Open a fresh page on the same context for any subsequent steps.
    try:
        new_page = await rec.context.new_page()
        rec._page = new_page
    except Exception:
        pass

    return asset


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

    pending_annotations: list[dict] = []
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
                elif action == "set_viewport":
                    await _handle_set_viewport(rec, step)
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
                    asset = await _handle_ai_annotate(step, output_dir, pending_annotations)
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
        "pending_ai_annotations": pending_annotations,  # v0.2.4
    }
