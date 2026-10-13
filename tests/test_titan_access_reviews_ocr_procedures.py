# -*- coding: utf-8 -*-
"""Escape in the application and widget reviews, a menu item that lands in
the window it opened, OCR readings whose lines press what they were read
from (Enter and NumPad 5), procedures that record presses, typing and keys
in both readers, and a name the user typed winning when a control is read.

Run directly: python tests/test_titan_access_reviews_ocr_procedures.py.
Nothing is spoken, shown, pressed or clicked; Titan is not asked.
"""

import os
import sys
import tempfile
import threading
import types
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='titan_ta_reviews_')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'titan access')
ADDON = os.path.join(ROOT, 'nvda-addon', 'addon', 'globalPlugins',
                     'titanEnhancements')
sys.path.insert(0, ROOT)
sys.path.insert(0, COMPONENT)

from titan_access.portable import (appReview, widgetReview, palette,  # noqa
                                   procedures, titan, icons)


class _Now(object):
    """A thread that runs its work at once, so a test sees the result."""

    def __init__(self, target=None, name=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


class _Quiet(unittest.TestCase):
    """Every module's voice and sounds replaced, and its threads run now."""

    MODULES = (appReview, widgetReview)

    def setUp(self):
        self.kept = []
        self.said = []
        self.calls = []
        for module in self.MODULES:
            self._swap(module, 'threading', types.SimpleNamespace(
                Thread=_Now, RLock=threading.RLock))
            self._swap(module, '_say',
                       lambda text, *a, **k: self.said.append(str(text)))
        self._swap(appReview, 'say_here', lambda *a, **k: (True, ''))
        self._swap(widgetReview, 'say_here', lambda *a, **k: (True, ''))
        self._swap(icons, 'play', lambda *a, **k: True)
        for name in ('press_described', 'key_described', 'close_described',
                     'set_described', 'close_widget', 'read_widget'):
            self._swap(titan, name, self._recorder(name))

    def _recorder(self, name):
        def call(*args, **kwargs):
            self.calls.append((name,) + args)
            answer = getattr(self, 'answer', None)
            return True, (answer if name != 'read_widget' else 'Głośność')
        return call

    def _swap(self, module, name, value):
        self.kept.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    def tearDown(self):
        for module, name, value in reversed(self.kept):
            setattr(module, name, value)
        appReview.stop()
        widgetReview.stop()


def _application(screen):
    with appReview._LOCK:
        appReview._state.update({'on': True, 'session': 's1', 'name': 'tNotes',
                                 'screen': screen, 'at': 0, 'inner': 0,
                                 'menu': None, 'typing': None,
                                 'field': None})


MAIN = {'id': 'main', 'title': 'Notatki', 'modal': False,
        'menus': [{'id': 'file', 'label': 'Plik',
                   'items': [{'id': 'new', 'label': 'Nowa notatka'},
                             {'id': 'quit', 'label': 'Zakończ'}]}],
        'controls': [{'id': 'list', 'kind': 'list', 'label': 'Notatki',
                      'items': ['Jedna']}]}
DIALOG = {'id': 'new-note', 'title': 'Nowa notatka', 'modal': True,
          'controls': [{'id': 'title', 'kind': 'text', 'label': 'Tytuł'},
                       {'id': 'ok', 'kind': 'button', 'label': 'OK'}]}


class EscapeInTheApplicationReview(_Quiet):

    def test_escape_in_the_main_window_closes_the_application(self):
        _application(MAIN)
        on, said = appReview.escape()
        self.assertFalse(on)
        self.assertFalse(appReview.reviewing())
        self.assertIn(('close_described', 's1'), self.calls)

    def test_escape_in_a_sub_window_is_the_applications(self):
        _application(DIALOG)
        on, _said = appReview.escape()
        self.assertTrue(on)
        self.assertTrue(appReview.reviewing())
        self.assertIn(('key_described', 's1', 'escape'), self.calls)
        self.assertNotIn(('close_described', 's1'), self.calls)

    def test_escape_in_a_menu_closes_only_the_menu(self):
        _application(MAIN)
        appReview.activate()                       # the Plik row opens
        self.assertTrue(appReview.in_a_menu())
        on, _said = appReview.escape()
        self.assertTrue(on)
        self.assertFalse(appReview.in_a_menu())
        self.assertTrue(appReview.reviewing())

    def test_escape_in_a_field_gives_the_keys_back(self):
        _application(DIALOG)
        with appReview._LOCK:
            appReview._state['typing'] = {'id': 'title'}
        on, said = appReview.escape()
        self.assertTrue(on)
        self.assertFalse(appReview.typing_mode())
        self.assertTrue(appReview.reviewing())


class AMenuItemLandsInTheWindowItOpened(_Quiet):

    def test_the_menu_goes_and_the_dialog_is_walked_from_its_top(self):
        _application(MAIN)
        appReview.activate()                       # open Plik
        self.answer = {'screen': DIALOG}           # Nowa notatka opens one
        appReview.activate()                       # choose Nowa notatka
        self.assertIn(('press_described', 's1', 'new'), self.calls)
        self.assertFalse(appReview.in_a_menu())
        self.assertTrue(appReview.in_a_sub_window())
        self.assertEqual(appReview.here()['id'], 'title')
        self.assertTrue(any('Nowa notatka' in one for one in self.said))

    def test_with_nothing_opened_the_cursor_is_on_its_menu(self):
        _application(MAIN)
        appReview.activate()
        self.answer = {'screen': MAIN}
        appReview.move(1)                          # Zakończ
        appReview.activate()
        self.assertFalse(appReview.in_a_menu())
        self.assertEqual(appReview.here()['kind'], 'menu')


class EscapeInTheWidgetReview(_Quiet):

    def test_escape_leaves_and_closes_the_widget(self):
        widgetReview.start('quick_settings', 'Szybkie ustawienia')
        on, said = widgetReview.escape()
        self.assertFalse(on)
        self.assertFalse(widgetReview.reviewing())
        self.assertIn(('close_widget', 'quick_settings'), self.calls)

    def test_stop_alone_does_not_close_it(self):
        widgetReview.start('quick_settings')
        widgetReview.stop()
        self.assertNotIn(('close_widget', 'quick_settings'), self.calls)


class TitanClosesAWidget(unittest.TestCase):

    def test_widgets_close_runs_its_cleanup_and_forgets_it(self):
        from src.ui import main_window_actions as actions
        cleaned = []

        class Widget(object):
            def cleanup(self):
                cleaned.append(True)
        keep = (actions._widget_modules, actions.run_on_gui,
                dict(actions._widget_instances))
        try:
            actions._widget_modules = lambda: [
                ('quick', object(), {'name': 'Szybkie'})]
            actions.run_on_gui = lambda fn: (fn(), None)
            actions._widget_instances['quick'] = Widget()
            said = actions._widget_close(widget='Szybkie')
            self.assertEqual(cleaned, [True])
            self.assertNotIn('quick', actions._widget_instances)
            self.assertIn('Szybkie', said)
        finally:
            actions._widget_modules, actions.run_on_gui = keep[0], keep[1]
            actions._widget_instances.clear()
            actions._widget_instances.update(keep[2])

    def test_the_bridge_and_the_reader_name_the_call(self):
        from src.titan_core import bridge_api
        self.assertIn('widgets.close', bridge_api.CALLS)
        self.assertNotIn('widgets.close', bridge_api.READ_ONLY)
        self.assertIn('widgets.close', titan.ACTS)


class ARefusalIsASentenceNotAnException(unittest.TestCase):
    """Titan's bridge raises RuntimeError with a sentence for the user
    ("Titan has no main window open."); a reader must say the sentence,
    not "RuntimeError: ..." in front of it."""

    def test_the_bridge_answers_the_sentence(self):
        import json
        from src.titan_core import bridge_api

        def refuses(_args):
            raise RuntimeError('Titan has no main window open.')

        def breaks(_args):
            raise ValueError('bad')
        bridge_api.CALLS['test.refuses'] = refuses
        bridge_api.CALLS['test.breaks'] = breaks
        try:
            said = json.loads(bridge_api.bridge(json.dumps(
                {'call': 'test.refuses', 'args': {}})))
            broken = json.loads(bridge_api.bridge(json.dumps(
                {'call': 'test.breaks', 'args': {}})))
        finally:
            del bridge_api.CALLS['test.refuses'], bridge_api.CALLS['test.breaks']
        self.assertEqual(said['error'], 'Titan has no main window open.')
        self.assertEqual(broken['error'], 'ValueError: bad')

    def test_the_reader_drops_an_older_titans_prefix(self):
        from titan_access.portable import link
        self.assertEqual(link._plain('RuntimeError: Zdanie.'), 'Zdanie.')
        self.assertEqual(link._plain('ValueError: bad'), 'ValueError: bad')


class EveryProviderTitanImportsByNameIsFrozen(unittest.TestCase):
    """`actions/builtin.py` and `src/ai/tools/__init__.py` import their tool
    modules by NAME, which PyInstaller cannot see: the compiled Titan had
    no `ocr` provider at all, so the reader's AI OCR (read, ask, press)
    answered nothing there. Every such name must be in both hidden-import
    lists."""

    def test_each_is_a_hidden_import(self):
        import ast
        import re
        wanted = set()
        for name in (('src', 'titan_core', 'actions', 'builtin.py'),
                     ('src', 'ai', 'tools', '__init__.py')):
            with open(os.path.join(ROOT, *name), encoding='utf-8') as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(
                        node.value, str) and re.fullmatch(
                            r'src(\.\w+)+', node.value) and os.path.exists(
                                os.path.join(ROOT, *node.value.split('.'))
                                + '.py'):
                    wanted.add(node.value)
        self.assertIn('src.ai.tools.ocr_tools', wanted)
        for listed in ('compiletorelease.py', 'Titan.spec'):
            with open(os.path.join(ROOT, listed), encoding='utf-8') as f:
                text = f.read()
            missing = sorted(one for one in wanted
                             if ('"%s"' % one) not in text
                             and ("'%s'" % one) not in text)
            self.assertEqual(missing, [], listed)


class AReadingIsAPageWhoseLinesPress(unittest.TestCase):

    def setUp(self):
        self.shown = []
        self.keep = palette.show
        palette.show = lambda rows, title, **k: (
            self.shown.append(rows) or (True, title))

    def tearDown(self):
        palette.show = self.keep

    def test_a_line_with_an_action_runs_it_on_enter(self):
        ran = []
        palette.page('Tytuł\n\n  Zapisz, button',
                     act=lambda index, line: (
                         (lambda: ran.append(index) or (True, ''))
                         if line.startswith('  ') else None))
        rows = self.shown[-1]
        self.assertNotIn('run', rows[0])
        rows[1]['run']()
        self.assertEqual(ran, [2])                  # blank lines count

    def test_an_ai_reading_presses_its_elements_by_name(self):
        from titan_access.portable import commands
        self.assertIsNone(commands._ai_line_press(0, 'Okno zapisu'))
        self.assertIsNone(commands._ai_line_press(2, '[Przyciski]'))
        asked, said = [], []
        link = types.SimpleNamespace(run_action=lambda *a, **k: (
            asked.append(k['name']) or
            ((True, "There is no control called 'Zapisz, button'")
             if k['name'] == 'Zapisz, button' else (True, 'Pressed.'))))
        keep = (commands.LINK, commands._close_then, commands.dialogs.report)
        try:
            commands.LINK = link
            commands._close_then = lambda work: (work(), (True, ''))[1]
            commands.dialogs.report = lambda text, *a, **k: said.append(text)
            keep_play = icons.play
            icons.play = lambda *a, **k: True
            run = commands._ai_line_press(3, '  Zapisz, button')
            run()
            import time
            end = time.time() + 3
            while 'Pressed.' not in said and time.time() < end:
                time.sleep(0.02)
            icons.play = keep_play
        finally:
            commands.LINK, commands._close_then, commands.dialogs.report = keep
        self.assertEqual(asked, ['Zapisz'])
        self.assertIn('Pressed.', said)

    def _wait_for(self, condition):
        import time
        end = time.time() + 3
        while not condition() and time.time() < end:
            time.sleep(0.02)

    def _wait_for_the_click(self):
        import time
        from titan_access.portable import smart
        end = time.time() + 3
        while smart.waiting_click() and time.time() < end:
            time.sleep(0.02)
        self.assertFalse(smart.waiting_click())

    def test_twice_quickly_is_one_double_click(self):
        from titan_access.portable import smart
        keep = icons.play
        icons.play = lambda *a, **k: True
        done = []
        try:
            smart.press_twice('x', lambda: done.append('once') or (True, ''),
                              lambda: done.append('twice') or (True, ''),
                              report=None)
            smart.press_twice('x', lambda: done.append('once') or (True, ''),
                              lambda: done.append('twice') or (True, ''),
                              report=None)
            self.assertEqual(done, ['twice'])
            self.assertFalse(smart.waiting_click())
            smart.press_twice('y', lambda: done.append('once') or (True, ''),
                              lambda: done.append('twice') or (True, ''),
                              report=None)
            self.assertTrue(smart.waiting_click())
            self._wait_for(lambda: done == ['twice', 'once'])
            self.assertEqual(done, ['twice', 'once'])
        finally:
            icons.play = keep

    def test_a_press_on_something_else_sends_the_waiting_click_now(self):
        from titan_access.portable import smart
        keep = icons.play
        icons.play = lambda *a, **k: True
        done = []
        try:
            smart.press_twice('a', lambda: done.append('a') or (True, ''),
                              lambda: (True, ''), report=None)
            smart.press_twice('b', lambda: done.append('b') or (True, ''),
                              lambda: (True, ''), report=None)
            self.assertEqual(done, ['a'])
            self._wait_for(lambda: done == ['a', 'b'])
            self.assertEqual(done, ['a', 'b'])
        finally:
            icons.play = keep

    def test_numpad5_activates_in_every_walked_ocr_view(self):
        with open(os.path.join(ADDON, '__init__.py'), encoding='utf-8') as f:
            plugin = f.read()
        for gesture in ("'kb:numpad5': 'paletteActivate'",
                        "'kb:numpad5': 'smartPress'",
                        "'kb:numpad5': 'ocrClick'",
                        "'kb:numpad5': 'widgetPress'",
                        "'kb:numpad5': 'appActivate'"):
            self.assertIn(gesture, plugin)
        with open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                  encoding='utf-8') as f:
            engine = f.read()
        self.assertGreaterEqual(
            engine.count("('return', 'enter', 'numpad5')"), 5)


