# -*- coding: utf-8 -*-
"""Probe: Titan Access's per-toolkit field writers against REAL windows.

Opens a wx, a WPF, a Windows Forms and a Tkinter window, finds the edit
field in each through the reader's own virtual window, and asks the
`toolkits` package how it would write it, what it reads, and whether a
written text really lands. Presses no keys. Windows only.
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
TARGETS = [
    ('wx', [PY, r'C:\tmp\ta_tk\wx_target.py'], 'TA probe wx'),
    ('wpf', ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
             '-File', r'C:\tmp\ta_tk\wpf_target.ps1'], 'TA probe wpf'),
    ('winforms', ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                  '-File', r'C:\tmp\ta_tk\winforms_target.ps1'],
     'TA probe winforms'),
    ('tk', [PY, r'C:\tmp\ta_tk\tk_target.py'], 'TA probe tk'),
    ('qt', [PY, r'C:\tmp\ta_tk\qt_target.py'], 'TA probe qt'),
]
WANTED = 'Zażółć gęślą jaźń'

engine = live.start_engine()
from titan_access import nvda_shape, toolkits                 # noqa: E402
from titan_access.portable import readerApi, virtualWindow    # noqa: E402

for name, command, title in TARGETS:
    if len(sys.argv) > 1 and name not in sys.argv[1:]:
        continue
    process = subprocess.Popen(command)
    hwnd = 0
    for _ in range(60):
        time.sleep(0.25)
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            break
    time.sleep(1.0)
    print('==', name, 'hwnd', hwnd)
    try:
        window = readerApi.window_object(hwnd)
        note = {}
        nodes = virtualWindow.nodes_of(window, note)
        print('  note:', {k: v for k, v in note.items() if k != 'ms'})
        edits = [n for n in nodes if str(n.get('role')).upper()
                 in ('EDITABLETEXT', 'DOCUMENT')]
        if not edits and note.get('pictured'):
            print('  read as a picture:', [n['name'] for n in nodes][:8])
            continue
        print('  rows:', [(n['name'], n['role']) for n in nodes][:8])
        print('  framework:', toolkits.framework_of(window))
        print('  client:', virtualWindow._client_rect(window))
        for n in nodes:
            try:
                l = n['obj'].location
                print('   ', n['name'], tuple(l))
            except Exception as e:
                print('   ', n['name'], 'no location', e)
        if not edits:
            print('  NO EDIT FIELD FOUND')
            continue
        node = edits[0]
        obj = nvda_shape.original_of(node['obj'])
        parts = virtualWindow.parts_of(node, at=0, count=len(nodes))
        print('  virtual window says:', ' | '.join(t for t, _c in parts))
        mode = readerApi.field_mode(node['obj'])
        print('  mode:', mode, ' module:', toolkits.for_obj(obj).NAME)
        print('  reads:', repr(readerApi.field_text(node['obj'])))
        if mode != 'keys':
            ok = readerApi.set_field_text(node['obj'], WANTED, mode)
            time.sleep(0.3)
            back = readerApi.field_text(node['obj'])
            print('  wrote:', ok, 'reads back:', repr(back),
                  'LANDED' if back == WANTED else 'DID NOT LAND')
    finally:
        process.terminate()
        time.sleep(0.5)
engine.stop()
