# -*- coding: utf-8 -*-
"""A walked list says its parts with the reader's pause, the reader menu
says "Titan Access" (pause) "menu", a menu opened on its container puts
the keyboard on its first item, and the reader's shortcut is a hotkey
field.

No window, no sound, no speech: the speech adapter is a recorder and the
key the reader would press is recorded instead of pressed.

Run directly: ``python tests/test_titan_access_pauses_and_menus.py``.
"""

import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

# A store of the test's own: nothing here may write the user's settings.
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_pauses_')


class _Adapter(object):
    """The speech adapter, recording what it is asked for."""

    def __init__(self):
        self.calls = []

    def speak_segments(self, segments, gap_ms=0):
        self.calls.append(('segments', [s[0] for s in segments], True))

    def _enqueue(self, utterance, interrupt):
        texts = [s[0] for s in (utterance.segments or [])] or [utterance.text]
        self.calls.append(('segments' if utterance.segments else 'text',
                           texts, interrupt))

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0,
              voice=None):
        self.calls.append(('text', [text], interrupt))


class AWalkedRowIsSaidInPartsWithAPause(unittest.TestCase):

    def setUp(self):
        from titan_access import speech_adapter
        from titan_access.portable import compat
        self.speech_adapter, self.compat = speech_adapter, compat
        self.adapter = _Adapter()
        self._old = speech_adapter._current
        speech_adapter._current = self.adapter
        compat._Ui.last_message = 0.0

    def tearDown(self):
        self.speech_adapter._current = self._old

    def test_a_row_is_separate_parts_not_one_comma_line(self):
        from titan_access.portable import elements
        sequence = elements.sequence([('OK', 'name'), ('przycisk', 'kind'),
                                      ('2 z 5', 'place')])
        self.assertEqual(list(sequence), ['OK', 'przycisk', '2 z 5'])
        self.compat.speech.speak(sequence)
        kind, texts, interrupt = self.adapter.calls[-1]
        self.assertEqual(kind, 'segments')
        self.assertEqual(texts, ['OK', 'przycisk', '2 z 5'])
        self.assertTrue(interrupt)
        self.assertNotIn('OK, przycisk', ' '.join(texts))

    def test_the_kind_is_lower_than_the_name(self):
        from titan_access.portable import elements
        sequence = elements.sequence([('OK', 'name'), ('przycisk', 'kind')])
        name, kind = sequence.segments
        self.assertLess(kind[1], name[1])

    def test_plain_strings_are_parts_too(self):
        self.compat.speech.speak(['Pierwszy', 'drugi'])
        self.assertEqual(self.adapter.calls[-1][:2],
                         ('segments', ['Pierwszy', 'drugi']))

    def test_a_row_after_a_title_follows_it_rather_than_cutting_it(self):
        from titan_access.portable import elements
        self.compat.ui.message('Paleta')
        self.compat.speech.speak(elements.sequence([('OK', 'name'),
                                                    ('przycisk', 'kind')]))
        self.assertEqual(self.adapter.calls[0], ('text', ['Paleta'], True))
        self.assertEqual(self.adapter.calls[1],
                         ('segments', ['OK', 'przycisk'], False))

    def test_the_voices_shim_is_what_the_walked_lists_find(self):
        from titan_access.portable import voices, classes
        self.assertTrue(callable(voices.speak_sequence))
        self.assertEqual(voices.VOICES.get('kind'), classes.SHIPPED['kind'])
        self.assertFalse(voices.say_whole('notification', 'x'))

    def test_the_palette_row_reaches_the_reader_as_parts(self):
        from titan_access.portable import palette, voices
        old_queue = self.compat.queueHandler
        self.compat.queueHandler = None          # say it now, not on wx
        try:
            palette._say_parts([('Ustawienia', 'name'), ('pozycja', 'kind')])
        finally:
            self.compat.queueHandler = old_queue
        self.assertEqual(self.adapter.calls[-1][:2],
                         ('segments', ['Ustawienia', 'pozycja']))


