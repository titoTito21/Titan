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



class VoiceEngine(ConcatEngine):
    """An engine with engines and voices, the way Titan's speech has them:
    a Titan TTS engine answers its voices as dicts with `id` and
    `display_name`, SAPI as plain names."""

    def __init__(self):
        ConcatEngine.__init__(self, duration=0.01)
        self.engine = 'sapi5'
        self.voice_at = None
        self.calls = []
        self.rate = self.pitch = 0
        self.volume = 100

    def set_engine(self, name):
        self.engine = name
        self.calls.append(('engine', name))

    def get_available_voices(self):
        if self.engine == 'smp':
            return [{'id': 'pl', 'display_name': 'Polish'}]
        if self.engine == 'supertonic':
            return [{'id': 'v1', 'display_name': 'Adam'},
                    {'id': 'v2', 'display_name': 'Ewa'}]
        return ['Microsoft Paulina Desktop - Polish', 'Microsoft Adam']

    def set_voice(self, index):
        self.voice_at = index
        self.calls.append(('voice', index))

    def set_rate(self, value):
        self.rate = value
        self.calls.append(('rate', value))

    def set_pitch(self, value):
        self.pitch = value

    def set_volume(self, value):
        self.volume = value
        self.calls.append(('volume', value))


class _Settings(object):
    """The reader's own voice, as `screenReader.ini` keeps it."""

    def __init__(self, synth='sapi5', voice='Microsoft Adam'):
        self.values = {('Speech', 'Synthesizer'): synth, ('Speech', 'Voice'): voice,
                       ('Speech', 'Rate'): 3, ('Speech', 'Pitch'): 0,
                       ('Speech', 'Volume'): 100}
        self.rate, self.volume, self.pitch = 3, 100, 0

    def get(self, section, key, default=''):
        return self.values.get((section, key), default)

    def get_int(self, section, key, default=0):
        try:
            return int(self.values.get((section, key), default))
        except (TypeError, ValueError):
            return default


def _voice_adapter(engine, settings):
    adapter = make_adapter(engine)
    adapter._settings = settings
    return adapter


class ATitanTtsVoiceIsTheOneChosen(unittest.TestCase):
    """The settings panel stores a voice's ID, and a Titan TTS engine's
    voices are dicts with `id` and `display_name` - neither of which is
    `name`, so the saved voice matched nothing and every Titan TTS engine
    spoke in its FIRST voice whatever had been chosen."""

    def test_a_voice_is_found_by_id_display_name_name_or_index(self):
        from titan_access import speech_adapter as sa
        engine = VoiceEngine()
        engine.engine = 'supertonic'
        self.assertEqual(sa._voice_index(engine, 'v2'), 1)
        self.assertEqual(sa._voice_index(engine, 'Ewa'), 1)
        self.assertEqual(sa._voice_index(engine, '1'), 1)
        self.assertIsNone(sa._voice_index(engine, 'nobody'))
        self.assertIsNone(sa._voice_index(engine, '7'))
        engine.engine = 'sapi5'
        self.assertEqual(sa._voice_index(engine, 'Microsoft Adam'), 1)

    def test_the_readers_own_voice_is_put_on_by_id(self):
        engine = VoiceEngine()
        adapter = _voice_adapter(engine, _Settings(synth='supertonic', voice='v2'))
        adapter._apply_own_voice()
        self.assertEqual(engine.engine, 'supertonic')
        self.assertEqual(engine.voice_at, 1)

    def test_a_voice_the_engine_has_not_got_changes_nothing(self):
        engine = VoiceEngine()
        adapter = _voice_adapter(engine, _Settings(synth='smp', voice='Ewa'))
        adapter._apply_own_voice()
        self.assertEqual(engine.engine, 'smp')
        self.assertIsNone(engine.voice_at)


class AWholeUtteranceIsSpokenInItsClassesOwnVoice(unittest.TestCase):
    """A voice class for a WHOLE utterance - a notification, an alert - may
    name a synthesizer and a voice of its own, and this reader stored the
    choice and never spoke it. The utterance goes to that synthesizer in
    that voice, and the reader's own voice is put back afterwards."""

    def setUp(self):
        self.engine = VoiceEngine()
        self.adapter = _voice_adapter(self.engine, _Settings())

    def _settle(self):
        for _ in range(200):
            if not self.adapter.pending_count() and not self.engine.is_speaking:
                break
            time.sleep(0.01)
        time.sleep(0.05)

    def test_the_synthesizer_and_voice_are_borrowed_and_given_back(self):
        self.adapter.speak('Nowa wiadomość', voice={'synth': 'smp', 'voice': 'pl'})
        self._settle()
        self.assertIn('Nowa wiadomość', self.engine.spoken)
        self.assertIn(('engine', 'smp'), self.engine.calls)
        borrowed = self.engine.calls.index(('engine', 'smp'))
        self.assertEqual(self.engine.calls[borrowed + 1], ('voice', 0))
        # Given back: the reader's own from the settings, after the words.
        self.assertIn(('engine', 'sapi5'), self.engine.calls[borrowed + 1:])
        self.assertEqual(self.engine.engine, 'sapi5')
        self.assertEqual(self.engine.voice_at, 1)

    def test_the_dials_ride_on_top_of_the_readers_own(self):
        self.adapter.speak('Uwaga', voice={'rate': 2, 'volume': -4})
        self._settle()
        self.assertIn(('rate', 5), self.engine.calls)
        self.assertIn(('volume', 80), self.engine.calls)
        self.assertEqual(self.engine.rate, 3)
        self.assertEqual(self.engine.volume, 100)

    def test_a_class_is_asked_by_name(self):
        from titan_access import speech_adapter as sa
        from titan_access.portable import classes
        had = classes.voice_of
        classes.voice_of = lambda tag: ({'synth': 'smp', 'voice': 'pl'}
                                        if tag == 'notification' else {})
        sa._current, was = self.adapter, sa._current
        try:
            self.assertTrue(sa.speak_in_class('Zapisano', 'notification'))
            self._settle()
        finally:
            classes.voice_of = had
            sa._current = was
        self.assertIn(('engine', 'smp'), self.engine.calls)
        self.assertIn('Zapisano', self.engine.spoken)

    def test_a_part_class_may_not_name_a_synthesizer(self):
        """`button` is part of a control's reading, and under a reader that
        speaks one utterance on one synthesizer (NVDA, and this adapter
        until the engine says otherwise) its synth is ignored."""
        from titan_access import speech_adapter as sa
        from titan_access.portable import classes
        had = classes.voice_of
        classes.voice_of = lambda tag: {'synth': 'smp', 'voice': 'pl', 'pitch': -4}
        sa._current, was = self.adapter, sa._current
        try:
            sa.speak_in_class('przycisk', 'kind')
            self._settle()
        finally:
            classes.voice_of = had
            sa._current = was
        self.assertNotIn(('engine', 'smp'), self.engine.calls)

    def test_the_shared_report_asks_this_reader_first(self):
        from titan_access.portable import compat, dialogs
        asked = []
        had = compat.speech.speak_in_class
        compat.speech.speak_in_class = lambda text, tag, interrupt=False: (
            asked.append((text, tag)) or True)
        try:
            dialogs.report('Gotowe', 'notification')
        finally:
            compat.speech.speak_in_class = had
        self.assertEqual(asked, [('Gotowe', 'notification')])




