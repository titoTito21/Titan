# -*- coding: utf-8 -*-
"""Switching the reader off switches ALL of it off.

Reported as "the keyboard hook and the terminal reader stay on after the
screen reader is turned off". The terminal's output poller is an app
module's thread that ran for the life of the process and read new output
aloud; the NVDA add-ons' plugins, the speech adapter that everything else
speaks through and the hook itself when the worker is late are taken down
too. No window, no sound, no speech, no real hook.

Run directly: ``python tests/test_titan_access_off_means_off.py``.
"""

import os
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_off_')


class _Stops(object):
    def __init__(self):
        self.stopped = 0
        self._installed = True

    def stop(self):
        self.stopped += 1
        self._installed = False


def _bare_engine():
    from titan_access.engine import TitanAccessEngine
    engine = TitanAccessEngine.__new__(TitanAccessEngine)
    engine.running = False
    engine.notifications = None
    engine.live_lists = None
    engine._live_stop = threading.Event()
    engine._stop_bg_worker = lambda: None
    for name in ('keyboard', 'provider', 'nvda_ctl', 'progress', 'mouse'):
        setattr(engine, name, _Stops())
    engine.speech = object()
    engine.app_modules = None
    return engine


class OffMeansOff(unittest.TestCase):

    def test_the_terminal_poller_ends(self):
        from titan_access.app_modules import terminal
        engine = _bare_engine()
        engine.running = True
        module = terminal.TerminalModule(engine)
        module._is_our_terminal_foreground = lambda: False
        module._ensure_poller()
        thread = module._poll_thread
        self.assertTrue(thread is None or thread.is_alive() or not terminal._UIA)
        module.stop()
        if thread is not None:
            thread.join(1.0)
            self.assertFalse(thread.is_alive())
        self.assertIsNone(module._poll_thread)

    def test_a_poller_is_not_started_for_a_reader_that_is_off(self):
        from titan_access.app_modules import terminal
        engine = _bare_engine()
        module = terminal.TerminalModule(engine)
        module._ensure_poller()
        self.assertIsNone(module._poll_thread)

    def test_teardown_stops_the_app_modules_and_releases_the_voice(self):
        from titan_access import speech_adapter
        engine = _bare_engine()

        class Manager(object):
            stopped = 0

            def stop_all(self):
                Manager.stopped += 1

        engine.app_modules = Manager()
        saved = speech_adapter.current()
        speech_adapter.use(engine.speech)
        try:
            engine._teardown_subsystems()
            self.assertEqual(Manager.stopped, 1)
            self.assertIsNone(speech_adapter.current())
            self.assertEqual(engine.keyboard.stopped, 1)
        finally:
            speech_adapter.use(saved)

    def test_the_manager_stops_every_module_once(self):
        from titan_access.app_modules import manager
        engine = _bare_engine()
        found = manager.AppModuleManager(engine)
        calls = []
        for module in set(found._modules.values()):
            module.stop = (lambda m=module: calls.append(m))
        found.stop_all()
        self.assertEqual(len(calls), len(set(map(id, found._modules.values()))))

    def test_a_late_worker_does_not_leave_the_hook_on(self):
        from titan_access import engine as engine_module
        engine = _bare_engine()
        engine.running = True
        engine.supervisor = None
        engine._thread_id = 0
        engine._thread = None
        engine.settings = type('S', (), {'startup_announcement': 'None'})()
        engine.play = lambda *a, **k: None
        engine.speak = lambda *a, **k: None
        old = engine_module._IS_WINDOWS
        engine_module._IS_WINDOWS = True
        try:
            engine.stop()
        finally:
            engine_module._IS_WINDOWS = old
        self.assertEqual(engine.keyboard.stopped, 1)
        self.assertFalse(engine.keyboard._installed)


class _FakeWorker(object):
    def __init__(self):
        import queue
        self._cmd_queue = queue.Queue()
        self.ended = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._subprocess_process = None

    def _run(self):
        while self._cmd_queue.get() is not None:
            pass
        self.ended.set()


class _FakeBridge(object):
    def __init__(self):
        self.shut = 0

    def shutdown(self):
        self.shut += 1


class _FakeRegistry(object):
    def __init__(self):
        self._engines = {'dectalk': _FakeBridge(), 'smp': _FakeBridge()}


def _adapter_with(engine, own=True):
    from titan_access import speech_adapter
    adapter = speech_adapter.SpeechAdapter.__new__(speech_adapter.SpeechAdapter)
    adapter.paused = False
    adapter._q_lock = threading.Lock()
    adapter._seq_lock = threading.Lock()
    adapter._queue = []
    adapter._generation = 0
    adapter._seq_id = 0
    adapter._speaking_until = 0.0
    adapter._current = None
    adapter._wake = threading.Event()
    adapter._pump_thread = None
    adapter._external_synth = lambda: ''
    adapter._mode = adapter._MODE_TCE
    adapter._engine = engine
    adapter._own = own
    return adapter


