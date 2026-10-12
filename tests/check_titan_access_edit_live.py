# -*- coding: utf-8 -*-
"""Drive the REAL Titan Access edit-field path against a REAL edit window.

    python tests/check_titan_access_edit_live.py

The reader's own engine object, its EditableTextHandler, its KeyboardHook
`_process` and a background read thread exactly as `submit_read` runs it;
a real multiline EDIT window (wrapping) with its own message loop. Every
key goes two places, as on a real desktop: through the hook (what the
reader sees), and to THAT window only (PostMessage WM_KEYDOWN / WM_CHAR) -
nothing is pressed globally, so the user's own window is never touched.
Speech is recorded, never spoken. Runs on a copy of the user's stores.

Prints what was said per key and fails on anything wrong.
"""

import ctypes
import os
import shutil
import sys
import tempfile
import threading
import time
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')

_base = os.getenv('APPDATA') or os.path.expanduser('~')
_target = tempfile.mkdtemp(prefix='titan_access_edit_probe_')
_src = os.path.join(_base, 'titosoft', 'Titan', 'screenreader')
if os.path.isdir(_src):
    shutil.copytree(_src, os.path.join(_target, 'titosoft', 'Titan', 'screenreader'),
                    ignore=shutil.ignore_patterns('*.log'))
os.environ['APPDATA'] = _target
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from titan_access import localization as loc            # noqa: E402
from titan_access.contracts import AccessibleObject      # noqa: E402
from titan_access.engine import TitanAccessEngine        # noqa: E402
from titan_access.editable_text import EditableTextHandler  # noqa: E402
from titan_access.keyboard_hook import KeyboardHook      # noqa: E402

u = ctypes.WinDLL('user32', use_last_error=True)
u.CreateWindowExW.restype = wintypes.HWND
u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                              wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.HWND,
                              wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
u.SendMessageW.restype = ctypes.c_ssize_t
u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t]
u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t]
u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
u.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
u.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
u.DestroyWindow.argtypes = [wintypes.HWND]
u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t]

said = []
T0 = time.time()


class Recorder:
    supports_pitch = True

    def speak_async(self, text, position=0.0, interrupt=True, pitch_offset=0, **_k):
        said.append((round(time.time() - T0, 3), text))

    speak = speak_async

    def stop(self):
        pass


TEXT = ('Pierwszy wiersz.\r\n'
        'Drugi wiersz to długi akapit, który zawija się na ekranie na kilka '
        'wierszy, bo okno jest wąskie i słowa się nie mieszczą.\r\n'
        'Ostatni.')
box = {}


def window_thread():
    ES = 0x0004 | 0x0040 | 0x0080 * 0           # MULTILINE | AUTOVSCROLL
    hwnd = u.CreateWindowExW(0, 'EDIT', None, ES, 0, 0, 260, 300,
                             None, None, None, None)
    buf = ctypes.create_unicode_buffer(TEXT)
    u.SendMessageW(hwnd, 0x000C, 0, ctypes.addressof(buf))
    u.SendMessageW(hwnd, 0x00B1, 0, 0)
    box['hwnd'] = hwnd
    box['tid'] = ctypes.windll.kernel32.GetCurrentThreadId()
    # Polish (Programmers) for THIS thread only (no KLF_SETFORPROCESS):
    # the user's own windows keep their layout.
    u.LoadKeyboardLayoutW.restype = ctypes.c_void_p
    u.LoadKeyboardLayoutW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    u.ActivateKeyboardLayout.restype = ctypes.c_void_p
    u.ActivateKeyboardLayout.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    box['hkl'] = u.LoadKeyboardLayoutW('00000415', 0x80)
    u.ActivateKeyboardLayout(box['hkl'], 0)
    msg = wintypes.MSG()
    while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == 0x8001:                    # WM_APP+1: Shift state
            state = (ctypes.c_ubyte * 256)()
            u.GetKeyboardState(state)
            for vk in (0x10, 0xA0):
                state[vk] = 0x80 if msg.wParam else 0
            u.SetKeyboardState(state)
            continue
        u.TranslateMessage(ctypes.byref(msg))
        u.DispatchMessageW(ctypes.byref(msg))
    u.DestroyWindow(hwnd)


threading.Thread(target=window_thread, daemon=True).start()
while 'hwnd' not in box:
    time.sleep(0.01)
hwnd = box['hwnd']

loc.set_language('pl')
engine = TitanAccessEngine()
engine.speech = Recorder()
engine._muted_for_foreground = lambda: False
engine.settings.phonetic_letters = False
# On the probe's COPY only: the user's own echo setting may be None.
engine.settings.keyboard_echo = 'CharactersAndWords'
engine.editable = EditableTextHandler(engine)
engine.submit_read = lambda fn: threading.Thread(target=fn, daemon=True).start()
engine.current_object = AccessibleObject(role='edit', name='Pole', class_name='Edit',
                                         hwnd=int(hwnd))
