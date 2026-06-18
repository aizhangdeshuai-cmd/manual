"""Edge TTS voice presets for the user-manual recorder.

Pure data, no runtime imports — safe to read from anywhere.
Mirrors the well-tested Chinese voice list that mainstream short-video
tools (e.g. Pixelle-Video) settle on; for a full list run:

    python3 -c "import asyncio, edge_tts; \
        print('\\n'.join(v['ShortName'] for v in \
            asyncio.run(edge_tts.list_voices()) if v['Locale'].startswith('zh-')))"

v0.3.2 — added for narration (video voiceover) support.
"""
from __future__ import annotations
from typing import List, Dict, Any


EDGE_TTS_VOICES: List[Dict[str, Any]] = [
    # Mandarin (Simplified) — mainline Chinese for business manuals
    {"id": "zh-CN-XiaoxiaoNeural", "locale": "zh-CN", "gender": "female",
     "name_zh": "晓晓", "style": "warm"},          # default — most common in business docs
    {"id": "zh-CN-YunxiNeural",    "locale": "zh-CN", "gender": "male",
     "name_zh": "云希", "style": "neutral"},
    {"id": "zh-CN-YunjianNeural",  "locale": "zh-CN", "gender": "male",
     "name_zh": "云健", "style": "news"},
    {"id": "zh-CN-XiaoyiNeural",   "locale": "zh-CN", "gender": "female",
     "name_zh": "晓伊", "style": "lively"},
    {"id": "zh-CN-YunyangNeural",  "locale": "zh-CN", "gender": "male",
     "name_zh": "云扬", "style": "professional"},   # news anchor style
    {"id": "zh-CN-YunxiaNeural",   "locale": "zh-CN", "gender": "male",
     "name_zh": "云夏", "style": "calm"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "locale": "zh-CN-liaoning", "gender": "female",
     "name_zh": "晓北(辽宁)", "style": "dialect"},
    # Mandarin (Traditional) / Cantonese
    {"id": "zh-HK-HiuGaaiNeural",  "locale": "zh-HK", "gender": "female",
     "name_zh": "晓佳(港)", "style": "cantonese"},
    {"id": "zh-HK-WanLungNeural",  "locale": "zh-HK", "gender": "male",
     "name_zh": "云龙(港)", "style": "cantonese"},
    {"id": "zh-TW-HsiaoChenNeural","locale": "zh-TW", "gender": "female",
     "name_zh": "晓臻(台)", "style": "taiwanese"},
    # English (for international audiences)
    {"id": "en-US-JennyNeural",    "locale": "en-US", "gender": "female",
     "name_zh": "Jenny(美)", "style": "friendly"},
    {"id": "en-US-GuyNeural",      "locale": "en-US", "gender": "male",
     "name_zh": "Guy(美)", "style": "neutral"},
]


DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE = "+0%"  # Edge TTS "rate" param; "+10%" = 10% faster


def get_voice(voice_id: str) -> Dict[str, Any] | None:
    """Look up a voice preset by id. Returns None if not in the curated list.

    Edge TTS accepts any voice short-name; this curated list is just
    for `manual-config.json` validation and the agent's `default_voice` picker.
    """
    for v in EDGE_TTS_VOICES:
        if v["id"] == voice_id:
            return v
    return None
