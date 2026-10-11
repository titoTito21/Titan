# -*- coding: utf-8 -*-
"""Titan Access reading Titan Antivirus - on the REAL engine and the REAL
window.

Three things the antivirus' semantics promise, each asked of the reader
rather than of the code:

1. a row of the results is read as the file, then the threat (the reader
   module's kind column), then "Stan: ..." / "Lokalizacja: ...";
2. the scan's `wx.Gauge` is a progress bar the reader's monitor hears, the
   beeps rising as the scan goes;
3. a threat put in front of the user is read as a WARNING ("Uwaga!" first,
   in the lower tone) followed by the dialog's title and its message.

The frame is the application's own `MainFrame` in this process, which is
what makes it a Titan window to the engine, and this pid is written down as
`tantivirus` the way `app_manager.open_application` writes down the real
one. Windows only; a temporary APPDATA; no keyboard hook, no speech (it is
recorded), no sound, no network. Run directly.
"""

import ctypes
import os
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
APP = os.path.join(TITAN, 'data', 'applications', 'tAntivirus')
for path in (COMPONENT, TITAN, os.path.join(COMPONENT, 'lib'), APP):
    if path not in sys.path:
        sys.path.insert(0, path)

IS_WINDOWS = sys.platform.startswith('win')
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='tav_reader_test_')
SAID = []


class _Recorder:
    supports_pitch = True
    is_speaking = False

    def __init__(self, settings=None):
        pass

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0,
              voice=None):
        SAID.append(('text', str(text)))

    speak_async = speak

    def speak_segments(self, segments, gap_ms=0):
        SAID.append(('segments', [str(s[0]) for s in segments]))

    def __getattr__(self, name):
        # Every other call the engine makes on its speech: answered, ignored.
        return lambda *args, **kwargs: (
            [] if name.startswith('get_') else True)


def _segments_with(word):
    word = word.casefold()
    found = []
    for kind, parts in list(SAID):
        if kind == 'segments' and any(word in p.casefold() for p in parts):
            found.append(parts)
    return found


