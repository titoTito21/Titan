# -*- coding: utf-8 -*-
"""Titan and Titan Access do not hang when the reader, the touch gestures
or another screen reader come and go.

    python tests/test_titan_access_no_hang.py

Reported as "Titan freezes when I turn the screen reader on or off, or
the touch gestures, or use it with another screen reader". Each of these
was measured before it was fixed:

* the settings window's "Enable screen reader" (and every action marshalled
  onto Titan's GUI thread) froze Titan for 5.0 s on start and 2.9 s on
  stop - the GUI thread waited for the reader's worker, whose UI
  Automation calls into Titan's own windows needed that very thread;
* a touch gesture was handled on the touch pump thread, beside the
  reader's own;
* starting or restarting real NVDA found the hidden "NVDA" window Titan
  Access keeps for Tolk, took Titan for a running NVDA, and ended it;
* a Win32 edit in a program that had hung held the reader's worker on an
  unbounded SendMessage until the supervisor restarted the reader.

Nothing here speaks, installs a hook or shows a window.
"""

import ctypes
import os
import sys
import tempfile
import threading
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_no_hang_')
for path in (os.path.join(COMPONENT, 'lib'), COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

WINDOWS = sys.platform.startswith('win')


def _bare_engine():
    from titan_access import engine as eng
    e = eng.TitanAccessEngine.__new__(eng.TitanAccessEngine)
    e.running = False
    e._thread = None
    e._thread_id = 0
    e._ready = threading.Event()
    e._start_thread = None
    e._touch_lock = threading.Lock()
    e._touch_hover = None
    return e


@unittest.skipUnless(WINDOWS, 'the GUI-thread rule is about Windows')
class TheGuiThreadNeverWaitsForTheReader(unittest.TestCase):
    """Start and stop called on Titan's GUI thread return at once."""

    def setUp(self):
        from titan_access import engine as eng
        self.eng = eng
        self.keep = (eng.TitanAccessEngine._start_now,
                     eng.TitanAccessEngine._stop_steps,
                     eng.TitanAccessEngine.instance,
                     eng.TitanAccessEngine._stopping)
        self.ran = []

        def slow_start(engine):
            self.ran.append(('start', threading.current_thread().name))
            time.sleep(0.6)
            return True

        def slow_stop(engine, titan_closing=False):
            self.ran.append(('stop', threading.current_thread().name))
            time.sleep(0.6)
        eng.TitanAccessEngine._start_now = slow_start
        eng.TitanAccessEngine._stop_steps = slow_stop

    def tearDown(self):
        eng = self.eng
        (eng.TitanAccessEngine._start_now, eng.TitanAccessEngine._stop_steps,
         eng.TitanAccessEngine.instance, eng.TitanAccessEngine._stopping) = \
            self.keep

    def _on_gui(self, fn):
        import wx
        app = wx.GetApp() or wx.App(False)
        # A main loop with no top-level window ends before it starts.
        frame = wx.Frame(None)
        box = {}

        def go():
            t0 = time.time()
            try:
                box['result'] = fn()
            except Exception as error:               # noqa: BLE001
                box['error'] = error
            finally:
                box['took'] = time.time() - t0
                frame.Destroy()
        wx.CallAfter(go)
        app.MainLoop()
        if 'error' in box:
            raise box['error']
        return box

    def test_start_and_stop_return_at_once_on_the_gui_thread(self):
        e = _bare_engine()

        def both():
            self.assertTrue(e._on_titan_gui_thread())
            e.start()
            started = self.eng.is_running() or e.running
            e.stop()
            return started
        box = self._on_gui(both)
        self.assertTrue(box['result'])
        self.assertLess(box['took'], 0.3)
        self.assertFalse(e.running)
        self.assertTrue(e._stopped.wait(5))
        names = [name for _what, name in self.ran]
        self.assertIn('TitanAccessStart', names)
        self.assertIn('TitanAccessStop', names)

    def test_off_the_gui_thread_it_is_synchronous(self):
        e = _bare_engine()
        self.assertFalse(e._on_titan_gui_thread())
        e.start()
        e.stop()
        self.assertEqual([what for what, _n in self.ran], ['start', 'stop'])
        self.assertTrue(e._stopped.is_set())

    def test_titan_closing_is_never_left_to_a_thread(self):
        e = _bare_engine()

        def closing():
            e.running = True
            e.stop(titan_closing=True)
        self._on_gui(closing)
        self.assertEqual(self.ran, [('stop', 'MainThread')])


class ANewReaderWaitsForTheOldOneToStop(unittest.TestCase):

    def setUp(self):
        from titan_access import engine as eng
        self.eng = eng
        self.keep = (eng.TitanAccessEngine.instance,
                     eng.TitanAccessEngine._stopping)

    def tearDown(self):
        (self.eng.TitanAccessEngine.instance,
         self.eng.TitanAccessEngine._stopping) = self.keep

    def test_a_stopping_reader_is_not_handed_out_again(self):
        eng = self.eng
        old = _bare_engine()
        eng.TitanAccessEngine.instance = old
        eng.TitanAccessEngine._stopping = old
        keep_init = eng.TitanAccessEngine.__init__
        eng.TitanAccessEngine.__init__ = lambda self: None
        try:
            fresh = eng.get_engine()
        finally:
            eng.TitanAccessEngine.__init__ = keep_init
        self.assertIsNot(fresh, old)

    def test_start_now_waits_for_the_previous_teardown(self):
        eng = self.eng
        old = _bare_engine()
        old._stopped.clear()
        eng.TitanAccessEngine._stopping = old
        new = _bare_engine()
        new.running = False      # switched off before it came up
        threading.Timer(0.3, old._stopped.set).start()
        t0 = time.time()
        self.assertFalse(new._start_now())
        self.assertGreaterEqual(time.time() - t0, 0.25)
        self.assertTrue(new._stopped.is_set())


class ATouchGestureRunsOnTheReadersThread(unittest.TestCase):

    def test_gestures_are_posted_and_hovers_coalesced(self):
        e = _bare_engine()
        e.running = True
        e._thread_id = 1
        posted, handled = [], []
        e.post_to_worker = posted.append
        e._handle_touch = lambda a, x, y: handled.append((a, x, y))
        from titan_access import engine as eng
        keep = eng._IS_WINDOWS
        eng._IS_WINDOWS = True
        try:
            e._on_touch('hover', 1, 1)
            e._on_touch('hover', 2, 2)
            e._on_touch('hover', 3, 3)
            e._on_touch('double_tap', 4, 4)
        finally:
            eng._IS_WINDOWS = keep
        self.assertEqual(handled, [], 'nothing runs on the caller thread')
        self.assertEqual(len(posted), 2, 'three hovers are one job')
        for job in posted:
            job()
        self.assertEqual(handled, [('hover', 3, 3), ('double_tap', 4, 4)])

    def test_a_reader_that_is_off_drops_the_gesture(self):
        e = _bare_engine()
        posted = []
        e.post_to_worker = posted.append
        e._on_touch('tap', 1, 1)
        self.assertEqual(posted, [])

    def test_switching_the_reader_off_switches_the_pad_off(self):
        from titan_access.portable import touchRecognizer, trackpad
        e = _bare_engine()
        stopped = []
        keep = (trackpad.running, trackpad.stop, touchRecognizer.listener)
        trackpad.running = lambda: True
        trackpad.stop = lambda: stopped.append(True)
        touchRecognizer.listener = e._on_touch
        try:
            e._teardown_the_rest()
        finally:
            trackpad.running, trackpad.stop, touchRecognizer.listener = keep
        self.assertEqual(stopped, [True])


class _FakeDll:
    def __init__(self):
        self.window = []
        self.retries = 0
        self.owns = 0

    def TitanAccessHelper_setNvdaWindow(self, show):
        self.window.append(show)
        return show

    def TitanAccessHelper_retryEndpoint(self):
        self.retries += 1
        return self.owns


class RealNvdaStartingNeverMeetsOurNvdaWindow(unittest.TestCase):

    def setUp(self):
        from titan_access import nvda_controller_server as n
        self.n = n
        self.keep = (n.GUARD_POLL_S, n.WINDOW_BACK_AFTER_S,
                     n.ENDPOINT_AFTER_S, n.RETRY_EVERY_S)
        n.GUARD_POLL_S, n.WINDOW_BACK_AFTER_S = 0.02, 0.3
        n.ENDPOINT_AFTER_S, n.RETRY_EVERY_S = 0.6, 0.05

    def tearDown(self):
        (self.n.GUARD_POLL_S, self.n.WINDOW_BACK_AFTER_S,
         self.n.ENDPOINT_AFTER_S, self.n.RETRY_EVERY_S) = self.keep

    def _server(self, present):
        server = self.n.NvdaControllerServer(engine=None)
        server._dll = _FakeDll()
        server._started = True
        server._owns_endpoint = False
        server._nvda = types.SimpleNamespace(running=lambda: present[0])
        return server

    def test_the_window_goes_the_moment_nvda_appears(self):
        present = [False]
        server = self._server(present)
        server._start_watch()
        try:
            time.sleep(0.1)
            present[0] = True
            time.sleep(0.15)
            self.assertEqual(server._dll.window, [0])
            self.assertEqual(server._dll.retries, 0,
                             'never take the endpoint while NVDA is here')
            present[0] = False
            time.sleep(0.15)
            self.assertEqual(server._dll.window, [0],
                             'not back the moment NVDA exits - it may be '
                             'restarting')
            time.sleep(0.4)
            self.assertEqual(server._dll.window, [0, 1])
            self.assertEqual(server._dll.retries, 0)
            time.sleep(0.5)
            self.assertGreater(server._dll.retries, 0)
        finally:
            server._watch_stop.set()

    def test_an_old_helper_still_has_its_window_closed(self):
        server = self.n.NvdaControllerServer(engine=None)
        closed = types.SimpleNamespace()
        self.assertFalse(server._set_window(closed, True))
        self.assertFalse(server._set_window(closed, False))

    def test_the_helper_exports_the_switch(self):
        path = os.path.join(COMPONENT, 'helper', 'titan_access_helper.dll')
        if not (WINDOWS and os.path.isfile(path)):
            self.skipTest('no helper built here')
        dll = ctypes.WinDLL(path)
        self.assertTrue(hasattr(dll, 'TitanAccessHelper_setNvdaWindow'))

    def test_nvda_is_recognised_by_its_executables(self):
        self.assertIn('nvda.exe', self.n.NVDA_PROCESSES)
        self.assertIn('nvda_uiaccess.exe', self.n.NVDA_PROCESSES)
        self.assertNotIn('nvda_probe64.exe', self.n.NVDA_PROCESSES)


@unittest.skipUnless(WINDOWS, 'Win32 messages')
class AProgramThatStopsAnsweringCostsAMomentNotTheReader(unittest.TestCase):

    def _busy_window(self):
        """A real window whose thread stops pumping, as a hung program."""
        user32 = ctypes.windll.user32
        user32.CreateWindowExW.restype = ctypes.c_void_p
        made, release = threading.Event(), threading.Event()
        box = {}

        def run():
            box['hwnd'] = user32.CreateWindowExW(
                0, 'EDIT', 'busy', 0, 0, 0, 10, 10, None, None, None, None)
            made.set()
            release.wait(10)
            user32.DestroyWindow(ctypes.c_void_p(box['hwnd']))
        threading.Thread(target=run, daemon=True).start()
        made.wait(5)
        return box['hwnd'], release

    def test_the_caret_of_a_busy_edit(self):
        from titan_access import editable_text
        hwnd, release = self._busy_window()
        try:
            t0 = time.time()
            self.assertIsNone(editable_text._win32_caret_pos(hwnd))
            self.assertLess(time.time() - t0, 3.0)
        finally:
            release.set()

    def test_win_msg_answers_or_gives_up(self):
        from titan_access import win_msg
        hwnd, release = self._busy_window()
        try:
            t0 = time.time()
            self.assertIsNone(win_msg.send(hwnd, 0x000E, timeout_ms=200))
            self.assertLess(time.time() - t0, 1.5)
        finally:
            release.set()

    def test_no_unbounded_send_message_is_left(self):
        import re
        folder = os.path.join(COMPONENT, 'titan_access')
        found = []
        for name in os.listdir(folder):
            if not name.endswith('.py'):
                continue
            with open(os.path.join(folder, name), encoding='utf-8') as f:
                for number, line in enumerate(f, 1):
                    code = line.split('#', 1)[0]
                    if re.search(r'\.SendMessageW\(', code) and \
                            'argtypes' not in code and 'restype' not in code:
                        found.append('%s:%d' % (name, number))
        self.assertEqual(found, [])


@unittest.skipUnless(WINDOWS, 'Win32 window classes')
class AWindowClassNeverPointsAtAFreedProcedure(unittest.TestCase):
    """Touch gestures on, reader off, reader on, touch gestures on: Titan
    ended with an access violation in VCRUNTIME140 - the pad's window
    class kept the address of a ctypes callback freed when the first run
    ended, and the second window was made with it."""

    def _class_proc(self, name):
        class WNDCLASSW(ctypes.Structure):
            _fields_ = [('style', ctypes.c_uint), ('proc', ctypes.c_void_p),
                        ('a', ctypes.c_int), ('b', ctypes.c_int),
                        ('h', ctypes.c_void_p), ('i', ctypes.c_void_p),
                        ('c', ctypes.c_void_p), ('br', ctypes.c_void_p),
                        ('m', ctypes.c_wchar_p), ('n', ctypes.c_wchar_p)]
        found = WNDCLASSW()
        here = ctypes.windll.kernel32.GetModuleHandleW(None)
        if not ctypes.windll.user32.GetClassInfoW(ctypes.c_void_p(here), name,
                                                  ctypes.byref(found)):
            return None
        return found.proc

    def test_the_pad_window_is_made_with_a_live_procedure_every_time(self):
        from titan_access.portable import trackpad, touchRecognizer
        keep = touchRecognizer.listener
        touchRecognizer.listener = lambda *a: None
        try:
            for _ in range(3):
                ok, said = trackpad.start()
                if not ok:
                    self.skipTest(said)
                live = ctypes.cast(trackpad._PERMANENT['proc'],
                                   ctypes.c_void_p).value
                self.assertEqual(
                    self._class_proc('TitanEnhancementsTrackpad'), live)
                trackpad.stop()
                for _wait in range(40):
                    if not trackpad.running():
                        break
                    time.sleep(0.05)
                self.assertFalse(trackpad.running())
        finally:
            touchRecognizer.listener = keep

    def test_the_attention_watcher_starts_again(self):
        from titan_access.portable import states
        for _ in range(2):
            states.start()
            for _wait in range(40):
                if states._state.get('running'):
                    break
                time.sleep(0.05)
            self.assertTrue(states._state.get('running'),
                            states._state.get('why'))
            states.stop()
            for _wait in range(40):
                if not states._state.get('running'):
                    break
                time.sleep(0.05)


if __name__ == '__main__':
    unittest.main(verbosity=2)
