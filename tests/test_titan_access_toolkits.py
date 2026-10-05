# -*- coding: utf-8 -*-
"""Titan Access: the virtual window names a control as a real window does,
and a walked edit field really changes the real control - written the
way its TOOLKIT allows (`titan_access/toolkits/`, `portable/fieldWriter`).

Run directly: ``python tests/test_titan_access_toolkits.py``. Nothing here
opens a window or presses a key; `tests/probe_toolkit_fields.py` and
`tests/probe_virtual_typing.py` do that against real wx, WPF, Windows
Forms and Tkinter windows.
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'titan access')
for path in (ROOT, COMPONENT):
    if path not in sys.path:
        sys.path.insert(0, path)
os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_toolkits_')

from titan_access import localization, nvda_shape, toolkits   # noqa: E402
from titan_access.portable import (appReview, elements,       # noqa: E402
                                   fieldWriter, hostWindow, toolkit,
                                   virtualWindow)


class EveryToolkitHasAModuleAndOnePlan(unittest.TestCase):

    def test_every_known_framework_has_a_module(self):
        for framework in list(toolkit.WORDS) + ['']:
            one = toolkits.by_framework(framework)
            self.assertIsInstance(one, toolkits.Toolkit, framework)

    def test_the_modules_and_the_shared_plans_agree(self):
        for one in toolkits.ALL:
            for framework in one.FRAMEWORKS:
                self.assertIn(framework, fieldWriter.PLANS, framework)
                self.assertEqual(tuple(one.PLAN),
                                 fieldWriter.PLANS[framework], framework)

    def test_every_plan_ends_in_the_keys(self):
        for framework, plan in fieldWriter.PLANS.items():
            self.assertEqual(plan[-1], 'keys', framework)

    def test_the_named_toolkits_are_there(self):
        for framework, name in (('qt', 'Qt'), ('wpf', 'WPF'), ('tk', 'Tk'),
                                ('winforms', 'Windows Forms'),
                                ('java', 'Java'), ('gtk', 'GTK')):
            self.assertEqual(toolkits.by_framework(framework).NAME, name)

    def test_tk9_is_recognised_by_its_libraries(self):
        self.assertEqual(toolkit._by_library(['tcl9tk90.dll'])[0], 'tk')
        self.assertEqual(toolkit._by_library(['tcl90.dll', 'python314.dll'])
                         [0], 'tk')

    def test_a_web_field_is_written_with_keys(self):
        self.assertEqual(toolkits.by_framework('chromium').PLAN, ('keys',))

    def test_a_wpf_password_box_takes_keys(self):
        class Password:
            role = 'password'
        self.assertEqual(toolkits.by_framework('wpf').mode(Password()),
                         'keys')


class NamesAreTheRealWindowsNames(unittest.TestCase):

    def test_an_edit_field_is_called_what_the_reader_calls_one(self):
        word = localization.role_label('edit')
        self.assertEqual(elements.role_word('EDITABLETEXT'), word)
        self.assertEqual(appReview.kind_word('text'), word)

    def test_a_check_box_says_checked_and_unchecked(self):
        self.assertEqual(elements.state_word('CHECKED'),
                         localization.state_label('checked'))
        self.assertEqual(elements.state_word('UNCHECKED'),
                         localization.state_label('unchecked'))
        on = appReview.parts_of({'kind': 'check', 'label': 'X',
                                 'value': True})
        self.assertIn(localization.state_label('checked'),
                      [text for text, _cls in on])

    def test_the_settings_walk_uses_the_real_words(self):
        from titan_access import settings_walk
        self.assertEqual(settings_walk._kind_word('text'),
                         localization.role_label('edit'))
        self.assertEqual(settings_walk._kind_word('bool'),
                         localization.role_label('checkbox'))
        entry = ('S', 'K', 'label', 'bool', 'help', True, None)
        self.assertEqual(settings_walk.value_word(entry, True),
                         localization.state_label('checked'))
        self.assertEqual(settings_walk.value_word(entry, False),
                         localization.state_label('unchecked'))


class LocationIsNvdasShape(unittest.TestCase):

    def test_bounds_become_left_top_width_height(self):
        class Original:
            bounds = (100, 50, 300, 90)
        rect = nvda_shape.Adapted(Original()).location
        self.assertEqual(tuple(rect), (100, 50, 200, 40))


class _Obj(object):
    name = 'Name'
    value = 'abc'
    role = None


class AWalkedFieldReachesTheRealControl(unittest.TestCase):

    def setUp(self):
        self.keep = (virtualWindow.here, virtualWindow.focus_here,
                     virtualWindow._is_a_field, virtualWindow._say,
                     virtualWindow._say_field, virtualWindow.typing_mode)
        self.obj = _Obj()
        self.node = {'name': 'Name', 'role': 'EDITABLETEXT',
                     'obj': self.obj}
        virtualWindow.here = lambda: self.node
        virtualWindow.focus_here = lambda: (True, '')
        virtualWindow._is_a_field = lambda node: True
        virtualWindow._say = lambda *a, **k: None
        virtualWindow._say_field = lambda: None
        from titan_access.portable import readerApi
        self.readerApi = readerApi
        self.keep_hooks = readerApi.hooks
        self.written = []
        self.sent_keys = []
        test = self

        class Hooks:
            def field_mode(self, obj):
                return test.mode

            def set_text(self, obj, text, method):
                test.written.append((text, method))
                return test.accept

            def read_text(self, obj):
                return 'abc'

            def send_key(self, name):
                test.sent_keys.append(name)
                return True
        readerApi.hooks = Hooks()
        self.mode, self.accept = 'win32', True

    def tearDown(self):
        (virtualWindow.here, virtualWindow.focus_here,
         virtualWindow._is_a_field, virtualWindow._say,
         virtualWindow._say_field, virtualWindow.typing_mode) = self.keep
        self.readerApi.hooks = self.keep_hooks
        virtualWindow._state.update({'typing': False, 'field': None,
                                     'writer': '', 'on': False})

    def _enter(self):
        with virtualWindow._LOCK:
            virtualWindow._state['typing'] = False
            virtualWindow._state['on'] = True
        ok, _said = virtualWindow.enter_typing()
        self.assertTrue(ok)

    def test_a_provider_writes_the_whole_text(self):
        self._enter()
        self.assertEqual(virtualWindow.writer(), 'win32')
        sent = []
        virtualWindow.type_key('x', lambda: sent.append('x'))
        self.assertEqual(self.written[-1], ('abcx', 'win32'))
        self.assertEqual(sent, [])          # nothing reaches the control twice

    def test_a_character_is_inserted_as_typed(self):
        self._enter()
        virtualWindow.type_character('ż', lambda: None)
        self.assertEqual(self.written[-1][0], 'abcż')

    def test_a_refusal_turns_to_the_keys(self):
        self.accept = False
        self._enter()
        sent = []
        virtualWindow.type_key('x', lambda: sent.append('x'))
        self.assertEqual(sent, ['x'])
        self.assertEqual(virtualWindow.writer(), 'keys')

    def test_the_keys_writer_passes_every_edit_on(self):
        self.mode = 'keys'
        self._enter()
        self.assertIn('end', self.sent_keys)   # carets put in one place
        sent = []
        virtualWindow.type_key('x', lambda: sent.append('x'))
        virtualWindow.type_key('backspace', lambda: sent.append('bs'))
        self.assertEqual(sent, ['x', 'bs'])
        self.assertEqual(self.written, [])
        self.assertEqual(virtualWindow.field().text, 'abc')


class TheHostStepsAsideForTyping(unittest.TestCase):

    def test_lend_and_reclaim(self):
        keep = dict(hostWindow._state)
        try:
            hostWindow._state.update({'up': True, 'lent': False})
            self.assertTrue(hostWindow.lend())
            self.assertTrue(hostWindow.lent())
            hostWindow.reclaim()
            self.assertFalse(hostWindow.lent())
            hostWindow._state['lent'] = True
            hostWindow.hide()
            self.assertFalse(hostWindow.lent())
        finally:
            hostWindow._state.clear()
            hostWindow._state.update(keep)


class AltGrReachesAWalkedField(unittest.TestCase):

    def test_control_alt_is_let_through_only_while_typing(self):
        from titan_access.engine import TitanAccessEngine
        keep = (virtualWindow.reviewing, virtualWindow.typing_mode)
        try:
            virtualWindow.reviewing = lambda: True
            virtualWindow.typing_mode = lambda: True
            self.assertTrue(TitanAccessEngine._typing_in_a_walked_field())
            virtualWindow.typing_mode = lambda: False
            self.assertFalse(TitanAccessEngine._typing_in_a_walked_field())
        finally:
            virtualWindow.reviewing, virtualWindow.typing_mode = keep


class AProgramThatDrawsItsOwnControlsIsFollowed(unittest.TestCase):
    """Tkinter before Tk 9.1, GTK on Windows, Unity, Godot, SDL."""

    def setUp(self):
        from titan_access.portable import surface
        self.surface = surface
        self.keep = (surface.named_inside_client, toolkit.of)

    def tearDown(self):
        self.surface.named_inside_client, toolkit.of = self.keep

    def _window(self, framework, named, window_class='TkTopLevel'):
        self.surface.named_inside_client = lambda obj: named
        toolkit.of = lambda obj, again=False: (framework, 'library', '')

        class Window:
            windowClassName = window_class
            role = None
            children = []
        return Window()

    def test_tkinter_with_nothing_inside_is_drawn(self):
        window = self._window('tk', named=False)
        self.assertTrue(self.surface.drawn_by_toolkit(window))
        self.assertTrue(self.surface.looks_drawn(window))

    def test_tk_9_1_that_speaks_msaa_is_native(self):
        window = self._window('tk', named=True)
        self.assertFalse(self.surface.drawn_by_toolkit(window))

    def test_qt_and_wpf_are_never_drawn_by_toolkit(self):
        for framework in ('qt', 'wpf', 'winforms', 'wx'):
            self.assertFalse(self.surface.drawn_by_toolkit(
                self._window(framework, named=False)), framework)

    def test_a_unity_game_with_an_accessibility_tree_is_native(self):
        unity = [one for one in self.surface.DRAWN_CLASSES
                 if 'unity' in one.lower()]
        self.assertTrue(unity)
        self.assertFalse(self.surface.looks_drawn(
            self._window('unity', named=True, window_class=unity[0])))
        self.assertTrue(self.surface.looks_drawn(
            self._window('unity', named=False, window_class=unity[0])))


class ADrawnFieldIsReadAtItsCaret(unittest.TestCase):

    def test_the_character_at_the_caret(self):
        from titan_access.portable import guest
        line = [{'text': 'Imie:', 'left': 227, 'width': 65},
                {'text': 'Anna', 'left': 306, 'width': 83}]
        self.assertEqual(guest._character_at(line, 337), 'n')
        self.assertEqual(guest._character_at(line, 300),
                         guest._('space'))
        self.assertEqual(guest._character_at(line, 500), guest._('end'))

    def test_the_caret_keys_by_either_readers_names(self):
        from titan_access.portable import guest
        for name in ('leftArrow', 'left', 'home', 'downarrow'):
            key = guest.CARET_KEY_NAMES.get(name.lower(), name.lower())
            self.assertIn(key, guest.CARET_KEYS, name)


class TheRecogniserReadsWhatItIsAskedAbout(unittest.TestCase):

    def test_small_pictures_are_enlarged_and_large_ones_not(self):
        from titan_access import windows_ocr
        bits = bytes([1, 2, 3, 255]) * (10 * 5)
        factor, width, height, big = windows_ocr._enlarge(10, 5, bits)
        self.assertEqual((factor, width, height), (4, 40, 20))
        self.assertEqual(len(big), 40 * 20 * 4)
        self.assertEqual(big[:8], bytes([1, 2, 3, 255]) * 2)
        self.assertEqual(windows_ocr._enlarge(200, 150, b'')[0], 1)

    def test_a_rectangle_reaches_both_tiers(self):
        from titan_access.portable import localOcr
        from titan_access.portable import link as link_module
        asked = []
        keep = link_module.LINK.bridge

        def bridge(call, timeout=None, **args):
            asked.append((call, args))
            return True, {'ok': False, 'lines': []}
        link_module.LINK.bridge = bridge
        try:
            localOcr.read_window_titan(5, rect=(10, 20, 300, 40))
        finally:
            link_module.LINK.bridge = keep
        first = asked[0]
        self.assertEqual(first[0], 'ocr.read_windows')
        self.assertEqual((first[1]['left'], first[1]['top'],
                          first[1]['width'], first[1]['height']),
                         (10, 20, 300, 40))
        for call, args in asked:
            if call == 'ocr.read_local':
                self.assertEqual(args.get('height'), 40)

    def test_the_model_takes_a_rectangle(self):
        from titan_access import local_model
        seen = []
        keep = local_model.read_window
        local_model.read_window = lambda hwnd=0, rect=None: \
            seen.append(rect) or {'ok': True}
        try:
            local_model.call_read_local({'hwnd': 3, 'left': 1, 'top': 2,
                                         'width': 30, 'height': 4})
        finally:
            local_model.read_window = keep
        self.assertEqual(seen, [(1, 2, 30, 4)])

    def test_the_drawn_apps_switch_exists_in_both_readers(self):
        from titan_access import settings_panel
        from titan_access.portable import configSpec
        self.assertIn(('drawnApps', True), settings_panel.SHARED_SWITCHES)
        spec = os.path.join(ROOT, 'nvda-addon', 'addon', 'globalPlugins',
                            'titanEnhancements', 'configSpec.py')
        self.assertIn("'drawnApps': 'boolean(default=True)'",
                      open(spec, encoding='utf-8').read())
        self.assertTrue(configSpec is not None)


if __name__ == '__main__':
    unittest.main()
