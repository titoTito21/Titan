# -*- coding: utf-8 -*-
"""What the reader says about itself is heard whole, and a window that
stops answering is named rather than stuttered over.

- "Wirtualne okno wyłączone", "Paleta zamknięta", "Zamknięto menu",
  "Zamykam komunikat" were cut after a syllable by the focus landing back
  on the program; they are PROTECTED utterances now.
- On and off are "Titan Access włączony" / "Titan Access wyłączony"
  ("Titan Access on" / "off"); a saved copy of the old welcome default
  no longer overrides it.
- Titan closing (not the reader alone) says "Trwa wyłączanie środowiska
  TCE", the reader's pause, "Titan Access wyłącza się", and is waited out.
- The window in front stopping answering is said once - "Brak odpowiedzi
  w <okno>" - and the reader does not read into it.

Run directly: python tests/test_titan_access_messages_and_hung.py. Nothing
is spoken, nothing is shown and no key is pressed; the one real window is
made off-screen in a process of its own.
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_msgs_')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(REPO, 'data', 'components', 'titan access')
for path in (REPO, COMPONENT, os.path.dirname(os.path.abspath(__file__))):
    if path not in sys.path:
        sys.path.insert(0, path)

from test_titan_access_speech_queue import make_adapter   # noqa: E402
from titan_access import localization                    # noqa: E402
from titan_access import speech_adapter as sa            # noqa: E402


class SlowEngine(object):
    """Takes a while to say anything, and remembers being stopped."""

    def __init__(self, duration=0.4):
        self.spoken, self.stops = [], []
        self.duration = duration
        self.is_speaking = False
        self._cut = threading.Event()

    def speak_async(self, text, position=0.0, pitch_offset=0):
        self._cut = threading.Event()
        cut = self._cut
        self.spoken.append(text)
        self.is_speaking = True

        def play():
            cut.wait(self.duration)
            self.is_speaking = False
        threading.Thread(target=play, daemon=True).start()

    speak = speak_async

    def stop(self):
        self.stops.append(list(self.spoken))
        self._cut.set()
        self.is_speaking = False


class PolishFirst(unittest.TestCase):
    def setUp(self):
        self.keep = localization.get_language()
        localization.set_language('pl')
        sa._protected_cache.clear()

    def tearDown(self):
        localization.set_language(self.keep)
        sa._protected_cache.clear()


class AReaderMessageIsHeardWhole(PolishFirst):

    def test_the_messages_the_user_named_are_protected(self):
        for text in ('Wirtualne okno wyłączone', 'Wirtualne okno włączone',
                     'Paleta zamknięta', 'Zamknięto menu', 'Zamykam komunikat',
                     'Titan Access włączony', 'Titan Access wyłączony',
                     'Tryb skanowania wyłączony'):
            self.assertTrue(sa.is_protected(text), text)
        self.assertTrue(sa.is_protected(
            localization.L('browse.scanOn', 40)))
        for text in ('Zapisz, przycisk', 'Wirtualne', '', 'Paleta'):
            self.assertFalse(sa.is_protected(text), text)

    def test_english_too(self):
        localization.set_language('en')
        sa._protected_cache.clear()
        for text in ('Virtual window off', 'Palette closed',
                     'Titan Access off'):
            self.assertTrue(sa.is_protected(text), text)

    def test_the_focus_after_it_waits_instead_of_cutting_it(self):
        engine = SlowEngine(0.4)
        speech = make_adapter(engine)
        speech.speak('Wirtualne okno wyłączone')
        time.sleep(0.1)                    # it is playing now
        speech.speak('Zapisz / przycisk')  # the focus, interrupting
        self.assertTrue(speech.wait_for_queue(timeout=5))
        self.assertEqual(engine.spoken,
                         ['Wirtualne okno wyłączone', 'Zapisz / przycisk'])
        self.assertFalse(any('Wirtualne okno wyłączone' in said and
                             'Zapisz / przycisk' not in said
                             for said in engine.stops),
                         'the protected message was stopped: %r'
                         % engine.stops)

    def test_an_ordinary_line_is_still_cut(self):
        engine = SlowEngine(0.4)
        speech = make_adapter(engine)
        speech.speak('Pierwszy element')
        time.sleep(0.1)
        speech.speak('Drugi element')
        self.assertTrue(speech.wait_for_queue(timeout=5))
        self.assertEqual(engine.spoken, ['Pierwszy element', 'Drugi element'])
        self.assertTrue(engine.stops)

    def test_stop_still_silences_it(self):
        engine = SlowEngine(1.0)
        speech = make_adapter(engine)
        speech.speak('Paleta zamknięta')
        speech.speak('Zapisz', interrupt=False)
        time.sleep(0.1)
        speech.stop()
        self.assertTrue(speech.wait_for_queue(timeout=3))
        self.assertNotIn('Zapisz', engine.spoken)


class OnAndOffSayTitanAccess(PolishFirst):

    def test_the_words(self):
        self.assertEqual(localization.L('app.welcome'), 'Titan Access włączony')
        self.assertEqual(localization.L('engine.closing'),
                         'Titan Access wyłączony')
        localization.set_language('en')
        self.assertEqual(localization.L('app.welcome'), 'Titan Access on')
        self.assertEqual(localization.L('engine.closing'), 'Titan Access off')

    def test_the_old_default_saved_in_a_store_is_not_a_choice(self):
        from titan_access.settings_store import get_settings
        st = get_settings()
        for old in ('Czytnik ekranu uruchomiony', 'Screen reader started'):
            st.set('General', 'WelcomeMessage', old)
            self.assertEqual(st.welcome_message, '')
        st.set('General', 'WelcomeMessage', 'Dzień dobry')
        self.assertEqual(st.welcome_message, 'Dzień dobry')
        st.set('General', 'WelcomeMessage', '')


class TitanClosingIsSaid(PolishFirst):

    def _engine(self):
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine.__new__(TitanAccessEngine)
        said = []

        class Speech(object):
            def speak_segments(self, parts, gap_ms=0, protected=False):
                said.append((tuple(p[0] for p in parts), gap_ms, protected))

            def wait_until_done(self, timeout=None):
                said.append(('waited', timeout))
        engine.speech = Speech()
        return engine, said

    def test_two_parts_with_the_readers_pause_and_waited_out(self):
        engine, said = self._engine()
        engine._say_goodbye_to_titan()
        (parts, gap, protected), waited = said
        self.assertEqual(parts, ('Trwa wyłączanie środowiska TCE',
                                 'Titan Access wyłącza się'))
        self.assertGreaterEqual(gap, 300)
        self.assertTrue(protected)
        self.assertEqual(waited[0], 'waited')
        self.assertGreaterEqual(waited[1], 5)

    def test_titans_own_exit_is_hooked_once(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'ta_component_init', os.path.join(COMPONENT, 'init.py'))
        component = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(component)
        calls = []

        class TitanApp(object):
            def shutdown_app(self):
                calls.append('titan exits')

            def Hide(self):
                calls.append('hidden')
        fake = types.ModuleType('src.ui.gui')
        fake.TitanApp = TitanApp
        keep = sys.modules.get('src.ui.gui')
        sys.modules['src.ui.gui'] = fake
        component.titan_closing = lambda: calls.append('reader says goodbye')
        try:
            component._hook_titan_exits()
            component._hook_titan_exits()          # twice: wrapped once
            TitanApp().shutdown_app()
            component._goodbye_thread.join(5)
        finally:
            if keep is not None:
                sys.modules['src.ui.gui'] = keep
            else:
                sys.modules.pop('src.ui.gui', None)
        self.assertEqual(calls, ['hidden', 'reader says goodbye',
                                 'titan exits'])
        # Not on the calling (GUI) thread: the reader's teardown needs it.
        self.assertNotEqual(component._goodbye_thread.ident,
                            threading.get_ident())


class AWindowThatStopsAnsweringIsNamed(PolishFirst):

    def _watch(self, answers):
        from titan_access import not_responding
        said = []
        engine = types.SimpleNamespace(hung_hwnd=0, speech=types.SimpleNamespace(
            speak=lambda text, interrupt=True, protected=False:
            said.append((text, protected))))
        probe = iter(answers)
        return not_responding.Watch(engine, probe=lambda: next(probe)), \
            engine, said

    def test_said_once_then_forgotten_when_it_answers(self):
        watch, engine, said = self._watch([
            (0, ''), (77, 'Notatnik'), (77, 'Notatnik'), (77, 'Notatnik'),
            (0, ''), (77, 'Notatnik')])
        hung = []
        for _ in range(6):
            watch.check_once()
            hung.append(engine.hung_hwnd)
        self.assertEqual(hung, [0, 77, 77, 77, 0, 77])
        self.assertEqual(said, [('Brak odpowiedzi w Notatnik', True)] * 2)

    def test_windows_own_suffix_is_not_said_twice(self):
        from titan_access import not_responding
        self.assertEqual(not_responding.sentence('Notatnik (Brak odpowiedzi)'),
                         'Brak odpowiedzi w Notatnik')
        self.assertEqual(not_responding.sentence(''),
                         'Brak odpowiedzi programu')

    def test_the_focus_path_leaves_the_hung_window_alone(self):
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine.__new__(TitanAccessEngine)
        engine.hung_hwnd = 4242
        touched = []
        engine._scripts_follow_focus = lambda obj: touched.append(obj)
        engine.on_focus(types.SimpleNamespace(hwnd=4242, role='edit'))
        self.assertEqual(touched, [])

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_a_real_hung_window_is_seen_without_waiting_on_it(self):
        import ctypes
        from titan_access import not_responding
        probe = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(
                os.path.abspath(__file__)), 'hung_window_probe.py'), '30'],
            stdout=subprocess.PIPE, text=True)
        try:
            hwnd = int(probe.stdout.readline())
            deadline = time.time() + 12
            while not ctypes.windll.user32.IsHungAppWindow(hwnd) and \
                    time.time() < deadline:
                time.sleep(0.5)
            self.assertTrue(ctypes.windll.user32.IsHungAppWindow(hwnd))
            started = time.perf_counter()
            title = not_responding.window_title(hwnd)
            took = time.perf_counter() - started
            self.assertEqual(title, 'Hung probe')
            self.assertLess(took, 0.05)
        finally:
            probe.kill()
            probe.wait(5)
            probe.stdout.close()



class AKeyInAFrozenWindowAsksItNothing(PolishFirst):

    def _engine(self, frozen=True):
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine.__new__(TitanAccessEngine)
        said = []
        engine.speech = types.SimpleNamespace(
            speak=lambda text, interrupt=True, protected=False:
            said.append((text, protected)))
        engine.hung_hwnd, engine.hung_title = 77, 'Notatnik'
        engine._frozen_in_front = lambda: frozen
        engine._bg_lock = threading.Lock()
        engine._bg_event = threading.Event()
        engine._bg_read = None
        import queue
        engine._action_queue = queue.Queue()
        return engine, said

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows reads')
    def test_no_read_is_sent_and_the_name_is_said_again_rarely(self):
        engine, said = self._engine()
        reads = []
        for _ in range(5):
            engine.submit_read(lambda: reads.append(1))
            engine.submit_action(lambda: reads.append(2))
        self.assertIsNone(engine._bg_read)
        self.assertTrue(engine._action_queue.empty())
        self.assertEqual(said, [('Brak odpowiedzi w Notatnik', True)])
        engine._frozen_said -= 4                     # three seconds pass
        engine.submit_read(lambda: None)
        self.assertEqual(len(said), 2)

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows reads')
    def test_an_answering_window_is_read_as_before(self):
        engine, said = self._engine(frozen=False)
        engine.submit_read(len)
        self.assertIs(engine._bg_read, len)
        self.assertEqual(said, [])

    def test_windows_ghost_of_a_frozen_window_is_not_read(self):
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine.__new__(TitanAccessEngine)
        engine.hung_hwnd = 0
        touched = []
        engine._scripts_follow_focus = lambda obj: touched.append(obj)
        engine.on_focus(types.SimpleNamespace(hwnd=5, role='window',
                                              class_name='Ghost'))
        self.assertEqual(touched, [])

    def test_a_frozen_or_ghost_window_is_never_offered_as_a_picture(self):
        with open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                  encoding='utf-8') as handle:
            text = handle.read()
        arrived = text.index('self._arrived_at = root')
        consider = text.index('surface.consider(adapted', arrived)
        guard = text[arrived:consider]
        self.assertIn('GHOST_CLASS', guard)
        self.assertIn('window_answers(root', guard)



class AControlIsReadOnceItsWindowAnswers(unittest.TestCase):

    def _engine(self, answers):
        from titan_access import engine as eng_mod, later
        engine = eng_mod.TitanAccessEngine.__new__(eng_mod.TitanAccessEngine)
        engine._announce_token = 1
        engine.hung_hwnd = 0
        engine._frozen_in_front = lambda: False
        engine._window_of = lambda obj: 4242
        replies = iter(answers)
        engine._answers = lambda hwnd: next(replies, False)
        read = []
        engine.announce_object = lambda obj: read.append(obj)
        engine.post_to_worker = lambda fn: fn()
        self.keep = later.call_later
        later.call_later = lambda delay, fn: fn()       # no waiting in a test
        engine.ANSWER_TRIES = 3
        return engine, read

    def tearDown(self):
        from titan_access import later
        if hasattr(self, 'keep'):
            later.call_later = self.keep

    def test_a_busy_window_is_read_when_it_answers(self):
        engine, read = self._engine([False, False, True])
        engine._announce_when_answering('Zapisz', 1)
        self.assertEqual(read, ['Zapisz'])

    def test_a_window_that_never_answers_is_never_read(self):
        engine, read = self._engine([False] * 10)
        engine._announce_when_answering('Zapisz', 1)
        self.assertEqual(read, [])

    def test_a_newer_focus_wins(self):
        engine, read = self._engine([False, True])
        engine._announce_when_answering('Stary', 1)
        self.assertEqual(read, ['Stary'])
        engine._announce_token = 2
        engine._announce_when_answering('Stary', 1)
        self.assertEqual(read, ['Stary'])

    @unittest.skipUnless(sys.platform.startswith('win'), 'Windows only')
    def test_titans_own_windows_are_never_asked(self):
        import ctypes
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine.__new__(TitanAccessEngine)
        from titan_access import native_hook
        keep = native_hook.window_answers
        native_hook.window_answers = lambda *a, **k: False
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow() or 0
            own = ctypes.windll.user32.CreateWindowExW(
                0, "STATIC", "own", 0, 0, 0, 1, 1, None, None, None, None)
            self.assertTrue(engine._answers(own))
            ctypes.windll.user32.DestroyWindow(own)
        finally:
            native_hook.window_answers = keep



class AStoppingReaderSaysOnlyItsGoodbye(unittest.TestCase):

    def test_nothing_but_titans_own_words_once_it_is_stopping(self):
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine.__new__(TitanAccessEngine)
        engine._for_titan = threading.local()
        engine._muted_for_foreground = lambda: False
        engine.running = True
        self.assertFalse(engine._silenced_here())
        engine.running = False
        self.assertTrue(engine._silenced_here())
        with engine.for_titan():
            self.assertFalse(engine._silenced_here())


if __name__ == '__main__':
    unittest.main()