class _FakeEngine(object):
    def __init__(self):
        self._sapi_worker = _FakeWorker()
        self.stopped = 0

    def stop(self):
        self.stopped += 1


class TheVoiceGoesWithTheReader(unittest.TestCase):
    """Measured with tests/check_titan_access_off.py before this: the
    speech pump, the private engine's SAPI worker and four Titan TTS bridge
    processes (DECtalk, Eloquence, SMP, Festival, each with a conhost) were
    all still running after the reader said it was off."""

    def test_the_pump_ends(self):
        adapter = _adapter_with(None, own=False)
        adapter._ensure_pump()
        pump = adapter._pump_thread
        self.assertTrue(pump.is_alive())
        adapter.shutdown()
        pump.join(2.0)
        self.assertFalse(pump.is_alive())

    def _with_registry(self, shared):
        from src.titan_core import stereo_speech, tce_speech
        engine = _FakeEngine()
        registry = _FakeRegistry()
        saved = (stereo_speech._engine_registry,
                 stereo_speech._stereo_speech_instance,
                 tce_speech._speaker, tce_speech._reader_speaker,
                 tce_speech._private_reader_speaker)
        stereo_speech._engine_registry = registry
        stereo_speech._stereo_speech_instance = shared
        tce_speech._speaker = None
        tce_speech._reader_speaker = None
        tce_speech._private_reader_speaker = engine
        try:
            adapter = _adapter_with(engine)
            adapter.shutdown()
            return engine, registry, stereo_speech._engine_registry, \
                tce_speech._private_reader_speaker
        finally:
            (stereo_speech._engine_registry,
             stereo_speech._stereo_speech_instance,
             tce_speech._speaker, tce_speech._reader_speaker,
             tce_speech._private_reader_speaker) = saved

    def test_the_private_engine_and_its_bridges_go(self):
        engine, registry, left, private = self._with_registry(shared=None)
        self.assertTrue(engine._sapi_worker is None)
        self.assertEqual([b.shut for b in registry._engines.values()], [1, 1])
        self.assertIsNone(left)
        self.assertIsNone(private)

    def test_titans_own_speech_keeps_the_bridges(self):
        engine, registry, left, private = self._with_registry(shared=object())
        self.assertEqual([b.shut for b in registry._engines.values()], [0, 0])
        self.assertIs(left, registry)
        self.assertIsNone(private)

    def test_the_sapi_worker_thread_ends(self):
        from titan_access import speech_adapter
        engine = _FakeEngine()
        worker = engine._sapi_worker
        speech_adapter._shut_sapi_worker(engine)
        self.assertTrue(worker.ended.wait(2.0))

    @unittest.skipUnless(sys.platform == 'win32', 'the shell hook is Windows')
    def test_the_attention_watcher_ends(self):
        from titan_access.portable import states
        states._stop.clear()
        thread = threading.Thread(target=states._shell_loop, daemon=True)
        thread.start()
        for _ in range(40):
            if states._held.get('hwnd'):
                break
            time.sleep(0.05)
        states.stop()
        thread.join(2.0)
        self.assertFalse(thread.is_alive())

    def test_an_addons_forgotten_timer_is_cancelled(self):
        from titan_access import nvda_host
        folder = nvda_host.folder()
        path = os.path.join(folder, 'someaddon', 'updater.py')
        namespace = {}
        exec(compile('def check():\n    pass\n', path, 'exec'), namespace)
        theirs = threading.Timer(86400, namespace['check'])
        ours = threading.Timer(86400, lambda: None)
        theirs.start()
        ours.start()
        try:
            self.assertEqual(nvda_host._cancel_addon_timers(), 1)
            theirs.join(2.0)
            self.assertFalse(theirs.is_alive())
            self.assertTrue(ours.is_alive())
        finally:
            theirs.cancel()
            ours.cancel()


class _Settings(object):
    def __init__(self, mute):
        self.mute_outside_tce = mute
        self.startup_announcement = 'None'

    def get_bool(self, section, key, default=False):
        return default


def _gated_engine(mute, tce):
    from titan_access.engine import TitanAccessEngine
    engine = TitanAccessEngine.__new__(TitanAccessEngine)
    engine.settings = _Settings(mute)
    engine._is_tce_foreground = lambda: tce
    said = []

    class Speech(object):
        def speak_async(self, text, **_k):
            said.append(text)

        def speak_segments(self, parts, gap_ms=0):
            said.append(' / '.join(p[0] for p in parts))
    engine.speech = Speech()
    engine.current_object = None
    engine.sound = None
    return engine, said


