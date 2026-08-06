# -*- coding: utf-8 -*-
"""
Regression tests for Titan Script (.TCS) macros and the writing of them.

The symptom these lock down: the AI asked for "count to ten, moving from the
left to the right and getting faster" produced a macro made of

    voice rate=100
    do "powiedz 1 z lewej strony (pozycja -1.0)" wait=true

which parsed, saved and did nothing useful - a wall of pseudocode plus numbers
no engine accepts, silently clamped.

1. Speech position, pitch and rate are real statements, so that script can be
   written out instead of described (``say "one" position=-1 rate=-6``).
2. A number outside what a setting takes is refused with its line number, at
   write time as well as run time.
3. With AI features off, a pseudocode line is reported by line BEFORE anything
   runs, and a parse error is announced instead of failing silently.
4. A macro written on somebody's behalf may not be pseudocode.
5. ``macros.edit_macro`` changes the macro that exists rather than making a
   second one, and refuses a bad script without touching the good one.
6. The creation kit's 'macro' kind writes a script, is grounded on the macro
   manager's own documentation, and has every generated .tcs checked by it.
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_macros_component():
    """The Macro Manager component, loaded straight from its file."""
    path = os.path.join(REPO, 'data', 'components', 'macros', 'init.py')
    spec = importlib.util.spec_from_file_location('macros_component', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MACROS = _load_macros_component()

# The macro manager writes its review in the language Titan is running in, and
# these tests assert the English wording, so the component is pinned to English
# here. `TheReviewSpeaksTheUsersLanguage` checks the Polish catalogue itself.
_LANGUAGES_DIR = os.path.join(REPO, 'data', 'components', 'macros',
                              'languages')


def _catalogue(language):
    import gettext
    return gettext.translation('macros', _LANGUAGES_DIR, languages=[language],
                               fallback=True).gettext


MACROS._ = _catalogue('en')

HALLUCINATED = (
    '# Makro: licz do 10\n'
    'voice rate=1\n'
    'do "powiedz 1 z lewej strony (pozycja -1.0)" wait=true\n'
    'voice rate=100\n'
    'do "powiedz 10 z prawej strony (pozycja 1.0)" wait=true\n'
)

CORRECTED = (
    'say "one" position=-1 rate=-10 wait=true\n'
    'say "five" position=0 rate=0 wait=true\n'
    'say "ten" position=1 rate=10 pitch=4 wait=true\n'
)


class SpeechIsPartOfTheLanguage(unittest.TestCase):
    """1. Where the voice is, how fast and how high, without the AI."""

    def setUp(self):
        self._ai_on = MACROS._ai_features_on
        MACROS._ai_features_on = lambda: True

    def tearDown(self):
        MACROS._ai_features_on = self._ai_on

    def test_corrected_script_is_valid(self):
        self.assertEqual([], MACROS.check_tcs(CORRECTED))
        self.assertEqual([], MACROS.pseudocode_lines(CORRECTED))

    def test_say_keeps_its_new_arguments(self):
        program, errors = MACROS._ai_parse(CORRECTED)
        self.assertEqual([], [e.describe() for e in errors])
        first = program['body'][0]
        self.assertEqual('say', first['kind'])
        for key in ('position', 'rate', 'wait'):
            self.assertIsNotNone(first[key], key)

    def test_the_values_reach_the_speaker(self):
        calls = []
        original = MACROS._tcs_say
        MACROS._tcs_say = lambda *a, **k: calls.append(k)
        try:
            program, _e = MACROS._ai_parse(
                'say "x" position=-0.5 pitch=3 rate=7 wait=true')
            MACROS._ai_execute(program['body'], {}, [],
                               {'steps': 100, 'prose': {}, 'dir': ''})
        finally:
            MACROS._tcs_say = original
        self.assertEqual(1, len(calls))
        self.assertEqual(-0.5, calls[0]['position'])
        self.assertEqual(3, calls[0]['pitch'])
        self.assertEqual(7, calls[0]['rate'])
        self.assertTrue(calls[0]['wait'])

    def test_an_unknown_argument_is_named(self):
        problems = MACROS.check_tcs('say "x" speed=3')
        self.assertTrue(any('does not know' in p for p in problems), problems)

    def test_the_bundled_examples_check_out(self):
        base_dir = os.path.join(REPO, 'data', 'macros')
        seen = 0
        for folder in sorted(os.listdir(base_dir)):
            folder_path = os.path.join(base_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            for name in sorted(os.listdir(folder_path)):
                if not name.lower().endswith('.tcs'):
                    continue
                seen += 1
                with open(os.path.join(folder_path, name),
                          encoding='utf-8') as handle:
                    text = handle.read()
                problems = [
                    p for p in MACROS.check_tcs(text, base_dir=folder_path)
                    # Resolving an action needs a running Titan; only the
                    # language itself is meaningful here.
                    if 'is not something' not in p and 'has no action' not in p
                    and 'no add-on' not in p]
                self.assertEqual([], problems, f"{folder}/{name}")
        self.assertTrue(seen)


class NumbersOutsideWhatTitanTakes(unittest.TestCase):
    """2. rate=100 is a guess, and a silently clamped guess teaches nothing."""

    def test_every_range_is_checked_before_the_macro_runs(self):
        for script, word in (('voice rate=100', 'rate'),
                             ('voice pitch=-40', 'pitch'),
                             ('voice volume=300', 'volume'),
                             ('say "x" position=1.5', 'position'),
                             ('say "x" rate=99', 'rate'),
                             ('play "a.ogg" position=-2', 'position')):
            problems = MACROS.check_tcs(script)
            self.assertTrue(any(word in p and 'line 1' in p for p in problems),
                            f"{script} -> {problems}")

    def test_a_value_from_a_variable_is_left_to_the_run(self):
        problems = MACROS.check_tcs('set p = 0.5\nsay "x" position=p')
        self.assertEqual([], [p for p in problems if 'position' in p])

    def test_a_value_in_range_is_accepted(self):
        self.assertEqual([], MACROS.check_tcs('voice rate=-10\n'
                                              'say "x" position=-1 pitch=10'))


class ErrorsNameTheirLine(unittest.TestCase):
    """3. A macro that does nothing is the worst possible answer."""

    def setUp(self):
        self.spoken = []
        self._speak, self._error = MACROS._speak, MACROS._play_error
        self._ai_on = MACROS._ai_features_on
        MACROS._speak = lambda text, force=False: self.spoken.append(str(text))
        MACROS._play_error = lambda: None
        MACROS._ai_features_on = lambda: False

    def tearDown(self):
        MACROS._speak, MACROS._play_error = self._speak, self._error
        MACROS._ai_features_on = self._ai_on

    def test_pseudocode_with_ai_off_stops_before_running_anything(self):
        ok, transcript = MACROS.run_tcs_text('say "first"\n'
                                             'do "policz do dziesieciu"\n')
        self.assertFalse(ok)
        self.assertTrue(any('line 2' in line for line in transcript),
                        transcript)
        self.assertTrue(any('line 2' in said for said in self.spoken),
                        self.spoken)

    def test_every_pseudocode_line_is_listed(self):
        problems = MACROS.check_tcs(HALLUCINATED)
        for number in (3, 5):
            self.assertTrue(any(f'line {number}' in p for p in problems),
                            problems)

    def test_a_parse_error_is_announced(self):
        ok, transcript = MACROS.run_tcs_text('repeat 3\nsay "x"\n')
        self.assertFalse(ok)
        self.assertTrue(any('line 1' in said for said in self.spoken),
                        self.spoken)


class WritingAMacroForSomebody(unittest.TestCase):
    """4/5. Created and edited macros are real scripts, or they are refused."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='titan_macros_test_')
        self._saved = (MACROS.MACROS_DIR, MACROS.USER_MACROS_DIR,
                       MACROS._refresh_macro_list, MACROS._ai_features_on)
        MACROS.MACROS_DIR = os.path.join(self.tmp, 'bundled')
        MACROS.USER_MACROS_DIR = os.path.join(self.tmp, 'user')
        os.makedirs(MACROS.MACROS_DIR, exist_ok=True)
        os.makedirs(MACROS.USER_MACROS_DIR, exist_ok=True)
        MACROS._refresh_macro_list = lambda: None
        MACROS._ai_features_on = lambda: True

    def tearDown(self):
        (MACROS.MACROS_DIR, MACROS.USER_MACROS_DIR,
         MACROS._refresh_macro_list, MACROS._ai_features_on) = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _text(result):
        return str(getattr(result, 'reason', result))

    def _create(self, name=' Counting', script=CORRECTED, **kwargs):
        return self._text(MACROS.action_create_macro(
            name.strip(), script=script, kind='tcs', **kwargs))

    def test_a_good_script_is_saved(self):
        self.assertIn('Created the macro', self._create())
        self.assertTrue(os.path.isfile(os.path.join(
            MACROS.USER_MACROS_DIR, 'counting', 'counting.tcs')))

    def test_a_hallucinated_script_is_refused_line_by_line(self):
        answer = self._create('Bad', script=HALLUCINATED)
        self.assertIn('would not run', answer)
        self.assertIn('line 3', answer)          # pseudocode
        self.assertIn('line 4', answer)          # rate=100
        self.assertIn('macros.macro_language', answer)   # the real language
        self.assertFalse(os.path.isdir(
            os.path.join(MACROS.USER_MACROS_DIR, 'bad')))

    def test_pseudocode_needs_asking_for(self):
        self.assertIn('would not run', self._create('Loose',
                                                    script='do "say hello"\n'))
        self.assertIn('Created the macro',
                      self._create('Loose', script='do "say hello"\n',
                                   allow_pseudocode=True))

    def test_creating_over_an_existing_macro_points_at_editing(self):
        self._create()
        answer = self._create()
        self.assertIn('already a macro', answer)
        self.assertIn('macros.edit_macro', answer)

    def test_editing_changes_that_macro_and_makes_no_second_one(self):
        self._create()
        answer = self._text(MACROS.action_edit_macro(
            'Counting', script=CORRECTED + 'say "eleven"\n'))
        self.assertIn('Changed the macro', answer)
        with open(os.path.join(MACROS.USER_MACROS_DIR, 'counting',
                               'counting.tcs'), encoding='utf-8') as handle:
            self.assertIn('eleven', handle.read())
        self.assertEqual(['counting'], os.listdir(MACROS.USER_MACROS_DIR))

    def test_a_bad_edit_leaves_the_macro_alone(self):
        self._create()
        path = os.path.join(MACROS.USER_MACROS_DIR, 'counting', 'counting.tcs')
        with open(path, encoding='utf-8') as handle:
            before = handle.read()
        answer = self._text(MACROS.action_edit_macro('Counting',
                                                     script='voice pitch=99\n'))
        self.assertIn('line 1', answer)
        with open(path, encoding='utf-8') as handle:
            self.assertEqual(before, handle.read())

    def test_appending_keeps_what_was_there(self):
        self._create()
        MACROS.action_edit_macro('Counting', script='say "extra"\n',
                                 append=True, hotkey='ctrl+alt+m')
        with open(os.path.join(MACROS.USER_MACROS_DIR, 'counting',
                               'counting.tcs'), encoding='utf-8') as handle:
            body = handle.read()
        self.assertIn('one', body)
        self.assertTrue(body.rstrip().endswith('"extra"'), body[-40:])
        with open(os.path.join(MACROS.USER_MACROS_DIR, 'counting',
                               '__macro__.TCE'), encoding='utf-8') as handle:
            self.assertIn('ctrl+alt+m', handle.read())

    def test_editing_a_bundled_macro_does_not_touch_the_installation(self):
        bundled = os.path.join(MACROS.MACROS_DIR, 'shipped')
        os.makedirs(bundled, exist_ok=True)
        with open(os.path.join(bundled, '__macro__.TCE'), 'w',
                  encoding='utf-8') as handle:
            handle.write('[macro]\nname_en = Shipped\nname_pl = Shipped\n'
                         'openfile = shipped.tcs\n\n[macrocfg]\nhotkey = \n')
        with open(os.path.join(bundled, 'shipped.tcs'), 'w',
                  encoding='utf-8') as handle:
            handle.write('say "original"\n')
        MACROS.action_edit_macro('Shipped', script='say "mine"\n')
        with open(os.path.join(bundled, 'shipped.tcs'),
                  encoding='utf-8') as handle:
            self.assertEqual('say "original"', handle.read().strip())
        with open(os.path.join(MACROS.USER_MACROS_DIR, 'shipped',
                               'shipped.tcs'), encoding='utf-8') as handle:
            self.assertIn('mine', handle.read())


