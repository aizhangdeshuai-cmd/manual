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
    """Convert '01 List' or '01List' to '01-list' for filename consistency.

    v0.2.4 audit round 3 (L1): distinct inputs that differ only in
    separators / case ('01 List', '01-List', '01List', '01_list') all
    collapse to the same kebab form ('01-list'). The recorder emits
    a stderr warning whenever the input had any character outside the
    kebab charset, so the user knows their file was renamed. This
    avoids false positives on already-kebab names like '01-list'.
    """
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    if re.search(r"[^a-z0-9-]", name):
        print(
            f"WARNING: step name {name!r} was normalized to {s!r} for the "
            f"output filename. If this collides with another step's name, "
            f"the second will overwrite the first on disk.",
            file=sys.stderr,
        )
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
    """v0.3.4: move the mouse to the target first, then click.

    v0.2.x used page.click() which teleports the cursor and clicks
    in the same frame. The video then shows the page jumping from
    A to B with no visible cursor travel, which looks like a demo
    step rather than a real click. We now:
      1. Resolve the selector
      2. Move the mouse toward the target in a few visible hops
      3. Hover ~150-300ms so the user sees the cursor arrive
      4. Click

    The agent can opt out with `instant_click: true` for steps where
    cursor animation isn't useful (e.g. clicking an offscreen anchor
    to scroll to a section).
    """
    import random
    resolver = SelectorResolver()
    selector = step["selector"]
    async def try_locator(variant: str):
        if step.get("instant_click"):
            await rec.page.click(variant, timeout=3000)
            return
        # 1) Find the target and compute its center
        loc = rec.page.locator(variant).first
        await loc.wait_for(state="visible", timeout=3000)
        box = await loc.bounding_box()
        if box is None:
            # Off-screen or hidden — fall back to teleport-click
            await rec.page.click(variant, timeout=3000)
            return
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        # 2) Move from current position to the target in 2-3 visible
        #    hops. This produces a visible cursor trail in the video.
        try:
            cur = await rec.page.evaluate("() => ({ x: window.__lastMouseX ?? 0, y: window.__lastMouseY ?? 0 })")
            sx, sy = cur.get("x", 0), cur.get("y", 0)
        except Exception:
            sx, sy = 0, 0
        steps = random.randint(8, 18)
        for i in range(1, steps + 1):
            t = i / steps
            # Ease-in-out cubic for a natural arc
            e = t * t * (3 - 2 * t)
            mx = sx + (cx - sx) * e + random.uniform(-2, 2)
            my = sy + (cy - sy) * e + random.uniform(-2, 2)
            await rec.page.mouse.move(mx, my)
            await rec.page.wait_for_timeout(random.randint(8, 20))
        # 3) Hover pause so the cursor sits on the target
        await rec.page.wait_for_timeout(random.randint(120, 250))
        # 4) Click
        await rec.page.mouse.click(cx, cy)
        # Record position for next time
        try:
            await rec.page.evaluate(
                f"() => {{ window.__lastMouseX = {cx}; window.__lastMouseY = {cy}; }}"
            )
        except Exception:
            pass
    ok, winning, attempts = await resolver.attempt_async(selector, try_locator)
    return ok, winning, attempts


async def _handle_type(rec: Recorder, step: dict) -> None:
    """v0.3.4: type with realistic per-character delay.

    v0.2.x used page.fill() which sets the value in a single frame, so
    the recorded video shows text appearing all at once (looks like a
    demo, not a real person typing). We now focus the element and
    press one key at a time with a small per-character delay
    (60-120ms, jittered) so the user sees the characters stream in
    one-by-one, matching real touch-typing cadence.

    The agent can opt out by setting `instant_type: true` for password
    fields or other cases where animation isn't desired.
    """
    selector = step["selector"]
    text = step["text"]
    if step.get("instant_type"):
        # Original fast path: single-frame fill. Used for passwords and
        # other cases where per-char animation hurts more than helps.
        await rec.page.fill(selector, text)
    else:
        # Click the field to focus, then type one char at a time.
        # The click is on the same selector so it lands inside the input.
        await rec.page.click(selector, timeout=3000)
        import random
        for ch in text:
            # 60-120ms per char (avg ~90ms) — looks like fast typing.
            delay_ms = random.randint(60, 120)
            await rec.page.keyboard.type(ch, delay=delay_ms)
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
    # v0.3.3: also remember the page URL so _handle_video_stop can re-navigate
    # the fresh page back to the same URL (otherwise the new page opens at
    # about:blank and every step after this video_stop fails).
    name = _to_kebab(step["name"])
    try:
        recording_url = rec.page.url
    except Exception:
        recording_url = ""
    name_to_path[f"_video_{name}"] = {
        "started_at": time.monotonic(),
        "started_wall": time.time(),
        "recording_page": rec.page,
        "recording_url": recording_url,
        "base_url": rec._last_base_url,
    }
    # v0.3.8: inject the HUD (cursor + keystroke badges + click
    # ripples) into the recorded page. The listener is registered
    # earlier (in Recorder.start() via context.add_init_script) so
    # it's already tracking mouse + keys from the very first
    # navigation. All we need here is to create the visible DOM
    # elements and wire them to the listener's state callbacks.
    # Pattern: see demowright (snomiao/demowright, MIT) for the
    # addInitScript + callback-wired DOM injector split.
    try:
        from recorder_plugin.cursor import inject_overlay
        await inject_overlay(rec.page)
    except Exception as e:
        print(
            f"WARNING: HUD overlay injection failed for video '{name}' "
            f"({type(e).__name__}: {e}); video will not show cursor/keys.",
            file=sys.stderr,
        )