@unittest.skipUnless(IS_WINDOWS, 'the real engine, on Windows')
class TitanAccessReadsTitanAntivirus(unittest.TestCase):

    def test_rows_progress_and_the_threat_warning(self):
        import wx
        import titan_access.keyboard_hook as hook
        import titan_access.speech_adapter as speech
        import titan_access.sound_manager as sound
        old = (hook.KeyboardHook.start, speech.SpeechAdapter,
               sound.SoundManager._load)
        hook.KeyboardHook.start = lambda self: self
        speech.SpeechAdapter = _Recorder
        sound.SoundManager._load = lambda self, name: None

        app = wx.GetApp() or wx.App(False)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'tav_main_reader', os.path.join(APP, 'main.py'))
        main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main)
        main.speak = lambda text: None
        main.play = lambda name: None
        import av_store
        import av_engine
        import av_guard
        av_store.update(threat_action='report')

        class FakeApp(object):
            clamd = av_engine.Clamd()
            guard = av_guard.Guard(lambda p: None, lambda s: None)

            def apply_settings(self):
                pass

        from src.titan_core import app_manager
        app_manager.note_process(os.getpid(), {'shortname': 'tantivirus',
                                               'name': 'Titan Antivirus'})
        frame = main.MainFrame(FakeApp())
        threat_file = os.path.join(os.environ['APPDATA'], 'setup_crack.exe')
        with open(threat_file, 'wb') as handle:
            handle.write(b'x')
        finding = av_engine.Finding(threat_file, 'Win.Trojan.Test-1234')
        frame._on_found(finding)
        frame.Show()

        from titan_access.engine import TitanAccessEngine
        from titan_access import progress_monitor as pm
        from titan_access.localization import L
        engine = TitanAccessEngine()
        problems = []
        beeps = []
        answers = []

        def check(condition, message):
            if not condition:
                problems.append(message)

        def deliver(element):
            obj = engine.provider.element_to_object(element)
            if obj is None:
                return False
            done = threading.Event()

            def run():
                try:
                    engine.on_focus(obj)
                finally:
                    done.set()
            engine.post_to_worker(run)
            return done.wait(8.0)

        def driver():
            import uiautomation as auto
            try:
                engine.start()
                time.sleep(1.5)
                engine._compute_is_tce_foreground = lambda: True
                engine._tce_fg_cache = None

                # 1. A row of the results.
                wx.CallAfter(frame.results.SetFocus)
                time.sleep(0.5)
                listing = auto.ControlFromHandle(int(frame.results.GetHandle()))
                rows = [child for child in listing.GetChildren()
                        if child.ControlTypeName in ('ListItemControl',
                                                     'DataItemControl')]
                check(rows, 'the results list has no rows to UIA')
                if rows:
                    check(deliver(rows[0]), 'the row was not delivered')
                    time.sleep(1.0)
                    said = _segments_with('setup_crack.exe')
                    check(said, 'the row was not read: %r' % (SAID,))
                    parts = said[-1] if said else []
                    joined = ' | '.join(parts)
                    check('Win.Trojan.Test-1234' in parts,
                          'the threat is not the row\'s kind: %r' % (parts,))
                    stan = main._("Status")
                    check(any(p.startswith(stan + ': ') for p in parts),
                          'the status column is not read: %r' % (parts,))
                    check(parts.index('Win.Trojan.Test-1234') <
                          min([i for i, p in enumerate(parts)
                               if p.startswith(stan + ': ')] or [99])
                          if 'Win.Trojan.Test-1234' in parts else False,
                          'the threat is not said before the status: %s'
                          % joined)
                    module = engine._module_for(engine._adapted(
                        engine.provider.element_to_object(rows[0])))
                    check(module is not None and module.id == 'tantivirus',
                          'the reader module did not apply: %r' % (module,))
                    print('row read as:', joined, flush=True)

                # 2. The progress bar.
                real = engine.sound.play_tone

                def recording(frequency=880.0, duration_ms=25, pan=0.0,
                              gain=0.5):
                    beeps.append(round(float(frequency), 1))
                    return real(frequency, duration_ms, pan=pan, gain=gain)
                engine.sound.play_tone = recording
                gauge = auto.ControlFromHandle(int(frame.gauge.GetHandle()))
                obj = engine.provider.element_to_object(gauge)
                check(obj is not None and obj.role == 'progressbar',
                      'the scan progress is not a progress bar: %r'
                      % (getattr(obj, 'role', None),))
                check(obj is not None and obj.name == main._("Scan progress"),
                      'the progress bar is not named: %r'
                      % (getattr(obj, 'name', None),))
                if obj is not None:
                    engine.progress.on_focus(obj)
                    for value in range(0, 101, 10):
                        wx.CallAfter(frame._on_progress, value, 100, 'x')
                        time.sleep(pm._TICK_S * 2.5)
                    time.sleep(0.5)
                    check(len(beeps) >= 5, 'too few beeps: %r' % (beeps,))
                    check(all(b >= a for a, b in zip(beeps, beeps[1:])),
                          'the beeps did not rise: %r' % (beeps,))
                    print('progress beeps:', beeps, flush=True)

                # 3. A threat, put in front of the user.
                SAID.clear()
                wx.CallAfter(lambda: answers.append(
                    main.ask_about_threat(frame, finding)))
                title = main._("Titan Antivirus - threat found")
                hwnd = 0
                deadline = time.time() + 5
                while not hwnd and time.time() < deadline:
                    hwnd = ctypes.windll.user32.FindWindowW('#32770', title)
                    time.sleep(0.1)
                check(hwnd, 'the warning dialog did not appear')
                if hwnd:
                    from titan_access.portable import dialog_kind
                    kind, how = dialog_kind.kind_of_window(hwnd)
                    check(kind == 'warning',
                          'the dialog is not a warning to the reader: %r'
                          % ((kind, how),))
                    dialog = auto.ControlFromHandle(hwnd)
                    buttons = [c for c in dialog.GetChildren()
                               if c.ControlTypeName == 'ButtonControl']
                    check(buttons, 'the dialog has no buttons to UIA')
                    if buttons:
                        deliver(buttons[0])
                        time.sleep(1.2)
                        warning = L('dialog.warning')
                        said = _segments_with(warning)
                        check(said, 'the warning was not said: %r' % (SAID,))
                        if said:
                            parts = said[0]
                            check(parts[0].casefold() == warning.casefold(),
                                  'the warning word is not first: %r' % (parts,))
                            check(any(title in p for p in parts),
                                  'the title is not read: %r' % (parts,))
                            everything = ' '.join(
                                ' '.join(p) for k, p in SAID if k == 'segments')
                            check('Win.Trojan.Test-1234' in everything,
                                  'the threat is not read: %r' % (SAID,))
                            print('warning read as:', said[0], flush=True)
                    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                    time.sleep(0.8)
                    check(answers == ['ignored'],
                          'closing the warning did not ignore: %r' % (answers,))
            except Exception as error:               # noqa: BLE001
                import traceback
                problems.append('driver raised: %s\n%s'
                                % (error, traceback.format_exc()))
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
            (hook.KeyboardHook.start, speech.SpeechAdapter,
             sound.SoundManager._load) = old
        thread.join(timeout=10.0)
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