class ActingOnTheOptionThatWasPicked(unittest.TestCase):
    """`if answer = "yes"` and `if answer = "1"` are the same option."""

    def test_an_answer_is_its_text(self):
        answer = MACROS._AIChoice('yes', 1, ['yes', 'no'])
        self.assertEqual('yes', str(answer))
        self.assertEqual('I said yes', 'I said ' + answer)

    def test_it_can_be_named_by_text_or_by_number(self):
        answer = MACROS._AIChoice('Save and read', 2,
                                  ['Save', 'Save and read', 'Cancel'])
        for operator in ('is', '=', '=='):
            self.assertTrue(MACROS._ai_compare(answer, operator,
                                               'Save and read'), operator)
            self.assertTrue(MACROS._ai_compare(answer, operator, '2'), operator)
            self.assertTrue(MACROS._ai_compare(answer, operator, 2), operator)
            self.assertFalse(MACROS._ai_compare(answer, operator, 'Cancel'))
            self.assertFalse(MACROS._ai_compare(answer, operator, '3'))
        self.assertTrue(MACROS._ai_compare(answer, 'is not', 'Cancel'))
        self.assertFalse(MACROS._ai_compare(answer, '!=', '2'))

    def test_it_works_on_either_side(self):
        answer = MACROS._AIChoice('no', 2, ['yes', 'no'])
        self.assertTrue(MACROS._ai_compare('2', 'is', answer))

    def test_an_ordinary_string_still_compares_as_text(self):
        self.assertFalse(MACROS._ai_compare('yes', 'is', '1'))
        self.assertTrue(MACROS._ai_compare('yes', 'is', 'YES'))

    def test_the_comparison_runs_in_a_script(self):
        variables = {'answer': MACROS._AIChoice('nie', 2, ['tak', 'nie'])}
        said = []
        original = MACROS._tcs_say
        MACROS._tcs_say = lambda text, **k: said.append(str(text))
        try:
            program, errors = MACROS._ai_parse(
                'if answer="2"\n    say "second"\nelse\n    say "first"\nend')
            self.assertEqual([], [e.describe() for e in errors])
            MACROS._ai_execute(program['body'], variables, [],
                               {'steps': 100, 'prose': {}, 'dir': ''})
        finally:
            MACROS._tcs_say = original
        self.assertEqual(['second'], said)


