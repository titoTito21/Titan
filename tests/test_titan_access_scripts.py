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


class TheConditionsSayMoreThanIs(unittest.TestCase):

    def test_every_operator(self):
        found = ta_scripts._conditions(
            'name != "a" title not contains "Draft" name starts with "Nowy" '
            'id matches "^Btn\\d+$"')
        self.assertEqual(found, [('name', 'not', 'a'),
                                 ('title', 'not contains', 'draft'),
                                 ('name', 'starts', 'nowy'),
                                 ('id', 'matches', '^Btn\\d+$')])

    def test_they_are_tested(self):
        values = {'name': 'Nowy plik', 'id': 'Btn12', 'title': 'Poczta'}
        conditions = ta_scripts._conditions(
            'name starts with "nowy" id matches "^btn\\d+$" '
            'title not contains "szkic" name != "x"')
        self.assertTrue(ta_scripts._matches(conditions, values))
        self.assertFalse(ta_scripts._matches(
            ta_scripts._conditions('title not contains "poczta"'), values))

    def test_a_broken_pattern_matches_nothing(self):
        self.assertFalse(ta_scripts._test('matches', 'abc', '(['))


class TheReadersOwnStatements(unittest.TestCase):

    def test_each_becomes_one_titan_script_line(self):
        cases = {
            'beep 880 40': 'titan_access.beep frequency=880 duration=40',
            '  read focus': '  titan_access.read_aloud what="focus"',
            'jump previous heading':
                'titan_access.go_to kind="heading" backward=true',
            'press "Zapisz"': 'titan_access.click_element text="Zapisz"',
            'setting "rate" = 60':
                'titan_access.set_setting name="rate" value="60"',
            'pass': 'titan_access.pass_key key="{{key}}"',
            'command "sayAll"': 'titan_access.run_command name="sayAll"',
            'silence': 'titan_access.stop_speech',
        }
        for said, meant in cases.items():
            self.assertEqual(ta_scripts.translate(said, 1), (meant, ''), said)

    def test_titan_script_is_left_alone(self):
        for line in ('say "x"', 'read the screen aloud', 'set a = 1'):
            self.assertEqual(ta_scripts.translate(line, 1), (None, ''))

    def test_line_numbers_stay_the_files(self):
        _t, body, _p = ta_scripts.parse('when reader starts\nsay "a"\nbeep 440')
        self.assertTrue(body.splitlines()[2].startswith('titan_access.beep'))

    def test_a_script_of_statements_checks_clean(self):
        problems = ta_scripts.check(
            'when key "ctrl+shift+f12"\nbeep 880 40\nread focus\n'
            'jump heading\npress "Zapisz"\nsetting "rate" = 60\n'
            'label "{{name}}"\ncommand "sayAll"\nif name is empty\n'
            '    pass\nend\n')
        self.assertEqual(problems, [])

    def test_every_statement_is_documented_and_declared(self):
        names = ta_scripts.own_actions()
        text = ta_scripts.language_text('en')
        for _pattern, template, what in ta_scripts.STATEMENTS:
            self.assertIn(what, text)
        for line in ('beep 1 1', 'cue "x"', 'braille "x"', 'press "x"',
                     'jump link', 'read focus', 'scan on', 'setting "x" = 1',
                     'label "x"', 'pass', 'silence', 'command "x"',
                     'script "x"'):
            said, _why = ta_scripts.translate(line, 1)
            action = said.strip().split()[0].split('.')[1]
            self.assertIn(action, names, line)


class TimedAndNotifiedScripts(unittest.TestCase):

    def setUp(self):
        self.ran = []
        self.keep = ta_scripts.run
        ta_scripts.run = lambda script, **kw: self.ran.append(
            (script['name'], kw.get('extra')))

    def tearDown(self):
        ta_scripts.run = self.keep
        for name in os.listdir(ta_scripts.folder()):
            if name.startswith('timed') or name.startswith('noted'):
                os.remove(os.path.join(ta_scripts.folder(), name))
        ta_scripts.load()
        ta_scripts.stop_clock()

    def _write(self, name, text):
        with open(os.path.join(ta_scripts.folder(), name), 'w',
                  encoding='utf-8') as handle:
            handle.write(text)
        ta_scripts.load()

    def test_every_runs_on_its_interval(self):
        self._write('timed.tas', 'when every 30s\nsay "tick"\n')
        start = 1000000.0
        ta_scripts.tick(start)                      # schedules
        ta_scripts.tick(start + 10)
        self.assertEqual(self.ran, [])
        ta_scripts.tick(start + 31)
        self.assertEqual([n for n, _e in self.ran], ['timed'])

    def test_time_runs_once_a_day(self):
        self._write('timed2.tas', 'when time "07:30"\nsay "rano"\n')
        at = time.mktime((2026, 10, 6, 7, 30, 5, 0, 0, -1))
        ta_scripts.tick(at)
        ta_scripts.tick(at + 20)
        self.assertEqual([n for n, _e in self.ran], ['timed2'])

    def test_bad_times_are_named(self):
        for line in ('when every 1s', 'when every soon', 'when time "25:00"'):
            _t, _b, problems = ta_scripts.parse(line)
            self.assertTrue(problems and 'line 1' in problems[0], line)

    def test_a_notification_runs_with_its_text(self):
        self._write('noted.tas',
                    'when notification text contains "bateria"\n'
                    'say "{{text}}"\n')
        self.assertEqual(ta_scripts.on_notification('Słaba bateria', 'x'), 1)
        self.assertEqual(self.ran, [('noted', {'text': 'Słaba bateria'})])
        self.assertEqual(ta_scripts.on_notification('Pobrano', 'x'), 0)


