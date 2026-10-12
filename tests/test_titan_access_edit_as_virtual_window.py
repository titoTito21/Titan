# -*- coding: utf-8 -*-
"""An edit field in Titan Access answers like a virtual window.

    python tests/test_titan_access_edit_as_virtual_window.py

What an arrow lands on is worked out from the field's own text and said
the moment the key is pressed (`editable_text.predict_caret`); the read of
the real control afterwards is silent when the program did what the model
said, and corrects it when it did not. No mode, no sound: it stays an
ordinary edit field. And what is typed is said as it is typed - AltGr's
Polish letters, a dead key's accented letter, the symbols by name.

The Win32 cases use REAL edit windows made with CreateWindowEx and never
shown; no key is pressed anywhere. Nothing here speaks or touches the
user's settings.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)
if sys.platform.startswith('win'):
    # The vendored uiautomation, as the component's init.py puts it there.
    sys.path.insert(0, os.path.join(COMPONENT, 'lib'))

os.environ['APPDATA'] = tempfile.mkdtemp()      # never the user's own store

from titan_access import localization as loc     # noqa: E402
from titan_access.contracts import AccessibleObject  # noqa: E402
from titan_access.settings_store import get_settings  # noqa: E402
from titan_access import editable_text, keyboard_hook, symbols  # noqa: E402

IS_WINDOWS = sys.platform.startswith('win')
predict = editable_text.predict_caret


def whole(text, caret, lines=None, line=None, count=None, sel_end=None):
    snap = {'text': text, 'caret': caret, 'whole': True,
            'sel_end': caret if sel_end is None else sel_end}
    if lines is not None:
        snap.update(lines=lines, line=line, count=count)
    return snap


class ThePredictionIsWhatTheFieldWillDo(unittest.TestCase):

    def test_right_reads_the_next_character(self):
        kind, text, after = predict(whole('Ala', 0), 'right')
        self.assertEqual((kind, text, after['caret']), ('char', 'l', 1))

    def test_left_reads_the_character_before(self):
        kind, text, after = predict(whole('Ala', 2), 'left')
        self.assertEqual((kind, text, after['caret']), ('char', 'l', 1))

    def test_a_crlf_is_one_step_both_ways(self):
        # "ab|\r\ncd": Right goes over the line break onto c.
        self.assertEqual(predict(whole('ab\r\ncd', 2), 'right')[1:3:2][0], 'c')
        self.assertEqual(predict(whole('ab\r\ncd', 2), 'right')[2]['caret'], 4)
        # "ab\r\n|cd": Left lands at the end of the line - a line break.
        kind, text, after = predict(whole('ab\r\ncd', 4), 'left')
        self.assertEqual((text, after['caret']), ('\r', 2))

    def test_the_ends_of_the_text(self):
        self.assertEqual(predict(whole('Ala', 3), 'right')[1], '')
        self.assertEqual(predict(whole('Ala', 0), 'left')[1], 'A')

    def test_a_selection_is_not_predicted(self):
        self.assertIsNone(predict(whole('Ala ma', 0, sel_end=3), 'right'))

    def test_a_model_the_typing_has_overtaken_is_not_used(self):
        snap = whole('Ala', 1)
        snap['stale'] = True
        self.assertIsNone(predict(snap, 'right'))

    def test_control_arrows_are_left_to_the_program(self):
        self.assertIsNone(predict(whole('Ala ma kota', 0), 'right', ctrl=True))

    def test_visual_lines_up_down_home_end(self):
        text = 'jeden dwa trzy cztery'
        # Wrapped on screen as "jeden dwa " / "trzy " / "cztery".
        lines = {0: (0, 10), 1: (10, 5), 2: (15, 6)}
        snap = whole(text, 12, lines=lines, line=1, count=3)
        self.assertEqual(predict(snap, 'down')[:2], ('line', 'cztery'))
        self.assertEqual(predict(snap, 'up')[:2], ('line', 'jeden dwa '))
        self.assertEqual(predict(snap, 'home')[1], 'trzy ')
        self.assertEqual(predict(snap, 'end')[2]['caret'], 15)
        self.assertEqual(predict(snap, 'home', ctrl=True)[1], 'jeden dwa ')
        self.assertEqual(predict(snap, 'end', ctrl=True)[1], 'cztery')
        # The column goes with the caret, kept within the line.
        self.assertEqual(predict(snap, 'down')[2]['caret'], 17)

    def test_up_on_the_first_line_stays_on_it(self):
        lines = {0: (0, 3), 1: (5, 3)}
        snap = whole('abc\r\ndef', 1, lines=lines, line=0, count=2)
        self.assertEqual(predict(snap, 'up')[1], 'abc')

    def test_one_line_up_down_is_each_programs_own(self):
        snap = whole('abc', 1, lines={0: (0, 3)}, line=0, count=1)
        self.assertIsNone(predict(snap, 'up'))

    def test_a_line_kept_by_the_last_read_answers_inside_the_line(self):
        snap = {'text': 'Ala ma\r', 'caret': 2, 'whole': False, 'sel': False}
        self.assertEqual(predict(snap, 'right')[1], ' ')
        self.assertEqual(predict(snap, 'home')[1], 'Ala ma\r')
        self.assertEqual(predict(snap, 'end')[2]['caret'], 6)
        # Off the line the next one is not known.
        self.assertIsNone(predict(dict(snap, caret=0), 'left'))
        self.assertIsNone(predict(snap, 'down'))
        self.assertIsNone(predict(dict(snap, sel=True), 'right'))


class _Engine:
    def __init__(self, obj):
        self.settings = get_settings()
        self.settings.phonetic_letters = False
        self.current_object = obj
        self.said = []

    def speak(self, text, **_k):
        self.said.append(text)

    def play(self, *_a, **_k):
        self.said.append('<sound>')

    def submit_action(self, fn):
        fn()

    class sound:
        @staticmethod
        def play_tone(*_a, **_k):
            pass


class TheConfirmingReadIsSilentWhenTheModelWasRight(unittest.TestCase):

    def handler(self):
        loc.set_language('pl')
        engine = _Engine(AccessibleObject(role='edit', name='Pole'))
        return engine, editable_text.EditableTextHandler(engine)

    def test_the_same_unit_is_not_said_twice(self):
        engine, handler = self.handler()
        handler._snap = {'text': 'kot', 'caret': 0, 'whole': False,
                         'sel': False, 't': 9e12}
        self.assertEqual(handler.predict_caret_move('right'), ('char', 'o'))
        self.assertEqual(engine.said, ['o'])
        handler._speak_caret_text('char', 'o')      # the real read
        self.assertEqual(engine.said, ['o'])

    def test_what_the_program_really_did_is_said_over_the_prediction(self):
        engine, handler = self.handler()
        handler._snap = {'text': 'kot', 'caret': 0, 'whole': False,
                         'sel': False, 't': 9e12}
        handler.predict_caret_move('right')
        handler._speak_caret_text('char', 't')
        self.assertEqual(engine.said, ['o', 't'])

    def test_a_repeated_letter_is_said_each_time(self):
        engine, handler = self.handler()
        handler._snap = {'text': 'aaa', 'caret': 0, 'whole': False,
                         'sel': False, 't': 9e12}
        handler.predict_caret_move('right')
        handler.predict_caret_move('right')
        self.assertEqual(engine.said, ['a', 'a'])

    def test_the_end_of_a_line_is_a_line_break_not_silence(self):
        engine, handler = self.handler()
        handler._speak_caret_text('char', '\r')
        self.assertEqual(engine.said, ['nowa linia'])

    def test_no_sound_is_played(self):
        engine, handler = self.handler()
        handler._snap = {'text': 'kot', 'caret': 0, 'whole': False,
                         'sel': False, 't': 9e12}
        for key in ('right', 'right', 'home', 'end', 'left'):
            handler.predict_caret_move(key)
        self.assertNotIn('<sound>', engine.said)


class _RawRange(object):
    """A stand-in IUIAutomationTextRange over [start, end) of a text whose
    Line unit has WPF's faults (see `editable_text._expand`)."""
    TEXT = 'Ala ma kota.\r\nDrugi.'
    LINES = ((0, 12), (14, 20))

    def __init__(self, start, end=None, lean_forward=False):
        self.start, self.end = start, start if end is None else end
        self.lean = lean_forward
        self.calls = []

    def Clone(self):
        return _RawRange(self.start, self.end, self.lean)

    def CompareEndpoints(self, src, other, target):
        assert isinstance(other, _RawRange), 'the COM call gets the raw range'
        a = self.start if src == 0 else self.end
        b = other.start if target == 0 else other.end
        return (a > b) - (a < b)

    def MoveEndpointByUnit(self, endpoint, unit, count):
        step = 2 if (count > 0 and self.TEXT[self.end:self.end + 2] == '\r\n') or \
            (count < 0 and self.TEXT[self.start - 2:self.start] == '\r\n') else 1
        if endpoint == 1:
            self.end = min(len(self.TEXT), self.end + step * count)
        else:
            self.start = max(0, self.start + step * count)
        return count

    def ExpandToEnclosingUnit(self, unit):
        p = self.start
        if self.start == self.end and (p == 14 or (p == 12 and self.lean)):
            self.start, self.end = 0, 20          # WPF: both lines
            return
        if self.end - self.start == 2 and self.TEXT[self.start:self.end] == '\r\n' \
                and self.lean:
            self.start, self.end = 0, 20
            return
        for a, b in self.LINES:
            if a <= p <= b + 1:
                self.start, self.end = a, b
                return

    def GetText(self, n=-1):
        return self.TEXT[self.start:self.end]