class ComparisonsWrittenTight(unittest.TestCase):
    """`if option="tak"` is a comparison; refusing it for want of spaces is not
    something a person writing a macro should have to discover."""

    def test_the_symbols_need_no_spaces(self):
        for line, operator in (('x="tak"', '='), ('x!="tak"', '!='),
                               ('x>=3', '>='), ('x<3', '<'), ('x==3', '==')):
            statement = MACROS._ai_parse_if(1, line)
            self.assertEqual(operator, statement['op'], line)

    def test_a_quoted_value_is_not_split_on(self):
        statement = MACROS._ai_parse_if(1, 'x = "a=b"')
        self.assertEqual('=', statement['op'])
        self.assertEqual('a=b', statement['right']['value'])

    def test_a_named_argument_in_brackets_is_not_the_comparison(self):
        found = MACROS._ai_tight_operator('tnotes.count(kind="work")>0')
        self.assertIsNotNone(found)
        self.assertEqual('>', found[1])

    def test_words_still_win(self):
        self.assertEqual('contains', MACROS._ai_parse_if(
            1, 'x contains "a=b"')['op'])

    def test_a_line_with_no_comparison_still_says_so(self):
        with self.assertRaises(MACROS.TCSError):
            MACROS._ai_parse_if(1, 'something entirely')


class FormsWithButtons(unittest.TestCase):
    """A form that can only be accepted or abandoned cannot be automated."""

    def test_buttons_parse_into_the_dialog(self):
        program, errors = MACROS._ai_parse(
            'dialog "New note"\n'
            '    field title = "Title"\n'
            '    buttons pressed = "Save", "Save and read", "Cancel"\n'
            'end')
        self.assertEqual([], [e.describe() for e in errors])
        fields = program['body'][0]['fields']
        buttons = [f for f in fields if f.get('control') == 'buttons']
        self.assertEqual(1, len(buttons))
        self.assertEqual('pressed', buttons[0]['name'])
        self.assertEqual(3, len(buttons[0]['options']))

    def test_buttons_belong_in_a_dialog(self):
        _program, errors = MACROS._ai_parse('buttons x = "One"')
        self.assertTrue(any('dialog' in e.describe() for e in errors), errors)

    def test_a_dialog_has_one_set_of_buttons(self):
        _program, errors = MACROS._ai_parse(
            'dialog "x"\n    buttons a = "One"\n    buttons b = "Two"\nend')
        self.assertTrue(any('one set of buttons' in e.describe()
                            for e in errors), [e.describe() for e in errors])

    def test_buttons_need_labels_and_a_name(self):
        for line in ('buttons pressed', 'buttons pressed ='):
            _program, errors = MACROS._ai_parse(f'dialog "x"\n    {line}\nend')
            self.assertTrue(errors, line)

    def test_the_example_form_is_valid(self):
        path = os.path.join(REPO, 'data', 'macros', 'form_demo',
                            'form_demo.tcs')
        with open(path, encoding='utf-8') as handle:
            text = handle.read()
        problems = [p for p in MACROS.check_tcs(
            text, base_dir=os.path.dirname(path))
            if 'is not something' not in p and 'has no action' not in p
            and 'no add-on' not in p]
        self.assertEqual([], problems)


