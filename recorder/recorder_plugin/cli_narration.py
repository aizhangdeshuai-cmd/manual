"""CLI subcommands for TTS synthesis and narration muxing.

Two new subcommands, following the user-manual `manual_helper.py` style
(no argparse, hand-rolled dispatch):

  python3 -m recorder_plugin.cli tts-synth <text> --out PATH
                                [--voice ID] [--rate PCT]
  python3 -m recorder_plugin.cli mux-audio <video> <audio> --out PATH
  python3 -m recorder_plugin.cli concat-narration <seg1> <seg2> [...]
                                --out PATH [--gap SECONDS]

All three exit 0 on success, non-zero on error, with errors on stderr.
On success they print a one-line JSON with the output path and metadata.

v0.3.2 — first version.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import List


def _print_ok(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def cmd_tts_synth(argv: List[str]) -> int:
    """Synthesize one text segment to an mp3 file."""
    parser = argparse.ArgumentParser(
        prog="recorder tts-synth",
        description="Synthesize text to mp3 via edge-tts (no API key).",
    )
    parser.add_argument("text", help="Narration text. Use multiple calls for multiple steps.")
    parser.add_argument("--out", required=True, help="Output .mp3 path.")
    parser.add_argument("--voice", default=None,
                        help="Edge TTS voice id (default: zh-CN-XiaoxiaoNeural).")
    parser.add_argument("--rate", default=None,
                        help="Edge TTS rate string (default: +0%%). Example: +10%% for 10%% faster.")
    args = parser.parse_args(argv)

    from recorder_plugin import tts
    try:
        out_path = tts.synthesize(args.text, args.out, voice=args.voice, rate=args.rate)
    except tts.TTSError as e:
        _print_err(str(e))
        return 1

    _print_ok({
        "status": "ok",
        "output": str(out_path),
        "bytes": out_path.stat().st_size,
        "voice": args.voice or tts.get_default_voice(),
        "rate": args.rate or tts.get_default_rate(),
    })
    return 0


def cmd_concat_narration(argv: List[str]) -> int:
    """Concatenate multiple narration mp3s with optional silence gaps."""
    parser = argparse.ArgumentParser(
        prog="recorder concat-narration",
        description="Concatenate narration mp3s with silence gaps between them.",
    )
    parser.add_argument("segments", nargs="+", help="Input mp3 paths in order.")
    parser.add_argument("--out", required=True, help="Output .mp3 path.")
    parser.add_argument("--gap", type=float, default=2.0,
                        help="Silence between segments in seconds (default: 2.0).")
    args = parser.parse_args(argv)

    from recorder_plugin import mux_audio
    try:
        out_path = mux_audio.concat_segments_with_gaps(
            args.segments, args.out, gap_seconds=args.gap,
        )
    except (ValueError, FileNotFoundError, subprocess := __import__("subprocess").CalledProcessError) as e:
        # `subprocess` imported above to keep the except clause one-liner.
        _print_err(f"{type(e).__name__}: {e}")
        return 1

    _print_ok({
        "status": "ok",
        "output": str(out_path),
        "bytes": out_path.stat().st_size,
        "segments": len(args.segments),
        "gap_seconds": args.gap,
    })
    return 0


def cmd_mux_audio(argv: List[str]) -> int:
    """Mux a narration mp3 onto a video file, looping video if needed."""
    parser = argparse.ArgumentParser(
        prog="recorder mux-audio",
        description="Combine narration audio with a recorded video into one mp4.",
    )
    parser.add_argument("video", help="Input video path (webm or mp4).")
    parser.add_argument("audio", help="Input audio path (mp3).")
    parser.add_argument("--out", required=True, help="Output .mp4 path.")
    args = parser.parse_args(argv)

    from recorder_plugin import mux_audio
    try:
        out_path = mux_audio.mux_narration_with_video(args.video, args.audio, args.out)
    except (FileNotFoundError, __import__("subprocess").CalledProcessError) as e:
        _print_err(f"{type(e).__name__}: {e}")
        return 1

    _print_ok({
        "status": "ok",
        "output": str(out_path),
        "bytes": out_path.stat().st_size,
    })
    return 0


SUBCOMMANDS = {
    "tts-synth": cmd_tts_synth,
    "concat-narration": cmd_concat_narration,
    "mux-audio": cmd_mux_audio,
}