class TheUiaRangesAreAskedDirectly(unittest.TestCase):

    def test_no_sleep_and_the_raw_range_reaches_compare(self):
        import time
        fast = editable_text._FastRange(_RawRange(3))
        t = time.perf_counter()
        for _ in range(20):
            work = fast.Clone()
            work.MoveEndpointByUnit(1, 0, 1)
            work.ExpandToEnclosingUnit(3)
            fast.CompareEndpoints(0, work, 0)
        self.assertLess(time.perf_counter() - t, 0.2)

    def test_the_line_at_both_ends_of_a_wpf_line(self):
        if editable_text._UNIT_CHAR is None:
            self.skipTest('uiautomation is not importable here')
        line = lambda r: editable_text._expand(
            editable_text._FastRange(r), editable_text._UNIT_LINE).GetText()
        self.assertEqual(line(_RawRange(14)), 'Drugi.')            # line start
        self.assertEqual(line(_RawRange(12, lean_forward=True)), 'Ala ma kota.')
        self.assertEqual(line(_RawRange(5)), 'Ala ma kota.')


class TheRepeatFilterIsPerKey(unittest.TestCase):

    def test_home_right_after_down_on_the_same_line_is_said(self):
        loc.set_language('pl')
        engine = _Engine(AccessibleObject(role='edit', name='Pole'))
        handler = editable_text.EditableTextHandler(engine)
        handler._key_now = ('down', False)
        handler._speak_caret_text('line', 'Drugi wiersz')
        handler._key_now = ('home', False)
        handler._speak_caret_text('line', 'Drugi wiersz')
        self.assertEqual(len(engine.said), 2)

    def test_one_key_delivered_twice_is_said_once(self):
        engine = _Engine(AccessibleObject(role='edit', name='Pole'))
        handler = editable_text.EditableTextHandler(engine)
        handler._key_now = ('down', False)
        handler._speak_caret_text('line', 'Drugi wiersz')
        handler._speak_caret_text('line', 'Drugi wiersz')
        self.assertEqual(len(engine.said), 1)