class SoundThatCanBePlacedAndMoved(unittest.TestCase):
    """Positioning, on the fly and in general."""

    def test_play_takes_the_positioning_arguments(self):
        program, errors = MACROS._ai_parse(
            'play "a.ogg" position=-1 to=1 duration=3s elevation=0.5')
        self.assertEqual([], [e.describe() for e in errors])
        statement = program['body'][0]
        for key in ('position', 'to', 'duration', 'elevation'):
            self.assertIsNotNone(statement.get(key), key)

    def test_an_unknown_argument_is_named(self):
        problems = MACROS.check_tcs('play "a.ogg" speed=2')
        self.assertTrue(any('does not know' in p for p in problems), problems)

    def test_positions_are_range_checked(self):
        for line, word in (('play "a.ogg" to=5', 'to'),
                           ('play "a.ogg" elevation=-9', 'elevation'),
                           ('play "a.ogg" position=2', 'position')):
            problems = MACROS.check_tcs(line)
            self.assertTrue(any(word in p and 'line 1' in p for p in problems),
                            f"{line} -> {problems}")

    def test_the_action_maps_minus_one_to_one_onto_the_mixers_pan(self):
        # sound.py has always taken 0..1; everything Titan exposes says
        # -1..1. Passing one straight into the other made the centre hard left.
        from src.ai import titan_tools
        seen = {}

        class _FakeSound(types.ModuleType):
            @staticmethod
            def play_sound_file(path, pan=None, elevation=0.0):
                seen['pan'] = pan
                return True

            @staticmethod
            def play_sound_file_moving(path, pan=0.0, to_pan=1.0, seconds=2.0,
                                       elevation=0.0, to_elevation=None):
                seen.update(pan=pan, to_pan=to_pan, seconds=seconds)
                return True

        fake = _FakeSound('src.titan_core.sound')
        saved = sys.modules.get('src.titan_core.sound')
        sys.modules['src.titan_core.sound'] = fake
        try:
            here = os.path.join(REPO, 'data', 'macros', 'form_demo', 'done.ogg')
            titan_tools.titan_play_sound(here, position=0.0)
            self.assertAlmostEqual(0.5, seen['pan'])       # centre is centre
            titan_tools.titan_play_sound(here, position=-1.0)
            self.assertAlmostEqual(0.0, seen['pan'])       # hard left
            titan_tools.titan_play_sound(here, position=1.0)
            self.assertAlmostEqual(1.0, seen['pan'])       # hard right
            titan_tools.titan_play_sound(here, position=-1.0, to=1.0,
                                         duration=3)
            self.assertAlmostEqual(0.0, seen['pan'])
            self.assertAlmostEqual(1.0, seen['to_pan'])
            self.assertAlmostEqual(3.0, seen['seconds'])
        finally:
            if saved is not None:
                sys.modules['src.titan_core.sound'] = saved
            else:
                sys.modules.pop('src.titan_core.sound', None)


class WindowsAreTitledWithTheMacro(unittest.TestCase):
    """A macro's window carries the macro's name, not the word "Macro"."""

    def tearDown(self):
        MACROS._tcs_running.title = ''

    def test_the_macros_own_name_is_the_default(self):
        MACROS._tcs_running.title = 'Voice demo'
        self.assertEqual('Voice demo', MACROS._tcs_title(''))

    def test_a_title_in_the_script_wins(self):
        MACROS._tcs_running.title = 'Voice demo'
        self.assertEqual('New note', MACROS._tcs_title('New note'))

    def test_running_a_script_sets_it(self):
        MACROS._tcs_running.title = ''
        MACROS.run_tcs_text('stop', announce=False, title='Morning routine')
        self.assertEqual('Morning routine', MACROS._tcs_title(''))


class TheDocumentationFollowsTitansLanguage(unittest.TestCase):
    """Somebody learning the language should not have to learn English first."""

    def test_polish_is_asked_for_by_name(self):
        polish = MACROS._macro_language_text('pl')
        english = MACROS._macro_language_text('en')
        self.assertIn('Język skryptowy Titana', polish)
        self.assertIn('The Titan Scripting Language', english)
        self.assertNotEqual(polish, english)

    def test_both_describe_the_same_language(self):
        for text in (MACROS._macro_language_text('pl'),
                     MACROS._macro_language_text('en')):
            for word in ('buttons ', 'position=-1 to=1 duration=3s',
                         'when startup', 'voice reset', 'repeat 3',
                         'multiline body', 'choice ', 'check '):
                self.assertIn(word, text)

    def test_the_action_takes_a_language(self):
        answer = str(MACROS.action_macro_language(language='pl'))
        self.assertIn('Język skryptowy Titana', answer)

    def test_the_new_script_template_has_a_polish_version(self):
        self.assertIn('Skrypt Titana', MACROS.TCS_TEMPLATE_PL)
        for template in (MACROS.TCS_TEMPLATE, MACROS.TCS_TEMPLATE_PL):
            body = "\n".join(line for line in template.splitlines()
                             if not line.startswith('#'))
            self.assertEqual([], MACROS.check_tcs(body) if body.strip() else [])


class AButtonThatDoesSomething(unittest.TestCase):
    """`on "<button>"` runs while the window is still open."""

    SCRIPT = ('dialog "Notes"\n'
              '    field query = "Search for"\n'
              '    buttons pressed = "Search", "Close"\n'
              '    on "Search"\n'
              '        say "searching {{query}}"\n'
              '    end\n'
              'end')

    def test_it_parses_into_the_dialog(self):
        program, errors = MACROS._ai_parse(self.SCRIPT)
        self.assertEqual([], [e.describe() for e in errors])
        handlers = [f for f in program['body'][0]['fields']
                    if f['kind'] == 'handler']
        self.assertEqual(1, len(handlers))
        self.assertEqual(1, len(handlers[0]['body']))

    def test_on_belongs_in_a_dialog(self):
        _program, errors = MACROS._ai_parse('on "Search"\n    say "x"\nend')
        self.assertTrue(any('dialog' in e.describe() for e in errors), errors)

    def test_on_needs_buttons_to_press(self):
        program, _errors = MACROS._ai_parse(
            'dialog "x"\n    field a = "A"\n    on "Save"\n        say "x"\n'
            '    end\nend')
        MACROS._ai_form = lambda *a, **k: {}
        with self.assertRaises(MACROS.TCSError):
            MACROS._ai_dialog(program['body'][0], {}, [], None)

    def test_pressing_it_runs_the_block_with_the_live_controls(self):
        program, _errors = MACROS._ai_parse(self.SCRIPT)
        said = []
        pressed_result = {}
        original_say, original_form = MACROS._tcs_say, MACROS._ai_form

        def fake_form(title, fields, on_press=None):
            # What the real form does: ask whether a button has a block, then
            # call it with the controls as they stand when it is pressed.
            pressed_result['live'] = on_press('Search', 1, None)
            pressed_result['dead'] = on_press('Close', 2, None)
            on_press('Search', 1, {'query': 'invoices'})
            return {'query': 'invoices',
                    'pressed': MACROS._AIChoice('Close', 2,
                                                ['Search', 'Close'])}

        MACROS._tcs_say = lambda text, **k: said.append(str(text))
        MACROS._ai_form = fake_form
        try:
            values = MACROS._ai_dialog(program['body'][0], {}, [],
                                       {'steps': 100, 'prose': {}, 'dir': ''})
        finally:
            MACROS._tcs_say, MACROS._ai_form = original_say, original_form
        self.assertTrue(pressed_result['live'])       # "Search" has a block
        self.assertFalse(pressed_result['dead'])      # "Close" has none
        self.assertEqual(['searching invoices'], said)
        self.assertEqual('Close', str(values['pressed']))

    def test_a_handler_matches_by_number_too(self):
        program, _errors = MACROS._ai_parse(
            self.SCRIPT.replace('on "Search"', 'on "1"'))
        original = MACROS._ai_form
        seen = {}

        def fake_form(title, fields, on_press=None):
            seen['live'] = on_press('Search', 1, None)
            return {}

        MACROS._ai_form = fake_form
        try:
            MACROS._ai_dialog(program['body'][0], {}, [], None)
        finally:
            MACROS._ai_form = original
        self.assertTrue(seen['live'])