class TitansOcrPressClicksOnceOrTwice(unittest.TestCase):
    """The AI OCR path end to end on Titan's side: a reading made with
    Titan's own model, rendered to the lines the reader is handed
    (`elements_as_lines`), each element line turned into a name by the
    reader's parser and pressed through Titan's real `ocr.press` action -
    with only the mouse itself stood in for."""

    def setUp(self):
        from src.ai.ocr import model, actions
        from src.ai.tools import ocr_tools
        self.actions, self.tools = actions, ocr_tools
        shot = types.SimpleNamespace(
            centre_of=lambda rect: (int(rect[0] + rect[2] / 2),
                                    int(rect[1] + rect[3] / 2)))
        self.screen = model.Screen(
            title='Instalator', summary='Pierwszy krok.', capture=shot,
            regions=[model.Region(name='Przyciski', elements=[
                model.Element(name='Dalej', role='button',
                              rect=(100, 200, 80, 30)),
                model.Element(name='Plik.txt', role='listitem',
                              rect=(10, 50, 120, 20))])])
        self.clicks = []
        self.kept = []
        for module, name, value in (
                (actions, 'can_act', lambda: True),
                (actions, '_focus_target', lambda shot: None),
                (actions, '_check_point_belongs', lambda shot, x, y: None),
                (actions, '_click', lambda x, y, button='left',
                 restore_cursor=True, clicks=1:
                 self.clicks.append((x, y, clicks)))):
            self.kept.append((module, name, getattr(module, name)))
            setattr(module, name, value)
        with ocr_tools._lock:
            self.kept_last = ocr_tools._last['screen']
            ocr_tools._last['screen'] = self.screen

    def tearDown(self):
        for module, name, value in self.kept:
            setattr(module, name, value)
        with self.tools._lock:
            self.tools._last['screen'] = self.kept_last

    def _press_line(self, line, double):
        """What the reader's page does with a line: its parser picks the
        name, and the action is asked over the bus - arguments as STRINGS,
        the way they arrive there."""
        spoken = line.strip()
        names = [spoken.split(', ')[0].strip(), spoken]
        for name in names:
            said = self.tools.ocr_press(name=name,
                                        double='true' if double else 'false')
            if 'there is no control called' not in str(said).lower():
                return said
        return said

    def test_every_element_line_presses_its_own_element(self):
        from src.ai.ocr import model
        lines = [one for one in model.elements_as_lines(self.screen)
                 if one.startswith('  ')]
        self.assertEqual(len(lines), 2)
        said = self._press_line(lines[0], double=False)
        self.assertEqual(self.clicks, [(140, 215, 1)])
        self.assertIn('Pressed Dalej', said)
        said = self._press_line(lines[1], double=True)
        self.assertEqual(self.clicks[-1], (70, 60, 2))
        self.assertIn('Double-clicked Plik.txt', said)

    def test_double_is_on_the_actions_own_declaration(self):
        tool = [one for one in self.tools.get_ocr_tools()
                if one.get('name') == 'ocr_press']
        self.assertEqual(len(tool), 1)
        self.assertIn('double', tool[0]['parameters']['properties'])


