# -*- coding: utf-8 -*-
"""Probe: what Titan Access SAYS in a program's own window, toolkit by
toolkit - Tab through a test window and record every announcement.

Windows only. Presses Tab into the windows it opens itself.
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
    'tk': ([PY, r'C:\tmp\ta_tk\tk_form.py'], 'TA probe tk form'),
    'wpf': (['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', r'C:\tmp\ta_tk\wpf_form.ps1'], 'TA probe wpf form'),
    'qt': ([PY, r'C:\tmp\ta_tk\qt_form.py'], 'TA probe qt form'),
}
user32 = ctypes.windll.user32
engine = live.start_engine()
for name in sys.argv[1:] or list(TARGETS):
    command, title = TARGETS[name]
    process = subprocess.Popen(command)
    hwnd = 0
    for _ in range(80):
        time.sleep(0.25)
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            break
    time.sleep(1.5)
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.5)
    print('==', name, 'hwnd', hwnd, 'front', user32.GetForegroundWindow() == hwnd)
    del live.said[:]
    for step in range(5):
        live.mark('tab %d' % step)
        live.tap(live.VK_TAB)
        time.sleep(1.6)
    for when, how, text in live.said:
        print('  ', how, text)
    process.terminate()
    time.sleep(0.5)
engine.stop()
