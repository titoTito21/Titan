# -*- coding: utf-8 -*-
"""The edit-field path through UI Automation, against a REAL WPF TextBox.

    python tests/check_titan_access_edit_live_uia.py

A WPF window is put up by PowerShell OFF the screen and never activated,
so the user's own window keeps the foreground and no key is pressed
anywhere. The reader's engine object, handler and KeyboardHook._process
see each key; what the program would do with it is played through the
TextBox's own TextPattern (TextRange.Select). Speech is recorded. Runs on
a copy of the user's stores. Fails on anything wrong.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
_base = os.getenv('APPDATA') or os.path.expanduser('~')
_target = tempfile.mkdtemp(prefix='titan_access_uia_probe_')
_src = os.path.join(_base, 'titosoft', 'Titan', 'screenreader')
if os.path.isdir(_src):
    shutil.copytree(_src, os.path.join(_target, 'titosoft', 'Titan', 'screenreader'))
os.environ['APPDATA'] = _target
for path in (os.path.join(COMPONENT, 'lib'), COMPONENT, TITAN):
    sys.path.insert(0, path)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TITLE = 'TitanAccessUiaProbe%d' % os.getpid()
PS = r'''
Add-Type -AssemblyName PresentationFramework
$w = New-Object System.Windows.Window
$w.Title = '%s'; $w.Left = -4000; $w.Top = -4000; $w.Width = 300; $w.Height = 300
$w.ShowActivated = $false; $w.ShowInTaskbar = $false
$t = New-Object System.Windows.Controls.TextBox
$t.AcceptsReturn = $true; $t.TextWrapping = 'Wrap'
$t.Text = "Ala ma kota.`r`nDrugi wiersz tutaj.`r`nTrzeci."
$w.Content = $t
$w.ShowDialog() | Out-Null
''' % TITLE
ps = subprocess.Popen(['powershell', '-NoProfile', '-STA', '-Command', PS])

# A UIA client in an STA that does not pump waits out every callback (3 s
# each, measured); the reader's own threads are MTA.
sys.coinit_flags = 0
import uiautomation as auto                      # noqa: E402
from titan_access import localization as loc     # noqa: E402
from titan_access.contracts import AccessibleObject  # noqa: E402
from titan_access.engine import TitanAccessEngine    # noqa: E402
from titan_access.editable_text import EditableTextHandler  # noqa: E402
from titan_access.keyboard_hook import KeyboardHook  # noqa: E402

said = []
problems = []
T0 = time.time()


class Recorder:
    def speak_async(self, text, position=0.0, interrupt=True, pitch_offset=0, **_k):
        said.append((time.time() - T0, text))

    speak = speak_async

    def stop(self):
        pass


def main():
    fg_before = auto.GetForegroundControl().NativeWindowHandle
    import ctypes
    hwnd = 0
    for _ in range(80):
        hwnd = ctypes.windll.user32.FindWindowW(None, TITLE)
        if hwnd:
            break
        time.sleep(0.25)
    if not hwnd:
        print('the WPF window did not appear', ps.poll()); return 1
    time.sleep(0.5)
    win = auto.ControlFromHandle(hwnd)
    box = win.EditControl(searchDepth=3)
    if not box.Exists(10, 0.2):
        print('no TextBox in the window'); return 1
    tp = box.GetTextPattern()
    print('foreground kept:', auto.GetForegroundControl().NativeWindowHandle == fg_before)
    doc = tp.DocumentRange
    caret0 = doc.Clone()
    caret0.MoveEndpointByRange(auto.TextPatternRangeEndpoint.End, caret0,
                               auto.TextPatternRangeEndpoint.Start)
    caret0.Select()

    Char, Line = auto.TextUnit.Character, auto.TextUnit.Line
    S, E = auto.TextPatternRangeEndpoint.Start, auto.TextPatternRangeEndpoint.End
    loc.set_language('pl')
    engine = TitanAccessEngine()
    engine.speech = Recorder()
    engine._muted_for_foreground = lambda: False
    engine.settings.phonetic_letters = False
    engine.editable = EditableTextHandler(engine)
    # The engine reads on a thread whose COM calls are marshalled by the
    # worker that pumps messages; this probe's thread does not pump, so
    # the read runs here, after the program has the key - the same order.
    queued = []
    engine.submit_read = queued.append
    engine.current_object = AccessibleObject(role='edit', name='Pole',
                                             class_name='TextBox', native=box)
    engine.editable.set_element(engine.current_object)
    if os.environ.get('UIA_DEBUG'):
        import titan_access.editable_text as et
        real = et.EditableTextHandler._unit_text

        def traced(rng, unit):
            d = et._FastPattern(tp).DocumentRange
            d.MoveEndpointByRange(E, rng, S)
            out = real(rng, unit)
            print('   unit_text at %d (unit %s) -> %r' % (len(d.GetText(-1)), unit, out))
            return out
        et.EditableTextHandler._unit_text = staticmethod(traced)
    hook = KeyboardHook(engine)
    hook.is_in_edit_field = True
    hook._process(0x7C, 0, 0, True); hook._process(0x7C, 0, 0x80, False)


    def collapsed(r, end=False):
        r = r.Clone()
        if end:
            r.MoveEndpointByRange(S, r, E, waitTime=0)
        else:
            r.MoveEndpointByRange(E, r, S, waitTime=0)
        return r

    def line_of(cur):
        probe = cur.Clone()
        if probe.MoveEndpointByUnit(E, Char, 1, waitTime=0) != 1:
            probe = cur.Clone()
        probe.ExpandToEnclosingUnit(Line, waitTime=0)
        return probe

    def program(key):
        """What the TextBox does with the key: the caret stays a
        degenerate range, as a real caret is."""
        cur = collapsed(tp.GetSelection()[0])
        if key == 'right':
            cur.MoveEndpointByUnit(E, Char, 1, waitTime=0)
            cur = collapsed(cur, end=True)
        elif key == 'left':
            cur.MoveEndpointByUnit(S, Char, -1, waitTime=0)
            cur = collapsed(cur)
        elif key in ('home', 'end', 'down'):
            line = line_of(cur)
            if key == 'home':
                cur = collapsed(line)
            elif key == 'end':
                text = line.GetText(-1) or ''
                cur = collapsed(line, end=True)
                if text.endswith(('\r', '\n')):
                    cur.MoveEndpointByUnit(S, Char, -1, waitTime=0)
                    cur = collapsed(cur)
            else:
                nxt = collapsed(line, end=True)
                if not (line.GetText(-1) or '').endswith(('\r', '\n')):
                    nxt.MoveEndpointByUnit(E, Char, 1, waitTime=0)
                    nxt = collapsed(nxt, end=True)
                cur = nxt
        cur.Select(waitTime=0)
        if os.environ.get('UIA_DEBUG'):
            sel = tp.GetSelection()[0]
            d1 = doc.Clone(); d1.MoveEndpointByRange(E, sel, S)
            d2 = doc.Clone(); d2.MoveEndpointByRange(E, sel, E)
            print('   program %s -> selection %d..%d' % (key, len(d1.GetText(-1)), len(d2.GetText(-1))))

    VK = {'right': 0x27, 'left': 0x25, 'down': 0x28, 'home': 0x24, 'end': 0x23}

    def press(key, want, at_once):
        mark = len(said)
        t = time.time()
        hook._process(VK[key], 0, 0x01, True)
        if os.environ.get('UIA_DEBUG'):
            print('   hook took %.2f s' % (time.time() - t))
        first = said[mark][0] - (t - T0) if len(said) > mark else None
        t_prog = time.time()
        program(key)
        if os.environ.get('UIA_DEBUG'):
            print('   program took %.2f s' % (time.time() - t_prog))
        hook._process(VK[key], 0, 0x81, False)
        if os.environ.get('UIA_DEBUG'):
            print('   predicted marker before read:', engine.editable._predicted, len(queued))
        t_read = time.time()
        while queued:
            queued.pop(0)()
        if os.environ.get('UIA_DEBUG'):
            print('   read took %.2f s' % (time.time() - t_read))
        time.sleep(0.1)
        words = [w for _t, w in said[mark:]]
        lat = '%.0f ms' % (first * 1000) if first is not None else '(after the program)'
        print('%-6s said %-28r first word %s' % (key, words, lat))
        if [w.strip() for w in words] != want:
            problems.append('%s: wanted %r, said %r' % (key, want, words))
        if at_once and (first is None or first > 0.03):
            problems.append('%s should be said before the program moves' % key)

    press('right', ['l'], True)
    press('right', ['a'], True)
    press('end', ['Ala ma kota.'], True)
    press('home', ['Ala ma kota.'], True)
    press('down', ['Drugi wiersz tutaj.'], False)       # read from the control
    press('home', ['Drugi wiersz tutaj.'], True)
    press('right', ['r'], True)
    press('left', ['d'], True)                          # a capital: by pitch
    press('left', ['nowa linia'], False)                # off the line: the control
    print('foreground kept:', auto.GetForegroundControl().NativeWindowHandle == fg_before)
    return 0


try:
    code = main()
finally:
    ps.kill()
print()
print('PROBLEMS:' if problems else 'ALL GOOD', *problems, sep='\n  ')
sys.exit(1 if problems or code else 0)