class DrivingAnythingElse(unittest.TestCase):
    """keys / type / an action named by a variable / an editable title."""

    def setUp(self):
        self.calls = []
        self.fake = types.ModuleType('fake_actions')

        class _R:
            def __init__(self, ok=True, text='done'):
                self.ok, self.text = ok, text

        def _run(addon, name='', **kwargs):
            self.calls.append((addon, name, kwargs))
            return _R()

        self.fake.run = _run

        class _EmptyRegistry:
            addons = []

            @staticmethod
            def by_id(_addon_id):
                return None

        self.fake.get_registry = lambda: _EmptyRegistry()
        import src.titan_core as core
        self._saved = getattr(core, 'actions', None)
        core.actions = self.fake

    def tearDown(self):
        import src.titan_core as core
        if self._saved is not None:
            core.actions = self._saved

    def _run(self, script, variables=None):
        program, errors = MACROS._ai_parse(script)
        self.assertEqual([], [e.describe() for e in errors])
        MACROS._ai_execute(program['body'], variables if variables is not None
                           else {}, [], {'steps': 100, 'prose': {}, 'dir': ''})

    def test_keys_presses_each_chord_in_order(self):
        self._run('keys "ctrl+c, ctrl+v"')
        self.assertEqual([('desktop', 'press_keys', {'keys': 'ctrl+c'}),
                          ('desktop', 'press_keys', {'keys': 'ctrl+v'})],
                         self.calls)

    def test_type_types(self):
        self._run('type "hello"')
        self.assertEqual([('desktop', 'type_text', {'text': 'hello'})],
                         self.calls)

    def test_they_take_variables(self):
        self._run('type "{{what}}"', {'what': 'from a variable'})
        self.assertEqual('from a variable', self.calls[0][2]['text'])

    def test_an_action_can_come_from_a_variable(self):
        asked = {}

        class _Spec:
            params = {'path': {'type': 'string'}}

        def _resolve(path):
            asked['path'] = path
            addon, _dot, action = path.partition('.')
            return addon, action, _Spec()

        original = MACROS._ai_resolve
        MACROS._ai_resolve = _resolve
        try:
            self._run('{{app}}.open_file path="x"', {'app': 'tedit'})
        finally:
            MACROS._ai_resolve = original
        # The name is filled in from the variable before it is resolved.
        self.assertEqual('tedit.open_file', asked['path'])
        self.assertEqual(('tedit', 'open_file'), self.calls[0][:2])

    def test_an_unknown_action_from_a_variable_still_says_so(self):
        with self.assertRaises(MACROS.TCSError):
            self._run('{{app}}.open_file path="x"', {'app': 'nosuchaddon'})

    def test_the_title_is_editable(self):
        MACROS._tcs_running.title = 'Old'
        try:
            self._run('title "New windows"')
            self.assertEqual('New windows', MACROS._tcs_title(''))
        finally:
            MACROS._tcs_running.title = ''


class OnlyWhatAModelDoesNeedsTheAI(unittest.TestCase):
    """An action is gated on the AI only if it actually sends something to a
    provider - living in src/ai/ is not the same as calling a model."""

    @classmethod
    def setUpClass(cls):
        try:
            from src.titan_core.actions import builtin, dispatch
        except Exception as e:                   # pragma: no cover
            raise unittest.SkipTest(f"the action API is not importable: {e}")
        cls.builtin, cls.dispatch = builtin, dispatch
        cls.addons = builtin.build()

    def _actions(self):
        return {f"{a.addon_id}.{x.name}": x
                for a in self.addons for x in a.actions}

    def test_the_automation_providers_are_there(self):
        ids = {a.addon_id for a in self.addons}
        for provider in ('desktop', 'ui', 'web', 'system', 'titan'):
            self.assertIn(provider, ids)
        actions = self._actions()
        for named in ('desktop.press_keys', 'desktop.type_text',
                      'desktop.launch_program', 'desktop.focus_window',
                      'ui.click_element', 'ui.list_elements', 'web.open'):
            self.assertIn(named, actions)

    def test_only_the_vision_actions_need_the_ai(self):
        gated = sorted(name for name, spec in self._actions().items()
                       if spec.needs_ai)
        self.assertEqual(['ocr.ask', 'ocr.read_window'], gated)

    def test_pressing_what_ocr_already_read_does_not(self):
        actions = self._actions()
        for named in ('ocr.press', 'ocr.type', 'ocr.send_key',
                      'memory.remember', 'memory.recall'):
            self.assertFalse(actions[named].needs_ai, named)

    def test_a_gated_action_is_refused_with_a_sentence(self):
        saved = self.dispatch.ai_features_on
        self.dispatch.ai_features_on = lambda: False
        try:
            result = self.dispatch.run('ocr', 'read_window')
        finally:
            self.dispatch.ai_features_on = saved
        self.assertFalse(result.ok)
        self.assertIn('AI features', result.text)
        self.assertIn('Settings', result.text)

    def test_an_ordinary_action_still_runs_with_the_ai_off(self):
        saved = self.dispatch.ai_features_on
        self.dispatch.ai_features_on = lambda: False
        try:
            result = self.dispatch.run('desktop', 'get_foreground_window')
        finally:
            self.dispatch.ai_features_on = saved
        self.assertTrue(result.ok, result.text)

    def test_it_is_visible_in_the_listing(self):
        actions = self._actions()
        self.assertIn('[needs AI]', actions['ocr.read_window'].describe())
        self.assertNotIn('[needs AI]', actions['ocr.press'].describe())


