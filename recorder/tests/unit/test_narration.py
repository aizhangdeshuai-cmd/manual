"""Unit tests for v0.3.2 narration (TTS + audio mux).

Tests are stdlib unittest only (no pytest, no edge-tts SDK mock — we test
the public contract: inputs → outputs). Heavy ffmpeg integration is covered
by recorder/tests/integration/test_video.py.

v0.3.2 — first version.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import skipIf

# Skip ALL tests if ffmpeg isn't available — these tests shell out to it.
ffmpeg_ok = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

# Skip TTS-specific tests if edge-tts isn't installed.
try:
    import edge_tts  # noqa: F401
    edge_tts_ok = True
except ImportError:
    edge_tts_ok = False


@skipIf(not ffmpeg_ok, "ffmpeg/ffprobe not on PATH")
class TestMuxAudio(unittest.TestCase):
    """Mux_audio public API."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="um-mux-test-"))
        # Build a 5s silent test video: solid color, 1280x720, no audio.
        self.video = self.tmp / "src.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=0x222222:s=320x240:d=5",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(self.video),
        ], check=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generate_silence_mp3_creates_valid_file(self) -> None:
        from recorder_plugin.mux_audio import generate_silence_mp3
        out = self.tmp / "silence.mp3"
        generate_silence_mp3(1.5, out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 100)
        # Verify with ffprobe
        info = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(out),
        ], capture_output=True, text=True, check=True)
        dur = float(info.stdout.strip())
        self.assertAlmostEqual(dur, 1.5, delta=0.2)

    def test_concat_segments_no_gap(self) -> None:
        from recorder_plugin.mux_audio import generate_silence_mp3, concat_segments_with_gaps
        a = self.tmp / "a.mp3"
        b = self.tmp / "b.mp3"
        generate_silence_mp3(1.0, a)
        generate_silence_mp3(1.0, b)
        out = self.tmp / "joined.mp3"
        concat_segments_with_gaps([a, b], out, gap_seconds=0)
        info = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(out),
        ], capture_output=True, text=True, check=True)
        dur = float(info.stdout.strip())
        self.assertAlmostEqual(dur, 2.0, delta=0.2)

    def test_concat_segments_with_gap(self) -> None:
        from recorder_plugin.mux_audio import generate_silence_mp3, concat_segments_with_gaps
        a = self.tmp / "a.mp3"
        b = self.tmp / "b.mp3"
        generate_silence_mp3(1.0, a)
        generate_silence_mp3(1.0, b)
        out = self.tmp / "joined.mp3"
        concat_segments_with_gaps([a, b], out, gap_seconds=2.0)
        info = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(out),
        ], capture_output=True, text=True, check=True)
        dur = float(info.stdout.strip())
        # 1s + 2s gap + 1s = 4s total
        self.assertAlmostEqual(dur, 4.0, delta=0.3)

    def test_concat_empty_segments_raises(self) -> None:
        from recorder_plugin.mux_audio import concat_segments_with_gaps
        with self.assertRaises(ValueError):
            concat_segments_with_gaps([], self.tmp / "x.mp3")

    def test_concat_missing_segment_raises(self) -> None:
        from recorder_plugin.mux_audio import concat_segments_with_gaps
        missing = self.tmp / "nope.mp3"
        with self.assertRaises(FileNotFoundError):
            concat_segments_with_gaps([missing], self.tmp / "x.mp3")

    def test_mux_audio_longer_loops_video_to_audio(self) -> None:
        """Audio longer than video → video is looped, output == audio_dur.

        v0.3.2 (round 2): we use `-t <audio_dur>` rather than `-shortest` so
        both "audio longer" and "audio shorter" cases converge to exactly
        audio_dur output (avoids ffmpeg's stream_loop + -shortest boundary bug).
        """
        from recorder_plugin.mux_audio import generate_silence_mp3, mux_narration_with_video
        # 8s audio > 5s video
        audio = self.tmp / "long.mp3"
        generate_silence_mp3(8.0, audio)
        out = self.tmp / "out.mp4"
        mux_narration_with_video(self.video, audio, out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 100)
        info = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(out),
        ], capture_output=True, text=True, check=True)
        # Output duration == audio duration (8s), NOT video (5s)
        self.assertAlmostEqual(float(info.stdout.strip()), 8.0, delta=0.5)

    def test_mux_missing_video_raises(self) -> None:
        from recorder_plugin.mux_audio import generate_silence_mp3, mux_narration_with_video
        audio = self.tmp / "a.mp3"
        generate_silence_mp3(1.0, audio)
        with self.assertRaises(FileNotFoundError):
            mux_narration_with_video(self.tmp / "nope.mp4", audio, self.tmp / "out.mp4")


