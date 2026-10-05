# -*- coding: utf-8 -*-
"""Probe: which native windows Titan Access treats as a program that draws
its own controls, and what it reads at a caret in a Tkinter entry - all
without pressing a key or taking the foreground. Windows only."""
import ctypes
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_titan_access_live as live      # copies the stores, sets paths

PY = sys.executable
engine = live.start_engine()
from titan_access.portable import guest, readerApi, surface, toolkit  # noqa

user32 = ctypes.windll.user32


def opened(command, title):
    process = subprocess.Popen(command)
    for _ in range(80):
        time.sleep(0.25)
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            time.sleep(1.5)
            return process, hwnd
    return process, 0


for name, command, title in (
        ('wx', [PY, r'C:\tmp\ta_tk\wx_target.py'], 'TA probe wx'),
        ('wpf', ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                 '-File', r'C:\tmp\ta_tk\wpf_target.ps1'], 'TA probe wpf'),
        ('qt', [PY, r'C:\tmp\ta_tk\qt_target.py'], 'TA probe qt'),
        ('tk', [PY, r'C:\tmp\ta_tk\tk_form.py'], 'TA probe tk form')):
    process, hwnd = opened(command, title)
    window = readerApi.window_object(hwnd)
    print('==', name, 'framework', toolkit.of(window)[0],
          'drawn', surface.looks_drawn(window),
          'by toolkit', surface.drawn_by_toolkit(window))
    if name == 'tk':
        info = json.load(open(r'C:\tmp\ta_tk\tk_form.json'))
        ok, _said = guest.enter(window, say=False, allowed=True)
        print('  entered:', ok, 'display hwnd', guest._state['hwnd'])
        # The caret where Windows would report it, in the reader's own
        # pixels: on the second letter of "Anna", as the window reads.
        from titan_access import windows_ocr
        whole = windows_ocr.read_window(guest._state['hwnd'])
        anna = [w for line in whole['lines'] for w in line
                if w['text'] == 'Anna'][0]
        caret = (anna['left'] + anna['width'] * 3 // 8, anna['top'], 0)
        for key in ('right', 'home'):
            t = time.time()
            print('  at the caret,', key, ':',
                  repr(guest.at_the_caret(guest._state['hwnd'], caret, key)),
                  '%.1fs' % (time.time() - t))
        from titan_access import windows_ocr
        from titan_access.portable import localOcr
        print('  caret:', caret, 'window', guest._rect_of(guest._state['hwnd']))
        print('  ocr:', windows_ocr.report())
        guest.leave()
    process.terminate()
    time.sleep(0.5)
engine.stop()
