# -*- coding: utf-8 -*-
"""TA scripts and NVDA add-ons under the REAL Titan Access engine - on
Linux (WSLg) as on Windows. Presses no real key: the engine's own key and
focus entry points are called, as the keyboard hook and the accessibility
provider call them. **Run it under WSLg, not on the user's own Windows
desktop**: the real engine follows the real foreground there, and its
questions (read this window as a picture?) appear on the user's screen.

    python3 tests/check_titan_access_linux_scripts_addons.py
"""
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault('GDK_BACKEND', 'x11')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
import test_titan_access_nvda_host as fixture       # sets a temporary home

from titan_access import nvda_host, ta_scripts        # noqa: E402

said = []
problems = []


class RecordingSpeech(object):
    supports_pitch = True

    def __init__(self, settings=None):
        pass

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0,
              voice=None):
        said.append(str(text))

    speak_async = speak

    def speak_segments(self, segments, gap_ms=0):
        said.append(' | '.join(str(s[0]) for s in segments))

    def __getattr__(self, name):
        return lambda *a, **k: None


def problem(text):
    problems.append(text)
    print('PROBLEM:', text, flush=True)


def wait_for(text, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if any(text in one for one in said):
            return True
        time.sleep(0.05)
        try:
            import wx
            wx.Yield()
        except Exception:                            # noqa: BLE001
            pass
    return False


def main():
    ok, why = nvda_host.install(fixture.build_addon(fixture.HOME))
    print('add-on installed:', ok, why, flush=True)
    with open(os.path.join(ta_scripts.folder(), 'probe.tas'), 'w',
              encoding='utf-8') as handle:
        handle.write('when key "insert+shift+h"\nsay "script says {{name}}"\n'
                     'control name="Old" name "New name"\n')
    import titan_access.speech_adapter as speech
    import titan_access.keyboard_hook as hook
    speech.SpeechAdapter = RecordingSpeech
    hook.KeyboardHook.start = lambda self: self
    import wx
    app = wx.App(False)
    frame = wx.Frame(None, title='Titan Access scripts probe')
    frame.Show()
    from titan_access.engine import TitanAccessEngine
    engine = TitanAccessEngine()
    print('engine started:', engine.start(), sys.platform, flush=True)

    def run():
        # The engine starts its gestures, scripts and add-ons on its own
        # thread on Windows; asked too early they are not there yet.
        deadline = time.time() + 15
        while time.time() < deadline and not (
                nvda_host.is_loaded() and ta_scripts.scripts()):
            time.sleep(0.1)
            wx.Yield()
        try:
            print('host:', {k: v for k, v in nvda_host.report().items()
                            if k in ('loaded', 'plugins', 'errors')},
                  flush=True)
            print('scripts:', ta_scripts.report()['scripts'], flush=True)

            class Obj(object):
                name = 'Zapisz'
                role = 'button'
                value = description = class_name = automation_id = ''
                hwnd = 0
                states = set()
            engine.current_object = Obj()
            engine.on_modifier_gesture(0x48, 'h', False, False, True,
                                       with_modifier=True)
            if not wait_for('script says Zapisz'):
                problem('the TA script did not speak: %r' % said[-3:])
            engine.on_modifier_gesture(0x5A, 'z', False, False, True,
                                       with_modifier=True)
            if not wait_for('witaj z dodatku'):
                problem('the add-on script did not speak: %r' % said[-3:])
            eaten = Obj()
            eaten.name = 'eat'
            engine.on_focus(eaten)
            if not wait_for('eaten'):
                problem('the add-on focus handler did not run')
            old = Obj()
            old.name = 'Old'
            changed, _say = ta_scripts.adjust(old)
            if changed.name != 'New name':
                problem('the control rule did not rename')
        except Exception:                            # noqa: BLE001
            problem('probe raised:\n' + traceback.format_exc())
        finally:
            engine.stop()
            wx.CallLater(200, app.ExitMainLoop)
    wx.CallLater(1500, run)
    app.MainLoop()
    print('said:', said[-6:], flush=True)
    print('==== %s' % ('OK' if not problems else '%d PROBLEM(S)'
                       % len(problems)), flush=True)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
