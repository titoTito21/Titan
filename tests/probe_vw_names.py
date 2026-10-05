# -*- coding: utf-8 -*-
"""Probe: what the virtual window calls each control, next to what Titan
Access says for the same real control. No keys are pressed."""
import sys, os, time
sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:]]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_titan_access_live as live      # copies the stores, sets paths
import ctypes
engine = live.start_engine()
exe = sys.argv[1] if len(sys.argv) > 1 else 'charmap.exe'
process = live.open_program(exe, 3.0)
try:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    from titan_access.portable import readerApi, virtualWindow
    from titan_access import nvda_shape
    window = readerApi.window_object(hwnd)
    note = {}
    nodes = virtualWindow.nodes_of(window, note)
    print('NODES', len(nodes), note)
    for at, node in enumerate(nodes[:60]):
        parts = virtualWindow.parts_of(node, at=at, count=len(nodes))
        vw = ' | '.join('%s' % t for t, _c in parts)
        del live.said[:]
        try:
            engine.announce_object(nvda_shape.original_of(node['obj']))
        except Exception as e:
            live.said.append(('', '', 'ERR %s' % e))
        time.sleep(0.05)
        real = ' || '.join(s[2] for s in live.said)
        print('VW  :', vw)
        print('REAL:', real)
finally:
    process.terminate()
    engine.stop()
