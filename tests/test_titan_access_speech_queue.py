# -*- coding: utf-8 -*-
"""Regression tests for Titan Access speech: nothing queued may go unspoken.

The symptom these lock down: with any engine other than SAPI5, an announcement
made of several parts (element name / role / state) was read only in part - the
name came out clipped or the role and state were never heard at all - and a
second announcement asked for with ``interrupt=False`` erased the first.

Two causes, both fixed here:

1. ``StereoSpeech.speak_concat`` (which joins the pitched parts into ONE clip)
   refused to run for anything but SAPI5, so every other engine fell back to a
   pipeline that spoke each part with ``interrupt=True`` and paced them on a
   playback signal only Titan's own pygame channel provides.
2. Titan's TTS engines have no queue at all - every ``speak``/``speak_async``
   stops what is playing - so "say this after that" was never possible.

So: ``speak_concat`` is engine-agnostic, and the reader owns an utterance queue
drained by one pump thread.
"""

import os
import sys
import threading
import time
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(REPO, "data", "components", "titan access")
sys.path.insert(0, REPO)
sys.path.insert(0, COMPONENT)


class FakeEngine(object):
    """A StereoSpeech stand-in that behaves like a NON-SAPI engine.

    It has no ``speak_concat`` at all (the plugin-engine case before this fix
    would land on the paced fallback here), records everything it is asked to
    say, and - crucially - interrupts on every call, exactly as the real engines
    do.
    """

    has_concat = False

    def __init__(self, duration=0.05):
        self.spoken = []
        self.lock = threading.Lock()
        self.is_speaking = False
        self._duration = duration
        self._stop = threading.Event()

    def speak_async(self, text, position=0.0, pitch_offset=0):
        self._stop.set()          # interrupt whatever is playing
        with self.lock:
            self.spoken.append(text)
        self._stop = threading.Event()
        stop = self._stop
        self.is_speaking = True

        def _play():
            stop.wait(self._duration)
            self.is_speaking = False

        threading.Thread(target=_play, daemon=True).start()

    speak = speak_async

    def stop(self):
        self._stop.set()
        self.is_speaking = False

    @property
    def texts(self):
        with self.lock:
            return list(self.spoken)


class ConcatEngine(FakeEngine):
    """Like :class:`FakeEngine`, but able to concatenate parts (any real engine
    that can synthesize to memory, which after the fix is all of them)."""

    has_concat = True

    def __init__(self, duration=0.05, works=True):
        FakeEngine.__init__(self, duration)
        self.works = works
        self.concat_calls = []

    def speak_concat(self, segments, gap_ms=30):
        self.concat_calls.append(list(segments))
        if not self.works:
            return False
        self.speak_async(" | ".join(s[0] for s in segments))
        return True


def make_adapter(engine):
    """Build a SpeechAdapter bound to *engine*, with no Titan TTS import."""
    from titan_access import speech_adapter as sa

    adapter = sa.SpeechAdapter.__new__(sa.SpeechAdapter)
    adapter._settings = types.SimpleNamespace(rate=0, volume=100, pitch=0)
    adapter._mode = sa.SpeechAdapter._MODE_TCE
    adapter._engine = engine
    adapter._seq_lock = threading.Lock()
    adapter._seq_id = 0
    adapter._q_lock = threading.Lock()
    adapter._queue = []
    adapter._current = None
    adapter._generation = 0
    adapter._pump_thread = None
    adapter._wake = threading.Event()
    adapter._speaking_until = 0.0
    adapter._tts_channel_getter = False      # no pygame channel in the test
    return adapter


