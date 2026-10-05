# -*- coding: utf-8 -*-
"""TA scripts: the user's own reader scripts in Titan Script.

Run directly: ``python tests/test_titan_access_scripts.py``. Nothing speaks,
opens a window or presses a key; the scripts folder is a temporary one.
"""

import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'titan access')
for path in (ROOT, COMPONENT):
    if path not in sys.path:
        sys.path.insert(0, path)
HOME = tempfile.mkdtemp(prefix='ta_scripts_')
os.environ['APPDATA'] = HOME

from titan_access import ta_scripts                        # noqa: E402
from titan_access.portable import readerHome               # noqa: E402

readerHome.folder = lambda: os.path.join(HOME, 'accessibility')


class Spoken(object):
    def __init__(self):
        self.said = []

    def speak(self, text, interrupt=False):
        self.said.append(str(text))


class Obj(object):
    name = 'Zapisz'
    role = 'button'
    value = ''
    description = ''


class TheFolderIsTheUsers(unittest.TestCase):

    def test_it_is_made_with_an_example(self):
        where = ta_scripts.folder()
        self.assertTrue(where.startswith(HOME))
        self.assertTrue(os.path.isfile(os.path.join(where, 'example.tas')))
        self.assertTrue(os.path.isfile(os.path.join(where, 'README.txt')))


class TheTriggersAreTheReaders(unittest.TestCase):

    def test_reader_triggers_come_out_and_lines_keep_their_numbers(self):
        triggers, body, problems = ta_scripts.parse(
            'when key "insert+j"\nwhen focus program="notepad" role="edit"\n'
            'say "hi"')
        self.assertEqual([t['kind'] for t in triggers], ['key', 'focus'])
        self.assertEqual(body.splitlines()[2], 'say "hi"')
        self.assertEqual(problems, [])
        self.assertEqual(triggers[1]['conditions'],
                         [('program', False, 'notepad'),
                          ('role', False, 'edit')])

    def test_contains(self):
        triggers, _body, _p = ta_scripts.parse(
            'when window title contains "Pobrane"')
        self.assertEqual(triggers[0]['conditions'],
                         [('title', True, 'pobrane')])

    def test_a_bad_key_line_is_named(self):
        _t, _b, problems = ta_scripts.parse('when key insert+j')
        self.assertTrue(problems and 'line 1' in problems[0])

    def test_keys_are_compared_in_one_spelling(self):
        self.assertEqual(ta_scripts._normalise('Shift+NVDA+J'),
                         'insert+shift+j')
        self.assertEqual(ta_scripts._spec('f12', True, False, True, False),
                         'ctrl+shift+f12')

    def test_the_example_checks_clean(self):
        self.assertEqual(ta_scripts.check(ta_scripts.EXAMPLE), [])

    def test_a_titan_script_mistake_is_reported(self):
        problems = ta_scripts.check('when reader starts\nnosuch.action x="1"')
        self.assertTrue(problems)


class AScriptRunsInTheReadersVoice(unittest.TestCase):

    def test_variables_and_say(self):
        engine = Spoken()
        path = os.path.join(ta_scripts.folder(), 'hello.tas')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('when key "insert+shift+h"\n'
                         'say "{{name}}, {{role_key}}"\n')
        ta_scripts.load()
        script = ta_scripts.by_name('hello')
        self.assertIsNotNone(script)
        engine.current_object = Obj()
        ok, why = ta_scripts.run(script, engine=engine, wait=True)
        self.assertTrue(ok, why)
        self.assertEqual(engine.said, ['Zapisz, button'])

    def test_a_focus_trigger_matches_by_role(self):
        engine = Spoken()
        path = os.path.join(ta_scripts.folder(), 'onbutton.tas')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('when focus role="button"\nsay "a button"\n')
        ta_scripts.load()
        ta_scripts.on_focus(Obj(), engine)
        for _ in range(50):
            if engine.said:
                break
            time.sleep(0.05)
        self.assertIn('a button', engine.said)


class AKeyWithTheModifierGoesInFront(unittest.TestCase):

    def test_bind_puts_the_script_first(self):
        from titan_access.gestures import GestureManager
        engine = Spoken()
        engine.gestures = GestureManager(engine)
        engine.gestures.register('readElementType', 'shift+j', lambda: None)
        path = os.path.join(ta_scripts.folder(), 'first.tas')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('when key "insert+shift+j"\nsay "mine"\n')
        ta_scripts.bind(engine)
        first = engine.gestures._bindings[0]
        self.assertTrue(first.action_id.startswith('script:'))
        self.assertTrue(first.matches('j', False, False, True))


class ControlRulesLikeJawsScripts(unittest.TestCase):
    """Reclass a control, name it, say it your own way, or silence it."""

    def setUp(self):
        self.keep = ta_scripts._foreground_process
        ta_scripts._foreground_process = lambda: 'myapp'
        self.keep_wp = ta_scripts._window_and_program
        ta_scripts._window_and_program = lambda: ('Okno', 'myapp')

    def tearDown(self):
        ta_scripts._foreground_process = self.keep
        ta_scripts._window_and_program = self.keep_wp
        for name in os.listdir(ta_scripts.folder()):
            if name.startswith('rules'):
                os.remove(os.path.join(ta_scripts.folder(), name))
        ta_scripts.load()

    def _write(self, text, name='rules.tas'):
        with open(os.path.join(ta_scripts.folder(), name), 'w',
                  encoding='utf-8') as handle:
            handle.write(text)
        ta_scripts.load()

    def _grid(self):
        class Grid:
            name = ''
            role = 'pane'
            value = '3 rows'
            description = ''
            class_name = 'TCustomGrid'
            automation_id = 'grid1'
        return Grid()

    def test_reclass_and_name(self):
        self._write('for program "myapp.exe"\n'
                    'control class="TCustomGrid" as list name "Orders"\n')
        grid = self._grid()
        changed, say = ta_scripts.adjust(grid)
        self.assertEqual((changed.role, changed.name), ('list', 'Orders'))
        self.assertEqual(say, '')
        self.assertEqual(grid.role, 'pane')     # the real one is untouched

    def test_a_custom_announcement_with_variables(self):
        self._write('control id="grid1" say "Orders: {{value}}"\n')
        _changed, say = ta_scripts.adjust(self._grid())
        self.assertEqual(say, 'Orders: 3 rows')

    def test_silent(self):
        self._write('control class contains "grid" silent\n')
        _changed, say = ta_scripts.adjust(self._grid())
        self.assertIsNone(say)

    def test_another_program_is_not_touched(self):
        self._write('for program "other"\ncontrol id="grid1" as list\n')
        changed, _say = ta_scripts.adjust(self._grid())
        self.assertEqual(changed.role, 'pane')

    def test_an_unknown_role_is_refused_by_line(self):
        self._write('control id="grid1" as wibble\n')
        script = ta_scripts.by_name('rules')
        self.assertTrue(script['problems'])
        self.assertIn('line 1', script['problems'][0])

    def test_a_rule_without_selectors_is_refused(self):
        _t, _b, problems = ta_scripts.parse('control as list')
        self.assertTrue(problems)

    def test_rules_alone_are_a_valid_script(self):
        problems = ta_scripts.check('for program "x"\ncontrol id="a" as button')
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main()