@skipIf(not edge_tts_ok, "edge-tts not installed")
class TestTTSAsync(unittest.TestCase):
    """v0.3.2 (round 3): the async API is what recorder's _apply_narration uses.

    Critical regression: the previous `synthesize` returned a non-awaited Task
    when called from inside a running event loop, so mp3 files were never
    written before downstream code tried to read them. The async API forces
    the caller to await.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="um-tts-async-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_asynthesize_writes_mp3(self) -> None:
        import asyncio
        from recorder_plugin import tts
        out = self.tmp / "async.mp3"

        async def go():
            return await tts.asynthesize("异步 API 测试。", out)

        result = asyncio.run(go())
        self.assertEqual(result, out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)

    def test_synthesize_from_running_loop_raises(self) -> None:
        """The fix: calling sync synthesize from inside a running loop must
        raise RuntimeError loudly, not silently return an un-awaited task."""
        import asyncio
        from recorder_plugin import tts

        async def go():
            # We're INSIDE a running loop. Sync synthesize must refuse.
            with self.assertRaises(RuntimeError) as cm:
                tts.synthesize("x", self.tmp / "x.mp3")
            self.assertIn("running event loop", str(cm.exception))
            self.assertIn("asynthesize", str(cm.exception))

        asyncio.run(go())

    def test_synthesize_outside_loop_still_works(self) -> None:
        """The sync API is preserved for CLI handlers and tests."""
        from recorder_plugin import tts
        out = self.tmp / "sync.mp3"
        tts.synthesize("同步 API 测试。", out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)

    def test_is_available_returns_false_on_missing_dep(self) -> None:
        """Regression: is_available must not raise when edge-tts is missing.

        The contract is "cheap probe returning bool" — used by
        check-recording-readiness which iterates over many capability checks
        and treats any exception as "broken" rather than "available".
        """
        from recorder_plugin import tts
        # Reset the module's lazy-import cache and inject a fake ImportError,
        # simulating "edge-tts not installed" without actually uninstalling.
        tts._edge_tts_mod = None
        tts._import_error = ImportError("simulated")
        try:
            result = tts.is_available()
        finally:
            # Restore real state so other tests in the suite still pass.
            tts._edge_tts_mod = None
            tts._import_error = None
        self.assertFalse(result)

    def test_new_semaphore_returns_usable_semaphore(self) -> None:
        """A 2-slot semaphore is acquirable twice before blocking the 3rd."""
        import asyncio
        from recorder_plugin import tts
        sem = tts.new_semaphore(value=2)

        async def go():
            await sem.acquire()
            await sem.acquire()
            # After 2 acquires on a 2-slot semaphore, the 3rd acquire must
            # block (we cancel it after a tiny wait to prove it's blocking).
            blocked = True
            try:
                await asyncio.wait_for(sem.acquire(), timeout=0.05)
                blocked = False
            except asyncio.TimeoutError:
                pass
            sem.release()
            sem.release()
            return blocked

        self.assertTrue(asyncio.run(go()))


class TestTTS(unittest.TestCase):
    """TTS public API (light integration test; relies on network)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="um-tts-test-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_synthesize_writes_nonempty_mp3(self) -> None:
        from recorder_plugin import tts
        out = self.tmp / "hello.mp3"
        result = tts.synthesize("你好,这是一个测试。", out)
        self.assertEqual(result, out)
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)  # mp3 with real audio > 1KB

    def test_synthesize_empty_text_raises(self) -> None:
        from recorder_plugin import tts
        with self.assertRaises(tts.TTSError):
            tts.synthesize("", self.tmp / "x.mp3")

    def test_synthesize_voice_override(self) -> None:
        """Different voices produce different file sizes (different waveforms)."""
        from recorder_plugin import tts
        a = self.tmp / "a.mp3"
        b = self.tmp / "b.mp3"
        tts.synthesize("测试不同音色。", a, voice="zh-CN-XiaoxiaoNeural")
        tts.synthesize("测试不同音色。", b, voice="zh-CN-YunxiNeural")
        # Bytes will differ at least by the wav header / encoding quirks
        self.assertNotEqual(a.stat().st_size, b.stat().st_size)

    def test_is_available(self) -> None:
        from recorder_plugin import tts
        self.assertTrue(tts.is_available())

    def test_get_default_voice_returns_known(self) -> None:
        from recorder_plugin import tts
        from recorder_plugin.tts_voices import get_voice, DEFAULT_VOICE
        self.assertEqual(tts.get_default_voice(), DEFAULT_VOICE)
        self.assertIsNotNone(get_voice(DEFAULT_VOICE))


