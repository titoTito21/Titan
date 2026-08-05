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
