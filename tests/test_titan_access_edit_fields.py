# -*- coding: utf-8 -*-
"""Edit fields in Titan Access: what they are called, and what Backspace
and Delete say.

    python tests/test_titan_access_edit_fields.py

A field that takes several lines is "Pole edycji" (pause) "wieloliniowe";
one that cannot be typed into is "Tekst" (pause) "tylko do odczytu" - the
type and the state as two parts, in their own voices. Backspace says what
it took away (Control: the word), Delete what the caret is on now.

The Win32 cases use REAL edit windows, made with CreateWindowEx and never
shown, because what this reads is the window's own style and text. Nothing
here speaks, plays a sound or touches the user's settings.
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

os.environ['APPDATA'] = tempfile.mkdtemp()      # never the user's own store

from titan_access import localization as loc     # noqa: E402
from titan_access.contracts import AccessibleObject  # noqa: E402
from titan_access.accessible import describe     # noqa: E402
from titan_access.settings_store import get_settings  # noqa: E402
from titan_access import edit_fields, editable_text  # noqa: E402

IS_WINDOWS = sys.platform.startswith('win')


def _texts(obj):
    return [seg[0] for seg in describe(obj, get_settings())]


class AFieldIsCalledWhatItIs(unittest.TestCase):

    def setUp(self):
        loc.set_language('pl')

    def test_a_multiline_field_says_so_after_its_type(self):
        obj = AccessibleObject(role='edit', name='Notatka',
                               states={'multiline'})
        self.assertEqual(_texts(obj), ['Notatka', 'Pole edycji',
                                       'wieloliniowe'])

    def test_a_read_only_field_is_text(self):
        obj = AccessibleObject(role='edit', name='Opis',
                               states={'readonly', 'multiline'})
        self.assertEqual(_texts(obj), ['Opis', 'Tekst', 'tylko do odczytu'])

    def test_a_single_line_field_is_only_a_field(self):
        obj = AccessibleObject(role='edit', name='Imię')
        self.assertEqual(_texts(obj), ['Imię', 'Pole edycji'])

    def test_a_document_that_is_not_a_page_takes_lines(self):
        obj = AccessibleObject(role='document', name='Bez tytułu',
                               framework_id='Win32')
        self.assertEqual(_texts(obj), ['Bez tytułu', 'Pole edycji',
                                       'wieloliniowe'])

    def test_a_web_page_is_left_alone(self):
        obj = AccessibleObject(role='document', name='Strona',
                               framework_id='Chrome')
        self.assertEqual(_texts(obj), ['Strona', 'Dokument'])

    def test_type_and_state_are_separate_parts_in_their_own_pitch(self):
        obj = AccessibleObject(role='edit', name='N', states={'multiline'})
        segs = describe(obj, get_settings())
        self.assertEqual(len(segs), 3)
        self.assertNotEqual(segs[1][1], segs[2][1])

    def test_a_state_is_never_said_as_its_english_key(self):
        for state, word in (('required', 'wymagane'),
                            ('readonly', 'tylko do odczytu'),
                            ('pressed', 'wciśnięty'),
                            ('busy', 'zajęty')):
            self.assertEqual(loc.state_label(state), word)

    def test_a_value_with_line_breaks_takes_lines(self):
        obj = AccessibleObject(role='edit', name='N', value='a\r\nb')
        self.assertEqual(_texts(obj)[-1], 'wieloliniowe')


class WhatBackspaceTookAway(unittest.TestCase):

    def snap(self, text, caret, whole=True):
        return {'text': text, 'caret': caret, 'whole': whole}

    def test_a_character(self):
        self.assertEqual(editable_text.removed_text(
            self.snap('kota', 4), self.snap('kot', 3)), 'a')

    def test_a_word(self):
        self.assertEqual(editable_text.removed_text(
            self.snap('Ala ma kota', 11), self.snap('Ala ma ', 7)), 'kota')

    def test_a_character_in_the_middle(self):
        self.assertEqual(editable_text.removed_text(
            self.snap('kkot', 2), self.snap('kot', 1)), 'k')

    def test_a_line_break_in_a_whole_text(self):
        self.assertEqual(editable_text.removed_text(
            self.snap('ab\r\ncd', 4), self.snap('abcd', 2)), '\r\n')

    def test_a_line_break_between_two_lines(self):
        self.assertEqual(editable_text.removed_text(
            self.snap('cd\r', 0, False), self.snap('abcd\r', 2, False)),
            '\n')

    def test_nothing_went(self):
        self.assertIsNone(editable_text.removed_text(
            self.snap('abc', 0), self.snap('abc', 0)))
        self.assertIsNone(editable_text.removed_text(
            self.snap('ab', 2), self.snap('abc', 3)))


class _Engine:
    def __init__(self, obj):
        self.settings = get_settings()
        # A letter as itself, not "Adam" - the setting is the user's, and
        # the arrows follow it the same way.
        self.settings.phonetic_letters = False
        self.current_object = obj
        self.said = []

    def speak(self, text, **_k):
        self.said.append(text)

    def play(self, *_a, **_k):
        pass

    def submit_action(self, fn):
        fn()

    class sound:
        @staticmethod
        def play_tone(*_a, **_k):
            pass


@unittest.skipUnless(IS_WINDOWS, 'real Win32 edit windows')
class ARealWin32EditField(unittest.TestCase):
    """A real EDIT window: its style says what it is, and Backspace and
    Delete are answered from its own text."""

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

    def edit(self, text, style=0):
        import ctypes
        hwnd = self.u.CreateWindowExW(0, 'EDIT', None, style, 0, 0, 200, 80,
                                      None, None, None, None)
        self.assertTrue(hwnd)
        self.windows.append(hwnd)
        buf = ctypes.create_unicode_buffer(text)
        self.u.SendMessageW(hwnd, 0x000C, 0, ctypes.addressof(buf))  # SETTEXT
        return hwnd

    def caret(self, hwnd, start, end=None):
        self.u.SendMessageW(hwnd, 0x00B1, start, start if end is None else end)

    def replace(self, hwnd, start, end, text=''):
        import ctypes
        self.caret(hwnd, start, end)
        buf = ctypes.create_unicode_buffer(text)
        self.u.SendMessageW(hwnd, 0x00C2, 1, ctypes.addressof(buf))  # REPLACESEL

    def obj(self, hwnd, **kw):
        return AccessibleObject(role='edit', name='Pole', class_name='Edit',
                                hwnd=int(hwnd), **kw)

    def test_the_style_says_several_lines(self):
        hwnd = self.edit('a', style=0x0004 | 0x0040)       # MULTILINE
        self.assertEqual(_texts(self.obj(hwnd))[-1], 'wieloliniowe')

    def test_the_style_says_read_only(self):
        hwnd = self.edit('a', style=0x0800)                 # READONLY
        self.assertEqual(_texts(self.obj(hwnd))[1:], ['Tekst',
                                                      'tylko do odczytu'])

    def test_a_plain_edit_is_one_line(self):
        hwnd = self.edit('a')
        self.assertEqual(edit_fields.shape(self.obj(hwnd)), ('edit', []))

    def handler(self, hwnd):
        engine = _Engine(self.obj(hwnd))
        handler = editable_text.EditableTextHandler(engine)
        handler.set_element(engine.current_object)
        return engine, handler

    def test_backspace_says_the_character_it_took(self):
        hwnd = self.edit('Ala ma kota')
        self.caret(hwnd, 11)
        engine, handler = self.handler(hwnd)
        before = handler.snapshot_before_key()
        self.replace(hwnd, 10, 11)                  # what the program does
        handler.read_deletion('backspace', False, before)
        self.assertEqual(engine.said[-1], 'a')

    def test_control_backspace_says_the_word(self):
        hwnd = self.edit('Ala ma kota')
        self.caret(hwnd, 11)
        engine, handler = self.handler(hwnd)
        before = handler.snapshot_before_key()
        self.replace(hwnd, 7, 11)
        handler.read_deletion('backspace', True, before)
        self.assertEqual(engine.said[-1], 'kota')

    def test_backspace_over_a_line_break_says_new_line(self):
        hwnd = self.edit('ab\r\ncd', style=0x0004 | 0x0040)
        self.caret(hwnd, 4)
        engine, handler = self.handler(hwnd)
        before = handler.snapshot_before_key()
        self.replace(hwnd, 2, 4)
        handler.read_deletion('backspace', False, before)
        self.assertEqual(engine.said[-1], 'nowa linia')

    def test_a_selection_deleted_is_said_whole(self):
        hwnd = self.edit('Ala ma kota')
        self.caret(hwnd, 0, 3)
        engine, handler = self.handler(hwnd)
        before = handler.snapshot_before_key()
        self.replace(hwnd, 0, 3)
        handler.read_deletion('backspace', False, before)
        self.assertEqual(engine.said[-1], 'Ala')

    def test_delete_says_what_the_caret_is_on_now(self):
        hwnd = self.edit('Ala')
        self.caret(hwnd, 0)
        engine, handler = self.handler(hwnd)
        before = handler.snapshot_before_key()
        self.replace(hwnd, 0, 1)
        handler.read_deletion('delete', False, before)
        self.assertEqual(engine.said[-1], 'l')

    def test_the_caret_baseline_is_taken_when_the_key_is_pressed(self):
        hwnd = self.edit('Ala ma kota')
        self.caret(hwnd, 0)
        engine, handler = self.handler(hwnd)
        self.caret(hwnd, 5)                         # moved by typing
        handler.note_caret_key()
        self.assertEqual(handler._last_win32_pos, 5)

    def test_backspace_at_the_start_says_the_edge_or_nothing(self):
        hwnd = self.edit('Ala')
        self.caret(hwnd, 0)
        engine, handler = self.handler(hwnd)
        engine.settings.announce_text_bounds = True
        handler.read_deletion('backspace', False,
                              handler.snapshot_before_key())
        self.assertEqual(engine.said, ['Początek'])
        engine.said[:] = []
        engine.settings.announce_text_bounds = False
        handler.read_deletion('backspace', False,
                              handler.snapshot_before_key())
        self.assertEqual(engine.said, [])
        engine.settings.announce_text_bounds = True


class WhatWasTypedIsWhatBackspaceTakes(unittest.TestCase):
    """UI Automation cannot be asked on the hook's thread: the line kept
    from the last read is behind what was typed since, and the hook's own
    record of the typing answers instead."""

    def test_a_stale_line_gives_way_to_the_typing(self):
        loc.set_language('pl')
        engine = _Engine(AccessibleObject(role='edit', name='Pole'))
        handler = editable_text.EditableTextHandler(engine)
        handler._snap = {'text': 'Ala', 'caret': 3, 'whole': False, 't': 0.0}
        handler.note_typed = lambda: None
        import time
        handler._typed_at = time.time()
        handler._snapshot_now = lambda: {'text': 'Ala ko', 'caret': 6,
                                         'whole': False, 't': time.time()}
        before = handler.snapshot_before_key()
        self.assertTrue(before['stale'])
        handler.read_deletion('backspace', False, before, typed='kot')
        self.assertEqual(engine.said[-1], 't')
        handler.read_deletion('backspace', True, before, typed='kot')
        self.assertEqual(engine.said[-1], 'kot')


class TheHookHandsDeletionsOver(unittest.TestCase):

    def hook(self, in_edit=True):
        from titan_access import keyboard_hook
        calls = []

        class Engine(object):
            def on_edit_delete(self, key, ctrl, typed=''):
                calls.append((key, ctrl, typed))

            def __getattr__(self, name):
                return lambda *a, **k: False
        hook = keyboard_hook.KeyboardHook.__new__(keyboard_hook.KeyboardHook)
        hook.engine = Engine()
        for name, value in (('_ctrl', False), ('_alt', False),
                            ('_shift', False), ('_reader_mod', False),
                            ('_mod_used', False), ('_ralt', False),
                            ('_word', list('kot')), ('_user32', None),
                            ('is_in_edit_field', in_edit),
                            ('is_in_browse_mode', False)):
            setattr(hook, name, value)
        hook._is_reader_modifier = lambda vk, extended: False
        hook._modifier_pressed = lambda name: None
        hook._command_pressed = lambda label: calls.append(('cmd', label))
        return hook, calls

    def test_backspace_in_a_field_is_reported_and_not_swallowed(self):
        hook, calls = self.hook()
        swallowed = hook._process(0x08, 0x0E, 0, True)
        self.assertFalse(swallowed)
        self.assertEqual(calls, [('backspace', False, 'kot')])
        self.assertEqual(hook._word, list('ko'))

    def test_delete_in_a_field_is_not_said_as_a_command(self):
        hook, calls = self.hook()
        hook._process(0x2E, 0x53, 0x01, True)        # extended Delete
        self.assertEqual(calls, [('delete', False, 'kot')])

    def test_outside_a_field_nothing_is_reported(self):
        hook, calls = self.hook(in_edit=False)
        hook._process(0x08, 0x0E, 0, True)
        self.assertNotIn(('backspace', False, 'kot'), calls)


if __name__ == '__main__':
    unittest.main(verbosity=1)