class MoreVariablesAndRuleChanges(unittest.TestCase):

    def test_the_place_in_the_list_and_the_states(self):
        class Row(Obj):
            role = 'listitem'
            states = {'selected'}
            pos_in_set = 3
            size_of_set = 9
            level = 0
            bounds = (10, 20, 30, 40)
        more = ta_scripts._more_about(Row())
        self.assertEqual((more['index'], more['count']), ('3', '9'))
        self.assertIn('3', more['position'])
        self.assertIn('9', more['position'])
        self.assertTrue(more['states'])
        self.assertEqual((more['x'], more['y']), ('20', '30'))

    def test_prefix_suffix_and_sound(self):
        path = os.path.join(ta_scripts.folder(), 'rulesmore.tas')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('control role="button" name starts with "zap" '
                         'prefix "[" suffix "]" sound "edge"\n')
        ta_scripts.load()
        played = []

        class Player(Spoken):
            def play(self, name, obj=None):
                played.append(name)
        keep = ta_scripts._state.get('engine')
        ta_scripts._state['engine'] = Player()
        try:
            changed, say = ta_scripts.adjust(Obj())
        finally:
            ta_scripts._state['engine'] = keep
            os.remove(path)
            ta_scripts.load()
        self.assertEqual(changed.name, '[Zapisz]')
        self.assertEqual(say, '')
        self.assertEqual(played, ['edge'])


class TheReferenceIsTheReaders(unittest.TestCase):

    def test_the_readme_follows_the_language(self):
        path = os.path.join(ta_scripts.folder(), 'README.txt')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('Titan Access scripts\n====================\nold\n')
        ta_scripts.load()
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        self.assertIn('when notification', text)

    def test_a_readme_the_user_wrote_is_theirs(self):
        path = os.path.join(ta_scripts.folder(), 'README.txt')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('My own notes\n')
        ta_scripts.load()
        with open(path, encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'My own notes\n')
        os.remove(path)

    def test_polish(self):
        text = ta_scripts.language_text('pl')
        self.assertIn('Skrypty Titan Access', text)
        self.assertIn('pass - przepuść do programu', text)
        self.assertIn('when every 5m', text)        # the syntax is not translated



class Node(object):
    def __init__(self, name, role, value=''):
        self.name, self.role, self.value = name, role, value
        self.states, self.level, self.landmark = (), 0, ''
        self.landmark_start = self.link = False
        self.is_heading = role == 'heading'

    @property
    def text(self):
        return ('%s %s' % (self.name, self.value)).strip() if self.value \
            else self.name


class Doc(object):
    def __init__(self, nodes, title='Okno'):
        self.nodes, self.title, self.source = nodes, title, 'uia'


