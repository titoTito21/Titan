# -*- coding: utf-8 -*-
"""What the reader says inside Titan's own windows - the behaviours Titan
Access has for TCE and nothing else - run on the REAL engine.

A wx frame in this process IS Titan to the engine (same pid), so a list
named the way Titan names its lists and a list named "Status Bar" are
read exactly as Titan's are: the region's name in a lower tone and no
"list" word, a status-bar row as "status bar item", a row as "list item"
with its hint. Reported as "the compiled build does not say the list's
name or 'status bar item' any more", which was the worker's loop dying
on its first posted callable; these assertions are what would have named
that regression in a second.

Windows only; the keyboard hook is not installed (another reader keeps
its keys); nothing is spoken (speech is recorded) and no sound plays.
Run directly: ``python tests/test_titan_access_tce.py``.
"""

import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN, os.path.join(COMPONENT, 'lib')):
    if path not in sys.path:
        sys.path.insert(0, path)

IS_WINDOWS = sys.platform.startswith('win')

# **Never the user's own stores.** The real engine reads and WRITES
# `%APPDATA%/titosoft/Titan`; a test that ran on it once flipped a setting
# the user then reported as a regression, and one that READS it depends on
# whatever scheme they chose a minute ago. A fresh folder: the defaults.
import tempfile as _tempfile
os.environ['APPDATA'] = _tempfile.mkdtemp(prefix='titan_access_test_')
SAID = []


class _Recorder:
    supports_pitch = True

    def __init__(self, settings=None):
        pass

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0, voice=None):
        SAID.append(('text', str(text)))

    speak_async = speak

    def speak_segments(self, segments, gap_ms=0):
        SAID.append(('segments', [str(s[0]) for s in segments]))

    def stop(self):
        pass

    is_speaking = False

    def apply_settings(self):
        pass

    def set_rate(self, *a):
        pass

    def current_rate(self):
        return 0

    def set_volume(self, *a):
        pass

    def set_pitch(self, *a):
        pass

    def set_engine(self, *a):
        pass

    def set_voice(self, *a):
        pass

    def get_voices(self):
        return []

    def get_engines(self):
        return []

    def wait_until_done(self, *a, **k):
        return True

    def wait_for_queue(self, *a, **k):
        return True

    def pending_count(self):
        return 0


