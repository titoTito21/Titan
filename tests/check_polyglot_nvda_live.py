# -*- coding: utf-8 -*-
"""What the RUNNING NVDA really says in Polyglot's windows and the new
General settings - not a model of a reader, the reader.

Needs NVDA running with the Titan enhancements add-on; Titan must NOT be
running (this starts the Action Bus itself, and two buses on one pipe
split it). The windows are put in FRONT and the focus moved control by
control, so NVDA speaks each one aloud exactly as it would for a user; after
each move the add-on's log of what NVDA said (`nvda.settings` ->
`spoken`) is read. The window that was in front is given back at the end.
It takes the foreground for about a minute.

    python tests/check_polyglot_nvda_live.py
"""
import ctypes
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='nvda_polyglot_')
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'polyglot'))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import wx                                                    # noqa: E402

user32 = ctypes.windll.user32
SETTLE = 1.6


def main():
    from src.titan_core.actions import bus
    from src.titan_core import titan_actions
    other = titan_actions.PipeChannel.connect(titan_actions.PIPE_NAME)
    if other is not None:
        other.close()
        print('Something already listens on the Action Bus (Titan?). Close it.')
        return 1
    bus._announce_client = lambda *_a, **_k: None
    bus.start()
    began = time.time()
    while time.time() - began < 30 and bus.get_peer('nvda') is None:
        time.sleep(0.5)
    if bus.get_peer('nvda') is None:
        print('No NVDA add-on joined in 30 s.')
        return 1
    print('NVDA joined the bus.')

    app = wx.App(False)
    from polyglotkit import settings_page
    from src.ui import settingsgui
    spec = importlib.util.spec_from_file_location(
        'polyglot', os.path.join(ROOT, 'data', 'components', 'polyglot', 'init.py'))
    polyglot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(polyglot)

    previous = user32.GetForegroundWindow()
    pages = []                     # (title, top-level window, controls)
    seen = set()
    results = []
    done = threading.Event()

    def spoken():
        ok, answer = bus.invoke('nvda', 'settings', {}, timeout=20.0)
        if not ok:
            return []
        if isinstance(answer, str):
            answer = json.loads(answer)
        rows = (answer.get('reading') or {}).get('spoken') or []
        out = []
        for row in rows:
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(row)
        return out

    def on_gui(function):
        box, flag = {}, threading.Event()

        def run():
            try:
                box['v'] = function()
            finally:
                flag.set()
        wx.CallAfter(run)
        flag.wait(10)
        return box.get('v')

    def front(window):
        from src.shell import win_shell
        window.Show()
        window.Raise()
        win_shell.take_foreground(window.GetHandle())

    def drive():
        try:
            spoken()                                  # forget what came before
            for title, window, controls in pages:
                on_gui(lambda: front(window))
                time.sleep(SETTLE)
                results.append(('== ' + title, [str(r) for r in spoken()]))
                for control in controls:
                    on_gui(control.SetFocus)
                    time.sleep(SETTLE)
                    label = on_gui(lambda: control.GetName())
                    results.append(('  [' + str(label) + ']',
                                    [str(r) for r in spoken()]))
                on_gui(window.Hide)
        except Exception:
            import traceback
            results.append(('ERROR', [traceback.format_exc()]))
        finally:
            done.set()
            wx.CallAfter(app.ExitMainLoop)

    def keep(window, controls, title):
        pages.append((title, window, [c for c in controls
                                      if not isinstance(c, wx.StaticText)
                                      and c.IsShownOnScreen() is not None]))

    def modal(self):
        keep(self, self.GetChildren(), 'Polyglot window')
        host = wx.Frame(None)
        language = settings_page.LanguageDialog(host, settings_page.Languages([]))
        keep(language.dialog, language.ident.GetParent().GetChildren(),
             'Add a language')
        frame = settingsgui.SettingsFrame(None)
        frame.ShowCategory(list(frame.categories)[0])
        keep(frame, [frame.usage_tips_cb, frame.packages_folder_ctrl,
                     frame.packages_folder_btn], 'Settings -> General (new)')
        threading.Thread(target=drive, daemon=True).start()
        wx.CallLater(240000, app.ExitMainLoop)
        app.MainLoop()
        return wx.ID_CANCEL

    wx.Dialog.ShowModal = modal
    try:
        polyglot.show_window(None)
    finally:
        try:
            if previous:
                from src.shell import win_shell
                win_shell.take_foreground(previous)
        except Exception:
            pass
        bus.stop()

    silent = 0
    for heading, rows in results:
        print(heading)
        for row in rows:
            print('      NVDA said:', row)
        if heading.startswith('  [') and not rows:
            silent += 1
    print('controls NVDA said nothing about:', silent)
    return 0


if __name__ == '__main__':
    code = main()
    sys.stdout.flush()
    os._exit(code)