class _Settings(object):
    def get_bool(self, _section, _key, default=True):
        return default


class _Engine(object):
    def __init__(self, host=0):
        self.settings = _Settings()
        self._menu_host_hwnd = host
        self.parts = []
        self.played = []

    def speak_segments(self, parts, gap_ms=None):
        self.parts.append([p[0] for p in parts])

    def speak(self, text, obj=None, interrupt=True, pitch_offset=0):
        self.parts.append([text])

    def play(self, name, obj=None):
        self.played.append(name)

    def post_to_worker(self, fn):
        fn()


class _Obj(object):
    def __init__(self, role, name, native=None):
        self.role, self.name, self.native = role, name, native


class TheReaderMenuAndMenusOpeningOnTheirContainer(unittest.TestCase):

    def _tracker(self, engine, menu_id=('m', 1), is_container=None):
        from titan_access import menu_tracker
        tracker = menu_tracker.MenuTracker(engine)
        tracker._in_menu_bar = lambda ctrl: False
        tracker._is_top_level_menu = lambda ctrl: False
        tracker._menu_parent = lambda ctrl: 'MENU'
        tracker._menu_id = lambda menu: menu_id
        tracker._name = lambda menu: 'Plik'
        tracker._count_items = lambda menu: 3
        tracker._segments = lambda obj: [(obj.name, 0), ('element menu', -4)]
        return tracker

    def test_the_reader_menu_says_titan_access_pause_menu(self):
        from titan_access.localization import L
        engine = _Engine(host=1234)
        tracker = self._tracker(engine)
        tracker._can_select_first = lambda: False
        tracker.handle_focus(_Obj('menuitem', 'Ustawienia'))
        self.assertEqual(engine.parts[-1][:2],
                         [L('readerMenu.titleName'), L('readerMenu.titleKind')])
        self.assertEqual(L('readerMenu.titleName'), 'Titan Access')
        self.assertEqual(engine.parts[-1][2], 'Ustawienia')

    def test_a_menu_opened_on_its_container_selects_its_first_item(self):
        from titan_access import keyboard_hook
        pressed = []
        old = keyboard_hook.pass_key
        keyboard_hook.pass_key = lambda vk: pressed.append(vk) or True
        try:
            engine = _Engine(host=1234)
            tracker = self._tracker(engine)
            tracker._can_select_first = lambda: True
            tracker.SELECT_AFTER_S = 0.01
            tracker.FALLBACK_AFTER_S = 5
            self.assertTrue(tracker.handle_focus(_Obj('menu', 'Menu')))
            self.assertEqual(engine.parts, [])      # nothing said yet
            time.sleep(0.15)
            self.assertEqual(pressed, [0x28])       # Down, for the user
            # The first item is focused: the opening is said with it.
            self.assertTrue(tracker.handle_focus(_Obj('menuitem', 'Ustawienia')))
            self.assertEqual(engine.parts[-1],
                             ['Titan Access', 'menu', 'Ustawienia',
                              'element menu'])
        finally:
            keyboard_hook.pass_key = old

    def test_a_menu_that_selects_itself_is_not_pushed_past_its_first_item(self):
        from titan_access import keyboard_hook
        pressed = []
        old = keyboard_hook.pass_key
        keyboard_hook.pass_key = lambda vk: pressed.append(vk) or True
        try:
            engine = _Engine()
            tracker = self._tracker(engine)
            tracker._can_select_first = lambda: True
            tracker.SELECT_AFTER_S = 0.2
            tracker.FALLBACK_AFTER_S = 5
            tracker.handle_focus(_Obj('menu', 'Menu'))
            tracker.handle_focus(_Obj('menuitem', 'Otwórz'))
            time.sleep(0.3)
            self.assertEqual(pressed, [])
            self.assertEqual(engine.parts[-1][0], 'Plik')
            self.assertIn('Otwórz', engine.parts[-1])
        finally:
            keyboard_hook.pass_key = old

    def test_an_ordinary_menu_is_parts_not_a_comma_line(self):
        engine = _Engine()
        tracker = self._tracker(engine)
        tracker._can_select_first = lambda: False
        tracker.handle_focus(_Obj('menuitem', 'Nowy'))
        said = engine.parts[-1]
        self.assertEqual(said[0], 'Plik')
        self.assertEqual(len(said), 5)              # name, menu, count, item, kind
        self.assertFalse(any(', ' in part for part in said))


