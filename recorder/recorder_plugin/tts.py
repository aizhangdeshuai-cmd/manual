"""TTS (text-to-speech) synthesis via edge-tts.

Public API:
    synthesize(text, output_path, *, voice=DEFAULT_VOICE, rate=DEFAULT_RATE) -> Path
    is_available() -> bool           # cheap import probe
    get_default_voice() -> str
    get_default_rate() -> str

Design notes:
- Built on `edge-tts` (rany2/edge-tts, 11k+ stars, MIT, 0 API key) — Microsoft's
  Edge online TTS service, no auth required. We use the asyncio client.
- Retry: 5 attempts, exponential backoff capped at 10s. Mirrors the battle-tested
  retry shape in Pixelle-Video's tts_util (Apache-2.0, similar domain).
- Concurrency: 3 in-flight requests max (semaphore); 0.5s pacing between starts.
  Edge TTS throttles aggressively — uncapped calls produce NoAudioReceived / 401s.
- Returns the final output Path. Raises TTSError on hard failure (after retries).
- Hard import: edge-tts is a recorder-level dependency (per CONTRIBUTING.md,
  opt-in plugins may declare their own deps; declared in pyproject.toml).

v0.3.2 — first version.
"""
from __future__ import annotations
import asyncio
import logging
import os
import ssl
import time
from pathlib import Path
from typing import Optional

# Edge TTS defaults — matched against Pixelle-Video's battle-tested values.
RETRY_COUNT = 5
RETRY_BASE_DELAY = 1.0
MAX_RETRY_DELAY = 10.0
REQUEST_DELAY = 0.5
MAX_CONCURRENT_REQUESTS = 3

logger = logging.getLogger(__name__)

# Lazy import — module-level import would force edge-tts on every recorder
# invocation (including pure-screenshot runs without narration). The recorder
# already does this pattern for playwright.
_edge_tts_mod = None
_import_error: Optional[BaseException] = None


def _ensure_edge_tts():
    global _edge_tts_mod, _import_error
    if _edge_tts_mod is not None:
        return _edge_tts_mod
    if _import_error is not None:
        raise _import_error
    try:
        import edge_tts  # type: ignore
    except ImportError as e:
        _import_error = e
        raise TTSError(
            "edge-tts is not installed. Install with: pip install edge-tts"
        ) from e
    _edge_tts_mod = edge_tts
    return edge_tts


class TTSError(RuntimeError):
    """Raised when synthesis fails after all retries."""


def is_available() -> bool:
    """Cheap probe: can we import edge-tts? Used by check-recording-readiness.

    Catches BOTH TTSError (our wrapper) and the raw ImportError
    (in case edge_tts is missing — the lazy import raises ImportError,
    we wrap it in TTSError, but the second time it's called we just
    re-raise the cached exception which is the original ImportError).
    """
    try:
        _ensure_edge_tts()
        return True
    except (TTSError, ImportError):
        return False


def get_default_voice() -> str:
    from recorder_plugin.tts_voices import DEFAULT_VOICE
    return DEFAULT_VOICE


def get_default_rate() -> str:
    from recorder_plugin.tts_voices import DEFAULT_RATE
    return DEFAULT_RATE


# --- async core --------------------------------------------------------------

async def _synthesize_async(
    text: str,
    output_path: Path,
    *,
    voice: str,
    rate: str,
    semaphore: asyncio.Semaphore,
) -> Path:
    edge_tts = _ensure_edge_tts()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # rate param accepts strings like "+0%", "+10%", "-20%". We pass through.
    last_err: Optional[BaseException] = None
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            async with semaphore:
                # Pacing: small sleep BEFORE the request, not after, so we don't
                # delay the final attempt on success.
                if REQUEST_DELAY > 0:
                    await asyncio.sleep(REQUEST_DELAY)
                comm = edge_tts.Communicate(text, voice=voice, rate=rate)
                await comm.save(str(output_path))
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise TTSError(f"edge-tts produced empty file at {output_path}")
            return output_path
        except Exception as e:  # noqa: BLE001 — broad: edge-tts raises diverse
            # transient errors (NoAudioReceived, WSServerHandshakeError,
            # ClientResponseError, OSError on SSL). We retry all of them.
            last_err = e
            if attempt >= RETRY_COUNT:
                break
            delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
            logger.warning(
                "tts: attempt %d/%d failed (%s: %s); retrying in %.1fs",
                attempt, RETRY_COUNT, type(e).__name__, e, delay,
            )
            await asyncio.sleep(delay)

    raise TTSError(
        f"edge-tts failed after {RETRY_COUNT} attempts: "
        f"{type(last_err).__name__}: {last_err}"
    )


# --- sync public API ---------------------------------------------------------

async def asynthesize(
    text: str,
    output_path: Path | str,
    *,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
    semaphore: Optional[asyncio.Semaphore] = None,
) -> Path:
    """Async API: await to synthesize `text` to `output_path` and return the Path.

    Use this from inside a running event loop (e.g. recorder's _apply_narration).
    Pass a shared `semaphore` if you want cross-call concurrency control;
    otherwise a fresh per-call semaphore is created.

    Args:
        text: narration text.
        output_path: destination .mp3 (will be created/overwritten).
        voice: Edge TTS voice id (default from tts_voices.DEFAULT_VOICE).
        rate: Edge TTS rate string (default "+0%").
        semaphore: optional shared asyncio.Semaphore for cross-call concurrency.

    Raises:
        TTSError: on hard failure (import, retries exhausted, empty output).
    """
    output_path = Path(output_path)
    voice = voice or get_default_voice()
    rate = rate or get_default_rate()
    if not text or not text.strip():
        raise TTSError("tts: text is empty")
    sem = semaphore or asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    return await _synthesize_async(
        text, output_path, voice=voice, rate=rate, semaphore=sem
    )


def synthesize(
    text: str,
    output_path: Path | str,
    *,
    voice: Optional[str] = None,
    rate: Optional[str] = None,
) -> Path:
    """Sync API: synthesize `text` to `output_path` and return the Path.

    Use this from sync code (CLI handlers, scripts, tests). Internally runs
    a fresh event loop via asyncio.run — DO NOT call from inside a running
    loop (use `await tts.asynthesize(...)` instead). A clear RuntimeError is
    raised in that case so the bug surfaces immediately, not silently later
    when downstream code finds the output file missing.

    Args:
        text: narration text.
        output_path: destination .mp3 (will be created/overwritten).
        voice: Edge TTS voice id (default from tts_voices.DEFAULT_VOICE).
        rate: Edge TTS rate string (default "+0%").

    Raises:
        RuntimeError: if called from inside a running event loop.
        TTSError: on hard failure (import, retries exhausted, empty output).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "tts.synthesize() called from inside a running event loop; "
            "use `await tts.asynthesize(...)` instead."
        )
    return asyncio.run(
        asynthesize(text, output_path, voice=voice, rate=rate)
    )


def new_semaphore(value: int = MAX_CONCURRENT_REQUESTS) -> asyncio.Semaphore:
    """Return a fresh asyncio.Semaphore. Callers can share it across many
    `asynthesize` calls to cap concurrent edge-tts requests."""
    return asyncio.Semaphore(value)


# Backward-compat shim: keep _get_or_create_loop_semaphore so any leftover callers (we removed all of them) still import without NameError. New code uses `new_semaphore()` directly.
_loop_semaphores: dict[int, asyncio.Semaphore] = {}
def _get_or_create_loop_semaphore(loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
    key = id(loop)
    sem = _loop_semaphores.get(key)
    if sem is None:
        sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        _loop_semaphores[key] = sem
    return sem
