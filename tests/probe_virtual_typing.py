# -*- coding: utf-8 -*-
"""Probe: typing into an edit field through Titan Access's virtual window,
end to end - the engine's own key path (`on_plain_key`), the field's
writer, and the REAL control read back afterwards.

Windows only. It presses keys into windows it opens itself (a passed-on
key in the 'keys' writer is a real key); do not type while it runs.
"""
import ctypes
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_titan_access_live as live      # copies the stores, sets paths

PY = sys.executable
TARGETS = {
    'wx': ([PY, r'C:\tmp\ta_tk\wx_target.py'], 'TA probe wx'),
    'wpf': (['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', r'C:\tmp\ta_tk\wpf_target.ps1'], 'TA probe wpf'),
    'winforms': (['powershell.exe', '-NoProfile', '-ExecutionPolicy',
                  'Bypass', '-File', r'C:\tmp\ta_tk\winforms_target.ps1'],
                 'TA probe winforms'),
    'tk': ([PY, r'C:\tmp\ta_tk\tk_target.py'], 'TA probe tk'),
}

engine = live.start_engine()
from titan_access import toolkits, nvda_shape              # noqa: E402
from titan_access.portable import virtualWindow           # noqa: E402

user32 = ctypes.windll.user32
wanted = sys.argv[1:] or list(TARGETS)


def key(name, vk, ctrl=False, alt=False, shift=False):
    engine.on_plain_key(vk, name, ctrl, alt, shift)
    time.sleep(0.25)


for name in wanted:
    command, title = TARGETS[name]
    process = subprocess.Popen(command)
    hwnd = 0
    for _ in range(60):
        time.sleep(0.25)
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            break
    time.sleep(1.2)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    print('==', name, 'foreground ok:', user32.GetForegroundWindow() == hwnd)
    try:
        ok, said = virtualWindow.start()
        rows = virtualWindow._state['nodes']
        print('  start:', ok, 'rows:', [(r['name'], r['role']) for r in rows][:6])
        at = next((i for i, r in enumerate(rows)
                   if str(r.get('role')).upper() == 'EDITABLETEXT'), None)
        if at is None:
            at = next((i for i, r in enumerate(rows)
                       if 'start' in str(r.get('name')).lower()), None)
        if at is None:
            print('  no field row')
            continue
        with virtualWindow._LOCK:
            virtualWindow._state['at'] = at
        ok, said = virtualWindow.activate()
        print('  enter:', ok, said, 'writer:', virtualWindow.writer())
        time.sleep(0.4)
        key('z', 0x5A)
        key('a', 0x41)
        mid = None
        if virtualWindow.writer() != 'keys':
            # AltGr+z: a Polish ż - only testable where nothing is passed
            # on, since the probe cannot HOLD a physical AltGr.
            key('z', 0x5A, ctrl=True, alt=True)
            obj = nvda_shape.original_of(rows[at]['obj'])
            mid = toolkits.read_text(obj)
            key('backspace', 0x08)
        print('  copy:', repr(virtualWindow.field().text if virtualWindow.field() else None))
        key('escape', 0x1B)
        time.sleep(0.6)
        if name == 'tk':
            with open(r'C:\tmp\ta_tk\tk_value.txt', encoding='utf-8') as f:
                real = f.read()
        else:
            real = toolkits.read_text(nvda_shape.original_of(rows[at]['obj']))
        print('  after AltGr+z:', repr(mid))
        print('  REAL control:', repr(real))
    finally:
        try:
            virtualWindow.stop()
        except Exception:
            pass
        process.terminate()
        time.sleep(0.5)
engine.stop()