class APartOfAnAnnouncementMayComeFromAnotherSynthesizer(unittest.TestCase):
    """Asked for as "can the control's name, its type, a message, come from
    another voice or another Titan TTS engine?". The whole-utterance
    classes always could; a PART could not, because one utterance was
    rendered in one `speak_concat`. Titan Access renders each part to
    memory itself, so once the engine says so (`PARTS_MAY_NAME_SYNTH`) the
    parts are grouped by voice profile and each group is spoken on its own
    synthesizer in turn - the name in the reader's voice, the type in
    another - and the reader's own voice is put back after."""

    def setUp(self):
        from titan_access.portable import classes
        self.classes = classes
        self.was = classes.PARTS_MAY_NAME_SYNTH
        classes.PARTS_MAY_NAME_SYNTH = True
        self.had = classes.voice_of
        classes.voice_of = lambda tag: ({'synth': 'smp', 'voice': 'pl', 'pitch': -4}
                                        if tag == 'kind' else {})
        self.engine = VoiceEngine()
        self.adapter = _voice_adapter(self.engine, _Settings())
        self.adapter._own = True

    def tearDown(self):
        self.classes.PARTS_MAY_NAME_SYNTH = self.was
        self.classes.voice_of = self.had

    def _settle(self):
        for _ in range(300):
            if not self.adapter.pending_count() and not self.engine.is_speaking:
                break
            time.sleep(0.01)
        time.sleep(0.05)

    def test_the_segment_carries_the_profile_only_where_allowed(self):
        from titan_access import accessible
        part = accessible._part('przycisk', 'kind', -4)
        self.assertEqual(accessible.voice_profile_of(part), {'synth': 'smp', 'voice': 'pl'})
        self.assertIsNone(accessible.voice_profile_of(accessible._part('Zapisz', 'name', 0)))
        self.classes.PARTS_MAY_NAME_SYNTH = False
        self.assertIsNone(accessible.voice_profile_of(accessible._part('przycisk', 'kind', -4)))

    def test_the_type_is_spoken_on_its_own_synthesizer_and_the_voice_put_back(self):
        from titan_access import accessible
        segments = [accessible._part('Zapisz', 'name', 0),
                    accessible._part('przycisk', 'kind', -4),
                    accessible._part('zaznaczony', 'state', 4)]
        self.adapter.speak_segments(segments)
        self._settle()
        # Three groups: name on the reader's own, type on smp, state on own.
        texts = [[seg[0] for seg in call] for call in self.engine.concat_calls]
        self.assertEqual(texts, [['Zapisz'], ['przycisk'], ['zaznaczony']])
        self.assertIn(('engine', 'smp'), self.engine.calls)
        borrowed = self.engine.calls.index(('engine', 'smp'))
        self.assertIn(('engine', 'sapi5'), self.engine.calls[borrowed + 1:])
        self.assertEqual(self.engine.engine, 'sapi5')
        # No segment handed to the engine still carries the profile dict.
        for call in self.engine.concat_calls:
            for seg in call:
                self.assertLessEqual(len(seg), 5)

    def test_without_a_profile_the_whole_announcement_is_one_clip(self):
        from titan_access import accessible
        self.classes.voice_of = lambda tag: {}
        segments = [accessible._part('Zapisz', 'name', 0),
                    accessible._part('przycisk', 'kind', -4)]
        self.adapter.speak_segments(segments)
        self._settle()
        self.assertEqual(len(self.engine.concat_calls), 1)
        self.assertNotIn(('engine', 'smp'), self.engine.calls)

    def test_the_part_class_may_name_a_synth_when_told_so(self):
        from titan_access import speech_adapter as sa
        sa._current, was = self.adapter, sa._current
        try:
            sa.speak_in_class('przycisk', 'kind')
            self._settle()
        finally:
            sa._current = was
        self.assertIn(('engine', 'smp'), self.engine.calls)

if __name__ == "__main__":
    unittest.main(verbosity=2)