class TestTTSVoicesData(unittest.TestCase):
    """Static data sanity for tts_voices.py (no network, no ffmpeg)."""

    def test_voice_list_nonempty(self) -> None:
        from recorder_plugin.tts_voices import EDGE_TTS_VOICES
        self.assertGreaterEqual(len(EDGE_TTS_VOICES), 5)

    def test_default_voice_in_list(self) -> None:
        from recorder_plugin.tts_voices import EDGE_TTS_VOICES, DEFAULT_VOICE
        ids = {v["id"] for v in EDGE_TTS_VOICES}
        self.assertIn(DEFAULT_VOICE, ids)

    def test_all_voices_have_required_keys(self) -> None:
        from recorder_plugin.tts_voices import EDGE_TTS_VOICES
        for v in EDGE_TTS_VOICES:
            for key in ("id", "locale", "gender", "name_zh", "style"):
                self.assertIn(key, v, f"voice {v.get('id')} missing {key}")

    def test_get_voice_unknown_returns_none(self) -> None:
        from recorder_plugin.tts_voices import get_voice
        self.assertIsNone(get_voice("totally-fake-voice-id"))


class TestCLINarration(unittest.TestCase):
    """CLI subcommand dispatch (no actual ffmpeg/TTS)."""

    def test_subcommands_registered(self) -> None:
        from recorder_plugin.cli_narration import SUBCOMMANDS
        self.assertIn("tts-synth", SUBCOMMANDS)
        self.assertIn("concat-narration", SUBCOMMANDS)
        self.assertIn("mux-audio", SUBCOMMANDS)

    def test_cli_dispatches_to_narration(self) -> None:
        """The 3 narration subcommands are recognized (not "unknown subcommand").

        We feed a known-bad payload (missing --out) and assert that the error
        path is argparse usage, NOT the cli.py "unknown subcommand" branch.
        argparse calls sys.exit(2) on usage error, which surfaces as SystemExit.
        """
        import io
        from contextlib import redirect_stderr
        from recorder_plugin.cli import main
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                rc = main(["cli", "tts-synth", "some text"])
        except SystemExit as e:
            rc = e.code if e.code is not None else 0
        # argparse exits 2 on usage error; main returns 2 via parse_args fallthrough
        self.assertEqual(rc, 2)
        # The decisive assertion: this did NOT hit the "unknown subcommand" branch
        self.assertNotIn("unknown subcommand", buf.getvalue())

    def test_cli_unknown_subcommand(self) -> None:
        from recorder_plugin.cli import main
        rc = main(["cli", "definitely-not-a-subcommand"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