engine.editable.set_element(engine.current_object)
hook = KeyboardHook(engine)
hook.is_in_edit_field = True

EXT = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}
NAMES = {0x25: 'Left', 0x27: 'Right', 0x26: 'Up', 0x28: 'Down', 0x24: 'Home',
         0x23: 'End', 0x22: 'PageDown'}
VK_CONTROL = 0x11
problems = []


def caret():
    s = wintypes.DWORD()
    u.SendMessageW(hwnd, 0x00B0, ctypes.addressof(s), 0)
    return s.value


def press(vk, ctrl=False, label=None):
    """The reader sees the key first (the hook runs before the program),
    then the program gets it."""
    mark = len(said)
    t = time.time()
    if ctrl:
        hook._process(0xA2, 0x1D, 0, True)
        u.PostMessageW(hwnd, 0x0100, VK_CONTROL, 0)
    flags = 0x01 if vk in EXT else 0
    if os.environ.get('PROFILE_FIRST') and mark == 0:
        import cProfile, pstats
        pr = cProfile.Profile()
        pr.runcall(hook._process, vk, 0, flags, True)
        pstats.Stats(pr).sort_stats('cumulative').print_stats(18)
    else:
        hook._process(vk, 0, flags, True)
    first = said[mark][0] - (t - T0) if len(said) > mark else None
    # GetKeyState decides Ctrl inside EDIT; a posted WM_KEYDOWN cannot
    # carry it, so a Control key is applied with what EDIT would do.
    if ctrl and vk == 0x24:
        u.SendMessageW(hwnd, 0x00B1, 0, 0)
    elif ctrl and vk == 0x23:
        n = u.SendMessageW(hwnd, 0x000E, 0, 0)
        u.SendMessageW(hwnd, 0x00B1, n, n)
    else:
        u.PostMessageW(hwnd, 0x0100, vk, 1)
        u.PostMessageW(hwnd, 0x0101, vk, 0xC0000001)
    hook._process(vk, 0, flags | 0x80, False)
    if ctrl:
        hook._process(0xA2, 0x1D, 0x80, False)
    time.sleep(0.45)
    words = [w for _t, w in said[mark:]]
    name = label or (('Ctrl+' if ctrl else '') + NAMES.get(vk, hex(vk)))
    lat = '%.0f ms' % (first * 1000) if first is not None else '-'
    print('%-12s caret=%-4d first word after %-7s %s' % (name, caret(), lat, words))
    return words, first


def type_char(ch, vk, altgr=False, shift=False):
    mark = len(said)
    if altgr:
        hook._process(0xA2, 0x21D, 0, True)
        hook._process(0xA5, 0x38, 0x01, True)
    if shift:
        hook._process(0xA0, 0x2A, 0, True)
    hook._process(vk, 0, 0, True)
    u.PostMessageW(hwnd, 0x0102, ord(ch), 1)            # what the program types
    hook._process(vk, 0, 0x80, False)
    if shift:
        hook._process(0xA0, 0x2A, 0x80, False)
    if altgr:
        hook._process(0xA5, 0x38, 0x81, False)
        hook._process(0xA2, 0x21D, 0x80, False)
    time.sleep(0.25)
    words = [w for _t, w in said[mark:]]
    print('type %-4r -> %s' % (ch, words))
    return words


def expect(cond, what):
    if not cond:
        problems.append(what)
        print('   !!', what)


# A started reader has imported its walkers and modules long before the
# first arrow; this engine was never started, so one harmless key (F13)
# pays that once, as start-up does.
hook._process(0x7C, 0, 0, True)
hook._process(0x7C, 0, 0x80, False)
print('--- arrows (the field: %d chars) ---' % len(TEXT))
w, f = press(0x27)                                       # Right
expect(w == ['i'], 'Right should say i once, said %r' % w)
expect(f is not None and f < 0.03, 'Right should be said at once')
w, _ = press(0x27)
expect(w == ['e'], 'second Right: e, said %r' % w)
w, _ = press(0x23)                                       # End
expect(w == ['Pierwszy wiersz.'], 'End: the line, said %r' % w)
w, _ = press(0x27)                                       # Right over CRLF
expect(w == ['d'], 'Right over the line break onto D (a capital: by pitch), said %r' % w)
w, _ = press(0x25)                                       # Left back to the CR
expect(w == ['nowa linia'], 'Left onto the line end: nowa linia, said %r' % w)
w, f = press(0x28)                                       # Down into the paragraph
expect(len(w) == 1 and w[0].startswith('Drugi') and 'mieszczą' not in w[0],
       'Down: the first SCREEN line of the paragraph, said %r' % w)