class AProcedureRecordsWhatTheUserDid(unittest.TestCase):

    def setUp(self):
        procedures.cancel_recording()
        procedures.start_recording('Test')
        self.added = []
        self.keep = (procedures.note_press, procedures.note_key)
        procedures.note_press = lambda obj=None: self.added.append(
            ('press', obj)) or True
        procedures.note_key = lambda name: self.added.append(
            ('key', name)) or True

    def tearDown(self):
        procedures.note_press, procedures.note_key = self.keep
        procedures.cancel_recording()

    def _role(self, name):
        return types.SimpleNamespace(role=types.SimpleNamespace(name=name))

    def test_enter_on_a_button_is_a_press(self):
        button = self._role('BUTTON')
        procedures.note_keystroke('return', obj=button)
        self.assertEqual(self.added, [('press', button)])

    def test_enter_in_a_field_is_the_key(self):
        procedures.note_keystroke('enter', obj=self._role('EDITABLETEXT'))
        self.assertEqual(self.added, [('key', 'enter')])

    def test_typing_and_moving_are_not_keys(self):
        field = self._role('EDITABLETEXT')
        for key in ('a', 'space', 'down', 'tab', 'shift', 'numpad8'):
            procedures.note_keystroke(key, obj=field)
        self.assertEqual(self.added, [])

    def test_a_shortcut_is_a_key_in_nvdas_spelling(self):
        procedures.note_keystroke('s', ctrl=True, obj=self._role('BUTTON'))
        procedures.note_keystroke('pageup', ctrl=True, shift=True,
                                  obj=self._role('BUTTON'))
        procedures.note_keystroke('escape', obj=self._role('BUTTON'))
        self.assertEqual([one[1] for one in self.added],
                         ['control+s', 'control+shift+pageUp', 'escape'])

    def test_nothing_is_kept_when_not_recording(self):
        procedures.cancel_recording()
        procedures.note_keystroke('escape', obj=self._role('BUTTON'))
        self.assertEqual(self.added, [])

    def test_both_readers_feed_the_recorder(self):
        with open(os.path.join(ADDON, '__init__.py'), encoding='utf-8') as f:
            plugin = f.read()
        self.assertIn('procedures.note_keystroke(', plugin)
        self.assertIn('def event_typedCharacter', plugin)
        with open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                  encoding='utf-8') as f:
            engine = f.read()
        for call in ('procedures.note_keystroke(', 'procedures.note_typing(',
                     'procedures.note_focus('):
            self.assertIn(call, engine)