class CheckScriptIsARealReview(unittest.TestCase):
    """"The macro is fine" is a promise. A script can parse, name only real
    actions, and still be wrong - so the check compares it against the
    documented language and against what each action declares."""

    HIDDEN = ('set greeting = "Hello"\n'          # 1
              'say "{{greting}}"\n'               # 2 - misspelt variable
              'dialog "X"\n'                      # 3
              '    field a = "A"\n'               # 4
              '    buttons pressed = "Save", "Cancel"\n'   # 5
              '    on "Sve"\n'                    # 6 - no such button
              '        say "{{a}}"\n'             # 7
              '    end\n'                         # 8
              'end\n'                             # 9
              'stop\n'                            # 10
              'say "never"\n')                    # 11 - unreachable

    def setUp(self):
        self._ai_on = MACROS._ai_features_on
        MACROS._ai_features_on = lambda: True

    def tearDown(self):
        MACROS._ai_features_on = self._ai_on

    def test_it_would_run_but_it_is_wrong(self):
        self.assertEqual([], MACROS.check_tcs(self.HIDDEN))   # parses, resolves
        warnings = MACROS.review_warnings(self.HIDDEN)
        self.assertTrue(any('greting' in w and 'never set' in w
                            for w in warnings), warnings)
        self.assertTrue(any("no button called 'Sve'" in w for w in warnings),
                        warnings)
        self.assertTrue(any('line 11' in w and 'never run' in w
                            for w in warnings), warnings)

    def test_an_answer_used_before_it_is_asked_for(self):
        # "Save the note, then ask what to call it" runs, and saves an
        # untitled note every time.
        warnings = MACROS.review_warnings(
            'tnotes.create_note title="{{title}}" text="x"\n'
            'ask title = "What should it be called?"')
        self.assertTrue(any('only gets a value on line 2' in w
                            for w in warnings), warnings)

    def test_a_loop_may_use_what_it_sets_at_the_end(self):
        self.assertEqual([], MACROS.review_warnings(
            'repeat 3\n    say "{{total}}"\n    set total = 1\nend'))

    def test_a_button_block_may_use_the_forms_controls(self):
        self.assertEqual([], MACROS.review_warnings(
            'dialog "x"\n    field a = "A"\n    buttons p = "Go"\n'
            '    on "Go"\n        say "{{a}}"\n    end\nend'))

    def test_a_misspelt_variable_suggests_the_real_one(self):
        warnings = MACROS.review_warnings('set greeting = "x"\n'
                                          'say "{{greting}}"')
        self.assertIn('did you mean greeting', warnings[0])

    def test_another_language_written_by_habit_is_pointed_at(self):
        for line, word in (('while x > 3', 'while'), ('for i in list', 'for'),
                           ('print "hello"', 'print'), ('sleep 5', 'sleep'),
                           ('var x = 3', 'var'), ('exit', 'exit')):
            warnings = MACROS.review_warnings(line)
            self.assertTrue(any(word in w and 'not part of the Titan' in w
                                for w in warnings), f"{line} -> {warnings}")

    def test_a_value_an_action_does_not_take_is_caught(self):
        # An action's own declaration IS the documentation, so a value outside
        # a declared enum is checked against it. (Resolution needs a running
        # Titan, so the declaration is supplied here.)
        class _Spec:
            params = {'kind': {'type': 'string',
                               'enum': ['keys', 'tcs', 'ahk', 'au3']}}
            needs_ai = False
            qualified = 'macros.create_macro'

        original = MACROS._ai_resolve
        MACROS._ai_resolve = lambda path: ('macros', 'create_macro', _Spec())
        try:
            warnings = MACROS.review_warnings(
                'macros.create_macro name="x" kind="python"')
        finally:
            MACROS._ai_resolve = original
        self.assertTrue(any('does not take kind' in w for w in warnings),
                        warnings)

    def test_an_ai_backed_action_is_flagged_when_the_ai_is_off(self):
        class _Spec:
            params = {}
            needs_ai = True
            qualified = 'ocr.read_window'

        original = MACROS._ai_resolve
        MACROS._ai_resolve = lambda path: ('ocr', 'read_window', _Spec())
        MACROS._ai_features_on = lambda: False
        try:
            warnings = MACROS.review_warnings('ocr.read_window')
        finally:
            MACROS._ai_resolve = original
        self.assertTrue(any('carried out by the AI' in w for w in warnings),
                        warnings)

    def test_the_bundled_examples_have_nothing_to_answer_for(self):
        base_dir = os.path.join(REPO, 'data', 'macros')
        for folder in sorted(os.listdir(base_dir)):
            folder_path = os.path.join(base_dir, folder)
            if not os.path.isdir(folder_path):
                continue
            for name in sorted(os.listdir(folder_path)):
                if not name.lower().endswith('.tcs'):
                    continue
                with open(os.path.join(folder_path, name),
                          encoding='utf-8') as handle:
                    text = handle.read()
                self.assertEqual(
                    [], MACROS.review_warnings(text, base_dir=folder_path),
                    f"{folder}/{name}")

    def test_a_clean_script_says_so_plainly(self):
        MACROS._ai_features_on = lambda: False
        answer = str(MACROS.action_check_macro(
            script='set x = "a"\nsay "{{x}}"'))
        self.assertIn('fine', answer)
        self.assertIn('AI features are off', answer)

    def test_the_three_tiers_are_reported_separately(self):
        original = MACROS.review_with_ai
        MACROS.review_with_ai = lambda text, actions='': [
            'line 2: the greeting is never spoken']
        try:
            answer = str(MACROS.action_check_macro(script=self.HIDDEN))
        finally:
            MACROS.review_with_ai = original
        self.assertIn('Would run, but looks wrong', answer)
        self.assertIn('The AI also read it and noticed', answer)
        self.assertNotIn('Would not run', answer)

    def test_the_ai_is_not_asked_about_a_script_that_cannot_parse(self):
        asked = []
        original = MACROS.review_with_ai
        MACROS.review_with_ai = lambda text, actions='': asked.append(1) or []
        try:
            problems, _warnings, notes = MACROS.review_tcs('repeat 3\n')
        finally:
            MACROS.review_with_ai = original
        self.assertTrue(problems)
        self.assertEqual([], asked)
        self.assertEqual([], notes)

    def test_the_ai_pass_is_off_when_ai_features_are(self):
        MACROS._ai_features_on = lambda: False
        self.assertEqual([], MACROS.review_with_ai('say "x"'))

    def test_the_ai_answering_ok_means_nothing_to_report(self):
        import src.ai.ai_provider as provider
        saved = provider.generate
        provider.generate = lambda *a, **k: "OK"
        try:
            self.assertEqual([], MACROS.review_with_ai('say "x"'))
            provider.generate = lambda *a, **k: (
                "line 3: the note is saved before its title is asked for\n"
                "Overall this looks reasonable.")
            notes = MACROS.review_with_ai('say "x"')
        finally:
            provider.generate = saved
        # Only line-anchored findings survive; prose is dropped.
        self.assertEqual(['line 3: the note is saved before its title is '
                          'asked for'], notes)

    def test_warnings_come_back_when_a_macro_is_written(self):
        tmp = tempfile.mkdtemp(prefix='titan_macros_review_')
        saved = (MACROS.MACROS_DIR, MACROS.USER_MACROS_DIR,
                 MACROS._refresh_macro_list)
        MACROS.MACROS_DIR = os.path.join(tmp, 'bundled')
        MACROS.USER_MACROS_DIR = os.path.join(tmp, 'user')
        os.makedirs(MACROS.MACROS_DIR, exist_ok=True)
        os.makedirs(MACROS.USER_MACROS_DIR, exist_ok=True)
        MACROS._refresh_macro_list = lambda: None
        try:
            answer = str(MACROS.action_create_macro(
                'Typo', kind='tcs',
                script='set greeting = "x"\nsay "{{greting}}"'))
        finally:
            (MACROS.MACROS_DIR, MACROS.USER_MACROS_DIR,
             MACROS._refresh_macro_list) = saved
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIn('Created the macro', answer)
        self.assertIn('Worth looking at', answer)
        self.assertIn('greting', answer)