class WhatJawsAndNvdaScriptsDo(unittest.TestCase):
    """The instructions an application script needs: put the keyboard on a
    control, say one without going there, click a hot spot, wait for a
    window, read a region, watch a control for changes, a key only in one
    window. Driven against a document of their own - nothing is focused,
    clicked or read on the real desktop."""

    def setUp(self):
        self.actions = ta_scripts._actions_module()
        self.doc = Doc([Node('Zapisz', 'button'), Node('Suma', 'text', '12'),
                        Node('Gotowe', 'statusbar')])
        self.keep = (self.actions._document, self.actions._buffer,
                     self.actions._engine, self.actions._click_point,
                     self.actions._window_origin)
        self.actions._document = lambda window=0, refresh=False, \
            use_ai=False: self.doc
        self.focused, self.clicked = [], []
        test = self

        class Buffer(object):
            def focus_node(self, node):
                test.focused.append(node.name)
                return True

            def window_text(self, hwnd):
                return 'Zapisz jako'

            def foreground_hwnd(self):
                return 5
        self.actions._buffer = lambda: Buffer()
        self.spoken = Spoken()
        self.actions._engine = lambda require_running=True: self.spoken
        self.actions._click_point = lambda x, y, button='left', clicks=1: \
            self.clicked.append((x, y, button, clicks)) or True
        self.actions._window_origin = lambda window=0: (100, 200)

    def tearDown(self):
        (self.actions._document, self.actions._buffer, self.actions._engine,
         self.actions._click_point, self.actions._window_origin) = self.keep

    def test_focus_puts_the_keyboard_on_the_control(self):
        said = self.actions.action_focus_element(text='zapisz', kind='button')
        self.assertEqual(self.focused, ['Zapisz'])
        self.assertIn('Zapisz', str(said))

    def test_read_control_says_it_without_moving(self):
        said = self.actions.action_read_control(text='Suma')
        self.assertEqual(self.focused, [])
        self.assertIn('12', said)
        self.assertEqual(len(self.spoken.said), 1)
        self.assertIn('Gotowe',
                      self.actions.action_read_control(kind='statusbar'))

    def test_a_hot_spot_is_from_the_windows_corner(self):
        self.actions.action_click_at(x=10, y=20)
        self.actions.action_click_at(x=10, y=20, button='right',
                                     relative='screen')
        self.assertEqual(self.clicked, [(110, 220, 'left', 1),
                                        (10, 20, 'right', 1)])

    def test_waiting_ends_when_it_is_there_and_says_when_it_is_not(self):
        self.assertIn('Zapisz jako',
                      str(self.actions.action_wait_for(window_title='zapisz')))
        missing = self.actions.action_wait_for(text='Nie ma', seconds=0.3)
        self.assertIn('did not appear', str(missing))

    def test_a_watched_control_runs_its_script_when_it_changes(self):
        ran = []
        keep = ta_scripts.run
        ta_scripts.run = lambda script, **kw: ran.append(kw.get('extra'))
        try:
            with open(os.path.join(ta_scripts.folder(), 'watched.tas'), 'w',
                      encoding='utf-8') as handle:
                handle.write('when change name="Suma"\nsay "{{text}}"\n')
            ta_scripts.load()
            ta_scripts._clock['seen'] = {}
            ta_scripts.tick(1000.0)               # where the watch starts
            ta_scripts.tick(1001.0)
            self.assertEqual(ran, [])
            self.doc.nodes[1].value = '15'
            ta_scripts.tick(1002.0)
            self.assertEqual(ran, [{'text': 'Suma 15', 'old': 'Suma 12'}])
        finally:
            ta_scripts.run = keep
            os.remove(os.path.join(ta_scripts.folder(), 'watched.tas'))
            ta_scripts.load()
            ta_scripts.stop_clock()

    def test_a_key_with_conditions_is_the_programs_elsewhere(self):
        ran = []
        keep = ta_scripts.run, ta_scripts._window_and_program
        ta_scripts.run = lambda script, **kw: ran.append(script['name'])
        try:
            with open(os.path.join(ta_scripts.folder(), 'inbox.tas'), 'w',
                      encoding='utf-8') as handle:
                handle.write('when key "f5" title contains "Inbox"\n'
                             'say "odswiez"\n')
            ta_scripts.load()
            ta_scripts._window_and_program = lambda: ('Notatnik', 'notepad')
            self.assertFalse(ta_scripts.plain_key('f5', False, False, False))
            ta_scripts._window_and_program = lambda: ('Inbox - Poczta', 'x')
            self.assertTrue(ta_scripts.plain_key('f5', False, False, False))
            self.assertEqual(ran, ['inbox'])
        finally:
            ta_scripts.run, ta_scripts._window_and_program = keep
            os.remove(os.path.join(ta_scripts.folder(), 'inbox.tas'))
            ta_scripts.load()

    def test_the_new_lines_are_titan_script_the_checker_accepts(self):
        text = ('when key "insert+k"\nfocus button "Zapisz"\n'
                'read control "Suma"\nread control statusbar\n'
                'read region 1 2 30 40\nclick double 5 6\n'
                'wait for window "Zapisz jako" 5s\n'
                'set total = titan_access.read_control text="Suma" '
                'speak=false\nsay "{{total}}"\n')
        self.assertEqual(ta_scripts.check(text), [])
        problems = ta_scripts.check('when change\nsay "x"\n')
        self.assertTrue(problems and 'line 1' in problems[0])

    def test_the_reference_names_every_new_instruction(self):
        text = ta_scripts.language_text('en')
        for word in ('focus "Save"', 'read control', 'read region',
                     'click 120 300', 'wait for window', 'when change',
                     '{{old}}' if '{{old}}' in text else 'old'):
            self.assertIn(word, text)


if __name__ == '__main__':
    unittest.main()