class QueuedSpeechTests(unittest.TestCase):
    def test_queued_lines_are_all_spoken_in_order(self):
        """interrupt=False means "after this one", not "instead of it"."""
        engine = FakeEngine()
        sp = make_adapter(engine)
        sp.speak("first", interrupt=True)
        sp.speak("second", interrupt=False)
        sp.speak("third", interrupt=False)
        self.assertTrue(sp.wait_for_queue(timeout=10.0))
        self.assertEqual(engine.texts, ["first", "second", "third"])

    def test_interrupt_discards_what_is_queued(self):
        """A new element announcement must not read the previous one's backlog."""
        engine = FakeEngine(duration=0.3)
        sp = make_adapter(engine)
        sp.speak("old one", interrupt=True)
        sp.speak("old two", interrupt=False)
        sp.speak("old three", interrupt=False)
        time.sleep(0.05)
        sp.speak("new", interrupt=True)
        self.assertTrue(sp.wait_for_queue(timeout=10.0))
        spoken = engine.texts
        self.assertIn("new", spoken)
        self.assertEqual(spoken[-1], "new")
        self.assertNotIn("old three", spoken)

    def test_segments_without_concat_are_spoken_as_one_complete_line(self):
        """No engine may lose the parts after the first."""
        engine = FakeEngine()
        sp = make_adapter(engine)
        sp.speak_segments([("Save", 0, 0.0), ("button", 4, 0.0),
                           ("unavailable", -4, 0.0)])
        self.assertTrue(sp.wait_for_queue(timeout=10.0))
        self.assertEqual(len(engine.texts), 1)
        line = engine.texts[0]
        for part in ("Save", "button", "unavailable"):
            self.assertIn(part, line)

    def test_segments_use_concat_when_the_engine_can(self):
        engine = ConcatEngine()
        sp = make_adapter(engine)
        sp.speak_segments([("Save", 0, 0.0), ("button", 4, 0.0)])
        self.assertTrue(sp.wait_for_queue(timeout=10.0))
        self.assertEqual(len(engine.concat_calls), 1)
        self.assertEqual(engine.texts, ["Save | button"])

    def test_concat_refusal_still_says_everything(self):
        """speak_concat returning False must not silence the announcement."""
        engine = ConcatEngine(works=False)
        sp = make_adapter(engine)
        sp.speak_segments([("Save", 0, 0.0), ("button", 4, 0.0)])
        self.assertTrue(sp.wait_for_queue(timeout=10.0))
        self.assertEqual(len(engine.texts), 1)
        self.assertIn("Save", engine.texts[0])
        self.assertIn("button", engine.texts[0])

    def test_stop_clears_the_queue(self):
        engine = FakeEngine(duration=0.3)
        sp = make_adapter(engine)
        sp.speak("one", interrupt=True)
        sp.speak("two", interrupt=False)
        sp.speak("three", interrupt=False)
        time.sleep(0.05)
        sp.stop()
        time.sleep(0.2)
        self.assertNotIn("three", engine.texts)
        self.assertFalse(sp.is_speaking)

    def test_is_speaking_covers_the_backlog(self):
        engine = FakeEngine(duration=0.2)
        sp = make_adapter(engine)
        sp.speak("one", interrupt=True)
        sp.speak("two", interrupt=False)
        self.assertTrue(sp.is_speaking)
        self.assertTrue(sp.wait_for_queue(timeout=10.0))
        self.assertFalse(sp.is_speaking)


class ConcatEngineAgnosticTests(unittest.TestCase):
    """``StereoSpeech.speak_concat`` must not be SAPI-only any more."""

    def test_supports_segment_synthesis_covers_plugin_engines(self):
        import importlib

        ss = importlib.import_module("src.titan_core.stereo_speech")
        obj = ss.StereoSpeech.__new__(ss.StereoSpeech)
        obj.engine = "supertonic"
        obj.default_pitch = 0

        class _Plugin(object):
            engine_name = "supertonic"

            def is_available(self):
                return True

            def generate(self, text, pitch):
                return "audio:" + text

        registry = types.SimpleNamespace(
            get_titantts_engine=lambda name: _Plugin() if name == "supertonic" else None)
        original = ss._get_engine_registry
        ss._get_engine_registry = lambda: registry
        try:
            if not ss.PYDUB_AVAILABLE:
                self.skipTest("pydub not installed")
            self.assertTrue(obj.supports_segment_synthesis())
            self.assertEqual(obj._synthesize_segment("hello", 3), "audio:hello")
            obj.engine = "spd"
            self.assertFalse(obj.supports_segment_synthesis())
        finally:
            ss._get_engine_registry = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