class TheReviewSpeaksTheUsersLanguage(unittest.TestCase):
    """Everything the check says is Titan's own wording, so it follows the
    language Titan is running in - and it lives in the MACRO component's
    catalogue, not in Titan's."""

    def setUp(self):
        self._ai_on, self._gettext = MACROS._ai_features_on, MACROS._
        MACROS._ai_features_on = lambda: True
        MACROS._ = _catalogue('pl')

    def tearDown(self):
        MACROS._ai_features_on, MACROS._ = self._ai_on, self._gettext

    def test_the_line_anchor_is_translated(self):
        self.assertTrue(MACROS._tcs_line(4, 'x').startswith('linia 4:'),
                        MACROS._tcs_line(4, 'x'))
        self.assertIn('linia', MACROS._tcs_line_prefixes())
        self.assertIn('line', MACROS._tcs_line_prefixes())

    def test_a_warning_is_polish(self):
        warnings = MACROS.review_warnings('set greeting = "x"\n'
                                          'say "{{greting}}"')
        self.assertIn('nigdy nie ustawione', warnings[0])
        self.assertIn('czy chodziło o greeting', warnings[0])

    def test_advice_about_another_language_is_polish(self):
        warnings = MACROS.review_warnings('while x > 3')
        self.assertIn('nie należy do języka skryptowego Titana', warnings[0])
        self.assertIn("użyj 'repeat", warnings[0])

    def test_the_sections_are_polish(self):
        answer = str(MACROS.action_check_macro(
            script='set greeting = "x"\nsay "{{greting}}"', use_ai=False))
        self.assertIn('Uruchomi się, ale wygląda źle:', answer)

    def test_a_clean_macro_is_told_so_in_polish(self):
        answer = str(MACROS.action_check_macro(script='say "x"', use_ai=False))
        self.assertIn('Makro jest w porządku', answer)

    def test_a_parse_error_is_polish(self):
        problems = MACROS.check_tcs('repeat 3\n')
        self.assertTrue(problems[0].startswith('linia 1:'), problems)

    def test_the_wording_comes_from_the_macro_component(self):
        # Not from languages/*.po - the macro manager owns what it says.
        with open(os.path.join(_LANGUAGES_DIR, 'pl', 'LC_MESSAGES',
                               'macros.po'), encoding='utf-8') as handle:
            catalogue = handle.read()
        for msgid in ('line {number}: {message}', 'Would not run:',
                      'The AI also read it and noticed (advisory):'):
            self.assertIn(f'msgid "{msgid}"', catalogue)

    def test_the_ai_is_asked_to_answer_in_that_language(self):
        seen = {}
        import src.ai.ai_provider as provider
        saved = provider.generate

        def _generate(system, prompt, **kwargs):
            seen['system'] = system
            return "linia 2: notatka powstaje, zanim pada pytanie o tytuł"

        provider.generate = _generate
        try:
            notes = MACROS.review_with_ai('say "x"')
        finally:
            provider.generate = saved
        self.assertIn('Polish', seen['system'])
        self.assertIn("'linia'", seen['system'])
        # ...and a Polish finding is still recognised as a finding.
        self.assertEqual(1, len(notes), notes)


class TheAiCorrectsWhatItFound(unittest.TestCase):
    """After the review, the AI mends the macro and checks its own mending -
    and a macro with nothing wrong costs nothing at all."""

    def setUp(self):
        self._ai_on = MACROS._ai_features_on
        MACROS._ai_features_on = lambda: True
        self.asked = []

    def tearDown(self):
        MACROS._ai_features_on = self._ai_on

    def _with_provider(self, answers):
        """Run fix_with_ai against a scripted model."""
        import src.ai.ai_provider as provider
        saved = provider.generate
        replies = list(answers)

        def _generate(system, prompt, **kwargs):
            self.asked.append(prompt)
            return replies.pop(0) if replies else "OK"

        provider.generate = _generate
        try:
            return MACROS.fix_with_ai(self.script)
        finally:
            provider.generate = saved

    def test_a_clean_macro_is_not_sent_anywhere(self):
        self.script = 'set x = "a"\nsay "{{x}}"'
        original = MACROS.review_with_ai
        MACROS.review_with_ai = lambda text, actions='': []
        try:
            fixed, problems, warnings, notes, rounds = self._with_provider([])
        finally:
            MACROS.review_with_ai = original
        self.assertEqual(self.script, fixed)
        self.assertEqual(0, rounds)
        self.assertEqual([], self.asked)      # nothing was asked of a model
        self.assertEqual(([], [], []), (problems, warnings, notes))

    def test_it_corrects_and_stops_when_nothing_is_left(self):
        self.script = 'set greeting = "Hello"\nsay "{{greting}}"'
        original = MACROS.review_with_ai
        MACROS.review_with_ai = lambda text, actions='': []
        try:
            fixed, problems, warnings, notes, rounds = self._with_provider([
                'set greeting = "Hello"\nsay "{{greeting}}"'])
        finally:
            MACROS.review_with_ai = original
        self.assertIn('{{greeting}}', fixed)
        self.assertEqual(1, rounds)
        self.assertEqual(([], [], []), (problems, warnings, notes))
        # One round was enough, so only one request was made.
        self.assertEqual(1, len(self.asked))

    def test_a_correction_that_is_worse_is_refused(self):
        self.script = 'set greeting = "Hello"\nsay "{{greting}}"'
        original = MACROS.review_with_ai
        MACROS.review_with_ai = lambda text, actions='': []
        try:
            fixed, _p, warnings, _n, _rounds = self._with_provider([
                'say "{{one}}"\nsay "{{two}}"\nsay "{{three}}"'])
        finally:
            MACROS.review_with_ai = original
        self.assertEqual(self.script, fixed)
        self.assertEqual(1, len(warnings), warnings)

    def test_a_code_fence_the_model_was_told_not_to_use_is_stripped(self):
        self.assertEqual('say "x"\n',
                         MACROS._tcs_strip_fences('```\nsay "x"\n```'))
        self.assertEqual('say "x"\n', MACROS._tcs_strip_fences('say "x"'))

    def test_it_does_nothing_with_the_ai_off(self):
        MACROS._ai_features_on = lambda: False
        script = 'set greeting = "x"\nsay "{{greting}}"'
        fixed, _p, warnings, _n, rounds = MACROS.fix_with_ai(script)
        self.assertEqual(script, fixed)
        self.assertEqual(0, rounds)
        self.assertTrue(warnings)

    def test_the_action_says_so_when_there_was_nothing_to_correct(self):
        original = MACROS.review_with_ai
        MACROS.review_with_ai = lambda text, actions='': []
        try:
            answer = str(MACROS.action_fix_macro(script='say "x"'))
        finally:
            MACROS.review_with_ai = original
        self.assertIn('nothing to correct', answer)

    def test_the_action_refuses_with_the_ai_off(self):
        MACROS._ai_features_on = lambda: False
        result = MACROS.action_fix_macro(script='say "{{x}}"')
        self.assertIn('AI features', str(getattr(result, 'reason', result)))


