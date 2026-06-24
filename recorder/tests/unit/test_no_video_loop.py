"""v0.3.6: mux_narration_with_video must NEVER loop the video.

The v0.3.2-v0.3.5 design looped the video when narration was longer
than video (to fill the voiceover). This made the user see the same
operation multiple times in a row — a 3.5s login video with 14.8s of
narration would show the login 4 times back-to-back. The user reported
this as "视频内容在重复" (video content repeats).

v0.3.6 changes the contract: output duration = min(video, narration).
The video is the canonical timeline; narration may be trimmed but
never stretched by looping.

This test locks in the new contract.
"""
import ast
from pathlib import Path
import pytest

MUX_PY = Path(__file__).resolve().parents[2] / "recorder_plugin" / "mux_audio.py"


def _parse() -> ast.Module:
    return ast.parse(MUX_PY.read_text())


def test_mux_narration_does_not_loop_video():
    """The ffmpeg command must NOT contain -stream_loop.

    The check is scoped to the function body (AST.unparse) so that
    docstring history prose that mentions "-stream_loop -1" as
    "this is what we used to do" doesn't trip the test. The contract
    is about the *code* not looping the video, not the docstring
    being silent about it.
    """
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.FunctionDef) and node.name == "mux_narration_with_video":
            body = ast.unparse(node)
            assert "stream_loop" not in body, (
                "mux_narration_with_video body must NOT use -stream_loop; "
                "looping the video makes the user watch the same operation "
                "multiple times. See SKILL.md §16.2 and v0.3.6 changelog."
            )
            return
    pytest.fail("mux_narration_with_video not found")


def test_mux_narration_uses_min_duration():
    """Output duration must be min(vid_dur, audio_dur), not audio_dur."""
    src = MUX_PY.read_text()
    mod = _parse()
    for node in ast.walk(mod):
        if isinstance(node, ast.FunctionDef) and node.name == "mux_narration_with_video":
            body = ast.unparse(node)
            # Look for the line computing out_dur
            assert "out_dur = min" in body, (
                "mux_narration_with_video must compute out_dur = min(vid_dur, audio_dur); "
                "if this is missing, the function will use audio_dur unconditionally "
                "and either loop the video (old behavior) or cut mid-action."
            )
            # And it must be used in the ffmpeg -t flag
            assert '"-t"' in body or "'-t'" in body and "out_dur" in body, (
                "ffmpeg -t must use out_dur, not audio_dur"
            )
            return
    pytest.fail("mux_narration_with_video not found")


def test_mux_narration_skips_loop_decision():
    """The old `loop_video = audio_dur > vid_dur` must be gone — it's the
    trigger for the bad behavior."""
    src = MUX_PY.read_text()
    assert "loop_video" not in src, (
        "mux_narration_with_video must not have a loop_video variable; "
        "the loop behavior is removed in v0.3.6."
    )