class TheReadersShortcutIsAHotkeyField(unittest.TestCase):

    def test_the_default_is_control_shift_t(self):
        from titan_access import hotkeys, settings_schema
        found = settings_schema.find('General', 'ToggleHotkey')
        self.assertEqual(found.kind, 'hotkey')
        self.assertEqual(found.default, 'ctrl+shift+t')
        self.assertEqual(hotkeys.current(), 'ctrl+shift+t')
        self.assertEqual(hotkeys.parse('ctrl+shift+t'),
                         (hotkeys.MOD_CONTROL | hotkeys.MOD_SHIFT, 0x54))

    def test_written_in_any_order_and_said_in_words(self):
        from titan_access import hotkeys
        self.assertEqual(hotkeys.normalize('Shift + Ctrl+T'), 'ctrl+shift+t')
        self.assertEqual(hotkeys.spoken('alt+f5'), 'Alt+F5')
        self.assertEqual(hotkeys.normalize('t'), '')       # no modifier
        self.assertEqual(hotkeys.normalize('f9'), 'f9')    # a function key
        self.assertEqual(hotkeys.normalize('ctrl+a+b'), '')

    def test_enter_in_the_walk_takes_the_next_combination(self):
        from titan_access import hotkeys, settings_walk
        entry = [e for e in settings_walk.SCHEMA[1][2]
                 if e[1] == 'ToggleHotkey'][0]
        written = []
        old_set, old_label = settings_walk.set_value, settings_walk._row_label
        settings_walk.set_value = lambda e, v, engine=None: written.append(v)
        settings_walk._row_label = lambda e, engine=None: 'Skrót'
        old_held = hotkeys._held
        hotkeys._held = lambda vk: vk in (0x11, 0x12)        # Control+Alt
        try:
            ok, said = settings_walk._change(None, 'general', entry, {})
            self.assertTrue(ok)
            self.assertTrue(hotkeys.capturing())
            self.assertIsNone(hotkeys.capture_key(0x11, True))   # a modifier
            self.assertTrue(hotkeys.capture_key(0x52, True))     # R: taken
            self.assertTrue(hotkeys.capture_key(0x52, False))    # and its up
            time.sleep(0.1)
            self.assertEqual(written, ['ctrl+alt+r'])
            self.assertFalse(hotkeys.capturing())
            self.assertIsNone(hotkeys.capture_key(0x52, True))   # not ours now
        finally:
            settings_walk.set_value, settings_walk._row_label = old_set, old_label
            hotkeys._held = old_held
            hotkeys.cancel_capture()

    def test_escape_leaves_it_as_it_was(self):
        from titan_access import hotkeys
        got = []
        old_held = hotkeys._held
        hotkeys._held = lambda vk: False
        try:
            hotkeys.begin_capture(got.append)
            self.assertTrue(hotkeys.capture_key(0x1B, True))
            time.sleep(0.1)
            self.assertEqual(got, [None])
            self.assertFalse(hotkeys.capturing())
        finally:
            hotkeys._held = old_held
            hotkeys.cancel_capture()

    def test_a_bare_letter_is_refused_and_it_goes_on_listening(self):
        from titan_access import hotkeys
        got = []
        old_held = hotkeys._held
        hotkeys._held = lambda vk: False
        try:
            hotkeys.begin_capture(got.append)
            hotkeys.capture_key(0x54, True)
            time.sleep(0.1)
            self.assertEqual(got, [''])
            self.assertTrue(hotkeys.capturing())
        finally:
            hotkeys._held = old_held
            hotkeys.cancel_capture()


if __name__ == '__main__':
    unittest.main()