expect(f is not None and f < 0.03, 'Down should be said at once')
w, _ = press(0x28)
expect(len(w) == 1 and not w[0].startswith('Drugi'),
       'Down again: the next screen line of the same paragraph, said %r' % w)
w, _ = press(0x23, ctrl=True)
expect(w == ['Ostatni.'], 'Ctrl+End: the last line, said %r' % w)
w, _ = press(0x24, ctrl=True)
expect(w == ['Pierwszy wiersz.'], 'Ctrl+Home: the first line, said %r' % w)
w, _ = press(0x26)
expect(w == ['Pierwszy wiersz.'], 'Up on the first line: the same line, said %r' % w)
expect(all(not x.startswith('<') for x in [s for _t, s in said]), 'no sound words')

print('--- typing at the end ---')
n = u.SendMessageW(hwnd, 0x000E, 0, 0)
u.SendMessageW(hwnd, 0x00B1, n, n)
engine.editable.set_element(engine.current_object)
layout_said = type_char('ą', 0x41, altgr=True)
expect(layout_said and layout_said[-1] in ('ą', 'Aniela'),
       'AltGr+A should say ą (with the layout of the window in front), said %r'
       % layout_said)
for ch, vk, shift in (('@', 0x32, True), ('!', 0x31, True), ('/', 0xBF, False)):
    w = type_char(ch, vk, shift=shift)
    # A symbol also ends the word before it, which is said first (echo
    # of words); the symbol itself is said by its name.
    expect(w and w[-1] != ch and len(w[-1]) > 1,
           '%r should be said by name, said %r' % (ch, w))
time.sleep(0.2)
text_len = u.SendMessageW(hwnd, 0x000E, 0, 0)
print('--- a dead key, through the real layout and TranslateMessage ---')
# The hook reads the layout of the window in front; here that is the
# probe's own window, whose thread runs Polish (Programmers).
real_user32 = hook._user32


class _Front(object):
    def __getattr__(self, name):
        return getattr(real_user32, name)

    def GetForegroundWindow(self):
        return hwnd


hook._user32 = _Front()
MapVK = u.MapVirtualKeyW


def key_through(vk, shift=False):
    """The hook first (as on a desktop), then the program's own
    TranslateMessage on its own thread and layout."""
    scan = MapVK(vk, 0)
    if shift:
        hook._process(0xA0, 0x2A, 0, True)
    hook._process(vk, scan, 0, True)
    u.PostMessageW(hwnd, 0x8001, 1 if shift else 0, 0)
    u.PostMessageW(hwnd, 0x0100, vk, 1 | (scan << 16))
    u.PostMessageW(hwnd, 0x0101, vk, 0xC0000001 | (scan << 16))
    u.PostMessageW(hwnd, 0x8001, 0, 0)
    hook._process(vk, scan, 0x80, False)
    if shift:
        hook._process(0xA0, 0x2A, 0x80, False)
    time.sleep(0.15)


if box.get('hkl'):
    mark = len(said)
    key_through(0xC0, shift=True)                       # ~ (dead)
    key_through(0x41)                                   # a
    key_through(0xC0, shift=True)
    key_through(0x5A)                                   # z
    dead_words = [w for _t, w in said[mark:]]
    print('the reader said:', dead_words)
    expect(dead_words[:1] == ['ą'] and 'ż' in dead_words,
           'the dead key: the reader should say ą and ż, said %r' % dead_words)
    time.sleep(0.2)
    n2 = u.SendMessageW(hwnd, 0x000E, 0, 0)
    b2 = ctypes.create_unicode_buffer(n2 + 1)
    u.SendMessageW(hwnd, 0x000D, n2 + 1, ctypes.addressof(b2))
    print('the program typed:', repr(b2.value[-2:]))
    expect(b2.value.endswith('ąż'),
           'the program must still get its accented letters, got %r' % b2.value[-4:])
    hook._user32 = real_user32
else:
    print('Polish (Programmers) is not installed: the dead key is not probed')

print('the field now ends with:', end=' ')
buf = ctypes.create_unicode_buffer(text_len + 1)
u.SendMessageW(hwnd, 0x000D, text_len + 1, ctypes.addressof(buf))
print(repr(buf.value[-8:]))
expect('ą@!/' in buf.value, 'what was typed reached the field')
u.PostThreadMessageW(box['tid'], 0x0012, 0, 0)

print()
print('PROBLEMS:' if problems else 'ALL GOOD', *problems, sep='\n  ')
sys.exit(1 if problems else 0)