class _Result:
    def __init__(self, ok, text):
        self.ok, self.text = ok, text


class TheCreationKitBuildsMacros(unittest.TestCase):
    """6. Programmer -> AI -> Macro writes a script, not a Python add-on."""

    @classmethod
    def setUpClass(cls):
        try:
            from src.ai import ai_creation_kit, creation_docs
        except Exception as e:                   # pragma: no cover - no wx
            raise unittest.SkipTest(f"the creation kit is not importable: {e}")
        cls.kit, cls.docs = ai_creation_kit, creation_docs

    def setUp(self):
        # The kit asks the macro manager whether a script would run; here that
        # answer is scripted, so the test needs neither Titan nor a model.
        import src.titan_core as core
        self._actions = getattr(core, 'actions', None)
        self.fake = types.ModuleType('fake_actions')
        core.actions = self.fake

    def tearDown(self):
        import src.titan_core as core
        if self._actions is not None:
            core.actions = self._actions

    def test_the_kind_is_wired_up(self):
        kind = self.kit.get_kind('macro')
        self.assertIsNotNone(kind)
        self.assertEqual('macros', kind['subdir'])
        self.assertEqual('__macro__.TCE', self.kit.primary_manifest(kind))
        self.assertFalse(kind['package'])

    def test_the_prompt_asks_for_a_script_not_python(self):
        prompt = self.kit.build_system_prompt(self.kit.get_kind('macro'),
                                              allow_questions=False)
        self.assertIn('__macro__.TCE', prompt)
        self.assertIn('Write NO Python', prompt)
        self.assertIn('Do NOT write pseudocode', prompt)
        self.assertNotIn('__actions.json', prompt)

    def test_other_kinds_keep_their_python_rules(self):
        prompt = self.kit.build_system_prompt(self.kit.get_kind('component'),
                                              allow_questions=False)
        self.assertIn('MUST be valid Python', prompt)
        self.assertNotIn('Write NO Python', prompt)

    def test_a_macro_needs_a_script_file(self):
        kind = self.kit.get_kind('macro')
        files = {'__macro__.TCE': '[macro]\nname_en = Morning\n'
                                  'name_pl = Poranek\nopenfile = m.tcs\n',
                 'm.tcs': 'say "good morning"\n'}
        self.assertTrue(self.kit.validate_files(kind, files)[0])
        self.assertFalse(self.kit.validate_files(
            kind, {'__macro__.TCE': '[macro]\n'})[0])
        self.assertEqual('Morning', self.kit._derive_name(kind, files))

    def test_generated_scripts_are_checked_by_the_macro_manager(self):
        def _run(_addon, _name, **kwargs):
            if 'rate=100' in kwargs.get('script', ''):
                return _Result(False,
                               "The macro would not run:\n"
                               "- line 2: rate 100 is outside what Titan's "
                               "speech takes\n\nHow to write one:\n"
                               "- Read macros.macro_language first.\n")
            return _Result(True, "The macro is fine.")

        self.fake.run = _run
        problems = self.kit.static_check({'m.tcs': 'say "x"\nvoice rate=100\n'})
        self.assertEqual(1, len(problems), problems)
        self.assertIn('line 2', problems[0])
        self.assertTrue(problems[0].startswith('m.tcs:'), problems[0])
        self.assertNotIn('macro_language', problems[0])
        self.assertEqual([], self.kit.static_check({'m.tcs': 'say "x"\n'}))

    def test_a_generated_macro_made_of_pseudocode_is_a_problem(self):
        def _run(_addon, _name, **_kwargs):
            return _Result(True, "The macro would run, but these lines are "
                                 "written in words and need AI features on "
                                 "every time it runs:\n- line 1: say hello\n")

        self.fake.run = _run
        problems = self.kit.static_check({'m.tcs': 'do "say hello"\n'})
        self.assertEqual(1, len(problems), problems)
        self.assertIn('real actions', problems[0])

    def test_the_documentation_comes_from_the_macro_manager(self):
        def _run(_addon, name, **_kwargs):
            if name == 'macro_language':
                return _Result(True, 'LANGUAGE REFERENCE')
            if name == 'macro_actions':
                return _Result(True, 'titan.speak(text, position, rate)')
            return _Result(False, '')

        self.fake.run = _run
        docs = self.docs.build_docs_block('macro')
        self.assertIn('LANGUAGE REFERENCE', docs)
        self.assertIn('titan.speak(text, position', docs)
        self.assertIn('does not exist', docs)
        self.assertNotIn('wxPython', docs)


if __name__ == '__main__':
    unittest.main(verbosity=2)