async def _handle_video_stop(
    rec: Recorder, step: dict, name_to_path: dict, output_dir: Path,
    *, reopen_after_video: bool = False, preserve_session: bool = False,
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

    # v0.3.5: capture localStorage BEFORE closing the recording page,
    # so we can replay it on the fresh page that replaces the closed one.
    # This is what lets cross-video flows stay logged in (and skip the
    # repeated-login intro that v0.3.3 forced on every video segment).
    name_key = f"_video_{name}"
    session = name_to_path.get(name_key, {})
    recording_page = session.get("recording_page") if isinstance(session, dict) else None
    captured_storage: dict = {}
    if preserve_session and recording_page is not None and not recording_page.is_closed():
        try:
            captured_storage = await recording_page.evaluate(
                "() => { const out = {};"
                " for (let i = 0; i < localStorage.length; i++) {"
                "   const k = localStorage.key(i);"
                "   out[k] = localStorage.getItem(k);"
                " }"
                " return out; }"
            )
        except Exception as e:
            print(
                f"WARNING: video_stop localStorage capture failed "
                f"({type(e).__name__}: {e}); session won't be preserved.",
                file=sys.stderr,
            )
    # Flush the webm: close the page that was active during recording.
    # v0.2.4 audit round 3 (H2): wrap page close in wait_for so a hung
    # Playwright teardown cannot block the whole script. TimeoutError
    # is logged as a warning — the webm may still flush from the
    # Playwright context teardown at session end.
    # v0.3.8: tear down the HUD overlay before closing so the
    # closed-page's last frame doesn't show a floating cursor /
    # key chip in the resulting webm. remove_overlay() also
    # nulls out the state callbacks so a later video_start
    # inject gets a clean slate.
    if recording_page is not None and not recording_page.is_closed():
        try:
            from recorder_plugin.cursor import remove_overlay
            await remove_overlay(recording_page)
        except Exception as e:
            print(
                f"WARNING: HUD cleanup failed for video '{name}' "
                f"({type(e).__name__}: {e}); overlay may be visible in "
                f"last frame.",
                file=sys.stderr,
            )
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
    # v0.3.3: re-navigate the fresh page to the URL that was active during
    # recording. Without this, the new page opens at about:blank and every
    # step after this video_stop fails (wait_for, click, type, screenshot
    # all target elements that no longer exist). Fall back to the script
    # root URL if we somehow lost the recording URL.
    new_page = None
    try:
        new_page = await rec.context.new_page()
        rec._page = new_page
    except Exception:
        pass
    # v0.3.5: replay localStorage onto the fresh page. Order matters:
    #   1. Navigate to the recording origin (about:blank has no localStorage)
    #   2. Write the captured keys
    #   3. Reload so the app reads the restored localStorage on init
    # This is what lets cross-video flows stay logged in (and skip the
    # repeated-login intro that v0.3.3 forced on every video segment).
    target_url = ""
    base_url = ""
    if reopen_after_video and new_page is not None:
        target_url = session.get("recording_url", "") if isinstance(session, dict) else ""
        base_url = session.get("base_url", "") if isinstance(session, dict) else ""
    if reopen_after_video and new_page is not None and target_url and target_url != "about:blank":
        try:
            from urllib.parse import urljoin
            full = urljoin(base_url, target_url) if base_url else target_url
            await new_page.goto(full, wait_until="domcontentloaded")
            if preserve_session and captured_storage:
                for k, v in captured_storage.items():
                    await new_page.evaluate(
                        "(args) => localStorage.setItem(args.k, args.v)",
                        {"k": k, "v": v},
                    )
                # Reload so the app reads the restored localStorage on init
                await new_page.reload(wait_until="domcontentloaded")
        except Exception as e:
            print(
                f"WARNING: video_stop re-navigate to {target_url!r} failed "
                f"({type(e).__name__}: {e}); subsequent steps may fail.",
                file=sys.stderr,
            )

    return asset


def _preflight_narration_coverage(steps: list, *, force: bool = False) -> None:
    """v0.5.1: walk the script's steps and warn if any video_stop step is
    missing the `narration` field. Without this, _apply_narration is
    silently skipped at video_stop time and the user gets a silent video
    with no indication of why.

    Behavior:
      - If NO video_stop step has narration: print a single WARNING
        listing the count of video sessions, with the fix hint
        "add `narration: [...]` to each video_stop step". This is the
        most common silent-failure case (LLM forgot the field).
      - If SOME have narration: print a per-session warning so the
        user can fill in the missing ones.
      - If `force=True` (set by --strict-narration), raise instead of
        warn — for CI envs that want hard enforcement.
    """
    video_stops = [s for s in steps if s.get("action") == "video_stop"]
    if not video_stops:
        return  # No video sessions, nothing to check.
    # v0.5.3: also reject `narration: <not a list>`. A string like
    # "step 1, step 2" is truthy but _apply_narration (line 552) skips it
    # via isinstance(narration_segs, list) check, producing silent video.
    have_narration = [s for s in video_stops
                      if s.get("narration") and isinstance(s.get("narration"), list)]
    missing = [s for s in video_stops
               if not s.get("narration") or not isinstance(s.get("narration"), list)]
    if not missing:
        return  # All video_stops have narration — good.
    missing_names = [s.get("name", f"<step-{i}>") for i, s in enumerate(missing)]
    if not have_narration:
        # Most common case: the LLM generated a script with NO
        # narration fields at all. Loud, single warning.
        msg = (
            f"WARNING: {len(missing)} video session(s) have NO `narration` field; "
            f"output videos will be SILENT. Fix: add `narration: [one string per step]` "
            f"to each video_stop step (one segment per task-card step). "
            f"Missing: {missing_names}"
        )
    else:
        msg = (
            f"WARNING: {len(missing)} of {len(video_stops)} video session(s) "
            f"missing `narration`; will be silent: {missing_names}. "
            f"Pass --strict-narration to fail-fast."
        )
    if force:
        raise RuntimeError(msg.replace("WARNING: ", "ERROR: "))
    print(msg, file=sys.stderr)


async def _apply_narration(
    asset: AssetRef, narration_segs: list, step: dict, output_dir: Path
) -> AssetRef:
    """v0.3.2: synthesize narration segments and mux them onto a recorded video.

    narration_segs: list of strings, one per task-card step.
    step.narration_gap: optional float, seconds of silence between segments
        (default 2.0). step.narration_voice / step.narration_rate override
        the global defaults for this video.

    Returns a NEW AssetRef whose .path is the muxed mp4 (the original silent
    mp4 is moved to a `.silent.mp4` sibling for archival). If TTS is not
    available (edge-tts not installed) we raise so the caller can warn-and-
    fallback; we do NOT auto-fall back to silent here, because callers
    almost always want to know whether narration actually worked.
    """
    from recorder_plugin import tts as tts_mod
    from recorder_plugin import mux_audio
    from recorder_plugin.core import AssetRef as _AR  # local re-import for typing

    if not tts_mod.is_available():
        raise tts_mod.TTSError(
            "edge-tts is not installed; skipping narration. "
            "Run: pip install edge-tts"
        )

    voice = step.get("narration_voice") or tts_mod.get_default_voice()
    rate = step.get("narration_rate") or tts_mod.get_default_rate()
    gap = float(step.get("narration_gap", 2.0))

    # 1) Synthesize each segment to a temp file.
    # v0.3.2 (round 3): use the ASYNC `asynthesize` here. The previous sync
    # `synthesize` was called from inside this async function and the
    # `loop.create_task` branch returned a Task that the caller never awaited,
    # so the mp3 files were never written before concat_segments_with_gaps
    # tried to read them — FileNotFoundError was raised and silently swallowed.
    seg_dir = output_dir / "_narration_segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    seg_paths: list[Path] = []
    # Share one semaphore across all N segments so we don't hammer edge-tts.
    sem = tts_mod.new_semaphore()
    for idx, text in enumerate(narration_segs):
        if not text or not str(text).strip():
            continue  # silently skip empty steps (they'd be empty audio)
        seg_path = seg_dir / f"{asset.path.stem}.seg{idx:02d}.mp3"
        await tts_mod.asynthesize(
            str(text), seg_path, voice=voice, rate=rate, semaphore=sem
        )
        seg_paths.append(seg_path)
    if not seg_paths:
        raise tts_mod.TTSError("all narration segments were empty")

    # 2) Concat with gaps → full narration
    narr_path = output_dir / f"{asset.path.stem}.narration.mp3"
    if len(seg_paths) == 1:
        # Single segment: skip gap concat to avoid ffmpeg round-trip
        narr_path.write_bytes(seg_paths[0].read_bytes())
    else:
        mux_audio.concat_segments_with_gaps(seg_paths, narr_path, gap_seconds=gap)

    # 3) Mux narration onto the (silent) video
    out_mp4 = asset.path  # overwrite in place
    silent_backup = asset.path.with_suffix(".silent.mp4")
    try:
        asset.path.rename(silent_backup)
    except FileNotFoundError:
        silent_backup = None
    mux_audio.mux_narration_with_video(
        silent_backup if silent_backup else asset.path,
        narr_path,
        out_mp4,
    )

    # Return a fresh AssetRef pointing at the muxed file
    new_ref = _AR(
        path=out_mp4,
        kind=asset.kind,
        size_bytes=out_mp4.stat().st_size,
        slice_index=asset.slice_index,
    )
    # Stash narration metadata for the script-level output dict
    new_ref.extra = dict(asset.extra or {})
    new_ref.extra["narration_segments"] = len(seg_paths)
    new_ref.extra["narration_gap_s"] = gap
    new_ref.extra["narration_voice"] = voice
    new_ref.extra["narration_seconds"] = sum(
        # rough estimate: each segment's file size / (24kHz * 1ch * 1byte ≈ 24kB/s)
        # not exact, but the agent can re-ffprobe if it needs the truth.
        p.stat().st_size / 24000.0 for p in seg_paths
    )
    return new_ref


async def run_script(script_path: Path) -> dict:
    """Execute a declarative JSON script. Returns the output dict (per spec §6.2)."""
    script_path = Path(script_path)
    # M4 fix (v0.2.4 audit round 3): wrap the script load in
    # try/except so a corrupt or missing script returns a clean
    # JSON error envelope instead of an uncaught traceback. The
    # dispatch loop already has its own try/except per step, but
    # this load is OUTSIDE the loop and would crash asyncio.run.
    try:
        script_data = json.loads(script_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "script": script_path.stem, "status": "error",
            "errors": [{"step": -1, "action": "load",
                        "error": f"script file not found: {script_path}"}],
        }
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return {
            "script": script_path.stem, "status": "error",
            "errors": [{"step": -1, "action": "load",
                        "error": f"could not parse script: {type(e).__name__}: {e}"}],
        }
    data = script_data
    script_name = data.get("name", script_path.stem)
    output_dir = Path(data.get("output_dir", "."))
    output_dir.mkdir(parents=True, exist_ok=True)
    viewport = data.get("viewport", {"width": 1280, "height": 800})
    record_video = any(s.get("action") in ("video_start", "video_stop") for s in data["steps"])
    rec_dir = output_dir / "_video_buffer" if record_video else None
    if rec_dir:
        rec_dir.mkdir(parents=True, exist_ok=True)
    # v0.5.1: preflight narration coverage. Without this, missing
    # `narration` fields silently produce silent videos (see
    # _preflight_narration_coverage docstring for the failure mode).
    _preflight_narration_coverage(data["steps"])
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
    # v0.3.3: opt-in auto re-navigation after video_stop. Default False —
    # the script author must explicitly `navigate` to the right URL between
    # videos. Setting `reopen_page_after_video: true` in the script makes
    # the recorder capture the recording URL and replay it on the fresh
    # page that replaces the closed recording page. Useful for stateless
    # apps (public marketing pages) but harmful for stateful apps
    # (Vue/React SPAs that lose in-memory auth on reload).
    reopen_after_video = bool(data.get("reopen_page_after_video", False))
    # v0.3.5: opt-in session preservation across video_stop boundaries.
    # When true, the recorder captures the recording page's localStorage
    # BEFORE closing it (Playwright only flushes webm on page close),
    # then replays the captured entries on the fresh page and reloads
    # so the app's init code reads the restored state. This is what
    # makes cross-video flows feel continuous instead of forcing a
    # "log in again" intro on every segment. Requires the app to
    # actually use localStorage for auth; in-memory auth needs the
    # app to be edited to opt in.
    preserve_session = bool(data.get("preserve_session", False))

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
                    asset = await _handle_video_stop(rec, step, name_to_path, output_dir, reopen_after_video=reopen_after_video, preserve_session=preserve_session)
                    # v0.3.2: optional narration. If the video_stop step carries
                    # `narration` (a list of strings, one per step), synthesize each
                    # segment, concatenate with gaps, then mux onto the recorded
                    # video. Failures are non-fatal (warn, keep the silent video)
                    # because TTS is opt-in and the user may be offline.
                    narration_segs = step.get("narration")
                    if narration_segs and isinstance(narration_segs, list) and narration_segs:
                        try:
                            asset = await _apply_narration(asset, narration_segs, step, output_dir)
                        except Exception as e:
                            print(
                                f"WARNING: narration failed for video '{name}' "
                                f"({type(e).__name__}: {e}); keeping silent video.",
                                file=sys.stderr,
                            )
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