@unittest.skipUnless(IS_WINDOWS, 'real Win32 edit windows')
class ARealWrappedWin32Field(unittest.TestCase):
    """A multiline EDIT that wraps: the model reads its visual lines from
    the control, and the real read of a line is the SCREEN line."""

    ES_MULTILINE = 0x0004
    ES_AUTOVSCROLL = 0x0040

    def setUp(self):
        import ctypes
        from ctypes import wintypes
        loc.set_language('pl')
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.u.CreateWindowExW.restype = wintypes.HWND
        self.u.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE,
            wintypes.LPVOID]
        self.u.SendMessageW.restype = ctypes.c_ssize_t
        self.u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        ctypes.c_size_t, ctypes.c_size_t]
        self.u.DestroyWindow.argtypes = [wintypes.HWND]
        self.windows = []

    def tearDown(self):
        for hwnd in self.windows:
            self.u.DestroyWindow(hwnd)

    def edit(self, text, style, width=200):
        import ctypes
        hwnd = self.u.CreateWindowExW(0, 'EDIT', None, style, 0, 0, width,
                                      200, None, None, None, None)
        self.assertTrue(hwnd)
        self.windows.append(hwnd)
        buf = ctypes.create_unicode_buffer(text)
        self.u.SendMessageW(hwnd, 0x000C, 0, ctypes.addressof(buf))
        return hwnd

    def caret(self, hwnd, pos):
        self.u.SendMessageW(hwnd, 0x00B1, pos, pos)

    def handler(self, hwnd):
        obj = AccessibleObject(role='edit', name='Pole', class_name='Edit',
                               hwnd=int(hwnd))
        engine = _Engine(obj)
        handler = editable_text.EditableTextHandler(engine)
        handler.set_element(obj)
        return engine, handler

    def test_the_model_knows_the_lines_of_a_multiline_field(self):
        hwnd = self.edit('pierwszy\r\ndrugi\r\ntrzeci',
                         self.ES_MULTILINE | self.ES_AUTOVSCROLL)
        self.caret(hwnd, 12)                         # in "drugi"
        snap = editable_text._win32_model(hwnd)
        self.assertEqual((snap['line'], snap['count']), (1, 3))
        self.assertEqual(predict(snap, 'down')[1], 'trzeci')
        self.assertEqual(predict(snap, 'up')[1], 'pierwszy')

    def test_down_is_said_before_the_program_moves_and_confirmed_quietly(self):
        hwnd = self.edit('pierwszy\r\ndrugi\r\ntrzeci',
                         self.ES_MULTILINE | self.ES_AUTOVSCROLL)
        self.caret(hwnd, 2)
        engine, handler = self.handler(hwnd)
        self.assertEqual(handler.predict_caret_move('down'),
                         ('line', 'drugi'))
        self.caret(hwnd, 12)                         # what the program does
        handler.read_caret_line()
        self.assertEqual(engine.said, ['drugi'])

    def test_a_wrapped_paragraph_is_read_a_screen_line_at_a_time(self):
        words = ' '.join(['slowo%d' % i for i in range(40)])
        hwnd = self.edit(words, self.ES_MULTILINE | self.ES_AUTOVSCROLL,
                         width=150)
        count = self.u.SendMessageW(hwnd, 0x00BA, 0, 0)
        self.assertGreater(count, 2, 'the paragraph must wrap')
        self.caret(hwnd, 0)
        engine, handler = self.handler(hwnd)
        handler.read_caret_line()
        first = engine.said[-1]
        self.assertTrue(words.startswith(first.strip()))
        self.assertLess(len(first), len(words) // 2)

    def test_a_single_line_field_reads_its_characters(self):
        hwnd = self.edit('zażółć', 0)
        self.caret(hwnd, 0)
        engine, handler = self.handler(hwnd)
        handler.predict_caret_move('right')
        handler.predict_caret_move('end')
        self.assertEqual(engine.said, ['a', 'zażółć'])


class _HookEngine(object):
    def __init__(self):
        self.typed = []
        self.moves = []

    def on_char_typed(self, ch):
        self.typed.append(ch)

    def on_edit_caret_move(self, key, ctrl, shift=False):
        self.moves.append((key, ctrl, shift))

    def __getattr__(self, name):
        return lambda *a, **k: False


def _hook(in_edit=True):
    hook = keyboard_hook.KeyboardHook.__new__(keyboard_hook.KeyboardHook)
    hook.engine = _HookEngine()
    for name, value in (('_ctrl', False), ('_alt', False),
                        ('_shift', False), ('_reader_mod', False),
                        ('_mod_used', False), ('_ralt', False),
                        ('_word', []), ('_user32', None),
                        ('is_in_edit_field', in_edit),
                        ('is_in_browse_mode', False)):
        setattr(hook, name, value)
    hook._is_reader_modifier = lambda vk, extended: False
    hook._modifier_pressed = lambda name: None
    hook._command_pressed = lambda label: None
    return hook


class WhatIsTypedIsSaid(unittest.TestCase):

    def test_altgr_letters_are_typing_not_a_command(self):
        hook = _hook()
        asked = []

        def to_char(vk, scan, altgr=False):
            asked.append(altgr)
            return 'ą' if altgr else 'a'
        hook._vk_to_char = to_char
        hook._ctrl = hook._alt = hook._ralt = True   # AltGr held
        hook._process(0x41, 0x1E, 0, True)
        self.assertEqual(hook.engine.typed, ['ą'])
        self.assertEqual(asked, [True])

    def test_control_alt_without_altgr_is_still_a_command(self):
        hook = _hook()
        hook._vk_to_char = lambda vk, scan, altgr=False: 'a'
        hook._ctrl = hook._alt = True
        hook._process(0x41, 0x1E, 0, True)
        self.assertEqual(hook.engine.typed, [])

    def test_control_home_and_page_down_are_read(self):
        hook = _hook()
        hook._ctrl = True
        hook._process(0x24, 0x47, 0x01, True)        # extended Home
        hook._ctrl = False
        hook._process(0x22, 0x51, 0x01, True)        # extended Page Down
        self.assertEqual(hook.engine.moves, [('home', True, False),
                                             ('pagedown', False, False)])

    def test_a_dead_key_and_the_letter_after_it(self):
        compose = keyboard_hook.compose_dead
        self.assertEqual(compose('~', 'a', 0x04150415), 'ą')   # Polish Programmers
        self.assertEqual(compose('~', 'z', 0x04150415), 'ż')
        self.assertEqual(compose('~', 'X', 0x04150415), 'Ź')
        self.assertEqual(compose('~', 'n', 0x04090409), 'ñ')
        self.assertEqual(compose('´', 'e', 0), 'é')
        self.assertEqual(compose('^', ' ', 0), '^')            # the accent alone
        self.assertEqual(compose('^', 'q', 0), 'q')            # nothing to put it on

    def test_the_symbols_a_polish_keyboard_types_have_names(self):
        loc.set_language('pl')
        settings = get_settings()
        for ch, word in (('€', 'euro'), ('§', 'paragraf'), ('~', 'tylda'),
                         ('„', 'cudzysłów otwierający'), ('–', 'półpauza'),
                         ('@', 'małpa')):
            self.assertEqual(symbols.describe_char(ch, settings)[0], word)
        self.assertEqual(symbols.describe_char('ż', settings)[0], 'ż')


class OffWindowsTheKeysymSaysWhatWasTyped(unittest.TestCase):
    """Linux: there is no ToUnicodeEx; the accessibility bus hands over
    the keysym with the layout and AltGr already applied."""

    def test_keysyms_are_characters(self):
        from titan_access import atspi_keys
        self.assertEqual(atspi_keys.typed_char(0x61), 'a')
        self.assertEqual(atspi_keys.typed_char(0x1b1), 'ą')        # aogonek
        self.assertEqual(atspi_keys.typed_char(0x1af), 'Ż')        # Zabovedot
        self.assertEqual(atspi_keys.typed_char(0xf3), 'ó')         # Latin-1
        self.assertEqual(atspi_keys.typed_char(0x20ac), '€')       # EuroSign
        self.assertEqual(atspi_keys.typed_char(0x1000105), 'ą')    # Unicode
        self.assertEqual(atspi_keys.typed_char(0xff51), '')        # Left

    @unittest.skipIf(IS_WINDOWS, 'the Linux path')
    def test_altgr_letter_is_echoed_from_the_keysym(self):
        hook = _hook()
        hook._alt = hook._ralt = True                 # ISO_Level3_Shift
        hook._posix_char = 'ł'
        hook._process(0x4C, 0, 0, True)
        self.assertEqual(hook.engine.typed, ['ł'])


@unittest.skipUnless(IS_WINDOWS, 'the real keyboard layout')
class TheRealLayoutTypesPolishLetters(unittest.TestCase):

    def test_altgr_a_on_polish_programmers(self):
        import ctypes
        u = ctypes.WinDLL('user32')
        u.LoadKeyboardLayoutW.restype = ctypes.c_void_p
        u.LoadKeyboardLayoutW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
        hkl = u.LoadKeyboardLayoutW('00000415', 0x80)   # KLF_NOTELLSHELL
        if not hkl or keyboard_hook._user32 is None:
            self.skipTest('Polish (Programmers) is not installed')

        class Layout(object):
            """user32, with the Polish layout in front."""
            def __getattr__(self, name):
                return getattr(keyboard_hook._user32, name)

            def GetKeyboardLayout(self, tid):
                return hkl

        hook = keyboard_hook.KeyboardHook.__new__(keyboard_hook.KeyboardHook)
        hook._user32 = Layout()
        hook._shift = False
        self.assertEqual(hook._vk_to_char(0x41, 0x1E, altgr=True), 'ą')
        self.assertEqual(hook._vk_to_char(0x5A, 0x2C, altgr=True), 'ż')
        self.assertEqual(hook._vk_to_char(0x41, 0x1E), 'a')
        hook._shift = True
        self.assertEqual(hook._vk_to_char(0x32, 0x03), '@')


    def test_dead_keys_on_real_layouts(self):
        """The real ToUnicodeEx with flag 4: the dead key is reported
        (None), the program's pending accent is left alone, and the
        letter after it is the accented one."""
        import ctypes
        u = ctypes.WinDLL('user32')
        u.LoadKeyboardLayoutW.restype = ctypes.c_void_p
        u.LoadKeyboardLayoutW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
        u.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]
        if not keyboard_hook._TOUNICODE_KEEPS_STATE:
            self.skipTest('Windows older than 10 1607')
        cases = (('00000415', [(0xC0, True), (0x41, False)], 'ą'),
                 ('00000415', [(0xC0, True), (0x5A, False)], 'ż'),
                 ('0000040C', [(0xDD, False), (0x45, False)], 'ê'),
                 ('00000407', [(0xDD, False), (0x45, False)], 'é'))
        for klid, keys, want in cases:
            hkl = u.LoadKeyboardLayoutW(klid, 0x80)
            if not hkl:
                continue

            class Layout(object):
                def __getattr__(self, name):
                    return getattr(keyboard_hook._user32, name)

                def GetKeyboardLayout(self, tid, hkl=hkl):
                    return hkl
            hook = keyboard_hook.KeyboardHook.__new__(keyboard_hook.KeyboardHook)
            hook._user32 = Layout()
            hook._dead = None
            got = []
            for vk, shift in keys:
                hook._shift = shift
                got.append(hook._vk_to_char(vk, int(u.MapVirtualKeyW(vk, 0))))
            self.assertEqual(got, [None, want], klid)

if __name__ == '__main__':
    unittest.main(verbosity=1)