class OutsideTceTheSystemReaderReads(unittest.TestCase):
    """ "Mute outside TCE": outside TCE the reader says nothing and takes no
    key, and does not hold NVDA's controller endpoint; inside TCE it reads
    as always. Titan speaking through it (the host bridge) and the reader's
    own on / off are said wherever the user is."""

    def test_nothing_is_said_outside_tce(self):
        engine, said = _gated_engine(mute=True, tce=False)
        engine.speak('a')
        engine.speak_segments([('b', 0)])
        self.assertEqual(said, [])

    def test_inside_tce_everything_is_said(self):
        engine, said = _gated_engine(mute=True, tce=True)
        engine.speak('a')
        engine.speak_segments([('b', 0)])
        self.assertEqual(said, ['a', 'b'])

    def test_without_the_setting_nothing_changes(self):
        engine, said = _gated_engine(mute=False, tce=False)
        engine.speak('a')
        self.assertEqual(said, ['a'])

    def test_titan_speaking_through_the_reader_is_said(self):
        engine, said = _gated_engine(mute=True, tce=False)
        with engine.for_titan():
            engine.speak('Titan')
        engine.speak('reader')
        self.assertEqual(said, ['Titan'])

    def test_the_host_bridge_speaks_as_titan(self):
        from titan_access import host_bridge
        from titan_access.engine import TitanAccessEngine
        engine, said = _gated_engine(mute=True, tce=False)
        engine.running = True
        saved = TitanAccessEngine.instance
        TitanAccessEngine.instance = engine
        try:
            self.assertTrue(host_bridge.speak('Invisible UI'))
        finally:
            TitanAccessEngine.instance = saved
        self.assertEqual(said, ['Invisible UI'])

    def _hook(self, mute, tce):
        from titan_access.keyboard_hook import KeyboardHook
        engine, _said = _gated_engine(mute, tce)
        gestures = []
        engine.on_modifier_gesture = lambda *a, **k: gestures.append(a) or True
        engine.on_stop_speech_key = lambda: None
        engine.on_plain_key = lambda *a, **k: False
        engine.on_walked_numpad = lambda *a, **k: False
        hook = KeyboardHook.__new__(KeyboardHook)
        KeyboardHook.__init__(hook, engine)
        hook._modifier_config = lambda: (True, False)
        return hook, gestures

    def test_insert_reaches_the_system_reader_outside_tce(self):
        hook, gestures = self._hook(mute=True, tce=False)
        self.assertFalse(hook._process(0x2D, 0x52, 0, True))     # Insert
        self.assertFalse(hook._process(0x54, 0x14, 0, True))     # T
        self.assertEqual(gestures, [])

    def test_insert_is_the_readers_inside_tce(self):
        hook, gestures = self._hook(mute=True, tce=True)
        self.assertTrue(hook._process(0x2D, 0x52, 0, True))
        self.assertTrue(hook._process(0x54, 0x14, 0, True))
        self.assertEqual(len(gestures), 1)

    def test_insert_pressed_inside_and_let_go_outside_is_taken(self):
        hook, _gestures = self._hook(mute=True, tce=True)
        self.assertTrue(hook._process(0x2D, 0x52, 0, True))
        hook.engine._is_tce_foreground = lambda: False
        self.assertTrue(hook._process(0x2D, 0x52, 0, False))
        self.assertFalse(hook._reader_mod)

    def test_the_controller_endpoint_is_left_to_the_system_reader(self):
        from titan_access.nvda_controller_server import NvdaControllerServer
        self.assertFalse(NvdaControllerServer.wanted(_Settings(True)))
        self.assertTrue(NvdaControllerServer.wanted(_Settings(False)))

    def test_another_reader_is_told_which_processes_are_tce(self):
        import json
        import titan_access_actions as actions
        from titan_access.engine import TitanAccessEngine
        from titan_access.settings_store import get_settings
        settings = get_settings()
        settings.mute_outside_tce = True
        saved = TitanAccessEngine.instance
        engine, _said = _gated_engine(mute=True, tce=True)
        engine.running = True
        TitanAccessEngine.instance = engine
        try:
            found = json.loads(actions.action_reader_policy())
        finally:
            TitanAccessEngine.instance = saved
            settings.mute_outside_tce = False
        self.assertTrue(found['reads_tce_alone'])
        self.assertIn(os.getpid(), found['tce_pids'])
        TitanAccessEngine.instance = None
        try:
            found = json.loads(actions.action_reader_policy())
        finally:
            TitanAccessEngine.instance = saved
        self.assertFalse(found['reads_tce_alone'])
        self.assertEqual(found['tce_pids'], [])


if __name__ == '__main__':
    unittest.main()