def _wait_for(predicate, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _segments_mentioning(word):
    word = word.casefold()
    return [parts for kind, parts in SAID
            if kind == 'segments' and any(word in str(p).casefold() for p in parts)]


@unittest.skipUnless(IS_WINDOWS, 'the real engine, on Windows')
class TitansOwnWindowsAreReadAsTitansOwn(unittest.TestCase):
    """One engine, one wx main loop. The checks run on a thread of their
    own while the MAIN thread runs `app.MainLoop()`: a UIA call into this
    process's own window is answered on the thread that owns the window,
    and a main thread parked in `wait` - or stepping a `Yield` - is the
    reader's worker stalled, which is what the first shape of this test
    measured (the supervisor restarted the engine under it)."""

    def test_titans_own_windows(self):
        import wx
        import titan_access.keyboard_hook as hook
        import titan_access.speech_adapter as speech
        import titan_access.sound_manager as sound
        old_hook, old_speech, old_load = (hook.KeyboardHook.start,
                                         speech.SpeechAdapter,
                                         sound.SoundManager._load)
        hook.KeyboardHook.start = lambda self: self
        speech.SpeechAdapter = _Recorder
        sound.SoundManager._load = lambda self, name: None
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None, title='Pakiet aplikacji Titan (test)')
        panel = wx.Panel(frame)
        listbox = wx.ListBox(panel, choices=['Aplikacje', 'Gry', 'Sieć'])
        status = wx.ListBox(panel, choices=['12:00', 'Bateria 80%'])
        self._name(listbox, 'Lista aplikacji')
        self._name(status, 'Status Bar')
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(listbox, 1, wx.EXPAND)
        sizer.Add(status, 0, wx.EXPAND)
        panel.SetSizer(sizer)
        frame.SetSize((420, 320))
        frame.Show()
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine()
        problems = []

        def check(condition, message):
            if not condition:
                problems.append(message)

        def driver():
            try:
                engine.start()
                time.sleep(1.5)
                engine._compute_is_tce_foreground = lambda: True
                engine._tce_fg_cache = None
                # 1. a row of the application list
                parts = self._deliver(engine, listbox, 0)
                check(parts is not None, 'no announcement for the list row: %r' % (SAID,))
                if parts:
                    low = [p.casefold() for p in parts]
                    check(any(p.startswith('lista') for p in low),
                          'the region is not named: %r' % (parts,))
                    check(any('element listy' in p or 'list item' in p for p in low),
                          'the row is not a list item: %r' % (parts,))
                    check(any('aplikacje' in p for p in low),
                          'the row is not read: %r' % (parts,))
                # 2. a row of the status bar
                parts = self._deliver(engine, status, 0)
                check(parts is not None, 'no announcement for the status row: %r' % (SAID,))
                if parts:
                    low = [p.casefold() for p in parts]
                    check(any('paska stanu' in p or 'status bar item' in p for p in low),
                          'the row is not a status bar item: %r' % (parts,))
                # 3. the regression itself: a hidden window, then a ping
                wx.CallAfter(frame.Hide)
                time.sleep(1.0)
                done = threading.Event()
                engine.post_to_worker(done.set)
                check(done.wait(4.0), 'the worker died on a posted callable')
                check(engine.running, 'the engine stopped running')
                sup = getattr(engine, 'supervisor', None)
                check(sup is None or sup.counts.get('restarts', 0) == 0,
                      'the supervisor had to restart the engine: %r' % (sup.report() if sup else None,))
            except Exception as error:               # noqa: BLE001
                import traceback
                problems.append('driver raised: %s\n%s' % (error, traceback.format_exc()))
            finally:
                try:
                    engine.stop()
                finally:
                    wx.CallAfter(frame.Destroy)
                    wx.CallAfter(app.ExitMainLoop)
        thread = threading.Thread(target=driver, daemon=True)
        thread.start()
        try:
            app.MainLoop()
        finally:
            hook.KeyboardHook.start = old_hook
            speech.SpeechAdapter = old_speech
            sound.SoundManager._load = old_load
        thread.join(timeout=10.0)
        self.assertEqual(problems, [])

    @staticmethod
    def _name(control, name):
        """The accessible name, the way Titan gives it to its native lists."""
        control.SetName(name)
        try:
            from src.shell import a11y
            a11y.name_control(control, name)
        except Exception:                            # noqa: BLE001
            pass

    def _deliver(self, engine, control, row):
        """Hand the engine the focus of a ROW of *control*, read off the real
        UIA tree, the way the provider would after a focus event - the event
        itself is not relied on (a test window on a live desktop is behind
        the user's work and raises none). Answers the segments said for the
        row, or None."""
        import wx
        # Nothing is cleared: a window in front raises its own focus event
        # the moment the control takes the focus, and THAT announcement is
        # the one with the window and the region in it - a container is
        # said when it is entered and not for every row after.
        wx.CallAfter(control.SetFocus)
        time.sleep(0.4)
        import uiautomation as auto
        root = auto.ControlFromHandle(int(control.GetHandle()))
        children = root.GetChildren()
        if not children:
            return None
        obj = engine.provider.element_to_object(children[row])
        if obj is None:
            return None
        done = threading.Event()

        def deliver():
            try:
                engine.on_focus(obj)
            finally:
                done.set()
        engine.post_to_worker(deliver)
        if not done.wait(8.0):
            return None
        time.sleep(1.0)
        wanted = str(control.GetString(row)).casefold()
        merged = []
        for kind, parts in list(SAID):
            if kind == 'segments' and any(wanted in str(p).casefold() for p in parts):
                merged.extend(parts)
        return merged or None


if __name__ == '__main__':
    unittest.main(verbosity=1)