class ANameTheUserTypedWins(unittest.TestCase):

    def _describe(self, program_name, row):
        from titan_access import accessible
        from titan_access.settings_store import get_settings
        from titan_access.contracts import AccessibleObject
        obj = AccessibleObject(name=program_name, role='button',
                               class_name='Button', automation_id='save')
        keep = (accessible._custom_for, accessible._shared_label_for)
        try:
            accessible._custom_for = lambda o: {}
            accessible._shared_label_for = lambda o: row
            return ' '.join(text for text, *_rest in
                            accessible.describe(obj, get_settings()))
        finally:
            accessible._custom_for, accessible._shared_label_for = keep

    def test_a_typed_name_replaces_the_programs(self):
        self.assertIn('Zapisz plik',
                      self._describe('Zapisz', ('Zapisz plik', 'user')))

    def test_a_guessed_name_only_fills_a_nameless_control(self):
        said = self._describe('Zapisz', ('Zgadnięta', 'ai'))
        self.assertIn('Zapisz', said)
        self.assertNotIn('Zgadnięta', said)
        self.assertIn('Zgadnięta', self._describe('', ('Zgadnięta', 'ai')))

    def test_the_reader_asks_the_labels_store_first(self):
        from titan_access import shared_names
        from titan_access.portable import labels
        keep = labels._store
        try:
            labels._store = {'notatnik': {'Button|BUTTON|save': {
                'label': 'Zapisz plik', 'source': 'user'}}}
            self.assertEqual(shared_names.name_for(
                'notatnik', 'Button|BUTTON|save'), 'Zapisz plik')
        finally:
            labels._store = keep


if __name__ == '__main__':
    unittest.main()
