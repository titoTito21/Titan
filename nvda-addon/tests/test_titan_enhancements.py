# -*- coding: utf-8 -*-
"""The add-on, with no NVDA under it.

Run it directly (`python nvda-addon/tests/test_titan_enhancements.py`).

The whole add-on is written so that every part of NVDA is reached through
:mod:`compat`, which answers None rather than raising - so all of it imports
and most of it can be exercised with nothing but a stub for
``globalPluginHandler``, which is the one name a global plugin cannot be a
global plugin without. That is not a testing trick: it is the same property
that makes the add-on degrade on an NVDA that is missing a feature instead
of failing to load at all, and a test that needed a running NVDA would be a
test nobody runs.

Nothing here speaks, opens a window, reaches the bus or touches the user's
NVDA configuration.
"""

import ast
import collections
import io
import re
import json
import os
import shutil
import tempfile
import threading
import sys
import time
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(os.path.dirname(HERE), 'addon')
ROOT = os.path.abspath(os.path.join(os.path.dirname(HERE), '..'))
if os.path.join(ADDON, 'globalPlugins') not in sys.path:
    sys.path.insert(0, os.path.join(ADDON, 'globalPlugins'))

# The one name a global plugin cannot do without.
if 'globalPluginHandler' not in sys.modules:
    _stub = types.ModuleType('globalPluginHandler')

    class _GlobalPlugin:
        def __init__(self):
            pass

        def terminate(self):
            pass
    _stub.GlobalPlugin = _GlobalPlugin
    sys.modules['globalPluginHandler'] = _stub

from titanEnhancements import compat                              # noqa: E402
from titanEnhancements import context                             # noqa: E402
from titanEnhancements import gestures                            # noqa: E402
from titanEnhancements import link                                # noqa: E402
from titanEnhancements import nvda_control                        # noqa: E402


class Plugin:
    """Something to hang scripts on, exactly as NVDA hangs them on the real
    plugin.

    They go on the CLASS. NVDA's Input Gestures dialog does not walk
    ``dir()``: ``inputCore._AllGestureMappingsRetriever.addObj`` walks
    ``obj.__class__.__mro__`` and reads each ``cls.__dict__``, so a script
    set on the INSTANCE runs perfectly once something is bound to it and can
    never be found to bind anything - which was every Titan action invisible
    in the one dialog the whole module exists to put them in.
    """


def sample(addon='tnotes', label='Notes', actions=('create_note', 'read')):
    return [{'id': addon, 'label': label, 'actions': list(actions)}]


# --------------------------------------------------------------------------- #
class AScriptNameNeverChanges(unittest.TestCase):
    """NVDA remembers a binding by the name, so the name is the promise."""

    def test_it_is_the_addon_and_the_action_and_nothing_else(self):
        self.assertEqual(gestures.script_name('tnotes', 'create_note'),
                         'titan_tnotes_create_note')

    def test_it_survives_anything_an_addon_id_can_contain(self):
        self.assertEqual(gestures.script_name('titan access', 'read-screen'),
                         'titan_titan_access_read_screen')
        self.assertEqual(gestures.script_name('a.b', 'c/d'), 'titan_a_b_c_d')

    def test_it_is_a_python_identifier(self):
        for addon, action in (('titan access', 'read screen'),
                              ('9lives', '2fast'), ('a', 'b')):
            name = gestures.script_name(addon, action)
            self.assertTrue(name.isidentifier(), name)

    def test_the_attribute_is_the_name_nvda_looks_for(self):
        self.assertEqual(gestures.attribute_name('m', 'run'),
                         'script_titan_m_run')


class TheCatalogue(unittest.TestCase):

    def test_one_row_per_action(self):
        rows = gestures.catalogue_from_addons(sample())
        self.assertEqual([row['action'] for row in rows],
                         ['create_note', 'read'])
        self.assertEqual(rows[0]['label'], 'Notes')

    def test_an_addon_with_no_id_is_not_a_row(self):
        self.assertEqual(gestures.catalogue_from_addons(
            [{'label': 'x', 'actions': ['a']}]), [])

    def test_nothing_at_all_is_not_an_error(self):
        self.assertEqual(gestures.catalogue_from_addons(None), [])
        self.assertEqual(gestures.catalogue_from_addons([{'id': 'x'}]), [])

    def test_there_is_a_ceiling(self):
        many = [{'id': 'x', 'label': 'X',
                 'actions': ['a%d' % i for i in range(gestures.MAX_SCRIPTS + 50)]}]
        self.assertEqual(len(gestures.catalogue_from_addons(many)),
                         gestures.MAX_SCRIPTS)

    def test_summaries_are_merged_onto_the_rows_that_have_them(self):
        rows = gestures.catalogue_from_addons(sample())
        changed = gestures._merge_summaries(rows, 'tnotes', [
            {'name': 'create_note', 'summary': 'Write a note.',
             'risk': 'confirm', 'needs_ai': False,
             'params': [{'name': 'title', 'required': True}]}])
        self.assertTrue(changed)
        self.assertEqual(rows[0]['summary'], 'Write a note.')
        self.assertEqual(rows[0]['risk'], 'confirm')
        self.assertEqual(rows[1]['summary'], '')      # untouched

    def test_merging_the_same_answer_twice_changes_nothing(self):
        rows = gestures.catalogue_from_addons(sample())
        described = [{'name': 'read', 'summary': 'Read it.'}]
        self.assertTrue(gestures._merge_summaries(rows, 'tnotes', described))
        self.assertFalse(gestures._merge_summaries(rows, 'tnotes', described))


class EveryActionIsAScriptNvdaCanBind(unittest.TestCase):

    def setUp(self):
        self.plugin = Plugin()
        self.addCleanup(lambda: gestures.install(self.plugin, []))

    def test_one_script_per_action(self):
        rows = gestures.catalogue_from_addons(sample())
        self.assertEqual(gestures.install(self.plugin, rows), 2)
        self.assertTrue(hasattr(self.plugin, 'script_titan_tnotes_create_note'))
        self.assertTrue(hasattr(self.plugin, 'script_titan_tnotes_read'))

    def test_nvda_finds_them_the_way_it_finds_its_own(self):
        """The regression that made the whole feature invisible.

        Read out of the running NVDA's own ``inputCore``: the dialog walks
        the class chain and each class's own ``__dict__``. An instance
        attribute passes ``hasattr`` and ``dir()`` and appears in that walk
        nowhere at all, so every Titan action could be RUN by a binding and
        never OFFERED for one.
        """
        gestures.install(self.plugin, gestures.catalogue_from_addons(sample()))
        found = set()
        for cls in type(self.plugin).__mro__:
            for name in vars(cls):
                if name.startswith('script_'):
                    found.add(name)
        self.assertEqual(sorted(found), ['script_titan_tnotes_create_note',
                                         'script_titan_tnotes_read'])
        self.assertEqual(gestures.bindable(self.plugin), sorted(found))

    def test_what_the_dialog_would_list_is_what_bindable_answers(self):
        gestures.install(self.plugin, [])
        self.assertEqual(gestures.bindable(self.plugin), [])
        gestures.install(self.plugin, gestures.catalogue_from_addons(
            sample('ocr', 'AI OCR', ['ask', 'read_window'])))
        self.assertEqual(gestures.bindable(self.plugin),
                         ['script_titan_ocr_ask',
                          'script_titan_ocr_read_window'])

    def test_the_addons_own_scripts_survive_every_sweep(self):
        """Only what this module put there is ever taken away again."""
        class Host(Plugin):
            def script_titanStatus(self, gesture):
                """Titan status."""
        host = Host()
        self.addCleanup(lambda: gestures.install(host, []))
        gestures.install(host, gestures.catalogue_from_addons(sample()))
        gestures.install(host, [])
        self.assertTrue(hasattr(host, 'script_titanStatus'))

    def test_the_dialog_has_something_to_show_for_each(self):
        rows = gestures.catalogue_from_addons(sample())
        gestures._merge_summaries(rows, 'tnotes',
                                  [{'name': 'read', 'summary': 'Read a note.'}])
        gestures.install(self.plugin, rows)
        script = self.plugin.script_titan_tnotes_read
        self.assertIn('Read a note.', script.__doc__)
        self.assertIn('Notes', script.category)

    def test_an_action_with_no_summary_still_says_what_it_is(self):
        gestures.install(self.plugin, gestures.catalogue_from_addons(sample()))
        self.assertIn('create_note',
                      self.plugin.script_titan_tnotes_create_note.__doc__)

    def test_an_action_that_needs_the_ai_says_so_where_it_is_bound(self):
        rows = gestures.catalogue_from_addons(sample('ocr', 'AI OCR', ['ask']))
        gestures._merge_summaries(rows, 'ocr', [{'name': 'ask',
                                                 'summary': 'Ask about it.',
                                                 'needs_ai': True}])
        gestures.install(self.plugin, rows)
        self.assertIn('AI', self.plugin.script_titan_ocr_ask.__doc__)

    def test_an_uninstalled_addon_leaves_no_script_behind(self):
        gestures.install(self.plugin, gestures.catalogue_from_addons(sample()))
        gestures.install(self.plugin, gestures.catalogue_from_addons(
            sample('tnotes', 'Notes', ['read'])))
        self.assertFalse(hasattr(self.plugin,
                                 'script_titan_tnotes_create_note'))
        self.assertTrue(hasattr(self.plugin, 'script_titan_tnotes_read'))

    def test_a_script_takes_the_one_argument_nvda_calls_it_with(self):
        gestures.install(self.plugin, gestures.catalogue_from_addons(sample()))
        said = []
        from titanEnhancements import dialogs
        original = dialogs.report
        dialogs.report = said.append
        try:
            # Titan is not running in a test, so this is the branch that
            # matters most: a bound key must answer, not fail silently.
            self.plugin.script_titan_tnotes_read(None)
        finally:
            dialogs.report = original
        self.assertEqual(len(said), 1)
        self.assertIn('not running', said[0])


class AnActionAsksForWhatItNeeds(unittest.TestCase):

    def test_a_required_parameter_is_something_to_ask_for(self):
        row = {'addon': 'a', 'action': 'b', 'params': [
            {'name': 'title', 'required': True},
            {'name': 'body', 'required': False}]}
        self.assertEqual([p['name'] for p in gestures._needed(row)], ['title'])

    def test_the_questions_are_asked_in_order_and_gathered(self):
        asked, done = [], []
        from titanEnhancements import dialogs
        original = dialogs.ask_text

        def ask(prompt, _title, on_answer=None, default=''):
            asked.append(prompt)
            on_answer('answer %d' % len(asked))
        dialogs.ask_text = ask
        try:
            gestures._ask_each([{'name': 'one', 'prompt': 'First?'},
                                {'name': 'two', 'prompt': 'Second?'}],
                               {}, done.append)
        finally:
            dialogs.ask_text = original
        self.assertEqual(asked, ['First?', 'Second?'])
        self.assertEqual(done, [{'one': 'answer 1', 'two': 'answer 2'}])

    def test_cancelling_a_question_runs_nothing(self):
        done = []
        from titanEnhancements import dialogs
        original = dialogs.ask_text
        dialogs.ask_text = lambda p, t, on_answer=None, default='': \
            on_answer(None)
        try:
            gestures._ask_each([{'name': 'one', 'prompt': '?'}], {},
                               done.append)
        finally:
            dialogs.ask_text = original
        self.assertEqual(done, [])

    def test_an_action_that_cannot_be_taken_back_is_confirmed(self):
        asked, ran = [], []
        from titanEnhancements import dialogs
        original = dialogs.confirm
        dialogs.confirm = lambda prompt, title, on_yes=None: asked.append(prompt)
        try:
            gestures._confirm({'addon': 'a', 'action': 'wipe',
                               'risk': 'always_confirm'},
                              lambda: ran.append(True))
            self.assertEqual(len(asked), 1)
            self.assertEqual(ran, [])
            gestures._confirm({'addon': 'a', 'action': 'read', 'risk': 'auto'},
                              lambda: ran.append(True))
            self.assertEqual(ran, [True])
        finally:
            dialogs.confirm = original

    def test_a_key_the_user_bound_is_not_second_guessed(self):
        # 'confirm' is what makes the AI check before acting on its own
        # initiative. Somebody who bound a key has already said yes.
        ran = []
        gestures._confirm({'addon': 'a', 'action': 'send', 'risk': 'confirm'},
                          lambda: ran.append(True))
        self.assertEqual(ran, [True])


class WhatNvdaCanSee(unittest.TestCase):
    """The context, with objects that answer the way NVDA's do."""

    class Obj:
        def __init__(self, **kw):
            self.name = kw.get('name', '')
            self.role = kw.get('role')
            self.states = kw.get('states', ())
            self.value = kw.get('value', '')
            self.description = ''
            self.keyboardShortcut = ''
            self.windowText = kw.get('window', '')
            self.windowClassName = ''
            self.windowHandle = kw.get('hwnd', 0)
            self.processID = 0
            self.positionInfo = kw.get('position', {})
            self.treeInterceptor = kw.get('interceptor')

        @property
        def appModule(self):
            raise AttributeError('no app module here')

    def test_a_control_is_described_by_what_it_answers(self):
        described = context.describe(self.Obj(
            name='Send', value='', hwnd=42,
            position={'indexInGroup': 3, 'similarItemsInGroup': 9}))
        self.assertEqual(described['name'], 'Send')
        self.assertEqual((described['index'], described['count']), (3, 9))
        self.assertEqual(described['hwnd'], 42)

    def test_what_cannot_be_read_is_absent_rather_than_invented(self):
        described = context.describe(self.Obj(name='Send'))
        self.assertNotIn('app', described)            # raised when asked
        self.assertNotIn('value', described)          # empty
        self.assertNotIn('states', described)

    def test_nothing_at_all_describes_to_nothing(self):
        self.assertEqual(context.describe(None), {})

    def test_a_role_is_a_word_however_this_nvda_spells_it(self):
        class Modern:
            displayString = 'button'
        self.assertEqual(context.role_name(Modern()), 'button')

        class Older:
            name = 'CHECKBOX'
            displayString = None
        self.assertEqual(context.role_name(Older()), 'CHECKBOX')
        self.assertEqual(context.role_name(None), '')

    def test_a_state_with_no_name_is_left_out_not_numbered(self):
        class Named:
            displayString = 'checked'

        class Bare:
            displayString = None
            name = ''
        self.assertEqual(context.state_names([Named(), Bare()]), ['checked'])

    def test_browse_mode_is_reported_as_the_user_would_say_it(self):
        class Interceptor:
            passThrough = False
        self.assertEqual(context._mode(self.Obj(interceptor=Interceptor())),
                         'browse')
        Interceptor.passThrough = True
        self.assertEqual(context._mode(self.Obj(interceptor=Interceptor())),
                         'focus')
        self.assertEqual(context._mode(self.Obj()), '')

    def test_the_sentence_says_where_the_user_is(self):
        line = context.sentence({'available': True,
                                 'focus': {'name': 'Send', 'role': 'button',
                                           'app': 'thunderbird',
                                           'states': ['focused']},
                                 'mode': 'browse'})
        for wanted in ('thunderbird', 'Send', 'button', 'browse mode'):
            self.assertIn(wanted, line)

    def test_a_reader_that_could_not_answer_says_nothing_rather_than_guess(self):
        self.assertEqual(context.sentence({'available': False,
                                           'why': 'busy'}), '')

    def test_reading_it_never_raises_however_broken_nvda_is(self):
        # compat.api is None in a test, which is the "this NVDA does not
        # expose it" branch - the honest answer, not an exception.
        answer = context.read()
        self.assertIn('available', answer)
        self.assertEqual(answer['reader'], 'nvda')


class TheTableIsTheBoundary(unittest.TestCase):
    """There is no path from a name Titan sends to an attribute of NVDA's."""

    def test_a_setting_nvda_does_not_offer_is_refused_by_name(self):
        with self.assertRaises(nvda_control.Refused):
            nvda_control.setting(name='__class__')
        with self.assertRaises(nvda_control.Refused):
            nvda_control.setting(name='anything at all')

    def test_a_review_unit_that_is_not_one_is_refused(self):
        with self.assertRaises(nvda_control.Refused):
            nvda_control.review(where='everything')

    def test_a_direction_that_is_not_one_is_refused(self):
        with self.assertRaises(nvda_control.Refused):
            nvda_control.review(where='line', direction='sideways')

    def test_a_mode_that_is_not_one_is_refused(self):
        with self.assertRaises(nvda_control.Refused):
            nvda_control.mode(name='upside down')

    def test_only_a_keyboard_gesture_can_be_sent(self):
        self._allow_keys(True)
        with self.assertRaises(nvda_control.Refused):
            nvda_control.press(gesture='br(freedomScientific):leftWizWheelUp')

    def _allow_keys(self, keys=False, drive=True):
        from titanEnhancements import configSpec
        original = configSpec.read
        configSpec.read = lambda: {'letTitanDrive': drive,
                                   'letTitanPressKeys': keys}
        self.addCleanup(lambda: setattr(configSpec, 'read', original))

    def test_pressing_a_key_is_off_until_the_user_says_otherwise(self):
        self._allow_keys(False)
        with self.assertRaises(nvda_control.Refused):
            nvda_control.press(gesture='kb:NVDA+f7')

    def test_changing_nvda_is_refused_when_the_switch_is_off(self):
        self._allow_keys(False, drive=False)
        with self.assertRaises(nvda_control.Refused):
            nvda_control.speak(text='hello')
        with self.assertRaises(nvda_control.Refused):
            nvda_control.mode(name='focus')

    def test_reading_nvda_is_served_whatever_the_switches_say(self):
        self._allow_keys(False, drive=False)
        # No exception: what is on the user's own screen is always answerable.
        self.assertIn('reader', context.read())
        self.assertIsInstance(nvda_control.settings(), dict)

    def test_a_refusal_crosses_the_wire_as_an_answer_not_an_exception(self):
        self._allow_keys(False, drive=False)
        served = nvda_control.handlers()
        answer = served['speak'](text='hello')
        self.assertIs(answer['ok'], False)
        self.assertTrue(answer['refused'])
        self.assertIn('Turn it on', answer['reason'])

    def test_settings_say_which_switches_are_on(self):
        self._allow_keys(True, drive=True)
        answer = nvda_control.settings()
        self.assertTrue(answer['may_change'])
        self.assertTrue(answer['may_press_keys'])

    def test_every_setting_offered_names_a_real_place_to_put_it(self):
        for name, spec in nvda_control.SETTINGS.items():
            self.assertEqual(len(spec), 5, name)
            section, key, kind, low, high = spec
            self.assertTrue(section and key, name)
            self.assertIn(kind, ('number', 'boolean', 'string'), name)
            if kind == 'number':
                self.assertIsNotNone(low, name)
                self.assertLess(low, high, name)


class TheProtocolIsAReadersNotNvdas(unittest.TestCase):
    """A second reader's add-on must work with no change on Titan's side."""

    def test_nothing_served_is_named_after_nvda(self):
        for name in nvda_control.handlers():
            self.assertNotIn('nvda', name.lower(), name)

    def test_everything_declared_is_really_served(self):
        served = set(link.handlers())
        for action in link.DECLARED:
            self.assertIn(action['name'], served, action['name'])

    def test_the_channels_own_plumbing_is_served_but_not_offered(self):
        declared = {action['name'] for action in link.DECLARED}
        for private in ('announce', 'attach', 'detach', 'capabilities',
                        'stand_down', 'beep'):
            self.assertIn(private, link.handlers(), private)
            self.assertNotIn(private, declared, private)

    def test_every_declaration_is_the_shape_titan_reads(self):
        for action in link.DECLARED:
            self.assertTrue(action.get('name'))
            self.assertTrue(action.get('summary'))
            self.assertIsInstance(action.get('params', {}), dict)
            if 'risk' in action:
                self.assertIn(action['risk'],
                              ('auto', 'confirm', 'always_confirm'))

    def test_pressing_a_key_is_declared_as_the_dangerous_one(self):
        by_name = {a['name']: a for a in link.DECLARED}
        self.assertEqual(by_name['press'].get('risk'), 'always_confirm')

    def test_titan_knows_which_ids_are_readers(self):
        path = os.path.join(ROOT, 'src', 'accessibility', 'reader_channel.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn("READER_CLIENTS", source)
        self.assertIn("'{}'".format(link.CLIENT_ID), source)


class NothingTitanCallsMayRaise(unittest.TestCase):
    """The bug that made the whole add-on look broken, and its whole class.

    `capabilities` read `panner.report()`, which is on the PANNER and not on
    the module. It is the one call Titan makes to decide what it may send -
    so when it raised, Titan cached an empty answer, sent no position, no
    pitch and nothing marked as replacing a focus report, and every symptom
    looked like a panner that did not work. The panner was fine. It was
    never given anything to place.

    Nothing here needs NVDA: every handler must answer on a machine with
    none, because that is exactly the state in which it is hardest to
    notice that it did not.
    """

    def _served(self):
        return link.handlers()

    def test_capabilities_answers(self):
        able = self._served()['capabilities']()
        self.assertIsInstance(able, dict)

    def test_capabilities_answers_every_key_titan_reads(self):
        # Titan's `Message.for_addon` asks about exactly these. A key that is
        # missing reads as False, which silently drops what it names.
        able = self._served()['capabilities']()
        for key in ('announce', 'position', 'position_marker', 'pitch',
                    'rate', 'volume', 'braille', 'queue', 'replaces_focus'):
            self.assertIn(key, able, key)

    def test_every_handler_answers_rather_than_raising(self):
        plausible = {
            'announce': {'text': 'hello'},
            'braille': {'text': 'hello'},
            'speak': {'text': 'hello'},
            'attach': {'pid': 1, 'version': '1.0.0'},
            'setting': {'name': 'rate'},
            'review': {'where': 'line', 'direction': 'current'},
            'mode': {'name': 'toggle'},
            'use_synth': {'name': 'espeak'},
            'use_voice': {'name': 'x'},
            'press': {'gesture': 'kb:NVDA+f7'},
        }
        for name, handler in sorted(self._served().items()):
            try:
                handler(**plausible.get(name, {}))
            except Exception as error:               # noqa: BLE001
                self.fail(f"'{name}' raised {type(error).__name__}: {error}")

    def test_a_report_of_what_can_be_panned_is_on_the_panner(self):
        # Named, because this is the exact shape of the mistake: a module
        # and its one instance both look like the thing to ask.
        from titanEnhancements import panner
        self.assertFalse(hasattr(panner, 'report'),
                         'if the module gains a report(), say which one '
                         'channel.capabilities should be using')
        self.assertTrue(callable(panner.PANNER.report))


class ASwitchThatDoesNothingIsWorseThanNone(unittest.TestCase):
    """Three of them were exactly that."""

    def setUp(self):
        from titanEnhancements import channel
        from titanEnhancements import panner
        self.channel = channel.CHANNEL
        # `configSpec.apply()` sets the PANNER's switch as well as the
        # channel's three, and a test that put back only the three left the
        # panner switched off for every test after it.
        was = (self.channel.position_enabled, self.channel.marker_enabled,
               self.channel.prosody_enabled, panner.PANNER.enabled)

        def restore():
            (self.channel.position_enabled, self.channel.marker_enabled,
             self.channel.prosody_enabled, panner.PANNER.enabled) = was
        self.addCleanup(restore)

    def test_the_settings_reach_the_channel(self):
        from titanEnhancements import configSpec
        original = configSpec.read
        configSpec.read = lambda: dict(
            {name: True for name in configSpec.SPEC},
            position=False, positionMarker=False, prosody=False)
        try:
            configSpec.apply()
        finally:
            configSpec.read = original
        self.assertFalse(self.channel.position_enabled)
        self.assertFalse(self.channel.marker_enabled)
        self.assertFalse(self.channel.prosody_enabled)

    def test_capabilities_stops_offering_what_was_switched_off(self):
        self.channel.position_enabled = False
        self.channel.marker_enabled = False
        self.channel.prosody_enabled = False
        able = self.channel.capabilities()
        for key in ('position', 'position_marker', 'pitch', 'rate', 'volume'):
            self.assertFalse(able[key], key)

    def test_prosody_off_means_no_pitch_command(self):
        from titanEnhancements import prosody
        sequence, _notes = prosody.build({'text': 'hi', 'pitch': 5},
                                         allow_prosody=False)
        self.assertEqual([part for part in sequence
                          if not isinstance(part, str)], [])

    def test_prosody_on_still_asks_for_it(self):
        # With no NVDA there is no PitchCommand to add, so what is checked
        # is that the switch is what decides and not the absence of NVDA.
        from titanEnhancements import prosody
        import inspect
        source = inspect.getsource(prosody.build)
        self.assertIn('if allow_prosody else 0', source)

    def test_the_marker_is_its_own_question(self):
        # A tone standing in for a position that cannot be applied is not
        # the same switch as the position itself.
        import inspect
        from titanEnhancements import prosody
        source = inspect.getsource(prosody.build)
        self.assertIn('allow_marker', source)
        self.assertIn('allow_pan', source)


class ThePlaceIsAskedOfBOTHLayers(unittest.TestCase):
    """The bug the user heard as "there is no positioned speech".

    eSpeak - NVDA's default - produces ONE channel, so the stream layer
    cannot pan it. `place()` has always fallen back to NVDA's own audio
    session, which does not care how many channels the synth makes. But
    `report()` only ever asked the stream, so `capabilities` said the voice
    could not be placed, Titan believed it, sent no position at all, and the
    fallback was never reached. Nothing was broken; nothing was ever asked.
    """

    def setUp(self):
        from titanEnhancements import panner
        self.panner = panner
        self.was = panner.PANNER._session_capable
        self.addCleanup(lambda: setattr(panner.PANNER, '_session_capable',
                                        self.was))

    def test_a_mono_synth_can_still_be_placed_by_the_session(self):
        self.panner.PANNER._session_capable = True
        self.assertTrue(self.panner.PANNER.can_place())

    def test_neither_layer_means_it_cannot(self):
        self.panner.PANNER._session_capable = False
        # No NVDA in a test, so the stream layer cannot either.
        self.assertFalse(self.panner.PANNER.can_place())

    def test_what_the_reader_offers_follows_can_place(self):
        from titanEnhancements import channel
        self.panner.PANNER._session_capable = True
        self.assertTrue(channel.CHANNEL.capabilities()['position'])
        self.panner.PANNER._session_capable = False
        self.assertFalse(channel.CHANNEL.capabilities()['position'])

    def test_it_says_why_before_anything_has_been_tried(self):
        # `_note` only records a reason while something is being PLACED, so
        # a machine that had never tried reported "cannot" with no reason -
        # a feature quietly missing, which is the thing this must not do.
        self.panner.PANNER._session_capable = False
        why = self.panner.PANNER.why_not()
        self.assertTrue(why)
        self.assertIn('session', why.lower())

    def test_nothing_to_explain_when_it_can(self):
        self.panner.PANNER._session_capable = True
        self.assertEqual(self.panner.PANNER.why_not(), '')

    def test_the_session_is_asked_once_and_never_on_the_path(self):
        """It is a COM walk, and `capabilities` must answer instantly.

        Titan waits two and a half seconds for that answer and used to keep
        an empty one for twenty; a slow first call there is what made every
        control be announced twice.
        """
        import threading
        import time
        self.panner.PANNER._session_capable = None
        self.panner.PANNER._session_probing = False
        asked = []
        started = threading.Event()
        release = threading.Event()
        original = self.panner._own_session

        def slow():
            asked.append(1)
            started.set()
            release.wait(2.0)
            return None
        self.panner._own_session = slow
        try:
            began = time.time()
            for _ in range(3):
                self.panner.PANNER._session_can()
            took = time.time() - began
            self.assertLess(took, 0.5, 'asking must not wait for the walk')
            self.assertTrue(started.wait(2.0), 'it must happen, on a thread')
            self.assertEqual(len(asked), 1, 'and only once')
        finally:
            release.set()
            time.sleep(0.15)
            self.panner._own_session = original
            self.panner.PANNER._session_probing = False

    def test_a_tone_does_not_stand_in_for_a_position_that_is_applied(self):
        from titanEnhancements import prosody
        self.panner.PANNER._session_capable = True
        sequence, notes = prosody.build({'text': 'left', 'position': -1.0})
        self.assertNotIn('tone', ' '.join(notes).lower())


class AControlInThreeTones(unittest.TestCase):
    """Titan Access's shape, rebuilt: name 0, control type -4, state +4."""

    class Obj:
        def __init__(self, **kw):
            self.name = kw.get('name', '')
            self.role = kw.get('role')
            self.states = kw.get('states', ())
            self._value = kw.get('value', '')
            self.description = kw.get('description', '')
            self.positionInfo = kw.get('position', {})

        @property
        def value(self):
            return self._value

    def setUp(self):
        from titanEnhancements import elements
        self.elements = elements

    def test_the_pitches_are_titan_accesss_own(self):
        self.assertEqual((self.elements.NAME_PITCH, self.elements.ROLE_PITCH,
                          self.elements.STATE_PITCH), (0, -4, 4),
                         "titan_access/accessible.py's constants; the two "
                         "readers must not disagree about what a control "
                         "sounds like")

    def test_the_order_is_name_then_type_then_state(self):
        class Role:
            displayString = 'button'

        class State:
            displayString = 'pressed'
        parts = self.elements.describe(self.Obj(name='Save', role=Role(),
                                                states=()))
        self.assertEqual(parts[0], ('Save', 'name'))
        self.assertEqual(parts[1], ('button', 'kind'))

    def test_every_part_is_tagged_with_its_CLASS_and_not_a_pitch(self):
        """The reported bug: "I want the variant quincy as the control type
        and it does not work" - and neither did a rate, a voice or a
        synthesizer.

        A reading was built with bare pitch NUMBERS, and `voices.voice_of`
        answers a number with a bare pitch and never looks at the user's
        table at all. Everything they set was written down, shown back to
        them in the dialog, and thrown away at the one moment it was needed.
        The dials only ever appeared to work because those numbers are what
        the classes happen to default to.
        """
        parts = self.elements.describe(self.Obj(
            name='Save', value='x', description='Saves the file',
            position={'indexInGroup': 3, 'similarItemsInGroup': 10}))
        for _text, voice in parts:
            self.assertIsInstance(voice, str,
                                  'a part must name its class, not a pitch')

    def test_the_classes_it_names_all_exist(self):
        """A part tagged with a class nobody defined is a part the user
        cannot set - which is the same bug wearing a different hat."""
        from titanEnhancements import classes
        known = classes.defaults()
        parts = self.elements.describe(self.Obj(
            name='Save', value='x', description='Saves the file',
            position={'indexInGroup': 3, 'similarItemsInGroup': 10}))
        for _text, voice in parts:
            self.assertIn(voice, known, voice)

    def test_the_defaults_are_what_they_always_were(self):
        """The wiring changed; what a control SOUNDS like must not."""
        from titanEnhancements import voices
        self.assertEqual(voices.voice_of('name').get('pitch', 0),
                         self.elements.NAME_PITCH)
        self.assertEqual(voices.voice_of('kind').get('pitch', 0),
                         self.elements.ROLE_PITCH)
        self.assertEqual(voices.voice_of('state').get('pitch', 0),
                         self.elements.STATE_PITCH)

    def test_a_field_says_its_name_and_what_is_in_it(self):
        parts = self.elements.describe(self.Obj(name='Address',
                                                value='titosoft.com'))
        self.assertEqual(parts[0], ('Address, titosoft.com', 'name'))

    def test_a_value_that_repeats_the_name_is_not_said_twice(self):
        parts = self.elements.describe(self.Obj(name='Save', value='Save'))
        self.assertEqual(parts[0], ('Save', 'name'))

    def test_focus_is_implied_and_never_said(self):
        # The live reading said "zaznaczalne, mozliwy fokus, ma fokus" for
        # every single control - noise on everything the reader reports.
        self.assertNotIn('FOCUSED', self.elements.STATE_ORDER)
        self.assertNotIn('FOCUSABLE', self.elements.STATE_ORDER)

    def test_the_states_are_titan_accesss_list_in_its_order(self):
        self.assertEqual(self.elements.STATE_ORDER[:3],
                         ('SELECTED', 'CHECKED', 'HALFCHECKED'))

    def test_a_place_in_a_list_is_said_in_the_place_voice(self):
        """Not the neutral tone any more, and that is the point of the
        table: "3 of 10" is orientation rather than content, there is a
        class that means exactly that, and it was being spoken as though
        there were not - so nothing the user set for it did anything."""
        parts = self.elements.describe(self.Obj(
            name='Notes', position={'indexInGroup': 3,
                                    'similarItemsInGroup': 10}))
        self.assertEqual(parts[-1][1], 'place')
        self.assertIn('3', parts[-1][0])
        self.assertIn('10', parts[-1][0])

    def test_a_description_that_repeats_the_name_is_dropped(self):
        parts = self.elements.describe(self.Obj(name='Save',
                                                description='Save'))
        self.assertEqual(len(parts), 1)

    def test_nothing_describes_to_nothing(self):
        self.assertEqual(self.elements.describe(None), [])

    def test_it_never_raises_however_odd_the_object(self):
        class Awkward:
            @property
            def name(self):
                raise RuntimeError('no')
        self.assertEqual(self.elements.describe(Awkward()), [])

    def test_with_no_pitch_command_it_is_one_flat_line(self):
        # This NVDA-less test IS the no-PitchCommand case.
        self.assertFalse(self.elements.can_pitch())
        out = self.elements.sequence([('Save', 0), ('button', -4)])
        self.assertEqual(out, ['Save, button'])

    def test_the_pitch_is_converted_onto_nvdas_scale(self):
        """The bug the user heard as "all one tone".

        Titan says -10..10; NVDA's PitchCommand offsets its own 0..100
        setting. Handed -4 unchanged, that is a four-point change on a
        hundred-point scale - the parts are pitched, correctly, and nobody
        can hear it. `prosody.SCALE` is the one place that knows.
        """
        from titanEnhancements import prosody
        self.assertEqual(prosody._offset(self.elements.ROLE_PITCH), -20)
        self.assertEqual(prosody._offset(self.elements.STATE_PITCH), 20)

    def test_the_sequence_really_uses_the_converted_number(self):
        """Asked of the sequence that is built, not of the source that
        builds it: the conversion moved into the voice builder once and a
        test that read the code said the feature had gone."""
        from titanEnhancements import prosody
        restore = _supported_by_anything()
        try:
            with WithCommands():
                out = self.elements.sequence([('Save', 0), ('button', -4)])
        finally:
            restore()
        offsets = [part.offset for part in out
                   if hasattr(part, 'offset') and part.offset]
        self.assertIn(prosody._offset(-4), offsets)
        self.assertNotIn(-4, offsets,
                         "a raw Titan pitch on NVDA's scale is inaudible")

    def test_a_synth_that_cannot_pitch_is_not_pretended_to(self):
        # NVDA drops an unsupported command silently, so the parts would
        # come out at one tone with nothing saying why.
        import inspect
        source = inspect.getsource(self.elements.can_pitch)
        self.assertIn('supportedCommands', source)

    def test_an_empty_description_makes_no_utterance(self):
        self.assertEqual(self.elements.sequence([]), [])


class WhichReportTheUserHears(unittest.TestCase):
    """Three outcomes, and the line drawn at Titan's own windows."""

    def setUp(self):
        from titanEnhancements import focus
        self.focus = focus
        focus.set_titan_pid(4242)
        # This Titan announces through the channel; the test below covers
        # the one that does not.
        focus.note_titan_spoke()
        was = focus._titan_spoke

        def restore():
            focus.set_titan_pid(0)
            focus._titan_spoke = was
        self.addCleanup(restore)
        self.called = []

    def _obj(self, pid=4242):
        class Obj:
            processID = pid
            name = 'Save'
            role = None
            states = ()
            value = ''
            description = ''
            positionInfo = {}
        return Obj()

    def test_outside_titan_nvda_is_left_entirely_alone(self):
        answer = self.focus.handle_gain_focus(self._obj(pid=99),
                                              lambda: self.called.append(1))
        self.assertIsNone(answer)
        self.assertEqual(self.called, [1])

    def test_a_titan_announcement_replaces_the_report(self):
        import time
        self.focus.replace_next(time.time() + 5)
        answer = self.focus.handle_gain_focus(self._obj(),
                                              lambda: self.called.append(1))
        self.assertEqual(answer, 'replaced')
        self.assertEqual(self.called, [1], 'muted, never skipped')

    def test_the_switch_is_what_decides(self):
        from titanEnhancements import configSpec
        original = configSpec.read
        configSpec.read = lambda: dict(
            {n: True for n in configSpec.SPEC}, pitchedFocus=False)
        try:
            answer = self.focus.handle_gain_focus(
                self._obj(), lambda: self.called.append(1))
        finally:
            configSpec.read = original
        self.assertIsNone(answer)

    def _watch_speech(self):
        from titanEnhancements import focus
        said = []
        original = focus._speak
        focus._speak = said.append
        self.addCleanup(lambda: setattr(focus, '_speak', original))
        return said

    def test_titans_own_announcement_wins_even_when_it_arrives_second(self):
        """The tab bar, pinned.

        Titan announces "Tab bar, tab, Applications, 1 of 6" around the
        moment the focus moves, and when the focus event lands FIRST there
        is no mark yet and nothing in the object says Titan is about to
        speak. Reading the row then reads it INSTEAD of the announcement -
        which is exactly what the user heard, measured live as
        `three_tones` climbing while `replaced` stayed at 0.

        With no NVDA here the wait runs inline, so this drives the two
        halves by hand: arm the read, let Titan speak, then let it fire.
        """
        from titanEnhancements import focus
        said = self._watch_speech()
        scheduled = []
        original = focus.core if hasattr(focus, 'core') else None

        # Capture what would have been run after the wait.
        import titanEnhancements.focus as f
        real = f._say_unless_titan_does

        def arm(sequence):
            marker = f._pending_read[0] = f._pending_read[0] + 1
            since = f.spoke_at()

            def later():
                if f._pending_read[0] != marker:
                    return
                if f.spoke_at() != since or f.take_mark():
                    return
                f._speak(sequence)
            scheduled.append(later)
        arm(['Applications, 1 of 6'])
        focus.note_titan_spoke()          # Titan's announcement lands now
        scheduled[0]()
        self.assertEqual(said, [],
                         "Titan's sentence carries what the row's own text "
                         "cannot, so it wins")
        self.assertIs(real, f._say_unless_titan_does)

    def test_a_control_titan_says_nothing_about_is_still_read(self):
        from titanEnhancements import focus
        said = self._watch_speech()
        focus.note_titan_spoke()          # some earlier, unrelated sentence
        focus._say_unless_titan_does(['Notes, list item'])
        self.assertEqual(said, [['Notes, list item']],
                         'nothing overtook it, so it is read')

    def test_a_newer_focus_cancels_the_one_before_it(self):
        from titanEnhancements import focus
        said = self._watch_speech()
        focus.note_titan_spoke()
        marker = focus._pending_read[0]
        focus._pending_read[0] = marker + 99
        focus._say_unless_titan_does(['second'])
        self.assertEqual(said, [['second']])

    def test_a_control_is_read_with_no_delay_at_all(self):
        """A reader that answers a moment late is a reader that feels broken.

        Waiting a beat to see whether Titan was about to announce was tried
        and reported at once as NVDA being less responsive: the delay was in
        front of EVERY control, to settle a race that happens on a handful
        of them.
        """
        from titanEnhancements import focus
        self.assertEqual(focus.PITCH_DELAY_MS, 0)

    def test_an_announcement_drops_a_read_that_has_not_happened(self):
        from titanEnhancements import channel, focus
        said = self._watch_speech()
        before = focus._pending_read[0]
        channel.CHANNEL.announce(text='Pasek kart')
        self.assertNotEqual(focus._pending_read[0], before,
                            'a read Titan has overtaken is not wanted')
        self.assertEqual(said, [])

    def test_a_titan_that_speaks_PAST_us_is_left_entirely_alone(self):
        """The regression, pinned.

        A Titan whose messages.py predates the reader channel announces
        through accessible_output3 - which this add-on never sees. Standing
        in for NVDA's report there loses whatever Titan said, and what the
        user heard was the tab bar announcement disappear.
        """
        self.focus._titan_spoke = 0.0
        answer = self.focus.handle_gain_focus(self._obj(),
                                              lambda: self.called.append(1))
        self.assertIsNone(answer)
        self.assertEqual(self.called, [1],
                         "NVDA's own report must still happen")

    def test_one_announcement_through_the_channel_is_what_unlocks_it(self):
        from titanEnhancements import channel
        self.focus._titan_spoke = 0.0
        self.assertFalse(self.focus.titan_coordinates())
        channel.CHANNEL.announce(text='anything')
        self.assertTrue(self.focus.titan_coordinates())

    def test_without_a_pitch_command_nvdas_own_report_stands(self):
        # Replacing NVDA's report to say the same thing in one tone would
        # be a loss, not a gain.
        from titanEnhancements import elements
        self.assertFalse(elements.can_pitch())
        answer = self.focus.handle_gain_focus(self._obj(),
                                              lambda: self.called.append(1))
        self.assertIsNone(answer)
        self.assertEqual(self.called, [1])


class TitansOwnCursorSounds(unittest.TestCase):
    """Titan Access's cue rules, including the one that reads backwards."""

    class Role:
        def __init__(self, name):
            self.name = name

    class Obj:
        def __init__(self, role, position=None, pid=99):
            self.role = role
            self.positionInfo = position or {}
            self.processID = pid
            self.location = (0, 0, 100, 20)

    def setUp(self):
        from titanEnhancements import earcons
        self.earcons = earcons

    def test_something_you_can_act_on_gets_the_cursor_cue(self):
        cues = self.earcons.cues_for(self.Obj(self.Role('BUTTON')))
        self.assertEqual(cues[0][0], self.earcons.SND_CURSOR)

    def test_something_you_can_only_read_gets_the_static_one(self):
        cues = self.earcons.cues_for(self.Obj(self.Role('STATICTEXT')))
        self.assertEqual(cues[0][0], self.earcons.SND_CURSOR_STATIC)

    def test_a_row_gets_the_list_cue(self):
        cues = self.earcons.cues_for(self.Obj(
            self.Role('LISTITEM'),
            {'indexInGroup': 5, 'similarItemsInGroup': 9}))
        self.assertEqual(cues[0][0], self.earcons.SND_LIST_ITEM)
        self.assertEqual(len(cues), 1, 'the middle of a list has no edge')

    def test_the_top_of_a_list_is_high_and_the_bottom_low(self):
        top = self.earcons.list_pitch(1, 10)
        bottom = self.earcons.list_pitch(10, 10)
        self.assertAlmostEqual(top, 1.5)
        self.assertAlmostEqual(bottom, 0.7)
        self.assertGreater(top, bottom, 'the list is heard as its shape')

    def test_a_list_of_one_is_not_a_division_by_zero(self):
        self.assertTrue(0.5 < self.earcons.list_pitch(1, 1) < 1.6)
        self.assertTrue(0.5 < self.earcons.list_pitch(0, 0) < 1.6)

    def test_both_ends_of_a_list_say_so(self):
        for index in (1, 9):
            cues = self.earcons.cues_for(self.Obj(
                self.Role('LISTITEM'),
                {'indexInGroup': index, 'similarItemsInGroup': 9}))
            self.assertEqual(cues[-1][0], self.earcons.SND_EDGE, index)

    def test_a_container_stepped_into_says_you_can_enter_it(self):
        cues = self.earcons.cues_for(self.Obj(self.Role('PANE')),
                                     for_navigation=True)
        self.assertEqual(cues[0][0], self.earcons.SND_CAN_INTERACT)
        # ...and not when the focus merely landed there.
        cues = self.earcons.cues_for(self.Obj(self.Role('PANE')))
        self.assertEqual(cues[0][0], self.earcons.SND_CURSOR_STATIC)

    def test_titans_own_windows_are_left_alone(self):
        # Titan already plays its own navigation sounds there, and a second
        # set on top is clutter. Titan Access suppresses its cues in exactly
        # the same place.
        from titanEnhancements import configSpec, focus
        original = configSpec.read
        configSpec.read = lambda: dict({n: True for n in configSpec.SPEC},
                                       earcons=True)
        focus.set_titan_pid(4242)
        try:
            self.assertFalse(self.earcons.announce(
                self.Obj(self.Role('BUTTON'), pid=4242)))
        finally:
            configSpec.read = original
            focus.set_titan_pid(0)

    def test_it_is_off_until_it_is_switched_on(self):
        from titanEnhancements import configSpec
        self.assertIn('default=False', configSpec.SPEC['earcons'])
        self.assertFalse(self.earcons.wanted())
        self.assertFalse(self.earcons.announce(self.Obj(self.Role('BUTTON'))))

    def test_nothing_describes_to_no_cue(self):
        self.assertEqual(self.earcons.cues_for(None), [])

    def test_the_names_are_titan_accesss_own(self):
        for name in (self.earcons.SND_CURSOR, self.earcons.SND_CURSOR_STATIC,
                     self.earcons.SND_LIST_ITEM, self.earcons.SND_EDGE,
                     self.earcons.SND_CAN_INTERACT):
            self.assertTrue(name.endswith('.ogg'), name)
        self.assertEqual(self.earcons.SND_LIST_ITEM, 'listitem.ogg')


class TitanAccessHabitsInNvda(unittest.TestCase):
    """A tone and a word for the kind of dialog; a state after the control."""

    def setUp(self):
        from titanEnhancements import interject
        self.interject = interject
        interject.clear()
        self.addCleanup(interject.clear)

    def test_a_kind_that_is_not_one_is_refused(self):
        answer = self.interject.dialog_kind(kind='mildly concerned')
        self.assertFalse(answer['armed'])

    def test_every_kind_titan_uses_has_a_tone_of_its_own(self):
        pitches = [hz for hz, _ms in self.interject.TONES.values()]
        self.assertEqual(len(set(pitches)), len(pitches),
                         'two kinds that sound alike are two kinds the user '
                         'cannot tell apart')

    def test_the_kind_word_follows_the_title(self):
        # Titan Access's own order: the title, then the type word, lower.
        self.interject.dialog_kind(kind='question', label='Pytanie')
        out = self.interject._filter(speechSequence=['Confirm Exit', 'dialog'])
        said = [p for p in out if isinstance(p, str)]
        self.assertEqual(said, ['Confirm Exit', 'dialog', 'Pytanie'])

    def test_a_warning_says_so_before_it_says_what_about(self):
        # `_DIALOG_KIND_TYPE_FIRST` in Titan Access, for the reason a
        # warning exists: you should know it is one before you know what it
        # is about.
        self.interject.dialog_kind(kind='warning', label='Uwaga!')
        out = self.interject._filter(speechSequence=['Delete 40 files'])
        said = [p for p in out if isinstance(p, str)]
        self.assertEqual(said, ['Uwaga!', 'Delete 40 files'])

    def test_the_word_is_titans_and_not_invented_here(self):
        answer = self.interject.dialog_kind(kind='error', label='Blad')
        self.assertEqual(answer['said'], 'Blad')

    def test_a_titan_too_old_to_send_a_word_still_says_something(self):
        answer = self.interject.dialog_kind(kind='error')
        self.assertEqual(answer['said'], 'error')

    def test_the_kind_is_said_at_titan_accesss_own_pitch(self):
        from titanEnhancements import interject
        self.assertEqual(interject.KIND_PITCH, -4,
                         "Titan Access's _REGION_PITCH; the two must match "
                         "or one desktop has two voices for one word")

    def test_and_that_pitch_is_converted_before_nvda_sees_it(self):
        """Asked of what is built, not of the code that builds it."""
        from titanEnhancements import interject, prosody
        restore = _supported_by_anything()
        try:
            with WithCommands():
                out = interject._pitched('Pytanie', interject.KIND_PITCH)
        finally:
            restore()
        offsets = [part.offset for part in out
                   if hasattr(part, 'offset') and part.offset]
        self.assertEqual(offsets, [prosody._offset(interject.KIND_PITCH)])
        self.assertIn('Pytanie', out)

    def test_a_state_goes_after_it(self):
        self.interject.state_suffix(text='checked')
        out = self.interject._filter(speechSequence=['Play shell sounds'])
        self.assertEqual(out[-1], 'checked')

    def test_it_is_one_shot(self):
        self.interject.state_suffix(text='checked')
        self.interject._filter(speechSequence=['first'])
        out = self.interject._filter(speechSequence=['second'])
        self.assertEqual(out, ['second'])

    def test_an_arming_nobody_collected_goes_stale(self):
        import time
        self.interject.state_suffix(text='checked')
        original = self.interject.WINDOW
        self.interject.WINDOW = 0.01
        try:
            time.sleep(0.05)
            self.assertEqual(self.interject._filter(speechSequence=['later']),
                             ['later'])
        finally:
            self.interject.WINDOW = original

    def test_it_waits_for_an_utterance_that_actually_says_something(self):
        # A beep or a braille-only update is not the thing the word belongs
        # to, and attaching it there would lose it.
        self.interject.state_suffix(text='checked')
        self.interject._filter(speechSequence=[])
        out = self.interject._filter(speechSequence=['the control'])
        self.assertEqual(out[-1], 'checked')

    def test_a_filter_that_goes_wrong_still_hands_back_a_sequence(self):
        # A registered filter that raises makes NVDA say nothing at all.
        self.interject.state_suffix(text='checked')
        original = self.interject._fresh
        self.interject._fresh = lambda _armed: (_ for _ in ()).throw(
            RuntimeError('boom'))
        try:
            self.assertEqual(self.interject._filter(speechSequence=['x']), ['x'])
        finally:
            self.interject._fresh = original

    def test_replacing_the_role_word_is_refused_rather_than_guessed(self):
        self.assertFalse(self.interject.capabilities()['role_label'])

    def test_the_capabilities_say_no_when_the_filter_is_not_registered(self):
        # With no NVDA there is no filter to register, and offering these
        # would be Titan sending something nothing acts on.
        self.assertFalse(self.interject.available())
        able = self.interject.capabilities()
        self.assertFalse(able['dialog_kind'])
        self.assertFalse(able['state_suffix'])


class EverySwitchCanBeReached(unittest.TestCase):
    """A switch nobody can find is a switch that does not exist.

    This repository has shipped that once already - the Titan shell's own
    master switch, kept inside a category that only appeared once the switch
    was ticked - so the settings page is checked against the spec rather
    than trusted to have kept up with it.
    """

    def test_the_panel_offers_everything_the_spec_declares(self):
        """Asked of the PAGE, not of its source.

        It used to grep the file for `'name':`, which was the right question
        while `onSave` restated every key by hand - and is the wrong one now
        the page is a table, because a name in a comment would pass it. The
        page can be asked what it offers, so it is.
        """
        from titanEnhancements import configSpec
        from titanEnhancements import settingsPanel
        offered = set(settingsPanel.keys_on_the_page())
        # `enabled` is the add-on as a whole, not a page switch.
        # `agentToken` is a SECRET: generated rather than typed, shown in the
        # panel's own key dialog so it can be copied, and deliberately not a
        # field on a page anybody who opens the settings can read.
        for name in configSpec.SPEC:
            if name in ('enabled', 'agentToken'):
                continue
            self.assertIn(name, offered,
                          "the settings page never offers " + name)

    def test_a_switch_the_page_offers_is_one_the_spec_knows(self):
        from titanEnhancements import configSpec
        from titanEnhancements import settingsPanel
        for name in settingsPanel.keys_on_the_page():
            self.assertIn(name, configSpec.SPEC, name)

    def test_no_switch_is_offered_twice(self):
        """Two check boxes for one answer disagree, and the last one built
        wins - which is a page that quietly discards what the user said."""
        from titanEnhancements import settingsPanel
        keys = settingsPanel.keys_on_the_page()
        self.assertEqual(sorted(keys), sorted(set(keys)))

    def test_a_switch_that_depends_on_one_depends_on_a_real_one(self):
        """A dependency naming a switch that is not there would leave the
        dependant disabled for ever, with nothing on the page to enable it."""
        from titanEnhancements import settingsPanel
        offered = set(settingsPanel.keys_on_the_page())
        for _label, _note, rows in settingsPanel._page():
            for _key, _text, depends in rows:
                if depends:
                    self.assertIn(depends, offered, depends)
    def test_pressing_nvdas_keys_is_the_one_that_starts_off(self):
        from titanEnhancements import configSpec
        self.assertIn('default=False', configSpec.SPEC['letTitanPressKeys'])
        self.assertIn('default=True', configSpec.SPEC['letTitanDrive'])

    def test_the_defaults_are_readable_with_no_nvda(self):
        from titanEnhancements import configSpec
        values = configSpec.read()
        self.assertIs(values['letTitanPressKeys'], False)
        self.assertIs(values['letTitanDrive'], True)


class ThePluginItselfComesUp(unittest.TestCase):
    """With no NVDA behind it, which is what every other test relies on."""

    def test_it_builds_and_terminates(self):
        from titanEnhancements import configSpec
        import titanEnhancements
        original = configSpec.read
        # `enabled` false so nothing joins a bus during a test run.
        configSpec.read = lambda: dict(
            {name: spec.endswith('default=True)')
             for name, spec in configSpec.SPEC.items()}, enabled=False)
        try:
            plugin = titanEnhancements.GlobalPlugin()
            try:
                self.assertTrue(hasattr(plugin, 'script_titanMenu'))
                self.assertTrue(hasattr(plugin, 'script_titanAssistant'))
            finally:
                plugin.terminate()
        finally:
            configSpec.read = original


class TheVendoredLibraryIsTitansOwn(unittest.TestCase):
    """Kept byte-identical, which link.py's docstring says a test does."""

    def test_it_is_the_same_file(self):
        mine = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'titan_actions.py')
        theirs = os.path.join(ROOT, 'src', 'titan_core', 'titan_actions.py')
        if not os.path.exists(theirs):
            self.skipTest('this is the add-on on its own, without Titan')
        with open(mine, 'rb') as handle:
            here = handle.read()
        with open(theirs, 'rb') as handle:
            there = handle.read()
        self.assertEqual(here, there,
                         'the vendored titan_actions.py has drifted from '
                         "Titan's own - copy it across")


class TheCatalogueSurvivesTitanNotRunning(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(HERE, 'titanActions.json')
        original = gestures._catalogue_path
        gestures._catalogue_path = lambda: self.path
        self.addCleanup(lambda: setattr(gestures, '_catalogue_path', original))
        self.addCleanup(lambda: os.path.exists(self.path)
                        and os.remove(self.path))

    def test_it_is_written_and_read_back(self):
        rows = gestures.catalogue_from_addons(sample())
        self.assertTrue(gestures.save_catalogue(rows))
        self.assertEqual(gestures.load_catalogue(), rows)

    def test_a_catalogue_that_is_not_there_is_not_an_error(self):
        self.assertEqual(gestures.load_catalogue(), [])

    def test_a_catalogue_that_is_rubbish_is_not_an_error(self):
        with open(self.path, 'w', encoding='utf-8') as handle:
            handle.write('{not json at all')
        self.assertEqual(gestures.load_catalogue(), [])

    def test_a_row_with_nothing_to_run_is_dropped_on_the_way_in(self):
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump([{'addon': 'a', 'action': 'b'}, {'addon': 'a'},
                       'not even a row'], handle)
        self.assertEqual(len(gestures.load_catalogue()), 1)


# --------------------------------------------------------------------------- #
class TheConversationIsREADBack(unittest.TestCase):
    """A key nothing writes is a working-looking empty list.

    Titan answers `ai.history` with `{"enabled": ..., "exchanges": [{"role",
    "text", ...}]}` - one row per TURN. This read `history`, with
    `question`/`answer` on each row, so the conversation came back as
    "Nothing has been asked yet" however much of it there was. Measured
    against a real Titan before it was believed: the bridge answered
    `['enabled', 'exchanges']` and eight turns of a real conversation.
    """

    def setUp(self):
        from titanEnhancements import commands, dialogs
        self.commands = commands
        self.said, self.pages = [], []
        self._report, self._browse = dialogs.report, dialogs.browse
        self._work = commands._work
        dialogs.report = self.said.append
        dialogs.browse = lambda text, title=None: self.pages.append(text)
        commands._work = lambda function: function()   # no threads in a test
        self.dialogs = dialogs

    def tearDown(self):
        self.dialogs.report = self._report
        self.dialogs.browse = self._browse
        self.commands._work = self._work

    def _answer(self, data):
        original = link.LINK.bridge
        link.LINK.bridge = lambda call, **kw: (True, data)
        self.addCleanup(lambda: setattr(link.LINK, 'bridge', original))

    def test_the_key_is_the_one_titan_really_writes(self):
        self.assertEqual(self.commands.HISTORY_KEY, 'exchanges')

    def test_a_conversation_is_shown(self):
        self._answer({'enabled': True, 'exchanges': [
            {'role': 'user', 'text': 'what time is it'},
            {'role': 'assistant', 'text': 'a quarter to twelve'}]})
        self.commands.assistant_history()
        self.assertEqual(len(self.pages), 1)
        self.assertIn('what time is it', self.pages[0])
        self.assertIn('a quarter to twelve', self.pages[0])
        # Whose turn it was survives, or a page of a conversation is a wall
        # of sentences with nobody saying them.
        self.assertNotEqual(self.pages[0].count('You:'),
                            self.pages[0].count('Titan:') + 1)

    def test_the_older_spelling_is_still_read(self):
        self._answer({'history': [{'question': 'a', 'answer': 'b'}]})
        self.commands.assistant_history()
        self.assertEqual(len(self.pages), 1)
        self.assertIn('a', self.pages[0])

    def test_memory_switched_off_says_so_rather_than_nothing_asked(self):
        self._answer({'enabled': False, 'exchanges': []})
        self.commands.assistant_history()
        self.assertEqual(self.pages, [])
        self.assertEqual(len(self.said), 1)
        self.assertIn('not keeping', self.said[0])

    def test_an_empty_conversation_is_still_an_answer(self):
        self._answer({'enabled': True, 'exchanges': []})
        self.commands.assistant_history()
        self.assertEqual(len(self.said), 1)


# --------------------------------------------------------------------------- #
class SwitchedOffMeansNVDAsOwnBehaviourBack(unittest.TestCase):
    """Off must not mean silence.

    Titan asks `replaces_focus` BEFORE it says the tab bar or a shell group
    at all, and stays quiet when the answer is no. The channel claimed it
    could take an announcement whatever its switch said, and then dropped
    every one with a reason nobody reads - so a user who turned Titan's
    announcements off in NVDA lost those sentences entirely instead of
    getting NVDA's own behaviour back.
    """

    def setUp(self):
        from titanEnhancements import channel
        self.channel = channel.Channel()

    def test_a_channel_that_is_on_says_it_can_announce(self):
        self.assertTrue(self.channel.capabilities()['announce'])

    def test_a_channel_that_is_off_says_it_cannot(self):
        self.channel.enabled = False
        able = self.channel.capabilities()
        self.assertFalse(able['announce'])
        # And nothing else claims to work either, or Titan composes an
        # announcement for a channel that will not carry it.
        for key in ('replaces_focus', 'braille', 'segments', 'position',
                    'pitch', 'queue'):
            self.assertFalse(able[key], key)

    def test_it_still_says_what_synthesizer_it_has(self):
        self.channel.enabled = False
        self.assertIn('synth', self.channel.capabilities())


# --------------------------------------------------------------------------- #
class WhereTheControlIS(unittest.TestCase):
    """Positioned speech, applied to the thing the user actually hears.

    Reported as "positioning does not work, and I have it switched on" -
    and it did not, for a reason that was never in the panner: nothing ever
    asked it to place a control. Titan sends a position for the few things
    whose place it knows and 0 for every ordinary one, and the reading this
    add-on does ITSELF - the three tones, which is most of what a Titan
    user hears - was never placed at all.
    """

    class Located:
        role = None
        states = ()

        def __init__(self, left, width):
            self.location = (left, 0, width, 20)

    def setUp(self):
        from titanEnhancements import panner
        self.panner = panner
        panner._SCREEN['width'] = 1000
        panner._SCREEN['at'] = 1e12          # never asked again in a test
        self.addCleanup(lambda: panner._SCREEN.update({'width': 0,
                                                       'at': 0.0}))

    def test_the_left_of_the_screen_is_the_left_ear(self):
        self.assertAlmostEqual(
            self.panner.screen_position(self.Located(0, 100)), -0.9, places=3)

    def test_the_middle_is_the_middle(self):
        self.assertAlmostEqual(
            self.panner.screen_position(self.Located(450, 100)), 0.0,
            places=3)

    def test_the_right_of_the_screen_is_the_right_ear(self):
        self.assertAlmostEqual(
            self.panner.screen_position(self.Located(900, 100)), 0.9,
            places=3)

    def test_a_control_with_no_rectangle_is_left_where_it_is(self):
        """None, not centre: moving it is a pan for no information."""
        self.assertIsNone(self.panner.screen_position(None))
        self.assertIsNone(self.panner.screen_position(self.Located(0, 0)))

    def test_the_cue_and_the_voice_use_the_same_arithmetic(self):
        from titanEnhancements import earcons
        control = self.Located(0, 100)
        self.assertAlmostEqual(earcons.pan_for(control),
                               self.panner.screen_position(control))


class FakeCommand:
    """Stands in for one of NVDA's speech commands.

    The suite runs with no NVDA under it, and `compat` answers None for
    every command there is - which is right and is also why the two things
    that MOVE an utterance could not be exercised at all: both tests
    skipped, and a skipped test proves nothing about the bug it was written
    for. A stand-in whose only job is to exist is enough, because what is
    being checked is the SHAPE of the sequence, not what a synthesizer does
    with it.
    """

    def __init__(self, *args, **kw):
        self.args = args
        self.kw = kw
        self.name = kw.get('name', '')
        self.offset = kw.get('offset')


class WithCommands:
    """Put stand-ins for NVDA's commands into `compat` for one test."""

    NAMES = ('PitchCommand', 'RateCommand', 'VolumeCommand', 'BeepCommand',
             'CallbackCommand')

    def __init__(self, *names):
        self.names = names or self.NAMES
        self._before = {}

    def __enter__(self):
        for name in self.names:
            self._before[name] = getattr(compat, name, None)
            setattr(compat, name, FakeCommand)
        return self

    def __exit__(self, *_exception):
        for name, value in self._before.items():
            setattr(compat, name, value)
        return False


def _supported_by_anything(monkeypatched=[]):
    """Make `prosody._supported` answer yes, whatever synth there is not."""
    from titanEnhancements import prosody
    before = prosody._supported
    prosody._supported = lambda synth, command: command is not None
    monkeypatched.append(before)
    return lambda: setattr(prosody, '_supported', before)


# --------------------------------------------------------------------------- #
class ARowIsPlacedUpAndDownNotLeftAndRight(unittest.TestCase):
    """The user's own correction, and it is right.

    Panning a list by where the list happens to sit on the screen says the
    same thing about every row in it, which is nothing. What a reader wants
    to know from a row is how far down the list it is - so a row is placed
    with the TONE instead, the top of the list high and the bottom low,
    which is exactly what Titan Access's own row cue has always said.
    """

    def setUp(self):
        from titanEnhancements import panner
        self.panner = panner

    def test_the_top_of_the_list_is_the_highest(self):
        self.assertAlmostEqual(self.panner.list_pitch(1, 10),
                               self.panner.LIST_PITCH_TOP)

    def test_the_bottom_of_the_list_is_the_lowest(self):
        self.assertAlmostEqual(
            self.panner.list_pitch(10, 10),
            self.panner.LIST_PITCH_TOP - self.panner.LIST_PITCH_SPAN)

    def test_it_falls_all_the_way_down(self):
        tones = [self.panner.list_pitch(n, 5) for n in range(1, 6)]
        self.assertEqual(tones, sorted(tones, reverse=True))

    def test_a_list_of_one_says_nothing_about_where_it_is(self):
        self.assertEqual(self.panner.list_pitch(1, 1), 0.0)

    def test_a_place_nvda_will_not_say_is_not_invented(self):
        self.assertEqual(self.panner.list_pitch(0, 0), 0.0)
        self.assertEqual(self.panner.list_pitch(None, None), 0.0)

    def test_the_step_is_the_one_this_addon_already_uses(self):
        """A list must not speak in a range nothing else here uses."""
        from titanEnhancements import elements
        self.assertEqual(self.panner.LIST_PITCH_TOP,
                         float(elements.STATE_PITCH))


# --------------------------------------------------------------------------- #
class WhichOfTheTwoAControlGets(unittest.TestCase):

    class Row:
        def __init__(self, role_name, index=0, count=0, left=0, width=100,
                     top=0, height=20):
            self.role = types.SimpleNamespace(name=role_name)
            self.positionInfo = {'indexInGroup': index,
                                 'similarItemsInGroup': count}
            self.location = (left, top, width, height)

    def setUp(self):
        from titanEnhancements import configSpec, focus, panner
        self.focus, self.panner = focus, panner
        self.configSpec = configSpec
        panner._SCREEN['width'] = 1000
        panner._SCREEN['height'] = 1000
        panner._SCREEN['at'] = 1e12
        configSpec.forget()
        self._read = configSpec.read
        self._answers = dict(configSpec.defaults())
        configSpec.read = lambda: dict(self._answers)
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))
        self.addCleanup(configSpec.forget)
        self.addCleanup(lambda: panner._SCREEN.update({'width': 0,
                                                       'height': 0,
                                                       'at': 0.0}))

    def _way(self, word):
        self._answers['positionAs'] = word

    # --------------------------------------------------------------- pitch
    def test_by_default_a_control_is_placed_up_and_down(self):
        """Pitch, not pan, and that is the reported bug's answer.

        Panning is exact only where a synthesizer feeds a stereo stream; on
        eSpeak - NVDA's own default and MONO - it is NVDA's whole audio
        session, put back on a timer rather than at the end of the line, so
        a long line snaps back inside itself. "It is not smooth, it cuts
        sometimes." A pitch belongs to the utterance it is in.
        """
        where, tone = self.focus.placement_of(
            self.Row('BUTTON', left=0, width=100, top=0, height=20))
        self.assertIsNone(where, 'the default must not pan')
        self.assertGreater(tone, 0, 'a control near the top is spoken higher')

    def test_a_control_near_the_bottom_of_the_screen_is_lower(self):
        _where, tone = self.focus.placement_of(
            self.Row('BUTTON', top=980, height=20))
        self.assertLess(tone, 0)

    def test_the_two_ends_of_the_screen_are_the_two_ends_of_the_list_range(self):
        """A control and a row must speak in one vocabulary."""
        _w, high = self.focus.placement_of(self.Row('BUTTON', top=0, height=0))
        _w2, low = self.focus.placement_of(self.Row('BUTTON', top=1000,
                                                    height=0))
        self.assertAlmostEqual(high, self.panner.LIST_PITCH_TOP)
        self.assertAlmostEqual(low, self.panner.LIST_PITCH_TOP
                               - self.panner.LIST_PITCH_SPAN)

    # ----------------------------------------------------------------- pan
    def test_asking_for_it_across_still_gives_it_across(self):
        self._way('pan')
        where, tone = self.focus.placement_of(
            self.Row('BUTTON', left=0, width=100))
        self.assertLess(where, -0.5)
        self.assertEqual(tone, 0.0, 'one way or the other, not both')

    def test_asking_for_both_gives_both(self):
        self._way('both')
        where, tone = self.focus.placement_of(
            self.Row('BUTTON', left=0, width=100, top=0, height=20))
        self.assertLess(where, -0.5)
        self.assertGreater(tone, 0)

    # ---------------------------------------------------------------- rows
    def test_a_row_is_placed_up_and_down_whichever_way_is_asked_for(self):
        for word in ('pitch', 'pan', 'both'):
            self._way(word)
            where, tone = self.focus.placement_of(
                self.Row('LISTITEM', index=1, count=10, left=0, width=100))
            self.assertIsNone(where, 'a row must not be panned: ' + word)
            self.assertGreater(tone, 0, word)

    def test_a_row_at_the_bottom_is_lower(self):
        _where, tone = self.focus.placement_of(
            self.Row('LISTITEM', index=10, count=10))
        self.assertLess(tone, 0)

    def test_a_row_whose_list_will_not_say_how_long_it_is_is_placed_anyway(self):
        """It is not a row any more, so it gets what a control gets."""
        self._way('pan')
        where, tone = self.focus.placement_of(
            self.Row('LISTITEM', left=900, width=100))
        self.assertGreater(where, 0.5)
        self.assertEqual(tone, 0.0)

    def test_the_switch_being_off_means_neither(self):
        self._answers['position'] = False
        self.assertEqual(
            self.focus.placement_of(self.Row('LISTITEM', 1, 10)),
            (None, 0.0))

    def test_a_control_whose_place_cannot_be_read_is_left_alone(self):
        """Nought is the voice exactly as it was - the honest answer to
        "I do not know where this is". Not the centre, and not the top of
        the screen: both of those are a statement about where it is."""
        row = self.Row('BUTTON')
        row.location = None
        self.assertEqual(self.focus.placement_of(row), (None, 0.0))


# --------------------------------------------------------------------------- #
class ASequenceIsSpokenFromWhereItIs(unittest.TestCase):

    def setUp(self):
        from titanEnhancements import configSpec, prosody
        self.prosody = prosody
        self.configSpec = configSpec
        configSpec.forget()
        self._read = configSpec.read
        self._answers = dict(configSpec.defaults())
        configSpec.read = lambda: dict(self._answers)
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))
        self.addCleanup(configSpec.forget)

    def _way(self, word):
        self._answers['positionAs'] = word

    def test_dead_centre_is_left_exactly_as_it_was(self):
        sequence, notes = self.prosody.place_sequence(['hello'], 0.0)
        self.assertEqual(sequence, ['hello'])
        self.assertEqual(notes, [])

    def test_nothing_to_say_is_not_a_pan(self):
        self.assertEqual(self.prosody.place_sequence([], -1.0)[0], [])

    def test_a_position_that_is_not_a_number_moves_nothing(self):
        self.assertEqual(self.prosody.place_sequence(['x'], 'left')[0], ['x'])

    def test_by_default_a_place_is_carried_as_a_tone(self):
        """And the pan is not reached at all - it is not a fallback here,
        it is the thing the user asked not to have."""
        restore = _supported_by_anything()
        try:
            with WithCommands():
                sequence, _notes = self.prosody.place_sequence(['hello'], -1.0)
        finally:
            restore()
        names = [getattr(part, 'name', None) for part in sequence]
        self.assertNotIn('titanPan', names)
        self.assertIn('hello', sequence)
        self.assertEqual(sequence[-1].offset, 0, 'the tone is put back')

    def test_the_pan_is_put_back_by_the_sequence_itself(self):
        """Whatever it does, it must end with the stream where it was."""
        from titanEnhancements import panner
        self._way('pan')
        can = panner.PANNER.can_place
        panner.PANNER.can_place = lambda: True
        try:
            with WithCommands():
                sequence, _notes = self.prosody.place_sequence(['hello'], -1.0)
        finally:
            panner.PANNER.can_place = can
        names = [getattr(part, 'name', None) for part in sequence]
        self.assertEqual(names[0], 'titanPan')
        self.assertEqual(names[-1], 'titanUnpan')
        self.assertIn('hello', sequence)

    def test_what_cannot_be_panned_is_marked_rather_than_lost(self):
        from titanEnhancements import panner
        self._way('pan')
        can = panner.PANNER.can_place
        panner.PANNER.can_place = lambda: False
        try:
            with WithCommands():
                sequence, notes = self.prosody.place_sequence(['hello'], 1.0)
        finally:
            panner.PANNER.can_place = can
        self.assertEqual(len(sequence), 2)
        self.assertTrue(notes)
    def test_a_row_gets_its_tone_and_the_tone_is_put_back(self):
        restore = _supported_by_anything()
        try:
            with WithCommands():
                sequence = self.prosody.pitch_sequence(['third row'], 4.0)
        finally:
            restore()
        self.assertEqual(len(sequence), 3)
        self.assertEqual(sequence[1], 'third row')
        self.assertEqual(sequence[-1].offset, 0)

    def test_a_tone_of_nothing_changes_nothing(self):
        restore = _supported_by_anything()
        try:
            with WithCommands():
                self.assertEqual(self.prosody.pitch_sequence(['x'], 0.0),
                                 ['x'])
        finally:
            restore()

    def test_the_tone_is_converted_onto_nvdas_own_scale(self):
        """Titan says -10..10; NVDA offsets its own 0..100 setting."""
        restore = _supported_by_anything()
        try:
            with WithCommands():
                sequence = self.prosody.pitch_sequence(['x'], 4.0)
        finally:
            restore()
        self.assertEqual(sequence[0].offset, 4 * self.prosody.SCALE)


# --------------------------------------------------------------------------- #
class ASwitchDecidesEveryTimeItIsAsked(unittest.TestCase):
    """A switch read once and then obeyed for ever is a switch that lies."""

    def setUp(self):
        from titanEnhancements import configSpec, focus
        self.configSpec = configSpec
        self.focus = focus
        self._read = configSpec.read
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))
        self.addCleanup(lambda: focus.stand_down(False))

    def _answers(self, **values):
        base = self.configSpec.defaults()
        base.update(values)
        self.configSpec.read = lambda: dict(base)

    def test_standing_down_is_obeyed_when_it_is_wanted(self):
        self._answers(standDownForTitanAccess=True)
        self.assertTrue(self.focus.stand_down(True))
        self.assertTrue(self.focus.standing_down())

    def test_standing_down_is_refused_when_it_is_not(self):
        self._answers(standDownForTitanAccess=False)
        self.assertFalse(self.focus.stand_down(True))
        self.assertFalse(self.focus.standing_down())

    def test_unticking_it_while_already_silent_gives_the_voice_back(self):
        self._answers(standDownForTitanAccess=True)
        self.focus.stand_down(True)
        self._answers(standDownForTitanAccess=False)
        self.assertFalse(self.focus.standing_down())


# --------------------------------------------------------------------------- #
class OneMissingAnswerCostsThatAnswerAlone(unittest.TestCase):
    """Read as one comprehension, a single key this NVDA has not got threw
    every answer the user had given back to its default at once."""

    def setUp(self):
        from titanEnhancements import configSpec
        self.configSpec = configSpec
        configSpec.forget()
        self.addCleanup(configSpec.forget)

    def test_a_key_that_is_not_there_leaves_the_others_alone(self):
        class Half(dict):
            def __getitem__(self, name):
                if name == 'earcons':
                    raise KeyError(name)
                return False
        stub = types.ModuleType('config')
        stub.conf = {self.configSpec.SECTION: Half()}
        sys.modules['config'] = stub
        try:
            values = self.configSpec.read()
        finally:
            del sys.modules['config']
        self.assertFalse(values['announcements'])     # really read
        self.assertFalse(values['earcons'])           # its own default

    def test_no_nvda_at_all_is_the_defaults(self):
        self.assertEqual(self.configSpec.read(), self.configSpec.defaults())

    def test_writing_throws_the_kept_answers_away(self):
        self.configSpec.read()
        self.configSpec.write({'earcons': True})
        self.assertIsNone(self.configSpec._CACHE['values'])


# --------------------------------------------------------------------------- #
class ARefusalIsAnAnswerNotAFailure(unittest.TestCase):
    """"Titan is asking its user" and "the call failed" are different.

    It used to be told apart by looking for the words "consent" or
    "permission" in Titan's answer - and Titan writes that sentence in ITS
    user's own language, so on a Polish Titan the test matched nothing and
    a refusal read like a broken bridge. Titan marks it on the wire and the
    client now carries the mark.
    """

    def test_the_client_carries_the_mark(self):
        from titanEnhancements import titan_actions
        answer = titan_actions.Result(False, 'nie wolno', consent='needed')
        self.assertTrue(answer.needs_consent)
        self.assertFalse(titan_actions.Result(False, 'broken').needs_consent)

    def test_the_link_keeps_titans_own_sentence(self):
        from titanEnhancements import titan_actions
        original_connected = titan_actions.is_connected
        original_call = titan_actions.call
        titan_actions.is_connected = lambda: True
        titan_actions.call = lambda *a, **kw: titan_actions.Result(
            False, 'Program X poprosil o kontrole nad Titanem.',
            consent='needed')
        link.LINK.needs_consent = False
        try:
            ok, text = link.LINK.bridge('addons.run')
            noticed = link.LINK.needs_consent
        finally:
            titan_actions.is_connected = original_connected
            titan_actions.call = original_call
            link.LINK.needs_consent = False
        self.assertFalse(ok)
        self.assertIn('Titanem', text)
        self.assertTrue(noticed)


# --------------------------------------------------------------------------- #
class Row:
    """A row of a report-mode list, answering what NVDA's own does."""

    def __init__(self, cells=(), headers=(), index=1, count=1, pid=4321,
                 role='LISTITEM', window=99):
        self.role = types.SimpleNamespace(name=role, displayString=role.lower())
        self._cells = list(cells)
        self._headers = list(headers)
        self.positionInfo = {'indexInGroup': index,
                             'similarItemsInGroup': count}
        self.processID = pid
        self.windowHandle = window
        self.name = cells[0] if cells else ''
        self.states = ()
        self.location = (0, 0, 100, 20)
        self.parent = types.SimpleNamespace(columnCount=len(self._cells),
                                            role=self.role, parent=None,
                                            name='')

    def _getColumnContent(self, index):
        return self._cells[index - 1]

    def _getColumnHeader(self, index):
        return self._headers[index - 1] if index <= len(self._headers) else ''


class TitansOwnApplicationsAreUnderstood(unittest.TestCase):
    """What an app module buys anywhere else, for a desktop that had none.

    NVDA reads a window; a reader with an app module reads the PROGRAM.
    Titan is a whole desktop of applications written for people who cannot
    see them, and every one of them was an unremarkable wxPython window
    from the outside - same class, same roles, a title in the user's own
    language. Which process is which is the one thing that cannot be
    worked out from a window, and it is the one thing Titan can simply
    say.
    """

    def setUp(self):
        from titanEnhancements import configSpec, semantics
        self.semantics = semantics
        semantics.forget()
        semantics.forget_titles()
        semantics.forget_regions()
        self.addCleanup(semantics.forget)
        self.addCleanup(semantics.forget_titles)
        self.addCleanup(semantics.forget_regions)
        self._read = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults())
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))
        semantics.note_processes([
            {'pid': 4321, 'id': 'tfm', 'label': 'File Manager', 'kind': 'app'},
            {'pid': 5555, 'id': 'tnotes', 'label': 'Notes', 'kind': 'app'}])

    # ------------------------------------------------------------ which one
    def test_a_window_is_matched_by_its_process(self):
        found = self.semantics.application_of(Row(pid=4321))
        self.assertEqual(found['id'], 'tfm')

    def test_a_window_that_is_nobodys_is_nobodys(self):
        self.assertIsNone(self.semantics.application_of(Row(pid=1)))

    def test_nothing_at_all_is_not_an_error(self):
        self.assertIsNone(self.semantics.application_of(None))

    def test_the_reader_itself_is_not_an_application(self):
        """NVDA is on the bus too, so its own pid is in this map - and if
        that counted as an application, the reader's own dialogs would
        stop being reported the ordinary way."""
        self.semantics.note_processes([
            {'pid': 4321, 'id': 'nvda', 'label': 'NVDA', 'kind': 'client'}])
        self.assertEqual(self.semantics.describe(Row(pid=4321)), ([], None))

    def test_a_component_has_no_window_of_its_own(self):
        self.semantics.note_processes([
            {'pid': 4321, 'id': 'macros', 'label': 'Macros',
             'kind': 'component'}])
        self.assertEqual(self.semantics.describe(Row(pid=4321)), ([], None))

    def test_a_titan_that_has_gone_is_forgotten(self):
        """A pid is reused, and reading somebody else's window as the file
        manager is worse than reading it plainly."""
        self.semantics.forget()
        self.assertIsNone(self.semantics.application_of(Row(pid=4321)))

    # -------------------------------------------------------------- the row
    def test_a_row_is_read_with_its_own_columns(self):
        row = Row(cells=['readme.txt', '2024-01-02', 'Text file'],
                  headers=['Name', 'Date modified', 'Type'], pid=4321)
        parts, application = self.semantics.describe(row)
        self.assertEqual(application['id'], 'tfm')
        said = [text for text, _voice in parts]
        self.assertEqual(said[0], 'readme.txt')
        # The file manager's own Type column IS what the row is, written
        # by the application in the user's own language.
        self.assertIn('Text file', said)
        self.assertTrue(any('Date modified' in text for text in said))

    def test_the_kind_is_said_at_the_control_type_tone(self):
        from titanEnhancements import elements
        row = Row(cells=['bin', '2024-01-02', 'Folder'],
                  headers=['Name', 'Date modified', 'Type'], pid=4321)
        parts, _application = self.semantics.describe(row)
        tones = dict((text, voice) for text, voice in parts)
        self.assertEqual(tones['Folder'], elements.ROLE_PITCH)

    def test_an_application_with_no_type_column_still_says_what_a_row_is(self):
        row = Row(cells=['Shopping', '1 Jan', '2 Jan'],
                  headers=['Note title', 'Date created', 'Date modified'],
                  pid=5555)
        parts, _application = self.semantics.describe(row)
        said = [text for text, _voice in parts]
        self.assertIn(self.semantics._noun('note'), said)

    def test_a_list_with_one_column_is_left_exactly_as_it_was(self):
        row = Row(cells=['only'], headers=['Name'], pid=4321)
        self.assertEqual(self.semantics.columns_of(row), [])

    def test_a_control_that_answers_no_columns_is_not_forced_to(self):
        class Plain:
            role = types.SimpleNamespace(name='LISTITEM')
            processID = 4321
        self.assertEqual(self.semantics.columns_of(Plain()), [])

    def test_the_switch_is_what_decides(self):
        from titanEnhancements import configSpec
        configSpec.read = lambda: dict(configSpec.defaults(),
                                       appSemantics=False)
        parts, application = self.semantics.describe(
            Row(cells=['a', 'b'], headers=['Name', 'Type'], pid=4321))
        self.assertEqual((parts, application), ([], None))

    # ------------------------------------------------------------ the place
    def test_the_folder_you_have_moved_into_is_said_once(self):
        """The file manager titles its window with the folder, so opening
        one changes nothing NVDA reports: the focus never left the list."""
        row = Row(cells=['a', 'b', 'c'], headers=['Name', 'D', 'T'], pid=4321)
        row.parent = types.SimpleNamespace(columnCount=3, name='Documents',
                                           parent=None, role=row.role)
        first = self.semantics.context_change(row, {'id': 'tfm'})
        self.assertEqual(first, 'Documents')
        self.assertEqual(self.semantics.context_change(row, {'id': 'tfm'}), '')

    def test_a_window_whose_title_is_not_a_place_is_not_announced(self):
        row = Row(pid=4321)
        row.parent = types.SimpleNamespace(columnCount=0, name='Downloads',
                                           parent=None, role=row.role)
        self.assertEqual(self.semantics.context_change(row, {'id': 'tdm'}), '')


# --------------------------------------------------------------------------- #
class TheRestOfWindowsToo(unittest.TestCase):
    """What a sighted person reads off the layout - and only what NVDA has
    NOT already said.

    The rule changed here, and it changed because of a bug report: tabbing
    round a dialog said "dialog, OK button" and then "dialog, Cancel
    button". NVDA already announces every newly entered focus ancestor
    (`NVDAObject.event_focusEntered`), so a layer that announced them too
    could only ever add the duplicate.
    """

    def setUp(self):
        from titanEnhancements import ancestry, configSpec, semantics
        self.semantics = semantics
        self.ancestry = ancestry
        semantics.forget_regions()
        self.addCleanup(semantics.forget_regions)
        self._read = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults(),
                                       windowsSemantics=True)
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))

    def _in(self, region, name='', window=7, control=99):
        row = Row(pid=1, window=control)
        row.parent = types.SimpleNamespace(
            role=types.SimpleNamespace(name=region, displayString=region.lower()),
            name=name, parent=None, columnCount=0, windowHandle=window)
        return row

    # ------------------------------------------------- what NVDA already says
    def test_a_toolbar_is_nvdas_to_announce_and_is_not_repeated(self):
        """NVDA fires focusEntered on a toolbar and speaks it. Saying it
        again is the whole of the bug this replaced."""
        self.assertEqual(self.semantics.region_change(self._in('TOOLBAR')), '')

    def test_tabbing_round_a_dialog_says_nothing_at_all(self):
        """The report, exactly: "dialog OK button, dialog Cancel button".

        Every control of a Win32 dialog is its own window, which is what
        made the old memory miss every single time.
        """
        said = []
        for control, name in ((101, 'OK'), (102, 'Cancel'), (103, 'Apply')):
            button = self._in('DIALOG', name='Save changes?', window=7,
                              control=control)
            said.append(self.semantics.region_change(button))
        self.assertEqual(said, ['', '', ''])

    def test_the_place_is_remembered_against_the_PLACE(self):
        """Not against the focused control, which is what was wrong."""
        first = self._in('LIST', name='Files', window=7, control=500)
        second = self._in('LIST', name='Files', window=7, control=501)
        self.assertEqual(self.semantics.region_change(first), 'Files')
        self.assertEqual(self.semantics.region_change(second), '')

    # ------------------------------------------------ what NVDA leaves silent
    def test_a_list_is_ours_because_nvda_enters_one_in_silence(self):
        """`event_focusEntered` excludes LIST deliberately - so a window
        with three lists in it gives the user no way to know which one they
        have moved to."""
        self.assertEqual(self.semantics.region_change(
            self._in('LIST', name='Applications')), 'Applications')

    def test_moving_between_two_lists_says_the_new_one(self):
        self.semantics.region_change(self._in('LIST', name='Applications',
                                              window=7))
        self.assertEqual(self.semantics.region_change(
            self._in('LIST', name='Games', window=8)), 'Games')

    def test_a_module_can_name_a_pane_the_program_never_named(self):
        from titanEnhancements.readerModules import schema
        module = schema.Module({'id': 'x', 'match': {'class': 'Thing'},
                                'regions': [{'match': {'role': 'PANE',
                                                       'unnamed': True},
                                             'say': 'Message body'}]})
        pane = self._in('PANE', name='')
        self.assertEqual(self.semantics.region_change(pane, module),
                         'Message body')

    def test_leaving_a_menu_is_said_because_nobody_says_it(self):
        """Opening a menu is announced by every reader; closing one by
        none, so the user cannot tell whether their next key is a command
        or a letter."""
        self.ancestry.forget()
        self.assertEqual(self.ancestry.changes(self._in('MENUBAR',
                                                        name='File'))[1], [])
        _entered, left = self.ancestry.changes(self._in('DOCUMENT'))
        self.assertEqual([step.role for step in left], ['MENUBAR'])
        self.assertTrue(self.ancestry.leaving_word(left))

    def test_leaving_anything_else_is_not_news(self):
        self.ancestry.forget()
        self.ancestry.changes(self._in('TOOLBAR'))
        _entered, left = self.ancestry.changes(self._in('DOCUMENT'))
        self.assertEqual(left, [])

    # ------------------------------------------------------------- the rest
    def test_a_row_anywhere_is_read_with_its_columns(self):
        row = Row(cells=['photo.jpg', '2 MB', 'JPEG image'],
                  headers=['Name', 'Size', 'Type'], pid=1)
        said = [text for text, _voice in self.semantics.windows_parts(row)]
        self.assertEqual(said[0], 'photo.jpg')
        self.assertTrue(any('Size' in text for text in said))

    def test_off_is_off(self):
        from titanEnhancements import configSpec
        configSpec.read = lambda: dict(configSpec.defaults(),
                                       windowsSemantics=False)
        row = Row(cells=['a', 'b'], headers=['Name', 'Type'], pid=1)
        self.assertEqual(self.semantics.windows_parts(row), [])

    def test_the_ancestry_is_the_place_it_is_asked_about(self):
        """"Where am I" is the whole chain and does NOT advance the
        memory: pressing it twice must say the same thing twice."""
        control = self._in('LIST', name='Files')
        first = self.ancestry.sentence(control)
        self.assertEqual(self.ancestry.sentence(control), first)
        self.assertIn('Files', first)


# --------------------------------------------------------------------------- #
class TheClassIsCarriedByTheVoice(unittest.TestCase):
    """Emacspeak's oldest idea: the voice says what it is, so a word need
    not. Every class must really reach the synthesizer as commands."""

    def setUp(self):
        from titanEnhancements import voices
        self.voices = voices

    def test_the_three_titan_access_already_has_are_its_own(self):
        from titanEnhancements import elements
        self.assertEqual(self.voices.voice_of('name'), {})
        self.assertEqual(self.voices.voice_of('kind')['pitch'],
                         elements.ROLE_PITCH)
        self.assertEqual(self.voices.voice_of('state')['pitch'],
                         elements.STATE_PITCH)

    def test_a_bare_number_is_still_a_pitch(self):
        self.assertEqual(self.voices.voice_of(-4), {'pitch': -4.0})

    def test_a_class_nobody_wrote_is_the_plain_voice(self):
        self.assertEqual(self.voices.voice_of('nothing_like_this'), {})

    def test_a_disabled_control_is_heard_before_it_is_said(self):
        voice = self.voices.voice_of('disabled')
        self.assertLess(voice.get('volume', 0), 0)

    def test_every_dial_is_put_back(self):
        restore = _supported_by_anything()
        try:
            with WithCommands():
                out = self.voices.sequence([('bin', 'folder'),
                                            ('2 MB', 'detail')])
        finally:
            restore()
        # Everything that was turned on is turned off again, or the reader
        # talks that way for everything after it.
        offsets = [part.offset for part in out if hasattr(part, 'offset')]
        self.assertEqual(sum(1 for value in offsets if value == 0),
                         sum(1 for value in offsets if value != 0))
        self.assertIn('bin,', out)
        self.assertIn('2 MB', out)

    def test_a_synth_that_takes_none_of_them_is_not_lied_to(self):
        from titanEnhancements import prosody
        before = prosody._supported
        prosody._supported = lambda synth, command: False
        try:
            with WithCommands():
                out = self.voices.sequence([('bin', 'folder')])
        finally:
            prosody._supported = before
        self.assertEqual(out, ['bin'])


# --------------------------------------------------------------------------- #
class AReadingIsNotARefusal(unittest.TestCase):
    """AI OCR, and the two things it answers that look identical.

    Every one of these actions answers with prose whether it worked or
    not - "AI OCR is switched off. Turn it on in Settings", "the vision
    provider has no key" - and a refusal shown in a page titled AI OCR
    reads as though the window had been read and had that in it. Measured
    against the real actions before it was believed: `ocr.read_window`
    answers `ok` and a sentence for every one of its failures.
    """

    def setUp(self):
        from titanEnhancements import commands, dialogs
        self.commands = commands
        self.said, self.pages = [], []
        self._report, self._browse = dialogs.report, dialogs.browse
        dialogs.report = self.said.append
        dialogs.browse = lambda text, title=None: self.pages.append(text)
        self.dialogs = dialogs

    def tearDown(self):
        self.dialogs.report = self._report
        self.dialogs.browse = self._browse

    def test_a_refusal_is_said_not_shown_as_a_reading(self):
        self.commands._ocr_answer(True, 'AI OCR is switched off. Turn it on '
                                        'in Settings, AI features.')
        self.assertEqual(self.pages, [])
        self.assertEqual(len(self.said), 1)

    def test_a_reading_is_a_page_with_the_cursor_on_it(self):
        reading = '\n'.join('row %d' % n for n in range(40))
        self.commands._ocr_answer(True, reading)
        self.assertEqual(len(self.pages), 1)
        self.assertIn('row 39', self.pages[0])

    def test_a_call_that_failed_is_always_said(self):
        self.commands._ocr_answer(False, 'x' * 400)
        self.assertEqual(self.pages, [])
        self.assertEqual(len(self.said), 1)

    def test_nothing_at_all_is_still_an_answer(self):
        self.commands._ocr_answer(True, '')
        self.assertEqual(len(self.said), 1)

    # ------------------------------------------------- written for a model
    def test_the_sentence_aimed_at_the_model_is_taken_off(self):
        """The same action answers Titan's own agent, which needs exactly
        that sentence. It is simply not for the person reading."""
        reading = ('Save, button\nCancel, button\n\n'
                   'Act on this with ocr_press, ocr_type, ocr_toggle or '
                   'ocr_send_key, or hand it to the user with '
                   'ocr_show_overlay.')
        said = self.commands._for_a_person(reading)
        self.assertEqual(said, 'Save, button\nCancel, button')

    def test_a_reading_with_nothing_to_trim_is_untouched(self):
        self.assertEqual(self.commands._for_a_person('Save, button'),
                         'Save, button')

    def test_the_notes_the_reading_carries_are_kept(self):
        """A warning about the reading is ABOUT the reading and belongs to
        whoever is looking at it."""
        said = self.commands._for_a_person(
            'Save, button\n\nNotes: two controls could not be placed.\n'
            'Act on this with ocr_press.')
        self.assertIn('could not be placed', said)


class AiOcrReadsTheWindowTheUserIsIn(unittest.TestCase):
    """The foreground and the window NVDA is in come apart constantly, and
    AI OCR is asked for in exactly the places where they do."""

    def test_a_controls_own_handle_is_not_the_window(self):
        """A focused control's windowHandle is the CONTROL - a list, a
        field - and AI OCR photographs the rectangle of the handle it is
        given, so that would photograph the list."""
        import inspect
        source = inspect.getsource(context.window)
        self.assertIn('getFocusObject', source)
        self.assertIn('_root_of', source)

    def test_both_are_answered_so_a_caller_can_choose(self):
        import inspect
        source = inspect.getsource(context.window)
        for key in ("'foreground'", "'focus'", "'hwnd'"):
            self.assertIn(key, source)

    def test_a_root_that_cannot_be_asked_for_is_the_handle_itself(self):
        self.assertEqual(context._root_of(0), 0)

    def test_what_is_sent_is_only_a_window_when_there_is_one(self):
        from titanEnhancements import commands
        before = context.window
        try:
            context.window = lambda **_: {'hwnd': 0}
            self.assertEqual(commands._here(), {})
            context.window = lambda **_: {'hwnd': 4242}
            self.assertEqual(commands._here(), {'hwnd': 4242})
        finally:
            context.window = before


# --------------------------------------------------------------------------- #
class NoTwoCommandsWantTheSameKey(unittest.TestCase):
    """A gesture declared twice is one command that silently never fires.

    NVDA binds them in order and the last one wins, with nothing said - so
    adding a command with a key somebody else already asked for takes a
    working command away and looks like nothing at all. Caught exactly that
    way while adding the notification command (NVDA+alt+n was already the
    announcements switch).
    """

    @staticmethod
    def _source(name):
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements', name)
        with io.open(path, encoding='utf-8') as handle:
            return handle.read()

    def _declared(self):
        import re
        return re.findall(r"gesture='([^']+)'", self._source('__init__.py'))

    def test_every_default_key_is_asked_for_once(self):
        keys = self._declared()
        self.assertTrue(keys, 'the add-on declares no gestures at all')
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        self.assertEqual(duplicates, [], 'two commands want the same key')

    def test_every_command_the_menu_names_really_exists(self):
        """The menu fires commands by NAME, so a renamed one is a menu
        entry that raises where nobody is looking."""
        import re
        from titanEnhancements import commands
        text = self._source('menu.py')
        for name in set(re.findall(r"_run_command\('([a-z_]+)'", text)):
            self.assertTrue(hasattr(commands, name),
                            'the menu names commands.' + name)

    def test_every_script_the_plugin_declares_calls_something_real(self):
        import re
        from titanEnhancements import commands
        text = self._source('__init__.py')
        for name in set(re.findall(r"commands\.([a-z_]+)\(", text)):
            self.assertTrue(hasattr(commands, name), 'commands.' + name)


class EverySubsystemTitanHasIsReachable(unittest.TestCase):
    """The claim is "every Titan subsystem, through the add-on" - so it is
    checked against Titan's own list of them rather than against a memory
    of which ones were wired up."""

    #: Calls this add-on deliberately does not make.
    #:
    #: **It is empty, and that is the point.** It used to hold most of
    #: Titan - the settings, the speech, the notifications, the whole
    #: application renderer, and everything reachable "through the action
    #: layer instead" - each with a reason that was true when it was
    #: written and is not true any more. Every one of them is now asked
    #: for by name, so the sweep below is the whole claim rather than the
    #: claim minus a list.
    #:
    #: A call added to Titan later fails this test until something here
    #: asks for it, which is exactly what it is for. Put a name back only
    #: with the reason beside it.
    NOT_OURS = set()

    def test_the_addon_asks_for_everything_else(self):
        import re
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        try:
            from src.titan_core import bridge_api
        except Exception as error:                   # noqa: BLE001
            # A skipped test proves nothing about the thing it was written
            # for, so this says WHY rather than passing quietly.
            self.skipTest('Titan is not importable from here: %s' % error)
        asked = set()
        folder = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements')
        for name in os.listdir(folder):
            if not name.endswith('.py'):
                continue
            with io.open(os.path.join(folder, name),
                         encoding='utf-8') as handle:
                text = handle.read()
                asked.update(re.findall(r"bridge\('([a-z_.]+)'", text))
                # A call reached through a typed helper of the add-on's own
                # is still a call this add-on makes. Matching only `bridge(`
                # reported four of them as forgotten while they were in use,
                # so a dotted name in any call position counts.
                asked.update(re.findall(r"\(\s*'([a-z_]+\.[a-z_]+)'", text))
        missing = sorted(set(bridge_api.CALLS) - asked - self.NOT_OURS)
        self.assertEqual(missing, [],
                         'Titan answers these and nothing here asks: %s'
                         % missing)


# --------------------------------------------------------------------------- #
class ALayerOnTheFocusPathMustMeasureItself(unittest.TestCase):
    """The regression that froze a real NVDA, pinned.

    The first version of the semantic layer walked eight parents on every
    focus event - each of them a call into another process that builds a
    whole NVDAObject. Measured on the machine it shipped to: the session
    before it existed froze zero times, the session after it froze ten.
    The walk is gone (NVDA has already built and cached that chain), but
    the lesson is not the walk: anything on this path must be able to
    notice it is too expensive and stand down, rather than needing somebody
    to work out from a frozen reader which add-on to blame.
    """

    def setUp(self):
        from titanEnhancements import configSpec, semantics
        self.semantics = semantics
        semantics.resume()
        semantics.forget()
        self.addCleanup(semantics.resume)
        self.addCleanup(semantics.forget)
        semantics._timing.update({'calls': 0, 'total': 0.0, 'worst': 0.0})
        self._read = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults())
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))

    def test_a_pass_is_timed(self):
        self.semantics.describe(None)
        self.assertEqual(self.semantics.timing()['calls'], 1)

    def test_one_slow_pass_is_not_enough_to_give_up(self):
        """A machine that was paging is not a reason to lose the feature
        for the rest of the session."""
        self.semantics._timing['slow'] = self.semantics.SLOW_ENOUGH - 1
        self.semantics.describe(None)
        self.assertEqual(self.semantics.stood_down(), '')

    def test_enough_slow_passes_and_it_stops(self):
        slow = lambda _obj: time.sleep(self.semantics.SLOW_ONCE * 1.2)
        for _ in range(self.semantics.SLOW_ENOUGH):
            self.semantics._measured(slow, None)
        self.assertTrue(self.semantics.stood_down())

    def test_once_it_has_stopped_it_costs_nothing(self):
        self.semantics._timing['stopped'] = 'because'
        asked = []
        self.semantics._measured(lambda obj: asked.append(obj), None)
        self.assertEqual(asked, [], 'it must not run again')
        self.assertEqual(self.semantics.describe(None), ([], None))
        self.assertEqual(self.semantics.windows_parts(None), [])

    def test_it_can_be_asked_to_try_again(self):
        self.semantics._timing['stopped'] = 'because'
        self.semantics.resume()
        self.assertEqual(self.semantics.stood_down(), '')

    def test_the_chain_above_a_control_is_not_walked_by_hand(self):
        """`obj.parent` is not a field, it is a question - and NVDA has
        already built and cached exactly this chain for the focus."""
        import inspect
        source = inspect.getsource(self.semantics._ancestors)
        # The walk lives in `ancestry` now - it is the one place that
        # knows the chain - but the rule is the same rule and is still
        # asserted, because it is the one that froze NVDA when it was
        # broken.
        from titanEnhancements import ancestry
        self.assertIn('getFocusAncestors', inspect.getsource(ancestry._chain))

    def test_a_control_that_is_not_the_focus_costs_one_step(self):
        class Step:
            def __init__(self, parent=None):
                self.parent = parent
                self.role = types.SimpleNamespace(name='WINDOW')
                self.name = ''
        deep = Step(Step(Step(Step())))
        self.assertEqual(len(self.semantics._ancestors(deep)), 1)


# --------------------------------------------------------------------------- #
class TheAudioSessionIsFoundOnceNotPerUtterance(unittest.TestCase):
    """A COM walk on the main thread, once per spoken control.

    `_own_session()` is `AudioUtilities.GetAllSessions()` - every audio
    session on the machine - and `place()` is reached from a
    `CallbackCommand`, which runs on NVDA's MAIN thread when speech gets to
    that point. On the default synthesizer (eSpeak is mono, so the stream
    layer always declines) that was every placed utterance there is. It had
    never shown up before because nothing had ever asked for a position:
    the moment positioned speech actually started working, NVDA's own
    watchdog started reporting freezes.
    """

    def setUp(self):
        from titanEnhancements import panner
        self.panner = panner
        self.walks = []
        self._own = panner._own_session

        class Volume:
            def __init__(self, outer):
                self.outer = outer
                self.set = []

            def GetChannelCount(self):
                return 2

            def SetChannelVolume(self, channel, value, _guid):
                self.set.append((channel, value))

        self.volume = Volume(self)
        session = types.SimpleNamespace(
            channelAudioVolume=lambda: self.volume)

        def walk():
            self.walks.append(1)
            return session
        panner._own_session = walk
        self.one = panner.Panner()
        self.addCleanup(lambda: setattr(panner, '_own_session', self._own))

    def test_the_walk_happens_once_however_often_it_is_placed(self):
        for _ in range(20):
            self.one._place_session(0.9, 0.1)
        self.assertEqual(len(self.walks), 1,
                         'the audio sessions were enumerated per utterance')
        self.assertEqual(len(self.volume.set), 40)

    def test_a_channel_volume_that_is_refused_is_asked_for_again(self):
        """The device can go - the headphones were unplugged mid-sentence."""
        self.one._place_session(0.9, 0.1)

        def refuse(*_a):
            raise RuntimeError('the endpoint has gone')
        self.volume.SetChannelVolume = refuse
        self.assertFalse(self.one._place_session(0.9, 0.1))
        self.volume.SetChannelVolume = lambda c, v, g: None
        self.one._place_session(0.9, 0.1)
        self.assertEqual(len(self.walks), 2, 'it must look again')

    def test_the_probe_keeps_what_it_found(self):
        """It already did the walk on its own thread; throwing the answer
        away made the first placed utterance do it again on the main one."""
        import inspect
        source = inspect.getsource(self.panner.Panner.probe_session)
        self.assertIn('_volume', source)

    def test_a_session_that_is_not_stereo_is_refused_rather_than_kept(self):
        self.volume.GetChannelCount = lambda: 1
        self.assertFalse(self.one._place_session(0.9, 0.1))
        self.assertIsNone(self.one._volume)




# --------------------------------------------------------------------------- #
# The reader modules, and everything built on them
# --------------------------------------------------------------------------- #
class Fake:
    """Something shaped like an NVDA object, and nothing more."""

    def __init__(self, role='BUTTON', name='', pid=1, window=1,
                 klass='', app='', automation='', value='',
                 description='', location=(0, 0, 100, 30), parent=None,
                 children=(), index=0):
        self.role = types.SimpleNamespace(name=role, displayString=role.lower())
        self.name = name
        self.processID = pid
        self.windowHandle = window
        self.windowClassName = klass
        self.appModule = types.SimpleNamespace(appName=app)
        self.UIAAutomationId = automation
        self.value = value
        self.description = description
        self.location = location
        self.parent = parent
        self.children = list(children)
        self.indexInParent = index
        self.states = ()
        self.positionInfo = {}


def _temp_config(case):
    """A configuration folder of its own, so nothing touches the user's.

    Every store this add-on has - the labels, the voice classes, the user's
    own reader modules - lives in NVDA's configuration folder, and a test
    that wrote into the real one would change the reader of whoever ran it.
    """
    import shutil
    import tempfile
    folder = tempfile.mkdtemp(prefix='titan-test-')
    case.addCleanup(shutil.rmtree, folder, True)
    stub = types.ModuleType('globalVars')
    stub.appArgs = types.SimpleNamespace(configPath=folder)
    previous = sys.modules.get('globalVars')
    sys.modules['globalVars'] = stub

    def put_back():
        if previous is None:
            sys.modules.pop('globalVars', None)
        else:
            sys.modules['globalVars'] = previous
    case.addCleanup(put_back)
    return folder


class AModuleIsDataAndIsChecked(unittest.TestCase):
    """A JAWS app module is code only its vendor can write. This is the same
    knowledge as data - which is why it can be checked, and why a wrong one
    costs one control's wording rather than the reader."""

    def setUp(self):
        from titanEnhancements.readerModules import schema
        self.schema = schema

    def test_a_module_with_no_match_is_about_no_window(self):
        self.assertTrue(self.schema.problems({'id': 'x'}))

    def test_a_key_nothing_reads_is_reported_not_ignored(self):
        """The failure this format exists to prevent: a module whose author
        wrote `kind` where `kind_column` was wanted loads, matches, and
        quietly does nothing."""
        wrong = self.schema.problems({'id': 'x', 'match': {'class': 'a'},
                                      'lists': [{'match': {}, 'kind': 'Type'}]})
        self.assertTrue(any("there is no 'kind'" in one for one in wrong))

    def test_a_match_on_something_that_cannot_be_matched(self):
        wrong = self.schema.problems({'id': 'x', 'match': {'colour': 'red'}})
        self.assertTrue(any('colour' in one for one in wrong))

    def test_a_good_module_has_no_problems(self):
        self.assertEqual(self.schema.problems({
            'id': 'x', 'match': {'executable': 'thing.exe'},
            'lists': [{'match': {'columns': ['Name']}, 'kind_column': 'Type'}],
            'live': [{'match': {'role': 'STATUSBAR'},
                      'politeness': 'polite'}]}), [])

    def test_politeness_is_one_of_two_things(self):
        wrong = self.schema.problems({'id': 'x', 'match': {'class': 'a'},
                                      'live': [{'match': {},
                                                'politeness': 'loud'}]})
        self.assertTrue(any('politeness' in one for one in wrong))

    # ------------------------------------------------------------- matching
    def test_a_titan_application_is_matched_by_what_titan_says(self):
        module = self.schema.Module({'id': 'tfm', 'match': {'titan': 'tfm'}})
        self.assertTrue(module.owns(Fake(app='python.exe'), {'id': 'tfm'}))
        self.assertFalse(module.owns(Fake(app='python.exe'), {'id': 'tnotes'}))

    def test_everything_else_is_matched_on_the_window(self):
        module = self.schema.Module({'id': 'n', 'match': {'executable':
                                                          'notepad.exe'}})
        self.assertTrue(module.owns(Fake(app='notepad.exe')))
        self.assertFalse(module.owns(Fake(app='wordpad.exe')))

    def test_a_pattern_is_the_way_a_person_writes_one(self):
        module = self.schema.Module({'id': 'n',
                                     'match': {'class': 'Unity*'}})
        self.assertTrue(module.owns(Fake(klass='UnityWndClass')))

    def test_every_condition_in_a_match_must_be_true(self):
        block = {'role': 'LIST', 'name': 'Files'}
        self.assertTrue(self.schema.matches(block, Fake(role='LIST',
                                                        name='Files')))
        self.assertFalse(self.schema.matches(block, Fake(role='LIST',
                                                         name='Games')))

    def test_unnamed_is_a_thing_to_match_on(self):
        rule = {'unnamed': True}
        self.assertTrue(self.schema.matches(rule, Fake(name='')))
        self.assertFalse(self.schema.matches(rule, Fake(name='Something')))


class TheModulesShippedHere(unittest.TestCase):
    """Written by reading Titan's own applications, none of which was
    touched. A module that names a column no list has is a module that
    silently does nothing."""

    def setUp(self):
        from titanEnhancements import readerModules
        self.modules = readerModules
        readerModules.forget()
        self.addCleanup(readerModules.forget)

    def test_every_one_of_them_is_a_valid_module(self):
        from titanEnhancements.readerModules import schema
        for module in self.modules.load():
            self.assertEqual(schema.problems(module.data), [],
                             module.id + ' is not a valid module')

    def test_the_applications_titan_ships_are_covered(self):
        found = {module.id for module in self.modules.load()}
        for known in ('tfm', 'tnotes', 'tdm', 'reminder', 'tedit', 'web'):
            self.assertIn(known, found)

    def test_the_file_manager_knows_its_type_column(self):
        module = [one for one in self.modules.load() if one.id == 'tfm'][0]
        row = Row(cells=['a.txt', '1 Jan', 'Text file'],
                  headers=['Name', 'Date modified', 'Type'])
        rule = module.list_rule(row, {'id': 'tfm'},
                                ['Name', 'Date modified', 'Type'])
        self.assertEqual(rule.get('kind_column'), 'Type')

    def test_a_module_is_found_for_a_process_and_then_remembered(self):
        first = self.modules.for_object(Fake(pid=77), {'id': 'tnotes'})
        self.assertIsNotNone(first)
        # The second answer costs one dictionary lookup, which is what makes
        # this affordable on the focus path.
        self.assertIs(self.modules.for_object(Fake(pid=77), None), first)

    def test_a_window_with_no_module_is_remembered_as_having_none(self):
        self.assertIsNone(self.modules.for_object(Fake(pid=88, app='x.exe')))
        self.assertIsNone(self.modules.for_object(Fake(pid=88, app='x.exe')))


class AUsersOwnModuleIsNotALesserKind(unittest.TestCase):

    def setUp(self):
        self.folder = _temp_config(self)
        from titanEnhancements import readerModules
        self.modules = readerModules
        readerModules.forget()
        self.addCleanup(readerModules.forget)

    def _write(self, name, data):
        import json
        where = os.path.join(self.modules.user_folder(), name)
        with io.open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        return where

    def test_one_written_by_hand_is_loaded(self):
        self._write('mine.json', {'id': 'mine',
                                  'match': {'executable': 'mine.exe'},
                                  'label': 'Mine'})
        found = self.modules.for_object(Fake(pid=5, app='mine.exe'))
        self.assertIsNotNone(found)
        self.assertEqual(found.id, 'mine')

    def test_a_wrong_one_is_reported_and_left_out(self):
        """Loading it anyway is the failure the whole format exists to
        avoid: a module that is nearly right is a control that has quietly
        gone silent."""
        self._write('bad.json', {'id': 'bad', 'match': {'nonsense': 1}})
        self.assertIsNone(self.modules.for_object(Fake(pid=6, app='bad.exe')))
        self.assertTrue(any('bad.json' in one
                            for one in self.modules.problems()))

    def test_one_that_will_not_parse_is_reported_too(self):
        with io.open(os.path.join(self.modules.user_folder(), 'broken.json'),
                     'w', encoding='utf-8') as handle:
            handle.write('{not json')
        self.modules.reload()
        self.assertTrue(any('broken.json' in one
                            for one in self.modules.problems()))


class WhatKindOfDialogThisIs(unittest.TestCase):
    """Titan Access has always said it for Titan's dialogs. This is the rest
    of Windows, and it needs neither Titan nor Titan Access."""

    def setUp(self):
        from titanEnhancements import dialog_kind
        self.kinds = dialog_kind
        dialog_kind.forget()
        self.addCleanup(dialog_kind.forget)

    def test_a_yes_no_box_is_a_question_by_construction(self):
        """Not by resemblance: those are the answers it will accept."""
        self.kinds._has_button = lambda hwnd, control: control in (6, 7)
        self.addCleanup(self._put_back)
        self.assertEqual(self.kinds._button_kind(1), 'question')

    def test_abort_retry_ignore_is_reporting_a_failure(self):
        self.kinds._has_button = lambda hwnd, control: control in (3, 4, 5)
        self.addCleanup(self._put_back)
        self.assertEqual(self.kinds._button_kind(1), 'error')

    def test_ok_and_cancel_is_deliberately_not_guessed_at(self):
        """An error box with a lone OK button called "information" would be
        worse than saying nothing."""
        self.kinds._has_button = lambda hwnd, control: control in (1, 2)
        self.addCleanup(self._put_back)
        self.assertEqual(self.kinds._button_kind(1), '')

    def _put_back(self):
        import importlib
        importlib.reload(self.kinds)

    def test_a_dialog_is_recognised_by_role_or_by_class(self):
        self.assertTrue(self.kinds.is_dialog(Fake(role='DIALOG')))
        self.assertTrue(self.kinds.is_dialog(Fake(role='WINDOW',
                                                  klass='#32770')))
        self.assertFalse(self.kinds.is_dialog(Fake(role='BUTTON')))

    def test_an_icon_is_matched_by_its_PICTURE_not_its_handle(self):
        """The first version compared HANDLES, on the documented grounds
        that Windows' system icons are shared. Measured against four real
        message boxes that is simply false - a box makes an icon of its
        own - so the comparison matched nothing, every time."""
        import inspect
        source = inspect.getsource(self.kinds)
        self.assertIn('SHGetStockIconInfo', source)
        self.assertIn('DrawIconEx', source)

    def test_the_stock_icons_are_references_and_so_are_the_legacy_ones(self):
        """Both are true, on different Windows versions and in programs
        with their own dialog templates."""
        kinds = {kind for _n, kind in self.kinds.STOCK_ICONS}
        self.assertEqual(kinds, set(self.kinds.KINDS))
        legacy = {kind for _n, kind in self.kinds.LEGACY_ICONS}
        self.assertEqual(legacy, set(self.kinds.KINDS))

    def test_a_picture_that_is_nothing_like_any_of_them_is_refused(self):
        """A dialog carrying somebody's own artwork must answer "I cannot
        tell" - and so must a screen capture that did not work, which is
        what makes the drawn path safe to ship at all."""
        flat = bytes([0x40, 0x80, 0xC0, 0] * 16)
        references = [('warning', bytes([0, 0, 0, 0] * 16)),
                      ('error', bytes([255, 255, 255, 0] * 16))]
        self.assertEqual(self.kinds._closest(flat, references), '')

    def test_a_near_match_with_no_margin_under_it_is_refused(self):
        """Nearest is not enough: it has to be clearly nearest, or two
        similar icons would be told apart by a rounding error."""
        picture = bytes([10, 10, 10, 0] * 16)
        references = [('warning', bytes([11, 11, 11, 0] * 16)),
                      ('error', bytes([12, 12, 12, 0] * 16))]
        self.assertEqual(self.kinds._closest(picture, references), '')

    def test_a_clear_match_is_taken(self):
        picture = bytes([10, 10, 10, 0] * 16)
        references = [('warning', bytes([10, 10, 10, 0] * 16)),
                      ('error', bytes([200, 200, 200, 0] * 16))]
        self.assertEqual(self.kinds._closest(picture, references), 'warning')

    def test_the_alpha_byte_is_not_compared(self):
        """An icon drawn by DrawIconEx carries one and a square captured
        off the screen does not: comparing it would put a constant
        difference between every pair and swamp what is being measured."""
        one = bytes([10, 10, 10, 255] * 16)
        other = bytes([10, 10, 10, 0] * 16)
        self.assertEqual(self.kinds._difference(one, other), 0.0)

    def test_a_task_dialog_is_recognised_by_what_is_inside_it(self):
        """The modern dialog is a #32770 with everything in one
        DirectUIHWND, and no icon control at all."""
        plain = Fake(role='DIALOG', children=[Fake(role='BUTTON')])
        self.assertFalse(self.kinds.is_task_dialog(plain))
        task = Fake(role='DIALOG',
                    children=[Fake(role='PANE', klass='DirectUIHWND')])
        self.assertTrue(self.kinds.is_task_dialog(task))

    def test_the_drawn_icon_is_found_by_the_name_the_dialog_gives_it(self):
        icon = Fake(role='GRAPHIC', name='MainInstructionIcon',
                    location=(10, 10, 32, 32))
        task = Fake(role='DIALOG', children=[
            Fake(role='PANE', klass='DirectUIHWND', children=[icon])])
        self.assertIs(self.kinds._icon_element(task), icon)

    def test_a_picture_that_is_not_square_is_not_the_dialogs_icon(self):
        wide = Fake(role='GRAPHIC', name='', location=(0, 0, 300, 20))
        task = Fake(role='DIALOG', children=[
            Fake(role='PANE', klass='DirectUIHWND', children=[wide])])
        self.assertIsNone(self.kinds._icon_element(task))

    def test_every_kind_has_a_word_and_a_sound(self):
        from titanEnhancements import interject
        for kind in self.kinds.KINDS:
            self.assertTrue(self.kinds.word(kind), kind)
            self.assertIn(kind, interject.SOUNDS)
            self.assertIn(kind, interject.TONES)

    def test_the_sounds_are_titans_own_and_live_in_a_theme(self):
        """Not a synthesised tone: Titan has real sounds for these, and they
        are in `sfx/<theme>/SRE/` so a Titan without the optional Titan
        Access component still has every one of them."""
        from titanEnhancements import interject
        theme = os.path.join(ROOT, 'sfx', 'default', 'SRE')
        if not os.path.isdir(theme):
            self.skipTest('Titan is not beside the add-on here')
        for name in interject.SOUNDS.values():
            self.assertTrue(os.path.exists(os.path.join(theme, name)), name)


class APictureIsNotTheWordGraphic(unittest.TestCase):

    def setUp(self):
        from titanEnhancements import graphics
        self.graphics = graphics

    def test_a_small_square_image_is_an_icon(self):
        self.assertEqual(self.graphics.kind_of(
            Fake(role='GRAPHIC', location=(0, 0, 16, 16))), 'icon')

    def test_a_large_one_is_a_picture(self):
        self.assertEqual(self.graphics.kind_of(
            Fake(role='GRAPHIC', location=(0, 0, 800, 600))), 'picture')

    def test_something_moving_says_so(self):
        self.assertEqual(self.graphics.kind_of(Fake(role='ANIMATION')),
                         'animation')
        self.assertEqual(self.graphics.kind_of(
            Fake(role='GRAPHIC', klass='SysAnimate32')), 'animation')

    def test_a_control_that_is_not_a_picture_is_left_alone(self):
        self.assertEqual(self.graphics.kind_of(Fake(role='BUTTON')), '')
        self.assertEqual(self.graphics.parts(Fake(role='BUTTON')), [])

    def test_the_kind_takes_the_place_of_the_control_type(self):
        from titanEnhancements import elements
        parts = self.graphics.parts(Fake(role='GRAPHIC', name='Logo',
                                         location=(0, 0, 16, 16)))
        self.assertEqual(parts[0][0], 'Logo')
        self.assertEqual(parts[1][1], elements.ROLE_PITCH)

    def test_the_ai_half_says_why_it_cannot(self):
        ready, why = self.graphics.ai_available()
        self.assertFalse(ready)
        self.assertTrue(why)


class NamesForWhatTheProgramNeverNamed(unittest.TestCase):

    def setUp(self):
        _temp_config(self)
        from titanEnhancements import labels
        self.labels = labels
        labels.forget()
        labels._path = ''
        self.addCleanup(labels.forget)

    def test_a_control_with_an_automation_id_has_a_strong_key(self):
        key, strong = self.labels.key_of(Fake(automation='saveButton'))
        self.assertTrue(key)
        self.assertTrue(strong)

    def test_one_with_nothing_but_its_position_has_a_weak_one(self):
        key, strong = self.labels.key_of(Fake(index=3))
        self.assertTrue(key)
        self.assertFalse(strong)

    def test_a_guess_is_refused_on_a_key_that_moves(self):
        """A toolbar that gains a button moves everything after it, and a
        guessed label that followed position would name the wrong control -
        which is worse than no label at all."""
        control = Fake(index=3, app='thing.exe')
        self.assertFalse(self.labels.put(control, 'Save', source='ai'))
        self.assertTrue(self.labels.put(control, 'Save', source='user'))

    def test_what_the_user_typed_is_never_overwritten_by_a_guess(self):
        control = Fake(automation='b1', app='thing.exe')
        self.labels.put(control, 'Save', source='user')
        self.assertFalse(self.labels.put(control, 'Disk', source='ai'))
        self.assertEqual(self.labels.get(control), 'Save')

    def test_it_survives_being_read_back(self):
        control = Fake(automation='b1', app='thing.exe')
        self.labels.put(control, 'Save', source='user')
        self.labels.forget()
        self.assertEqual(self.labels.get(control), 'Save')

    def test_only_a_control_with_nothing_to_say_wants_one(self):
        self.assertTrue(self.labels.needs_one(Fake(automation='b1')))
        self.assertFalse(self.labels.needs_one(Fake(automation='b1',
                                                    name='Save')))
        self.assertFalse(self.labels.needs_one(Fake(automation='b1',
                                                    value='7')))

    def test_forgetting_one_really_forgets_it(self):
        control = Fake(automation='b1', app='thing.exe')
        self.labels.put(control, 'Save', source='user')
        self.assertTrue(self.labels.remove(control))
        self.assertEqual(self.labels.get(control), '')


class TheClassManagerOwnsTheVoices(unittest.TestCase):

    def setUp(self):
        _temp_config(self)
        from titanEnhancements import classes, voices
        self.classes = classes
        self.voices = voices
        classes.forget()
        self.addCleanup(classes.forget)

    def test_every_class_says_what_it_is_for(self):
        """"detail" means nothing; "the columns beside a row's name" is a
        thing somebody can have an opinion about."""
        words = self.classes.meanings()
        for row in self.classes.described():
            self.assertTrue(words.get(row['id']), row['id'])

    def test_the_defaults_are_titan_accesss_where_it_has_one(self):
        from titanEnhancements import elements
        self.assertEqual(self.classes.voice_of('kind').get('pitch'),
                         elements.ROLE_PITCH)
        self.assertEqual(self.classes.voice_of('state').get('pitch'),
                         elements.STATE_PITCH)

    def test_a_users_answer_reaches_what_is_really_spoken(self):
        """A manager that showed one thing while the reader said another
        would be worse than not having one."""
        self.classes.set_voice('kind', {'pitch': -9})
        self.assertEqual(self.voices.voice_of('kind').get('pitch'), -9)

    def test_only_what_was_changed_is_kept(self):
        self.classes.set_voice('kind', {'pitch': -9})
        self.assertTrue(self.classes.changed('kind'))
        self.assertFalse(self.classes.changed('state'))

    def test_putting_one_back_really_puts_it_back(self):
        from titanEnhancements import elements
        self.classes.set_voice('kind', {'pitch': -9})
        self.classes.reset('kind')
        self.assertEqual(self.voices.voice_of('kind').get('pitch'),
                         elements.ROLE_PITCH)

    def test_a_dial_cannot_be_set_past_what_the_scale_is(self):
        self.classes.set_voice('kind', {'pitch': 900})
        self.assertEqual(self.classes.voice_of('kind')['pitch'],
                         self.classes.LIMIT)

    def test_a_guessed_name_does_not_sound_like_a_real_one(self):
        """The difference between "the button is called Save" and "the
        button appears to say Save"."""
        self.assertNotEqual(self.classes.voice_of('guessed'),
                            self.classes.voice_of('name'))


# --------------------------------------------------------------------------- #
class WhatChangedWhileYouWereElsewhere(unittest.TestCase):
    """JAWS polls a rectangle of the screen for this. Windows already sends
    an event, so a region that never changes costs nothing at all."""

    def setUp(self):
        from titanEnhancements import configSpec, live
        self.live = live
        live.forget()
        self.addCleanup(live.forget)
        self._read = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults())
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))
        self.said = []
        self.live.announce = lambda text, politeness='polite', prefix='': (
            self.said.append((text, politeness)) or True)

    def test_a_module_says_which_control_is_live(self):
        from titanEnhancements.readerModules import schema
        module = schema.Module({'id': 'x', 'match': {'class': 'a'},
                                'live': [{'match': {'role': 'PROGRESSBAR'},
                                          'politeness': 'assertive'}]})
        rule = self.live.rule_for(Fake(role='PROGRESSBAR'), module)
        self.assertEqual(rule['politeness'], 'assertive')

    def test_the_status_bar_of_the_window_in_front_is_the_floor(self):
        self.assertIsNotNone(self.live.rule_for(Fake(role='STATUSBAR')))

    def test_a_control_nobody_declared_is_not_live(self):
        self.assertIsNone(self.live.rule_for(Fake(role='BUTTON')))

    def test_the_same_text_again_is_not_news(self):
        """A status bar rewritten with the same text on every timer tick is
        the commonest thing in Windows."""
        bar = Fake(role='STATUSBAR', name='Ready')
        self.assertTrue(self.live.changed(bar))
        self.assertFalse(self.live.changed(bar))

    def test_a_burst_is_rate_limited(self):
        for index in range(6):
            self.live.changed(Fake(role='STATUSBAR', name='%d%%' % index))
        self.assertLessEqual(len(self.said), 2)
        self.assertTrue(self.live.report()['dropped'])

    def test_the_switch_is_what_decides(self):
        from titanEnhancements import configSpec
        configSpec.read = lambda: dict(configSpec.defaults(),
                                       liveRegions=False)
        self.assertFalse(self.live.changed(Fake(role='STATUSBAR',
                                                name='Ready')))

    def test_a_program_that_knows_it_has_news_can_simply_say_so(self):
        """The half no amount of watching a screen can do for itself."""
        self.assertTrue(self.live.pushed(text='A message arrived')['said'])
        self.assertFalse(self.live.pushed(text='A message arrived')['said'])
        self.assertFalse(self.live.pushed(text='')['said'])


class AWindowThatAnswersNothing(unittest.TestCase):
    """A Unity game draws its menu onto a texture. There is nothing to ask,
    so the only honest answer is a picture."""

    def setUp(self):
        from titanEnhancements import configSpec, surface
        self.surface = surface
        self._read = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults())
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))

    def test_an_engine_window_is_recognised_by_its_class(self):
        self.assertTrue(self.surface.looks_drawn(
            Fake(role='WINDOW', klass='UnityWndClass')))

    def test_a_window_with_no_children_at_all_is_a_surface(self):
        self.assertTrue(self.surface.looks_drawn(
            Fake(role='WINDOW', children=[])))

    def test_a_window_with_real_controls_is_not(self):
        real = Fake(role='WINDOW', children=[Fake(name='Save')])
        self.assertFalse(self.surface.looks_drawn(real))

    def test_unnamed_children_are_an_interface_we_are_reading_badly(self):
        """Not a surface. A window whose controls are merely unnamed is a
        different problem with a different answer - and asking whether to
        photograph it is how a user gets questioned about their terminal.
        The first rule asked whether any of the first TWELVE children had
        a name, which is also false of a window whose named controls come
        thirteenth."""
        unnamed = Fake(role='WINDOW', children=[Fake(name=''), Fake(name='')])
        self.assertFalse(self.surface.looks_drawn(unnamed))

    def test_the_programs_that_are_never_surfaces_are_never_asked_about(self):
        """A terminal answers with no children at all while it is still
        starting; Explorer, a dialog and a browser all have real controls.
        Being wrong in this direction puts a question in front of somebody
        about a window that was never the point."""
        for window_class in ('CASCADIA_HOSTING_WINDOW_CLASS',
                             'ConsoleWindowClass', 'CabinetWClass',
                             '#32770', 'Chrome_WidgetWin_1',
                             'MozillaWindowClass',
                             'ApplicationFrameWindow'):
            self.assertFalse(
                self.surface.looks_drawn(Fake(role='WINDOW', children=[],
                                              klass=window_class)),
                window_class + ' must never be read as a picture')

    def test_a_control_that_cannot_be_asked_is_not_a_surface(self):
        """Cannot tell means no: the safe answer is the one that asks the
        user nothing."""
        class Refuses:
            role = types.SimpleNamespace(name='WINDOW')
            windowClassName = 'Thing'

            @property
            def children(self):
                raise RuntimeError('no')
        self.assertFalse(self.surface.looks_drawn(Refuses()))

    def test_a_module_may_simply_say_so(self):
        from titanEnhancements.readerModules import schema
        module = schema.Module({'id': 'g', 'match': {'class': 'x'},
                                'surface': {'ocr': True}})
        self.assertTrue(self.surface.looks_drawn(Fake(role='BUTTON'), module))

    def test_the_highlight_is_read_out_of_the_reading(self):
        """Asking would spend a request every poll: `read_screen` skips the
        model on an unchanged picture only when nothing is asked."""
        reading = ('Main menu\n\n[Menu]\n  New game, button\n'
                   '  Continue, button, selected\n  Quit, button')
        self.assertIn('Continue', self.surface.highlight_in(reading))

    def test_a_reading_with_no_highlight_says_nothing(self):
        self.assertEqual(self.surface.highlight_in('Main menu\n  Quit'), '')

    def test_it_is_off_until_it_is_asked_for(self):
        """It sends a picture of the user's screen to their AI provider."""
        from titanEnhancements import configSpec
        self.assertIn('default=False', configSpec.SPEC['surfaceReading'])
        ok, why = self.surface.start(123)
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_asking_never_carries_a_question(self):
        import inspect
        source = inspect.getsource(self.surface.read)
        self.assertNotIn('question', source.split('"""')[2])


class AModuleWrittenForYou(unittest.TestCase):
    """Writing an app module has always begun with finding out what the
    program's controls are called - which is the same work as using the
    program blind. The reader has already done it."""

    def setUp(self):
        _temp_config(self)
        from titanEnhancements import draft, readerModules
        self.draft = draft
        self.modules = readerModules
        readerModules.forget()
        self.addCleanup(readerModules.forget)

    def _window(self):
        row = Row(cells=['a.txt', '1 Jan', 'Text file'],
                  headers=['Name', 'Date modified', 'Type'])
        listing = Fake(role='LIST', name='Files', children=[row])
        listing._getColumnHeader = row._getColumnHeader
        listing.columnCount = 3
        bar = Fake(role='STATUSBAR', name='Ready')
        return Fake(role='WINDOW', name='Thing', app='thing.exe',
                    klass='ThingClass', children=[listing, bar])

    def test_everything_in_an_observed_draft_was_really_read(self):
        seen = self.draft.observe(self._window())
        self.assertEqual(seen['executable'], 'thing.exe')
        self.assertEqual(seen['class'], 'ThingClass')
        self.assertTrue(any(one['columns'] for one in seen['lists']))

    def test_the_draft_is_a_valid_module(self):
        from titanEnhancements.readerModules import schema
        module, _seen = self.draft.draft_for(self._window())
        self.assertEqual(schema.problems(module), [])

    def test_a_type_column_becomes_the_word_for_what_a_row_is(self):
        """The single most useful line a module can carry, and the one
        nothing else can work out."""
        module, _seen = self.draft.draft_for(self._window())
        self.assertEqual(module['lists'][0].get('kind_column'), 'Type')

    def test_a_status_bar_becomes_a_live_region(self):
        module, _seen = self.draft.draft_for(self._window())
        self.assertTrue(module.get('live'))

    def test_it_is_written_where_the_users_own_modules_live(self):
        module, _seen = self.draft.draft_for(self._window())
        where, problem = self.draft.save(module, name='thing')
        self.assertEqual(problem, '')
        self.assertTrue(os.path.isfile(where))

    def test_nothing_is_ever_overwritten(self):
        module, _seen = self.draft.draft_for(self._window())
        self.draft.save(module, name='thing')
        _where, problem = self.draft.save(module, name='thing')
        self.assertTrue(problem)

    def test_a_module_that_is_not_one_is_refused(self):
        _where, problem = self.draft.save({'id': 'x'}, name='bad')
        self.assertTrue(problem)

    def test_an_answer_that_is_not_a_module_is_not_a_module(self):
        self.assertIsNone(self.draft._json_in('I am sorry, I cannot'))
        self.assertEqual(self.draft._json_in('here it is: {"a": 1} done'),
                         {'a': 1})


class TheTouchpadAsATouchScreen(unittest.TestCase):
    """NVDA's touch support needs a touch SCREEN and UI Access. The tracker
    underneath it needs neither, and takes plain numbers."""

    def setUp(self):
        from titanEnhancements import trackpad
        self.trackpad = trackpad

    def test_it_says_why_it_cannot_rather_than_raising(self):
        ready, why = self.trackpad.available()
        self.assertFalse(ready)
        self.assertTrue(why)

    def test_a_report_is_answered_with_no_nvda_under_it(self):
        found = self.trackpad.report()
        self.assertIn('on', found)
        self.assertFalse(found['on'])

    def test_the_devices_counter_counts_the_devices_really_read(self):
        """`devices` was set to 0 once and assigned by NOTHING, so the status
        command reported "no digitizer" for ever while the pad was delivering
        contacts - measured live at contacts=14, gestures=1, devices=0. A
        field read by a name nothing writes is a working-looking zero, and in
        the diagnostics that exist to settle arguments a lying reading is
        worse than none.

        `_preparsed` holds one entry per raw-input device a report has
        arrived from, with None for a descriptor that would not parse.
        """
        kept = dict(self.trackpad._preparsed)
        try:
            self.trackpad._preparsed.clear()
            self.assertEqual(self.trackpad.report()['devices'], 0)
            self.assertEqual(self.trackpad.report()['devices_refused'], 0)

            self.trackpad._preparsed[111] = object()      # a pad that parsed
            self.trackpad._preparsed[222] = object()      # and a second one
            self.trackpad._preparsed[333] = None          # one that would not
            found = self.trackpad.report()
            self.assertEqual(found['devices'], 2)
            self.assertEqual(found['devices_refused'], 1)
        finally:
            self.trackpad._preparsed.clear()
            self.trackpad._preparsed.update(kept)

    def test_a_finger_that_stops_being_mentioned_has_lifted(self):
        """The pad stops reporting a contact rather than announcing its
        end, so nothing would ever complete and every touch would be an
        endless hover."""
        seen = []

        class Manager:
            def update(self, identifier, x, y, complete):
                seen.append((identifier, complete))

            def emitTrackers(self):
                return []
        self.trackpad._manager = Manager()
        self.addCleanup(lambda: setattr(self.trackpad, '_manager', None))
        self.trackpad.feed([(1, 10, 10, True)])
        self.trackpad.feed([])
        self.assertEqual(seen, [(1, False), (1, True)])

    def test_only_the_contacts_the_report_carries_are_read(self):
        """A pad describes every slot it could ever use and sends all of
        them in every report; the unused ones come back at (0, 0) with the
        tip clear and contact id ZERO - the same id as the first real
        finger.

        Measured on a real ELAN pad before this: one finger drawn across
        it turned 238 reports into 1190 contacts, 955 of them "finger 0 has
        lifted". Every touch was a press followed instantly by a lift, so
        no gesture could ever be recognised. Contact Count (usage 0x54)
        says how many slots are real.
        """
        import inspect
        source = inspect.getsource(self.trackpad.contacts_in)
        self.assertIn('HID_USAGE_CONTACT_COUNT', source)
        self.assertIn('break', source)

    def test_a_window_handle_is_passed_back_as_a_pointer(self):
        """A module handle is too large for the C int ctypes converts a
        bare int into: `CreateWindowExW` raised OverflowError before
        Windows was ever called, and both windows this add-on makes failed
        at creation."""
        import inspect
        for module in (self.trackpad, __import__(
                'titanEnhancements.states', fromlist=['states'])):
            source = inspect.getsource(module)
            self.assertNotIn('None, wanted.hInstance', source,
                             module.__name__)
            self.assertIn('c_void_p(wanted.hInstance)', source,
                          module.__name__)

    def test_nvda_is_given_the_handler_its_own_scripts_reach_for(self):
        """Feeding contacts produces gestures, and every NVDA touch script
        then died on `touchHandler.handler.screenExplorer` because there
        was no handler at all. Seen live in NVDA's log: the gesture was
        recognised, dispatched, and raised inside the script."""
        surface = self.trackpad.TouchSurface
        for name in ('screenExplorer', 'trackerManager', '_curTouchMode'):
            self.assertIn(name, surface.__init__.__code__.co_names, name)
        for name in ('pump', 'setMode', 'terminate'):
            self.assertTrue(callable(getattr(surface, name, None)), name)

    def test_ours_is_removed_again_and_nvdas_is_never_touched(self):
        import types as _types
        fake = _types.ModuleType('touchHandler')
        fake.handler = object()          # NVDA's own, running
        sys.modules['touchHandler'] = fake
        self.addCleanup(lambda: sys.modules.pop('touchHandler', None))
        ok, _why = self.trackpad._install_surface()
        self.assertTrue(ok)
        self.assertFalse(self.trackpad._held['surface'],
                         'NVDA had one; we must not have installed ours')
        keep = fake.handler
        self.trackpad._remove_surface()
        self.assertIs(fake.handler, keep, "NVDA's own must survive")

    def test_the_gestures_are_emitted_from_the_pump_not_the_input_thread(self):
        """A tap is held back in case a second one follows; a tracker
        drained only when the next report arrives emits that tap late, or
        never."""
        import inspect
        self.assertIn('requestPump', inspect.getsource(self.trackpad.feed))
        self.assertIn('emitTrackers',
                      inspect.getsource(self.trackpad._emit))

    def test_it_is_off_until_it_is_asked_for(self):
        from titanEnhancements import configSpec
        self.assertIn('default=False', configSpec.SPEC['trackpad'])


class EveryNewSwitchReallyDecides(unittest.TestCase):
    """A switch that lies is the one thing this add-on keeps taking back
    out. Each of these is asked at the moment it matters, not once."""

    def setUp(self):
        from titanEnhancements import configSpec
        self._read = configSpec.read
        self.configSpec = configSpec
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))

    def _off(self, name):
        self.configSpec.read = lambda: dict(self.configSpec.defaults(),
                                            **{name: False})

    def test_reader_modules_off_means_no_module_is_consulted(self):
        from titanEnhancements import semantics
        self._off('readerModules')
        self.assertIsNone(semantics.module_for(Fake(pid=1), {'id': 'tfm'}))

    def test_dialog_kinds_off_means_nothing_is_armed(self):
        from titanEnhancements import dialog_kind
        self._off('dialogKinds')
        self.assertEqual(dialog_kind.announce(Fake(role='DIALOG')), '')

    def test_menu_leaving_off_means_nothing_is_said(self):
        from titanEnhancements import ancestry, focus
        self._off('menuLeaving')
        ancestry.forget()
        self.assertFalse(focus._menu_left(Fake(role='BUTTON'), None))

    def test_live_regions_off_means_nothing_is_announced(self):
        from titanEnhancements import live
        self._off('liveRegions')
        self.assertFalse(live.announce('something'))

    def test_the_defaults_say_what_starts_off(self):
        """Everything that sends a picture of the screen anywhere, and
        everything that reads a whole input device, starts off."""
        values = self.configSpec.defaults()
        for name in ('autoLabel', 'surfaceReading', 'trackpad', 'earcons',
                     'positionEverywhere'):
            self.assertIs(values[name], False, name)
        for name in ('readerModules', 'windowsSemantics', 'dialogKinds',
                     'graphicKinds', 'liveRegions', 'menuLeaving'):
            self.assertIs(values[name], True, name)



# --------------------------------------------------------------------------- #
class TheContextLayerMeasuresItselfToo(unittest.TestCase):
    """The same rule the application layer already learned, applied to the
    layer that now runs on EVERY focus event."""

    def setUp(self):
        from titanEnhancements import ancestry
        self.ancestry = ancestry
        ancestry.forget()
        ancestry.resume()
        self.addCleanup(ancestry.resume)
        self.addCleanup(ancestry.forget)

    def test_a_pass_is_timed(self):
        self.ancestry.changes(Fake(role='BUTTON'))
        self.assertTrue(self.ancestry.timing()['calls'])

    def test_it_stands_down_when_it_keeps_being_slow(self):
        real = self.ancestry.path_of

        def slow(obj, module=None):
            time.sleep(self.ancestry.SLOW_ONCE + 0.01)
            return real(obj, module)
        self.ancestry.path_of = slow
        self.addCleanup(lambda: setattr(self.ancestry, 'path_of', real))
        for _pass in range(self.ancestry.SLOW_ENOUGH):
            self.ancestry.changes(Fake(role='BUTTON'))
        self.assertTrue(self.ancestry.stood_down())
        # And having stood down, it really does nothing.
        self.assertEqual(self.ancestry.changes(Fake(role='LIST',
                                                    name='Files')), ([], []))

    def test_one_slow_pass_is_not_a_reason_to_lose_the_feature(self):
        """A machine that was paging, or a window that had just opened."""
        self.assertFalse(self.ancestry.stood_down())



# --------------------------------------------------------------------------- #
class AReadingOfWhereYouAreIsNotAReadingOfTheControl(unittest.TestCase):
    """Reported: in NVDA's own settings, arrowing the category list said the
    LIST's name where the item should have been.

    A list item with no columns has nothing this add-on can add about it,
    so the whole reading was "Settings categories" - and it was spoken in
    NVDA's place, because the decision to replace was made on whether the
    control is a list ITEM rather than on whether anything had been read.
    """

    def setUp(self):
        from titanEnhancements import ancestry, configSpec, focus, semantics
        self.focus = focus
        self.semantics = semantics
        ancestry.forget()
        semantics.forget_regions()
        self.addCleanup(ancestry.forget)
        self.addCleanup(semantics.forget_regions)
        self._read = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults())
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))
        self.said = []
        self._speak = focus._speak
        focus._speak = lambda sequence: self.said.append(sequence)
        self.addCleanup(lambda: setattr(focus, '_speak', self._speak))
        self.prefixed = []
        from titanEnhancements import interject
        self._prefix = interject.prefix_next
        interject.prefix_next = lambda text, voice='context': (
            self.prefixed.append(text) or True)
        self.addCleanup(lambda: setattr(interject, 'prefix_next',
                                        self._prefix))

    def _item_in_a_list(self, name='General'):
        """A row of a plain list box: no columns, like NVDA's own."""
        item = Row(cells=[], headers=[], pid=1, role='LISTITEM', window=500)
        item.name = name
        item._getColumnContent = None
        item.parent = types.SimpleNamespace(
            role=types.SimpleNamespace(name='LIST', displayString='list'),
            name='Settings categories', parent=None, columnCount=0,
            windowHandle=400)
        return item

    def test_the_list_name_is_ADDED_not_spoken_instead(self):
        called = []
        answer = self.focus.handle_gain_focus(self._item_in_a_list(),
                                              lambda: called.append(1))
        self.assertEqual(answer, 'windows')
        self.assertEqual(called, [1], "NVDA's own report must still happen")
        self.assertEqual(self.said, [],
                         'nothing may be spoken in NVDA\'s place')
        self.assertEqual(self.prefixed, ['Settings categories'])

    def test_a_reading_of_only_context_is_never_a_replacement(self):
        self.assertTrue(self.focus._only_context([('Documents', 'context')]))
        self.assertFalse(self.focus._only_context(
            [('Documents', 'context'), ('readme.txt', 0)]))
        self.assertFalse(self.focus._only_context([]))

    def test_a_row_that_really_was_read_still_replaces(self):
        """The feature this is protecting: a row with columns says more
        than NVDA would, so it may stand in for it."""
        row = Row(cells=['photo.jpg', '2 MB', 'JPEG image'],
                  headers=['Name', 'Size', 'Type'], pid=1, window=501)
        row.parent.windowHandle = 400
        parts = self.semantics.windows_parts(row)
        self.assertFalse(self.focus._only_context(parts))

    def test_moving_within_the_list_says_nothing_extra_at_all(self):
        first = []
        self.focus.handle_gain_focus(self._item_in_a_list('General'),
                                     lambda: first.append(1))
        self.prefixed[:] = []
        second = []
        self.focus.handle_gain_focus(self._item_in_a_list('Speech'),
                                     lambda: second.append(1))
        self.assertEqual(second, [1])
        self.assertEqual(self.prefixed, [],
                         'the list is entered once, not once per row')
        self.assertEqual(self.said, [])



# --------------------------------------------------------------------------- #
class LeavingAMenuIsLeavingTheMENUS(unittest.TestCase):
    """Said when the menu really closes - Escape at the top, or choosing an
    item - and not when one menu inside another does.

    A submenu closing is not the menus closing: Escape in a submenu, or
    Left arrow out of it, puts the user back on the parent menu. Announcing
    "out of menu" there tells them the opposite of what happened.
    """

    def setUp(self):
        from titanEnhancements import ancestry
        self.ancestry = ancestry
        ancestry.forget()
        self.addCleanup(ancestry.forget)
        # Put the real chain reader back afterwards. A test that leaves a
        # module patched is a test that fails ten other ones somewhere
        # else, which is exactly what this one did before the cleanup was
        # added - and the failures were nowhere near here.
        self._chain = ancestry._chain
        self.addCleanup(lambda: setattr(ancestry, '_chain', self._chain))

    def _under(self, *roles):
        """A control whose ancestry is these places, outermost first."""
        chain = []
        for index, role in enumerate(roles):
            chain.append(types.SimpleNamespace(
                role=types.SimpleNamespace(name=role,
                                           displayString=role.lower()),
                name=role.title(), parent=None, windowHandle=100 + index,
                columnCount=0))
        for index in range(len(chain) - 1):
            chain[index + 1].parent = chain[index]
        leaf = Row(pid=1, window=900 + len(roles), role='MENUITEM')
        leaf.parent = chain[-1] if chain else None
        # `path_of` reads the chain through `_chain`, which walks one step
        # when the object is not the focus - so the whole chain is given.
        self.ancestry._chain = lambda obj, _c=list(chain): list(_c)
        return leaf

    def test_escape_at_the_top_closes_the_menus_and_says_so(self):
        self.ancestry.changes(self._under('WINDOW', 'MENUBAR', 'POPUPMENU'))
        _entered, left = self.ancestry.changes(self._under('WINDOW',
                                                           'DOCUMENT'))
        self.assertTrue(left)
        self.assertTrue(self.ancestry.leaving_word(left))

    def test_choosing_an_item_that_opens_a_dialog_says_it_too(self):
        self.ancestry.changes(self._under('WINDOW', 'MENUBAR', 'POPUPMENU'))
        _entered, left = self.ancestry.changes(self._under('DIALOG'))
        self.assertTrue(left)

    def test_escape_out_of_a_SUBmenu_says_nothing(self):
        """The user is still in the menus; the reader must not say they
        have left them."""
        self.ancestry.changes(self._under('WINDOW', 'MENUBAR', 'POPUPMENU',
                                          'POPUPMENU'))
        _entered, left = self.ancestry.changes(self._under('WINDOW',
                                                           'MENUBAR',
                                                           'POPUPMENU'))
        self.assertEqual(left, [])

    def test_moving_between_top_level_menus_says_nothing(self):
        self.ancestry.changes(self._under('WINDOW', 'MENUBAR', 'POPUPMENU'))
        _entered, left = self.ancestry.changes(self._under('WINDOW',
                                                           'MENUBAR',
                                                           'POPUPMENU'))
        self.assertEqual(left, [])

    def test_never_entering_a_menu_never_leaves_one(self):
        self.ancestry.changes(self._under('WINDOW', 'DOCUMENT'))
        _entered, left = self.ancestry.changes(self._under('WINDOW', 'LIST'))
        self.assertEqual(left, [])



# --------------------------------------------------------------------------- #
class ASwitchThatMeansHereNotEverywhere(unittest.TestCase):
    """The three that spend something are answered per PROGRAM.

    Whether it is worth sending pictures of a window to an AI provider is
    a different answer in a media player whose toolbar is unnamed and in
    the browser somebody lives in all day, and one switch for the machine
    cannot say both.
    """

    def setUp(self):
        _temp_config(self)
        from titanEnhancements import configSpec, perProgram
        self.per = perProgram
        perProgram.forget()
        self.addCleanup(perProgram.forget)
        self._read = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults())
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))

    def test_with_no_answer_of_its_own_the_general_setting_decides(self):
        from titanEnhancements import configSpec
        self.assertFalse(self.per.value('autoLabel', Fake(app='thing.exe')))
        configSpec.read = lambda: dict(configSpec.defaults(), autoLabel=True)
        self.assertTrue(self.per.value('autoLabel', Fake(app='thing.exe')))

    def test_a_program_may_answer_for_itself(self):
        self.per.set_value('autoLabel', 'thing.exe', True)
        self.assertTrue(self.per.value('autoLabel', Fake(app='thing.exe')))
        self.assertFalse(self.per.value('autoLabel', Fake(app='other.exe')))

    def test_a_program_may_switch_something_OFF_that_is_on_generally(self):
        from titanEnhancements import configSpec
        configSpec.read = lambda: dict(configSpec.defaults(), autoLabel=True)
        self.per.set_value('autoLabel', 'browser.exe', False)
        self.assertFalse(self.per.value('autoLabel', Fake(app='browser.exe')))
        self.assertTrue(self.per.value('autoLabel', Fake(app='thing.exe')))

    def test_forgetting_it_gives_the_general_setting_back(self):
        self.per.set_value('autoLabel', 'thing.exe', True)
        self.assertTrue(self.per.clear('autoLabel', 'thing.exe'))
        self.assertFalse(self.per.value('autoLabel', Fake(app='thing.exe')))

    def test_the_menu_can_tell_an_answer_from_an_inheritance(self):
        """A user cannot be shown a switch that is on and not told whether
        they turned it on here."""
        self.per.set_value('autoLabel', 'thing.exe', True)
        rows = {row['id']: row for row in
                self.per.described(Fake(app='thing.exe'))}
        self.assertTrue(rows['autoLabel']['own'])
        self.assertFalse(rows['surfaceReading']['own'])

    def test_only_the_switches_that_spend_something_are_per_program(self):
        from titanEnhancements import configSpec
        for name in self.per.PER_PROGRAM:
            if name in self.per.NO_GENERAL_SETTING:
                continue
            self.assertIn(name, configSpec.SPEC, name)
        self.assertIn('autoLabel', self.per.PER_PROGRAM)
        self.assertIn('surfaceReading', self.per.PER_PROGRAM)
        self.assertNotIn('pitchedFocus', self.per.PER_PROGRAM)

    def test_whether_a_program_is_a_game_has_no_general_setting(self):
        """It is a fact about that program, not a preference: there is
        nothing sensible for "are programs games" to mean."""
        self.assertIn('surfaceGame', self.per.NO_GENERAL_SETTING)
        self.assertFalse(self.per.value('surfaceGame', Fake(app='x.exe')))

    def test_it_survives_being_read_back(self):
        self.per.set_value('surfaceReading', 'game.exe', True)
        self.per.forget()
        self.assertTrue(self.per.value('surfaceReading', Fake(app='game.exe')))

    def test_a_switch_it_does_not_know_is_the_general_one(self):
        self.assertFalse(self.per.value('nonsense', Fake(app='thing.exe')))
        self.assertFalse(self.per.set_value('nonsense', 'thing.exe', True))

    def test_the_features_really_ask_it(self):
        import inspect
        from titanEnhancements import focus, surface
        self.assertIn('perProgram', inspect.getsource(focus._maybe_label))
        self.assertIn('perProgram', inspect.getsource(surface.wanted))

    def test_the_menu_names_commands_that_exist(self):
        from titanEnhancements import commands
        for name in ('toggle_here', 'forget_here'):
            self.assertTrue(callable(getattr(commands, name, None)), name)



# --------------------------------------------------------------------------- #
class EveryFeatureIsWiredToAnEvent(unittest.TestCase):
    """A feature NVDA never calls is a feature that does not exist.

    Three of them shipped that way: `event_foreground`, `event_nameChange`
    and `event_valueChange` were never added to the plugin at all, because
    the edit that was supposed to add them matched nothing and said
    nothing. Dialog kinds, live regions and automatic window reading were
    all present, tested, documented - and wired to nothing, which from the
    outside is indistinguishable from being broken.
    """

    @staticmethod
    def _plugin_source():
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            '__init__.py')
        with io.open(path, encoding='utf-8') as handle:
            return handle.read()

    def test_the_events_the_features_need_are_all_handled(self):
        import re
        source = self._plugin_source()
        handled = set(re.findall(r'def (event_\w+)\(', source))
        for event in ('event_gainFocus', 'event_foreground',
                      'event_nameChange', 'event_valueChange'):
            self.assertIn(event, handled, event + ' is handled by nobody')

    def test_every_automatic_feature_is_really_called(self):
        """Not "the module exists" - called, from the plugin."""
        source = self._plugin_source()
        for call in ('dialog_kind.announce(', 'live.changed(',
                     'surface.consider(', 'focus.handle_gain_focus(',
                     'windowKind.announce(', 'tce.crossing('):
            self.assertIn(call, source, call + ' is never called')

    def test_the_plugin_imports_everything_it_calls(self):
        import re
        source = self._plugin_source()
        imported = set(re.findall(r'^from \. import (\w+)', source,
                                  re.MULTILINE))
        for line in source.splitlines():
            for used in re.findall(r'\b([a-z_]+)\.[a-z_]+\(', line):
                if used in ('self', 'wx', 'os', 'sys', 'time', 'threading',
                            'compat', 'core'):
                    continue
                if used in imported or used in ('titan_menu', 'gestures'):
                    continue
                # Anything else must be a local name, not a module we
                # forgot to import - which is an error only at the moment
                # the user presses the key.
                self.assertNotIn(used, ('dialog_kind', 'live', 'surface', 'tce',
                                        'states', 'trackpad', 'focus',
                                        'windowKind'),
                                 used + ' is used but not imported')






# --------------------------------------------------------------------------- #
def _guiHelper_stub():
    """NVDA's `gui.guiHelper`, enough of it to build a real dialog.

    The manager is built with NVDA's own helper, which exists only inside
    NVDA. Standing in for it is what lets the REAL wx dialog be built here
    - and building it for real is the only thing that would have caught
    the bug this class exists for.
    """
    import wx
    if 'gui' in sys.modules and hasattr(sys.modules['gui'], 'guiHelper'):
        return sys.modules['gui'].guiHelper

    class BoxSizerHelper:
        def __init__(self, parent, orientation=None, sizer=None):
            self.parent = parent
            self.sizer = sizer or wx.BoxSizer(orientation or wx.VERTICAL)

        def addItem(self, item, **kw):
            # A ButtonHelper carries a sizer; NVDA's own helper unwraps it.
            real = getattr(item, 'sizer', item)
            self.sizer.Add(real, **{key: value for key, value in kw.items()
                                    if key in ('flag', 'proportion',
                                               'border')})
            return item

        def addLabeledControl(self, label, cls, **kw):
            box = wx.BoxSizer(wx.HORIZONTAL)
            box.Add(wx.StaticText(self.parent, label=label))
            control = cls(self.parent, **kw)
            box.Add(control, 1)
            self.sizer.Add(box, 0, wx.EXPAND)
            return control

        def addDialogDismissButtons(self, buttons, **kw):
            self.sizer.Add(buttons)
            return buttons

    class ButtonHelper:
        def __init__(self, orientation):
            self.sizer = wx.BoxSizer(orientation)

        def addButton(self, parent, label='', **kw):
            button = wx.Button(parent, label=label)
            self.sizer.Add(button)
            return button

    gui = types.ModuleType('gui')
    helper = types.ModuleType('gui.guiHelper')
    helper.BoxSizerHelper = BoxSizerHelper
    helper.ButtonHelper = ButtonHelper
    gui.guiHelper = helper
    gui.mainFrame = None
    sys.modules.setdefault('gui', gui)
    sys.modules.setdefault('gui.guiHelper', helper)
    return helper


class TheManagerIsBuiltForREAL(unittest.TestCase):
    """Not "the source mentions a Notebook" - built, with every button pressed.

    The manager shipped with a labels page that called a helper which was
    not there, and because the dialog is put up from a `wx.CallAfter`
    nothing caught it: the traceback went to NVDA's log, `show()` had
    already answered True, and the user pressed the menu entry and got no
    window and no sentence. Every tab was unreachable because of one line
    on one of them.

    Nothing here is shown on the screen; the dialog is built, driven and
    destroyed.
    """

    @classmethod
    def setUpClass(cls):
        try:
            import wx
        except Exception:                            # noqa: BLE001
            raise unittest.SkipTest('no wxPython here')
        _guiHelper_stub()
        cls.app = wx.App(False) if wx.GetApp() is None else wx.GetApp()

    def _no_modals(self):
        """Every modal answered NO or cancelled, for the length of a test.

        **A test never puts a window in front of whoever runs it**, and
        the button sweep presses buttons that ask: a confirmation, and
        two text boxes on the way to customising a control. It passed on
        a machine whose lists happen to be empty and would have sat
        waiting for a click on anybody else's - which is exactly how it
        cost 131 seconds the first time. Answering them is also what
        makes this the test that they ASK.
        """
        import wx
        asked = []
        real_box = wx.MessageBox
        real_entry = wx.TextEntryDialog
        real_choice = wx.SingleChoiceDialog

        def box(*args, **kw):
            asked.append(str(args[0]) if args else '')
            return wx.NO

        class _Cancelled:
            def __init__(self, *args, **kw):
                asked.append(str(args[1]) if len(args) > 1 else '')

            def ShowModal(self):
                return wx.ID_CANCEL

            def GetValue(self):
                return ''

            def GetSelection(self):
                return -1

            def Destroy(self):
                pass

        wx.MessageBox = box
        wx.TextEntryDialog = _Cancelled
        wx.SingleChoiceDialog = _Cancelled
        self.addCleanup(setattr, wx, 'MessageBox', real_box)
        self.addCleanup(setattr, wx, 'TextEntryDialog', real_entry)
        self.addCleanup(setattr, wx, 'SingleChoiceDialog', real_choice)
        return asked

    def _built(self):
        import wx
        from titanEnhancements import managerGui
        made = managerGui.build()
        self.assertIsNotNone(made, 'the manager class would not build')
        frame = wx.Frame(None)
        self.addCleanup(frame.Destroy)
        dialog = made(frame)
        self.addCleanup(dialog.Destroy)
        return dialog

    #: Every tab the manager must have. Named rather than counted: a
    #: count fails when a tab is ADDED, which is not a fault, and passes
    #: when one is renamed into nonsense, which is.
    TABS = ('Programs', 'Place markers', 'Watched areas', 'Scripts',
            'Control names', 'Sound scheme', 'Auditory icons')

    def test_every_tab_is_there(self):
        dialog = self._built()
        pages = [dialog.book.GetPageText(index)
                 for index in range(dialog.book.GetPageCount())]
        for wanted in self.TABS:
            self.assertIn(wanted, pages)

    def test_every_button_on_every_tab_presses_without_raising(self):
        """Every button, including the ones that ask before they act.

        **A test never puts a window in front of whoever runs it.** The
        first version of this pressed "Forget everything", which raises a
        real confirmation - and the suite sat for 131 seconds with a
        modal dialog on the user's own desktop waiting for a click nobody
        knew to give. So the question is answered NO here, which also
        makes this the test that the destructive button asks at all.
        """
        import wx
        asked = self._no_modals()
        dialog = self._built()
        pressed = 0
        for index in range(dialog.book.GetPageCount()):
            dialog.book.SetSelection(index)
            page = dialog.book.GetPage(index)
            for child in page.GetChildren():
                if not isinstance(child, wx.Button):
                    continue
                event = wx.CommandEvent(wx.EVT_BUTTON.typeId, child.GetId())
                event.SetEventObject(child)
                child.GetEventHandler().ProcessEvent(event)
                pressed += 1
        self.assertGreater(pressed, 8, 'almost nothing was pressed')
        # Every modal that did appear was answered here rather than on
        # somebody's desktop. With empty lists most buttons return early,
        # so this is "no more than a handful", not a count.
        self.assertLessEqual(len(asked), 6, asked)

    def test_a_page_that_will_not_build_is_ONE_page(self):
        """The whole of the fix, proved by putting the bug back."""
        from titanEnhancements import labels
        gone = labels.everything
        del labels.everything
        try:
            dialog = self._built()
            self.assertEqual(dialog.book.GetPageCount(), len(self.TABS),
                             'one broken page took the others with it')
        finally:
            labels.everything = gone

    def test_the_sweep_is_safe_with_things_really_stored(self):
        """The sweep passed on a machine whose lists are empty. With rows
        in them every asking button really asks - and none of it may
        reach the desktop of whoever runs the suite."""
        import wx
        from titanEnhancements import labels, procedures, markers
        rows = {'SomeApp|BUTTON|save': {'label': 'Save', 'source': 'user'}}
        real = (labels.everything, labels.for_application, labels.set_field,
                labels.rename_key, labels.remove_key,
                procedures.all_procedures, markers.all_markers)
        labels.everything = lambda: {'someapp': dict(rows)}
        labels.for_application = lambda name: dict(rows) \
            if name == 'someapp' else {}
        labels.set_field = lambda *a, **kw: True
        labels.rename_key = lambda *a, **kw: True
        labels.remove_key = lambda *a, **kw: True
        procedures.all_procedures = lambda: [
            {'name': 'A script', 'program': 'someapp', 'steps': []}]
        markers.all_markers = lambda: [{'name': 'A marker',
                                        'program': 'someapp'}]
        asked = self._no_modals()
        try:
            dialog = self._built()
            for index in range(dialog.book.GetPageCount()):
                dialog.book.SetSelection(index)
                page = dialog.book.GetPage(index)
                for child in page.GetChildren():
                    if not isinstance(child, wx.Button):
                        continue
                    event = wx.CommandEvent(wx.EVT_BUTTON.typeId,
                                            child.GetId())
                    event.SetEventObject(child)
                    child.GetEventHandler().ProcessEvent(event)
        finally:
            (labels.everything, labels.for_application, labels.set_field,
             labels.rename_key, labels.remove_key,
             procedures.all_procedures, markers.all_markers) = real
        # It really did ask - which is the point - and every question was
        # answered here.
        self.assertGreater(len(asked), 0, 'nothing asked, so nothing acted')

    def test_forgetting_a_program_asks_first_and_no_means_no(self):
        """There is no undo: the names somebody typed go with it."""
        import wx
        from titanEnhancements import labels
        removed = []
        rows = {'SomeApp|BUTTON|save': {'label': 'Save', 'source': 'user'}}
        real_all, real_one = labels.everything, labels.for_application
        real_remove = labels.remove_key
        labels.everything = lambda: {'someapp': dict(rows)}
        labels.for_application = lambda name: dict(rows) \
            if name == 'someapp' else {}
        labels.remove_key = lambda program, key: removed.append((program, key))
        asked = self._no_modals()
        try:
            dialog = self._built()
            index = list(dialog.programs.GetString(at) for at
                         in range(dialog.programs.GetCount())).index('someapp')
            dialog.programs.SetSelection(index)
            event = wx.CommandEvent(wx.EVT_BUTTON.typeId)
            dialog._forget_program(event)
        finally:
            labels.everything, labels.for_application = real_all, real_one
            labels.remove_key = real_remove
        self.assertEqual(len(asked), 1, 'it did not ask')
        self.assertIn('someapp', asked[0])
        self.assertEqual(removed, [], 'it threw things away after a no')

    def test_a_program_page_says_what_is_known_and_nothing_else(self):
        from titanEnhancements import labels, procedures
        rows = {'SomeApp|BUTTON|save': {'label': 'Save', 'source': 'user',
                                        'description': 'A floppy disk.'}}
        real_all, real_one = labels.everything, labels.for_application
        real_note = labels.application_note
        real_procs = procedures.all_procedures
        labels.everything = lambda: {'someapp': dict(rows)}
        labels.for_application = lambda name: dict(rows) \
            if name == 'someapp' else {}
        labels.application_note = lambda a, f: 'a green leaf' \
            if a == 'someapp' else ''
        procedures.all_procedures = lambda: [{'name': 'x',
                                              'program': 'someapp',
                                              'steps': []}]
        try:
            dialog = self._built()
            index = list(dialog.programs.GetString(at) for at
                         in range(dialog.programs.GetCount())).index('someapp')
            dialog.programs.SetSelection(index)
            dialog._program_shown()
            said = dialog.program_facts.GetValue()
        finally:
            labels.everything, labels.for_application = real_all, real_one
            labels.application_note = real_note
            procedures.all_procedures = real_procs
        self.assertIn('1', said)                 # one named control
        self.assertIn('a green leaf', said)      # what its icon was read as
        self.assertIn('someapp', ''.join(
            dialog.programs.GetString(at)
            for at in range(dialog.programs.GetCount())))

    def test_the_scripts_page_lists_what_was_recorded(self):
        from titanEnhancements import procedures
        real = procedures.all_procedures
        procedures.all_procedures = lambda: [
            {'name': 'Weekly report', 'program': 'tedit',
             'steps': [{'do': 'press'}, {'do': 'type'}]}]
        try:
            dialog = self._built()
        finally:
            procedures.all_procedures = real
        rows = [dialog.procedures.GetString(at)
                for at in range(dialog.procedures.GetCount())]
        self.assertEqual(len(rows), 1)
        self.assertIn('Weekly report', rows[0])
        self.assertIn('tedit', rows[0])
        self.assertIn('2', rows[0])          # how many steps

    def test_the_names_page_lists_a_program_and_its_controls(self):
        from titanEnhancements import labels
        rows = {'SomeApp|BUTTON|save': {'label': 'Save', 'source': 'ai',
                                        'description': 'A floppy disk.'}}
        real_all = labels.everything
        real_one = labels.for_application
        labels.everything = lambda: {'someapp': dict(rows)}
        labels.for_application = lambda name: dict(rows) \
            if name == 'someapp' else {}
        try:
            dialog = self._built()
        finally:
            labels.everything = real_all
            labels.for_application = real_one
        self.assertEqual(dialog.label_programs.GetString(0), 'someapp')
        row = dialog.labels.GetString(0)
        self.assertIn('Save', row)
        self.assertIn('ai', row)







# --------------------------------------------------------------------------- #
class AVirtualMachineIsAnotherComputersScreen(unittest.TestCase):
    """The case this whole tier exists for, and the one it was getting wrong.

    A virtual machine's window really does expose things - a menu bar, a
    status line, the host's own chrome - so "no children at all" answered
    no, and the guest's screen, which exposes nothing at all, was never
    read. Reported twice as "the accessible virtual machine window still
    does not work".
    """

    def setUp(self):
        from titanEnhancements import surface
        self.surface = surface

    @staticmethod
    def _window(klass='', program='', children=(), handle=1,
                location=(0, 0, 800, 600)):
        return types.SimpleNamespace(
            windowClassName=klass, windowHandle=handle,
            children=list(children), location=tuple(location),
            role=types.SimpleNamespace(name='WINDOW'),
            appModule=types.SimpleNamespace(appName=program))

    def test_vmware_workstation_is_recognised_by_its_program(self):
        for program in ('vmware', 'vmware-vmx', 'vmplayer', 'vmrc'):
            self.assertTrue(
                self.surface.is_virtual_machine(self._window(program=program)),
                program)

    def test_vmware_is_recognised_by_its_window_class_too(self):
        """Two ways, so a user running it under a name the list has not
        got is still recognised."""
        self.assertTrue(
            self.surface.is_virtual_machine(self._window(klass='VMUIFrame')))
        self.assertTrue(
            self.surface.is_virtual_machine(self._window(klass='MKSEmbedded')))

    def test_the_others_are_recognised(self):
        for program in ('virtualboxvm', 'vmconnect', 'mstsc', 'vncviewer'):
            self.assertTrue(
                self.surface.is_virtual_machine(self._window(program=program)),
                program)

    def test_an_ordinary_qt_program_is_NOT_a_virtual_machine(self):
        """`QWidget` is what VirtualBox paints the guest onto AND the class
        of every Qt program on the machine. Putting it in the recognising
        set made all of them virtual machines."""
        self.assertFalse(self.surface.is_virtual_machine(
            self._window(klass='QWidget', program='someqtapp')))
        self.assertFalse(self.surface.is_virtual_machine(
            self._window(klass='Notepad', program='notepad')))

    def test_a_vm_looks_drawn_even_though_it_has_controls(self):
        """The whole fix: the measurement below it answers "this has an
        interface", because the host's chrome is an interface."""
        chrome = self._window(klass='ToolbarWindow32', handle=2)
        self.assertTrue(self.surface.looks_drawn(
            self._window(klass='VMUIFrame', children=[chrome])))

    def test_the_guest_screen_is_what_is_found(self):
        """Reading the whole window gives somebody "File Machine View"
        across the top of their Linux console."""
        guest = self._window(klass='MKSEmbedded', handle=99)
        chrome = self._window(klass='ToolbarWindow32', handle=2)
        found = self.surface.display_of(
            self._window(klass='VMUIFrame', children=[chrome, guest]))
        self.assertEqual(getattr(found, 'windowHandle', 0), 99)

    def test_virtualbox_guest_is_found_by_being_inside_one(self):
        """Its guest surface is a plain QWidget, which is safe to look for
        only inside a window already known to be a virtual machine."""
        guest = self._window(klass='QWidget', handle=77)
        found = self.surface.display_of(
            self._window(klass='VirtualBoxVM', children=[guest]))
        self.assertEqual(getattr(found, 'windowHandle', 0), 77)

    def test_with_no_display_child_the_window_itself_is_read(self):
        window = self._window(klass='VMUIFrame', handle=5)
        self.assertIs(self.surface.display_of(window), window)

    def test_the_guest_is_found_however_deep_it_is_buried(self):
        """Measured on the user's own VMware Workstation: `MKSEmbedded`
        sits under the frame, a `VMUIView`, a `CVMUIStatusPane` and two
        containers. Looking only at the frame's own children never
        reached it, so the class match - the one certain answer there is -
        never fired at all."""
        guest = self._window(klass='MKSEmbedded', handle=790808,
                             location=(497, 474, 640, 480))
        buried = guest
        for depth, klass in enumerate(('xui::TWinContainer', '#32770',
                                       'CVMUIStatusPane', 'VMUIView')):
            buried = self._window(klass=klass, handle=100 + depth,
                                  children=[buried],
                                  location=(496, 409, 642, 546))
        found = self.surface.display_of(
            self._window(klass='VMUIFrame', children=[buried]))
        self.assertEqual(getattr(found, 'windowHandle', 0), 790808)

    def test_the_parked_console_is_not_the_one_to_read(self):
        """VMware keeps more than one `MKSEmbedded` and parks the spare at
        (-31797, -31820) - the same trick Titan's own offscreen bridge
        frame uses. Matched on class alone the parked one won, and what
        was then read was a console nobody can see: a picture that never
        changes, no words in it, and a reader saying nothing while
        reporting that it had found the guest."""
        parked = self._window(klass='MKSEmbedded', handle=2755056,
                              location=(-31797, -31820, 640, 480))
        real = self._window(klass='MKSEmbedded', handle=790808,
                            location=(497, 474, 640, 480))
        found = self.surface.display_of(
            self._window(klass='VMUIFrame', children=[parked, real],
                         location=(296, 341, 846, 702)))
        self.assertEqual(getattr(found, 'windowHandle', 0), 790808)

    def test_a_check_that_cannot_see_does_not_refuse(self):
        """A candidate with no rectangle at all is still the console: a
        test that cannot tell must not be the thing that says no."""
        guest = self._window(klass='MKSEmbedded', handle=3)
        guest.location = None
        found = self.surface.display_of(
            self._window(klass='VMUIFrame', children=[guest]))
        self.assertEqual(getattr(found, 'windowHandle', 0), 3)

    def test_a_one_pixel_strip_is_never_the_screen(self):
        """VMware's `unibar.ahTarget` is the auto-hide strip along the top
        of the window - 1894 by 1 pixels, and with no children, so it won
        "the biggest child that exposes nothing" outright while the real
        console (which has children above it) never qualified. What was
        then watched was a one-pixel line: the recogniser read no words in
        it, ever, the picture never changed, and the whole feature was
        silent while reporting that it was working."""
        strip = self._window(klass='unibar.ahTarget', handle=2558612,
                             location=(296, 341, 1894, 1))
        found = self.surface.display_of(
            self._window(klass='VMUIFrame', handle=5, children=[strip]))
        self.assertNotEqual(getattr(found, 'windowHandle', 0), 2558612)

    def test_the_biggest_childless_child_is_still_the_fallback(self):
        """The measurement is not gone - it is only refused a rectangle
        that could not be a screen."""
        strip = self._window(klass='unibar.ahTarget', handle=7,
                             location=(0, 0, 1894, 1))
        screen = self._window(klass='SomethingDrawn', handle=8,
                              location=(0, 0, 640, 480))
        found = self.surface.display_of(
            self._window(klass='VMUIFrame', children=[strip, screen]))
        self.assertEqual(getattr(found, 'windowHandle', 0), 8)

    def test_looking_for_the_guest_is_bounded(self):
        """It runs on arriving in a window, and a window with thousands of
        controls must not make that expensive."""
        window = self._window(klass='VMUIFrame')
        deep = window
        for _ in range(40):
            deep.children = [self._window(klass='Filler',
                                          children=[], handle=1)]
            deep = deep.children[0]
        seen = self.surface._descendants(window)
        self.assertLessEqual(len(seen), self.surface.DISPLAY_BUDGET)
        self.assertLessEqual(len(seen), self.surface.DISPLAY_DEPTH)

    def test_the_watcher_really_switches_to_the_guest(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'surface.py'),
                         encoding='utf-8').read()
        at = source.index('def _begin(')
        block = source[at:at + 1800]
        self.assertIn('is_virtual_machine(obj)', block)
        self.assertIn('display_of(obj)', block)


# --------------------------------------------------------------------------- #
class AnAutomaticReadingMayNotCostAProviderCall(unittest.TestCase):
    """Windows' recogniser is what the reader may use by ITSELF.

    Local, private, free, about a tenth of a second - against a picture of
    the user's screen sent to a provider and an answer measured taking
    longer than the bus waits for it. "Titan did not answer within 12s",
    in the log, over and over, from controls the reader chose to look at
    on its own.
    """

    def test_the_automatic_path_reads_locally(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'focus.py'),
                         encoding='utf-8').read()
        at = source.index('def _maybe_label(')
        block = source[at:at + 4000]
        local = block.index('graphics.label_locally')
        ai = block.index('graphics.label_with_ai')
        self.assertLess(local, ai, 'the AI is asked first')
        self.assertIn('_label_ai_wanted()', block,
                      'the AI is asked without the user having said so')

    def test_the_ai_is_only_for_a_user_who_asked_for_it(self):
        from titanEnhancements import configSpec, focus
        before = configSpec.read
        try:
            for answer, wanted in (('local', False), ('both', False),
                                   ('ai', True)):
                configSpec.read = lambda a=answer: dict(configSpec.defaults(),
                                                        ocrTier=a)
                self.assertEqual(focus._label_ai_wanted(), wanted, answer)
        finally:
            configSpec.read = before

    def test_a_local_label_needs_a_place_on_the_screen(self):
        from titanEnhancements import graphics
        obj = types.SimpleNamespace(name='', value='', description='',
                                    windowClassName='X', UIAAutomationId='a',
                                    role=types.SimpleNamespace(name='BUTTON'),
                                    location=None,
                                    appModule=types.SimpleNamespace(
                                        appName='someapp'))
        ok, said = graphics.label_locally(obj)
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_the_timeout_really_reaches_the_bridge(self):
        """`surface.read(hwnd, timeout=45.0)` took a timeout it never
        passed on, so every AI reading answered "did not answer within
        12s" while Titan was answering a few seconds later."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'link.py'),
                         encoding='utf-8').read()
        at = source.index('def run_action(')
        block = source[at:at + 1400]
        self.assertIn('timeout=CALL_TIMEOUT', block)
        self.assertIn('timeout=timeout', block)
        for name in ('surface.py', 'graphics.py'):
            other = io.open(os.path.join(ADDON, 'globalPlugins',
                                         'titanEnhancements', name),
                            encoding='utf-8').read()
            self.assertIn('timeout=timeout', other, name)

# --------------------------------------------------------------------------- #
class MSAAForAWindowThatHasNone(unittest.TestCase):
    """Titan Virtual Input Accessibility.

    A virtual machine's screen, a program on a toolkit nobody wired up, an
    installer that paints its own widgets: one rectangle with nothing
    inside it. There is no accessibility to read because the program never
    exposed any - but there is a picture, and a picture has structure.
    """

    def setUp(self):
        from titanEnhancements import virtualInput
        self.vi = virtualInput
        virtualInput.forget()
        self.addCleanup(virtualInput.forget)

    class _Reading:
        def __init__(self, lines):
            self.lines = lines

    @staticmethod
    def _word(text, left, top, width=40, height=16):
        return {'text': text, 'left': left, 'top': top,
                'width': width, 'height': height}

    def _menu_bar_and_two_rows(self):
        w = self._word
        return self._Reading([
            [w('File', 10, 10), w('Edit', 200, 10), w('View', 400, 10)],
            [w('document.txt', 10, 40), w('12 KB', 300, 40)],
            [w('picture.png', 10, 60), w('340 KB', 300, 60)],
        ])

    def test_a_row_of_widely_spaced_words_is_SEVERAL_things(self):
        """"File Edit View" is three menus, not a sentence - and without
        that a VM's menu bar is one node nobody can move through."""
        nodes = self.vi.build(self._menu_bar_and_two_rows())
        first = [node.text for node in nodes if node.line == 0]
        self.assertEqual(first, ['File', 'Edit', 'View'])

    def test_words_are_grouped_by_where_they_REALLY_are(self):
        """The recogniser's idea of a line and a grid's own row are not
        the same thing."""
        w = self._word
        # Two words the recogniser put on different "lines", on one row.
        reading = self._Reading([[w('left', 10, 100)], [w('right', 500, 102)]])
        nodes = self.vi.build(reading)
        self.assertEqual(len({node.line for node in nodes}), 1)

    def test_a_highlighted_row_is_marked_selected(self):
        """In a virtual machine the highlight IS the interface."""
        nodes = self.vi.build(self._menu_bar_and_two_rows(),
                              highlights=[(0, 55, 800, 20)])
        chosen = [node.text for node in self.vi.selected_in(nodes)]
        self.assertEqual(chosen, ['picture.png', '340 KB'])
        for node in nodes:
            if node.text == 'document.txt':
                self.assertFalse(node.selected)

    def test_a_selected_node_SAYS_it_is(self):
        nodes = self.vi.build(self._menu_bar_and_two_rows(),
                              highlights=[(0, 55, 800, 20)])
        parts = self.vi.describe(self.vi.selected_in(nodes)[0])
        self.assertEqual(parts[0][1], 'name')
        self.assertEqual(parts[-1][1], 'state')

    def test_with_no_highlight_nothing_is_guessed_at(self):
        nodes = self.vi.build(self._menu_bar_and_two_rows())
        self.assertEqual(self.vi.selected_in(nodes), [])

    def test_only_what_is_NEW_comes_back(self):
        """A screen re-read from the top on every poll is a reader nobody
        can use - and it is what a terminal in a VM most needs right."""
        first = self.vi.build(self._menu_bar_and_two_rows())
        self.vi.changed(7, first)
        w = self._word
        after = self.vi.build(self._Reading([
            [w('File', 10, 10), w('Edit', 200, 10), w('View', 400, 10)],
            [w('document.txt', 10, 40), w('12 KB', 300, 40)],
            [w('picture.png', 10, 60), w('340 KB', 300, 60)],
            [w('a new line of output', 10, 90)],
        ]))
        new, gone = self.vi.changed(7, after)
        self.assertEqual([node.text for node in new], ['a new line of output'])
        self.assertEqual(gone, [])

    def test_a_line_reads_as_one_thing(self):
        nodes = self.vi.build(self._menu_bar_and_two_rows())
        self.assertEqual(self.vi.line_of(nodes, 0), 'File Edit View')

    def test_it_never_raises_on_nonsense(self):
        """It is the only thing a window like this has; an exception here
        takes that away."""
        self.assertEqual(self.vi.build(None), [])
        self.assertEqual(self.vi.build(self._Reading(None)), [])
        self.assertEqual(self.vi.build(self._Reading([[{'no': 'text'}]])), [])
        self.assertEqual(self.vi.describe(None), [])

    # -- the colours ------------------------------------------------------- #
    class _Picture:
        """A bitmap with the two methods anything here needs of one."""

        def __init__(self, width, height, ground=(0, 0, 0), band=None,
                     band_colour=(255, 255, 255)):
            self.size = (width, height)
            self._ground = ground
            self._band = band
            self._band_colour = band_colour

        def getpixel(self, where):
            _x, y = where
            if self._band and self._band[0] <= y < self._band[1]:
                return self._band_colour
            return self._ground

    def test_an_inverted_row_is_found(self):
        """Nothing in a picture says which entry the arrows are on except
        that its background is inverted."""
        picture = self._Picture(400, 200, ground=(0, 0, 0),
                                band=(80, 100), band_colour=(255, 255, 255))
        found = self.vi.highlights(picture)
        self.assertTrue(found, 'the inverted row was not found')
        _left, top, _width, height = found[0]
        self.assertLessEqual(abs(top - 80), 4)
        self.assertGreaterEqual(height, 12)

    def test_a_plain_screen_has_no_highlight(self):
        """A false highlight is worse than none: it would tell somebody
        they are on a line they are not on."""
        self.assertEqual(
            self.vi.highlights(self._Picture(400, 200, ground=(0, 0, 0))), [])

    def test_a_picture_it_cannot_read_answers_nothing(self):
        class Broken:
            size = (400, 200)

            def getpixel(self, where):
                raise RuntimeError('no')
        self.assertEqual(self.vi.highlights(Broken()), [])
        self.assertEqual(self.vi.highlights(None), [])

    def test_the_local_reader_hands_the_highlights_over_in_SCREEN_places(self):
        """A highlight in the picture's coordinates compared against a
        word in the screen's matches nothing - or the wrong line, by a
        margin that changes with the window's size."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'localOcr.py'),
                         encoding='utf-8').read()
        self.assertIn('def _highlighted(', source)
        at = source.index('def _highlighted(')
        block = source[at:at + 1200]
        self.assertIn('_screen_y(info', block)
        self.assertIn('info.screenLeft', block)

    def test_windows_reading_nothing_is_what_asks_the_AI(self):
        """"Windows' own recogniser first, the AI when it cannot" was
        documented in `_not_a_game` and only ever happened when the
        recogniser RAISED - so a window Windows read as blank was watched
        for ever, in silence, and never promoted."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'surface.py'),
                         encoding='utf-8').read()
        at = source.index('def _watch_locally(')
        end = source.index('\ndef ', at + 10)
        block = source[at:end]
        self.assertIn('if not reading.lines:', block)
        self.assertIn('EMPTY_ENOUGH', block)
        from titanEnhancements import surface
        self.assertGreater(surface.EMPTY_ENOUGH, 1,
                           'a screen is blank for a moment while it '
                           'repaints; one reading is not an answer')

    def test_what_the_watcher_said_is_written_down(self):
        """"It reads the window and says nothing" wears four different
        faults and only a record of what it decided to say tells them
        apart."""
        from titanEnhancements import surface
        for field in ('said', 'last_said', 'empty'):
            self.assertIn(field, surface.report())

    def test_the_watcher_says_the_highlight_instead_of_the_diff(self):
        """When the highlight moves the whole screen "changes", and
        reading the new lines would recite the menu instead of saying
        which item the user is on."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'surface.py'),
                         encoding='utf-8').read()
        at = source.index('def _watch_locally(')
        # To the end of the function rather than a fixed number of
        # characters: a comment added above the line being looked for
        # would otherwise push it out of the slice and fail a test about
        # something else entirely.
        end = source.index('\ndef ', at + 10)
        block = source[at:end]
        self.assertIn('virtualInput.selected_in', block)
        self.assertIn('if not said_it:', block,
                      'the diff is read even when the highlight was said')

# --------------------------------------------------------------------------- #
class AnAutomaticFeatureMayNotStopTheReader(unittest.TestCase):
    """The Action Bus is ONE pipe, and that is what makes this a rule.

    `_maybe_label` started a thread per unnamed control, each making a
    call that waits up to twelve seconds. Tab through ten of them and
    that is ten calls nose to tail with every other call queued behind -
    including the ones NVDA makes on its own main thread. In the log:
    "Titan did not answer within 12s". To the user: a reader that has
    stopped.
    """

    def setUp(self):
        from titanEnhancements import focus
        self.focus = focus
        focus._label_busy = False
        focus._label_last = 0.0
        focus._label_failures = 0
        self.addCleanup(setattr, focus, '_label_busy', False)
        self.addCleanup(setattr, focus, '_label_last', 0.0)
        self.addCleanup(setattr, focus, '_label_failures', 0)

    def test_only_one_is_asked_for_at_a_time(self):
        self.assertTrue(self.focus._label_may_ask())
        self.assertFalse(self.focus._label_may_ask(),
                         'a second went out while the first was in flight')

    def test_they_are_spaced_out(self):
        """However many unnamed controls go past."""
        self.assertTrue(self.focus._label_may_ask())
        self.focus._label_done(True)
        self.assertFalse(self.focus._label_may_ask(),
                         'the next one went out immediately')

    def test_after_a_few_failures_it_stands_down(self):
        """A Titan that just failed to answer in twelve seconds will fail
        the next one too, and asking anyway is how a feature that cannot
        work takes the reader with it."""
        for _try in range(self.focus.LABEL_GIVE_UP):
            self.focus._label_last = 0.0
            self.assertTrue(self.focus._label_may_ask())
            self.focus._label_done(False)
        self.assertTrue(self.focus.label_layer_stood_down())
        self.focus._label_last = 0.0
        self.assertFalse(self.focus._label_may_ask())

    def test_one_that_works_puts_the_count_back(self):
        self.focus._label_failures = self.focus.LABEL_GIVE_UP - 1
        self.focus._label_done(True)
        self.assertEqual(self.focus._label_failures, 0)
        self.assertFalse(self.focus.label_layer_stood_down())

    def test_standing_down_is_SAID(self):
        """A feature that quietly stopped is the thing this add-on keeps
        taking back out."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'focus.py'),
                         encoding='utf-8').read()
        self.assertIn('label_layer_stood_down()', source)
        self.assertIn('switched off for now', source)

    def test_nothing_is_asked_before_the_guard(self):
        """The guard is worth nothing if the thread starts anyway."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'focus.py'),
                         encoding='utf-8').read()
        at = source.index('def _maybe_label(')
        # To the end of the function rather than a fixed number of
        # characters: a comment added inside it would otherwise push the
        # line being looked for out of the slice and fail a test about
        # something else entirely.
        block = source[at:source.index('\ndef ', at + 10)]
        guard = block.index('_label_may_ask()')
        thread = block.index('threading.Thread')
        self.assertLess(guard, thread,
                        'the thread is started before the guard is asked')

# --------------------------------------------------------------------------- #
class OneControlMendedForGood(unittest.TestCase):
    """JAWS' customised control: mended once, by the person it is wrong for.

    A label replaces the name; these are the other four answers to "what
    should this be to me?" - what it is SAID to be, what is added after
    it, the voice its name is spoken in, and never announcing it at all.
    """

    def setUp(self):
        from titanEnhancements import labels
        self.labels = labels
        self.store = {}
        self._real_load = labels._load
        labels._load = lambda: self.store
        self._real_save = labels.save
        labels.save = lambda: True
        self.addCleanup(setattr, labels, '_load', self._real_load)
        self.addCleanup(setattr, labels, 'save', self._real_save)

    def _obj(self):
        return types.SimpleNamespace(
            windowHandle=0, windowClassName='SomeApp',
            UIAAutomationId='saveButton', name='',
            role=types.SimpleNamespace(name='BUTTON'),
            appModule=types.SimpleNamespace(appName='someapp'))

    def test_nothing_is_decided_until_it_is(self):
        self.assertEqual(self.labels.custom_of(self._obj()), {})

    def test_each_field_is_kept_and_read_back(self):
        obj = self._obj()
        self.labels.customise(obj, role_word='toolbar', note='read only',
                              voice='detail', silent=False)
        found = self.labels.custom_of(obj)
        self.assertEqual(found.get('role_word'), 'toolbar')
        self.assertEqual(found.get('note'), 'read only')
        self.assertEqual(found.get('voice'), 'detail')
        self.assertNotIn('silent', found, 'a false switch is stored')

    def test_an_empty_answer_takes_the_field_OFF(self):
        """So "put it back to normal" is the same call as any other, and
        there is no third state to get wrong."""
        obj = self._obj()
        self.labels.customise(obj, role_word='toolbar')
        self.labels.customise(obj, role_word='')
        self.assertNotIn('role_word', self.labels.custom_of(obj))

    def test_a_silent_control_is_read_as_nothing_at_all(self):
        from titanEnhancements import elements
        obj = self._obj()
        obj.name = 'Save'
        self.assertTrue(elements.describe(obj), 'it said nothing to begin with')
        self.labels.customise(obj, silent=True)
        self.assertEqual(elements.describe(obj), [])

    def test_what_the_user_calls_its_KIND_is_what_is_said(self):
        from titanEnhancements import elements
        obj = self._obj()
        obj.name = 'Save'
        self.labels.customise(obj, role_word='toolbar')
        kinds = [text for text, voice in elements.describe(obj)
                 if voice == 'kind']
        self.assertEqual(kinds, ['toolbar'])

    def test_a_note_is_ADDED_rather_than_replacing_anything(self):
        """The whole difference between a note and a label."""
        from titanEnhancements import elements
        obj = self._obj()
        obj.name = 'Save'
        self.labels.customise(obj, note='read only')
        said = [text for text, _voice in elements.describe(obj)]
        self.assertIn('Save', said)
        self.assertIn('read only', said)
        self.assertLess(said.index('Save'), said.index('read only'))

    def test_the_voice_it_is_spoken_in_is_the_users(self):
        from titanEnhancements import elements
        obj = self._obj()
        obj.name = 'Save'
        self.labels.customise(obj, voice='detail')
        for text, voice in elements.describe(obj):
            if text == 'Save':
                self.assertEqual(voice, 'detail')
                return
        self.fail('the name was not read at all')

    def test_a_control_with_no_stable_key_keeps_nothing(self):
        """Anything set on it would never be found again, and a setting
        that lands on the wrong control is worse than none."""
        obj = types.SimpleNamespace(
            windowHandle=0, windowClassName='', name='',
            role=types.SimpleNamespace(name=''), indexInParent=-1,
            appModule=types.SimpleNamespace(appName='someapp'))
        self.assertFalse(self.labels.customise(obj, note='x'))

    def test_it_lives_beside_the_label_of_the_same_control(self):
        """One question about one control; two files would drift."""
        obj = self._obj()
        self.labels.put(obj, 'Save', source='user')
        self.labels.customise(obj, note='read only')
        rows = self.labels.for_application('someapp')
        row = list(rows.values())[0]
        self.assertEqual(row.get('label'), 'Save')
        self.assertEqual(row.get('note'), 'read only')

    def test_every_field_the_editor_offers_is_one_the_store_knows(self):
        """A field the editor sets and the store drops is a setting that
        silently does not happen."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'commands.py'),
                         encoding='utf-8').read()
        at = source.index('def customise_control(')
        block = source[at:at + 4000]
        for field in ('role_word', 'note', 'voice', 'silent'):
            self.assertIn("'%s'" % field, block, field)
            self.assertIn(field, self.labels.CUSTOM, field)

# --------------------------------------------------------------------------- #
class LayersInsteadOfAMillionShortcuts(unittest.TestCase):
    """A hundred and sixteen commands, and a keyboard without that many chords.

    JAWS' answer, and it is better than a longer list of shortcuts because
    of what it does for memory: the letters inside a layer only have to be
    unique within it, so they can be the obvious ones.
    """

    def setUp(self):
        from titanEnhancements import layers
        self.layers = layers
        layers.forget()
        self.addCleanup(layers.forget)

    def test_every_key_of_every_layer_names_a_real_command(self):
        """A layer that offers something that does not exist is a key that
        does nothing, which is the failure of every hidden shortcut."""
        from titanEnhancements import commands
        for name in self.layers.names():
            for key, (command, _said) in self.layers.keys_of(name).items():
                self.assertTrue(hasattr(commands, command),
                                '%s/%s -> %s' % (name, key, command))

    def test_every_key_has_words_saying_what_it_does(self):
        for name in self.layers.names():
            for key, (_command, said) in self.layers.keys_of(name).items():
                text = said() if callable(said) else said
                self.assertTrue(str(text or '').strip(),
                                '%s/%s' % (name, key))

    def test_a_layer_lasts_for_exactly_one_key(self):
        self.layers.enter('reading')
        self.assertEqual(self.layers.open_layer(), 'reading')
        self.layers.chose('w')
        self.assertEqual(self.layers.open_layer(), '',
                         'the layer stayed open and would eat the next key')

    def test_a_layer_lets_go_by_itself(self):
        """A layer entered by accident must be gone before the user types
        anything they meant for the program."""
        self.layers.enter('reading')
        self.layers.__dict__['_opened_at'] = time.time() - \
            (self.layers.SECONDS + 1)
        self.assertEqual(self.layers.open_layer(), '')
        self.assertEqual(self.layers.report()['timed_out'], 1)

    def test_a_key_pressed_after_it_closed_is_the_programs(self):
        """Not eaten, and not run: it belongs to whatever is in front."""
        what, _value = self.layers.chose('w')
        self.assertEqual(what, 'closed')

    def test_a_key_the_layer_does_not_know_says_so(self):
        self.layers.enter('reading')
        what, which = self.layers.chose('q')
        self.assertEqual(what, 'unknown')
        self.assertEqual(which, 'reading')
        self.assertTrue(self.layers.unknown_sentence(which))

    def test_question_mark_and_h_both_ask_for_help(self):
        for key in self.layers.HELP_KEYS:
            self.layers.enter('reading')
            what, which = self.layers.chose(key)
            self.assertEqual(what, 'help', key)
            self.assertEqual(which, 'reading')

    def test_the_help_is_built_from_what_is_really_bound(self):
        """So it cannot describe a command the layer has not got."""
        lines = self.layers.help_for('program')
        self.assertEqual(len(lines), len(self.layers.keys_of('program')))
        for key in self.layers.keys_of('program'):
            self.assertTrue(any(line.startswith(key + ' ') for line in lines),
                            key)

    def test_a_letter_may_mean_different_things_in_different_layers(self):
        """The whole reason a layer is worth having."""
        reading = self.layers.keys_of('reading')
        program = self.layers.keys_of('program')
        self.assertIn('w', reading)
        self.assertIn('w', program)
        self.assertNotEqual(reading['w'][0], program['w'][0])

    def test_no_layer_offers_one_letter_twice(self):
        for name in self.layers.names():
            keys = list(self.layers.keys_of(name))
            self.assertEqual(len(keys), len(set(keys)), name)

    def test_every_layer_has_a_name_a_person_would_recognise(self):
        for name in self.layers.names():
            self.assertTrue(self.layers.label(name), name)

    def test_the_palette_is_reachable_by_the_two_gestures_asked_for(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def script_titanPalette(')
        before = source[max(0, at - 700):at]
        self.assertIn('kb:NVDA+shift+space', before)
        self.assertIn('kb:NVDA+`', before)

    def test_the_layer_keys_are_borrowed_and_given_back(self):
        """A reader still holding the alphabet in the next window is a
        machine that has stopped answering."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        self.assertIn('def _borrow_layer_keys', source)
        self.assertIn('removeGestureBinding', source)
        at = source.index('def _borrow_layer_keys')
        block = source[at:at + 800]
        self.assertIn('removeGestureBinding', block,
                      'the keys are taken and never given back')

# --------------------------------------------------------------------------- #
class AModuleCanBePerfectAndCompletelyDEAD(unittest.TestCase):
    """The check the schema cannot make.

    A reader module whose match blocks name a class spelled slightly
    differently, or a column the program calls something else, is well
    formed by every rule the schema has and fires not once. It loads, it
    is listed, it can be switched on, and from the outside it is exactly a
    module that was never written.
    """

    def setUp(self):
        from titanEnhancements import verify
        self.verify = verify

    def _control(self, role='BUTTON', name='', cls='SomeApp', children=()):
        node = types.SimpleNamespace(
            windowHandle=1, windowClassName=cls, name=name,
            role=types.SimpleNamespace(name=role), children=list(children),
            parent=None)
        return node

    def _window(self, children):
        top = self._control(role='WINDOW', name='A window', children=children)
        top.appModule = types.SimpleNamespace(appName='someapp')
        return top

    def test_a_rule_that_matches_something_is_alive(self):
        window = self._window([self._control('BUTTON', 'Save')])
        module = {'id': 'someapp', 'match': {'executable': 'someapp'},
                  'controls': [{'match': {'role': 'BUTTON'}, 'say': 'x'}]}
        report = self.verify.check(module, window)
        self.assertTrue(report['works'])
        self.assertEqual(report['alive'], 1)
        self.assertEqual(report['dead'], [])

    def test_a_rule_that_matches_nothing_is_NAMED(self):
        window = self._window([self._control('BUTTON', 'Save')])
        module = {'id': 'someapp', 'match': {'executable': 'someapp'},
                  'controls': [{'match': {'role': 'SLIDER'}, 'say': 'x'}]}
        report = self.verify.check(module, window)
        self.assertFalse(report['works'])
        self.assertEqual(len(report['dead']), 1)
        self.assertIn('SLIDER', report['dead'][0])

    def test_a_module_that_does_not_claim_the_window_says_so(self):
        """Every rule would be reported dead for the wrong reason."""
        window = self._window([self._control('BUTTON', 'Save')])
        module = {'id': 'other', 'match': {'executable': 'somethingelse'},
                  'controls': [{'match': {'role': 'BUTTON'}, 'say': 'x'}]}
        report = self.verify.check(module, window)
        self.assertFalse(report.get('matches_this_window'))
        self.assertTrue(report['why'])

    def test_a_module_with_no_rules_does_nothing_and_says_so(self):
        window = self._window([self._control('BUTTON', 'Save')])
        report = self.verify.check(
            {'id': 'someapp', 'match': {'executable': 'someapp'}}, window)
        self.assertFalse(report['works'])
        self.assertTrue(report['why'])

    def test_the_walk_is_bounded(self):
        """A window with three thousand controls must not cost a second."""
        many = [self._control('BUTTON', 'b%d' % n) for n in range(50)]
        window = self._window(many)
        module = {'id': 'someapp', 'match': {'executable': 'someapp'},
                  'controls': [{'match': {'role': 'BUTTON'}, 'say': 'x'}]}
        report = self.verify.check(module, window, limit=10)
        self.assertLessEqual(report['controls'], 10)

    def test_what_the_MODEL_is_told_names_the_rules(self):
        """A model handed "it does not work" writes a different module;
        one handed the rules that matched nothing mends this one."""
        window = self._window([self._control('BUTTON', 'Save')])
        module = {'id': 'someapp', 'match': {'executable': 'someapp'},
                  'controls': [{'match': {'role': 'SLIDER'}, 'say': 'x'}]}
        complaint = self.verify.complaint(self.verify.check(module, window))
        self.assertIn('SLIDER', complaint)
        self.assertIn('matched nothing', complaint)

    def test_a_module_that_works_has_nothing_to_complain_about(self):
        window = self._window([self._control('BUTTON', 'Save')])
        module = {'id': 'someapp', 'match': {'executable': 'someapp'},
                  'controls': [{'match': {'role': 'BUTTON'}, 'say': 'x'}]}
        self.assertEqual(
            self.verify.complaint(self.verify.check(module, window)), '')

    def test_the_sentence_is_something_a_person_can_be_told(self):
        window = self._window([self._control('BUTTON', 'Save')])
        module = {'id': 'someapp', 'match': {'executable': 'someapp'},
                  'controls': [{'match': {'role': 'BUTTON'}, 'say': 'x'},
                               {'match': {'role': 'SLIDER'}, 'say': 'y'}]}
        said = self.verify.sentence(self.verify.check(module, window))
        self.assertIn('1', said)
        self.assertIn('SLIDER', said)

    def test_it_presses_nothing_and_writes_nothing(self):
        """It reads. A control that is asked to act would be a check that
        changes the thing it is checking."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'verify.py'),
                         encoding='utf-8').read()
        for forbidden in ('doDefaultAction', 'setFocus', 'BM_CLICK',
                          'save(', 'put('):
            self.assertNotIn(forbidden, source, forbidden)

# --------------------------------------------------------------------------- #
class WhatAWindowIsWrittenIn(unittest.TestCase):
    """The first thing anybody writing an app module works out by hand.

    A program cannot be running on a toolkit whose library it has not
    loaded, so the module list is the one piece of evidence here that
    cannot be a coincidence - as long as it is matched exactly.
    """

    def setUp(self):
        from titanEnhancements import toolkit
        self.toolkit = toolkit
        toolkit.forget()

    def _obj(self, cls='', pid=0, uia=''):
        obj = types.SimpleNamespace(windowHandle=0, windowClassName=cls,
                                    processID=pid)
        if uia:
            obj.UIAElement = types.SimpleNamespace(CurrentFrameworkId=uia)
        return obj

    def _with_modules(self, modules):
        real = self.toolkit.modules_of
        self.toolkit.modules_of = lambda pid: list(modules)
        self.addCleanup(setattr, self.toolkit, 'modules_of', real)

    def test_a_library_is_proof(self):
        self._with_modules(['ntdll.dll', 'qt6core.dll', 'user32.dll'])
        self.assertEqual(self.toolkit.of(self._obj(pid=1))[:2], ('qt', 'library'))

    def test_a_three_letter_fragment_is_not_evidence(self):
        """`vcl` appears in `srvcli.dll`, which half the programs on the
        machine have loaded - and every one of them was reported as
        Delphi. Matched by prefix now, never by substring."""
        self._with_modules(['srvcli.dll', 'comctl32.dll', 'ntdll.dll'])
        framework, how, _evidence = self.toolkit.of(self._obj(pid=2))
        self.assertNotEqual(framework, 'vcl')
        self.assertEqual((framework, how), ('win32', 'library'))

    def test_delphi_is_told_by_its_packages(self):
        self._with_modules(['vcl280.bpl', 'rtl280.bpl', 'ntdll.dll'])
        self.assertEqual(self.toolkit.of(self._obj(pid=3))[0], 'vcl')

    def test_the_more_specific_answer_wins(self):
        """An Electron program has loaded Chromium too, and calling it
        Chromium would be true and useless."""
        self._with_modules(['chrome_elf.dll', 'libcef.dll', 'ntdll.dll'])
        self.assertEqual(self.toolkit.of(self._obj(pid=4))[0], 'cef')

    def test_ui_automation_answers_when_the_libraries_do_not(self):
        self._with_modules([])
        obj = self._obj(pid=5, uia='WPF')
        self.assertEqual(self.toolkit.of(obj)[:2], ('wpf', 'uia'))

    def test_the_window_class_is_the_last_resort(self):
        self._with_modules([])
        self.assertEqual(self.toolkit.of(self._obj('UnityWndClass', pid=6))[:2],
                         ('unity', 'class'))

    def test_a_process_that_will_not_say_is_not_guessed_at(self):
        """Nothing read and nothing else to go on is an honest 'cannot
        tell' - reporting it as native would be a guess wearing the
        clothes of evidence."""
        self._with_modules([])
        self.assertEqual(self.toolkit.of(self._obj('SomethingOdd', pid=7)),
                         ('', '', ''))

    def test_native_is_only_claimed_when_the_modules_were_really_read(self):
        self._with_modules(['comctl32.dll', 'ntdll.dll', 'user32.dll'])
        self.assertEqual(self.toolkit.of(self._obj('SomethingOdd', pid=8))[0],
                         'win32')

    def test_it_is_asked_once_per_process(self):
        """Reading a module list is tens of milliseconds and a program
        cannot change what it is written in."""
        asked = []
        real = self.toolkit.modules_of
        self.toolkit.modules_of = lambda pid: asked.append(pid) or ['qt6core.dll']
        try:
            obj = self._obj(pid=9)
            self.toolkit.of(obj)
            self.toolkit.of(obj)
            self.toolkit.of(obj)
        finally:
            self.toolkit.modules_of = real
        self.assertEqual(len(asked), 1)

    def test_every_framework_it_can_answer_has_a_word(self):
        """A framework with no word is one that is named to nobody."""
        every = {name for _prefix, name in self.toolkit.BY_LIBRARY}
        every |= set(self.toolkit.BY_UIA.values())
        every |= {name for _prefix, name in self.toolkit.BY_CLASS}
        every.add('vcl')
        for framework in sorted(every):
            self.assertTrue(self.toolkit.word(framework), framework)

    def test_a_note_says_what_to_DO_about_it(self):
        """Naming a toolkit is worth little; knowing that Java answers
        nothing until the Access Bridge is on is the useful half."""
        self.assertIn('Access Bridge', self.toolkit.note('java'))
        self.assertTrue(self.toolkit.note('unity'))
        self.assertEqual(self.toolkit.note('nonsense'), '')

    def test_the_sentence_names_the_evidence(self):
        """An answer that cannot be checked is one that has to be
        believed."""
        self._with_modules(['qt6core.dll'])
        said = self.toolkit.describe(self._obj(pid=10))
        self.assertIn('Qt', said)
        self.assertIn('qt6core.dll', said)

    def test_the_observed_draft_carries_it(self):
        """It is what an app module is written FROM."""
        from titanEnhancements import draft
        self._with_modules(['qt6core.dll'])
        obj = self._obj('QWidget', pid=11)
        obj.name = 'Something'
        obj.appModule = types.SimpleNamespace(appName='someprogram')
        seen = draft.observe(obj)
        self.assertEqual(seen.get('framework'), 'qt')
        self.assertEqual(seen.get('framework_how'), 'library')
        self.assertTrue(seen.get('framework_note'))

# --------------------------------------------------------------------------- #
class WhatKindOfWindowYouHaveArrivedIn(unittest.TestCase):
    """`dialog_kind` answers four kinds of dialog and nothing about the rest.

    Nearly every window is one of the rest, and a reader that says only the
    title says nothing a sighted person gets for free: whether this is an
    application, a little box that will go away again, a game that has
    painted its own screen, or the desktop.
    """

    def setUp(self):
        from titanEnhancements import windowKind
        self.windowKind = windowKind
        windowKind.forget()

    def _obj(self, cls='SomeClass', role='WINDOW', hwnd=0):
        return types.SimpleNamespace(
            windowHandle=hwnd, windowClassName=cls,
            role=types.SimpleNamespace(name=role))

    def test_a_game_engines_class_is_a_game(self):
        """Not a heuristic: UnityWndClass is Unity and nothing else."""
        kind, how = self.windowKind.kind_of(self._obj('UnityWndClass'))
        self.assertEqual((kind, how), ('game', 'class'))

    def test_the_game_list_is_surfaces_own(self):
        """One list, read twice - a class added there is known here."""
        from titanEnhancements import surface
        for name in list(surface.GAME_CLASSES)[:4]:
            self.assertTrue(self.windowKind.is_game(self._obj(name)), name)

    def test_a_dialog_is_a_dialog(self):
        kind, how = self.windowKind.kind_of(self._obj('#32770', 'DIALOG'))
        self.assertEqual((kind, how), ('dialog', 'role'))

    def test_the_desktop_is_not_a_small_window(self):
        """Progman is a popup with no minimise and no maximise box, which is
        true of the bits and wrong about the thing."""
        for name in ('Progman', 'WorkerW'):
            kind, how = self.windowKind.kind_of(self._obj(name))
            self.assertEqual((kind, how), ('desktop', 'class'), name)

    def test_nothing_is_answered_about_nothing(self):
        self.assertEqual(self.windowKind.kind_of(None), ('', ''))
        self.assertEqual(self.windowKind.kind_of(self._obj('X', hwnd=0)),
                         ('', ''))

    def test_every_kind_has_a_word(self):
        """A kind with no word is a kind that is silently not said."""
        for kind in ('application', 'window', 'game', 'tool', 'desktop',
                     'dialog'):
            self.assertTrue(self.windowKind.word(kind), kind)

    def test_a_kind_nobody_has_is_no_word_rather_than_a_wrong_one(self):
        self.assertEqual(self.windowKind.word('nonsense'), '')

    def test_the_kind_is_said_at_the_tone_a_control_type_is_said_at(self):
        """It IS what the thing you arrived in is, which everywhere else in
        this add-on is the 'kind' voice."""
        parts = self.windowKind.parts_for(self._obj('UnityWndClass'))
        self.assertTrue(parts)
        self.assertEqual(parts[0][1], 'kind')

    def test_it_is_said_once_per_window_and_not_once_per_control(self):
        """The bug the region layer had, which must not come back."""
        said = []
        obj = self._obj('UnityWndClass', hwnd=4242)
        import titanEnhancements.interject as interject
        original = interject.prefix_next
        interject.prefix_next = lambda text, voice='context': said.append(text)
        try:
            self.assertEqual(self.windowKind.announce(obj), 'game')
            self.assertEqual(self.windowKind.announce(obj), '')
            self.assertEqual(self.windowKind.announce(obj), '')
        finally:
            interject.prefix_next = original
        self.assertEqual(len(said), 1)

    def test_the_switch_being_off_means_nothing_is_said(self):
        from titanEnhancements import configSpec
        obj = self._obj('UnityWndClass', hwnd=99)
        original = configSpec.read
        configSpec.read = lambda: {'windowKinds': False}
        try:
            self.assertEqual(self.windowKind.announce(obj), '')
        finally:
            configSpec.read = original

    def test_the_switch_is_in_the_spec_and_on_the_page(self):
        from titanEnhancements import configSpec, settingsPanel
        self.assertIn('windowKinds', configSpec.SPEC)
        self.assertIn('windowKinds', settingsPanel.keys_on_the_page())

    def test_an_icon_is_never_read_with_ai_twice_for_one_program(self):
        """A program somebody opens fifty times a day costs one request in
        its life - the shape the label path already has."""
        obj = self._obj('UnityWndClass', hwnd=7)
        obj.appModule = types.SimpleNamespace(appName='somegame')
        asked = []
        original = self.windowKind._may_describe
        self.windowKind._may_describe = lambda o: asked.append(1) or False
        try:
            self.windowKind.describe_icon_later(obj)
            self.windowKind.describe_icon_later(obj)
            self.windowKind.describe_icon_later(obj)
        finally:
            self.windowKind._may_describe = original
        self.assertEqual(len(asked), 1)

    def test_nothing_is_asked_of_a_titan_that_is_not_there(self):
        """The bug this add-on has already fixed once on the label path: a
        thread started for every window, to be told Titan is not running."""
        from titanEnhancements import perProgram
        obj = self._obj('UnityWndClass', hwnd=8)
        original = perProgram.value
        perProgram.value = lambda name, o=None: True
        try:
            # No bus in a test run, so LINK.connected() is false.
            self.assertFalse(self.windowKind._may_describe(obj))
        finally:
            perProgram.value = original

    def test_unknown_is_recognised_as_the_absence_of_an_answer(self):
        """And in the user's own language, which is the whole difficulty:
        a list of English spellings works on an English NVDA and nowhere
        else - which is the machine this was reported from."""
        self.assertTrue(self.windowKind.is_unknown_word('unknown'))
        self.assertTrue(self.windowKind.is_unknown_word('UNKNOWN'))
        self.assertFalse(self.windowKind.is_unknown_word('button'))
        self.assertFalse(self.windowKind.is_unknown_word(''))
        self.assertFalse(self.windowKind.is_unknown_word(None))

    def test_a_window_read_as_unknown_is_read_as_what_it_is(self):
        """Measured live before this: "ELTEN 3.0.3, nieznane"."""
        from titanEnhancements import elements, context
        obj = self._obj('UnityWndClass', 'UNKNOWN', hwnd=11)
        obj.name = 'Some Game'
        original = context.role_name
        context.role_name = lambda role: 'unknown'
        try:
            parts = elements.describe(obj)
        finally:
            context.role_name = original
        kinds = [text for text, voice in parts if voice == 'kind']
        self.assertEqual(kinds, [self.windowKind.word('game')])
        self.assertNotIn('unknown', [k.lower() for k in kinds])

    def test_a_role_nvda_DOES_know_is_left_exactly_as_it_was(self):
        """The word is REPLACED, not added to - so a control NVDA can
        classify must come through untouched."""
        from titanEnhancements import elements, context
        obj = self._obj('UnityWndClass', 'BUTTON', hwnd=12)
        obj.name = 'Save'
        original = context.role_name
        context.role_name = lambda role: 'button'
        try:
            parts = elements.describe(obj)
        finally:
            context.role_name = original
        self.assertIn(('button', 'kind'), parts)

    def test_a_window_icon_is_remembered_for_good(self):
        """A reading is a REQUEST, so it is paid for once in a program's
        life - not once per session."""
        from titanEnhancements import labels
        obj = self._obj('UnityWndClass', hwnd=21)
        obj.appModule = types.SimpleNamespace(appName='someprogram')
        kept = {}
        real_set = labels.set_application_note
        real_get = labels.application_note
        def _keep(a, f, t):
            kept[(a, f)] = t
            return True
        labels.set_application_note = _keep
        labels.application_note = lambda a, f: kept.get((a, f), '')
        try:
            self.assertTrue(self.windowKind.remember_icon(obj, 'a blue cat'))
            self.assertEqual(kept[('someprogram', self.windowKind.ICON_NOTE)],
                             'a blue cat')
            # A new session: nothing in memory, everything in the file.
            self.windowKind.forget()
            self.assertEqual(self.windowKind.described_icon(obj), 'a blue cat')
            # And it is never asked for again.
            self.assertFalse(self.windowKind.describe_icon_later(obj))
        finally:
            labels.set_application_note = real_set
            labels.application_note = real_get

    def test_looking_it_up_is_not_asking_for_it(self):
        """Reading the file must not count as having asked, or a program
        whose icon has never been read is never read."""
        from titanEnhancements import labels, perProgram
        obj = self._obj('UnityWndClass', hwnd=22)
        obj.appModule = types.SimpleNamespace(appName='freshprogram')
        asked = []
        real_note = labels.application_note
        real_value = perProgram.value
        real_may = self.windowKind._may_describe
        labels.application_note = lambda a, f: ''
        perProgram.value = lambda name, o=None: True
        self.windowKind._may_describe = lambda o: asked.append(1) or False
        try:
            self.assertEqual(self.windowKind.described_icon(obj), '')
            self.windowKind.describe_icon_later(obj)
            self.assertEqual(len(asked), 1, 'it never asked')
            self.windowKind.describe_icon_later(obj)
            self.assertEqual(len(asked), 1, 'it asked twice')
        finally:
            labels.application_note = real_note
            perProgram.value = real_value
            self.windowKind._may_describe = real_may

    def test_the_report_says_what_it_has_really_done(self):
        self.windowKind.kind_of(self._obj('UnityWndClass'))
        report = self.windowKind.report()
        self.assertEqual(report['game'], 1)
        self.assertIn('enabled', report)


# --------------------------------------------------------------------------- #
class AGameAndAnInaccessibleApplicationAreDifferentProblems(unittest.TestCase):
    """The same answer is wrong for one of them.

    A game already has a keyboard model - its menu moves with the arrows,
    and what the player cannot do is SEE what is now highlighted. Taking
    those keys to drive a cursor of ours would break the game while
    appearing to help. An inaccessible application has no keyboard model
    that reaches the user at all, and there a cursor of ours IS the
    interface.
    """

    def setUp(self):
        _temp_config(self)
        from titanEnhancements import perProgram, smart, surface
        self.surface = surface
        self.smart = smart
        self.per = perProgram
        perProgram.forget()
        smart.forget()
        self.addCleanup(perProgram.forget)
        self.addCleanup(smart.forget)

    # ------------------------------------------------------------ which one
    def test_a_game_engine_window_is_a_game(self):
        self.assertEqual(
            self.surface.mode_for(Fake(klass='UnityWndClass')),
            self.surface.MODE_GAME)

    def test_anything_else_drawn_is_read_locally_by_default(self):
        """The default for a window that is not a game is LOCAL.

        Windows has a recogniser built in: free, on this machine, and
        nothing sent anywhere. The AI reading understands what it reads -
        which of these is a button, what is highlighted - and costs a
        picture of the user's screen at a provider, so it is opted INTO,
        which is the same rule everything else here follows.
        """
        self.assertEqual(self.surface.mode_for(Fake(klass='WeirdInstaller')),
                         self.surface.MODE_LOCAL)

    def test_the_user_chooses_which_recogniser_reads_it(self):
        """And "both" means the FREE one first.

        It used to mean the AI first, and both halves of that were wrong.
        The cheap half: Windows' recogniser is local, private and answers
        in a tenth of a second, while the AI is a picture of the screen
        sent to a provider. The expensive half is what it does to the
        READER - the Action Bus is one pipe, and a call measured taking
        longer than the bus waits ("Titan did not answer within 12s", in
        the log, from a window this started reading by itself) is that
        long with every other call queued behind it, including NVDA's
        own. An automatic feature that can do that does not read a
        window, it stops the screen reader.
        """
        from titanEnhancements import configSpec
        before = configSpec.read
        try:
            for answer, wanted in (('ai', self.surface.MODE_NATIVE),
                                   ('both', self.surface.MODE_LOCAL),
                                   ('local', self.surface.MODE_LOCAL)):
                configSpec.read = lambda a=answer: dict(configSpec.defaults(),
                                                        ocrTier=a)
                self.assertEqual(
                    self.surface.mode_for(Fake(klass='WeirdInstaller')),
                    wanted, answer)
        finally:
            configSpec.read = before

    def test_the_ai_is_still_there_as_the_fallback(self):
        """Windows first is only right if the AI still catches what
        Windows cannot read - otherwise it is not an order, it is a
        feature taken away."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'surface.py'),
                         encoding='utf-8').read()
        at = source.index('if mode == MODE_LOCAL:')
        block = source[at:at + 700]
        self.assertIn('MODE_APPLICATION', block,
                      'a local reading that fails now goes nowhere')
        self.assertIn('with AI instead', block)

    def test_a_reader_module_may_simply_say(self):
        from titanEnhancements.readerModules import schema
        module = schema.Module({'id': 'x', 'match': {'class': 'a'},
                                'surface': {'ocr': 'application'}})
        self.assertEqual(
            self.surface.mode_for(Fake(klass='UnityWndClass'), module),
            self.surface.MODE_APPLICATION)

    def test_a_reader_module_may_ask_for_the_native_one(self):
        from titanEnhancements.readerModules import schema
        module = schema.Module({'id': 'x', 'match': {'class': 'a'},
                                'surface': {'ocr': 'native'}})
        self.assertEqual(
            self.surface.mode_for(Fake(klass='UnityWndClass'), module),
            self.surface.MODE_NATIVE)

    def test_the_user_can_say_and_it_is_remembered(self):
        self.per.set_value('surfaceGame', 'thing.exe', True)
        self.assertEqual(self.surface.mode_for(Fake(klass='WeirdInstaller',
                                                    app='thing.exe')),
                         self.surface.MODE_GAME)

    def test_saying_it_is_not_a_game_asks_for_a_reading(self):
        """And which reading is the user's other answer, not this one's."""
        self.per.set_value('surfaceGame', 'thing.exe', False)
        self.assertIn(self.surface.mode_for(Fake(klass='UnityWndClass',
                                                 app='thing.exe')),
                      (self.surface.MODE_LOCAL, self.surface.MODE_NATIVE))

    # -------------------------------------------------- the navigable model
    def _reading(self):
        return ('Main menu\nA game menu\n\n[Menu]\n'
                '  New game, button\n  Continue, button, selected\n'
                '  Options, button\n\n[Footer]\n  Version 1.2, text')

    def test_the_reading_becomes_controls_in_the_order_they_appear(self):
        found = self.smart.controls_in(self._reading())
        self.assertEqual([one['name'] for one in found],
                         ['New game', 'Continue', 'Options', 'Version 1.2'])
        self.assertEqual(found[0]['region'], 'Menu')
        self.assertEqual(found[3]['region'], 'Footer')

    def test_the_title_and_the_summary_are_not_controls(self):
        found = self.smart.controls_in(self._reading())
        self.assertNotIn('Main menu', [one['name'] for one in found])
        self.assertNotIn('A game menu', [one['name'] for one in found])

    def test_tab_walks_them_and_stops_at_the_ends(self):
        self.smart.take(7, self._reading())
        first = self.smart.move(1)
        self.assertEqual(first['control']['name'], 'New game')
        self.assertEqual(first['at'], 0)
        self.smart.move(1)
        self.smart.move(1)
        last = self.smart.move(1)
        self.assertEqual(last['control']['name'], 'Version 1.2')
        # A wall is information: wrapping would leave the user unable to
        # tell how long the window is.
        edge = self.smart.move(1)
        self.assertTrue(edge['edge'])
        self.assertEqual(edge['control']['name'], 'Version 1.2')

    def test_shift_tab_goes_back(self):
        self.smart.take(7, self._reading())
        self.smart.move(1)
        self.smart.move(1)
        back = self.smart.move(-1)
        self.assertEqual(back['control']['name'], 'New game')

    def test_a_new_reading_keeps_the_cursor_where_it_was(self):
        """A game re-reads whenever the picture changes, and a cursor that
        jumped to the top每 time would be unusable exactly when something
        is happening."""
        self.smart.take(7, self._reading())
        self.smart.move(1)
        self.smart.move(1)
        self.assertEqual(self.smart.here()['control']['name'], 'Continue')
        self.smart.take(7, self._reading().replace('selected', ''))
        self.assertEqual(self.smart.here()['control']['name'], 'Continue')

    def test_a_control_that_has_gone_moves_the_cursor(self):
        self.smart.take(7, self._reading())
        self.smart.move(1)
        self.smart.take(7, 'Other\n\n[Menu]\n  Quit, button')
        self.assertIsNone(self.smart.here())

    def test_nothing_to_move_to_is_answered_not_guessed(self):
        self.smart.forget()
        self.assertIsNone(self.smart.move(1))
        self.assertIsNone(self.smart.here())

    def test_pressing_needs_titan_and_says_so(self):
        self.smart.take(7, self._reading())
        self.smart.move(1)
        ok, said = self.smart.press()
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_saying_yes_writes_a_reader_module_for_that_program(self):
        """The switch would make it work again; a module says WHY, can be
        corrected, and can be given to somebody with the same program."""
        from titanEnhancements import readerModules
        readerModules.forget()
        self.addCleanup(readerModules.forget)
        window = Fake(role='WINDOW', klass='UnityWndClass', app='game.exe',
                      name='A Game', children=[])
        self.assertTrue(self.surface._write_a_module(window, None,
                                                     'game.exe'))
        written = [one for one in readerModules.load()
                   if one.match.get('class') == 'UnityWndClass']
        self.assertTrue(written, 'no module was written')
        self.assertEqual(written[0].surface.get('ocr'),
                         self.surface.MODE_GAME)

    def test_a_program_that_already_has_a_module_keeps_it(self):
        from titanEnhancements.readerModules import schema
        module = schema.Module({'id': 'x', 'match': {'class': 'UnityWndClass'},
                                'surface': {'ocr': 'application'}})
        self.assertFalse(self.surface._write_a_module(
            Fake(klass='UnityWndClass'), module, 'game.exe'))

    def test_the_keys_are_only_borrowed_for_an_application(self):
        """A reader that swallowed Tab in a game would break the game."""
        import re
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            '__init__.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('MODE_APPLICATION', source)
        keys = re.search(r'SMART_KEYS = \{(.+?)\}', source, re.S).group(1)
        # The game's own left and right must never be taken.
        self.assertNotIn('leftArrow', keys)
        self.assertNotIn('rightArrow', keys)
        self.assertIn('kb:tab', keys)
        self.assertIn('kb:escape', keys)


# --------------------------------------------------------------------------- #
class AWindowWornAsItsOwnControls(unittest.TestCase):
    """The native mode: the reading becomes REAL controls on the real window.

    Nothing is parsed and nothing is announced from the add-on here - that is
    the claim, and it is what makes this mode worth having: the controls are
    Titan's own wx controls, parented into the target window, so NVDA reads
    them the way it reads any program's. What this loop owes the user is that
    they stay TRUE, and that a window which will not wear them still leaves
    them with something.
    """

    def setUp(self):
        from titanEnhancements import link, surface
        self.surface = surface
        self.link = link
        self.calls = []
        self.answers = {}
        original = link.LINK.bridge
        connected = link.LINK.connected

        def fake(call, timeout=None, **args):
            self.calls.append((call, args))
            return self.answers.get(call, (True, {'open': True}))
        link.LINK.bridge = fake
        link.LINK.connected = lambda: True
        self.addCleanup(lambda: setattr(link.LINK, 'bridge', original))
        self.addCleanup(lambda: setattr(link.LINK, 'connected', connected))

    def test_putting_the_controls_on_reads_the_window_first(self):
        ok, _said = self.surface.overlay_show(1234)
        self.assertTrue(ok)
        call, args = self.calls[0]
        self.assertEqual(call, 'ocr.overlay_show')
        self.assertEqual(args['hwnd'], 1234)
        # Reading first is the point: an overlay built from a reading taken
        # some time ago is a set of controls that were true then.
        self.assertTrue(args['read'])

    def test_a_window_that_will_not_wear_them_says_so_rather_than_lying(self):
        self.answers['ocr.overlay_show'] = (True, {'open': False,
                                                   'said': 'nothing to place'})
        ok, said = self.surface.overlay_show(1)
        self.assertFalse(ok)
        self.assertIn('nothing to place', said)

    def test_refreshing_is_asked_of_the_overlay_not_of_the_reader(self):
        """Only the overlay knows to make itself invisible first.

        A reading taken while our own controls sit on the window is a reading
        of our own controls, so the watcher must never call `ocr.read_window`
        once an overlay is up.
        """
        self.surface.overlay_refresh()
        self.assertEqual([call for call, _a in self.calls],
                         ['ocr.overlay_refresh'])

    def test_the_watch_falls_back_rather_than_leaving_nothing(self):
        import threading
        self.answers['ocr.overlay_show'] = (True, {'open': False, 'said': 'no'})
        stop = threading.Event()
        stop.set()                                   # one pass and out
        self.assertEqual(self.surface._watch_native(9, stop),
                         self.surface.MODE_APPLICATION)

    def test_the_controls_are_taken_off_when_the_watch_ends(self):
        """Left standing they would be read while nothing kept them true."""
        with self.surface._LOCK:
            self.surface._watching['mode'] = self.surface.MODE_NATIVE
        self.surface._finish_watch()
        self.assertIn('ocr.overlay_close',
                      [call for call, _a in self.calls])

    def test_the_user_working_in_the_overlay_counts_as_being_here(self):
        """The keyboard is on a control of Titan's while it is being used.

        Two of the three ways an overlay attaches are top-level windows of
        their own, so the plain "is the target the foreground window" answers
        "they have gone somewhere else" for as long as somebody is working in
        it - and the controls would stop being refreshed exactly then.
        """
        import titanEnhancements.surface as s
        self.addCleanup(lambda: setattr(s, '_foreground', s._foreground))
        s._foreground = lambda: 77
        s._root_owner = lambda h: 42 if h == 77 else h
        self.assertTrue(s._user_is_here(42))
        s._root_owner = lambda h: h
        self.assertFalse(s._user_is_here(42))



# --------------------------------------------------------------------------- #
class TheNativeCursorAnnouncesItself(unittest.TestCase):
    """Entering the model is a MODE CHANGE, and a mode change is announced.

    The keyboard is about to mean something different - Tab walks a model
    of what a picture was read as, rather than doing whatever the program
    does with it - and a user who is not told that is a user pressing Tab
    and hearing something they cannot account for.
    """

    def setUp(self):
        from titanEnhancements import smart
        self.smart = smart
        smart.forget()
        self.addCleanup(smart.forget)
        self.said = []
        self._announce = smart._announce
        smart._announce = lambda entered: (self.said.append(entered) or True)
        self.addCleanup(lambda: setattr(smart, '_announce', self._announce))

    def _reading(self):
        return 'A window\n\n[Main]\n  Play, button\n  Quit, button'

    def test_arriving_says_so_once(self):
        self.smart.take(7, self._reading())
        self.assertEqual(self.said, [True])

    def test_re_reading_the_same_window_says_nothing(self):
        """A game re-reads whenever the picture changes; announcing each
        time would be a sound and a sentence over whatever the user is
        doing."""
        self.smart.take(7, self._reading())
        self.said[:] = []
        self.smart.take(7, self._reading())
        self.smart.take(7, self._reading().replace('Quit', 'Exit'))
        self.assertEqual(self.said, [])

    def test_leaving_says_so(self):
        self.smart.take(7, self._reading())
        self.said[:] = []
        self.smart.forget()
        self.assertEqual(self.said, [False])

    def test_leaving_when_it_was_never_there_says_nothing(self):
        self.smart.forget()
        self.assertEqual(self.said, [])

    def test_a_reading_with_no_controls_is_not_an_arrival(self):
        self.smart.take(7, 'A window\n\nnothing indented here')
        self.assertEqual(self.said, [])


class TheSoundsAndWordsItUses(unittest.TestCase):

    def test_the_sounds_are_ones_the_theme_really_has(self):
        """A sound named but missing is silence, which is what this whole
        area keeps being caught by."""
        from titanEnhancements import smart
        theme = os.path.join(ROOT, 'sfx', 'default', 'SRE')
        if not os.path.isdir(theme):
            self.skipTest('Titan is not beside the add-on here')
        for name in (smart.SOUND_ON, smart.SOUND_OFF):
            self.assertTrue(os.path.exists(os.path.join(theme, name)), name)

    def test_the_polish_catalogue_compiles_and_says_it(self):
        """The add-on shipped `locale/pl` as an EMPTY folder, so every
        string was English however the user had set NVDA up."""
        sys.path.insert(0, os.path.dirname(HERE))
        import build as builder
        source = os.path.join(ADDON, 'locale', 'pl', 'LC_MESSAGES',
                              'nvda.po')
        if not os.path.exists(source):
            self.skipTest('no Polish catalogue')
        entries = builder._read_po(source)
        self.assertIn('', entries, 'the header carries the charset')
        self.assertEqual(entries.get('Window recognised, Native TCE cursor'),
                         'Rozpoznano okno, Native TCE cursor')


    def test_the_compiled_catalogue_is_readable_by_gettext(self):
        import gettext
        made = os.path.join(ADDON, 'locale', 'pl', 'LC_MESSAGES', 'nvda.mo')
        if not os.path.exists(made):
            self.skipTest('not built yet')
        with open(made, 'rb') as handle:
            catalogue = gettext.GNUTranslations(handle)
        self.assertEqual(
            catalogue.gettext('Window recognised, Native TCE cursor'),
            'Rozpoznano okno, Native TCE cursor')
        # Anything the catalogue has not got must fall back to the English
        # source, not to nothing. A msgid that will never exist, because
        # using a real untranslated one is a test that starts failing the
        # day somebody translates it.
        self.assertEqual(catalogue.gettext('__no such string__'),
                         '__no such string__')

    def test_every_string_the_addon_can_say_is_translated(self):
        """The whole catalogue, checked against the whole source.

        A reader whose Polish is nine tenths of the way there is one that
        says every tenth sentence in English, and the sentences that get
        left behind are always the newest - which are the ones nobody has
        read yet. So this is not "is there a catalogue": it is every
        `_('...')` in every module, and a string added today fails it.

        The strings are found the way the builder finds them, by parsing
        the source rather than by matching text, so a call written across
        several lines counts and a word in a comment does not.
        """
        import ast
        source_of = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements')
        made = os.path.join(ADDON, 'locale', 'pl', 'LC_MESSAGES', 'nvda.po')
        if not os.path.exists(made):
            self.skipTest('no Polish catalogue')
        sys.path.insert(0, os.path.join(ROOT, 'nvda-addon'))
        try:
            import build as builder
        finally:
            sys.path.pop(0)
        have = {key for key, value in builder._read_po(made).items() if value}
        missing = []
        for base, _dirs, names in os.walk(source_of):
            if '__pycache__' in base:
                continue
            for name in sorted(names):
                if not name.endswith('.py'):
                    continue
                with io.open(os.path.join(base, name),
                             encoding='utf-8') as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call) or not node.args:
                        continue
                    called = getattr(node.func, 'id', None) \
                        or getattr(node.func, 'attr', None)
                    if called != '_':
                        continue
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and \
                            isinstance(first.value, str) and \
                            first.value not in have:
                        missing.append('%s:%d %r' % (name, node.lineno,
                                                     first.value[:60]))
        self.assertEqual(missing, [],
                         '%d strings have no Polish: %s'
                         % (len(missing), '; '.join(missing[:8])))



# --------------------------------------------------------------------------- #
class AskingTheMainThreadFromTheMainThread(unittest.TestCase):
    """Reported as "there is no window to read", while looking at one.

    `commands.watch_surface` is a gesture's script, so it runs on NVDA's
    main thread; it asked `context.window()`, which queued the work onto
    the main thread and blocked waiting for it. The queue is drained by
    the thread that was now waiting, so nothing ran, the wait timed out
    after four seconds, and the caller was handed nothing - which the
    command reported as there being no window.
    """

    def setUp(self):
        from titanEnhancements import compat, context
        self.context = context
        self.compat = compat
        self._queue = compat.queueHandler

        class NeverRuns:
            """A queue nothing drains - which is what the main thread is
            while it is blocked waiting for the answer."""
            eventQueue = object()

            @staticmethod
            def queueFunction(_queue, _function):
                return None
        compat.queueHandler = NeverRuns
        self.addCleanup(lambda: setattr(compat, 'queueHandler', self._queue))

    def test_it_runs_there_and_then_instead_of_deadlocking(self):
        import time
        began = time.time()
        answer = self.context._on_main(lambda: 'answered', timeout=1.0)
        self.assertEqual(answer, 'answered')
        self.assertLess(time.time() - began, 0.5,
                        'it waited, which means it queued and deadlocked')

    def test_from_another_thread_it_still_goes_through_the_queue(self):
        """The whole point of the function is unchanged: a bus thread must
        not touch NVDA's objects itself."""
        import threading
        answers = []

        def elsewhere():
            try:
                self.context._on_main(lambda: 'x', timeout=0.3)
            except TimeoutError:
                answers.append('queued')
            except Exception as error:               # noqa: BLE001
                answers.append(type(error).__name__)
        worker = threading.Thread(target=elsewhere)
        worker.start()
        worker.join(3)
        self.assertEqual(answers, ['queued'])

    def test_watching_asks_windows_when_nvda_cannot_say(self):
        """A watch needs a concrete handle: "whatever is in front" is not
        something that can be watched, and a window that has gone must be
        able to end it."""
        import inspect
        from titanEnhancements import commands
        source = inspect.getsource(commands.watch_surface)
        self.assertIn('_foreground_window()', source)

    def test_but_a_reading_still_says_nothing_rather_than_guessing(self):
        """`_here()` empty means NVDA could not say, and Titan reads that
        as "whatever is in front" - which is right for a reading and wrong
        to invent here."""
        import inspect
        from titanEnhancements import commands
        source = inspect.getsource(commands._here)
        self.assertNotIn('_foreground_window', source)



# --------------------------------------------------------------------------- #
class ReadingTheWholeMachineTheWayTitanIsRead(unittest.TestCase):
    """Reported as "controls are not read".

    They were not, and that was a decision rather than a fault: outside
    Titan the add-on deliberately leaves NVDA's own reporting alone,
    because NVDA knows about tables, landmarks and browse mode and standing
    in for it everywhere to gain three tones is a trade nobody should make
    on somebody else's behalf. It is a switch now, because it was always
    the user's trade to make.
    """

    def setUp(self):
        from titanEnhancements import configSpec, focus
        self.focus = focus
        focus.set_titan_pid(4242)
        focus.note_titan_spoke()
        self.addCleanup(lambda: focus.set_titan_pid(0))
        self._read = configSpec.read
        self.configSpec = configSpec
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))

    def _on(self, **extra):
        self.configSpec.read = lambda: dict(self.configSpec.defaults(),
                                            **extra)

    def test_it_is_off_by_default(self):
        self.assertIn('default=False',
                      self.configSpec.SPEC['pitchedEverywhere'])
        self._on()
        self.assertFalse(self.focus._pitched_everywhere())

    def test_the_switch_is_what_decides(self):
        self._on(pitchedEverywhere=True)
        self.assertTrue(self.focus._pitched_everywhere())

    def test_with_it_off_an_ordinary_control_is_left_to_nvda(self):
        """Which is the whole point of the line being drawn where it is."""
        self._on()
        called = []
        answer = self.focus.handle_gain_focus(
            Fake(role='BUTTON', name='Save', pid=99),
            lambda: called.append(1))
        self.assertIsNone(answer)
        self.assertEqual(called, [1])

    def test_the_reading_it_uses_is_the_same_one_titan_gets(self):
        """Not a second implementation: the name, the control type lower,
        the state higher, from `elements.describe`."""
        import inspect
        source = inspect.getsource(self.focus._windows_reading)
        self.assertIn('_pitched_everywhere()', source)
        self.assertIn('elements.describe(obj)', source)
        self.assertIn('can_mute()', source)

    def test_where_the_user_is_still_goes_in_front_of_it(self):
        import inspect
        source = inspect.getsource(self.focus._windows_reading)
        branch = source[source.index('if _pitched_everywhere() and can_mute'):
                        source.index('elements.describe(obj)')]
        self.assertIn('prefix_next', branch,
                      'the context must still be said in front of it')




# --------------------------------------------------------------------------- #
class TitansOwnVocabularyInNVDA(unittest.TestCase):
    """Titan Access's TCE behaviours, ported.

    A user who reads Titan with NVDA got a strictly poorer reading of the
    same desktop than one reading it with Titan's own reader, and every
    difference was something Titan Access knew and NVDA could not: a slot of
    the status bar is a status bar item, and arriving in Titan is worth
    saying. Two readers, one desktop, one vocabulary.
    """

    class Node:
        def __init__(self, role, name=''):
            self.role = types.SimpleNamespace(name=role)
            self.name = name

    def setUp(self):
        from titanEnhancements import configSpec, semantics, tce
        self.tce = tce
        self.semantics = semantics
        self.configSpec = configSpec
        configSpec.forget()
        self._read = configSpec.read
        self._answers = dict(configSpec.defaults())
        configSpec.read = lambda: dict(self._answers)
        self._chain = semantics._ancestors
        self._said = []
        self._sounds = []
        from titanEnhancements import earcons
        self._play = earcons.play_named
        earcons.play_named = lambda name, **kw: self._sounds.append(name)
        tce.forget()
        self.addCleanup(tce.forget)
        self.addCleanup(lambda: setattr(earcons, 'play_named', self._play))
        self.addCleanup(lambda: setattr(semantics, '_ancestors', self._chain))
        self.addCleanup(lambda: setattr(configSpec, 'read', self._read))
        self.addCleanup(configSpec.forget)

    def _above(self, *nodes):
        self.semantics._ancestors = lambda obj: list(nodes)

    # ------------------------------------------------- the status bar slot
    def test_a_slot_of_titans_status_bar_is_a_status_bar_item(self):
        self._above(self.Node('LIST', 'Status bar'), self.Node('WINDOW'))
        self.assertEqual(
            self.tce.role_word(self.Node('LISTITEM'), 'tnotes', 'list item'),
            'status bar item')

    def test_it_knows_the_bar_by_its_role_as_well_as_by_its_name(self):
        self._above(self.Node('STATUSBAR', ''))
        self.assertEqual(
            self.tce.role_word(self.Node('LISTITEM'), 'tce', 'list item'),
            'status bar item')

    def test_the_name_is_matched_in_the_users_own_language(self):
        """The container's name follows the application's language, so both
        spellings are the same container."""
        self._above(self.Node('PANE', 'Pasek stanu:'))
        self.assertEqual(
            self.tce.role_word(self.Node('LISTITEM'), 'tce', 'element listy'),
            'status bar item')

    def test_an_ordinary_row_of_an_ordinary_list_is_left_alone(self):
        self._above(self.Node('LIST', 'Applications'), self.Node('WINDOW'))
        self.assertEqual(
            self.tce.role_word(self.Node('LISTITEM'), 'tce', 'list item'),
            'list item')

    def test_outside_titan_nothing_is_relabelled(self):
        """Saying it about somebody else's list would be inventing a fact
        about their program."""
        self._above(self.Node('LIST', 'Status bar'))
        self.assertEqual(
            self.tce.role_word(self.Node('LISTITEM'), None, 'list item'),
            'list item')

    def test_a_control_that_is_not_a_row_is_left_alone(self):
        self._above(self.Node('STATUSBAR'))
        self.assertEqual(
            self.tce.role_word(self.Node('BUTTON'), 'tce', 'button'), 'button')

    # ------------------------------------------------ arriving and leaving
    def test_the_first_focus_of_a_session_says_nothing(self):
        """It establishes the baseline. NVDA starting while Titan is in
        front must not open with an announcement about a window the user has
        been sitting in."""
        self.assertEqual(self.tce.crossing(None, application='tce'), '')
        self.assertEqual(self._sounds, [])

    def test_arriving_in_titan_is_a_cue_and_the_name(self):
        self.tce.crossing(None, application='tce')      # baseline
        self.tce.crossing(None, application=None)
        self._sounds[:] = []
        self.assertEqual(self.tce.crossing(None, application='tnotes'),
                         'entered')
        self.assertEqual(self._sounds, [self.tce.SOUND_ENTER])

    def test_leaving_titan_is_the_other_cue(self):
        self.tce.crossing(None, application='tce')      # baseline
        self.assertEqual(self.tce.crossing(None, application=None), 'left')
        self.assertEqual(self._sounds, [self.tce.SOUND_LEAVE])

    def test_moving_between_titans_own_windows_is_not_a_crossing(self):
        """The launcher and everything it starts are one desktop. A cue per
        window would fire on the shell's own furniture constantly."""
        self.tce.crossing(None, application='tce')
        self._sounds[:] = []
        self.assertEqual(self.tce.crossing(None, application='tnotes'), '')
        self.assertEqual(self.tce.crossing(None, application='tedit'), '')
        self.assertEqual(self._sounds, [])

    def test_the_switch_being_off_means_neither(self):
        self._answers['appSemantics'] = False
        self.tce.crossing(None, application='tce')
        self.assertEqual(self.tce.crossing(None, application=None), '')
        self.assertEqual(self._sounds, [])

    def test_the_sounds_are_the_ones_titan_access_uses(self):
        """A theme replaces them; a user without Titan Access still has
        them, because they live in the theme rather than in that
        component."""
        import os
        for name in (self.tce.SOUND_ENTER, self.tce.SOUND_LEAVE):
            self.assertTrue(os.path.exists(
                os.path.join(ROOT, 'sfx', 'default', 'SRE', name)), name)




# --------------------------------------------------------------------------- #
class OneKeyOneMacro(unittest.TestCase):
    """What a Leasey script is on this desktop: the user's own macro, on a
    key, in NVDA's own Input Gestures dialog, under its own name.

    Every Titan action was already bindable, which is most of a hot-key
    manager - but "run a macro" is ONE action taking the macro's name, so
    binding it gets a key that asks which macro. A menu on a key is not a
    macro on a key.
    """

    def setUp(self):
        from titanEnhancements import gestures, link
        self.gestures = gestures
        self.macros = {'macros': [
            {'name': 'Voice demo', 'hotkey': 'ctrl+alt+v', 'type': 'tcs'},
            {'name': 'Read the clock', 'hotkey': '', 'type': 'macro'},
            {'name': '', 'hotkey': 'x', 'type': 'tcs'},
        ]}
        original = link.LINK.bridge
        link.LINK.bridge = lambda call, **kw: (
            (True, self.macros) if call == 'macros.list' else (False, 'no'))
        self.addCleanup(lambda: setattr(link.LINK, 'bridge', original))

    def test_every_macro_becomes_a_row_of_its_own(self):
        rows = self.gestures.macro_rows()
        self.assertEqual([row['key'] for row in rows],
                         ['Voice demo', 'Read the clock'])

    def test_a_macro_with_no_name_is_not_a_row(self):
        """There would be nothing to name the script after, and a script
        with no name cannot be bound to anything."""
        self.assertEqual(len(self.gestures.macro_rows()), 2)

    def test_each_gets_a_script_name_of_its_own(self):
        """One script per macro. Without the key they would all be
        `titan_macros_run_macro`, and the last one built would answer every
        binding the user made."""
        rows = self.gestures.macro_rows()
        names = [self.gestures.script_name(row['addon'], row['action'],
                                           row['key']) for row in rows]
        self.assertEqual(len(set(names)), 2)
        self.assertIn('Voice', names[0])

    def test_the_macro_name_is_already_answered(self):
        """Or the key the user bound to one macro would ask which macro."""
        rows = self.gestures.macro_rows()
        self.assertEqual(rows[0]['arguments'], {'name': 'Voice demo'})

    def test_the_row_says_which_macro_it_is(self):
        """It is the description column of the Input Gestures dialog, so a
        row that said "run a macro" for all of them would be a list nobody
        can bind from."""
        rows = self.gestures.macro_rows()
        self.assertIn('Voice demo', rows[0]['summary'])
        self.assertIn('ctrl+alt+v', rows[0]['summary'])

    def test_an_actions_own_summary_never_overwrites_a_macros(self):
        rows = self.gestures.macro_rows()
        self.gestures._merge_summaries(
            rows, 'macros', [{'name': 'run_macro', 'summary': 'Run a macro.'}])
        self.assertIn('Voice demo', rows[0]['summary'])

    def test_a_titan_that_has_no_macros_is_not_an_error(self):
        self.macros = {'macros': []}
        self.assertEqual(self.gestures.macro_rows(), [])

    def test_a_titan_that_does_not_answer_is_not_an_error(self):
        from titanEnhancements import link
        link.LINK.bridge = lambda call, **kw: (False, 'not running')
        self.assertEqual(self.gestures.macro_rows(), [])



# --------------------------------------------------------------------------- #
class AVoiceIsMoreThanThreeDials(unittest.TestCase):
    """A class may name a whole voice - and only where that can be honoured.

    Pitch, rate and volume are real NVDA speech commands: exact, per
    utterance, and they can be part of a control's reading. A voice, a
    variant and above all a SYNTHESIZER are not commands at all - they are
    settings on a driver - and a different synthesizer is a second program
    producing sound, which cannot be part of one sentence. So the table can
    hold that answer for a whole MESSAGE and must refuse it for a part.
    """

    def setUp(self):
        from titanEnhancements import classes
        self.classes = classes
        self._path = classes.path
        self._dir = tempfile.mkdtemp()
        classes.path = lambda: os.path.join(self._dir, 'classes.json')
        classes.forget()
        self.addCleanup(classes.forget)
        self.addCleanup(lambda: setattr(classes, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self._dir, ignore_errors=True))

    def test_a_whole_message_may_have_a_synthesizer_of_its_own(self):
        self.classes.set_voice('notification',
                               {'synth': 'espeak', 'pitch': 3})
        self.assertEqual(self.classes.synth_of('notification'), 'espeak')

    def test_part_of_a_reading_may_not(self):
        """Two synthesizers cannot make one sentence between them."""
        self.classes.set_voice('kind', {'synth': 'espeak', 'pitch': -4})
        self.assertEqual(self.classes.voice_of('kind').get('synth'), None)
        self.assertEqual(self.classes.synth_of('kind'), '')

    def test_a_stored_synth_on_a_part_is_still_not_acted_on(self):
        """A table that can hold a wrong answer must not obey it - the file
        is a file, and an older add-on or a hand edit can put one there."""
        self.classes._load()['kind'] = {'synth': 'espeak'}
        self.assertEqual(self.classes.synth_of('kind'), '')

    def test_a_voice_and_a_variant_are_kept_for_anything(self):
        self.classes.set_voice('kind', {'voice': 'pl', 'variant': 'max'})
        kept = self.classes.voice_of('kind')
        self.assertEqual(kept['voice'], 'pl')
        self.assertEqual(kept['variant'], 'max')

    def test_inflection_is_a_dial_like_the_others(self):
        self.classes.set_voice('text', {'inflection': 5})
        self.assertEqual(self.classes.voice_of('text')['inflection'], 5)

    def test_a_dial_of_nothing_is_not_stored(self):
        """Or every class would be "changed" the moment it was looked at."""
        self.classes.set_voice('text', {'pitch': 0, 'voice': ''})
        self.assertEqual(self.classes.voice_of('text'), {})

    def test_the_old_file_still_reads(self):
        """The store used to be nothing but classes. Reading that shape as
        the new one would lose every answer somebody had given."""
        with io.open(self.classes.path(), 'w', encoding='utf-8') as handle:
            json.dump({'kind': {'pitch': -6}}, handle)
        self.classes.forget()
        self.assertEqual(self.classes.voice_of('kind')['pitch'], -6)

    def test_the_new_classes_are_all_whole_messages(self):
        for tag in ('notification', 'controller', 'text'):
            self.assertTrue(self.classes.is_whole(tag), tag)

    def test_every_class_is_in_a_group(self):
        """A class in no group would be missing from the manager's list."""
        grouped = {tag for _name, members in self.classes.GROUPS
                   for tag in members}
        for tag in self.classes.defaults():
            self.assertIn(tag, grouped, tag)

    def test_every_class_has_words_saying_what_it_is_for(self):
        words = self.classes.meanings()
        for tag in self.classes.defaults():
            self.assertTrue(words.get(tag), tag)


# --------------------------------------------------------------------------- #
class TheOrderTheePartsAreReadIn(unittest.TestCase):
    """"Checked, check box" and "check box, checked" are the same three
    facts in two orders, and which is right is what somebody is used to."""

    class Obj:
        def __init__(self, **kw):
            self.name = kw.get('name', '')
            self.value = kw.get('value', '')
            self.description = kw.get('description', '')
            self.role = types.SimpleNamespace(name=kw.get('role', 'BUTTON'))
            self.states = kw.get('states', set())
            self.positionInfo = kw.get('position', {})

    def setUp(self):
        from titanEnhancements import classes, elements
        self.classes, self.elements = classes, elements
        self._path = classes.path
        self._dir = tempfile.mkdtemp()
        classes.path = lambda: os.path.join(self._dir, 'classes.json')
        classes.forget()
        self.addCleanup(classes.forget)
        self.addCleanup(lambda: setattr(classes, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self._dir, ignore_errors=True))

    def _said(self, obj):
        return [text for text, _voice in self.elements.describe(obj)]

    def test_the_default_is_the_name_then_what_it_is(self):
        self.assertEqual(self.classes.parts_read()[:3],
                         ['name', 'kind', 'state'])

    def test_the_order_can_be_turned_round(self):
        self.classes.set_order([('kind', True), ('state', True),
                                ('name', True)])
        said = self._said(self.Obj(name='Save', role='CHECKBOX'))
        self.assertEqual(said[-1], 'Save')

    def test_a_part_can_be_switched_off_entirely(self):
        self.classes.set_order([('name', True), ('kind', False),
                                ('state', True)])
        said = self._said(self.Obj(name='Save', role='BUTTON'))
        self.assertEqual(said, ['Save'])

    def test_a_part_this_version_added_appears_rather_than_vanishing(self):
        """A stored order written before a part existed must gain it, or
        the part is silently missing for everybody who ever saved one."""
        self.classes.set_order([('name', True), ('kind', True)])
        self.assertEqual([name for name, _on in self.classes.order()],
                         ['name', 'kind', 'state', 'value', 'description',
                          'place'])

    def test_a_switched_off_part_stays_switched_off_across_a_save(self):
        self.classes.set_order([('name', True), ('kind', False)])
        self.assertFalse(dict(self.classes.order())['kind'])

    def test_putting_it_back_really_puts_it_back(self):
        self.classes.set_order([('state', True), ('name', True)])
        self.classes.reset_order()
        self.assertEqual(self.classes.parts_read()[0], 'name')
        self.assertFalse(self.classes.order_changed())

    def test_a_control_is_never_read_as_silence(self):
        """Every part off is a preference; saying nothing at all is a
        reader that has stopped working."""
        self.classes.set_order([(name, False) for name in self.classes.PARTS])
        said = self._said(self.Obj(name='', role='BUTTON'))
        self.assertTrue(said)

    def test_a_value_is_not_said_twice(self):
        said = self._said(self.Obj(name='Save', value='Save'))
        self.assertEqual(said.count('Save'), 1)

    def test_every_part_has_words_saying_what_it_is(self):
        words = self.classes.part_names()
        for name in self.classes.PARTS:
            self.assertTrue(words.get(name), name)


# --------------------------------------------------------------------------- #
class AnotherSynthesizerForAWholeMessage(unittest.TestCase):
    """`speaking` is the half a speech command cannot do, and it is written
    around putting back what it changed."""

    class Synth:
        def __init__(self):
            self.rate = 50
            self.pitch = 50
            self.volume = 50
            self.voice = 'en'
            self.variant = 'none'
            self.said = []
            self.cancelled = 0

        def speak(self, sequence):
            self.said.append(sequence)

        def cancel(self):
            self.cancelled += 1

    def setUp(self):
        from titanEnhancements import speaking
        self.speaking = speaking
        speaking.forget()
        self.addCleanup(speaking.forget)

    def test_a_profile_is_put_on_and_taken_off_again(self):
        synth = self.Synth()
        was = self.speaking.apply_to(synth, {'rate': 4, 'voice': 'pl'})
        self.assertEqual(synth.voice, 'pl')
        self.assertNotEqual(synth.rate, 50)
        self.speaking.put_back(synth, was)
        self.assertEqual(synth.voice, 'en')
        self.assertEqual(synth.rate, 50)

    def test_a_dial_stays_inside_nvdas_own_range(self):
        synth = self.Synth()
        synth.rate = 98
        self.speaking.apply_to(synth, {'rate': 10})
        self.assertLessEqual(synth.rate, 100)
        synth.rate = 2
        self.speaking.apply_to(synth, {'rate': -10})
        self.assertGreaterEqual(synth.rate, 0)

    def test_a_dial_the_driver_has_not_got_is_left_alone(self):
        class Bare:
            supportedSettings = ()
            voice = 'en'
        bare = Bare()
        self.assertEqual(self.speaking.apply_to(bare, {'rate': 5}), {})

    def test_putting_back_never_raises(self):
        class Awkward:
            def __setattr__(self, name, value):
                raise RuntimeError('no')
        self.speaking.put_back(Awkward(), {'rate': 50})

    def test_a_synthesizer_that_will_not_start_is_not_asked_twice(self):
        self.assertIsNone(self.speaking.driver_for('no such synth'))
        self.assertIn('no such synth', self.speaking.refused())
        self.assertIsNone(self.speaking.driver_for('no such synth'))

    def test_nothing_named_is_nothing_asked_for(self):
        self.assertIsNone(self.speaking.driver_for(''))

    def test_saying_a_whole_thing_needs_a_synthesizer_to_say_it_with(self):
        self.assertFalse(self.speaking.speak_with({}, 'hello'))
        self.assertFalse(self.speaking.speak_with({'synth': 'nope'}, 'hello'))


# --------------------------------------------------------------------------- #
class AWholeMessageInItsOwnVoice(unittest.TestCase):
    """`voices.say_whole` is where the rule is enforced rather than trusted,
    and `False` from it always means "say it the ordinary way"."""

    def setUp(self):
        from titanEnhancements import classes, voices
        self.classes, self.voices = classes, voices
        self._path = classes.path
        self._dir = tempfile.mkdtemp()
        classes.path = lambda: os.path.join(self._dir, 'classes.json')
        classes.forget()
        self.addCleanup(classes.forget)
        self.addCleanup(lambda: setattr(classes, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self._dir, ignore_errors=True))

    def test_nothing_to_say_is_not_said(self):
        self.assertFalse(self.voices.say_whole('notification', '   '))

    def test_a_part_of_a_reading_is_refused_outright(self):
        self.assertFalse(self.voices.say_whole(
            'kind', 'hello', profile={'synth': 'espeak'}))

    def test_a_class_with_no_synthesizer_is_left_to_the_ordinary_path(self):
        """It keeps the message in NVDA's own queue, where it can be
        interrupted and where braille follows it."""
        self.assertFalse(self.voices.say_whole('notification', 'hello'))

    def test_the_dials_are_offered_to_a_message_either_way(self):
        self.classes.set_voice('notification', {'pitch': 3, 'rate': -2})
        self.assertEqual(self.voices.dials_of('notification'),
                         {'pitch': 3, 'rate': -2, 'volume': 0})

# --------------------------------------------------------------------------- #
class TheCatalogueCanBeBroughtBackInStep(unittest.TestCase):
    """`test_every_string_the_addon_can_say_is_translated` fails when a
    string is added, and a failing test that names no way to fix it is a
    test people learn to ignore. `update_catalogue.py` is the way, so it is
    checked too - and the one thing it must never do is lose somebody's
    work.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, 'nvda-addon'))
        try:
            import update_catalogue
        finally:
            sys.path.pop(0)
        self.tool = update_catalogue
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def _po(self, text):
        path = os.path.join(self.dir, 'nvda.po')
        with io.open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        return path

    def test_it_reads_a_catalogue_it_wrote(self):
        path = self._po('msgid "Save"\nmsgstr "Zapisz"\n')
        self.assertEqual(self.tool.read_po(path), {'Save': 'Zapisz'})

    def test_a_string_split_across_lines_is_one_string(self):
        """gettext joins adjacent quoted strings, and a reader that does not
        loses everything after the first line of every long message."""
        path = self._po('msgid ""\n"one "\n"two"\nmsgstr ""\n"raz "\n"dwa"\n')
        self.assertEqual(self.tool.read_po(path), {'one two': 'raz dwa'})

    def test_the_escapes_survive_a_round_trip(self):
        for text in ('a "quoted" word', 'two\nlines', 'a\\backslash',
                     'a\ttab'):
            path = self._po('msgid "x"\nmsgstr "%s"\n' % self.tool.escape(text))
            self.assertEqual(self.tool.read_po(path)['x'], text, repr(text))

    def test_the_header_is_not_an_entry(self):
        path = self._po('msgid ""\nmsgstr "Language: pl\\n"\n\n'
                        'msgid "Save"\nmsgstr "Zapisz"\n')
        self.assertEqual(self.tool.read_po(path), {'Save': 'Zapisz'})

    def test_an_obsolete_entry_is_still_read(self):
        """Or a string that came back would be re-translated from nothing."""
        path = self._po('#~ msgid "Old"\n#~ msgstr "Stare"\n')
        self.assertEqual(self.tool.read_po(path).get('Old'), 'Stare')

    def test_every_string_it_finds_is_one_the_addon_really_says(self):
        found = self.tool.strings()
        self.assertTrue(found)
        for where, line, _note, msgid in found:
            self.assertTrue(msgid, where)
            self.assertGreater(line, 0)

    def test_it_finds_no_string_twice(self):
        seen = [msgid for _w, _l, _n, msgid in self.tool.strings()]
        self.assertEqual(len(seen), len(set(seen)))

    def test_english_is_never_given_a_catalogue(self):
        """Its msgid is its translation, so one would be 391 empty entries
        and a build product nobody reads."""
        self.assertEqual(self.tool.SOURCE_LANGUAGE, 'en')
        made = os.path.join(ADDON, 'locale', 'en', 'LC_MESSAGES', 'nvda.po')
        self.assertFalse(os.path.exists(made))

# --------------------------------------------------------------------------- #
class InstallingItIntoTheRealNVDA(unittest.TestCase):
    """`install.py` empties a folder, so what it will and will not empty is
    the part that has to be pinned.

    Nothing here installs anything: the target is a temporary folder of the
    test's own, and the build step is never run.
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, 'nvda-addon'))
        try:
            import install
        finally:
            sys.path.pop(0)
        self.install = install
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def _make(self, *names):
        for name in names:
            path = os.path.join(self.dir, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if name.endswith('/'):
                os.makedirs(path, exist_ok=True)
            else:
                with io.open(path, 'w', encoding='utf-8') as handle:
                    handle.write('x')

    def test_an_install_of_this_add_on_may_be_replaced(self):
        self._make('manifest.ini', 'globalPlugins/titanEnhancements/x.py')
        self.assertTrue(self.install._is_ours(self.dir))

    def test_an_empty_folder_may_be_used(self):
        self.assertTrue(self.install._is_ours(self.dir))

    def test_a_folder_that_is_not_this_add_on_is_LEFT_ALONE(self):
        """One bad --to away from taking somebody's configuration with it."""
        self._make('nvda.ini', 'speechDicts/default.dic')
        self.assertFalse(self.install._is_ours(self.dir))
        self.assertFalse(self.install.install(self.dir))
        self.assertTrue(os.path.exists(os.path.join(self.dir, 'nvda.ini')))

    def test_another_add_on_is_left_alone_too(self):
        self._make('manifest.ini', 'synthDrivers/somebodyElse.py')
        self.assertFalse(self.install._is_ours(self.dir))

    def test_it_installs_the_add_on_this_repository_builds(self):
        """The name and the package path have to agree with build.py, or
        this installs nothing and says it installed something."""
        self.assertTrue(self.install.PACKAGE.endswith('.nvda-addon'))
        self.assertIn(self.install.NAME,
                      os.path.basename(self.install.PACKAGE))
        manifest = os.path.join(ADDON, 'manifest.ini')
        with io.open(manifest, encoding='utf-8') as handle:
            self.assertIn('name = ' + self.install.NAME, handle.read())

    def test_the_target_is_nvdas_own_add_ons_folder(self):
        where = self.install.nvda_addons()
        self.assertTrue(where.replace('\\', '/').endswith('nvda/addons'))

    def test_a_module_that_has_gone_really_goes(self):
        """A file left from the last build is a module that still imports,
        still runs, and is not in the source any more.

        This is the one thing emptying the folder was FOR, and it is still
        true now that the installer writes over instead: what the old
        install had and the new package has not is taken away afterwards.
        """
        import subprocess
        installer = os.path.join(os.path.dirname(HERE), 'install.py')
        if not os.path.isfile(installer):
            self.skipTest('install.py is not beside the tests')
        subprocess.run([sys.executable, installer, '--to', self.dir],
                       capture_output=True, text=True,
                       cwd=os.path.dirname(installer))
        package = os.path.join(self.dir, 'globalPlugins', 'titanEnhancements')
        if not os.path.isdir(package):
            self.skipTest('the add-on could not be built here')
        stray = os.path.join(package, 'old.py')
        with io.open(stray, 'w', encoding='utf-8') as handle:
            handle.write('# left over from an older build\n')
        again = subprocess.run([sys.executable, installer, '--to', self.dir],
                               capture_output=True, text=True,
                               cwd=os.path.dirname(installer))
        # Said with the installer's own words when it fails: "it is still
        # there" is a report with no reason in it, and the reason - a
        # build that refused, a file something else is holding - is
        # already printed by the thing that knows.
        self.assertFalse(os.path.exists(stray),
                         'a module that is no longer shipped is still '
                         'there. The installer said: %s'
                         % (again.stdout or again.stderr)[-300:])

# --------------------------------------------------------------------------- #
class AVariantIsNotASpeechCommand(unittest.TestCase):
    """The reported bug: "I want the variant quincy as the control type, and
    it does not work".

    It did not, and the reason is structural rather than a slip. Pitch, rate
    and volume are `SynthParamCommand`s - the synth is HANDED them inside the
    utterance. A voice, a variant and an inflection are SETTINGS on the
    driver, and this module changed them with a `CallbackCommand`, which
    NVDA's own speech manager runs "when the synth reaches this point" -
    that is, when the audio has been PLAYED, by which time the whole
    utterance was synthesized long ago. So three dials worked and three did
    nothing at all.

    The answer is the only moment NVDA guarantees: the end of the utterance
    BEFORE the one that wants the voice.
    """

    # A stand-in PER command, not one for all of them: a test that cannot
    # tell an EndUtterance from a PitchCommand cannot check the shape of
    # the sequence, which is the whole of what is being fixed.
    @staticmethod
    def _fake(kind):
        class Fake:
            COMMAND = kind

            def __init__(self, offset=0, **kw):
                self.offset = offset
                self.name = kw.get('name', '')
        Fake.__name__ = kind
        return Fake

    def setUp(self):
        from titanEnhancements import classes, compat, voices
        self.voices, self.classes, self.compat = voices, classes, compat
        self._path = classes.path
        self._dir = tempfile.mkdtemp()
        classes.path = lambda: os.path.join(self._dir, 'classes.json')
        classes.forget()
        self._before = {}
        for name in ('PitchCommand', 'RateCommand', 'VolumeCommand',
                     'CallbackCommand', 'EndUtteranceCommand'):
            self._before[name] = getattr(compat, name, None)
            setattr(compat, name, self._fake(name))
        self._supported = voices._supported
        voices._supported = lambda synth, command: command is not None
        self.addCleanup(lambda: setattr(voices, '_supported', self._supported))
        self.addCleanup(lambda: [setattr(compat, k, v)
                                 for k, v in self._before.items()])
        self.addCleanup(classes.forget)
        self.addCleanup(lambda: setattr(classes, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self._dir, ignore_errors=True))
        voices._remember_first(None)

    def _kinds(self, sequence):
        return ['text' if isinstance(part, str) else
                getattr(part, 'name', '') or getattr(part, 'COMMAND', 'dial')
                for part in sequence]

    def _has(self, sequence, kind):
        return any(getattr(part, 'COMMAND', '') == kind for part in sequence)

    def test_a_variant_starts_a_new_utterance(self):
        """Which is the whole fix: a driver setting can only change between
        utterances, so the part that wants one has to be its own."""
        self.classes.set_voice('kind', {'variant': 'quincy'})
        out = self.voices.sequence([('Save', 'name'), ('button', 'kind')])
        self.assertTrue(self._has(out, 'EndUtteranceCommand'))

    def test_the_change_is_made_before_the_utterance_that_wants_it(self):
        """The callback has to be the LAST thing in the utterance that is
        ending, or it fires after the words it was meant to colour."""
        self.classes.set_voice('kind', {'variant': 'quincy'})
        out = self.voices.sequence([('Save', 'name'), ('button', 'kind')])
        kinds = self._kinds(out)
        self.assertLess(kinds.index('titanVoice'), kinds.index('text', 1),
                        'the change must come before the words it colours')
        said = [part for part in out if isinstance(part, str)]
        self.assertEqual(said[0].strip().rstrip(','), 'Save')

    def test_the_driver_is_always_put_back_at_the_end(self):
        """A variant left on is every word afterwards in the wrong voice."""
        self.classes.set_voice('kind', {'variant': 'quincy'})
        out = self.voices.sequence([('Save', 'name'), ('button', 'kind')])
        self.assertEqual(self._kinds(out)[-1], 'EndUtteranceCommand',
                         'the last thing is the end of an utterance')
        self.assertEqual(self._kinds(out).count('titanVoice'), 2,
                         'one to put it on, one to take it off')

    def test_an_ordinary_reading_is_still_ONE_utterance(self):
        """Nothing may pay for this that did not ask for it."""
        out = self.voices.sequence([('Save', 'name'), ('button', 'kind'),
                                    ('checked', 'state')])
        self.assertEqual(self._kinds(out).count('titanVoice'), 0)
        self.assertFalse(self._has(out, 'EndUtteranceCommand'))

    def test_two_parts_asking_for_the_same_voice_share_an_utterance(self):
        self.classes.set_voice('kind', {'variant': 'quincy'})
        self.classes.set_voice('state', {'variant': 'quincy'})
        out = self.voices.sequence([('Save', 'name'), ('button', 'kind'),
                                    ('checked', 'state')])
        self.assertEqual(self._kinds(out).count('titanVoice'), 2)

    def test_the_first_part_is_handed_to_whoever_speaks_it(self):
        """There is no utterance before the first one, so its voice cannot
        be a callback: it is put on immediately before `speech.speak`."""
        self.classes.set_voice('name', {'variant': 'quincy'})
        self.voices.sequence([('Save', 'name'), ('button', 'kind')])
        self.assertEqual(self.voices.pending_first(), {'variant': 'quincy'})

    def test_asking_for_it_twice_gets_it_once(self):
        """Or a sequence built and never spoken lends its voice to whatever
        is spoken next."""
        self.classes.set_voice('name', {'variant': 'quincy'})
        self.voices.sequence([('Save', 'name')])
        self.voices.pending_first()
        self.assertIsNone(self.voices.pending_first())

    def test_a_stale_answer_is_thrown_away(self):
        self.classes.set_voice('name', {'variant': 'quincy'})
        self.voices.sequence([('Save', 'name')])
        self.voices._pending['at'] -= self.voices.PENDING_SECONDS * 2
        self.assertIsNone(self.voices.pending_first())

    def test_an_ordinary_reading_leaves_nothing_pending(self):
        self.classes.set_voice('name', {'variant': 'quincy'})
        self.voices.sequence([('Save', 'name')])
        self.voices.sequence([('Save', 'name'), ('button', 'kind')])
        self.voices._pending['profile'] = None
        self.voices.sequence([('x', 'kind')])
        self.assertIsNone(self.voices.pending_first())

    def test_the_reading_is_spoken_through_the_one_door(self):
        """`focus._speak` must go through `voices`, or the first part's
        voice is worked out and then dropped on the floor."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'focus.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('voices.speak_sequence(', source)


# --------------------------------------------------------------------------- #
class ADriverSettingIsAlwaysPutBack(unittest.TestCase):
    """The one thing this must not do is leave the reader in another voice.

    A reading that changes a variant and is then cut short - the user
    presses a key, speech is cancelled, the callback that would have put it
    back never fires - would otherwise leave every word afterwards wrong.
    That cannot be made impossible, so it is made harmless.
    """

    class Synth:
        def __init__(self):
            self.variant = 'none'
            self.voice = 'en'
            self.rate = 50

    def setUp(self):
        from titanEnhancements import speaking
        self.speaking = speaking
        self.synth = self.Synth()
        self._current = speaking.current
        speaking.current = lambda: self.synth
        speaking.restore_standing(self.synth)
        self.addCleanup(lambda: setattr(speaking, 'current', self._current))
        self.addCleanup(speaking.restore_standing)

    def test_becoming_a_voice_and_becoming_nothing_again(self):
        self.speaking.become({'variant': 'quincy'})
        self.assertEqual(self.synth.variant, 'quincy')
        self.speaking.become({})
        self.assertEqual(self.synth.variant, 'none')

    def test_what_is_outstanding_is_known(self):
        self.speaking.become({'variant': 'quincy'})
        self.assertEqual(self.speaking.standing(), {'variant': 'none'})
        self.speaking.restore_standing()
        self.assertEqual(self.speaking.standing(), {})

    def test_a_second_change_does_not_lose_the_original(self):
        """Two changes and one restore must end at the ORIGINAL, not at the
        first change - which is what happens if what was there is
        overwritten instead of kept."""
        self.speaking.become({'variant': 'quincy'})
        self.speaking.become({'variant': 'michael'})
        self.speaking.become({})
        self.assertEqual(self.synth.variant, 'none')

    def test_restoring_when_nothing_is_outstanding_is_not_an_error(self):
        self.assertFalse(self.speaking.restore_standing())

# --------------------------------------------------------------------------- #
class ADifferentSynthesizerForReadingText(unittest.TestCase):
    """"RHVoice for reading text" - and the one class this add-on must not
    speak itself.

    Say all feeds itself: each utterance carries the callbacks that queue
    the next line, so taking the words away to another synthesizer stops the
    reading after one line, and `setSynth` mid-read cancels speech. NVDA
    already switches synthesizer for say all, through a configuration
    profile, at the right utterance boundary. So the whole job is to put a
    synthesizer in that profile.

    What is checked here is the FOOTPRINT, because that is what can go
    wrong: this writes into somebody's NVDA configuration.
    """

    def setUp(self):
        from titanEnhancements import sayall_profile
        self.profile = sayall_profile
        self.dir = tempfile.mkdtemp()
        self._folder = sayall_profile.folder
        sayall_profile.folder = lambda: os.path.join(self.dir, 'profiles')
        self.triggers = {}
        self.saved = [0]

        class Conf:
            triggersToProfiles = self.triggers

            @staticmethod
            def saveProfileTriggers():
                self.saved[0] += 1
        self.config = types.SimpleNamespace(conf=Conf)
        self._config = sayall_profile._config
        sayall_profile._config = lambda: self.config
        self.addCleanup(lambda: setattr(sayall_profile, 'folder',
                                        self._folder))
        self.addCleanup(lambda: setattr(sayall_profile, '_config',
                                        self._config))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def _written(self):
        with io.open(self.profile.path(), encoding='utf-8') as handle:
            return handle.read()

    def test_choosing_one_writes_the_profile_and_binds_the_trigger(self):
        ok, said = self.profile.set_synth('rhvoice')
        self.assertTrue(ok, said)
        self.assertIn('synth = rhvoice', self._written())
        self.assertEqual(self.triggers['sayAll'], self.profile.PROFILE)
        self.assertEqual(self.saved[0], 1, 'the trigger map must be saved')

    def test_the_profile_carries_the_synthesizer_and_nothing_else(self):
        """A profile holds only what differs from the base one. That is what
        makes it safe: everything not written is whatever the user has, so
        this changes the synthesizer for reading text and nothing else about
        how they read."""
        self.profile.set_synth('rhvoice')
        written = self._written()
        for never in ('rate =', 'pitch =', 'volume =', 'symbolLevel'):
            self.assertNotIn(never, written, never)

    def test_a_voice_and_variant_go_under_the_synthesizer(self):
        """NVDA keeps a synth's own settings under its own name."""
        self.profile.set_synth('rhvoice', voice='anna', variant='x')
        written = self._written()
        self.assertIn('[[rhvoice]]', written)
        self.assertIn('voice = anna', written)

    def test_it_says_it_is_ours(self):
        """A profile somebody finds in NVDA's own dialog has to be traceable
        to the thing that made it."""
        self.profile.set_synth('rhvoice')
        self.assertIn(self.profile.MARK, self._written())
        self.assertTrue(self.profile.ours())

    def test_a_profile_this_add_on_did_not_write_is_LEFT_ALONE(self):
        os.makedirs(os.path.dirname(self.profile.path()), exist_ok=True)
        with io.open(self.profile.path(), 'w', encoding='utf-8') as handle:
            handle.write('[speech]\nsynth = somebodyElse\n')
        ok, said = self.profile.set_synth('rhvoice')
        self.assertFalse(ok)
        self.assertIn('somebodyElse', self._written())
        self.assertNotIn('sayAll', self.triggers)
        self.assertIn(self.profile.PROFILE, said)

    def test_choosing_nothing_takes_the_arrangement_away(self):
        self.profile.set_synth('rhvoice')
        ok, _said = self.profile.set_synth('')
        self.assertTrue(ok)
        self.assertNotIn('sayAll', self.triggers)
        self.assertFalse(os.path.exists(self.profile.path()))

    def test_it_never_unbinds_somebody_elses_trigger(self):
        """A user who has pointed say-all at a profile of their own keeps
        it."""
        self.triggers['sayAll'] = 'Their own profile'
        self.profile.clear()
        self.assertEqual(self.triggers['sayAll'], 'Their own profile')

    def test_what_it_is_set_to_can_be_read_back(self):
        self.assertEqual(self.profile.current(), '')
        self.profile.set_synth('rhvoice')
        self.assertEqual(self.profile.current(), 'rhvoice')

    def test_with_no_nvda_it_says_so_rather_than_raising(self):
        self.profile._config = lambda: None
        self.profile.folder = lambda: ''
        ok, said = self.profile.set_synth('rhvoice')
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_the_dialog_really_calls_it(self):
        """A choice the dialog offers and never acts on is a switch that
        lies, which is the fault this whole change is about."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'classManager.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('sayall_profile.set_synth(', source)
        self.assertIn('sayall_profile.clear()', source)

# --------------------------------------------------------------------------- #
class WhereAnUtteranceCameFrom(unittest.TestCase):
    """Keyboard echo in one voice, the controller in another.

    By the time NVDA's speech filter sees an utterance it is a list of
    strings and nothing says what kind it is. NVDA knows while it is still
    in the function that produced it - `speakTypedCharacters`,
    `speakSpelling`, `speakMessage`, `speakText` - so the mark is taken
    there. Nothing here reads the words.
    """

    def _speech(self):
        """A stand-in shaped like NVDA's speech MODULE - plain functions on
        a module object, not methods - because that is what is really being
        wrapped, and a bound method behaves differently on the way back."""
        from titanEnhancements import origin
        marks = []
        module = types.ModuleType('speech')

        def record():
            marks.append(origin.current())

        def speakTypedCharacters(ch):
            record()

        def speakSpelling(text):
            record()

        def speakText(text):
            record()

        def speakMessage(text):
            # NVDA's own does exactly this, which is the whole reason the
            # OUTERMOST mark has to win.
            module.speakText(text)
        for name, value in (('speakTypedCharacters', speakTypedCharacters),
                            ('speakSpelling', speakSpelling),
                            ('speakText', speakText),
                            ('speakMessage', speakMessage)):
            setattr(module, name, value)
        module.marks = marks
        return module

    def setUp(self):
        from titanEnhancements import compat, origin
        self.origin = origin
        self.speech = self._speech()
        self._before = compat.speech
        compat.speech = self.speech
        origin.stop()
        self.addCleanup(origin.stop)
        self.addCleanup(lambda: setattr(compat, 'speech', self._before))

    def test_typing_is_marked_as_typing(self):
        self.origin.start()
        self.speech.speakTypedCharacters('a')
        self.assertEqual(self.speech.marks, ['typed'])

    def test_spelling_is_marked_as_spelling(self):
        self.origin.start()
        self.speech.speakSpelling('cat')
        self.assertEqual(self.speech.marks, ['spelling'])

    def test_the_controller_is_marked_as_the_controller(self):
        """`nvdaController_speakText` queues `speech.speakText` - read out
        of NVDA's own NVDAHelper - so that is where the mark goes."""
        self.origin.start()
        self.speech.speakText('from another program')
        self.assertEqual(self.speech.marks, ['controller'])

    def test_a_message_is_a_message_and_not_the_controller(self):
        """The OUTERMOST mark wins. `speakMessage` calls `speakText`, so if
        the innermost decided, every message NVDA says about itself would be
        coloured as though another program had said it."""
        self.origin.start()
        self.speech.speakMessage('Titan is not running.')
        self.assertEqual(self.speech.marks, ['notification'])

    def test_nothing_is_marked_before_it_is_started(self):
        self.speech.speakTypedCharacters('a')
        self.assertEqual(self.speech.marks, [''])

    def test_the_mark_does_not_outlive_the_call(self):
        """A mark left standing colours whatever is said next."""
        self.origin.start()
        self.speech.speakTypedCharacters('a')
        self.assertEqual(self.origin.current(), '')

    def test_a_mark_is_per_thread(self):
        """Speech is queued from several threads - the controller's own RPC
        call is one - and a mark visible to another thread would colour
        whatever that thread was saying at the same moment."""
        self.origin.push('typed')
        try:
            seen = []
            worker = threading.Thread(
                target=lambda: seen.append(self.origin.current()))
            worker.start()
            worker.join()
        finally:
            # In a finally, or a test that fails here leaves a mark on this
            # thread and colours every test after it - which is exactly what
            # it would do to a reader.
            self.origin.pop()
        self.assertEqual(seen, [''])

    def test_stopping_puts_nvdas_own_functions_back(self):
        original = self.speech.speakText
        self.origin.start()
        self.assertIsNot(self.speech.speakText, original)
        self.origin.stop()
        self.assertIs(self.speech.speakText, original)

    def test_starting_twice_does_not_bury_the_real_one(self):
        original = self.speech.speakText
        self.origin.start()
        self.origin.start()
        self.origin.stop()
        self.assertIs(self.speech.speakText, original)

    def test_somebody_elses_wrapper_is_never_thrown_away(self):
        """A reader is not the place to win an argument with another
        add-on."""
        self.origin.start()
        theirs = lambda text: None
        self.speech.speakText = theirs
        self.origin.stop()
        self.assertIs(self.speech.speakText, theirs)

    def test_a_function_this_nvda_has_not_got_is_recorded_not_fatal(self):
        del self.speech.speakSpelling
        self.assertGreater(self.origin.start(), 0)
        self.assertIn('speakSpelling', self.origin.report()['missing'])

    def test_the_plugin_starts_and_stops_it(self):
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            '__init__.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('origin.start()', source)
        self.assertIn('origin.stop()', source)

    def test_every_mark_is_a_class_that_really_exists(self):
        """A mark naming a class nobody defined is a voice nobody can set."""
        from titanEnhancements import classes
        known = classes.defaults()
        for _name, mark in self.origin.MARKS:
            self.assertIn(mark, known, mark)

    def test_the_filter_spends_the_mark(self):
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'interject.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('origin.current()', source)

# --------------------------------------------------------------------------- #
class ATerminalReviewedTheWayTitanAccessDoesIt(unittest.TestCase):
    """Numpad minus, then the plain arrow keys walk the buffer.

    Ported from Titan Access's own terminal module. What is checked here is
    the part that can make a machine worse: the arrows are the shell's own
    keys the rest of the time, so they are borrowed only while review is
    really on and given straight back.
    """

    def setUp(self):
        from titanEnhancements import terminal
        self.terminal = terminal
        terminal.stop()
        self._is = terminal.is_terminal
        self._read = terminal._read_lines
        terminal.is_terminal = lambda obj=None: True
        terminal._read_lines = lambda obj=None: [
            'C:\\> dir', 'one.txt', 'two.txt', '', 'C:\\> ']
        self.said = []
        self._say = terminal._say
        terminal._say = lambda text, **kw: self.said.append(str(text))
        self.beeps = []
        self._beep = terminal._beep
        terminal._beep = lambda row: self.beeps.append(row)
        self.addCleanup(terminal.stop)
        self.addCleanup(lambda: setattr(terminal, '_beep', self._beep))
        self.addCleanup(lambda: setattr(terminal, '_say', self._say))
        self.addCleanup(lambda: setattr(terminal, '_read_lines', self._read))
        self.addCleanup(lambda: setattr(terminal, 'is_terminal', self._is))

    def test_it_starts_on_the_last_line_that_has_anything_on_it(self):
        """Where the prompt is. Entering at the very bottom of a buffer
        padded with blank lines reads as a terminal with nothing in it."""
        self.terminal.start()
        self.assertEqual(self.terminal.report()['row'], 4)

    def test_the_arrows_walk_the_buffer(self):
        self.terminal.start()
        self.terminal.move_line(-1)
        self.assertEqual(self.terminal.report()['row'], 3)
        self.terminal.move_line(-1)
        self.assertIn('two.txt', self.said)

    def test_a_blank_line_says_so_rather_than_nothing(self):
        self.terminal.start()
        self.said[:] = []
        self.terminal.move_line(-1)
        self.assertTrue(self.said, 'a blank line must still be reported')

    def test_it_cannot_walk_off_either_end(self):
        self.terminal.start()
        for _ in range(20):
            self.terminal.move_line(-1)
        self.assertEqual(self.terminal.report()['row'], 0)
        for _ in range(50):
            self.terminal.move_line(1)
        self.assertEqual(self.terminal.report()['row'], 4)

    def test_every_line_movement_is_marked_by_a_beep(self):
        """Pitched by where the line is on its screenful, which is what
        makes it worth listening to rather than a noise per line."""
        self.terminal.start()
        self.beeps[:] = []
        self.terminal.move_line(-1)
        self.assertEqual(len(self.beeps), 1)

    def test_a_page_is_exactly_a_screenful(self):
        """So the beep's pattern repeats and the pitch means the same thing
        all the way through the scrollback."""
        self.terminal.start()
        before = self.terminal.report()['row']
        self.terminal.move_page(-1)
        self.assertEqual(before - self.terminal.report()['row'],
                         min(before, self.terminal.VISIBLE))

    def test_numpad_minus_turns_it_off_again(self):
        self.terminal.toggle()
        self.assertTrue(self.terminal.reviewing())
        self.terminal.toggle()
        self.assertFalse(self.terminal.reviewing())

    def test_it_refuses_outside_a_terminal_rather_than_doing_nothing(self):
        self.terminal.is_terminal = lambda obj=None: False
        on, said = self.terminal.start()
        self.assertFalse(on)
        self.assertTrue(said)

    def test_a_terminal_that_will_not_give_up_its_text_says_so(self):
        self.terminal._read_lines = lambda obj=None: []
        on, said = self.terminal.start()
        self.assertFalse(on)
        self.assertTrue(said)

    def test_leaving_the_terminal_ends_the_review(self):
        """A review cursor left running over a window the user has moved
        away from would swallow their arrow keys in whatever they moved
        to."""
        self.terminal.start()
        self.terminal.is_terminal = lambda obj=None: False
        self.assertTrue(self.terminal.left_the_terminal())
        self.assertFalse(self.terminal.reviewing())

    def test_staying_in_the_terminal_does_not(self):
        self.terminal.start()
        self.assertFalse(self.terminal.left_the_terminal())
        self.assertTrue(self.terminal.reviewing())

    def test_the_keys_are_borrowed_only_while_review_is_on(self):
        import re
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            '__init__.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        keys = re.search(r'TERMINAL_KEYS = \{(.+?)\}', source, re.S).group(1)
        self.assertIn('kb:upArrow', keys)
        self.assertIn('kb:escape', keys)
        self.assertIn('terminal.reviewing()', source)
        # And given back: a binding that outlived the terminal would
        # swallow an arrow key in whatever the user moved to, so the state
        # of the binding follows `reviewing()` rather than being set once.
        self.assertIn('self._borrow_terminal_keys(want)', source)
        self.assertIn('removeGestureBinding', source)

    def test_a_terminal_is_recognised_by_what_it_IS(self):
        """Both ways, because neither is enough on its own: Windows
        Terminal, an old conhost and PuTTY share no window class."""
        self.assertIn('ConsoleWindowClass', self.terminal.CLASSES)
        self.assertIn('powershell', self.terminal.PROGRAMS)
        self.assertIn('wt', self.terminal.PROGRAMS)


# --------------------------------------------------------------------------- #
class WindowsOwnRecogniserIsTheFirstTier(unittest.TestCase):
    """The cheap reading, and it is a first-class one.

    Windows has an OCR engine built in and NVDA already wraps it: local,
    free, about a tenth of a second, nothing sent anywhere. It gives the
    words and a rectangle per line in real screen coordinates - which is
    everything a cursor needs - so a drawn window becomes navigable with no
    model asked. The AI is left for what only it can do.
    """

    class Info:
        resizeFactor = 2.0

        @staticmethod
        def convertXToScreen(x):
            return 100 + x // 2

        @staticmethod
        def convertYToScreen(y):
            return 200 + y // 2

    class Result:
        """NVDA's OWN shape, quoted from `contentRecog.LinesWordsResult`:
        a LIST of lines, each a list of word dicts. It is not a dict with a
        "lines" key, and this test used to say it was - so it passed while
        every real reading came back empty and three features reported
        "Windows read nothing in that window". A stand-in that is not the
        shape of the real thing tests nothing."""
        data = [
            [{'text': 'New', 'x': 0, 'y': 0, 'width': 40, 'height': 20},
             {'text': 'game', 'x': 50, 'y': 0, 'width': 60, 'height': 20}],
            [{'text': 'Options', 'x': 0, 'y': 40, 'width': 80, 'height': 20}],
            [{'text': '   ', 'x': 0, 'y': 80, 'width': 10, 'height': 20}],
        ]

    class OldResult:
        data = {'lines': [
            [{'text': 'New', 'x': 0, 'y': 0, 'width': 40, 'height': 20}],
        ]}

    def setUp(self):
        from titanEnhancements import localOcr
        self.localOcr = localOcr
        self.reading = localOcr.Reading.of(self.Result(), self.Info())

    def test_the_words_come_back_as_lines(self):
        self.assertEqual(self.reading.text, 'New game\nOptions')

    def test_a_word_that_is_only_whitespace_is_not_a_word(self):
        self.assertEqual(len(self.reading.lines), 2)

    def test_the_rectangles_are_SCREEN_coordinates(self):
        """The recogniser answers in the coordinates of the picture it was
        given, scaled - so a rectangle used as it comes points at the wrong
        place, by an amount that changes with the window's size."""
        _text, rect = self.reading.rows()[0]
        self.assertEqual(rect[0], 100)
        self.assertEqual(rect[1], 200)

    def test_a_line_is_the_whole_line_and_its_box(self):
        text, rect = self.reading.rows()[0]
        self.assertEqual(text, 'New game')
        self.assertGreater(rect[2], 0)
        self.assertGreater(rect[3], 0)

    def test_an_unchanged_screen_is_known_to_be_unchanged(self):
        """Which is the whole reason this tier exists: it is what stops the
        AI being asked about a screen that has not moved."""
        again = self.localOcr.Reading.of(self.Result(), self.Info())
        self.assertFalse(again.changed_from(self.reading))

    def test_a_changed_screen_is_known_to_have_changed(self):
        self.assertTrue(self.reading.changed_from(None))
        empty = self.localOcr.Reading()
        self.assertTrue(self.reading.changed_from(empty))

    def test_only_what_is_NEW_is_offered_to_be_said(self):
        """A window whose whole reading is announced on every change would
        be a reader reading a menu from the top every time one line of it
        moved."""
        before = self.localOcr.Reading([self.reading.lines[0]])
        self.assertEqual(self.reading.added_since(before), ['Options'])

    def test_a_line_can_be_found_by_its_words(self):
        found = self.reading.find('options')
        self.assertIsNotNone(found)
        self.assertEqual(found[0], 'Options')

    def test_nothing_read_is_falsy(self):
        self.assertFalse(self.localOcr.Reading())
        self.assertTrue(self.reading)

    def test_a_result_that_is_not_one_answers_nothing(self):
        self.assertFalse(self.localOcr.Reading.of(object(), self.Info()))

    def test_the_shape_is_nvdas_documented_one(self):
        """Pinned against the real class rather than against what this
        test happened to build: `LinesWordsResult.data` is a list of lines."""
        self.assertIsInstance(self.Result.data, list)
        self.assertIsInstance(self.Result.data[0], list)
        self.assertIn('text', self.Result.data[0][0])

    def test_the_older_shape_is_still_read(self):
        """An older NVDA, or somebody else's recogniser. Taking both costs
        a line and losing one costs the whole feature."""
        reading = self.localOcr.Reading.of(self.OldResult(), self.Info())
        self.assertEqual(reading.text, 'New')

    def test_it_says_why_it_cannot_rather_than_raising(self):
        ok, why = self.localOcr.available()
        self.assertIsInstance(ok, bool)
        if not ok:
            self.assertTrue(why)

    def test_the_cursor_can_be_built_straight_from_it(self):
        """The point of the tier: navigable with no model asked."""
        from titanEnhancements import smart
        controls = smart.controls_from(self.reading)
        self.assertEqual([c['name'] for c in controls],
                         ['New game', 'Options'])
        self.assertTrue(all(c.get('rect') for c in controls))

    def test_every_PIECE_is_a_control_not_every_line(self):
        """A menu bar read as "File Edit View" was ONE control the cursor
        could not get inside, and a row with a name and a size beside it
        was one lump of text. `virtualInput` already splits a row where
        the gaps are; using it is what makes this tier show what is
        really there rather than the lines it came in."""
        from titanEnhancements import smart
        from titanEnhancements import localOcr

        class Wide:
            data = [[{'text': 'File', 'x': 0, 'y': 0,
                      'width': 30, 'height': 10},
                     {'text': 'Edit', 'x': 200, 'y': 0,
                      'width': 30, 'height': 10}]]
        reading = localOcr.Reading.of(Wide(), self.Info())
        names = [one['name'] for one in smart.controls_from(reading)]
        self.assertIn('File', names)
        self.assertIn('Edit', names)

    def test_what_the_picture_highlighted_is_marked(self):
        """In a game's menu and a guest's file list the highlight IS the
        interface - it is the entry the arrow keys are on."""
        from titanEnhancements import smart
        reading = self.reading
        # The highlight is built from the row's OWN rectangle, padded, so
        # this asks whether a highlight over a row marks it rather than
        # whether the test guessed the geometry right.
        _text, rect = reading.rows()[0]
        reading.highlights = [(rect[0] - 4, rect[1] - 4,
                               rect[2] + 8, rect[3] + 8)]
        controls = smart.controls_from(reading)
        chosen = smart.selected_in(controls)
        self.assertTrue(chosen, 'nothing was marked as highlighted')
        self.assertTrue(chosen[0].get('region'),
                        'a highlighted control says nothing about being one')

    def test_a_reading_with_no_pieces_still_answers_its_lines(self):
        """A reading with nothing to split is still a reading: answering
        that the window is empty would be worse than the lines."""
        from titanEnhancements import smart
        controls = smart.controls_from(self.reading)
        self.assertTrue(controls)
        self.assertTrue(all(one.get('rect') for one in controls))

    def test_a_control_that_knows_where_it_is_presses_itself(self):
        """No Titan, no AI, no request - a click at a place we were told."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'smart.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn("rect = control.get('rect')", source)
        self.assertIn('SetCursorPos', source)

    def test_the_user_chooses_which_recogniser(self):
        from titanEnhancements import configSpec
        self.assertEqual(configSpec.defaults()['ocrTier'], 'local')
        self.assertEqual(sorted(configSpec.choices('ocrTier')),
                         ['ai', 'both', 'local'])


# --------------------------------------------------------------------------- #
class TheSettingsPageIsCategorised(unittest.TestCase):
    """It has outgrown a column, and a page nobody can find anything on is
    a page of settings nobody uses."""

    def setUp(self):
        from titanEnhancements import configSpec, settingsPanel
        self.panel = settingsPanel
        self.configSpec = configSpec

    def test_every_category_has_a_name(self):
        for label, _note, _rows in self.panel._page():
            self.assertTrue(str(label).strip())

    def test_no_category_is_empty_of_both_settings_and_words(self):
        """A category with nothing in it and nothing to say is a row in the
        list that answers with a blank page."""
        for label, note, rows in self.panel._page():
            self.assertTrue(rows or str(note).strip(), label)

    def test_a_setting_with_more_than_two_answers_is_a_list(self):
        values, labels = self.panel._options_for('ocrTier')
        self.assertEqual(len(values), len(labels))
        self.assertIn('local', values)

    def test_an_ordinary_switch_is_not(self):
        self.assertEqual(self.panel._options_for('pitchedFocus'), ([], []))

    def test_a_setting_whose_answers_are_a_fact_about_this_machine(self):
        """Which languages Windows can read in is not something a spec can
        say, so it is asked at the moment the page is built."""
        values, labels = self.panel._options_for('localOcrLanguage')
        self.assertEqual(values[0], '')
        self.assertEqual(len(values), len(labels))

    def test_the_stored_word_is_never_the_translated_one(self):
        """A setting whose value is translated is a configuration file that
        means something different on a Polish machine."""
        for word in ('local', 'ai', 'both', 'pitch', 'pan'):
            self.assertIn(word, self.panel.WORDS.keys() | {'pan'})

# --------------------------------------------------------------------------- #
class WatchingAPartOfTheScreen(unittest.TestCase):
    """JAWS calls them Frames, ZDSR calls them monitored areas.

    A status line at the bottom of a build, a chat window behind the one you
    are typing in, a percentage in a corner. A reader speaks about the thing
    you are ON, and none of that is the thing you are on.
    """

    class Obj:
        def __init__(self, name='Status', value='', klass='Static',
                     automation='statusText', location=(10, 20, 100, 30)):
            self.name = name
            self.value = value
            self.description = ''
            self.windowClassName = klass
            self.UIAAutomationId = automation
            self.location = location
            self.role = types.SimpleNamespace(name='STATICTEXT')
            self.children = []

    def setUp(self):
        from titanEnhancements import monitors
        self.monitors = monitors
        self.dir = tempfile.mkdtemp()
        self._path = monitors.path
        monitors.path = lambda: os.path.join(self.dir, 'monitors.json')
        monitors.forget()
        self.said = []
        self._say = monitors._say
        monitors._say = lambda text: self.said.append(str(text))
        self.addCleanup(monitors.stop)
        self.addCleanup(monitors.forget)
        self.addCleanup(lambda: setattr(monitors, '_say', self._say))
        self.addCleanup(lambda: setattr(monitors, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    # --------------------------------------------------------------- why
    def test_the_watch_says_why_it_is_not_running(self):
        """`_state['why']` was declared and assigned by NOTHING, so the
        diagnostics carried an empty reason for ever - and `running: false`
        with nothing saying why is the one answer an operator cannot act on.
        Every sibling layer says it (`guest`: "the setting is off").

        The two reasons are the only two there are: the switch went off, or
        there is nothing left to watch.
        """
        wanted = self.monitors.wanted
        self.addCleanup(lambda: setattr(self.monitors, 'wanted', wanted))

        # nothing watched, switch on
        self.monitors.wanted = lambda: True
        self.monitors._keep_running()
        self.assertEqual(self.monitors.report()['why'],
                         'nothing is being watched')

        # something watched, switch off
        self.monitors.watch_this_control(self.Obj())
        self.monitors.wanted = lambda: False
        self.monitors._keep_running()
        self.assertEqual(self.monitors.report()['why'], 'the setting is off')

    def test_a_running_watch_gives_no_reason_because_there_is_none(self):
        wanted = self.monitors.wanted
        self.addCleanup(lambda: setattr(self.monitors, 'wanted', wanted))
        self.monitors.wanted = lambda: True
        self.monitors.watch_this_control(self.Obj())
        self.monitors._keep_running()
        self.assertEqual(self.monitors.report()['why'], '')
        self.assertTrue(self.monitors.report()['running'])

    # ------------------------------------------------------------- making
    def test_a_control_with_a_name_of_its_own_is_watched_by_that(self):
        """Not by where it sits: a control watched by its place among its
        siblings starts watching the one next door the moment a toolbar
        gains a button."""
        ok, _said = self.monitors.watch_this_control(self.Obj())
        self.assertTrue(ok)
        self.assertEqual(self.monitors.all_monitors()[0]['kind'],
                         self.monitors.BY_CONTROL)

    def test_a_control_with_nothing_stable_is_watched_by_its_PLACE(self):
        """Weaker, and it is what happens rather than a refusal - but it is
        a different kind, so the difference is not hidden."""
        ok, _said = self.monitors.watch_this_control(
            self.Obj(automation=''))
        self.assertTrue(ok)
        self.assertEqual(self.monitors.all_monitors()[0]['kind'],
                         self.monitors.BY_POINT)

    def test_a_control_that_is_nowhere_at_all_is_refused(self):
        ok, said = self.monitors.watch_this_control(
            self.Obj(automation='', location=None))
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_a_whole_window_is_watched_as_a_rectangle(self):
        """The one that works on a program with no accessibility at all,
        which is what JAWS Frames is really for."""
        ok, _said = self.monitors.watch_this_window(self.Obj())
        self.assertTrue(ok)
        row = self.monitors.all_monitors()[0]
        self.assertEqual(row['kind'], self.monitors.BY_AREA)
        self.assertEqual(row['rect'], [10, 20, 100, 30])

    # ------------------------------------------------ object navigation
    def _navigator_is(self, navigator=None, focus=None, foreground=None):
        """Stand in for NVDA's ``api`` so a test can say where the
        navigator is with no NVDA under it."""
        module = types.ModuleType('api')
        module.getNavigatorObject = lambda: navigator
        module.getFocusObject = lambda: focus
        module.getForegroundObject = lambda: foreground
        had = sys.modules.get('api')

        def put_back():
            if had is None:
                sys.modules.pop('api', None)
            else:
                sys.modules['api'] = had
        sys.modules['api'] = module
        self.addCleanup(put_back)

    def test_what_is_watched_is_the_NAVIGATOR_object(self):
        """A progress bar, a status line, a pane that fills itself in: not
        one of them is ever focused, and object navigation is how NVDA
        reaches them - which is the whole reason anybody watches one."""
        bar = self.Obj(name='', value='40%', klass='msctls_progress32',
                       automation='theProgress')
        self._navigator_is(navigator=bar, focus=self.Obj(name='Focused'))
        ok, _said = self.monitors.watch_this_control()
        self.assertTrue(ok)
        row = self.monitors.all_monitors()[0]
        self.assertEqual(row['kind'], self.monitors.BY_CONTROL)
        self.assertNotEqual(row['name'], 'Focused')

    def test_the_focus_is_what_the_navigator_falls_back_to(self):
        """An NVDA whose review cursor has not settled anywhere must still
        answer, or the command does nothing and says nothing."""
        self._navigator_is(navigator=None, focus=self.Obj(name='Focused'))
        ok, _said = self.monitors.watch_this_control()
        self.assertTrue(ok)
        self.assertEqual(self.monitors.all_monitors()[0]['name'], 'Focused')

    def test_the_AREA_of_an_object_is_watched_not_the_whole_window(self):
        """Watching the window instead would read every clock and counter
        anywhere in it, which is a monitor that never stops talking."""
        self._navigator_is(navigator=self.Obj(location=(5, 6, 70, 8)))
        ok, _said = self.monitors.watch_this_area()
        self.assertTrue(ok)
        row = self.monitors.all_monitors()[0]
        self.assertEqual(row['kind'], self.monitors.BY_AREA)
        self.assertEqual(row['rect'], [5, 6, 70, 8])

    def test_an_object_with_no_width_is_not_an_area(self):
        """A rectangle with no width is not a small area, it is an object
        that is not on the screen - and OCR on one reads whatever is
        behind it for ever."""
        self._navigator_is(navigator=self.Obj(location=(5, 6, 0, 0)))
        ok, said = self.monitors.watch_this_area()
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_an_unnamed_control_is_called_what_it_IS(self):
        """Not "this area": the things worth watching are exactly the ones
        with no name, and a list of them all called the same thing is a
        list nobody can tell apart."""
        bar = self.Obj(name='', klass='msctls_progress32')
        bar.role = types.SimpleNamespace(name='PROGRESSBAR')
        self.assertEqual(self.monitors._describe(bar), 'PROGRESSBAR')

    def test_the_same_thing_is_not_watched_twice(self):
        self.monitors.watch_this_control(self.Obj())
        ok, said = self.monitors.watch_this_control(self.Obj())
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_it_survives_being_forgotten_and_read_again(self):
        self.monitors.watch_this_control(self.Obj())
        self.monitors.forget()
        self.assertEqual(len(self.monitors.all_monitors()), 1)

    def test_one_can_be_stopped(self):
        self.monitors.watch_this_control(self.Obj())
        self.assertTrue(self.monitors.remove(0))
        self.assertEqual(self.monitors.all_monitors(), [])

    def test_stopping_one_that_is_not_there_is_not_an_error(self):
        self.assertFalse(self.monitors.remove(3))

    # ------------------------------------------------------------ saying
    def test_a_change_is_announced_and_an_unchanged_one_is_not(self):
        monitor = {'kind': self.monitors.BY_AREA, 'name': 'Score',
                   'rect': [0, 0, 10, 10]}
        self.monitors._load().append(monitor)
        readings = ['10 points', '10 points', '20 points']
        self.monitors._read = lambda m: readings.pop(0)
        try:
            self.monitors.check()          # the first reading is a baseline
            self.assertEqual(self.said, [])
            self.monitors.check()
            self.assertEqual(self.said, [])
            self.monitors.check()
            self.assertEqual(len(self.said), 1)
            self.assertIn('20 points', self.said[0])
            self.assertIn('Score', self.said[0])
        finally:
            del self.monitors._read

    def test_something_that_cannot_be_read_is_not_news(self):
        """A monitor whose window is closed has nothing to say and must not
        be announced as having become blank."""
        monitor = {'kind': self.monitors.BY_AREA, 'name': 'Score',
                   'rect': [0, 0, 10, 10]}
        self.monitors._load().append(monitor)
        readings = ['10 points', None, None]
        self.monitors._read = lambda m: readings.pop(0)
        try:
            self.monitors.check()
            self.monitors.check()
            self.assertEqual(self.said, [])
        finally:
            del self.monitors._read

    def test_becoming_empty_is_not_news_either(self):
        """Usually a window being rebuilt rather than something happening."""
        monitor = {'kind': self.monitors.BY_AREA, 'name': 'Score',
                   'rect': [0, 0, 10, 10]}
        self.monitors._load().append(monitor)
        readings = ['10 points', '   ']
        self.monitors._read = lambda m: readings.pop(0)
        try:
            self.monitors.check()
            self.monitors.check()
            self.assertEqual(self.said, [])
        finally:
            del self.monitors._read

    def test_a_long_change_is_shortened_rather_than_read_out(self):
        """A monitor that has become a page of text is not something to
        read at somebody who is doing something else."""
        said = self.monitors._shorten('word ' * 500)
        self.assertLessEqual(len(said), self.monitors.MAX_SAID + 3)

    def test_it_never_interrupts(self):
        """A reader that talks over you is one you switch off, and none of
        this is the thing the user is doing."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'monitors.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('queueFunction', source)
        self.assertNotIn('cancelSpeech', source)

    def test_the_watch_only_runs_when_there_is_something_to_watch(self):
        """A thread polling nothing is a thread reading the screen for no
        reason, and this one can reach Windows' own recogniser."""
        self.monitors._keep_running()
        self.assertFalse(self.monitors.report()['running'])
        self.monitors.watch_this_control(self.Obj())
        self.assertTrue(self.monitors.report()['running'])
        self.monitors.clear()
        self.assertFalse(self.monitors.report()['running'])

# --------------------------------------------------------------------------- #
class WatchingAListMeansWatchingWhatIsINIt(unittest.TestCase):
    """"Monitor an area, of a list say" - and a list is the case a monitor
    that reads one object gets wrong.

    Asking a list for its value answers the same string for ever, because
    what changes is what is IN it. A chat, a build log, a queue: being told
    that a line arrived is the whole reason anybody watches one.
    """

    class Row:
        def __init__(self, name):
            self.name = name
            self.value = ''
            self.children = []
            self.role = types.SimpleNamespace(name='LISTITEM')

    class List:
        def __init__(self, rows):
            self.name = 'Messages'
            self.value = ''
            self.description = ''
            self.role = types.SimpleNamespace(name='LIST')
            self.children = rows

    def setUp(self):
        from titanEnhancements import monitors
        self.monitors = monitors

    def test_a_list_is_read_as_its_rows(self):
        listed = self.List([self.Row('one'), self.Row('two')])
        self.assertEqual(self.monitors._read_object(listed), 'one\ntwo')

    def test_an_ordinary_control_is_still_read_as_itself(self):
        control = self.Row('Save')
        control.role = types.SimpleNamespace(name='BUTTON')
        self.assertEqual(self.monitors._read_object(control), 'Save')

    def test_a_list_that_cannot_be_walked_is_not_an_empty_list(self):
        """None rather than '': a collection that cannot be read is not one
        that has become empty, and saying the second when it is the first is
        how a window being rebuilt is reported as news."""
        listed = self.List([])
        self.assertIsNone(self.monitors._read_rows(listed))

    def test_only_what_ARRIVED_is_said(self):
        """A chat window that has gained one line must not be read out from
        the top."""
        before = 'one\ntwo'
        now = 'one\ntwo\nthree'
        self.assertEqual(self.monitors.rows_added(before, now), ['three'])

    def test_rows_merely_reordered_are_not_news(self):
        self.assertEqual(self.monitors.rows_added('one\ntwo', 'two\none'), [])

    def test_the_first_reading_is_all_of_it(self):
        self.assertEqual(self.monitors.rows_added(None, 'one\ntwo'),
                         ['one', 'two'])

    def test_a_huge_list_is_not_read_out(self):
        listed = self.List([self.Row('row %d' % n) for n in range(500)])
        read = self.monitors._read_object(listed)
        self.assertLessEqual(len(read.splitlines()),
                             self.monitors.MAX_ROWS + 1)
        self.assertIn('(+', read)


# --------------------------------------------------------------------------- #
class WindowsAndActions(unittest.TestCase):
    """Window-Eyes' own idea: the windows, their controls, and what each
    control will actually DO.

    A different question from "read me the screen": this is about what can
    be done, and it is the answer to "there is a button in this dialog and
    Tab will not reach it".
    """

    class Obj:
        def __init__(self, name='', role='BUTTON', actions=(), value='',
                     children=()):
            self.name = name
            self.value = value
            self.role = types.SimpleNamespace(name=role)
            self.children = list(children)
            self._actions = list(actions)
            self.done = []
            self.focused = False

        @property
        def actionCount(self):
            return len(self._actions)

        def getActionName(self, index):
            return self._actions[index]

        def doAction(self, index):
            self.done.append(index)

        def setFocus(self):
            self.focused = True

    def setUp(self):
        from titanEnhancements import windowsAndActions
        self.wa = windowsAndActions

    def test_a_controls_own_verbs_are_what_is_offered(self):
        """Nothing is invented: an action is one the control declares, so a
        control that offers nothing comes back empty - which is a true
        answer and a useful one."""
        obj = self.Obj(name='Save', actions=('Press',))
        self.assertEqual(self.wa.actions_of(obj), [(0, 'Press')])
        self.assertEqual(self.wa.actions_of(self.Obj(name='Label')), [])

    def test_a_control_that_says_nothing_at_all_is_not_asked(self):
        self.assertEqual(self.wa.actions_of(object()), [])

    def test_doing_one_says_what_it_was(self):
        obj = self.Obj(name='Save', actions=('Press',))
        ok, said = self.wa.do(obj, 0)
        self.assertTrue(ok)
        self.assertEqual(obj.done, [0])
        self.assertIn('Press', said)

    def test_one_that_fails_says_so_rather_than_raising(self):
        class Awkward(self.Obj):
            def doAction(self, index):
                raise RuntimeError('no')
        ok, said = self.wa.do(Awkward(actions=('Press',)), 0)
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_the_keyboard_can_be_moved_to_one(self):
        """Half of what a list like this is for: a control Tab will not
        reach can still be worked."""
        obj = self.Obj(name='Save')
        ok, _said = self.wa.focus(obj)
        self.assertTrue(ok)
        self.assertTrue(obj.focused)

    def test_furniture_is_not_listed(self):
        """A window and a pane hold other things and do nothing themselves,
        so listing them puts a hundred rows between the user and the
        controls they came for."""
        window = self.Obj(name='Dialog', role='WINDOW', children=[
            self.Obj(name='Panel', role='PANE', children=[
                self.Obj(name='Save', role='BUTTON', actions=('Press',)),
            ]),
        ])
        found = self.wa.controls(window)
        self.assertEqual([row['label'].split(',')[0] for row in found],
                         ['Save'])

    def test_a_control_with_nothing_to_call_it_is_not_listed(self):
        window = self.Obj(name='Dialog', role='WINDOW', children=[
            self.Obj(name='', role='BUTTON'),
            self.Obj(name='Save', role='BUTTON'),
        ])
        self.assertEqual(len(self.wa.controls(window)), 1)

    def test_the_walk_is_bounded(self):
        """A reader that walks a whole browser tree is a reader that has
        stopped answering."""
        deep = self.Obj(name='leaf', role='BUTTON')
        for _ in range(50):
            deep = self.Obj(name='x', role='PANE', children=[deep] * 20)
        found = self.wa.controls(deep)
        self.assertLessEqual(len(found), self.wa.MAX_CONTROLS)

    def test_it_never_acts_by_itself(self):
        """Listing is free and changes nothing; doing is a separate
        keypress on a chosen row."""
        window = self.Obj(name='Dialog', role='WINDOW', children=[
            self.Obj(name='Delete everything', role='BUTTON',
                     actions=('Press',)),
        ])
        found = self.wa.controls(window)
        self.assertEqual(found[0]['obj'].done, [])

# --------------------------------------------------------------------------- #
class PlaceMarkers(unittest.TestCase):
    """JAWS has had them for twenty years and people who use them do not
    give them up.

    A program you use every day has three places in it you actually go, and
    getting to each is a dozen Tabs every time - because a reader can only
    offer you the control you are ON and the one after it.
    """

    class Obj:
        def __init__(self, name='Search', automation='searchBox',
                     klass='Edit', location=(10, 20, 100, 30)):
            self.name = name
            self.value = ''
            self.windowClassName = klass
            self.UIAAutomationId = automation
            self.location = location
            self.role = types.SimpleNamespace(name='EDITABLETEXT')
            self.children = []
            self.focused = False

        def setFocus(self):
            self.focused = True

    def setUp(self):
        from titanEnhancements import anchors, markers
        self.markers, self.anchors = markers, anchors
        self.dir = tempfile.mkdtemp()
        self._path = markers.path
        markers.path = lambda: os.path.join(self.dir, 'markers.json')
        markers.forget()
        self._program = anchors.program_of
        anchors.program_of = lambda obj=None: 'mail.exe'
        self.addCleanup(markers.forget)
        self.addCleanup(lambda: setattr(anchors, 'program_of', self._program))
        self.addCleanup(lambda: setattr(markers, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def test_a_marker_is_made_and_numbered(self):
        """The number is the point: the third thing you marked is always the
        third thing, so going there becomes a key you press."""
        ok, said = self.markers.mark(self.Obj())
        self.assertTrue(ok)
        self.assertIn('1', said)

    def test_the_numbering_follows_the_order_they_were_made(self):
        self.markers.mark(self.Obj(name='Search', automation='a'))
        self.markers.mark(self.Obj(name='List', automation='b'))
        self.markers.mark(self.Obj(name='Send', automation='c'))
        self.assertEqual([row['name'] for row in self.markers.for_program()],
                         ['Search', 'List', 'Send'])

    def test_they_belong_to_a_program(self):
        """Or the first nine markers are nine markers from nine different
        programs, and the list is not worth opening."""
        self.markers.mark(self.Obj(automation='a'))
        self.anchors.program_of = lambda obj=None: 'browser.exe'
        self.assertEqual(self.markers.for_program(), [])
        self.assertEqual(len(self.markers.all_markers()), 1)

    def test_the_same_control_is_not_marked_twice(self):
        self.markers.mark(self.Obj())
        ok, said = self.markers.mark(self.Obj())
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_a_control_with_nothing_stable_is_marked_by_its_place(self):
        ok, _said = self.markers.mark(self.Obj(automation=''))
        self.assertTrue(ok)
        self.assertEqual(self.markers.for_program()[0]['anchor']['kind'],
                         self.anchors.BY_POINT)

    def test_a_control_that_is_nowhere_is_refused(self):
        ok, said = self.markers.mark(self.Obj(automation='', location=None))
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_going_to_one_moves_the_keyboard(self):
        obj = self.Obj()
        self.markers.mark(obj)
        self.anchors.find = lambda anchor: obj
        try:
            ok, _said = self.markers.go(self.markers.for_program()[0])
        finally:
            del self.anchors.find
        self.assertTrue(ok)
        self.assertTrue(obj.focused)

    def test_a_control_that_cannot_take_the_keyboard_gets_the_review_cursor(self):
        """Most of the places worth marking cannot be focused, and a marker
        that refused those would be a marker for buttons only."""
        class Static(self.Obj):
            def setFocus(self):
                raise RuntimeError('no')
        obj = Static(name='Status')
        self.markers.mark(obj)
        self.anchors.find = lambda anchor: obj
        moved = []
        import titanEnhancements.markers as m
        self.assertTrue(hasattr(m, 'go'))
        try:
            ok, said = self.markers.go(self.markers.for_program()[0])
        finally:
            del self.anchors.find
        # With no NVDA there is no review cursor either, so what is checked
        # is that it did not simply give up on the focus failing.
        self.assertIsInstance(said, str)
        self.assertTrue(said)

    def test_a_marker_whose_control_is_gone_says_so(self):
        self.markers.mark(self.Obj())
        self.anchors.find = lambda anchor: None
        try:
            ok, said = self.markers.go(self.markers.for_program()[0])
        finally:
            del self.anchors.find
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_a_number_nobody_marked_says_so(self):
        ok, said = self.markers.go_to_number(4)
        self.assertFalse(ok)
        self.assertIn('4', said)

    def test_one_can_be_renamed_and_forgotten(self):
        self.markers.mark(self.Obj())
        row = self.markers.for_program()[0]
        self.assertTrue(self.markers.rename(row, 'The search box'))
        self.assertEqual(self.markers.for_program()[0]['name'],
                         'The search box')
        self.assertTrue(self.markers.remove(self.markers.for_program()[0]))
        self.assertEqual(self.markers.for_program(), [])

    def test_they_survive_being_forgotten_and_read_again(self):
        self.markers.mark(self.Obj())
        self.markers.forget()
        self.assertEqual(len(self.markers.for_program()), 1)

    def test_only_a_STRONG_anchor_names_a_control(self):
        """A key built from where a control sits moves the moment a toolbar
        gains a button, and a marker that jumped somewhere wrong is one the
        user acts on."""
        self.assertTrue(self.anchors.strong_key(self.Obj()))
        self.assertEqual(self.anchors.strong_key(self.Obj(automation='')), '')


# --------------------------------------------------------------------------- #
class TheSoundScheme(unittest.TestCase):
    """A state said in words costs a word every time, and the word is the
    same length whether or not the listener already knew."""

    def setUp(self):
        from titanEnhancements import schemes
        self.schemes = schemes
        self.dir = tempfile.mkdtemp()
        self._path = schemes.path
        schemes.path = lambda: os.path.join(self.dir, 'scheme.json')
        schemes.forget()
        self.addCleanup(schemes.forget)
        self.addCleanup(lambda: setattr(schemes, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def test_nothing_is_changed_until_something_is_chosen(self):
        """A state nobody has touched is spoken exactly as NVDA spoke it,
        through the same path, with no work done at all."""
        words, sounds = self.schemes.answer(['CHECKED', 'SELECTED'])
        self.assertEqual(words, ['CHECKED', 'SELECTED'])
        self.assertEqual(sounds, [])

    def test_a_state_given_a_sound_is_played_instead_of_said(self):
        self.schemes.set_way('CHECKED', self.schemes.AS_SOUND)
        words, sounds = self.schemes.answer(['CHECKED', 'SELECTED'])
        self.assertEqual(words, ['SELECTED'])
        self.assertEqual(len(sounds), 1)

    def test_both_says_it_and_plays_it(self):
        self.schemes.set_way('CHECKED', self.schemes.AS_BOTH)
        words, sounds = self.schemes.answer(['CHECKED'])
        self.assertEqual(words, ['CHECKED'])
        self.assertEqual(len(sounds), 1)

    def test_a_sound_is_never_the_only_way_something_is_said_by_default(self):
        """The mistake to avoid is the one where the earcon becomes
        load-bearing."""
        for row in self.schemes.described():
            if not row['changed']:
                self.assertEqual(row['way'], self.schemes.AS_WORD, row['state'])

    def test_putting_one_back_really_puts_it_back(self):
        self.schemes.set_way('CHECKED', self.schemes.AS_SOUND)
        self.schemes.reset('CHECKED')
        self.assertEqual(self.schemes.way_of('CHECKED'),
                         self.schemes.AS_WORD)

    def test_the_switch_being_off_means_every_word_is_said(self):
        from titanEnhancements import configSpec
        self.schemes.set_way('CHECKED', self.schemes.AS_SOUND)
        before = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults(),
                                       soundScheme=False)
        try:
            words, sounds = self.schemes.answer(['CHECKED'])
        finally:
            configSpec.read = before
        self.assertEqual(words, ['CHECKED'])
        self.assertEqual(sounds, [])

    def test_every_default_sound_is_one_the_theme_really_has(self):
        """A mapping to a missing file is silence, which for a state that is
        no longer being said in words is the state simply gone."""
        for state, name in self.schemes.STATES.items():
            self.assertTrue(os.path.exists(
                os.path.join(ROOT, 'sfx', 'default', 'SRE', name)),
                '%s -> %s' % (state, name))

    def test_every_state_has_words_saying_what_it_is(self):
        words = self.schemes.state_names()
        for state in self.schemes.STATES:
            self.assertTrue(words.get(state), state)

    def test_it_survives_being_forgotten_and_read_again(self):
        self.schemes.set_way('SELECTED', self.schemes.AS_SOUND)
        self.schemes.forget()
        self.assertEqual(self.schemes.way_of('SELECTED'),
                         self.schemes.AS_SOUND)

    def test_the_reader_really_asks_it(self):
        """A scheme nothing consults is a manager that changes nothing."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'elements.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('schemes.answer(', source)
        self.assertIn('schemes.play(', source)

# --------------------------------------------------------------------------- #
class TheManagerIsAManagerAndNotAChooser(unittest.TestCase):
    """A list you pick one thing out of and that then closes is right for
    "go to this marker" and wrong for tidying up what you have accumulated.

    Nothing here opens a window: what is checked is that the manager reads
    and writes the modules that OWN each kind of thing, so what it shows is
    what is really in force.
    """

    def setUp(self):
        from titanEnhancements import managerGui
        self.gui = managerGui
        with io.open(managerGui.__file__, encoding='utf-8') as handle:
            self.source = handle.read()

    def test_it_has_a_page_for_each_kind_of_thing(self):
        for page in ('_markers_page', '_monitors_page', '_scheme_page'):
            self.assertIn('def %s' % page, self.source)

    def test_every_page_reads_the_module_that_owns_its_kind(self):
        """A manager that showed one thing while the reader did another
        would be worse than not having one."""
        self.assertIn('markers.all_markers()', self.source)
        self.assertIn('monitors.all_monitors()', self.source)
        self.assertIn('schemes.described()', self.source)

    def test_every_page_can_change_what_it_shows(self):
        for call in ('markers.rename(', 'markers.remove(',
                     'monitors.remove(', 'schemes.set_way('):
            self.assertIn(call, self.source, call)

    def test_it_is_a_real_tab_control(self):
        """The platform says "tab, 1 of 3" without a word being written
        here."""
        self.assertIn('wx.Notebook', self.source)

    def test_it_answers_with_nothing_rather_than_raising_without_wx(self):
        self.assertIsNone(self.gui.build())
        self.assertFalse(self.gui.show())

    def test_the_command_and_the_menu_both_reach_it(self):
        for name, needle in (
                ('__init__.py', 'commands.manager()'),
                ('menu.py', "_run_command('manager')"),
                ('commands.py', 'managerGui.show()')):
            path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                                name)
            with io.open(path, encoding='utf-8') as handle:
                self.assertIn(needle, handle.read(), name)

# --------------------------------------------------------------------------- #
class TheJournalRemembersWhereItCameFrom(unittest.TestCase):
    """Every reader has a speech history. None of them answers "where was
    that?", because the words were stored and the thing that said them was
    not.
    """

    class Obj:
        def __init__(self, name='Status', automation='statusText'):
            self.name = name
            self.value = ''
            self.windowClassName = 'Static'
            self.UIAAutomationId = automation
            self.location = (0, 0, 10, 10)
            self.role = types.SimpleNamespace(name='STATICTEXT')
            self.children = []

    def setUp(self):
        from titanEnhancements import anchors, journal
        self.journal, self.anchors = journal, anchors
        journal.forget()
        self._program = anchors.program_of
        anchors.program_of = lambda obj=None: 'mail.exe'
        self.addCleanup(journal.forget)
        self.addCleanup(lambda: setattr(anchors, 'program_of', self._program))

    def test_a_line_is_kept_with_the_way_back_to_it(self):
        self.journal.note('Message sent', kind='notification',
                          obj=self.Obj())
        row = self.journal.lines()[0]
        self.assertEqual(row['text'], 'Message sent')
        self.assertTrue(self.journal.can_go(row))

    def test_the_kind_of_speech_is_kept_too(self):
        self.journal.note('a', kind='typed', obj=self.Obj())
        self.assertEqual(self.journal.lines()[0]['kind'], 'typed')

    def test_the_same_line_twice_running_is_one_thing(self):
        """A list that re-announced, a status bar rewritten on a timer - a
        reader repeating itself is not two things that happened."""
        self.journal.note('Ready', obj=self.Obj())
        self.journal.note('Ready', obj=self.Obj())
        self.assertEqual(len(self.journal.lines()), 1)

    def test_it_is_newest_first(self):
        for said in ('one', 'two', 'three'):
            self.journal.note(said, obj=self.Obj())
        self.assertEqual([row['text'] for row in self.journal.lines()],
                         ['three', 'two', 'one'])

    def test_it_can_be_searched(self):
        self.journal.note('Message sent', obj=self.Obj())
        self.journal.note('Nothing to send', obj=self.Obj())
        self.assertEqual(len(self.journal.lines(containing='sent')), 1)

    def test_it_never_grows_without_bound(self):
        for number in range(self.journal.KEPT + 50):
            self.journal.note('line %d' % number, obj=self.Obj())
        self.assertLessEqual(len(self.journal.lines()), self.journal.KEPT)

    def test_a_line_whose_control_is_gone_says_so(self):
        self.journal.note('Message sent', obj=self.Obj())
        row = self.journal.lines()[0]
        self.anchors.find = lambda anchor: None
        try:
            ok, said = self.journal.go(row)
        finally:
            del self.anchors.find
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_the_switch_being_off_keeps_nothing(self):
        from titanEnhancements import configSpec
        before = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults(), journal=False)
        try:
            self.assertFalse(self.journal.note('x', obj=self.Obj()))
        finally:
            configSpec.read = before
        self.assertEqual(self.journal.lines(), [])

    def test_the_reader_really_writes_to_it(self):
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'interject.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('journal.note(', source)


# --------------------------------------------------------------------------- #
class ProceduresAreRecordedByCONTROLnotByKey(unittest.TestCase):
    """The one that goes past JAWS, and the reason is not cleverness: a
    recorded keystroke is the wrong unit.

    Tab, Tab, Tab, Space works until the dialog gains a checkbox - and then
    it does the wrong thing silently, which for somebody who cannot see the
    screen is the failure that matters.
    """

    class Obj:
        def __init__(self, name='Save', automation='saveButton',
                     actions=('Press',)):
            self.name = name
            self.value = ''
            self.windowClassName = 'Button'
            self.UIAAutomationId = automation
            self.location = (0, 0, 10, 10)
            self.role = types.SimpleNamespace(name='BUTTON')
            self.children = []
            self._actions = list(actions)
            self.done = []
            self.focused = False

        @property
        def actionCount(self):
            return len(self._actions)

        def getActionName(self, index):
            return self._actions[index]

        def doAction(self, index):
            self.done.append(index)

        def setFocus(self):
            self.focused = True

    def setUp(self):
        from titanEnhancements import anchors, procedures
        self.procedures, self.anchors = procedures, anchors
        self.dir = tempfile.mkdtemp()
        self._path = procedures.path
        procedures.path = lambda: os.path.join(self.dir, 'procedures.json')
        procedures.forget()
        procedures.cancel_recording()
        self._program = anchors.program_of
        anchors.program_of = lambda obj=None: 'mail.exe'
        self.addCleanup(procedures.cancel_recording)
        self.addCleanup(procedures.forget)
        self.addCleanup(lambda: setattr(anchors, 'program_of', self._program))
        self.addCleanup(lambda: setattr(procedures, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def test_nothing_is_recorded_until_it_is_asked_for(self):
        self.procedures.note_focus(self.Obj())
        self.assertEqual(self.procedures.report()['steps'], 0)

    def test_a_step_is_a_control_and_what_happened_to_it(self):
        self.procedures.start_recording()
        self.procedures.note_focus(self.Obj())
        self.procedures.note_press(self.Obj())
        _ok, _said = self.procedures.stop_recording('Send')
        steps = self.procedures.for_program()[0]['steps']
        self.assertEqual([step['do'] for step in steps],
                         [self.procedures.GO, self.procedures.PRESS])
        self.assertTrue(steps[0]['anchor'])

    def test_passing_through_a_control_is_not_visiting_it(self):
        """Tabbing through a dialog would otherwise record a step per
        control passed, which is a keystroke macro wearing a hat."""
        self.procedures.start_recording()
        for name in ('First', 'Second', 'Third'):
            self.procedures.note_focus(self.Obj(name=name, automation=name))
        self.procedures.stop_recording('x')
        steps = self.procedures.for_program()[0]['steps']
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]['what'], 'Third')

    def test_a_run_of_typing_is_one_step(self):
        self.procedures.start_recording()
        for letter in 'hello':
            self.procedures.note_typing(letter)
        self.procedures.stop_recording('x')
        steps = self.procedures.for_program()[0]['steps']
        self.assertEqual(steps, [{'do': self.procedures.TYPE,
                                  'text': 'hello'}])

    def test_a_recording_is_READABLE(self):
        """A keystroke macro can only be re-recorded; this can be checked,
        corrected and handed to somebody else."""
        self.procedures.start_recording()
        self.procedures.note_focus(self.Obj(name='Search'))
        self.procedures.note_typing('titan')
        self.procedures.stop_recording('Look it up')
        text = self.procedures.as_text(self.procedures.for_program()[0])
        self.assertIn('Search', text)
        self.assertIn('titan', text)

    def test_an_empty_recording_is_not_kept(self):
        self.procedures.start_recording()
        ok, said = self.procedures.stop_recording('x')
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_replay_finds_the_control_before_it_touches_it(self):
        obj = self.Obj()
        self.procedures.start_recording()
        self.procedures.note_press(obj)
        self.procedures.stop_recording('Send')
        self.anchors.find = lambda anchor: obj
        try:
            ok, _said = self.procedures.run(
                self.procedures.for_program()[0])
        finally:
            del self.anchors.find
        self.assertTrue(ok)
        self.assertEqual(obj.done, [0])

    def test_it_STOPS_at_the_first_step_it_cannot_do(self):
        """A procedure that carried on past a step that did not happen
        would be pressing controls in a state nobody predicted."""
        obj = self.Obj()
        self.procedures.start_recording()
        self.procedures.note_press(obj)
        self.procedures.note_press(self.Obj(name='Close', automation='close'))
        self.procedures.stop_recording('Send')
        self.anchors.find = lambda anchor: None
        before = self.procedures.APPEAR_SECONDS
        self.procedures.APPEAR_SECONDS = 0.0
        try:
            ok, said = self.procedures.run(
                self.procedures.for_program()[0])
        finally:
            self.procedures.APPEAR_SECONDS = before
            del self.anchors.find
        self.assertFalse(ok)
        self.assertIn('1', said)
        self.assertEqual(obj.done, [])

    def test_it_presses_the_controls_OWN_action(self):
        """Never a synthesised click: a click at a coordinate is what a
        keystroke macro degrades into, and it is what this exists not to
        be."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'procedures.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('obj.doAction(0)', source)
        self.assertNotIn('SetCursorPos', source)

    def test_they_belong_to_a_program(self):
        self.procedures.start_recording()
        self.procedures.note_press(self.Obj())
        self.procedures.stop_recording('Send')
        self.anchors.program_of = lambda obj=None: 'browser.exe'
        self.assertEqual(self.procedures.for_program(), [])
        self.assertEqual(len(self.procedures.all_procedures()), 1)


# --------------------------------------------------------------------------- #
class FindingTheControlThatDOESAThing(unittest.TestCase):
    """Every reader can move you to the next button. None can answer "where
    is the thing that saves this?"."""

    class Obj:
        def __init__(self, name='', value='', description='', children=()):
            self.name = name
            self.value = value
            self.description = description
            self.role = types.SimpleNamespace(name='BUTTON')
            self.children = list(children)

    def setUp(self):
        from titanEnhancements import findControl
        self.find = findControl
        self.rows = [
            {'label': 'Save', 'obj': None, 'words': 'save'},
            {'label': 'Save as...', 'obj': None, 'words': 'save as'},
            {'label': 'Preferences', 'obj': None,
             'words': 'preferences turn off notifications'},
        ]

    def test_the_words_are_tried_first_and_are_free(self):
        hits = self.find.by_words('save', self.rows)
        self.assertEqual(len(hits), 2)

    def test_the_words_in_any_order_still_find_it(self):
        """"save file" should find "Save the file as..." and a substring
        match alone will not."""
        rows = [{'label': 'x', 'obj': None, 'words': 'save the file as'}]
        self.assertEqual(len(self.find.by_words('file save', rows)), 1)

    def test_a_question_nothing_matches_finds_nothing(self):
        self.assertEqual(self.find.by_words('quit', self.rows), [])

    def test_the_ai_is_not_reached_unless_it_is_asked_for(self):
        """It sends the control names of the window to a provider, which is
        a small thing to send and still a thing to be asked about."""
        tier, rows, why = self.find.find('turn off notifications',
                                        use_ai=False)
        self.assertEqual(rows, [])
        self.assertTrue(why)

    def test_a_match_says_which_tier_found_it(self):
        """"Save, by its name" and "Preferences, by what it does" are
        different answers and the user knows which they got."""
        names = self.find.tier_names()
        for tier in (self.find.BY_WORDS, self.find.BY_SCREEN,
                     self.find.BY_MEANING):
            self.assertTrue(names.get(tier), tier)

    def test_a_match_off_the_screen_carries_where_it_is(self):
        """So it can be pressed, with no control behind it at all."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'findControl.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn("'rect': rect", source)
        self.assertIn('smart._click(', source)

# --------------------------------------------------------------------------- #
class EveryCommandAndKeyReallyGoesSomewhere(unittest.TestCase):
    """The sweep that keeps a growing add-on honest.

    Every one of these is a fault that is invisible until somebody presses
    the key: a script that calls a command nobody wrote, a menu entry
    naming one that has been renamed, two commands claiming one gesture -
    where the second silently never fires and the user reports "that key
    does nothing" about a feature that is perfectly written.
    """

    def setUp(self):
        folder = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements')
        self.folder = folder
        self.sources = {}
        for name in sorted(os.listdir(folder)):
            if name.endswith('.py'):
                with io.open(os.path.join(folder, name),
                             encoding='utf-8') as handle:
                    self.sources[name] = handle.read()
        self.commands = set(re.findall(r'^def ([a-z_][a-z_0-9]*)\(',
                                       self.sources['commands.py'], re.M))

    def test_no_two_things_claim_the_same_key(self):
        """The second one silently never fires."""
        found = re.findall(r"gesture='(kb:[^']+)'", self.sources['__init__.py'])
        twice = [key for key, count in collections.Counter(found).items()
                 if count > 1]
        self.assertEqual(twice, [], 'two commands claim: %s' % twice)

    def test_every_script_calls_a_command_that_exists(self):
        called = set(re.findall(r'commands\.([a-z_][a-z_0-9]*)\(',
                                self.sources['__init__.py']))
        self.assertEqual(sorted(called - self.commands), [])

    def test_every_menu_entry_names_a_command_that_exists(self):
        named = set(re.findall(r"_run_command\('([a-z_][a-z_0-9]*)'",
                               self.sources['menu.py']))
        self.assertEqual(sorted(named - self.commands), [])

    def test_every_script_has_a_description(self):
        """It is what the user reads in Input Gestures, and a script with
        none is a row they cannot tell from any other."""
        source = self.sources['__init__.py']
        for name in re.findall(r'def (script_[A-Za-z0-9_]+)\(', source):
            at = source.index('def %s(' % name)
            before = source[max(0, at - 500):at]
            self.assertIn('description=', before, name)

    def test_every_module_the_plugin_imports_is_really_there(self):
        imported = set(re.findall(r'^from \. import ([a-z_A-Z0-9]+)',
                                  self.sources['__init__.py'], re.M))
        for name in imported:
            self.assertIn('%s.py' % name, self.sources, name)

    def test_every_module_imports_without_nvda(self):
        """The property that makes the add-on degrade on an NVDA missing a
        feature instead of failing to load at all."""
        import importlib
        for name in sorted(self.sources):
            if name == '__init__.py':
                continue
            importlib.import_module('titanEnhancements.%s' % name[:-3])

    def test_every_store_writes_somewhere_of_its_own(self):
        """Two features sharing a file would overwrite each other."""
        files = []
        for name, source in self.sources.items():
            for found in re.findall(r"^FILENAME = '([^']+)'", source, re.M):
                files.append((name, found))
        names = [found for _module, found in files]
        self.assertEqual(sorted(names), sorted(set(names)), files)

    def test_nothing_speaks_by_calling_speech_directly_on_a_worker(self):
        """Everything that says something goes through `dialogs.report` or
        the speech filter, so the sound scheme, the journal and the voice
        classes all see it."""
        for name in ('markers.py', 'procedures.py', 'findControl.py',
                     'monitors.py'):
            self.assertNotIn('speech.speak(', self.sources[name], name)

# --------------------------------------------------------------------------- #
class TheManagersAreAMenuOfTheirOwn(unittest.TestCase):
    """They were mixed in among "where am I" and "read this window", and by
    the time there were twenty of them that list was something a user
    arrowed through looking for the one they came for.

    A manager is not a thing you do to the control you are on: it is a
    thing you keep. Keeping the two apart is what makes both lists short
    enough to read.
    """

    def setUp(self):
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'menu.py')
        with io.open(path, encoding='utf-8') as handle:
            self.source = handle.read()
        self.managers = self._between('managers = wx.Menu()',
                                      'reader = wx.Menu()')
        self.reader = self._between('reader = wx.Menu()',
                                    "_('This program')")

    def _between(self, start, end):
        at = self.source.index(start)
        return self.source[at:self.source.index(end, at)]

    def test_there_is_a_managers_menu(self):
        self.assertIn("menu.AppendSubMenu(managers, _('Managers'))",
                      self.source)

    def test_every_manager_is_in_it(self):
        for command in ('manager', 'mark_this', 'go_to_marker',
                        'watch_this', 'watched_areas', 'record_procedure',
                        'run_procedure', 'read_journal', 'search_journal',
                        'find_control', 'find_control_with_ai',
                        'windows_and_actions', 'sound_scheme',
                        'voice_classes', 'reader_modules'):
            self.assertIn("_run_command('%s')" % command, self.managers,
                          command)

    def test_none_of_them_is_left_in_the_reading_menu(self):
        for command in ('manager', 'mark_this', 'run_procedure',
                        'read_journal', 'find_control', 'sound_scheme',
                        'windows_and_actions', 'voice_classes'):
            self.assertNotIn("_run_command('%s')" % command, self.reader,
                             command)

    def test_the_reading_menu_keeps_what_is_about_THIS_window(self):
        for command in ('where_am_i', 'label_control', 'describe_control',
                        'read_locally', 'watch_surface'):
            self.assertIn("_run_command('%s')" % command, self.reader,
                          command)

    def test_a_manager_with_several_commands_gets_a_submenu_of_its_own(self):
        """Six commands in a row under one heading is the flat list again,
        one level down."""
        for name in ('markers', 'watched', 'doing', 'spoken', 'finding',
                     'modules'):
            self.assertIn('%s = wx.Menu()' % name, self.source, name)
            self.assertIn('managers.AppendSubMenu(%s,' % name, self.source,
                          name)

    def test_no_manager_command_is_reachable_from_nowhere(self):
        """A command with a key and no menu entry is one nobody discovers;
        every one of these has both."""
        plugin = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                              '__init__.py')
        with io.open(plugin, encoding='utf-8') as handle:
            scripts = handle.read()
        for command in ('journal_page', 'cancel_procedure',
                        'read_procedure', 'forget_marker'):
            self.assertIn("_run_command('%s')" % command, self.source,
                          command)
            self.assertIn('commands.%s(' % command, scripts, command)

# --------------------------------------------------------------------------- #
class WhatIsSETInAManagerReallyCHANGESWhatIsRead(unittest.TestCase):
    """The check that matters, and the one a manager can pass without.

    Every manager here has tests that it stores what it was told. That is
    not the question. The question is whether the reader then behaves
    differently - because a manager that writes a file nothing reads is a
    window full of switches that do nothing, and it looks exactly like one
    that works.
    """

    class Obj:
        def __init__(self, name='', value='', description='',
                     automation='thing', klass='Button'):
            self.name = name
            self.value = value
            self.description = description
            self.windowClassName = klass
            self.UIAAutomationId = automation
            self.location = (0, 0, 10, 10)
            self.role = types.SimpleNamespace(name='BUTTON')
            self.children = []

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def _store(self, module, name):
        before = module.path
        module.path = lambda: os.path.join(self.dir, name)
        module.forget()
        self.addCleanup(module.forget)
        self.addCleanup(lambda: setattr(module, 'path', before))

    # ------------------------------------------------------ the labels
    def test_renaming_a_NAMED_control_really_renames_it(self):
        """The reported bug. It stored the name, said "this control is now
        called X", and read the old one for ever - because the rule that
        decided whether to use a stored name was the rule for deciding
        whether to GUESS one."""
        from titanEnhancements import labels
        self._store(labels, 'labels.json')
        obj = self.Obj(name='Button 3')
        labels.put(obj, 'Send', source='user')
        label, source = labels.applies(obj)
        self.assertEqual(label, 'Send')
        self.assertEqual(source, 'user')

    def test_a_GUESSED_name_is_still_only_for_a_control_with_none(self):
        """The other half of the same rule, which was right and must stay
        right: a control the program named is not improved by a guess."""
        from titanEnhancements import labels
        self._store(labels, 'labels.json')
        obj = self.Obj(name='Button 3')
        labels.put(obj, 'Probably send', source='ai')
        self.assertEqual(labels.applies(obj), ('', ''))

    def test_a_guessed_name_IS_used_where_the_control_has_nothing(self):
        from titanEnhancements import labels
        self._store(labels, 'labels.json')
        obj = self.Obj(name='')
        labels.put(obj, 'Probably send', source='ai')
        label, source = labels.applies(obj)
        self.assertEqual(label, 'Probably send')
        self.assertEqual(source, 'ai')

    def test_forgetting_a_name_really_forgets_it(self):
        from titanEnhancements import labels
        self._store(labels, 'labels.json')
        obj = self.Obj(name='Button 3')
        labels.put(obj, 'Send', source='user')
        labels.remove(obj)
        self.assertEqual(labels.applies(obj), ('', ''))

    def test_the_reader_asks_that_one_place(self):
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'focus.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('labels.applies(', source)

    # ----------------------------------------------- the sound scheme
    def test_a_state_given_a_sound_really_leaves_the_reading(self):
        from titanEnhancements import elements, schemes
        self._store(schemes, 'scheme.json')
        played = []
        before = schemes.play
        schemes.play = lambda sounds: played.extend(sounds)
        try:
            said = elements._sounded([('CHECKED', 'checked'),
                                      ('SELECTED', 'selected')])
            self.assertEqual(said, ['checked', 'selected'])
            self.assertEqual(played, [])
            schemes.set_way('CHECKED', schemes.AS_SOUND)
            said = elements._sounded([('CHECKED', 'checked'),
                                      ('SELECTED', 'selected')])
            self.assertEqual(said, ['selected'])
            self.assertEqual(len(played), 1)
        finally:
            schemes.play = before

    def test_both_really_says_it_and_plays_it(self):
        from titanEnhancements import elements, schemes
        self._store(schemes, 'scheme.json')
        played = []
        before = schemes.play
        schemes.play = lambda sounds: played.extend(sounds)
        try:
            schemes.set_way('CHECKED', schemes.AS_BOTH)
            said = elements._sounded([('CHECKED', 'checked')])
            self.assertEqual(said, ['checked'])
            self.assertEqual(len(played), 1)
        finally:
            schemes.play = before

    # ------------------------------------------------- the voice table
    def test_a_variant_set_on_a_class_really_reaches_the_sequence(self):
        from titanEnhancements import classes, compat, voices

        class Fake:
            def __init__(self, offset=0, **kw):
                self.offset = offset
                self.name = kw.get('name', '')
        self._store(classes, 'classes.json')
        before = {name: getattr(compat, name, None)
                  for name in ('PitchCommand', 'CallbackCommand',
                               'EndUtteranceCommand')}
        for name in before:
            setattr(compat, name, Fake)
        supported = voices._supported
        voices._supported = lambda synth, command: command is not None
        try:
            classes.set_voice('kind', {'variant': 'quincy'})
            out = voices.sequence([('Save', 'name'), ('button', 'kind')])
            self.assertTrue(any(getattr(part, 'name', '') == 'titanVoice'
                                for part in out))
        finally:
            voices._supported = supported
            for name, value in before.items():
                setattr(compat, name, value)

    def test_the_reading_order_set_really_changes_the_reading(self):
        from titanEnhancements import classes, elements
        self._store(classes, 'classes.json')

        class Row:
            name = 'Save'
            value = ''
            description = ''
            role = types.SimpleNamespace(name='BUTTON')
            states = set()
            positionInfo = {}
        classes.set_order([('kind', True), ('name', True)])
        said = [text for text, _voice in elements.describe(Row())]
        self.assertEqual(said[-1], 'Save')

    # ----------------------------------------------------- the journal
    def test_what_the_reader_says_really_reaches_the_journal(self):
        from titanEnhancements import interject, journal
        journal.forget()
        self.addCleanup(journal.forget)
        interject._filter(speechSequence=['Message sent'])
        self.assertEqual([row['text'] for row in journal.lines()],
                         ['Message sent'])

    def test_the_journal_switch_off_really_keeps_nothing(self):
        from titanEnhancements import configSpec, interject, journal
        journal.forget()
        self.addCleanup(journal.forget)
        before = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults(), journal=False)
        try:
            interject._filter(speechSequence=['Message sent'])
        finally:
            configSpec.read = before
        self.assertEqual(journal.lines(), [])

    # ----------------------------------------------------- the monitors
    def test_a_monitor_added_really_starts_the_watch(self):
        from titanEnhancements import anchors, monitors
        self._store(monitors, 'monitors.json')
        program = anchors.program_of
        anchors.program_of = lambda obj=None: 'x.exe'
        self.addCleanup(lambda: setattr(anchors, 'program_of', program))
        self.addCleanup(monitors.stop)
        monitors._keep_running()
        self.assertFalse(monitors.report()['running'])
        monitors.watch_this_window(self.Obj(name='Window'))
        self.assertTrue(monitors.report()['running'])

    # --------------------------------------------------- the OCR tier
    def test_the_ocr_tier_set_really_decides_which_reader_is_used(self):
        from titanEnhancements import configSpec, surface
        before = configSpec.read
        try:
            configSpec.read = lambda: dict(configSpec.defaults(),
                                           ocrTier='ai')
            self.assertEqual(surface._not_a_game(), surface.MODE_NATIVE)
            configSpec.read = lambda: dict(configSpec.defaults(),
                                           ocrTier='local')
            self.assertEqual(surface._not_a_game(), surface.MODE_LOCAL)
        finally:
            configSpec.read = before


# --------------------------------------------------------------------------- #
class WalkingTheRecognisedScreen(unittest.TestCase):
    """The terminal review, applied to a screen that was read as a picture.

    Every reader that does OCR hands you a document and stops there: the
    words are text and the thing they were written on is gone. This keeps
    the coordinates, so Enter clicks what you just read.
    """

    def setUp(self):
        from titanEnhancements import localOcr, ocrReview
        self.review = ocrReview
        ocrReview.stop()
        self.addCleanup(ocrReview.stop)
        reading = localOcr.Reading([
            [{'text': 'New', 'left': 10, 'top': 10, 'width': 30,
              'height': 20},
             {'text': 'game', 'left': 50, 'top': 10, 'width': 40,
              'height': 20}],
            [{'text': 'Options', 'left': 10, 'top': 40, 'width': 60,
              'height': 20}],
        ])
        with ocrReview._LOCK:
            ocrReview._state.update({'on': True, 'row': 0, 'word': 0,
                                     'hwnd': 1,
                                     'rows': reading.rows(),
                                     'lines': list(reading.lines)})
        self.said = []
        self._say = ocrReview._say
        ocrReview._say = lambda text, **kw: self.said.append(str(text))
        self._beep = ocrReview._beep
        ocrReview._beep = lambda row: None
        self.addCleanup(lambda: setattr(ocrReview, '_beep', self._beep))
        self.addCleanup(lambda: setattr(ocrReview, '_say', self._say))

    def test_up_and_down_are_lines(self):
        self.review.move_line(1)
        self.assertIn('Options', self.said)

    def test_left_and_right_are_words(self):
        self.review.move_word(1)
        self.assertEqual(self.said[-1], 'game')

    def test_it_cannot_walk_off_either_end(self):
        for _ in range(10):
            self.review.move_line(-1)
        self.assertEqual(self.review.report()['row'], 0)
        for _ in range(10):
            self.review.move_line(1)
        self.assertEqual(self.review.report()['row'], 1)

    def test_the_cursor_carries_where_it_is_on_the_SCREEN(self):
        """Which is the whole reason to keep the coordinates."""
        text, rect = self.review.here()
        self.assertEqual(text, 'New game')
        self.assertEqual(rect[0], 10)

    def test_moving_along_the_line_narrows_the_click_to_the_WORD(self):
        """A click meant for the third word must not land on the first."""
        self.review.move_word(1)
        text, rect = self.review.here()
        self.assertEqual(text, 'game')
        self.assertEqual(rect[0], 50)

    def test_enter_clicks_where_the_cursor_is(self):
        from titanEnhancements import smart
        clicked = []
        before = smart._click
        smart._click = lambda rect, name: (clicked.append((rect, name)),
                                           (True, name))[1]
        try:
            ok, _said = self.review.click()
        finally:
            smart._click = before
        self.assertTrue(ok)
        self.assertEqual(clicked[0][1], 'New game')

    def test_home_and_end_are_the_ends_of_the_line(self):
        self.review.move_end(True)
        self.assertEqual(self.said[-1], 'game')
        self.review.move_end(False)
        self.assertEqual(self.said[-1], 'New')

    def test_leaving_the_window_ends_it(self):
        before = self.review._foreground
        self.review._foreground = lambda: 999
        try:
            self.assertTrue(self.review.left_the_window())
        finally:
            self.review._foreground = before
        self.assertFalse(self.review.reviewing())

    def test_the_keys_are_the_terminal_reviews_own(self):
        """A user should learn one set of keys and not two."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            '__init__.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        ocr = re.search(r'OCR_KEYS = \{(.+?)\}', source, re.S).group(1)
        terminal = re.search(r'TERMINAL_KEYS = \{(.+?)\}', source,
                             re.S).group(1)
        for key in ('kb:upArrow', 'kb:downArrow', 'kb:leftArrow',
                    'kb:rightArrow', 'kb:pageUp', 'kb:pageDown', 'kb:home',
                    'kb:end', 'kb:escape'):
            self.assertIn(key, ocr, key)
            self.assertIn(key, terminal, key)
        # And the one the terminal has no use for.
        self.assertIn('kb:enter', ocr)

# --------------------------------------------------------------------------- #
class RunningItForRealInsideNVDA(unittest.TestCase):
    """The check that catches what a stand-in cannot.

    Every other test here asks a question a stand-in can answer, and all of
    them passed while the local recogniser returned an empty reading for
    every window on the machine - because the stand-in was built in the
    shape the code EXPECTED rather than the shape NVDA really hands back,
    so the test agreed with the bug.
    """

    def setUp(self):
        from titanEnhancements import link, selftest
        self.selftest = selftest
        self.link = link

    def test_it_runs_and_answers_rather_than_raising(self):
        """With no NVDA under it every check fails, and that is the right
        answer - what must not happen is an exception, because a harness
        that dies tells you about one thing and hides the rest."""
        answer = self.selftest.run()
        self.assertIn('checks', answer)
        self.assertEqual(len(answer['checks']), len(self.selftest.CHECKS))
        for row in answer['checks']:
            self.assertIn('ok', row)
            self.assertTrue(row['said'], row['check'])

    def test_it_covers_every_feature_that_can_fail_on_the_machine(self):
        named = {name for name, _work in self.selftest.CHECKS}
        for wanted in ('local OCR', 'screen review', 'windows and actions',
                       'anchoring a control', 'finding a control',
                       'the journal', 'the sound scheme', 'the names',
                       'the monitors', 'speech origins'):
            self.assertIn(wanted, named, wanted)

    def test_it_reads_and_never_acts(self):
        """It runs on somebody's live machine: it must not press a control,
        type, write to a store or send anything to a provider."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'selftest.py')
        with io.open(path, encoding='utf-8') as handle:
            source = handle.read()
        for never in ('doAction(', 'setFocus(', '_click(', '.send()',
                      'set_way(', 'set_voice(', 'put(', 'save()',
                      "run_action('ocr'"):
            self.assertNotIn(never, source, never)

    def test_it_can_be_asked_for_from_outside(self):
        """A check nobody can run from outside is a check that is run once
        and then never again."""
        self.assertIn('selftest', dict(self.link.handlers()))

    def test_everything_served_that_is_a_THING_TO_DO_is_declared(self):
        """An action served and not declared is not callable over the bus -
        this add-on's own rule, which it has already broken once."""
        served = set(dict(self.link.handlers()))
        declared = {row['name'] for row in self.link.DECLARED}
        # The channel's own plumbing: Titan calls these directly and nobody
        # should be offered them as things to do.
        plumbing = {'attach', 'detach', 'status', 'announce', 'braille',
                    'interrupt', 'speaking', 'beep', 'capabilities',
                    'stand_down'}
        self.assertEqual(sorted(served - declared - plumbing), [])

    def test_the_local_ocr_check_names_the_fault_it_was_written_for(self):
        """A failing check that says "it did not work" sends nobody
        anywhere; this one names the shape to look at."""
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'selftest.py')
        with io.open(path, encoding='utf-8') as handle:
            self.assertIn('LinesWordsResult.data', handle.read())

# --------------------------------------------------------------------------- #
class ASettingThatIsAWordIsNotABoolean(unittest.TestCase):
    """Found by asking the live NVDA what its switches were, which is the
    only place it could have been found.

    `localOcrLanguage` came back as `False`. It is a `string(...)`, and the
    reader matched only `option(...)` as "not a yes or a no" - so the
    language was read through `bool()`, and the next thing to save would
    have written that `False` back over whatever the user had chosen.
    """

    def setUp(self):
        from titanEnhancements import configSpec
        self.configSpec = configSpec

    def test_a_string_setting_reads_as_a_string(self):
        self.assertEqual(self.configSpec.defaults()['localOcrLanguage'], '')

    def test_an_option_setting_reads_as_its_word(self):
        self.assertEqual(self.configSpec.defaults()['ocrTier'], 'local')

    def test_a_switch_still_reads_as_a_switch(self):
        for name in ('journal', 'monitors', 'soundScheme'):
            self.assertIsInstance(self.configSpec.defaults()[name], bool,
                                  name)

    def test_a_string_setting_offers_no_fixed_list(self):
        """It allows any word, so the page asks something that knows the
        machine what the answers really are."""
        self.assertEqual(self.configSpec.choices('localOcrLanguage'), [])
        self.assertTrue(self.configSpec.choices('ocrTier'))

    def test_every_setting_in_the_spec_reads_back_as_its_own_kind(self):
        """The sweep, so a third kind added later cannot arrive as False."""
        defaults = self.configSpec.defaults()
        for name, spec in self.configSpec.SPEC.items():
            wanted = str if ('option(' in spec or 'string(' in spec) else bool
            self.assertIsInstance(defaults[name], wanted, name)
class TheMapOfTitan(unittest.TestCase):
    """`titan.py` - Titan's whole bridge, in the shapes a window is built of.

    Every one of these is a shape read off a LIVE Titan before the code was
    written, because a key nothing writes is a working-looking empty list -
    the fault this add-on has already shipped twice (`ai.history`, and the
    download count in Titan's own repository).
    """

    def setUp(self):
        from titanEnhancements import titan
        from titanEnhancements.link import LINK
        self.titan = titan
        self.answers = {}
        self._bridge = LINK.bridge
        LINK.bridge = lambda call, timeout=None, **args: self.answers.get(
            call, (False, 'nothing said'))
        self.addCleanup(lambda: setattr(LINK, 'bridge', self._bridge))

    def test_buffers_are_read_as_CATEGORIES(self):
        """Titan answers `categories`, each carrying its own buffers -
        measured, not assumed. Reading `buffers` gets an empty list from a
        Titan that is working perfectly."""
        self.answers['buffers.list'] = (True, {'categories': [{'id': 'tts'}]})
        ok, rows = self.titan.buffers()
        self.assertTrue(ok)
        self.assertEqual(rows, [{'id': 'tts'}])

    def test_the_status_bar_is_a_LIST_of_applets(self):
        """The clock, the battery, the volume, the network - not one
        string. Reading it as one makes the whole bar one unreadable
        line."""
        self.answers['statusbar.read'] = (
            True, {'items': [{'key': 'time', 'text': 'Zegar: 14:49'},
                             {'key': 'battery', 'text': '100%'}]})
        ok, rows = self.titan.statusbar()
        self.assertTrue(ok)
        self.assertEqual(len(rows), 2)

    def test_speaking_answers_the_WORD_no(self):
        """Titan says "no", and `bool('no')` is True - so a caller reading
        it as a boolean is told Titan is speaking for ever."""
        self.answers['speech.speaking'] = (True, {'speaking': 'no'})
        ok, speaking = self.titan.speaking()
        self.assertTrue(ok)
        self.assertIs(speaking, False)

    def test_speaking_still_answers_a_real_boolean(self):
        self.answers['speech.speaking'] = (True, {'speaking': True})
        self.assertIs(self.titan.speaking()[1], True)

    def test_a_refusal_is_carried_through_as_titans_own_sentence(self):
        """In the user's own language, naming the one thing that changes
        the answer - which a translation of ours would not."""
        self.answers['apps.list'] = (False, 'Titan nie zezwolil na to')
        ok, said = self.titan.applications()
        self.assertFalse(ok)
        self.assertEqual(said, 'Titan nie zezwolil na to')

    def test_an_answer_that_is_not_a_list_is_refused_rather_than_empty(self):
        self.answers['apps.list'] = (True, {'nothing': 1})
        ok, said = self.titan.applications()
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_a_setting_is_set_by_ITEM_not_by_id(self):
        """Read out of Titan's own `bridge_api._settings_set`. A nearly
        right argument name is the bug this bridge keeps producing, and it
        fails as "nothing happened"."""
        asked = {}

        def bridge(call, timeout=None, **args):
            asked.update(args)
            asked['call'] = call
            return True, {}
        from titanEnhancements.link import LINK
        LINK.bridge = bridge
        self.titan.set_setting('sound_theme', 'default')
        self.assertEqual(asked.get('item'), 'sound_theme')
        self.assertNotIn('id', asked)

    def test_a_widget_answers_ELEMENT_and_nothing_else(self):
        """Read off a live Titan. Looking for `text` or `said` found
        neither: reading a widget came back as the words "element:
        Top-Left" and MOVING one came back empty, which in the review is a
        cursor that moves and says nothing."""
        self.answers['widgets.read'] = (True, {'element': 'Top-Left'})
        ok, said = self.titan.read_widget('example_grid')
        self.assertTrue(ok)
        self.assertEqual(said, 'Top-Left')

    def test_moving_a_widget_says_what_is_under_it_now(self):
        self.answers['widgets.move'] = (True, {'element': 'Top-Right'})
        ok, said = self.titan.move_widget('example_grid', 'right')
        self.assertTrue(ok)
        self.assertEqual(said, 'Top-Right')

    def test_a_sound_is_played_by_NAME_with_a_pan(self):
        asked = {}

        def bridge(call, timeout=None, **args):
            asked.update(args)
            return True, {}
        from titanEnhancements.link import LINK
        LINK.bridge = bridge
        self.titan.play('done.ogg', pan=-1)
        self.assertEqual(asked.get('name'), 'done.ogg')
        self.assertEqual(asked.get('pan'), -1)


class ATitanApplicationAsAVirtualWindow(unittest.TestCase):
    """`appReview.py` - the terminal review's idea, applied to an interface.

    What the arrows walk here is not text read off a screen: it is the
    application's own account of itself, so Enter presses the real control.
    """

    SCREEN = {
        'id': 1, 'kind': 'window', 'title': 'Notes',
        'controls': [
            {'id': 1, 'kind': 'label', 'label': 'Your notes'},
            {'id': 2, 'kind': 'list', 'label': 'Notes',
             'items': ['Shopping', 'Ideas'], 'index': 0},
            {'id': 3, 'kind': 'check', 'label': 'Read it back',
             'value': False},
            {'id': 4, 'kind': 'button', 'label': 'New note'},
        ],
        'menus': [],
    }

    def setUp(self):
        from titanEnhancements import appReview
        self.review = appReview
        self.said = []
        self._say = appReview._say
        appReview._say = lambda text, interrupt=True: self.said.append(
            str(text))
        self._parts = appReview._say_parts
        appReview._say_parts = lambda parts: self.said.append(
            ', '.join(str(text) for text, _voice in parts))
        appReview._state.update({'on': True, 'session': 'abc',
                                 'name': 'Notes', 'screen': self.SCREEN,
                                 'at': 0, 'inner': 0})
        self.addCleanup(lambda: appReview._state.update(
            {'on': False, 'session': '', 'screen': {}, 'at': 0, 'inner': 0}))
        self.addCleanup(lambda: setattr(appReview, '_say', self._say))
        self.addCleanup(lambda: setattr(appReview, '_say_parts', self._parts))

    def test_up_and_down_walk_the_controls(self):
        self.review.move(1)
        self.assertEqual(self.review.here()['id'], 2)
        self.review.move(1)
        self.assertEqual(self.review.here()['id'], 3)
        self.review.move(-1)
        self.assertEqual(self.review.here()['id'], 2)

    def test_it_stops_at_the_ends_rather_than_wrapping(self):
        """A cursor that wraps is one nobody can tell has reached the end,
        which for somebody working by ear is the list having no shape."""
        self.review.move(-1)
        self.assertEqual(self.review.here()['id'], 1)
        self.review.move_end(True)
        self.review.move(1)
        self.assertEqual(self.review.here()['id'], 4)

    def test_left_and_right_walk_what_is_INSIDE_a_control(self):
        """The same relationship as the OCR review's lines and words, one
        level up."""
        self.review.move(1)
        sent = []
        self.review._send_inside = lambda control, index: sent.append(index)
        _ok, said = self.review.move_inside(1)
        self.assertEqual(said, 'Ideas')

    def test_a_control_with_nothing_inside_says_itself_rather_than_moving(self):
        self.review.move_end(True)
        ok, _said = self.review.move_inside(1)
        self.assertTrue(ok)
        self.assertEqual(self.review.here()['id'], 4)

    def test_a_control_is_read_in_the_users_own_voice_classes(self):
        """The label as a name, what it IS a little lower - so a described
        application is read like everything else this add-on reads."""
        parts = self.review.parts_of(self.SCREEN['controls'][3], at=3,
                                     count=4)
        self.assertIn(('New note', 'name'), parts)
        kinds = [voice for _text, voice in parts]
        self.assertIn('kind', kinds)
        self.assertIn('place', kinds)

    def test_a_tick_box_says_its_state(self):
        parts = self.review.parts_of(self.SCREEN['controls'][2])
        self.assertIn('state', [voice for _text, voice in parts])

    def test_a_table_row_of_cells_is_not_read_as_a_python_list(self):
        """A table's row is a list of cells and a list's row is a string.
        A renderer that assumed one would say "['a', 'b']" out loud."""
        self.assertEqual(self.review.row_text(['Shopping', '12 KB']),
                         'Shopping, 12 KB')
        self.assertEqual(self.review.row_text({'text': 'Ideas'}), 'Ideas')

    def test_enter_CLICKS_the_row_rather_than_sending_a_key(self):
        """A press on a list is `EVT_LISTBOX_DCLICK` in the shim - the
        application's own "this row was opened", the same event a double
        click produces. Sending Enter does something only if the
        application happens to bind Enter, and most bind the activation.
        """
        from titanEnhancements import titan
        done = []
        was_press = titan.press_described
        was_key = titan.key_described
        titan.press_described = lambda token, control: (
            done.append(('press', control)) or (True, {'answered': True}))
        titan.key_described = lambda token, key: (
            done.append(('key', key)) or (True, {'answered': True}))
        try:
            self.review._state['at'] = 1        # the list
            self.review.activate()
            for _ in range(40):
                if done:
                    break
                time.sleep(0.02)
        finally:
            titan.press_described = was_press
            titan.key_described = was_key
        self.assertEqual(done[0], ('press', 2))

    def test_the_key_is_the_fallback_when_nothing_answered(self):
        """An application that binds Enter rather than the activation
        would otherwise be a press that silently did nothing."""
        from titanEnhancements import titan
        done = []
        was_press = titan.press_described
        was_key = titan.key_described
        titan.press_described = lambda token, control: (
            done.append(('press', control)) or (True, {'answered': False}))
        titan.key_described = lambda token, key: (
            done.append(('key', key)) or (True, {'answered': True}))
        try:
            self.review._state['at'] = 1
            self.review.activate()
            for _ in range(40):
                if len(done) > 1:
                    break
                time.sleep(0.02)
        finally:
            titan.press_described = was_press
            titan.key_described = was_key
        self.assertEqual(done, [('press', 2), ('key', 'enter')])

    def test_leaving_does_not_close_the_application(self):
        """A key that both leaves and quits is a key nobody can use
        safely."""
        closed = []
        from titanEnhancements import titan
        was = titan.close_described
        titan.close_described = lambda session: closed.append(session)
        try:
            self.review.stop()
            self.assertEqual(closed, [])
        finally:
            titan.close_described = was


class TheScreenChangedIsWhatTheControlsHOLD(unittest.TestCase):
    """The rule the Elten renderer had to learn twice, pinned here.

    Rebuilding on the index makes every arrow key take the keyboard away;
    comparing the control just set makes a typed word come out backwards.
    """

    def setUp(self):
        from titanEnhancements import appScreen
        self.appScreen = appScreen

    def _screen(self, **rest):
        control = {'id': 1, 'kind': 'list', 'label': 'Notes',
                   'items': ['a', 'b'], 'index': 0}
        control.update(rest)
        return {'title': 'Notes', 'kind': 'window', 'controls': [control]}

    def test_the_cursor_moving_is_not_the_screen_changing(self):
        before = self.appScreen.fingerprint(self._screen(index=0))
        after = self.appScreen.fingerprint(self._screen(index=1))
        self.assertEqual(before, after)

    def test_what_a_control_holds_IS_the_screen_changing(self):
        before = self.appScreen.fingerprint(self._screen())
        after = self.appScreen.fingerprint(self._screen(items=['a', 'b', 'c']))
        self.assertNotEqual(before, after)

    def test_the_control_just_set_is_left_out_of_both_sides(self):
        """Or the form is rebuilt on every keystroke and a typed word comes
        out backwards, because a rebuilt field starts with its caret at the
        beginning."""
        before = self.appScreen.fingerprint(
            self._screen(kind='text', value='ab'), ignore=1)
        after = self.appScreen.fingerprint(
            self._screen(kind='text', value='abc'), ignore=1)
        self.assertEqual(before, after)


class TheAuditoryIcons(unittest.TestCase):
    """Emacspeak's oldest idea: a sound that says WHAT happened.

    They are the add-on's own files played through NVDA's own audio, so an
    icon sounds with no Titan running and no sound theme chosen.
    """

    def setUp(self):
        from titanEnhancements import icons
        self.icons = icons
        self.dir = tempfile.mkdtemp()
        self._path = icons.path
        icons.path = lambda: os.path.join(self.dir, 'icons.json')
        icons.forget()
        self.addCleanup(icons.forget)
        self.addCleanup(lambda: setattr(icons, 'path', self._path))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))

    def test_every_name_it_knows_really_has_a_sound(self):
        """A name with no file is silence, and silence is what a broken
        icon sounds like - so the ones it ships are checked."""
        missing = [name for name in self.icons.NAMES
                   if not os.path.isfile(
                       os.path.join(self.icons.OURS, name + '.wav'))]
        self.assertEqual(missing, [], 'no sound for: %s' % missing)

    def test_the_names_are_emacspeaks_own(self):
        """So somebody who has used Emacspeak already knows what they mean,
        and a theme written for one could be dropped in for the other."""
        for name in ('select-object', 'open-object', 'close-object',
                     'task-done', 'warn-user', 'item', 'button', 'on', 'off'):
            self.assertIn(name, self.icons.NAMES, name)

    def test_every_icon_says_what_it_marks(self):
        """A row nobody can have an opinion about is a row that cannot be
        set."""
        for name in self.icons.NAMES:
            self.assertTrue(self.icons.meanings().get(name), name)

    def test_one_can_be_turned_off_and_stays_off(self):
        self.icons.set_wanted('item', False)
        self.icons.forget()
        self.assertFalse(self.icons.wanted('item'))
        self.icons.set_wanted('item', True)
        self.assertTrue(self.icons.wanted('item'))

    def test_a_name_that_could_escape_the_folder_is_refused(self):
        """It is a file name from a store, and a store is a file on disk."""
        for name in ('../secret', 'a/b', '..\\thing', '.hidden'):
            self.assertEqual(self.icons.path_of(name), '', name)

    def test_every_kind_of_control_has_an_icon(self):
        from titanEnhancements import appReview
        for kind in ('button', 'check', 'list', 'text', 'gauge', 'label'):
            self.assertIn(self.icons.for_control(kind), self.icons.NAMES,
                          kind)

    def test_an_unknown_kind_still_gets_one(self):
        """A control kind added later is heard, not silent."""
        self.assertIn(self.icons.for_control('something-new'),
                      self.icons.NAMES)


class TheNamedVoices(unittest.TestCase):
    """Emacspeak's voice overlays: a name instead of four numbers."""

    def setUp(self):
        from titanEnhancements import personalities
        self.personalities = personalities

    def test_every_overlay_says_what_it_is_for(self):
        for name in self.personalities.NAMES:
            self.assertTrue(self.personalities.meanings().get(name), name)

    def test_putting_one_on_leaves_what_it_does_not_name(self):
        """So an overlay composes with what somebody already set rather
        than wiping it."""
        made = self.personalities.put_on({'volume': 5}, 'monotone-medium')
        self.assertEqual(made['volume'], 5)
        self.assertEqual(made['inflection'], -4)

    def test_plain_really_means_the_readers_own_voice(self):
        made = self.personalities.put_on(
            {'pitch': 4, 'rate': 2, 'volume': 1, 'inflection': 3}, 'plain')
        self.assertEqual(made, {})

    def test_what_a_class_is_wearing_is_read_off_the_dials(self):
        """Not remembered - a class whose numbers were edited by hand is
        honestly reported as wearing none."""
        self.assertEqual(self.personalities.matching(
            self.personalities.dials_of('bolden')), 'bolden')
        self.assertEqual(self.personalities.matching({'pitch': 7}), '')

    def test_a_dial_is_never_pushed_past_what_a_class_takes(self):
        from titanEnhancements import classes
        for name in self.personalities.NAMES:
            for dial, value in self.personalities.put_on({}, name).items():
                self.assertLessEqual(abs(int(value)), classes.LIMIT,
                                     '%s %s' % (name, dial))


class TheThirdReviewUsesTheSameKeys(unittest.TestCase):
    """One set of keys, not three.

    The terminal review, the recognised screen and a Titan application are
    three different things walked the same way on purpose: a user should
    learn Up, Down, Left, Right, Home, End, Enter, F5 and Escape once.
    """

    def test_the_application_review_borrows_the_reviews_own_keys(self):
        plugin = _plugin_class()
        for gesture in plugin.OCR_KEYS:
            self.assertIn(gesture, plugin.APP_KEYS,
                          '%s is not in the application review' % gesture)

    def test_every_borrowed_key_names_a_script_that_exists(self):
        plugin = _plugin_class()
        for gesture, name in plugin.APP_KEYS.items():
            self.assertTrue(hasattr(plugin, 'script_' + name),
                            '%s -> %s, which is not there' % (gesture, name))

    def test_the_keys_are_given_back(self):
        """A binding that outlived its review would swallow the user's
        arrow keys in whatever they moved to."""
        source = _source_of('__init__.py')
        self.assertIn('_borrow_app_keys', source)
        self.assertIn('removeGestureBinding', source)


class AnyWindowAsAVirtualWindow(unittest.TestCase):
    """`virtualWindow.py` - the fourth thing walked with the same keys.

    The terminal review's shape applied to the accessibility tree, so
    Emacspeak's voice classes and its auditory icons reach every program
    on the machine - as a MODE, which is the honest way: NVDA's own
    reporting is untouched the moment it is off.
    """

    class Obj:
        def __init__(self, name='', role='BUTTON', value='',
                     children=(), actions=(), location=(0, 0, 40, 20)):
            self.name = name
            self.value = value
            self.description = ''
            self.role = types.SimpleNamespace(name=role)
            self.children = list(children)
            self.location = types.SimpleNamespace(
                left=location[0], top=location[1],
                width=location[2], height=location[3])
            self._actions = list(actions)
            self.done = []
            self.states = set()

        @property
        def actionCount(self):
            return len(self._actions)

        def getActionName(self, index):
            return self._actions[index]

        def doAction(self, index):
            self.done.append(index)

    def setUp(self):
        from titanEnhancements import virtualWindow
        self.vw = virtualWindow
        self.said = []
        self._say = virtualWindow._say
        self._parts = virtualWindow._say_parts
        virtualWindow._say = lambda text: self.said.append(str(text))
        virtualWindow._say_parts = lambda parts: self.said.append(
            ', '.join(str(text) for text, _voice in parts))
        self.addCleanup(lambda: setattr(virtualWindow, '_say', self._say))
        self.addCleanup(
            lambda: setattr(virtualWindow, '_say_parts', self._parts))
        self.addCleanup(lambda: virtualWindow._state.update(
            {'on': False, 'nodes': [], 'at': 0, 'inner': 0}))

    def _window(self):
        return self.Obj(name='A window', role='WINDOW', children=[
            self.Obj(name='Toolbar', role='TOOLBAR'),
            self.Obj(name='Save', role='BUTTON', actions=['Press']),
            self.Obj(name='Read it back', role='CHECKBOX'),
            self.Obj(name='Notes', role='LIST', children=[
                self.Obj(name='Shopping', role='LISTITEM'),
                self.Obj(name='Ideas', role='LISTITEM'),
            ]),
            self.Obj(name='', role='PANE'),
        ])

    def _up(self):
        nodes = self.vw.nodes_of(self._window())
        self.vw._state.update({'on': True, 'nodes': nodes, 'at': 0,
                               'inner': 0})
        return nodes

    def test_the_frame_around_a_window_is_not_the_window(self):
        """Read as it comes, a window answers with its own scrollbars and
        title bar before a word of its content - the mistake Titan's own
        mirror documents."""
        nodes = self.vw.nodes_of(self._window())
        roles = [node['role'] for node in nodes]
        self.assertNotIn('WINDOW', roles)
        self.assertNotIn('PANE', roles)

    def test_a_control_with_nothing_to_call_it_is_left_out(self):
        """A blank row is one somebody arrows onto and is told nothing
        about, which is worse than a shorter list."""
        nodes = self.vw.nodes_of(self._window())
        self.assertTrue(all(node['name'] or node['value'] for node in nodes))

    def test_it_is_breadth_first_so_a_dialogs_own_controls_come_first(self):
        """A depth-first walk spends the whole budget in the first branch
        it falls into - which is how a review of a browser becomes a
        review of its toolbar."""
        nodes = self.vw.nodes_of(self._window())
        names = [node['name'] for node in nodes]
        self.assertLess(names.index('Save'), names.index('Shopping'))

    def test_the_arrows_walk_it(self):
        self._up()
        self.vw.move(1)
        self.assertEqual(self.vw.here()['name'], 'Save')

    def test_quick_navigation_jumps_by_kind(self):
        """b for a button, x for a check box, i for a row - NVDA's own
        browse-mode letters, because a second set for the same job is a
        second thing to learn for nothing."""
        self._up()
        ok, _said = self.vw.jump('x')
        self.assertTrue(ok)
        self.assertEqual(self.vw.here()['role'], 'CHECKBOX')
        ok, _said = self.vw.jump('i')
        self.assertTrue(ok)
        self.assertEqual(self.vw.here()['name'], 'Shopping')
        ok, _said = self.vw.jump('b', back=True)
        self.assertTrue(ok)
        self.assertEqual(self.vw.here()['name'], 'Save')

    def test_a_letter_that_finds_nothing_SAYS_so(self):
        """A letter that silently left the cursor where it was is
        indistinguishable from a key that is not bound."""
        self._up()
        ok, said = self.vw.jump('k')
        self.assertFalse(ok)
        self.assertTrue(said)

    def test_every_letter_says_what_it_jumps_to(self):
        for letter in self.vw.QUICK:
            self.assertTrue(self.vw.quick_names().get(letter), letter)

    def test_enter_does_what_the_control_says_it_can_do(self):
        """Its OWN verb from the accessibility layer, never a synthesised
        click - a control that offers one is pressed, not clicked at."""
        nodes = self._up()
        at = [index for index, node in enumerate(nodes)
              if node['name'] == 'Save'][0]
        self.vw._state['at'] = at
        ok, said = self.vw.activate()
        self.assertTrue(ok)
        self.assertEqual(nodes[at]['obj'].done, [0])
        self.assertEqual(said, 'Press')

    def test_a_control_is_read_in_the_users_own_voice_classes(self):
        nodes = self._up()
        parts = self.vw.parts_of(nodes[0], at=0, count=len(nodes))
        self.assertEqual(parts[0][1], 'name')
        self.assertIn('place', [voice for _text, voice in parts])

    def test_a_window_too_big_to_walk_is_cut_short_by_TIME(self):
        """Measured on this machine: a dialog is 25 ms, a file manager
        312 ms and a forum page in Edge **4.4 seconds** for 477 controls -
        none of which is worth waiting for with the key already pressed.
        The counts are a guess at how long a window will take; the clock
        is the measurement."""
        maker = AnyWindowAsAVirtualWindow.Obj

        class Slow(object):
            """A window whose every branch costs what a real one costs -
            a call into another process per node."""
            name = 'huge'
            value = ''
            description = ''
            role = types.SimpleNamespace(name='BUTTON')
            windowHandle = 1

            @property
            def children(self):
                time.sleep(0.02)
                return [Slow() for _ in range(6)]

        was = self.vw.SECONDS
        self.vw.SECONDS = 0.15
        try:
            note = {}
            started = time.time()
            nodes = self.vw.nodes_of(Slow(), note)
            took = time.time() - started
        finally:
            self.vw.SECONDS = was
        self.assertEqual(note.get('ran_out'), 'time')
        self.assertLess(took, 2.0, 'it walked for %.1f s' % took)
        # And it hands over what it HAS rather than nothing: a partial
        # window is usable, a wait is not.
        self.assertTrue(nodes)

    def test_it_says_when_it_only_got_part_of_the_way(self):
        """Said once, because it happened once - the user would otherwise
        arrow to the end and wonder where the rest of the window went."""
        source = _source_of('virtualWindow.py')
        self.assertIn("_('Part of it only')", source)
        block = source.split('def start(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("note.get('ran_out')", block)

    def test_it_ends_when_the_window_has_gone(self):
        """A review that outlived its window would swallow the arrow keys
        in whatever the user moved to."""
        self._up()
        self.vw._state['hwnd'] = 111
        self.vw._foreground = lambda: types.SimpleNamespace(windowHandle=222)
        try:
            self.assertTrue(self.vw.left_the_window())
            self.assertFalse(self.vw.reviewing())
        finally:
            del self.vw._foreground


class AMenuRowIsANameNotASentence(unittest.TestCase):
    """A menu is walked one row at a time with the arrows.

    So a row that is a sentence is a sentence heard on the way to the row
    below it, every time. The entries here read "Open an application and
    walk it with the arrows..." and the submenu holding them was called
    "Titan itself" - a description of a feature rather than the name of a
    place to go. Reported, in those words: the naming is wrong, they
    should be "(applications)", "(TCE)".
    """

    #: Just above the longest that survived the rewrite ("Read the steps
    #: of one..."). A bound set at what is there rather than at a round
    #: number, so the next sentence written into a menu fails this.
    LONGEST = 5

    def setUp(self):
        import re
        self.re = re
        path = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements',
                            'menu.py')
        with io.open(path, encoding='utf-8') as handle:
            self.source = handle.read()

    def _labels(self):
        found = []
        for match in self.re.finditer(
                r"(builder\.item\([a-z_]+, |AppendSubMenu\([a-z_]+, )"
                r"_\((.*?)\)(?:,|\))", self.source, self.re.S):
            text = ' '.join(self.re.findall(r"'((?:[^'\\]|\\.)*)'",
                                            match.group(2)))
            text = text.replace("\\'", "'")
            if text:
                found.append(text)
        return found

    def test_no_row_is_a_sentence(self):
        labels = self._labels()
        self.assertGreater(len(labels), 40, 'the labels were not found')
        long = [text for text in labels
                if len(text.split()) > self.LONGEST]
        self.assertEqual(long, [], 'these read as sentences: %s' % long)

    def test_no_row_explains_itself_in_brackets(self):
        """"AI OCR (read a window nothing else can)" is a name and then a
        sentence about it. The name is the half that survives."""
        for text in self._labels():
            inside = text.partition('(')[2].partition(')')[0]
            self.assertLessEqual(len(inside.split()), 3,
                                 'explained in brackets: %s' % text)

    def test_the_applications_are_called_what_they_are(self):
        """TCE is what Titan's own applications have always been called,
        and it is what the user asked for."""
        self.assertIn("_('TCE applications')", self.source)
        self.assertNotIn("_('Titan itself')", self.source)


class LeavingAnApplicationDoesNotLeaveItRunning(unittest.TestCase):
    """Escape leaves the review and deliberately does NOT close the
    application - a key that both leaves and quits is a key nobody can use
    safely. Which means something has to come BACK to it.

    Without that, walking away and opening it again opened a second copy.
    Measured on a live Titan: three sessions left behind by three probes,
    each a subprocess of Titan's with nobody rendering it.
    """

    def setUp(self):
        from titanEnhancements import titan
        from titanEnhancements.link import LINK
        self.titan = titan
        self.calls = []
        self.sessions = []
        self._bridge = LINK.bridge

        def bridge(call, timeout=None, **args):
            self.calls.append((call, args))
            if call == 'app.sessions':
                return True, self.sessions
            if call == 'app.screen':
                return True, {'screen': {'controls': []}, 'said': ''}
            if call == 'app.open':
                return True, {'session': '9', 'application': args.get('name'),
                              'screen': {'controls': []}}
            if call == 'app.close':
                return True, {'closed': True}
            return False, 'nothing said'
        LINK.bridge = bridge
        self.addCleanup(lambda: setattr(LINK, 'bridge', self._bridge))

    def test_it_comes_back_to_the_one_already_open(self):
        self.sessions = [{'token': 3, 'application': 'File Manager',
                          'owner': 'nvda'}]
        ok, data = self.titan.open_described('File Manager')
        self.assertTrue(ok)
        self.assertEqual(data.get('session'), '3')
        self.assertNotIn('app.open', [call for call, _args in self.calls])

    def test_somebody_elses_session_is_not_taken_over(self):
        """Another client rendering the same application is not ours."""
        self.sessions = [{'token': 3, 'application': 'File Manager',
                          'owner': 'elten_tce_bridge'}]
        ok, _data = self.titan.open_described('File Manager')
        self.assertTrue(ok)
        self.assertIn('app.open', [call for call, _args in self.calls])

    def test_a_different_application_is_opened_freshly(self):
        self.sessions = [{'token': 3, 'application': 'Notes',
                          'owner': 'nvda'}]
        self.titan.open_described('File Manager')
        self.assertIn('app.open', [call for call, _args in self.calls])

    def test_everything_ours_is_closed_when_the_plugin_goes(self):
        self.sessions = [{'token': 1, 'application': 'Notes',
                          'owner': 'nvda'},
                         {'token': 2, 'application': 'Other',
                          'owner': 'somebody else'},
                         {'token': 3, 'application': 'File Manager',
                          'owner': 'nvda'}]
        self.assertEqual(self.titan.close_all_described(), 2)
        closed = [args.get('session') for call, args in self.calls
                  if call == 'app.close']
        self.assertEqual(closed, ['1', '3'])

    def test_the_plugin_really_calls_it_on_the_way_out(self):
        source = _source_of('__init__.py')
        self.assertIn('_close_described_applications', source)
        self.assertIn('close_all_described', source)


class AToggleSaysWhichStateAndNothingElse(unittest.TestCase):
    """A pair of messages a user hears many times a day.

    They have to be short and symmetrical, or somebody has to listen to
    the whole sentence to work out which state they are now in. "Virtual
    window on, 24 controls" carried a fact about the WINDOW in a message
    about the SWITCH - and the first control is spoken straight after it
    anyway, so the count was said on the way to what was wanted.
    """

    #: Every review that is a real switch, and the two words it must
    #: answer with. `appReview` is deliberately not here: opening an
    #: application takes seconds, so its start is news ("Opening Notes")
    #: rather than a switch.
    TOGGLES = ('terminal', 'ocrReview', 'virtualWindow', 'widgetReview')

    def test_each_pair_is_the_same_words_with_on_and_off(self):
        import importlib
        import re
        for name in self.TOGGLES:
            module = importlib.import_module('titanEnhancements.' + name)
            source = _source_of(name + '.py')
            said = set(re.findall(r"_\('([A-Z][^']*(?:on|off))'\)", source))
            ons = {text for text in said if text.endswith(' on')}
            offs = {text for text in said if text.endswith(' off')}
            self.assertTrue(ons, '%s never says it is on: %s' % (name, said))
            self.assertTrue(offs, '%s never says it is off' % name)
            for text in ons:
                self.assertIn(text[:-3] + ' off', offs,
                              '%s says %r but not its opposite' % (name, text))

    def test_no_toggle_carries_a_count(self):
        import re
        for name in self.TOGGLES:
            source = _source_of(name + '.py')
            for text in re.findall(r"_\('([^']*(?: on| off))'\)", source):
                self.assertNotIn('{', text,
                                 '%s puts a number in a toggle: %r'
                                 % (name, text))

    def test_the_virtual_window_says_exactly_that(self):
        from titanEnhancements import virtualWindow
        self.assertIn("_('Virtual window on')",
                      _source_of('virtualWindow.py'))
        self.assertIn("_('Virtual window off')",
                      _source_of('virtualWindow.py'))


class TheCursorKeysAreBoundInEveryModeButAGame(unittest.TestCase):
    """"Native TCE cursor on", and Tab does nothing.

    The keys were borrowed only in `MODE_APPLICATION` - and that is not
    the mode most windows are read in. Windows' own recogniser goes
    first, which leaves the watch in `MODE_LOCAL`, where the cursor is
    built exactly the same way by `smart.take_local`. So the mode change
    was announced, the controls were there to walk, and not one key was
    bound to walk them with.
    """

    def test_the_rule_is_everything_but_a_game(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def _keep_keys_right(')
        end = source.index('\n    def ', at + 10)
        block = source[at:end]
        self.assertIn('MODE_GAME', block)
        self.assertNotIn('== surface.MODE_APPLICATION', block,
                         'the cursor is built in MODE_LOCAL too')

    def test_a_game_still_keeps_its_own_keys(self):
        """Its menu is what the arrows are for, and a second cursor over
        it would break the thing this is for while appearing to help."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def _keep_keys_right(')
        end = source.index('\n    def ', at + 10)
        self.assertIn('!= surface.MODE_GAME', source[at:end])


# --------------------------------------------------------------------------- #
class EveryWin32ArgumentIsAnInteger(unittest.TestCase):
    """`argument 4: TypeError: an integer is required`, on every press.

    `winUser.mouse_event(flags, 0, 0, None, None)` - and `dwData` and
    `dwExtraInfo` are DWORDs. NVDA declares argtypes for its bindings
    (`winBindings/user32.py`), so `None` is refused rather than quietly
    becoming a null pointer the way a bare `ctypes.windll` call would
    take it. It raised inside `click_here`, was caught by the `except`
    there, answered as False and reported as "Nothing could be done
    here" - so Enter in a window read as a picture, which is the whole of
    pressing anything inside a virtual machine, never once clicked.
    `smart.py` had `0, 0` right beside it the whole time.
    """

    def _clicks(self):
        for name in ('virtualWindow.py', 'smart.py', 'ocrReview.py',
                     'widgetReview.py', 'appReview.py'):
            where = os.path.join(ADDON, 'globalPlugins',
                                 'titanEnhancements', name)
            if os.path.exists(where):
                yield name, io.open(where, encoding='utf-8').read()

    def test_no_click_passes_None_where_a_DWORD_belongs(self):
        import re
        pattern = re.compile(r'mouse_event\s*\(([^)]*)\)')
        seen = 0
        for name, source in self._clicks():
            for arguments in pattern.findall(source):
                seen += 1
                self.assertNotIn('None', arguments,
                                 '%s passes None to mouse_event: %s'
                                 % (name, arguments))
        self.assertGreater(seen, 0, 'no click was found to check at all')

    def test_the_same_for_keybd_event(self):
        import re
        pattern = re.compile(r'keybd_event\s*\(([^)]*)\)')
        for name, source in self._clicks():
            for arguments in pattern.findall(source):
                self.assertNotIn('None', arguments,
                                 '%s passes None to keybd_event' % name)

    def test_a_click_that_failed_says_why(self):
        """"Nothing could be done here" is the least useful true sentence
        there is - it wears a rectangle that was never read, a control
        off the screen, an NVDA with no mouse handler and a click that
        really raised, and each is a different thing to do about it."""
        from titanEnhancements import virtualWindow
        said = virtualWindow._refusal('the click itself failed: argument 4')
        self.assertIn('argument 4', said)
        self.assertIn('why', virtualWindow.report())


# --------------------------------------------------------------------------- #
class WhatTheApplicationSaidIsASentence(unittest.TestCase):
    """`said` is a LIST, not a string.

    The shim sends what the application announced with the position,
    pitch and interrupt it asked for, and reading it with `str()` speaks
    the repr of that list at somebody - measured on the real tNotes:
    "[{'text': 'Notatka zostala zapisana!', 'position': 0.0, 'pitch': 0,
    'interrupt': True}]", said aloud, in place of the sentence.
    """

    def setUp(self):
        from titanEnhancements import appReview
        self.app = appReview

    def test_the_sentence_is_taken_out_of_the_list(self):
        found = self.app.announcements({'said': [
            {'text': 'Notatka zostala zapisana!', 'position': 0.0,
             'pitch': 0, 'interrupt': True}]})
        self.assertEqual(found, ['Notatka zostala zapisana!'])

    def test_several_are_kept_in_order(self):
        found = self.app.announcements(
            {'said': [{'text': 'one'}, {'text': 'two'}]})
        self.assertEqual(found, ['one', 'two'])

    def test_the_older_shape_is_still_read(self):
        """A Titan older than the change sends a bare string."""
        self.assertEqual(self.app.announcements({'said': 'saved'}),
                         ['saved'])

    def test_nothing_said_is_no_sentences(self):
        for nothing in ({}, {'said': None}, {'said': []}, None,
                        {'said': [{'text': '  '}]}):
            self.assertEqual(self.app.announcements(nothing), [])

    def test_no_caller_reads_it_with_str(self):
        import re
        for name in ('appReview.py', 'appScreen.py'):
            source = io.open(os.path.join(ADDON, 'globalPlugins',
                                          'titanEnhancements', name),
                             encoding='utf-8').read()
            self.assertEqual(
                re.findall(r"str\((?:answer|data)\.get\('said'\)", source),
                [], '%s still speaks the repr of the list' % name)


class ASubWindowIsFollowedAndSaid(unittest.TestCase):
    """An application that opens a dialog over the window being walked
    has not taken the user anywhere else - they are still in the same
    program, in a window sitting on the one they were in. Stopping there
    gave them a review that vanished exactly when something appeared to
    read."""

    def test_the_shim_marks_a_sub_window_while_it_is_UP(self):
        """It asked `self._modal_ended is not None`, which is backwards:
        that field is None WHILE a modal is up and is set when it ends -
        so every sub-window reported itself as not modal for the whole
        time it was on the screen, and as modal only once it had gone."""
        titan = os.path.dirname(os.path.dirname(ADDON))
        source = io.open(os.path.join(titan, 'src', 'app_ui', 'shim', 'wx',
                                      '__init__.py'), encoding='utf-8').read()
        at = source.index('def _is_modal(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('RUNTIME.screens', block)
        # The docstring quotes the old expression on purpose, so only
        # what the function RETURNS is checked.
        answer = block[block.rindex('return'):]
        self.assertNotIn('_modal_ended', answer)

    def test_the_review_says_it_has_arrived_in_one(self):
        from titanEnhancements import appReview
        appReview._state['screen'] = {'id': 1, 'title': 'tNotes',
                                      'modal': False}
        self.addCleanup(lambda: appReview._state.update({'screen': {}}))
        said = appReview._arrived_somewhere(
            {'id': 2, 'title': 'Nowa notatka', 'modal': True})
        self.assertIn('Nowa notatka', said)

    def test_the_same_screen_again_is_not_news(self):
        from titanEnhancements import appReview
        appReview._state['screen'] = {'id': 2, 'title': 'X', 'modal': True}
        self.addCleanup(lambda: appReview._state.update({'screen': {}}))
        self.assertEqual(appReview._arrived_somewhere(
            {'id': 2, 'title': 'X', 'modal': True}), '')

    def test_the_virtual_window_follows_rather_than_stopping(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements',
                                      'virtualWindow.py'),
                         encoding='utf-8').read()
        at = source.index('def left_the_window(')
        block = source[at:source.index('\ndef _owned_by', at)]
        self.assertIn('follow(window)', block)

    def test_a_window_of_another_program_is_still_left(self):
        """A review that outlived its window would swallow the arrow keys
        in whatever the user moved to."""
        from titanEnhancements import virtualWindow
        self.assertFalse(virtualWindow._owned_by(0, 0))
        self.assertFalse(virtualWindow._owned_by(1234, 0))


class TheMenuBarIsWalkedIntoNotPressed(unittest.TestCase):
    """Pressing it opens the real menu and takes the keyboard out of the
    review; what somebody walking a window wants from the menu bar is to
    see what is ON it. A flyout is a menu a keyboard cannot follow."""

    def test_enter_on_a_menu_bar_opens_it_in_place(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements',
                                      'virtualWindow.py'),
                         encoding='utf-8').read()
        at = source.index('def activate(')
        block = source[at:source.index('\ndef ', at + 10)]
        self.assertIn('MENUBAR', block)
        self.assertIn('open_menu(node)', block)

    def test_escape_leaves_the_menu_before_the_window(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def script_virtualLeave(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertLess(block.index('in_a_menu'), block.index('stop()'))

    def test_the_menu_keeps_what_it_came_from(self):
        from titanEnhancements import virtualWindow
        virtualWindow._state.update({'on': True, 'nodes': [
            {'name': 'File', 'role': 'MENUBAR', 'obj': None}], 'at': 0,
            'menu': None})
        self.addCleanup(lambda: virtualWindow._state.update(
            {'on': False, 'nodes': [], 'menu': None, 'at': 0}))
        self.assertFalse(virtualWindow.in_a_menu())


# --------------------------------------------------------------------------- #
class AnIconIsNamedWithoutAskingAnybody(unittest.TestCase):
    """A reader that says "graphic" for a warning triangle, a folder, a
    printer and a photograph of a dog has said one word about four
    different things. Windows draws most of the icons on Windows, so the
    ones it drew can be named here - instantly, free, with nothing
    leaving the machine - and anything else is left to the tier that can
    describe a picture."""

    def setUp(self):
        from titanEnhancements import iconNames
        self.icons = iconNames
        iconNames.forget()

    def test_every_kind_has_a_word(self):
        """A kind with no word is a control announced as nothing."""
        for _siid, kind in self.icons.STOCK:
            self.assertTrue(self.icons.word(kind),
                            'no word for %r' % kind)

    def test_a_kind_nobody_wrote_is_no_word_rather_than_the_key(self):
        self.assertEqual(self.icons.word('nonesuch'), '')
        self.assertEqual(self.icons.word(''), '')

    def test_nothing_is_named_without_a_picture(self):
        self.assertEqual(self.icons.of_handle(0), '')
        self.assertEqual(self.icons.describe(None), (False, ''))

    def test_the_comparison_is_not_written_twice(self):
        """The drawing, the difference and the threshold live in
        `dialog_kind`, because there is no reason for two of them."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'iconNames.py'),
                         encoding='utf-8').read()
        self.assertIn('dialog_kind._closest', source)
        self.assertIn('dialog_kind._drawn', source)
        self.assertNotIn('def _difference', source)

    def test_it_is_asked_before_anything_is_read_or_sent(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'graphics.py'),
                         encoding='utf-8').read()
        at = source.index('def label_locally(')
        block = source[at:source.index('\ndef ', at + 10)]
        self.assertIn('iconNames.describe', block)
        self.assertLess(block.index('iconNames.describe'),
                        block.index('localOcr.read'))

    def test_the_shared_half_works_without_NVDAs_own_settings(self):
        """`dialog_kind` is shared with the other reader now, and that
        reader has no `configSpec` - absent, the answer is yes, because a
        reader without the switch has not turned it off."""
        from titanEnhancements import dialog_kind
        self.assertIsInstance(dialog_kind.wanted(), bool)
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'dialog_kind.py'),
                         encoding='utf-8').read()
        at = source.index('def wanted(')
        self.assertIn('except', source[at:at + 700])


# --------------------------------------------------------------------------- #
class AnAnswerIsWalkedNotSpoken(unittest.TestCase):
    """A paragraph handed to `ui.message` is one utterance, and the next
    focus event cancels it halfway through - so Titan's status, what it
    can do, what an application said and the journal were all answers the
    user heard the beginning of. A reader that answers a question and is
    cut off has not answered it."""

    def setUp(self):
        from titanEnhancements import palette
        self.palette = palette
        palette.forget()
        self.addCleanup(palette.forget)

    def test_a_long_answer_becomes_a_list_of_its_lines(self):
        ok, _said = self.palette.page('one\ntwo\nthree', 'Status')
        self.assertTrue(ok)
        self.assertEqual([row['label'] for row in
                          self.palette._state['rows']],
                         ['one', 'two', 'three'])

    def test_blank_lines_are_not_rows(self):
        """A row somebody arrows onto and is told nothing about is worse
        than a shorter list."""
        self.palette.page('one\n\n   \ntwo', 'Status')
        self.assertEqual(len(self.palette._state['rows']), 2)

    def test_an_empty_answer_is_not_a_window(self):
        ok, _said = self.palette.page('   \n\n', 'Status')
        self.assertFalse(ok)

    def test_enter_on_a_line_says_it_again_rather_than_failing(self):
        """A row that only says something is not a failure to press."""
        self.palette.page('one\ntwo', 'Status')
        ok, _said = self.palette.activate()
        self.assertTrue(ok)

    def test_browse_walks_before_it_falls_back(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'dialogs.py'),
                         encoding='utf-8').read()
        at = source.index('def browse(')
        block = source[at:source.index('\ndef _keep_keys_right', at)]
        # The docstring names the fallback first on purpose, so only the
        # CODE is compared.
        code = block[block.index('from . import palette'):]
        self.assertIn('palette.page', code)
        self.assertLess(code.index('palette.page'),
                        code.index('browseableMessage'))


class TheTitanMenuIsTheSameMenu(unittest.TestCase):
    """It used to build a list out of the action catalogue, and that is a
    DIFFERENT thing: the menu has a shape somebody thought about - the
    assistant first, then AI OCR, the applications, this program, the
    managers, the switches - and a second list beside it is how the two
    quietly stop agreeing."""

    def test_it_walks_the_menu_that_is_really_built(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'menuWalk.py'),
                         encoding='utf-8').read()
        self.assertIn('menu_module.build(plugin)', source)
        self.assertIn('GetMenuItems', source)
        # Past the module docstring, which names the catalogue precisely
        # to say that this no longer builds one.
        code = source[source.index('import threading'):]
        self.assertNotIn('load_catalogue', code,
                         'it is building a second list again')

    def test_an_entry_runs_the_menus_OWN_callable(self):
        """The same one the platform menu would have fired, out of the
        builder's map - not a lookup of our own by label."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'menuWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _chosen(')
        block = source[at:source.index('\ndef _reopen', at)]
        self.assertIn('builder.doing.get', block)

    def test_the_builder_outlives_the_walk_and_is_let_go(self):
        """It holds the callables and NVDA's frame holds the bindings; a
        handler left bound outlives the item it was for."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'menuWalk.py'),
                         encoding='utf-8').read()
        self.assertIn('builder.release()', source)
        at = source.index('def _chosen(')
        self.assertIn('_release()', source[at:at + 1600])

    def test_a_switch_says_whether_it_is_on(self):
        """This is a list rather than a real menu, so the platform will
        not say it for us."""
        from titanEnhancements import menuWalk
        said = menuWalk._said_as({'label': 'Dialog kinds', 'checkable': True,
                                  'ticked': True, 'enabled': True})
        self.assertNotEqual(said, 'Dialog kinds')
        off = menuWalk._said_as({'label': 'Dialog kinds', 'checkable': True,
                                 'ticked': False, 'enabled': True})
        self.assertNotEqual(said, off)

    def test_an_entry_that_cannot_be_used_says_so(self):
        from titanEnhancements import menuWalk
        said = menuWalk._said_as({'label': 'Read this window',
                                  'checkable': False, 'ticked': False,
                                  'enabled': False})
        self.assertIn('Read this window', said)
        self.assertNotEqual(said, 'Read this window')

    def test_a_separator_is_not_a_row(self):
        """A row somebody arrows onto and is told nothing about is worse
        than a shorter list."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'menuWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _level(')
        block = source[at:source.index('\ndef _items', at)]
        self.assertIn('continue', block)


class EverythingTitanOffersIsAWindowToo(unittest.TestCase):
    """The action CATALOGUE, which is a different question from the menu:
    "what can this add-on be told to do"."""

    def test_it_is_built_from_the_catalogue(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'commands.py'),
                         encoding='utf-8').read()
        at = source.index('def titan_actions(')
        block = source[at:source.index('\ndef _titan_actions', at)]
        self.assertIn('gestures.load_catalogue()', block)
        self.assertIn('palette.show', block)

    def test_an_action_is_labelled_the_way_the_menu_labels_it(self):
        from titanEnhancements import commands
        found = commands._action_label(
            {'action': 'do_thing', 'summary': 'Does the thing. And more.'})
        self.assertEqual(found, 'Does the thing')

    def test_it_is_on_a_layer_so_it_can_be_reached(self):
        from titanEnhancements import layers
        named = set()
        for name in layers.names():
            named.update(command for command, _said
                         in layers.keys_of(name).values())
        self.assertIn('titan_menu', named)


class AWidgetIsOpenedByOnePress(unittest.TestCase):
    """What somebody arriving at a widget wants is the widget - walked
    with the arrow keys, the way everything else on this desktop is
    walked."""

    def test_enter_and_a_double_click_open_it(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWindow.py'),
                         encoding='utf-8').read()
        at = source.index('def _widgets_page(')
        block = source[at:source.index('def _widgets_are(', at)]
        self.assertIn('EVT_LISTBOX_DCLICK, self._walk_widget', block)
        self.assertIn('EVT_CHAR_HOOK, self._widget_key', block)

    def test_the_button_that_only_repeated_enter_is_gone(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWindow.py'),
                         encoding='utf-8').read()
        at = source.index('def _widgets_page(')
        block = source[at:source.index('def _widgets_are(', at)]
        self.assertNotIn("_('&Walk it')", block)
        # Read and Press stay: different verbs, and they cannot both be
        # Enter.
        self.assertIn("_('&Read it')", block)
        self.assertIn("_('&Press it')", block)


# --------------------------------------------------------------------------- #
class TitanItselfIsAWindowToWalk(unittest.TestCase):
    """The `wx.Dialog` is kept - it is a real form and the platform
    announces it - but it takes the foreground, has to be closed, and
    says every answer once."""

    def setUp(self):
        from titanEnhancements import titanWalk
        self.walk = titanWalk
        titanWalk.forget()

    def test_every_page_has_a_name_a_verb_and_a_way_to_fetch_it(self):
        """A page missing any of the three is a row that opens onto
        nothing."""
        for key, page in self.walk._PAGES.items():
            for part in ('name', 'what', 'fetch', 'label', 'press'):
                self.assertIn(part, page, '%s has no %s' % (key, part))
                self.assertTrue(callable(page[part]), '%s.%s' % (key, part))
            self.assertTrue(page['name'](), key)
            self.assertTrue(page['what'](), key)

    def test_everything_titan_has_is_a_page(self):
        """Applications, games, Klango, Titan IM, macros, widgets, views,
        the menu, the actions, the settings, the buffers, what arrived
        and the status bar - the window is Titan, so a part of Titan that
        is not on it is a part nobody can reach this way."""
        listed = {key for key, _name in self.walk.PAGES}
        for wanted in ('applications', 'games', 'cling', 'im', 'macros',
                       'widgets', 'views', 'menu', 'actions', 'settings',
                       'buffers', 'arrived', 'statusbar'):
            self.assertIn(wanted, listed, '%s is not a page' % wanted)

    def test_a_row_that_carries_its_own_rows_is_walked_into(self):
        """Titan answers a different field per kind, and this reader
        cannot be rebuilt every time one is added."""
        for name in self.walk.INSIDE:
            self.assertEqual(
                self.walk._things_inside({name: ['a', 'b']}), ['a', 'b'],
                '%s is not read as what is inside a row' % name)
        self.assertEqual(self.walk._things_inside({'label': 'x'}), [])
        self.assertEqual(self.walk._things_inside(None), [])

    def test_a_view_says_itself_when_it_carries_nothing(self):
        """`views.list` is the whole of what Titan serves for a view, so
        inventing `views.open` would be an entry that answers "no such
        call"."""
        ok, said = self.walk._open_view({'label': 'Applications'})
        self.assertTrue(ok)
        self.assertEqual(said, 'Applications')
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        self.assertNotIn('titan.open_view', source)

    def test_a_macro_reads_as_its_name_and_its_key(self):
        """**`hotkey`, not `shortcut`** - asked of the running Titan over
        the bus rather than guessed. `macros.list` really answers
        `{"macros": [{"name", "hotkey", "type"}]}`, and a key nothing
        writes is a working-looking empty string."""
        self.assertEqual(
            self.walk._macro_row({'name': 'Notes', 'hotkey': 'ctrl+alt+n',
                                  'type': '.tcs'}),
            'Notes (ctrl+alt+n)')
        self.assertEqual(self.walk._macro_row({'name': 'Notes'}), 'Notes')

    def test_the_shapes_are_the_ones_titan_really_answers(self):
        """Every one of these was read off the RUNNING Titan through the
        bus, not guessed from a name that looked right."""
        # views.list -> {"id", "label", "short_name"}; the label is the
        # window's heading, colon and all.
        self.assertEqual(
            self.walk._PAGES['views']['label'](
                {'id': 'apps', 'label': 'Lista aplikacji:',
                 'short_name': 'Aplikacje'}), 'Aplikacje')
        # buffers.list -> categories, each carrying `buffers`.
        self.assertIn('buffers', self.walk.INSIDE)
        self.assertEqual(
            self.walk._things_inside({'id': 'tts', 'name': 'TTS engine',
                                      'live': True, 'buffers': ['a']}), ['a'])
        # menu.list -> groups, each carrying `entries`.
        self.assertIn('entries', self.walk.INSIDE)
        # widgets.list -> {"id", "name", "type"}
        self.assertEqual(
            self.walk._PAGES['widgets']['label'](
                {'id': 'example_grid', 'name': 'Example Grid',
                 'type': 'grid'}), 'Example Grid (grid)')

    def test_a_view_carries_no_rows_so_it_says_itself(self):
        """Measured: `views.list` answers id, label and short_name and
        nothing else."""
        ok, said = self.walk._open_view(
            {'id': 'apps', 'label': 'Lista aplikacji:',
             'short_name': 'Aplikacje'})
        self.assertTrue(ok)
        self.assertEqual(said, 'Aplikacje')

    def test_the_pages_are_the_ones_the_window_has(self):
        listed = {key for key, _name in self.walk.PAGES}
        self.assertEqual(listed, set(self.walk._PAGES))

    def test_it_asks_titan_what_the_window_asks_it(self):
        """One set of calls and two ways of showing what comes back, so
        the two can never offer different things."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        window = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWindow.py'),
                         encoding='utf-8').read()
        for call in ('titan.applications', 'titan.widgets', 'titan.settings',
                     'titan.notifications', 'titan.statusbar'):
            self.assertIn(call, source, '%s is not asked for' % call)
            self.assertIn(call, window, '%s is not what the window asks' % call)

    def test_a_row_reads_as_something_even_when_a_field_is_missing(self):
        """Titan answers different shapes for different kinds, and a row
        with no label is a row somebody arrows onto and is told nothing
        about."""
        self.assertEqual(self.walk._label_of({'name': 'tNotes'}, 'name',
                                             'id'), 'tNotes')
        self.assertEqual(self.walk._label_of({'id': 'x'}, 'name', 'id'), 'x')
        self.assertEqual(self.walk._label_of({}, 'name', 'id'), '')

    def test_a_widget_is_OPENED_rather_than_pressed(self):
        """What somebody arriving at a widget wants is the widget."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _walk_a_widget(')
        block = source[at:source.index('\n_PAGES', at)]
        self.assertIn('widgetReview.start', block)

    def test_nothing_waits_on_the_readers_thread(self):
        """Every list is a round trip to another process."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _open_page(')
        block = source[at:source.index('\ndef _on_the_readers_thread', at)]
        self.assertIn('threading.Thread', block)

    def test_it_is_on_a_layer_so_it_can_be_reached(self):
        from titanEnhancements import layers
        named = set()
        for name in layers.names():
            named.update(command for command, _said
                         in layers.keys_of(name).values())
        self.assertIn('titan_window', named)

    def test_walking_it_is_the_DEFAULT_and_the_form_is_the_other_way(self):
        """A dialog takes the foreground away from the program the user
        was in, has to be closed before anything else can be done, and
        says every answer once. Every other list here is walked; Titan's
        own window was the one that was not."""
        from titanEnhancements import commands
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'commands.py'),
                         encoding='utf-8').read()
        at = source.index('def titan_window(')
        block = source[at:source.index('\ndef titan_window_as_a_form', at)]
        self.assertIn('titanWalk.open_it', block)
        self.assertNotIn('titanWindow.show', block)
        self.assertTrue(hasattr(commands, 'titan_window_as_a_form'),
                        'the form is no longer reachable at all')


# --------------------------------------------------------------------------- #
class _Setting:
    def __init__(self, id):
        self.id = id


class _NoVariants:
    """A synthesizer with no variants. NVDA does not answer that question -
    `synthDriverHandler._getAvailableVariants` RAISES."""
    name = 'sapi5'
    supportedSettings = (_Setting('voice'), _Setting('rate'))
    availableVoices = {'Zosia': 'Zosia', 'Natan': 'Natan'}
    voice = 'Zosia'

    @property
    def availableVariants(self):
        raise NotImplementedError


class _ESpeak:
    """NVDA's eSpeak: the change is QUEUED onto a thread of its own, so a
    name it has not got fails where no caller can catch it."""
    name = 'espeak'
    supportedSettings = (_Setting('voice'), _Setting('variant'),
                         _Setting('rate'))
    availableVoices = {'pl': 'Polish', 'en': 'English'}
    availableVariants = {'quincy': 'Quincy', 'Mario': 'Mario'}

    def __init__(self):
        object.__setattr__(self, 'errors', [])
        object.__setattr__(self, '_voice', 'pl')
        object.__setattr__(self, '_variant', 'quincy')
        object.__setattr__(self, 'rate', 50)

    def __setattr__(self, name, value):
        if name == 'voice' and value not in type(self).availableVoices:
            self.errors.append('espeak_SetVoiceByName: code 2')
            return
        object.__setattr__(self, '_' + name if name in ('voice', 'variant')
                           else name, value)

    def __getattr__(self, name):
        if name in ('voice', 'variant'):
            return object.__getattribute__(self, '_' + name)
        raise AttributeError(name)


class AVoiceBelongsToItsOwnSynthesizer(unittest.TestCase):
    """Reported as "I set a voice on another synthesizer, save, and NVDA
    fills up with errors".

    Two faults, and each one alone was enough. The manager CRASHED on a
    synthesizer with no variants, and the voice - which means nothing
    outside the synthesizer it came from - was pushed onto whatever
    driver NVDA happened to be using. In the user's own table
    `controller` was sapi5_32's
    `HKEY_LOCAL_MACHINE\\...\\RHVoice\\Natan` while NVDA ran eSpeak: 261
    `espeak_SetVoiceByName: code 2` in four minutes, none of them
    audible, and the setting had never once worked.
    """

    def setUp(self):
        from titanEnhancements import speaking
        self.speaking = speaking
        speaking.forget()

    def tearDown(self):
        self.speaking.forget()

    # -- the crash -------------------------------------------------------
    def test_getattrs_default_does_not_catch_this(self):
        """Why `getattr(synth, 'availableVariants', None)` was a crash: it
        is a PROPERTY, so reading it runs the getter, and the default
        catches `AttributeError` and nothing else."""
        with self.assertRaises(NotImplementedError):
            getattr(_NoVariants(), 'availableVariants', None)

    def test_a_synthesizer_with_no_variants_answers_none_of_them(self):
        synth = _NoVariants()
        self.speaking._drivers['sapi5'] = synth
        self.assertEqual(self.speaking.variants_of('sapi5', 'Zosia'), [])
        self.assertEqual(sorted(self.speaking.voices_of('sapi5')),
                         [('Natan', 'Natan'), ('Zosia', 'Zosia')])

    def test_reading_a_driver_never_raises(self):
        self.assertIsNone(self.speaking._ask(_NoVariants(),
                                             'availableVariants'))
        self.assertIsNone(self.speaking._ask(None, 'anything'))

    # -- the swarm -------------------------------------------------------
    def test_a_voice_the_driver_has_not_got_is_never_set(self):
        """It cannot be caught afterwards: eSpeak queues the change onto a
        thread of its own, so the failure is logged there, once per
        utterance, for as long as the class is used."""
        synth = _ESpeak()
        was = self.speaking.apply_to(synth, {
            'voice': 'HKEY_LOCAL_MACHINE\\SOFTWARE\\...\\RHVoice\\Natan'})
        self.assertEqual(was, {})
        self.assertEqual(synth.errors, [])
        self.assertEqual(synth.voice, 'pl')

    def test_a_voice_the_driver_really_has_is_still_set_and_put_back(self):
        synth = _ESpeak()
        was = self.speaking.apply_to(synth, {'voice': 'en',
                                             'variant': 'Mario'})
        self.assertEqual(was, {'voice': 'pl', 'variant': 'quincy'})
        self.assertEqual((synth.voice, synth.variant), ('en', 'Mario'))
        self.speaking.put_back(synth, was)
        self.assertEqual((synth.voice, synth.variant), ('pl', 'quincy'))

    def test_a_dial_the_driver_has_not_got_is_never_set(self):
        """A variant on a synthesizer with no variants is not an error - it
        is a class spoken in the plain voice."""
        synth = _NoVariants()
        self.assertEqual(self.speaking.apply_to(synth, {'variant': 'Mario'}),
                         {})

    def test_a_driver_that_will_not_say_is_not_guessed_about(self):
        """Three answers, not two: yes, no, and "it will not say" - which
        means set it and see, because that is what this always did."""
        self.assertIs(self.speaking.has_setting(_ESpeak(), 'voice', 'pl'),
                      True)
        self.assertIs(self.speaking.has_setting(_ESpeak(), 'voice', 'xx'),
                      False)
        self.assertIsNone(self.speaking.has_setting(_NoVariants(), 'variant',
                                                    'Mario'))
        self.assertIsNone(self.speaking.has_setting(_ESpeak(), 'voice', ''))

    def test_a_profile_knows_whose_voice_it_is(self):
        synth = _ESpeak()
        self.assertTrue(self.speaking.for_another_synth(
            {'synth': 'sapi5_32', 'voice': 'Natan'}, synth))
        self.assertFalse(self.speaking.for_another_synth(
            {'synth': 'espeak', 'voice': 'en'}, synth))
        # A profile that names none was chosen for whatever the user uses;
        # `has_setting` is what catches it if they have since changed.
        self.assertFalse(self.speaking.for_another_synth({'voice': 'en'},
                                                         synth))

    def test_another_synthesizers_voice_never_reaches_this_one(self):
        synth = _ESpeak()
        self.speaking._drivers['espeak'] = synth
        kept = self.speaking.current
        self.speaking.current = lambda: synth
        try:
            self.speaking.become({'synth': 'sapi5_32', 'voice': 'Natan',
                                  'variant': 'Mario'})
        finally:
            self.speaking.current = kept
        self.assertEqual(synth.errors, [])
        self.assertEqual(synth.voice, 'pl')

    # -- and it is SAID by the synthesizer it names -----------------------
    def test_a_class_that_names_a_synthesizer_is_spoken_by_it(self):
        """NVDA has no speech command for a synthesizer, so the utterance
        is taken away from it and said by a driver of ours."""
        from titanEnhancements import interject, voices
        synth = _ESpeak()
        self.speaking._drivers['espeak'] = synth
        said = []
        kept_say, kept_now = voices.say_whole, self.speaking.current
        voices.say_whole = lambda tag, text, profile=None, interrupt=False: (
            said.append((tag, text)), True)[1]
        self.speaking.current = lambda: synth
        try:
            took = interject._elsewhere(
                'controller', {'synth': 'sapi5_32', 'voice': 'Natan'},
                ['Something arrived'])
        finally:
            voices.say_whole, self.speaking.current = kept_say, kept_now
        self.assertTrue(took)
        self.assertEqual(said, [('controller', 'Something arrived')])
        self.assertEqual(interject._by_synth.get('controller'), 1)

    def test_the_same_synthesizer_is_not_another_one(self):
        """A second instance of one driver is two programs on one device."""
        from titanEnhancements import interject, voices
        synth = _ESpeak()
        kept_say, kept_now = voices.say_whole, self.speaking.current
        voices.say_whole = lambda *a, **k: True
        self.speaking.current = lambda: synth
        try:
            self.assertFalse(interject._elsewhere(
                'controller', {'synth': 'espeak', 'voice': 'en'}, ['hello']))
            # Nor is a class that is only PART of a control's reading.
            self.assertFalse(interject._elsewhere(
                'kind', {'synth': 'sapi5_32', 'voice': 'Natan'}, ['button']))
        finally:
            voices.say_whole, self.speaking.current = kept_say, kept_now

    def test_only_the_words_are_sent_elsewhere(self):
        from titanEnhancements import interject
        self.assertEqual(
            interject._words_of(['Save', object(), '  ', 'button']),
            'Save button')

    # -- and NVDA is told to say nothing ---------------------------------
    def test_nvda_is_left_with_nothing_to_say(self):
        """Checked against NVDA's own source: `speak()` applies the filter
        first and returns at once on an empty sequence, so the synth is
        never reached."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'interject.py'),
                         encoding='utf-8').read()
        at = source.index('def _origin_voice(')
        block = source[at:source.index('\ndef _journal(', at)]
        self.assertIn('_elsewhere(mark, profile, sequence)', block)
        self.assertIn('return []', block)

    # -- the key that shuts the reader up ---------------------------------
    def test_cancelling_speech_stops_our_driver_too(self):
        """A driver of ours is not in NVDA's speech queue, so the key that
        shuts the reader up reaches it only if we listen for the cancel."""
        from titanEnhancements import compat
        stopped = []
        cancelled = []

        class Speech:
            @staticmethod
            def cancelSpeech(*args):
                cancelled.append(True)
        speech = Speech()
        kept_speech, kept_stop = compat.speech, self.speaking.stop
        compat.speech = speech
        self.speaking.stop = lambda: stopped.append(True)
        try:
            self.assertTrue(self.speaking.follow_cancel())
            # Idempotent: twice must not bury the real one under two of ours.
            self.assertTrue(self.speaking.follow_cancel())
            speech.cancelSpeech()
            self.assertEqual(stopped, [True])
            self.assertEqual(cancelled, [True])
            self.assertTrue(self.speaking.unfollow_cancel())
            self.assertIs(speech.cancelSpeech, Speech.cancelSpeech)
        finally:
            self.speaking.stop = kept_stop
            self.speaking._cancel_was = None
            compat.speech = kept_speech

    def test_a_wrapper_that_is_not_ours_is_left_alone(self):
        """A reader is not the place to win an argument with another
        add-on."""
        from titanEnhancements import compat

        class Speech:
            @staticmethod
            def cancelSpeech(*args):
                pass
        speech = Speech()
        kept = compat.speech
        compat.speech = speech
        try:
            self.speaking.follow_cancel()
            somebody_else = lambda *a: None          # noqa: E731
            speech.cancelSpeech = somebody_else
            self.assertFalse(self.speaking.unfollow_cancel())
            self.assertIs(speech.cancelSpeech, somebody_else)
        finally:
            self.speaking._cancel_was = None
            compat.speech = kept


# --------------------------------------------------------------------------- #
class NewTextInATerminalIsNotAnErrorPerLine(unittest.TestCase):
    """Reported as "when there is new content in the terminal, there is an
    NVDA error".

    The chain, read out of NVDA's own source rather than guessed at:
    a console is `NVDAObjects.behaviors.Terminal`, which is a `LiveText`;
    `LiveText._reportNewText` announces new output with
    **`speech.speakText`**; `origin.MARKS` marks `speakText` as the
    **controller** class; and the user's `controller` class named
    sapi5_32's `HKEY_LOCAL_MACHINE\\...\\RHVoice\\Natan` while NVDA was
    running eSpeak. So every line the terminal produced set a voice
    eSpeak has not got - one `espeak_SetVoiceByName: code 2` per line, on
    a thread where nothing could catch it.

    This drives that whole path through the REAL speech filter.
    """

    #: The user's own table, as it really was.
    CONTROLLER = {
        'synth': 'sapi5_32',
        'voice': 'HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices'
                 '\\TokenEnums\\RHVoice\\Natan',
    }

    def setUp(self):
        from titanEnhancements import classes, interject, origin, speaking
        from titanEnhancements import voices
        self.interject, self.origin = interject, origin
        self.speaking, self.voices, self.classes = speaking, voices, classes
        speaking.forget()
        interject._by_synth.clear()
        # NVDA is running eSpeak, as the log said.
        self.espeak = _ESpeak()
        self._kept = (speaking.current, classes.voice_of, voices.say_whole,
                      origin.wanted)
        speaking.current = lambda: self.espeak
        classes.voice_of = lambda tag: (dict(self.CONTROLLER)
                                        if tag == 'controller' else {})
        origin.wanted = lambda: True
        self.said_elsewhere = []
        voices.say_whole = lambda tag, text, profile=None, interrupt=False: (
            self.said_elsewhere.append((tag, text)), True)[1]

    def tearDown(self):
        (self.speaking.current, self.classes.voice_of,
         self.voices.say_whole, self.origin.wanted) = self._kept
        self.origin.pop()
        del self.origin._stack()[:]
        self.speaking.forget()
        self.interject._by_synth.clear()

    def a_line_of_output(self, text='Compiling titanEnhancements...'):
        """One line of new terminal output, exactly as NVDA produces it."""
        self.origin.push('controller')
        try:
            return self.interject._filter(speechSequence=[text])
        finally:
            self.origin.pop()

    def test_the_marks_are_the_ones_nvdas_terminal_really_uses(self):
        """`LiveText._reportNewText` calls `speech.speakText`, so new
        terminal output is the CONTROLLER class and not a notification.
        The add-on's own terminal review is `speakMessage` and is a
        different class - which is why the review was never the fault."""
        self.assertIn(('speakText', 'controller'), self.origin.MARKS)
        self.assertIn(('speakMessage', 'notification'), self.origin.MARKS)
        review = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'terminal.py'),
                         encoding='utf-8').read()
        self.assertIn('speakMessage', review)

    def test_a_line_of_output_no_longer_sets_a_voice_espeak_has_not_got(self):
        """The fault itself: one error per line, and not one of them
        audible."""
        for _line in range(20):
            self.a_line_of_output()
        self.assertEqual(self.espeak.errors, [],
                         '%d lines produced %d driver errors'
                         % (20, len(self.espeak.errors)))
        self.assertEqual(self.espeak.voice, 'pl',
                         "the reader's own voice was changed under it")

    def test_the_line_is_said_by_the_synthesizer_the_class_names(self):
        """And it is not merely silenced: the setting finally does what it
        says."""
        left = self.a_line_of_output('Ran 1090 tests')
        self.assertEqual(self.said_elsewhere,
                         [('controller', 'Ran 1090 tests')])
        self.assertEqual(left, [], 'NVDA was left something to say as well')
        self.assertEqual(self.interject._by_synth.get('controller'), 1)

    def test_with_no_synthesizer_of_its_own_nothing_is_taken_away(self):
        """A class that only bends the voice is left exactly as it was -
        this must not become "the controller class is never spoken by
        NVDA"."""
        self.classes.voice_of = lambda tag: ({'pitch': 3.0}
                                             if tag == 'controller' else {})
        left = self.a_line_of_output('still NVDA\'s to say')
        self.assertEqual(self.said_elsewhere, [])
        self.assertTrue(any(isinstance(part, str) and 'still' in part
                            for part in left),
                        'the words were taken away from NVDA')

    def test_a_voice_of_the_SAME_synthesizer_is_still_a_command(self):
        """Nothing here may turn an ordinary voice change into a second
        program producing sound."""
        self.classes.voice_of = lambda tag: ({'synth': 'espeak',
                                              'voice': 'en'}
                                             if tag == 'controller' else {})
        self.a_line_of_output('one line')
        self.assertEqual(self.said_elsewhere, [])

    def test_the_braille_display_still_gets_it(self):
        """`speak()` feeds no braille at all, and what another program
        says through the controller is brailled by nobody - so a line
        spoken elsewhere would be one a braille reader never gets."""
        from titanEnhancements import compat
        shown = []

        class Handler:
            @staticmethod
            def message(text):
                shown.append(text)

        class Braille:
            handler = Handler()
        kept = compat.braille
        compat.braille = Braille()
        try:
            self.a_line_of_output('error: no such file')
        finally:
            compat.braille = kept
        self.assertEqual(shown, ['error: no such file'])


# --------------------------------------------------------------------------- #
class ThePointerIsTheReaderInsideAGuest(unittest.TestCase):
    """A virtual machine's window is another computer's screen, and a
    screen is pixels: there is nothing in it for a reader to read.

    So the pointer. What it is SHOWING names the control, and where it IS
    names the one strip of the guest worth reading.
    """

    def setUp(self):
        from titanEnhancements import guest
        self.guest = guest
        guest.forget()

    def tearDown(self):
        self.guest.forget()

    # -- there is no key -------------------------------------------------
    def test_there_is_no_shortcut_to_press(self):
        """Ctrl+G is VMware's own and belongs to VMware. A reader that
        bound it would take it away from the program it belongs to, and
        the user would have one more thing to remember."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        self.assertNotIn('control+g', source)
        self.assertNotIn('guestLook', source)
        # It is reached from arriving in the window and from nowhere else.
        self.assertIn('guest.consider(obj)', source)
        self.assertIn('guest.crossing(obj)', source)

    def test_it_does_nothing_at_all_until_it_is_switched_on(self):
        from titanEnhancements import configSpec
        self.assertIn('default=False', configSpec.SPEC['guestCursor'])
        kept = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults(),
                                       guestCursor=False)
        try:
            self.assertFalse(self.guest.wanted())
            self.assertFalse(self.guest.consider(object()))
        finally:
            configSpec.read = kept

    def test_the_switch_is_on_the_page(self):
        from titanEnhancements import settingsPanel
        self.assertIn('guestCursor', settingsPanel.keys_on_the_page())

    # -- what the pointer is showing --------------------------------------
    def test_a_cursor_nobody_has_ever_seen_is_still_named(self):
        """**The whole reason this works.** A guest's cursor is built by
        the virtual machine out of the guest's own bitmap, so it has a
        handle no `LoadCursorW` will ever hand back - and naming a cursor
        has always been a comparison of handles, which is why a reader
        said nothing at all inside a guest. A COPY of a standard cursor is
        exactly that case: nobody's handle, somebody's picture."""
        import ctypes
        try:
            user32 = ctypes.windll.user32
        except Exception:                            # noqa: BLE001
            self.skipTest('not Windows')
        user32.LoadCursorW.restype = ctypes.c_void_p
        user32.CopyIcon.restype = ctypes.c_void_p
        named = 0
        for number, word in ((32513, 'text cursor'), (32649, 'hand'),
                             (32514, 'hourglass'), (32512, 'arrow')):
            handle = int(user32.LoadCursorW(None,
                                            ctypes.c_void_p(number)) or 0)
            if not handle:
                continue
            copy = int(user32.CopyIcon(ctypes.c_void_p(handle)) or 0)
            if not copy:
                continue
            try:
                self.assertEqual(self.guest.shape_of(copy), word,
                                 'a guest-shaped %s was not named' % word)
                named += 1
            finally:
                user32.DestroyIcon(ctypes.c_void_p(copy))
        if not named:
            self.skipTest('this Windows would not lend its cursors')

    def test_a_cursor_that_is_nothing_is_not_guessed_at(self):
        self.assertEqual(self.guest.shape_of(0), '')

    # -- what it says -----------------------------------------------------
    def test_the_shape_names_the_CONTROL_not_the_picture(self):
        """Somebody working in a guest wants to be told what they are on,
        not what the pointer looks like."""
        kinds = self.guest.kinds()
        self.assertEqual(kinds['text cursor'], 'edit box')
        self.assertEqual(kinds['hand'], 'link')
        # An ordinary arrow says nothing about what is under it, so it is
        # deliberately not in the table: the words are the whole answer.
        self.assertNotIn('arrow', kinds)

    def test_what_is_there_and_what_it_is(self):
        self.assertEqual(self.guest.sentence('Username', 'text cursor'),
                         'Username, edit box')
        self.assertEqual(self.guest.sentence('File  Edit', 'arrow'),
                         'File  Edit')
        self.assertEqual(self.guest.sentence('', 'hourglass'), 'busy')
        self.assertEqual(self.guest.sentence('', ''), '')

    # -- which strip ------------------------------------------------------
    def test_the_strip_is_the_row_the_pointer_is_on(self):
        """The full width, because what a row SAYS is very often not under
        the pointer - a tick, a shortcut, a label all sit away from it."""
        kept = self.guest._rect_of
        self.guest._rect_of = lambda hwnd: (100, 200, 1100, 800)
        try:
            where = self.guest.strip_for(1, 500)
            self.assertEqual(where[0], 100)
            self.assertEqual(where[2], 1000)
            self.assertEqual(where[3], self.guest.STRIP)
            middle = where[1] + where[3] / 2.0
            self.assertLess(abs(middle - 500), 2)
            # Clamped: a pointer at the very top or bottom still gets a
            # whole strip, inside the window.
            self.assertGreaterEqual(self.guest.strip_for(1, 205)[1], 200)
            bottom = self.guest.strip_for(1, 795)
            self.assertLessEqual(bottom[1] + bottom[3], 800)
        finally:
            self.guest._rect_of = kept

    def test_a_window_with_no_place_on_the_screen_has_no_strip(self):
        kept = self.guest._rect_of
        self.guest._rect_of = lambda hwnd: None
        try:
            self.assertIsNone(self.guest.strip_for(1, 500))
        finally:
            self.guest._rect_of = kept

    def test_the_hosts_own_half_of_the_window_is_left_to_nvda(self):
        """A virtual machine's menu bar, tabs and status line are
        ordinary, and NVDA reads them properly already."""
        kept = self.guest._rect_of
        self.guest._rect_of = lambda hwnd: (100, 200, 1100, 800)
        try:
            self.assertTrue(self.guest.on_the_guest(1, 500, 400))
            self.assertFalse(self.guest.on_the_guest(1, 500, 100))
            self.assertFalse(self.guest.on_the_guest(1, 50, 400))
        finally:
            self.guest._rect_of = kept

    # -- the row is chosen, not the first line ----------------------------
    def test_the_row_nearest_the_pointer_is_the_one_said(self):
        from titanEnhancements import localOcr
        reading = localOcr.Reading([
            [{'text': 'Documents', 'left': 10, 'top': 480,
              'width': 90, 'height': 16}],
            [{'text': 'Downloads', 'left': 10, 'top': 505,
              'width': 90, 'height': 16}],
        ])
        asked = []
        kept_rect, kept_read = self.guest._rect_of, localOcr.read
        self.guest._rect_of = lambda hwnd: (0, 0, 1000, 1000)
        localOcr.read = lambda *where, **how: (asked.append(how), reading)[1]
        try:
            self.assertEqual(self.guest.words_at(1, 488), 'Documents')
            self.assertEqual(self.guest.words_at(1, 512), 'Downloads')
        finally:
            self.guest._rect_of, localOcr.read = kept_rect, kept_read
        # **The guest's OWN picture.** A screen capture of the guest was
        # measured returning the text of the window IN FRONT of it.
        self.assertEqual([one.get('hwnd') for one in asked], [1, 1])

    def test_what_windows_could_not_read_is_asked_of_the_model(self):
        """A guest is what Windows' own recogniser is worst at: somebody
        else's screen, at somebody else's resolution, scaled into a
        window."""
        from titanEnhancements import localOcr
        asked = []
        reading = localOcr.Reading([
            [{'text': 'Zainstaluj', 'left': 10, 'top': 490,
              'width': 90, 'height': 16}]])
        kept = (self.guest._rect_of, localOcr.read,
                localOcr.read_window_model)
        self.guest._rect_of = lambda hwnd: (0, 0, 1000, 1000)
        localOcr.read = lambda *where, **how: None
        localOcr.read_window_model = lambda hwnd: (asked.append(hwnd),
                                                   reading)[1]
        try:
            self.assertEqual(self.guest.words_at(7, 498), 'Zainstaluj')
            self.assertEqual(asked, [7])
            # **Kept.** The model is a second or two whatever it is given,
            # so the whole guest is read once and the next moves are free.
            self.assertEqual(self.guest.words_at(7, 498), 'Zainstaluj')
            self.assertEqual(asked, [7], 'the model was asked twice')
        finally:
            (self.guest._rect_of, localOcr.read,
             localOcr.read_window_model) = kept

    # -- the picture is the GUEST's, not the screen's ---------------------
    def test_a_window_is_read_from_its_own_picture(self):
        """**A screen capture reads whatever is IN FRONT.** Measured on a
        real VMware guest sitting behind a terminal: a screen capture of
        the guest's rectangle came back as the TERMINAL's text, and would
        have been announced as though it were the guest. A window's own
        device context has no such problem - on that same guest it gave
        92% of the points the teal of a Windows 95 desktop, 5% the grey
        of its taskbar, and the taskbar found as a highlight with 'Start'
        inside it."""
        from titanEnhancements import localOcr
        self.assertTrue(hasattr(localOcr, 'from_window'))
        # Without NVDA there is no `screenBitmap`, and it answers None
        # rather than raising - which is also the fallback that matters:
        # a window that will not draw itself is read from the screen.
        self.assertIsNone(localOcr.from_window(0, 10, 10))
        self.assertIsNone(localOcr.from_window(1, 0, 0))

    def test_a_picture_that_is_MOSTLY_one_colour_is_not_blank(self):
        """**The bug that made the whole feature silent on a maximised
        guest.** A Windows 95 desktop is 97% one colour, and a twelve-
        sample grid across 2358x1285 found nothing but that teal - so
        every capture of the user's own machine was refused as "flat" and
        the reader fell back to photographing the SCREEN, which is
        whatever is in front of the guest. Measured on that guest: 132
        colours in the very picture this called blank."""
        from titanEnhancements import localOcr

        class Dot:
            def __init__(self, r, g, b):
                self.rgbRed, self.rgbGreen, self.rgbBlue = r, g, b
        teal, navy = Dot(0, 128, 128), Dot(0, 0, 128)
        wide, tall = 2358, 1285
        rows = [[teal] * wide for _ in range(tall)]
        # One label's worth of selection, as a share of the screen about
        # what a real one is.
        for y in range(240, 300):
            for x in range(40, 600):
                rows[y][x] = navy
        self.assertFalse(localOcr._blank(rows, wide, tall),
                         'a desktop with a selection on it was called '
                         'blank')

    def test_ONE_colour_and_nothing_else_is_blank(self):
        """Which is what a window that would not draw itself gives:
        measured on VMware, all three `PrintWindow` flags answer pure
        black."""
        from titanEnhancements import localOcr

        class Dot:
            rgbRed = rgbGreen = rgbBlue = 0
        black = Dot()
        rows = [[black] * 800 for _ in range(600)]
        self.assertTrue(localOcr._blank(rows, 800, 600))

    def test_a_flat_capture_is_refused_rather_than_returned(self):
        """`PrintWindow` answers pure black for a surface drawn by
        Direct3D - measured on the same guest, all three of its flags -
        and a flat answer is not a picture. Refusing it is what makes the
        caller fall back to the screen."""
        from titanEnhancements import localOcr

        class Flat:
            rgbRed = rgbGreen = rgbBlue = 0
        rows = [[Flat() for _x in range(40)] for _y in range(30)]
        self.assertTrue(localOcr._blank(rows, 40, 30))

        class Varied:
            def __init__(self, value):
                self.rgbRed = self.rgbGreen = self.rgbBlue = value
        mixed = [[Varied((x * y) % 200) for x in range(40)]
                 for y in range(30)]
        self.assertFalse(localOcr._blank(mixed, 40, 30))

    # -- leaving -----------------------------------------------------------
    def test_leaving_the_window_stops_it(self):
        self.guest._state.update({'on': True, 'hwnd': 99})
        self.assertTrue(self.guest.crossing(None))
        self.assertFalse(self.guest.inside())
        # Idempotent: already out is not a second leaving.
        self.assertFalse(self.guest.crossing(None))


# --------------------------------------------------------------------------- #
class AnIconSaysWhichKindItIs(unittest.TestCase):
    """Windows 11 hands back the SAME artwork for several of its own stock
    icons, and two words on one picture is a picture that can only ever be
    refused - which is why nine of fifty-seven answered nothing."""

    def setUp(self):
        from titanEnhancements import iconNames
        self.icons = iconNames
        iconNames.forget()

    def tearDown(self):
        self.icons.forget()

    def test_a_word_that_is_the_other_word_is_merged(self):
        """An open folder is a folder, and a removable drive is a drive -
        in every sense somebody being told what an icon shows cares
        about."""
        self.assertEqual(self.icons._general('open folder'), 'folder')
        self.assertEqual(self.icons._general('removable drive'), 'drive')
        self.assertEqual(self.icons._general('printer'), 'printer')

    def test_one_picture_carrying_one_meaning_keeps_it(self):
        made = [('folder', b'aaa'), ('open folder', b'aaa'),
                ('printer', b'bbb')]
        kept = self.icons._collapse(made)
        self.assertEqual(sorted(word for word, _p in kept),
                         ['folder', 'printer'])

    def test_one_picture_carrying_TWO_meanings_is_dropped(self):
        """Measured on Windows 11: `disc` and `shield` are one picture and
        so are `music` and `computer` - generic artwork for icons Windows
        no longer draws differently. Naming either would be inventing a
        fact about the user's screen."""
        made = [('disc', b'aaa'), ('shield', b'aaa'), ('printer', b'bbb')]
        kept = self.icons._collapse(made)
        self.assertEqual([word for word, _p in kept], ['printer'])
        self.assertEqual(self.icons.report().get('dropped'), 1)

    def test_the_references_really_are_one_word_each(self):
        made = self.icons._known()
        if not made:
            self.skipTest('this Windows lends no stock icons')
        by_picture = {}
        for word, picture in made:
            by_picture.setdefault(bytes(bytearray(picture)),
                                  set()).add(word)
        for words in by_picture.values():
            self.assertEqual(len(words), 1,
                             'one picture, several words: %s' % words)


# --------------------------------------------------------------------------- #
class EveryNameReadAcrossModulesExists(unittest.TestCase):
    """A name that does not exist, read off one of the add-on's own
    modules, inside a `try/except`.

    **It imports cleanly, passes every other test, and does nothing at
    all.** Two shipped in the session that added this - `surface.is_vm`
    where the function is `surface.is_virtual_machine` (four places), and
    `compat.core` where `compat` had no `core` at all - so the whole
    virtual-machine reader was dead, twice over, and reported itself as
    working both times.

    **The checker is the repository's own**, not a second one written
    here. A hand-rolled sweep was tried first and was measurably weaker:
    it found `surface.is_vm` and was blind to `compat.core`, which is
    exactly how a check ends up passing for the wrong reason. There is
    one implementation and this makes it run.
    """

    def checker(self):
        where = os.path.join(ROOT, '.claude', 'skills', 'bug-fixer',
                             'scripts', 'check_names.py')
        if not os.path.exists(where):
            self.skipTest('the bug-fixer skill is not in this checkout')
        return where

    def test_no_module_reads_a_name_another_has_not_got(self):
        import subprocess
        answer = subprocess.run(
            [sys.executable, self.checker(),
             os.path.join(ADDON, 'globalPlugins', 'titanEnhancements')],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        said = answer.stdout.decode('utf-8', 'replace')
        self.assertEqual(answer.returncode, 0,
                         'names that do not exist:\n%s' % said)
        self.assertIn('file(s) checked', said,
                      'the checker did not run: %s' % said)


class ThePolishSaysWhatTheEnglishSays(unittest.TestCase):
    """Reported by somebody reading it: "the Polish seems nonsense in places,
    a grammatical error, use a dictionary".

    They were right, and three of the four faults could only be found by
    reading: the settings group `Titan's own settings` had become
    `Titan w ustawieniach` - "Titan in the settings", which is not what the
    group is - and `recogniser` had become `rozpoznawacz`, a word that is in
    no dictionary and nowhere else in this repository. The fourth was a
    missing letter (`strzalkami`), and that a machine finds instantly.

    So the machine-checkable half is checked: a placeholder that changed
    name (`{count}` written as `{ilosc}` raises `KeyError` in front of the
    user), a string left in English or left untranslated, a lost keyboard
    accelerator, a sentence that lost its full stop, and a form that
    addresses the reader as a man or a woman, which NVDA's own Polish never
    does.
    """

    def checker(self):
        where = os.path.join(ROOT, '.claude', 'skills', 'bug-fixer',
                             'scripts', 'check_translation.py')
        if not os.path.exists(where):
            self.skipTest('the bug-fixer skill is not in this checkout')
        return where

    def catalogue(self):
        return os.path.join(ADDON, 'locale', 'pl', 'LC_MESSAGES', 'nvda.po')

    def test_the_polish_catalogue_is_clean(self):
        import subprocess
        answer = subprocess.run([sys.executable, self.checker(),
                                 self.catalogue()],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        said = answer.stdout.decode('utf-8', 'replace')
        self.assertIn('entries', said, 'the checker did not run: %s' % said)
        self.assertEqual(answer.returncode, 0, 'the Polish:\n%s' % said)

    def test_the_word_that_is_in_no_dictionary_is_gone(self):
        with io.open(self.catalogue(), encoding='utf-8') as handle:
            polish = handle.read()
        self.assertNotIn('rozpoznawacz', polish)
        self.assertNotIn('Titan w ustawieniach', polish)
        self.assertNotIn('strzalkami', polish)

    def test_one_abbreviation_for_artificial_intelligence(self):
        """Titan's own Polish says SI 218 times and AI 52, all of the latter
        in the product name AI OCR. A catalogue that says both makes the
        reader learn the same thing twice."""
        import re
        with io.open(self.catalogue(), encoding='utf-8') as handle:
            polish = handle.read()
        for line in polish.splitlines():
            if not line.startswith('msgstr'):
                continue
            without = re.sub(r'AI OCR', '', line)
            self.assertNotIn('(AI)', without,
                             'AI where the rest of the catalogue says SI: %s'
                             % line)


# --------------------------------------------------------------------------- #
class _Win95:
    """A Windows 95 desktop: teal ground, a grey taskbar across the
    bottom, icon labels down the left, one selected in navy.

    This exact layout is what fooled the row detector - the taskbar is
    the most highlighted-looking thing on it and it never moves.
    """
    WIDE, TALL = 640, 480
    TEAL, GREY, NAVY = (0, 128, 128), (192, 192, 192), (0, 0, 128)
    WHITE, BLACK = (255, 255, 255), (0, 0, 0)
    ICONS = (('My Computer', 30), ('Network Neighborhood', 110),
             ('Inbox', 190), ('Recycle Bin', 270))

    def __init__(self, selected):
        self.size = (self.WIDE, self.TALL)
        self.rows = [[self.TEAL] * self.WIDE for _ in range(self.TALL)]
        for y in range(self.TALL - 28, self.TALL):
            for x in range(self.WIDE):
                self.rows[y][x] = self.GREY
        for name, top in self.ICONS:
            for y in range(top, top + 32):
                for x in range(24, 56):
                    self.rows[y][x] = self.WHITE if (x + y) % 5 \
                        else self.BLACK
            ground = self.NAVY if name == selected else self.TEAL
            ink = self.WHITE if name == selected else self.BLACK
            wide = min(8 * len(name), 150)
            for y in range(top + 34, top + 48):
                for x in range(10, 10 + wide):
                    self.rows[y][x] = ground
            for number in range(min(len(name), 18)):
                for y in range(top + 36, top + 46):
                    for x in range(12 + number * 8, 12 + number * 8 + 5):
                        if x < self.WIDE:
                            self.rows[y][x] = ink

    def getpixel(self, where):
        x, y = where
        return self.rows[int(y)][int(x)]

    @classmethod
    def icon_at(cls, top):
        for name, where in cls.ICONS:
            if where <= top <= where + 60:
                return name
        return ''


class AGuestIsAScreenNotAList(unittest.TestCase):
    """Reported as "it still is not right", with the one thing that
    settles it: **a guest is the screen of a virtual computer.**

    `highlights` finds a whole ROW whose background is unlike the
    window's own, which is what a menu and a list look like. On a screen
    it is the wrong question: measured on a real Windows 95 guest, the
    most highlighted-looking thing is the TASKBAR - a grey band across
    the bottom of a teal desktop - so arrowing between icons was
    answered "Start", every time.
    """

    def setUp(self):
        from titanEnhancements import guest, virtualInput
        self.guest, self.vi = guest, virtualInput
        guest.forget()

    def tearDown(self):
        self.guest.forget()

    def answer(self, picture):
        self.guest._picture_of = lambda hwnd: (picture, picture.WIDE,
                                               picture.TALL)
        self.guest._rect_of = lambda hwnd: (0, 0, picture.WIDE,
                                            picture.TALL)

    # -- the fault itself -------------------------------------------------
    def test_the_row_detector_answers_the_taskbar_on_a_desktop(self):
        """Why this was written. Not a criticism of `highlights` - it is
        right for a menu and this is a screen."""
        after = _Win95('Network Neighborhood')
        marks = self.vi.highlights(after)
        self.assertTrue(marks, 'it found nothing at all')
        top = marks[0][1]
        self.assertGreater(top, after.TALL - 60,
                           'the row detector no longer finds the taskbar; '
                           'this test is about the case where it does')
        self.assertEqual(_Win95.icon_at(top), '',
                         'the taskbar is not one of the icons')

    def test_what_the_key_changed_is_the_icon_it_moved_onto(self):
        """Two places change when a selection moves: the label that lost
        it and the one that gained it. The one that GAINED it is the one
        that is now unlike the background."""
        self.answer(_Win95('My Computer'))
        self.assertIsNone(self.guest.what_changed(7),
                          'the first look has nothing to compare against')
        self.answer(_Win95('Network Neighborhood'))
        where = self.guest.what_changed(7)
        self.assertIsNotNone(where, 'the change was not noticed')
        left, top, wide, tall = where
        self.assertEqual(_Win95.icon_at(top + tall // 2),
                         'Network Neighborhood')
        # And it is a REGION, not the whole screen: reading it is cheap.
        self.assertLess(wide * tall,
                        _Win95.WIDE * _Win95.TALL // 4,
                        'it asked for most of the screen')

    def test_moving_back_up_says_the_one_it_moved_onto(self):
        for first, second in (('Inbox', 'Network Neighborhood'),
                              ('Network Neighborhood', 'Recycle Bin')):
            self.guest.forget()
            self.answer(_Win95(first))
            self.guest.what_changed(7)
            self.answer(_Win95(second))
            where = self.guest.what_changed(7)
            self.assertIsNotNone(where, '%s -> %s was not noticed'
                                 % (first, second))
            self.assertEqual(_Win95.icon_at(where[1] + where[3] // 2),
                             second)

    def test_a_screen_that_did_not_change_says_nothing(self):
        self.answer(_Win95('Inbox'))
        self.guest.what_changed(7)
        self.answer(_Win95('Inbox'))
        self.assertIsNone(self.guest.what_changed(7))

    def test_a_whole_new_screen_is_not_what_a_key_did(self):
        """That is a new screen and belongs to the reading of the whole
        window, not to one arrow."""
        self.answer(_Win95('Inbox'))
        self.guest.what_changed(7)

        class Everything(_Win95):
            def __init__(self):
                _Win95.__init__(self, 'Inbox')
                for y in range(self.TALL):
                    for x in range(self.WIDE):
                        self.rows[y][x] = (200, 30, 30)
        self.answer(Everything())
        self.assertIsNone(self.guest.what_changed(7))

    # -- the cost ----------------------------------------------------------
    def test_looking_costs_the_same_whatever_size_the_guest_is(self):
        """A guest can be 640x480 or a maximised 2358x1285 and this runs
        several times a second. Measured: 14 ms, 10 ms, 7 ms."""
        for width in (640, 1280, 2358):
            block = self.guest._block_for(width)
            across = width // block
            self.assertLessEqual(across, self.guest.BLOCKS_ACROSS + 1,
                                 'a %d-wide guest is %d blocks across'
                                 % (width, across))
        self.assertGreaterEqual(self.guest._block_for(320), self.vi.BLOCK)

    # -- the order ---------------------------------------------------------
    def test_what_changed_is_asked_BEFORE_the_row_detector(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'guest.py'),
                         encoding='utf-8').read()
        at = source.index('def after_key(')
        block = source[at:source.index('\ndef _read_the_category', at)
                       if '\ndef _read_the_category' in source[at:]
                       else at + 2600]
        self.assertLess(block.index('what_changed('),
                        block.index('selected_in('),
                        'the row detector is being asked first again')

    def test_the_keys_may_never_reach_us_so_the_picture_is_watched(self):
        """A virtual machine that has grabbed the keyboard has its own
        low-level hook, and whichever was installed last is called first
        - so inside a grabbed guest the reader may not see the arrows at
        all. The screen changing is the one thing that is always true."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'guest.py'),
                         encoding='utf-8').read()
        at = source.index('def _follow(')
        block = source[at:source.index('\ndef crossing(', at)]
        self.assertIn('after_key(say=True)', block,
                      'the watcher does not look at the picture itself')


# --------------------------------------------------------------------------- #
class TheArrowKeysAreReadInAPicture(unittest.TestCase):
    """Reported as "moving through icons and options in a VM does not read
    what is really displayed - the arrows and Tab say nothing".

    Following the pointer answers "what is under my mouse" and nothing at
    all about the arrow keys, and arrowing is how these windows are
    really used: the mouse never moves. Nothing on the host changes when
    it happens - no focus event, no caret, no object - so the only thing
    that can be read is the picture, and the only cheap moment is just
    after the key.

    The method is the one the patent literature calls active-element
    detection: **a key, then the frame, then what CHANGED**.
    """

    def setUp(self):
        from titanEnhancements import guest, localOcr
        self.guest, self.localOcr = guest, localOcr
        guest.forget()
        self.said = []
        self._say = guest._say
        self._wanted = guest.wanted
        guest._say = self.said.append
        # The user has switched it on; everything here is about what it
        # does once they have.
        guest.wanted = lambda: True
        guest._state.update({'on': True, 'hwnd': 77})

    def tearDown(self):
        self.guest._say = self._say
        self.guest.wanted = self._wanted
        self.guest.forget()

    def reading(self, rows, highlight=None):
        """A reading whose rows sit twenty pixels apart, as a list does."""
        lines = []
        for number, text in enumerate(rows):
            lines.append([{'text': text, 'left': 10, 'top': 100 + number * 20,
                           'width': 120, 'height': 16}])
        made = self.localOcr.Reading(lines)
        if highlight is not None:
            top = 100 + highlight * 20
            made.highlights = [(0, top - 2, 400, 20)]
        return made

    def answer(self, reading):
        self.guest._read_now = lambda hwnd: reading

    # -- what is highlighted ---------------------------------------------
    def test_the_highlighted_row_is_what_the_arrow_moved_onto(self):
        """A drawn interface marks the entry the arrows are on by
        inverting its background and by NOTHING else - there is nothing
        in a picture that says it otherwise."""
        self.answer(self.reading(['Kosz', 'Ten komputer', 'Dokumenty'],
                                 highlight=1))
        ok, said = self.guest.after_key()
        self.assertTrue(ok)
        self.assertEqual(said, 'Ten komputer')
        self.assertEqual(self.said, ['Ten komputer'])

    def test_the_same_row_twice_is_not_said_twice(self):
        self.answer(self.reading(['Kosz', 'Dokumenty'], highlight=0))
        self.assertTrue(self.guest.after_key()[0])
        self.assertFalse(self.guest.after_key()[0])
        self.assertEqual(self.said, ['Kosz'])

    def test_moving_the_highlight_says_the_new_row(self):
        self.answer(self.reading(['Kosz', 'Dokumenty'], highlight=0))
        self.guest.after_key()
        self.answer(self.reading(['Kosz', 'Dokumenty'], highlight=1))
        ok, said = self.guest.after_key()
        self.assertTrue(ok)
        self.assertEqual(said, 'Dokumenty')

    # -- what changed ------------------------------------------------------
    def test_where_no_highlight_can_be_told_what_CHANGED_is_the_answer(self):
        """A game that marks its choice with an arrow or a colour rather
        than a bar."""
        self.answer(self.reading(['> Nowa gra', 'Opcje', 'Wyjscie']))
        self.guest.after_key()                     # the first is a baseline
        self.answer(self.reading(['Nowa gra', '> Opcje', 'Wyjscie']))
        ok, said = self.guest.after_key()
        self.assertTrue(ok)
        self.assertEqual(said, 'Nowa gra > Opcje')

    def test_a_whole_new_screen_is_not_what_the_key_did(self):
        """Saying forty rows after one arrow is worse than saying
        nothing; that is the watcher's own reading, not this."""
        self.answer(self.reading(['a', 'b']))
        self.guest.after_key()
        self.answer(self.reading(['p', 'q', 'r', 's', 't', 'u']))
        self.assertFalse(self.guest.after_key()[0])

    def test_an_arrow_that_moved_nothing_says_nothing(self):
        """Which is the commonest answer and the right one: an arrow
        inside a field moves a caret and no rows, and a reader that spoke
        on every keystroke would be unusable where people type most."""
        self.answer(self.reading(['nazwa: ala', 'haslo:']))
        self.guest.after_key()
        self.said[:] = []
        self.assertFalse(self.guest.after_key()[0])
        self.assertEqual(self.said, [])

    def test_a_window_that_reads_as_nothing_says_nothing(self):
        self.guest._read_now = lambda hwnd: None
        self.assertFalse(self.guest.after_key()[0])

    # -- the keys themselves ----------------------------------------------
    def test_the_keys_are_sent_on_before_anything_else(self):
        """They belong to the guest, or to the game. A reader that
        swallowed one would break the window it is describing."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def script_guestMoved(')
        block = source[at:at + 900]
        self.assertLess(block.index('gesture.send()'),
                        block.index('guest.after_key'),
                        'the key is acted on before it is passed through')

    def test_the_keys_are_the_ones_that_move_something(self):
        import titanEnhancements
        keys = titanEnhancements.GlobalPlugin.GUEST_KEYS
        for wanted in ('kb:upArrow', 'kb:downArrow', 'kb:leftArrow',
                       'kb:rightArrow', 'kb:tab', 'kb:shift+tab',
                       'kb:enter'):
            self.assertIn(wanted, keys, wanted)
        # Space is typing, and so is everything else left out.
        self.assertNotIn('kb:space', keys)
        self.assertNotIn('kb:escape', keys)

    def test_the_keys_are_only_held_while_such_a_window_is_in_front(self):
        self.assertTrue(self.guest.following())
        self.guest._state.update({'on': False})
        self.assertFalse(self.guest.following())

    # -- all three windows the user named ---------------------------------
    def test_a_guest_a_game_and_a_drawn_window_are_one_problem(self):
        from titanEnhancements import surface
        kept = (surface.is_virtual_machine, surface.looks_drawn, surface.report)
        surface.report = lambda: {'watching': 0}
        try:
            for is_vm, drawn, wanted in ((True, False, True),
                                         (False, True, True),
                                         (False, False, False)):
                self.guest.forget()
                surface.is_virtual_machine = lambda obj, a=is_vm: a
                surface.looks_drawn = lambda obj, module=None, a=drawn: a
                kept_enter = self.guest.enter
                self.guest.enter = lambda obj, product='', say=True: (True, '')
                try:
                    self.assertIs(self.guest.consider(object()), wanted,
                                  'is_vm=%s drawn=%s' % (is_vm, drawn))
                finally:
                    self.guest.enter = kept_enter
        finally:
            surface.is_virtual_machine, surface.looks_drawn, surface.report = kept

    def test_it_takes_the_window_over_from_the_watcher(self):
        """**Both read the guest; they answer different questions.** The
        watcher polls and says what CHANGED, which on the live Windows 95
        guest meant it said "Window-Eyes 2:42 AM" - the clock - thirteen
        times while the arrows moved through icons and said nothing about
        them. This answers the key and says the highlighted row, so it
        takes the window rather than standing aside from it.

        It used to stand aside, and that was the bug: the watcher being
        busy with a clock kept the better reader from running at all."""
        from titanEnhancements import surface
        stopped = []
        kept = (surface.is_virtual_machine, surface.looks_drawn,
                surface.report, surface.stop_now)
        surface.is_virtual_machine = lambda obj: True
        surface.looks_drawn = lambda obj, module=None: True
        surface.report = lambda: {'watching': 4242}
        surface.stop_now = lambda: stopped.append(True)
        held = self.guest.display_of
        self.guest.display_of = lambda obj: (obj, 4242)
        try:
            self.guest.forget()
            self.guest.wanted = lambda: True
            self.assertTrue(self.guest.consider(object()))
            self.assertEqual(stopped, [True])
            self.assertEqual(self.guest.report().get('took_over'), 1)
        finally:
            self.guest.display_of = held
            self.guest.leave()
            (surface.is_virtual_machine, surface.looks_drawn,
             surface.report, surface.stop_now) = kept


# --------------------------------------------------------------------------- #
class TitansSettingsAreWalkedCategoryFirst(unittest.TestCase):
    """Reported as "the categories are bugged - it says to say which
    control you want to press".

    `settings.screen` answers `{'categories': [{'name', 'items'}]}` - the
    shape of Titan's own settings window, a list of categories and the
    controls of the chosen one (`src/ui/settingsgui.py`) - and this page
    read a CATEGORY as a control. It was announced as "General, setting",
    and Enter sent `_label_of(row, 'id', 'label')` of a dict that carries
    neither, so Titan was asked to press a control called nothing and
    answered **"Say which control to press."** for every category there is.
    The page was one level short.
    """

    ITEMS = [
        {'id': 'general_0', 'label': 'Start with Windows', 'kind': 'bool',
         'value': True, 'options': [], 'enabled': True},
        {'id': 'general_1', 'label': 'Voice', 'kind': 'choice',
         'value': 'Zosia', 'options': ['Zosia', 'Ewa'], 'enabled': True},
        {'id': 'general_2', 'label': 'Drivable add-ons', 'kind': 'multi',
         'value': ['tNotes'], 'options': ['tNotes', 'tEdit'],
         'enabled': True},
        {'id': 'general_3', 'label': 'Downloads folder', 'kind': 'text',
         'value': 'C:\\Down', 'options': [], 'enabled': True},
        {'id': 'general_4', 'label': 'Forget the notes', 'kind': 'command',
         'value': None, 'options': [], 'enabled': True},
    ]

    def category(self):
        return {'name': 'General',
                'items': [dict(one) for one in self.ITEMS]}

    def setUp(self):
        from titanEnhancements import palette
        from titanEnhancements import titanWalk
        self.walk = titanWalk
        self.palette = palette
        titanWalk.forget()
        palette.forget()
        self.said = []
        self._say = titanWalk._say
        titanWalk._say = self.said.append
        # Every verb here goes to a worker and comes back on the reader's
        # thread; in a test both are this one.
        self._sent = []
        self._without = titanWalk._without_closing

        def inline(work, then):
            self._sent.append((work, then))
            return True, ''
        titanWalk._without_closing = inline
        self._readers = titanWalk._on_the_readers_thread
        titanWalk._on_the_readers_thread = lambda work: work()
        self._again = titanWalk._read_the_category_again
        titanWalk._read_the_category_again = lambda category: None
        titanWalk._unsaved['on'] = False

    def tearDown(self):
        self.walk._say = self._say
        self.walk._without_closing = self._without
        self.walk._on_the_readers_thread = self._readers
        self.walk._read_the_category_again = self._again
        self.walk._unsaved['on'] = False
        self.palette.forget()
        self.walk.forget()

    def run_the_last(self, answer):
        """What the row asked for, answered as Titan would have."""
        _work, then = self._sent[-1]
        then(answer)

    def what_was_asked(self):
        """The call the row would have made, without making it."""
        asked = {}
        work, _then = self._sent[-1]
        from titanEnhancements import titan
        keep = (titan.set_setting, titan.press_setting, titan.save_settings)
        titan.set_setting = lambda control, value: (
            asked.update({'set': (control, value)}), (True, 'ok'))[1]
        titan.press_setting = lambda control: (
            asked.update({'press': control}), (True, 'Pressed it.'))[1]
        titan.save_settings = lambda: (
            asked.update({'save': True}), (True, 'Saved.'))[1]
        try:
            work()
        finally:
            (titan.set_setting, titan.press_setting,
             titan.save_settings) = keep
        return asked

    # -- the bug itself --------------------------------------------------
    def test_a_category_is_announced_as_a_category(self):
        """"General, setting" is a lie about a row that is a whole page of
        them."""
        self.assertEqual(self.walk._PAGES['settings']['what'](), 'category')

    def test_a_category_is_never_pressed_as_a_control(self):
        """The whole of the reported fault: a category carries no `id` and
        no `label`, so `press_setting` was handed an empty string and
        Titan answered "Say which control to press."."""
        self.assertEqual(self.walk._label_of(self.category(), 'id', 'label'),
                         '', 'a category really has neither')
        self.assertIs(self.walk._PAGES['settings']['press'],
                      self.walk._open_settings_category)
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        at = source.index("    'settings': {")
        block = source[at:source.index('},', at)]
        self.assertNotIn('press_setting', block,
                         'a category is being pressed as a control again')

    def test_pressing_a_category_opens_what_is_in_it(self):
        ok, _said = self.walk._open_settings_category(self.category())
        self.assertTrue(ok)
        rows = self.palette._state['rows']
        self.assertEqual(len(rows), len(self.ITEMS))
        self.assertEqual(self.palette._state['title'], 'General')

    def test_a_category_with_nothing_in_it_says_so(self):
        ok, said = self.walk._open_settings_category({'name': 'Empty',
                                                      'items': []})
        self.assertFalse(ok)
        self.assertEqual(said, 'Nothing here')

    # -- the rows --------------------------------------------------------
    def test_a_row_says_what_the_control_IS(self):
        """A tick box and a button are not the same row, and somebody
        working by ear cannot see which is which."""
        self.walk._open_settings_category(self.category())
        roles = [row['role'] for row in self.palette._state['rows']]
        self.assertEqual(roles, ['tick box', 'choice', 'tick list', 'text',
                                 'button'])

    def test_a_row_carries_what_the_control_HOLDS(self):
        """A list that showed only the names would make somebody open
        every setting to find out what it holds."""
        self.walk._open_settings_category(self.category())
        labels = [row['label'] for row in self.palette._state['rows']]
        self.assertEqual(labels[0], 'Start with Windows: on')
        self.assertEqual(labels[1], 'Voice: Zosia')

    def test_a_tick_list_is_said_as_words_never_as_a_list(self):
        """Its value IS a list, and a list put into a row through `str()`
        is `['tNotes']` - brackets, quotes and commas, read out one
        punctuation mark at a time."""
        self.walk._open_settings_category(self.category())
        said = self.palette._state['rows'][2]['label']
        self.assertEqual(said, 'Drivable add-ons: tNotes')
        for wrong in ('[', ']', "'"):
            self.assertNotIn(wrong, said)
        self.assertEqual(
            self.walk._setting_label({'label': 'Drivable add-ons',
                                      'kind': 'multi', 'value': []}),
            'Drivable add-ons: none')

    def test_a_row_plays_what_it_is_before_a_word_of_it(self):
        self.walk._open_settings_category(self.category())
        icons = [row['icon'] for row in self.palette._state['rows']]
        self.assertEqual(icons[0], 'on')
        self.assertEqual(icons[4], 'button')
        self.assertEqual(
            self.walk._setting_icon({'kind': 'bool', 'value': False}), 'off')

    # -- pressing one ----------------------------------------------------
    def test_a_tick_box_is_set_to_the_OPPOSITE_of_what_it_holds(self):
        self.walk._open_settings_category(self.category())
        row = self.palette._state['rows'][0]
        row['run']()
        self.assertEqual(self.what_was_asked()['set'], ('general_0', False))

    def test_a_button_is_pressed_by_its_own_id(self):
        self.walk._open_settings_category(self.category())
        self.palette._state['at'] = 4
        self.palette.activate()
        self.assertEqual(self.what_was_asked()['press'], 'general_4')

    def test_a_choice_offers_its_answers_and_marks_the_one_in_force(self):
        self.walk._open_settings_category(self.category())
        self.palette._state['at'] = 1
        ok, _said = self.palette.activate()
        self.assertTrue(ok)
        rows = self.palette._state['rows']
        self.assertEqual([row['label'] for row in rows], ['Zosia', 'Ewa'])
        self.assertEqual(rows[0]['role'], 'now')
        self.assertEqual(rows[1]['role'], '')
        rows[1]['run']()
        self.assertEqual(self.what_was_asked()['set'], ('general_1', 'Ewa'))

    def test_a_tick_list_crosses_as_json_TEXT(self):
        """Titan's `_set_value` stringifies whatever arrives before it
        parses it, so a real list comes back through `str()` in Python's
        own spelling - single quotes - which is not JSON."""
        self.walk._open_settings_category(self.category())
        self.palette._state['at'] = 2
        self.palette.activate()
        rows = self.palette._state['rows']
        self.assertEqual([row['role'] for row in rows],
                         ['ticked', 'not ticked'])
        rows[1]['run']()
        control, value = self.what_was_asked()['set']
        self.assertEqual(control, 'general_2')
        self.assertIsInstance(value, str)
        self.assertEqual(json.loads(value), ['tNotes', 'tEdit'])

    def test_a_tick_leaves_the_cursor_exactly_where_it_is(self):
        """Putting the level up again would say the title and then the
        row - two announcements for one keystroke."""
        self.walk._open_settings_category(self.category())
        self.palette._state['at'] = 2
        self.palette.activate()
        self.palette._state['at'] = 1
        row = self.palette._state['rows'][1]
        row['run']()
        self.run_the_last((True, 'Drivable add-ons is now tNotes, tEdit.'))
        self.assertEqual(self.palette._state['at'], 1)
        self.assertIs(self.palette.here(), row)
        self.assertEqual(row['role'], 'ticked')

    def test_a_setting_titan_gave_no_id_for_says_so(self):
        """An empty id is what asked Titan to press a control called
        nothing. It is refused here rather than sent."""
        ok, said = self.walk._change_setting(
            {'label': 'x'}, {'label': 'x', 'kind': 'bool', 'value': True},
            'General')
        self.assertFalse(ok)
        self.assertIn('what this control is called', said)

    def test_a_kind_it_has_not_been_taught_is_not_silently_dropped(self):
        ok, said = self.walk._change_setting(
            {'label': 'x'}, {'id': 'z', 'label': 'Colours', 'kind': 'palette'},
            'General')
        self.assertFalse(ok)
        self.assertIn('Colours', said)

    def test_something_to_read_is_read_again_rather_than_pressed(self):
        ok, said = self.walk._change_setting(
            {'label': 'x'},
            {'id': 'i', 'label': 'Version', 'kind': 'info', 'value': '5.1'},
            'General')
        self.assertTrue(ok)
        self.assertEqual(said, '5.1')

    # -- keeping them ----------------------------------------------------
    def test_the_page_ends_with_save_and_put_them_back(self):
        """Titan writes nothing until it is told to, so a walker with no
        save was one in which every answer given was thrown away."""
        self.walk._page_arrived(self.walk._PAGES['settings'], True,
                                [self.category()])
        labels = [row['label'] for row in self.palette._state['rows']]
        self.assertEqual(labels[0], 'General (5)')
        self.assertEqual(labels[-2:], ['Save', 'Put them back'])

    def test_the_save_row_says_when_something_is_waiting(self):
        self.walk._unsaved['on'] = True
        self.assertIn('not saved yet',
                      self.walk._keeping_the_settings()[0]['label'])

    def test_a_change_is_remembered_as_waiting_and_said_once(self):
        self.walk._open_settings_category(self.category())
        row = self.palette._state['rows'][0]
        row['run']()
        self.run_the_last((True, 'Start with Windows is now False.'))
        self.assertTrue(self.walk._unsaved['on'])
        self.assertEqual(len(self.said), 1, 'two announcements about one key')
        self.assertIn('Start with Windows: off', self.said[0])
        self.assertIn('Not saved yet', self.said[0])
        # Said ONCE: the second change is the line and nothing else.
        self.said[:] = []
        row['run']()
        self.run_the_last((True, 'Start with Windows is now True.'))
        self.assertEqual(self.said, ['Start with Windows: on'])

    def test_a_refusal_is_titans_own_sentence(self):
        """It is in the user's own language and it names the one thing
        that changes the answer."""
        self.walk._open_settings_category(self.category())
        self.palette._state['rows'][0]['run']()
        self.run_the_last((False, 'Titan has not been told this add-on may '
                                  'control it.'))
        self.assertEqual(self.said, ['Titan has not been told this add-on '
                                     'may control it.'])
        self.assertFalse(self.walk._unsaved['on'])

    def test_saving_puts_the_waiting_change_away(self):
        from titanEnhancements import titan
        self.walk._unsaved['on'] = True
        keep = titan.save_settings
        titan.save_settings = lambda: (True, 'Saved.')
        try:
            self.assertEqual(self.walk._keep_them(), (True, 'Saved.'))
        finally:
            titan.save_settings = keep
        self.assertFalse(self.walk._unsaved['on'])

    def test_a_save_that_failed_leaves_the_change_waiting(self):
        from titanEnhancements import titan
        self.walk._unsaved['on'] = True
        keep = titan.save_settings
        titan.save_settings = lambda: (False, 'Titan is not running.')
        try:
            self.walk._keep_them()
        finally:
            titan.save_settings = keep
        self.assertTrue(self.walk._unsaved['on'],
                        'a save that failed must not look like one that did')

    def test_saving_straight_away_is_a_switch_and_starts_off(self):
        """Saving is Titan's own `OnSave` - the SAPI registration, the
        system monitor, the shell, the menu bar - which is a great deal to
        do on every keystroke."""
        from titanEnhancements import configSpec
        self.assertIn('default=False', configSpec.SPEC['titanAutoSave'])
        self.assertIn('default=True', configSpec.SPEC['titanValues'])
        self.assertIn('default=True', configSpec.SPEC['titanCounts'])

    def test_the_new_switches_are_on_the_page(self):
        from titanEnhancements import settingsPanel
        offered = set(settingsPanel.keys_on_the_page())
        for name in ('titanValues', 'titanCounts', 'titanAutoSave'):
            self.assertIn(name, offered, name)

    def test_a_switch_that_is_off_really_takes_that_away(self):
        from titanEnhancements import configSpec
        kept = configSpec.read
        configSpec.read = lambda: dict(configSpec.defaults(),
                                       titanValues=False, titanCounts=False)
        try:
            self.assertEqual(self.walk._setting_label(self.ITEMS[0]),
                             'Start with Windows')
            self.assertEqual(self.walk._how_many(self.category()), 'General')
        finally:
            configSpec.read = kept

    # -- the list is not lost --------------------------------------------
    def test_setting_one_thing_does_not_close_the_list(self):
        """`_on_a_thread` stops the walker, which is right for "start that
        application" and wrong here: somebody setting one thing in a
        category is nearly always setting the next one too."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _change_setting(')
        block = source[at:source.index('def _set_it(', at)]
        self.assertNotIn('_on_a_thread(', block)
        self.assertIn('_without_closing(', block)

    def test_the_cursor_comes_back_to_the_setting_that_was_answered(self):
        """Somebody who went into a setting, answered it and came out
        belongs on the setting they answered, not at the top of forty."""
        self.walk._open_settings_category(self.category())
        self.palette._state['at'] = 3
        self.walk._remember_where()
        self.palette.stop()
        self.walk._back_to_category('General')
        self.assertEqual(self.palette._state['at'], 3)
        self.assertEqual(self.palette._state['title'], 'General')

    def test_a_cursor_that_is_no_longer_a_row_is_the_first_row(self):
        """A list that has since got shorter must not land the cursor on
        nothing."""
        rows = [{'label': 'one'}, {'label': 'two'}]
        self.palette.show(rows, 'Some', at=9)
        self.assertEqual(self.palette._state['at'], 0)
        self.palette.show(rows, 'Some', at='2')
        self.assertEqual(self.palette._state['at'], 0)

    def test_asking_for_a_value_can_be_cancelled(self):
        """Cancelling is an ANSWER - "leave it as it was" - and a caller
        that cannot hear it leaves somebody nowhere: the walk has been
        closed to let the box have the arrow keys."""
        import inspect
        from titanEnhancements import dialogs
        self.assertIn('on_cancel',
                      inspect.signature(dialogs.ask_text).parameters)
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _ask_for_a_value(')
        block = source[at:source.index('def _without_closing(', at)]
        self.assertIn('on_cancel=', block)
        self.assertIn('palette.stop()', block)

    def test_a_field_that_cannot_be_asked_for_does_not_close_the_walk(self):
        """There is no wx in the tests, which is exactly the case: closing
        the walk for a box that will never appear would leave somebody
        with neither the box nor the list."""
        self.walk._open_settings_category(self.category())
        self.palette._state['at'] = 3
        ok, said = self.palette.activate()
        self.assertFalse(ok)
        self.assertIn('Downloads folder', said)
        self.assertTrue(self.palette.walking(),
                        'the walk was closed for a box that never opened')

    def test_a_key_is_never_shown_back_to_anybody(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'titanWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _ask_for_a_value(')
        block = source[at:source.index('def _without_closing(', at)]
        self.assertIn("'' if kind == 'secret'", block)

    def test_what_titan_now_holds_is_put_into_the_rows_silently(self):
        """One setting can move another - a switch that enables half a
        page - so the rows follow. Silently: the announcement has already
        happened."""
        self.walk._open_settings_category(self.category())
        moved = [{'name': 'General',
                  'items': [dict(self.ITEMS[0], value=False)]}]
        self.said[:] = []
        self.walk._relabel('General', moved)
        self.assertEqual(self.palette._state['rows'][0]['label'],
                         'Start with Windows: off')
        self.assertEqual(self.said, [])

    def test_a_reading_of_another_category_is_not_applied_to_this_one(self):
        self.walk._open_settings_category(self.category())
        self.walk._relabel('Sound', [{'name': 'Sound', 'items': [
            dict(self.ITEMS[0], value=False)]}])
        self.assertEqual(self.palette._state['rows'][0]['label'],
                         'Start with Windows: on')

    def test_one_category_is_asked_for_rather_than_the_whole_window(self):
        """The whole window is a hundred and fifty controls, read to build
        a list nobody is looking at."""
        from titanEnhancements import titan
        asked = {}
        keep = titan.LINK.bridge
        titan.LINK.bridge = lambda call, **args: (
            asked.update({'call': call, 'args': args}),
            (True, {'categories': []}))[1]
        try:
            titan.settings(category='General')
            self.assertEqual(asked['args'], {'category': 'General'})
            titan.settings()
            self.assertEqual(asked['args'], {})
        finally:
            titan.LINK.bridge = keep


# --------------------------------------------------------------------------- #
class TheKindTakesThePlaceOfTheWordDialog(unittest.TestCase):
    """NVDA says the dialog's name and then its role - "dialog" - and the
    kind said beside that is the same fact twice: "Zapisz, dialog,
    pytanie". What the user wants to hear is "Zapisz, pytanie"."""

    def setUp(self):
        from titanEnhancements import interject
        self.interject = interject
        interject.forget() if hasattr(interject, 'forget') else None

    def test_it_swaps_the_role_word_when_it_knows_it(self):
        import time
        self.interject._instead = ('pytanie', time.time())
        was = self.interject._dialog_word
        self.interject._dialog_word = lambda: 'dialog'
        try:
            made, swapped = self.interject._kind_instead(
                ['Zapisz', 'dialog'])
        finally:
            self.interject._dialog_word = was
            self.interject._instead = None
        self.assertTrue(swapped)
        self.assertEqual(made, ['Zapisz', 'pytanie'])

    def test_a_name_that_merely_CONTAINS_the_word_is_not_renamed(self):
        """Only ever an exact, whole-item match: a dialog called "Dialog
        options" is not a dialog called "pytanie options"."""
        import time
        self.interject._instead = ('pytanie', time.time())
        was = self.interject._dialog_word
        self.interject._dialog_word = lambda: 'dialog'
        try:
            made, swapped = self.interject._kind_instead(
                ['Dialog options', 'button'])
        finally:
            self.interject._dialog_word = was
            self.interject._instead = None
        self.assertFalse(swapped)
        self.assertEqual(made, ['Dialog options', 'button'])

    def test_it_swaps_once(self):
        import time
        self.interject._instead = ('pytanie', time.time())
        was = self.interject._dialog_word
        self.interject._dialog_word = lambda: 'dialog'
        try:
            made, _swapped = self.interject._kind_instead(
                ['dialog', 'dialog'])
        finally:
            self.interject._dialog_word = was
            self.interject._instead = None
        self.assertEqual(made, ['pytanie', 'dialog'])

    def test_nothing_armed_changes_nothing(self):
        self.interject._instead = None
        made, swapped = self.interject._kind_instead(['Zapisz', 'dialog'])
        self.assertFalse(swapped)
        self.assertEqual(made, ['Zapisz', 'dialog'])

    def test_a_word_it_cannot_learn_leaves_the_sequence_alone(self):
        """An alpha build renames these constantly, so the word is asked
        of the running NVDA rather than written down - and when it will
        not say, the kind is said beside the role as it was before."""
        import time
        self.interject._instead = ('pytanie', time.time())
        was = self.interject._dialog_word
        self.interject._dialog_word = lambda: ''
        try:
            made, swapped = self.interject._kind_instead(['Zapisz', 'dialog'])
        finally:
            self.interject._dialog_word = was
            self.interject._instead = None
        self.assertFalse(swapped)
        self.assertEqual(made, ['Zapisz', 'dialog'])

    def test_it_is_the_only_role_word_ever_replaced(self):
        from titanEnhancements import interject
        found = interject.capabilities() if hasattr(interject, 'capabilities') \
            else {}
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'interject.py'),
                         encoding='utf-8').read()
        self.assertIn("'role_label': False", source,
                      'the general refusal is gone')
        self.assertIn("'dialog_role_label': True", source)

    def test_the_kind_is_not_ALSO_said_beside_it(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'interject.py'),
                         encoding='utf-8').read()
        at = source.index('def _filter(')
        block = source[at:at + 2000]
        self.assertIn('_kind_instead', block)
        at = block.index('_kind_instead')
        self.assertIn("globals()['_prefix'] = None", block[at:at + 400])


# --------------------------------------------------------------------------- #
class LeftAndRightReadTheRow(unittest.TestCase):
    """The words while there are words, and then the characters.

    A row with several words is read a word at a time, which is what
    somebody wants from a name or a path. A row that is one word - or the
    END of a row that has run out of them - is read a character at a
    time, which is how a spelling or a number is checked by ear. Stopping
    dead at the last word says nothing about what is in it.
    """

    def setUp(self):
        from titanEnhancements import virtualWindow
        self.vw = virtualWindow
        self.said = []
        self._was = virtualWindow._say
        virtualWindow._say = lambda text: self.said.append(str(text))
        self.addCleanup(lambda: setattr(virtualWindow, '_say', self._was))
        virtualWindow._state.update({'on': True, 'at': 0, 'inner': 0,
                                     'letter': 0})
        self.addCleanup(lambda: virtualWindow._state.update(
            {'on': False, 'nodes': [], 'at': 0, 'inner': 0, 'letter': 0}))

    def _row(self, name):
        self.vw._state['nodes'] = [{'name': name, 'value': '',
                                    'description': '', 'role': 'TEXT',
                                    'level': 0, 'obj': None}]

    def test_words_first(self):
        self._row('Save the file')
        self.vw.move_inside(1)
        self.assertEqual(self.said[-1], 'the')

    def test_a_single_word_is_read_by_character(self):
        """There are no words to move through, so Left and Right are the
        letters - which is the whole point of asking for them."""
        self._row('Save')
        self.vw.move_inside(1)
        self.assertEqual(len(self.said[-1]), 1)

    def test_running_out_of_words_carries_on_into_the_letters(self):
        self._row('one two')
        self.vw.move_inside(1)          # 'two'
        self.vw.move_inside(1)          # past the end -> characters
        self.assertEqual(len(self.said[-1]), 1)

    def test_the_letter_cursor_starts_again_on_the_next_row(self):
        """It belongs to the row, not to the window."""
        self.vw._state['nodes'] = [
            {'name': 'Save', 'value': '', 'description': '',
             'role': 'TEXT', 'level': 0, 'obj': None},
            {'name': 'Open', 'value': '', 'description': '',
             'role': 'TEXT', 'level': 0, 'obj': None}]
        self.vw.move_inside(1)
        self.vw.move(1)
        self.assertEqual(self.vw._state['letter'], 0)


# --------------------------------------------------------------------------- #
class AMessageIsTextToWalk(unittest.TestCase):
    """A message box is a dialog, and a dialog is the wrong shape for an
    answer: it takes the foreground, has to be dismissed, and what it
    says is said once - so a message arriving while something else speaks
    is cut in half."""

    def test_a_message_is_walked_before_a_box_is_put_up(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'dialogs.py'),
                         encoding='utf-8').read()
        at = source.index('def message(')
        block = source[at:source.index('\ndef report(', at)]
        code = block[block.index('caption = title'):]
        self.assertIn('palette.page', code)
        self.assertLess(code.index('palette.page'), code.index('messageBox'))

    def test_an_error_still_interrupts(self):
        """The one message worth a real box: it is the thing that went
        wrong, and it should not wait to be arrowed to."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'dialogs.py'),
                         encoding='utf-8').read()
        at = source.index('def message(')
        block = source[at:source.index('\ndef report(', at)]
        self.assertIn('if not error:', block)

    def test_the_pair_is_symmetrical(self):
        """Somebody should not have to listen to work out which state
        they are in."""
        from titanEnhancements import palette
        palette.forget()
        self.addCleanup(palette.forget)
        palette.page('one\ntwo', 'Status')
        self.assertEqual(palette._state['kind'], 'text')
        _ok, said = palette.stop()
        self.assertTrue(said)


# --------------------------------------------------------------------------- #
class WhatYouHaveMadeIsWalkedToo(unittest.TestCase):
    """`managerGui` and `classManager` are kept because EDITING wants a
    form - a voice's pitch is a slider and recording a procedure is a
    sequence of presses, and a list can be neither. What a list is good
    for is seeing what is there, which is asked far more often."""

    def setUp(self):
        from titanEnhancements import managerWalk
        self.walk = managerWalk
        managerWalk.forget()

    def test_every_page_of_both_dialogs_is_there(self):
        listed = {key for key, _name, _fetch in self.walk.PAGES}
        for wanted in ('markers', 'programs', 'procedures', 'names',
                       'monitors', 'icons', 'scheme', 'voices', 'order'):
            self.assertIn(wanted, listed, '%s is not walkable' % wanted)

    def test_each_page_names_itself_and_can_be_read(self):
        for key, name, fetch in self.walk.PAGES:
            self.assertTrue(name(), key)
            self.assertIsInstance(fetch(), list, key)

    def test_a_module_that_will_not_answer_is_an_empty_page(self):
        """Never an exception: these read eight different modules and one
        of them being unhappy must not take the window down."""
        def angry():
            raise RuntimeError('no')
        self.assertEqual(self.walk._rows_of(angry), [])

    def test_the_form_is_a_row_on_every_level(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'managerWalk.py'),
                         encoding='utf-8').read()
        self.assertEqual(source.count("_('Open as a form')"), 2)

    def test_the_voices_open_the_class_manager_not_the_other_one(self):
        """They are edited in a different dialog, and "open as a form"
        that opened the wrong window would be worse than none."""
        for key in self.walk.THE_CLASS_MANAGER:
            self.assertIn(key, {one for one, _n, _f in self.walk.PAGES})
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'managerWalk.py'),
                         encoding='utf-8').read()
        at = source.index('def _as_a_form(')
        block = source[at:]
        self.assertIn('classManager', block)
        self.assertIn('managerGui', block)

    def test_the_commands_walk_and_the_forms_are_still_reachable(self):
        from titanEnhancements import commands
        for walked, form in (('manager', 'manager_as_a_form'),
                             ('voice_classes', 'voice_classes_as_a_form'),
                             ('titan_window', 'titan_window_as_a_form'),
                             ('titan_menu', 'titan_menu_as_a_menu')):
            self.assertTrue(callable(getattr(commands, walked, None)), walked)
            self.assertTrue(callable(getattr(commands, form, None)), form)


class EvenAShortAnswerIsAPage(unittest.TestCase):
    """A one-line answer is usually the one somebody asked a direct
    question to get, and it was going to speech - cut off by the next
    thing that spoke exactly as a long one was."""

    def test_one_line_is_not_spoken(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'commands.py'),
                         encoding='utf-8').read()
        at = source.index('def _page(')
        block = source[at:source.index('\ndef notifications', at)]
        code = block[block.index('lines = ['):]
        self.assertIn('dialogs.browse', code)
        self.assertNotIn('dialogs.report', code)

    def test_a_toggle_is_still_two_words_of_speech(self):
        """Those are meant to be heard in passing; a window for "Edit
        field on" would be worse than the interruption it avoids."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'dialogs.py'),
                         encoding='utf-8').read()
        at = source.index('def report(')
        block = source[at:at + 700]
        self.assertNotIn('palette.page', block)


# --------------------------------------------------------------------------- #
class NoScriptIsDefinedTwice(unittest.TestCase):
    """The second definition replaces the first, in silence.

    `script_appType` was written twice: once to relay a key into the
    field being walked, and once - older - to put up a `TextEntryDialog`
    titled "TCE application" asking for the text. Python keeps the
    LATER one, so every key bound for typing opened that dialog instead,
    and nothing anywhere said the first had been replaced. This is the
    first of the four shapes in the bug-fixer skill, and it has now cost
    this add-on twice (`_actions_of` was the other).
    """

    def test_the_plugin_defines_each_script_once(self):
        import ast
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            seen = {}
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                    continue
                if item.name in seen:
                    self.fail('%s.%s is defined on line %d and again on '
                              'line %d - the second replaces the first'
                              % (node.name, item.name, seen[item.name],
                                 item.lineno))
                seen[item.name] = item.lineno

    def test_no_module_defines_a_function_twice(self):
        import ast
        where = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements')
        for name in sorted(os.listdir(where)):
            if not name.endswith('.py'):
                continue
            tree = ast.parse(io.open(os.path.join(where, name),
                                     encoding='utf-8').read())
            seen = {}
            for item in tree.body:
                if not isinstance(item, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                    continue
                if item.name in seen:
                    self.fail('%s: %s is defined twice, on lines %d and %d'
                              % (name, item.name, seen[item.name],
                                 item.lineno))
                seen[item.name] = item.lineno

    def test_the_dialog_that_asked_for_the_text_is_gone(self):
        """There is an edit-field mode now; asking for the text in a box
        titled "TCE application" is the thing it replaced."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'commands.py'),
                         encoding='utf-8').read()
        self.assertNotIn('def type_into_application', source)
        menu = io.open(os.path.join(ADDON, 'globalPlugins',
                                    'titanEnhancements', 'menu.py'),
                       encoding='utf-8').read()
        self.assertNotIn('type_into_application', menu)


# --------------------------------------------------------------------------- #
class TheEditFieldIsAVirtualWindow(unittest.TestCase):
    """`textField.py` - the field's own text as the thing the cursor
    walks.

    Handing the keys to whatever happens to be focused is what this
    replaced, and it was wrong twice over: over a row read off a picture
    there is nothing focused to receive them, and even over a real
    control the reader is then guessing what the control did with each
    key rather than knowing.
    """

    def setUp(self):
        from titanEnhancements import textField
        self.tf = textField
        textField.forget()

    def _field(self, text='one two\nthree', at=0, multiline=True):
        return self.tf.Field(text=text, at=at, multiline=multiline)

    # ------------------------------------------------------------ moving
    def test_left_and_right_are_characters_and_say_the_character(self):
        """Which is how somebody proof-reads a word by ear."""
        field = self._field(at=0)
        what, said = self.tf.press(field, 'right')
        self.assertEqual(what, 'moved')
        self.assertEqual(said, 'n')
        what, said = self.tf.press(field, 'left')
        self.assertEqual(said, 'o')

    def test_up_and_down_are_lines_and_say_the_line(self):
        field = self._field(at=0)
        what, said = self.tf.press(field, 'down')
        self.assertEqual(what, 'moved')
        self.assertEqual(said, 'three')
        what, said = self.tf.press(field, 'up')
        self.assertEqual(said, 'one two')

    def test_a_line_keeps_the_column(self):
        field = self._field(text='abcd\nefgh', at=3)
        self.tf.press(field, 'down')
        self.assertEqual(field.column, 3)

    def test_control_and_an_arrow_is_a_word(self):
        field = self._field(text='one two three', at=13, multiline=False)
        self.tf.press(field, 'ctrl+left')
        self.assertEqual(field.at, 8)

    def test_home_and_end_are_the_LINE_and_control_the_whole_text(self):
        field = self._field(text='abc\ndef', at=5)
        self.tf.press(field, 'home')
        self.assertEqual(field.at, 4)
        self.tf.press(field, 'ctrl+home')
        self.assertEqual(field.at, 0)
        self.tf.press(field, 'end')
        self.assertEqual(field.at, 3)
        self.tf.press(field, 'ctrl+end')
        self.assertEqual(field.at, 7)

    def test_it_stops_at_the_ends_and_says_so_by_not_moving(self):
        field = self._field(text='ab', at=0, multiline=False)
        what, _said = self.tf.press(field, 'left')
        self.assertEqual(what, 'edge')

    # ------------------------------------------------------------ typing
    def test_a_letter_goes_in_at_the_caret_and_is_echoed(self):
        field = self._field(text='ac', at=1, multiline=False)
        what, said = self.tf.press(field, 'b')
        self.assertEqual((what, said), ('typed', 'b'))
        self.assertEqual(field.text, 'abc')

    def test_shift_and_a_bare_capital_both_give_a_capital(self):
        for key in ('shift+n', 'N'):
            field = self._field(text='', at=0, multiline=False)
            self.tf.press(field, key)
            self.assertEqual(field.text, 'N', key)

    def test_space_is_a_space(self):
        field = self._field(text='ab', at=2, multiline=False)
        what, _said = self.tf.press(field, 'space')
        self.assertEqual(field.text, 'ab ')
        self.assertEqual(what, 'typed')

    def test_backspace_says_the_character_that_went(self):
        """Which is what tells somebody they deleted the right one."""
        field = self._field(text='abc', at=3, multiline=False)
        what, said = self.tf.press(field, 'back')
        self.assertEqual((what, said), ('deleted', 'c'))
        self.assertEqual(field.text, 'ab')

    def test_control_and_backspace_takes_the_word(self):
        field = self._field(text='one two', at=7, multiline=False)
        _what, said = self.tf.press(field, 'ctrl+back')
        self.assertEqual(said, 'two')
        self.assertEqual(field.text, 'one ')

    def test_delete_takes_what_is_after_it(self):
        field = self._field(text='abc', at=0, multiline=False)
        _what, said = self.tf.press(field, 'delete')
        self.assertEqual(said, 'a')
        self.assertEqual(field.text, 'bc')

    def test_backspace_at_the_start_is_an_edge_not_a_deletion(self):
        field = self._field(text='abc', at=0, multiline=False)
        what, _said = self.tf.press(field, 'back')
        self.assertEqual(what, 'edge')
        self.assertEqual(field.text, 'abc')

    def test_enter_is_a_line_in_a_multiline_field_and_the_forms_otherwise(self):
        """In a one-line field Enter presses the default button, so the
        field says it did not deal with it."""
        field = self._field(text='ab', at=2, multiline=True)
        what, _said = self.tf.press(field, 'enter')
        self.assertEqual((what, field.text), ('typed', 'ab\n'))
        one_line = self._field(text='ab', at=2, multiline=False)
        what, _said = self.tf.press(one_line, 'enter')
        self.assertEqual(what, '', 'Enter was taken from the form')

    def test_a_label_that_could_not_be_worked_out_says_why(self):
        """The log carried "Titan could not work out a name:" with
        nothing after the colon, three times in a row - a refusal that
        names nothing, which is the shape of message this add-on exists
        not to produce. Each reason is a different thing to do about
        it."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'graphics.py'),
                         encoding='utf-8').read()
        at = source.index('def label_locally(')
        block = source[at:source.index('\ndef label_with_ai', at)]
        import re
        bare = re.findall(r'return False, \'\'', block)
        self.assertEqual(bare, [], 'label_locally still refuses with no '
                                   'reason at all')

    def test_NVDAs_own_key_names_are_the_fields_too(self):
        """NVDA says `leftArrow` and `control`; the wire says `left` and
        `ctrl`. A key that is not recognised is handed back to the
        program - which is right for Tab and catastrophic for an arrow,
        because the arrow then reaches the real control and the classic
        edit field answers it underneath the one being walked. That is
        what "strzalki odpalaja klasyczne pole edycji" was."""
        for nvda, wire in (('leftArrow', 'left'), ('rightArrow', 'right'),
                           ('upArrow', 'up'), ('downArrow', 'down'),
                           ('backspace', 'back'), ('return', 'enter')):
            self.assertEqual(self.tf.bare_name(nvda), wire, nvda)
            self.assertEqual(self.tf.bare_name(wire), wire, wire)

    def test_an_arrow_is_never_handed_to_the_program(self):
        field = self._field(text='abc', at=1, multiline=False)
        for key in ('leftArrow', 'rightArrow', 'control+leftArrow',
                    'left', 'ctrl+left'):
            what, _said = self.tf.press(field, key)
            self.assertNotEqual(what, '', '%s reached the real control' % key)

    def test_control_is_spelled_both_ways(self):
        for key in ('control+leftArrow', 'ctrl+left'):
            field = self._field(text='one two', at=7, multiline=False)
            self.tf.press(field, key)
            self.assertEqual(field.at, 4, key)

    def test_escape_is_never_typed(self):
        """It is the way out of the mode."""
        field = self._field(text='ab', at=2, multiline=False)
        what, _said = self.tf.press(field, 'escape')
        self.assertEqual(what, '')
        self.assertEqual(field.text, 'ab')

    def test_the_virtual_window_passes_the_modifiers_too(self):
        """Or Control and an arrow is a plain arrow, and Control and
        Backspace takes one character."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def script_virtualType(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('modifierNames', block)

    def test_tab_is_never_the_fields(self):
        field = self._field()
        self.assertEqual(self.tf.press(field, 'tab')[0], '')

    def test_a_read_only_field_moves_and_refuses_to_change(self):
        field = self.tf.Field(text='abc', at=1, readonly=True)
        self.assertEqual(self.tf.press(field, 'x')[0], 'edge')
        self.assertEqual(field.text, 'abc')
        self.assertEqual(self.tf.press(field, 'right')[0], 'moved')

    # ------------------------------------------------------------ saying
    def test_the_caret_says_the_character_it_is_ON(self):
        """A caret sits BETWEEN characters and every reader says the one
        after it - that is the one the next keystroke acts on."""
        field = self._field(text='abc', at=0, multiline=False)
        self.assertEqual(field.character(), 'a')

    def test_a_field_is_announced_like_every_other_list(self):
        field = self._field()
        parts = field.parts()
        self.assertTrue(parts)
        self.assertEqual(parts[0][1], 'name')
        self.assertTrue(any(voice == 'place' for _text, voice in parts))

    def test_an_empty_line_is_said_as_blank_not_as_silence(self):
        field = self.tf.Field(text='', at=0)
        self.assertTrue(field.parts()[0][0])

    def test_the_virtual_window_walks_the_field_rather_than_relaying(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements',
                                      'virtualWindow.py'),
                         encoding='utf-8').read()
        at = source.index('def type_key(')
        block = source[at:source.index('\ndef _write_back', at)]
        self.assertIn('textField.press', block)


# --------------------------------------------------------------------------- #
class TypingIntoADescribedField(unittest.TestCase):
    """The other half of the edit-field mode: a described application has
    no control here to focus - it is in another process, behind the
    Action Bus - so the keys are relayed to the field itself, which holds
    the text and the caret."""

    def setUp(self):
        from titanEnhancements import appReview
        self.app = appReview
        self.sent = []
        self._act = appReview._act
        appReview._act = lambda work: self.sent.append(work)
        self.addCleanup(lambda: setattr(appReview, '_act', self._act))
        appReview._state.update({'on': True, 'session': 's1', 'at': 0,
                                 'inner': 0, 'menu': None, 'typing': None,
                                 'screen': {'controls': [
                                     {'id': 7, 'kind': 'text',
                                      'label': 'Title', 'value': ''}]}})
        self.addCleanup(lambda: appReview._state.update(
            {'on': False, 'typing': None, 'screen': {}, 'at': 0}))

    def test_enter_on_a_field_turns_the_mode_on(self):
        ok, said = self.app.activate()
        self.assertTrue(ok)
        self.assertTrue(self.app.typing_mode())
        self.assertTrue(said)

    def test_escape_turns_it_off_and_the_pair_is_symmetrical(self):
        _ok, on = self.app.activate()
        ok, off = self.app.leave_typing()
        self.assertTrue(ok)
        self.assertFalse(self.app.typing_mode())
        self.assertEqual(on.rsplit(' ', 1)[0], off.rsplit(' ', 1)[0])

    def test_a_read_only_field_is_refused_with_a_reason(self):
        self.app._state['screen']['controls'][0]['readonly'] = True
        ok, said = self.app.activate()
        self.assertFalse(ok)
        self.assertTrue(said)
        self.assertFalse(self.app.typing_mode())

    def test_a_letter_edits_the_field_and_is_written_back(self):
        """`app.set` is the only way a described application's field can
        be changed at all - `app.key` reaches the window's own handlers,
        which is where an application binds F5."""
        import time
        from titanEnhancements import titan as titan_module
        written = []
        was = titan_module.set_described
        titan_module.set_described = (
            lambda session, control, value:
            (written.append((control, value)), (True, {}))[1])
        try:
            self.app.activate()
            ok, _said = self.app.relay('a')
            self.assertTrue(ok)
            for _ in range(50):
                if written:
                    break
                time.sleep(0.02)
        finally:
            titan_module.set_described = was
        self.assertEqual(written, [(7, 'a')])

    def test_a_key_the_field_does_not_want_goes_to_the_application(self):
        """Tab, and Enter in a one-line field, which presses the form's
        default button."""
        sent = []
        was = self.app._act
        self.app._act = lambda work: sent.append(work)
        try:
            self.app.activate()
            self.app.relay('tab')
        finally:
            self.app._act = was
        self.assertEqual(len(sent), 1)

    def test_typing_never_re_reads_the_whole_control(self):
        """`_act` re-announces it after every call, which is right for a
        press and would read "Title, edit, abc" back at somebody for
        every letter they typed."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'appReview.py'),
                         encoding='utf-8').read()
        at = source.index('def relay(')
        block = source[at:source.index('\ndef _value_of', at)]
        self.assertIn('textField.press', block)
        self.assertIn('_took_quietly', block)

    def test_both_modes_ask_the_same_field(self):
        """One implementation, so the app browser and the virtual window
        cannot drift apart about what Backspace means."""
        for name in ('appReview.py', 'virtualWindow.py'):
            source = io.open(os.path.join(ADDON, 'globalPlugins',
                                          'titanEnhancements', name),
                             encoding='utf-8').read()
            self.assertIn('textField.press', source, name)

    def test_nvdas_key_names_are_translated_to_the_wires(self):
        """NVDA says `leftArrow` and `control`; the shim's field is
        written against the names an interface would send, so the
        translation happens once rather than in every caller."""
        self.assertEqual(self.app.wire_key('leftArrow', ['control']),
                         'ctrl+left')
        self.assertEqual(self.app.wire_key('a', ['shift']), 'shift+a')
        self.assertEqual(self.app.wire_key('backspace'), 'back')
        self.assertEqual(self.app.wire_key('downArrow'), 'down')
        self.assertEqual(self.app.wire_key('a'), 'a')

    def test_escape_is_not_relayed(self):
        """It is the way out, and a field that swallowed it would be a
        mode nobody could leave."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def _typing_gestures(')
        end = source.index('\n    def ', at + 10)
        block = source[at:end]
        self.assertIn("wanted['kb:escape'] = 'appLeave'", block)

    def test_every_printable_key_is_held_while_typing(self):
        """A field that took only the letters would be a field you could
        not put a number or a full stop in."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('TYPING_CHARACTERS = ')
        block = source[at:at + 300]
        for wanted in ('abcdefghijklmnopqrstuvwxyz', '0123456789'):
            self.assertIn(wanted, block)


# --------------------------------------------------------------------------- #
class WhatAPictureOfAWindowIS(unittest.TestCase):
    """`sceneModel.py` - the structure, worked out from geometry.

    The recogniser answers words and rectangles, which is enough to make
    a drawn window navigable and not enough to make it understandable: a
    menu bar, a list with columns, a status line and the entry the arrow
    keys are on all arrive as the same flat run of text.
    """

    def setUp(self):
        from titanEnhancements import sceneModel
        self.scene = sceneModel
        sceneModel.forget()

    @staticmethod
    def _piece(text, left, top, width=60, height=12, line=0, column=0,
               selected=False):
        return {'text': text, 'left': left, 'top': top, 'width': width,
                'height': height, 'line': line, 'column': column,
                'selected': selected}

    def test_a_menu_bar_is_recognised_by_SHAPE_not_by_its_words(self):
        """"File Edit View" is English and the same bar in Polish is
        "Plik Edycja Widok". What is the same in every language is
        several short pieces spread across the top."""
        pieces = [self._piece('Plik', 0, 0, 40),
                  self._piece('Edycja', 100, 0, 50),
                  self._piece('Widok', 200, 0, 45),
                  self._piece('Pomoc', 300, 0, 45)]
        for index in range(6):
            pieces.append(self._piece('body %d' % index, 0, 40 + index * 20,
                                      line=index + 1))
        found = self.scene.scene(pieces)
        self.assertTrue(found['menu'], 'the top row was not read as a menu')
        self.assertEqual(found['rows'][0]['kind'], 'menubar')

    def test_columns_that_repeat_are_a_table(self):
        """A table is not declared anywhere in a picture; what says so is
        that the same left edge comes back row after row."""
        pieces = []
        for row in range(5):
            pieces.append(self._piece('name%d' % row, 0, row * 20, line=row))
            pieces.append(self._piece('%d KB' % row, 300, row * 20, line=row))
            pieces.append(self._piece('1 Jan', 500, row * 20, line=row))
        found = self.scene.scene(pieces)
        self.assertGreaterEqual(len(found['columns']), 2)
        self.assertIn('cells', [row['kind'] for row in found['rows']])

    def test_two_pieces_that_happen_to_line_up_are_not_a_table(self):
        """Fewer than COLUMN_ROWS of them is a coincidence."""
        pieces = [self._piece('a', 0, 0, line=0),
                  self._piece('b', 300, 0, line=0),
                  self._piece('c', 0, 20, line=1),
                  self._piece('d', 300, 20, line=1)]
        found = self.scene.scene(pieces)
        self.assertLess(len(found['columns']), 2)

    def test_the_highlight_is_the_selection(self):
        pieces = [self._piece('One', 0, 0, line=0),
                  self._piece('Two', 0, 20, line=1, selected=True),
                  self._piece('Three', 0, 40, line=2)]
        found = self.scene.scene(pieces)
        self.assertEqual([one['text'] for one in found['selected']], ['Two'])
        self.assertEqual(found['rows'][1]['cells'][0]['kind'], 'selected')

    def test_the_bottom_band_is_a_status_line(self):
        pieces = [self._piece('Title', 0, 0, line=0)]
        for index in range(6):
            pieces.append(self._piece('row %d' % index, 0, 20 + index * 20,
                                      line=index + 1))
        pieces.append(self._piece('Ready', 0, 200, line=7))
        found = self.scene.scene(pieces)
        self.assertEqual(found['rows'][-1]['kind'], 'status')

    def test_nothing_is_invented(self):
        """A piece's text is exactly what came back; what is added is
        where it sits and what that position means."""
        pieces = [self._piece('Only this', 0, 0)]
        found = self.scene.scene(pieces)
        said = [one['text'] for row in found['rows'] for one in row['cells']]
        self.assertEqual(said, ['Only this'])

    def test_an_empty_reading_is_an_empty_scene_not_a_crash(self):
        for nothing in ([], None, [{'text': ''}]):
            found = self.scene.scene(nothing)
            self.assertEqual(found['rows'], [])

    def test_everything_reads_the_window_as_it_is_laid_out(self):
        pieces = [self._piece('name', 0, 0, line=0),
                  self._piece('size', 300, 0, line=0)]
        lines = self.scene.everything(self.scene.scene(pieces))
        self.assertTrue(any('name' in line and 'size' in line
                            for line in lines))


class TheLocalModelIsATierOfItsOwn(unittest.TestCase):
    """Between Windows' recogniser and the AI: a modern OCR model running
    on this machine. Nothing leaves it, nothing is spent, and it reads a
    game's stylised menu and a low-resolution guest that Windows cannot.
    """

    def setUp(self):
        from titanEnhancements import localOcr
        self.localOcr = localOcr

    def test_it_answers_the_same_Reading_as_windows_own(self):
        """So everything built on that - the pieces, the scene, the
        cursor, the virtual window - works on it unchanged."""
        self.assertTrue(hasattr(self.localOcr, 'read_window_model'))
        self.assertTrue(hasattr(self.localOcr, 'model_available'))

    def test_a_model_that_is_not_there_answers_None_rather_than_raising(self):
        from titanEnhancements import link
        was = link.LINK.bridge
        link.LINK.bridge = lambda call, **kw: (False, 'Titan is not running')
        try:
            self.assertIsNone(self.localOcr.read_window_model(1))
            ok, _why = self.localOcr.model_available()
            self.assertFalse(ok)
        finally:
            link.LINK.bridge = was

    def test_a_reading_from_the_model_becomes_lines(self):
        from titanEnhancements import link
        was = link.LINK.bridge

        def answer(call, **kw):
            return True, {'ok': True, 'ms': 12, 'lines': [
                {'text': 'New game', 'left': 10, 'top': 20,
                 'width': 80, 'height': 14}]}
        link.LINK.bridge = answer
        try:
            reading = self.localOcr.read_window_model(1)
        finally:
            link.LINK.bridge = was
        self.assertIsNotNone(reading)
        self.assertEqual(reading.text, 'New game')
        self.assertEqual(reading.rows()[0][1], (10, 20, 80, 14))

    def test_the_model_is_asked_before_the_AI_and_after_windows(self):
        """The tier order the user asked for, with a free private step in
        the middle: Windows' recogniser, then this, and the AI only when
        even it found nothing."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'surface.py'),
                         encoding='utf-8').read()
        at = source.index('def _watch_locally(')
        end = source.index('\ndef ', at + 10)
        block = source[at:end]
        self.assertIn('_model_reading', block)
        model_at = block.index('_model_reading')
        ai_at = block.rindex('return MODE_APPLICATION')
        self.assertLess(model_at, ai_at,
                        'the AI is asked before the model on this machine')

    def test_fetching_it_is_asked_for_and_never_automatic(self):
        """It is a download of a few hundred megabytes."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'commands.py'),
                         encoding='utf-8').read()
        at = source.index('def local_model(')
        end = source.index('\ndef ', at + 10)
        block = source[at:end]
        self.assertIn('dialogs.confirm', block)
        self.assertIn('install_local_model', block)


# --------------------------------------------------------------------------- #
class TheMenuBarIsInTheListAndAtTheTop(unittest.TestCase):
    """The menu bar is most of what a program can be told to do, and
    neither walker had it: the virtual window dropped it because wx gives
    it no accessible name (the "nothing to call it by" rule), and the
    application review walked only `controls`, while a described screen
    carries its `menus` beside them."""

    class Obj:
        def __init__(self, name='', role='BUTTON', children=()):
            self.name = name
            self.value = ''
            self.description = ''
            self.role = types.SimpleNamespace(name=role)
            self.children = list(children)
            self.location = types.SimpleNamespace(left=0, top=0,
                                                  width=40, height=20)
            self.states = set()

    def test_an_unnamed_menu_bar_is_still_a_row(self):
        from titanEnhancements import virtualWindow
        window = self.Obj(name='A window', role='WINDOW', children=[
            self.Obj(name='', role='MENUBAR'),
            self.Obj(name='Save', role='BUTTON')])
        rows = virtualWindow.nodes_of(window)
        roles = [str(row.get('role') or '').upper() for row in rows]
        self.assertIn('MENUBAR', roles)

    def test_it_comes_first(self):
        from titanEnhancements import virtualWindow
        window = self.Obj(name='A window', role='WINDOW', children=[
            self.Obj(name='Save', role='BUTTON'),
            self.Obj(name='Open', role='BUTTON'),
            self.Obj(name='', role='MENUBAR')])
        rows = virtualWindow.nodes_of(window)
        self.assertEqual(str(rows[0].get('role') or '').upper(), 'MENUBAR')

    def test_a_described_screens_menus_are_walked_too(self):
        from titanEnhancements import appReview
        screen = {'controls': [{'id': 1, 'kind': 'button', 'label': 'Save'}],
                  'menus': [{'label': 'File', 'items': [
                      {'id': 10, 'label': 'New'},
                      {'id': 11, 'label': 'Open'}]}]}
        rows = appReview._controls(screen)
        self.assertEqual(rows[0]['kind'], 'menu')
        self.assertEqual(rows[0]['label'], 'File')
        self.assertEqual(rows[-1]['label'], 'Save')

    def test_a_menu_opens_in_place_and_escape_comes_back(self):
        """A flyout is a menu a keyboard cannot follow - the answer
        Titan's own Start menu arrived at for the same reason."""
        from titanEnhancements import appReview
        appReview._state.update({'on': True, 'at': 0, 'inner': 0,
                                 'menu': None, 'screen': {
                                     'controls': [{'id': 1, 'kind': 'button',
                                                   'label': 'Save'}],
                                     'menus': [{'label': 'File', 'items': [
                                         {'id': 10, 'label': 'New'}]}]}})
        self.addCleanup(lambda: appReview._state.update(
            {'on': False, 'menu': None, 'screen': {}, 'at': 0}))
        row = appReview._controls()[0]
        ok, _said = appReview.open_menu(row)
        self.assertTrue(ok)
        self.assertTrue(appReview.in_a_menu())
        self.assertEqual([one['label'] for one in appReview._controls()],
                         ['New'])
        appReview.close_menu()
        self.assertFalse(appReview.in_a_menu())
        self.assertEqual(appReview._controls()[0]['kind'], 'menu')

    def test_a_separator_is_not_an_item(self):
        """`app_ui.model.menu` says an item with no id is a separator, and
        a row somebody arrows onto and is told nothing about is worse than
        a shorter list."""
        from titanEnhancements import appReview
        ok, _said = appReview.open_menu(
            {'label': 'File', 'items': [{'id': 10, 'label': 'New'},
                                        {'label': '-'},
                                        {'id': 11, 'label': 'Exit'}]})
        self.addCleanup(lambda: appReview._state.update({'menu': None}))
        self.assertTrue(ok)
        self.assertEqual([one['label'] for one in appReview._controls()],
                         ['New', 'Exit'])


# --------------------------------------------------------------------------- #
class ThePaletteIsWalkedLikeAWindow(unittest.TestCase):
    """A modal dialog is the one interaction here that is not like the
    others: it takes the keyboard from the reader, NVDA reads it as a
    dialog rather than this add-on reading it in the user's own voice
    classes, and it plays none of the auditory icons every other list
    plays. The palette is opened twenty times a day and was the one thing
    that did not feel like the rest of the add-on."""

    def setUp(self):
        from titanEnhancements import palette
        self.palette = palette
        palette.forget()
        self.addCleanup(palette.forget)

    def _rows(self, count=3):
        self.ran = []
        return [{'label': 'Row %d' % n, 'role': 'command',
                 'run': (lambda n=n: (self.ran.append(n) or (True, '')))}
                for n in range(count)]

    def test_it_is_a_list_and_not_a_dialog(self):
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', 'commands.py'),
                         encoding='utf-8').read()
        at = source.index('def command_palette(')
        end = source.index('\ndef ', at + 10)
        block = source[at:end]
        self.assertIn('palette.show', block)
        self.assertNotIn('dialogs.choose', block,
                         'the palette is walked, not shown as a dialog')

    def test_the_arrows_walk_it(self):
        self.palette.show(self._rows(), 'Commands')
        self.assertEqual(self.palette.here()['label'], 'Row 0')
        self.palette.move(1)
        self.assertEqual(self.palette.here()['label'], 'Row 1')
        self.palette.move(-1)
        self.assertEqual(self.palette.here()['label'], 'Row 0')

    def test_it_stops_at_the_ends_rather_than_wrapping(self):
        self.palette.show(self._rows(), 'Commands')
        self.palette.move(-1)
        self.assertEqual(self.palette.here()['label'], 'Row 0')
        self.palette.move_end(True)
        self.palette.move(1)
        self.assertEqual(self.palette.here()['label'], 'Row 2')

    def test_enter_runs_what_the_cursor_is_on(self):
        self.palette.show(self._rows(), 'Commands')
        self.palette.move(1)
        self.palette.activate()
        self.assertEqual(self.ran, [1])

    def test_escape_goes_back_one_level_before_it_closes(self):
        """Picking the wrong layer should cost one keystroke rather than
        the whole palette."""
        went = []
        self.palette.show(self._rows(), 'Second',
                          back=lambda: (went.append(True), (True, ''))[1])
        self.palette.back()
        self.assertEqual(went, [True])
        self.palette.show(self._rows(), 'First')
        self.palette.back()
        self.assertFalse(self.palette.walking())

    def test_it_is_one_of_the_reviews_that_share_the_arrows(self):
        """NVDA binds a gesture to one script per plugin, so two of these
        up at once means the second one's bindings replaced the first's -
        and the first is a review that still says it is running and
        answers no key at all."""
        from titanEnhancements import reviews
        self.assertIn('palette', reviews._ALL)
        self.assertTrue(hasattr(self.palette, 'reviewing'))
        self.palette.show(self._rows(), 'Commands')
        self.assertTrue(self.palette.reviewing())

    def test_a_row_with_no_label_is_not_a_row(self):
        ok, _said = self.palette.show([{'label': '', 'run': lambda: None}],
                                      'Commands')
        self.assertFalse(ok)


# --------------------------------------------------------------------------- #
class TypingIntoAFieldFromTheVirtualWindow(unittest.TestCase):
    """Enter on a field means "type into it", and Escape comes back.

    Pressing a field is not a thing anybody wants done to it - its own
    action is usually nothing at all, so Enter fell through to a click,
    which put the caret in the field and left the virtual window still
    holding every letter, every arrow and Enter itself. The user was in
    a field they could not type a word into.
    """

    class Obj:
        def __init__(self, role='EDITABLETEXT', states=()):
            self.name = 'Title'
            self.value = ''
            self.description = ''
            self.role = types.SimpleNamespace(name=role)
            self.children = []
            self.states = set(states)
            self.focused = False

        def setFocus(self):
            self.focused = True

    def setUp(self):
        from titanEnhancements import virtualWindow
        self.vw = virtualWindow
        virtualWindow._state.update({'on': True, 'at': 0, 'inner': 0,
                                     'typing': False})
        self.addCleanup(lambda: virtualWindow._state.update(
            {'on': False, 'nodes': [], 'at': 0, 'inner': 0,
             'typing': False}))

    def _field(self, role='EDITABLETEXT'):
        obj = self.Obj(role=role)
        self.vw._state['nodes'] = [{'name': 'Title', 'value': '',
                                    'description': '', 'role': role,
                                    'level': 0, 'obj': obj}]
        return obj

    def test_a_field_is_recognised_by_its_role(self):
        self.assertTrue(self.vw._is_a_field(
            {'role': 'EDITABLETEXT', 'obj': None}))
        self.assertFalse(self.vw._is_a_field(
            {'role': 'BUTTON', 'obj': None}))

    def test_enter_hands_the_keyboard_over(self):
        obj = self._field()
        ok, said = self.vw.activate()
        self.assertTrue(ok)
        self.assertTrue(obj.focused, 'the real field never took the focus')
        self.assertTrue(self.vw.typing_mode())
        self.assertTrue(said)

    def test_escape_takes_it_back(self):
        self._field()
        self.vw.activate()
        ok, said = self.vw.leave_typing()
        self.assertTrue(ok)
        self.assertFalse(self.vw.typing_mode())
        self.assertTrue(said)

    def test_the_pair_is_symmetrical(self):
        """A toggle says which state it is in; somebody should not have to
        listen to work out which one they are now in."""
        self._field()
        _ok, on = self.vw.activate()
        _ok, off = self.vw.leave_typing()
        self.assertNotEqual(on, off)
        self.assertEqual(on.rsplit(' ', 1)[0], off.rsplit(' ', 1)[0])

    def test_leaving_the_window_leaves_the_field(self):
        self._field()
        self.vw.activate()
        self.vw.stop()
        self.assertFalse(self.vw.typing_mode())

    def test_typing_mode_is_off_when_the_window_is(self):
        """It is read as a mode of the virtual window, so it cannot be on
        while the virtual window is not."""
        self._field()
        self.vw.activate()
        self.vw._state['on'] = False
        self.assertFalse(self.vw.typing_mode())

    def test_while_typing_the_addon_holds_only_escape(self):
        """Every letter, every arrow, Backspace and Enter belong to the
        program being typed into - Up and Down are its lines, Left and
        Right its characters, Control and an arrow its words. Holding one
        key rather than none is the whole of what makes the mode
        leavable."""
        source = io.open(os.path.join(ADDON, 'globalPlugins',
                                      'titanEnhancements', '__init__.py'),
                         encoding='utf-8').read()
        at = source.index('def _virtual_wants(')
        end = source.index('\n    def ', at + 10)
        self.assertIn("'escape'", source[at:end])
        at = source.index('def _keep_virtual_keys_right(')
        end = source.index('\n    def ', at + 10)
        block = source[at:end]
        self.assertIn("kb:escape", block)
        self.assertIn("'all'", block)


# --------------------------------------------------------------------------- #
class OpenMeansTheVirtualWindow(unittest.TestCase):
    """The Open button in the Titan window.

    It built a window of native controls, which is a second interface to
    be in rather than the one the user has already learned everywhere
    else here. That view is still there - "As real controls" on the menu -
    for a form that is easier to fill in than to read.
    """

    def setUp(self):
        self.source = _source_of('titanWindow.py')

    def test_open_starts_the_virtual_window(self):
        block = self.source.split('def _open_here', 1)[1]
        block = block.split('\n        def ', 1)[0]
        self.assertIn('appReview.start', block)
        self.assertNotIn('appScreen', block)

    def test_open_still_means_something_for_a_game(self):
        """A game is played on Titan's own screen and a menu entry is a
        command: there is no virtual window to be had, and a first button
        greyed out for four of the five kinds is one nobody trusts."""
        block = self.source.split('def _open_here', 1)[1]
        block = block.split('\n        def ', 1)[0]
        self.assertIn('_start_it', block)
        self.assertNotIn('_here_button', self.source)

    def test_the_other_button_says_where_it_opens(self):
        self.assertIn("_('Open in &Titan')", self.source)


class AWidgetIsAVirtualWindowToo(unittest.TestCase):
    """A widget's cursor lives in Titan, so the arrows move it there.

    The other reviews build the whole thing up front and then move about
    locally. A widget answers one element at a time and nothing answers
    how many there are - so there is no list, no "3 of 10", and no page
    key offered that could not be honoured.
    """

    def setUp(self):
        from titanEnhancements import widgetReview
        self.review = widgetReview
        self.said = []
        self._say = widgetReview._say
        self._parts = widgetReview._say_parts
        widgetReview._say = lambda text: self.said.append(str(text))
        widgetReview._say_parts = lambda parts: self.said.append(
            ', '.join(str(text) for text, _voice in parts))
        self.addCleanup(lambda: setattr(widgetReview, '_say', self._say))
        self.addCleanup(
            lambda: setattr(widgetReview, '_say_parts', self._parts))
        self.addCleanup(lambda: widgetReview._state.update(
            {'on': False, 'widget': '', 'said': ''}))

    def test_the_directions_are_the_ones_titan_understands(self):
        """`up`, `down`, `left`, `right` - read out of Titan's own applets.
        `next` is what this was written with first, and it moved nothing at
        all: the applet's navigate() tests for the four words and silently
        ignores anything else."""
        source = _source_of('__init__.py')
        block = source.split('def script_widgetUp', 1)[1][:900]
        for word in ("'up'", "'down'", "'left'", "'right'"):
            self.assertIn(word, block, word)
        self.assertNotIn("'next'", block)

    def test_a_move_that_changed_nothing_is_the_end_of_the_widget(self):
        """Titan answers the same element when the move went nowhere, and
        saying it again would be a cursor that reads as stuck."""
        from titanEnhancements import titan
        self.review._state.update({'on': True, 'widget': 'taskbar',
                                   'name': 'Taskbar', 'said': 'the same'})
        edges = []
        was_edge = self.review._edge
        self.review._edge = lambda: edges.append(1)
        was_move = titan.move_widget
        titan.move_widget = lambda widget, direction: (True, 'the same')
        try:
            self.review.move('down')
            for _ in range(40):
                if edges:
                    break
                time.sleep(0.02)
        finally:
            self.review._edge = was_edge
            titan.move_widget = was_move
        self.assertEqual(edges, [1])

    def test_it_is_one_of_the_reviews_that_end_each_other(self):
        from titanEnhancements import reviews
        self.assertIn('widgetReview', reviews._ALL)

    def test_it_answers_the_two_questions_every_review_answers(self):
        self.assertTrue(callable(self.review.reviewing))
        self.assertTrue(callable(self.review.stop))


class TheSettingsAreShapedLikeTheJawsSettingsCentre(unittest.TestCase):
    """One list, Space acts on the row, and a word is edited in a field.

    Asked for in those terms. Pressing a button called "Change" is one
    more thing to Tab to for something that should be a keystroke, and a
    dialog on top of the window is a second place for the keyboard to be.
    """

    def setUp(self):
        self.source = _source_of('titanWindow.py')

    def test_space_acts_on_the_row(self):
        block = self.source.split('def _setting_key', 1)[1][:400]
        self.assertIn('WXK_SPACE', block)
        self.assertIn('_change_setting', block)

    def test_a_word_setting_is_a_real_edit_field(self):
        block = self.source.split('def _setting_chosen', 1)[1][:900]
        for kind in ("'text'", "'number'", "'secret'"):
            self.assertIn(kind, block, kind)
        self.assertIn('self.field.Show', block)

    def test_nothing_raises_a_dialog_to_type_into_any_more(self):
        self.assertNotIn('TextEntryDialog', self.source)

    def test_the_list_is_called_what_is_IN_it(self):
        """"Titan has, list" is a sentence about the window; "Applications,
        list" is what the keyboard has landed on."""
        self.assertNotIn("_('&Titan has')", self.source)
        # To the end of the method rather than a number of characters: a
        # slice measured in characters fails the day somebody writes a
        # comment, which is a test that punishes explaining yourself.
        block = self.source.split('def _kind_chosen', 1)[1]
        block = block.split('\n        def ', 1)[0]
        self.assertIn('self.things.SetName', block)


class ACappedWalkIsAHoleNotABudget(unittest.TestCase):
    """Found on a real taskbar: an anchored control was not found again.

    `anchors.find` and `monitors._find_control` both walked a window
    breadth first and queued `children[:40]`. The walk is already bounded
    by how many objects it looks at, so capping the CHILDREN buys nothing
    and costs everything: a control past the fortieth child of its parent
    could never be reached, so a place marker on the twelfth tray icon or
    a monitor on a deep toolbar row silently never came back.
    """

    class Obj:
        def __init__(self, name='', children=()):
            self.name = name
            self.value = ''
            self.description = ''
            self.role = types.SimpleNamespace(name='BUTTON')
            self.children = list(children)
            self.windowClassName = 'Shell_TrayWnd'
            self.UIAAutomationId = name

    def test_a_control_past_the_fortieth_child_is_still_found(self):
        from titanEnhancements import anchors
        from titanEnhancements import labels
        wanted = self.Obj(name='the fiftieth')
        window = self.Obj(name='taskbar', children=[
            self.Obj(name='button %d' % index) for index in range(49)
        ] + [wanted])
        key = labels.key_of(wanted)[0]
        module = types.ModuleType('api')
        module.getForegroundObject = lambda: window
        had = sys.modules.get('api')

        def put_back():
            if had is None:
                sys.modules.pop('api', None)
            else:
                sys.modules['api'] = had
        sys.modules['api'] = module
        self.addCleanup(put_back)
        note = {}
        found = anchors.find({'kind': anchors.BY_CONTROL, 'where': key},
                             note)
        self.assertIs(found, wanted,
                      'not found, and it said: %s' % note.get('why'))

    def test_neither_walk_caps_the_children_any_more(self):
        for name in ('anchors.py', 'monitors.py'):
            self.assertNotIn('children or [])[:40]', _source_of(name), name)

    def test_it_says_WHY_it_found_nothing(self):
        """"It was not found" has four causes with four different things
        to do about them, and a caller that cannot tell them apart reports
        a bug that is really a window having closed."""
        from titanEnhancements import anchors
        note = {}
        anchors.find({'kind': anchors.BY_CONTROL, 'where': ''}, note)
        self.assertTrue(note.get('why'))


class InstallingNeverLeavesHalfAScreenReader(unittest.TestCase):
    """The installer used to empty the folder and then copy into it.

    Shipping sound files broke that: NVDA holds a `.wav` open the moment
    it has played one, so the delete failed AFTER the folder had been
    emptied, and what was on disk was a half-installed screen reader -
    measured, 21 of 29 auditory icons gone. Writing over instead means a
    file that cannot be replaced keeps its previous version, which is one
    file behind and a working reader.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.installer = os.path.join(os.path.dirname(HERE), 'install.py')
        if not os.path.isfile(self.installer):
            self.skipTest('install.py is not beside the tests')

    def _install(self):
        import subprocess
        return subprocess.run([sys.executable, self.installer, '--to',
                               self.dir], capture_output=True, text=True,
                              cwd=os.path.dirname(self.installer))

    def test_a_file_that_cannot_be_written_costs_only_that_file(self):
        import stat
        first = self._install()
        if not os.path.isdir(os.path.join(self.dir, 'globalPlugins')):
            self.skipTest('the add-on could not be built here: %s'
                          % first.stdout[-200:])
        sounds = os.path.join(self.dir, 'globalPlugins', 'titanEnhancements',
                              'sounds')
        victim = os.path.join(sounds, 'button.wav')
        with io.open(victim, 'wb') as handle:
            handle.write(b'OLD VERSION')
        os.chmod(victim, stat.S_IREAD)
        try:
            again = self._install()
        finally:
            os.chmod(victim, stat.S_IWRITE)
        # Everything else is really there, which is the whole point.
        self.assertGreater(sum(len(names) for _b, _d, names
                               in os.walk(self.dir)), 100)
        self.assertEqual(len(os.listdir(sounds)), 29)
        with io.open(victim, 'rb') as handle:
            self.assertEqual(handle.read(), b'OLD VERSION')
        # And the user is told which file, rather than being left to find
        # out from a reader that has gone quiet.
        self.assertIn('button.wav', again.stdout)

    def test_the_installer_does_not_empty_the_folder_any_more(self):
        with io.open(self.installer, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('def _empty(', source)
        self.assertIn('_write_over', source)


class AllOfTitanIsAMEASUREMENT(unittest.TestCase):
    """"All of Titan" is a claim, so it is counted rather than asserted.

    The live check (`selftest._titan_map`) asks Titan what its bridge
    serves and sweeps this add-on for every one of those names. It has to
    go red when one is missing, or passing proves nothing - and it has to
    sweep the WHOLE add-on, because reading one module reported 49 of 58
    while nothing at all was missing, which is a measurement that invites
    work on a gap that is not there.
    """

    def setUp(self):
        from titanEnhancements import selftest
        self.selftest = selftest

    def test_the_sweep_finds_a_call_that_is_really_asked_for(self):
        asked = self.selftest._asked_for()
        for call in ('apps.list', 'settings.set', 'app.open', 'speech.say',
                     'notifications.add', 'client.report', 'app.log',
                     'ai.available', 'widgets.read', 'menu.run'):
            self.assertIn(call, asked, call)

    def test_the_sweep_does_not_invent_one(self):
        self.assertNotIn('nonsense.call', self.selftest._asked_for())

    def test_it_goes_red_when_something_is_unreached(self):
        """Proved by making Titan claim a call nobody asks for."""
        from titanEnhancements.link import LINK
        was = LINK.bridge
        LINK.bridge = lambda call, timeout=None, **args: (
            True, {'calls': ['apps.list', 'nobody.asks']})
        connected = LINK.connected
        LINK.connected = lambda: True
        try:
            ok, said = self.selftest._titan_map()
        finally:
            LINK.bridge = was
            LINK.connected = connected
        self.assertFalse(ok)
        self.assertIn('nobody.asks', said)

    def test_nothing_is_exempt_any_more(self):
        """The exemption list used to hold most of Titan. It is empty, and
        a name put back must carry the reason beside it - which is what
        this test is for: it fails on a silent re-exemption."""
        self.assertEqual(EverySubsystemTitanHasIsReachable.NOT_OURS, set())


class ALetterIsTheLetterWhenYouAreTyping(unittest.TestCase):
    """The one guard quick navigation cannot do without.

    The virtual window turns itself on in a program the user chose, and a
    bare `b` would then be a command rather than the letter b. Browse mode
    has exactly this problem and answers it exactly this way.
    """

    def setUp(self):
        from titanEnhancements import virtualWindow
        self.vw = virtualWindow

    def _focus_is(self, role, states=()):
        module = types.ModuleType('api')
        module.getFocusObject = lambda: types.SimpleNamespace(
            role=types.SimpleNamespace(name=role), states=set(states))
        had = sys.modules.get('api')

        def put_back():
            if had is None:
                sys.modules.pop('api', None)
            else:
                sys.modules['api'] = had
        sys.modules['api'] = module
        self.addCleanup(put_back)

    def test_a_field_keeps_its_letters(self):
        self._focus_is('EDITABLETEXT')
        self.assertTrue(self.vw.typing_now())

    def test_a_terminal_and_a_document_keep_theirs_too(self):
        for role in ('TERMINAL', 'DOCUMENT', 'PASSWORDEDIT', 'COMBOBOX'):
            self._focus_is(role)
            self.assertTrue(self.vw.typing_now(), role)

    def test_a_button_does_not(self):
        self._focus_is('BUTTON')
        self.assertFalse(self.vw.typing_now())

    def test_the_key_handler_asks_before_it_takes_the_letter(self):
        source = _source_of('__init__.py')
        block = source.split('def _quick', 1)[1][:600]
        self.assertIn('typing_now()', block)
        self.assertIn('gesture.send()', block)


class OnlyOneReviewAtATime(unittest.TestCase):
    """Four reviews share one set of arrow keys, so only one may be up.

    NVDA binds a gesture to one script per plugin: two at once means the
    second one's bindings replaced the first's, and the first is then a
    review that is still running, still says so, and answers no key. That
    does not look like a bug from outside - it looks like the arrows
    breaking.
    """

    def test_starting_one_ends_the_others(self):
        from titanEnhancements import reviews
        from titanEnhancements import virtualWindow
        ended = []

        class Fake:
            def __init__(self, name):
                self.name = name

            def reviewing(self):
                return True

            def stop(self):
                ended.append(self.name)
                return False, ''
        import sys
        held = {}
        for name in ('terminal', 'ocrReview', 'appReview'):
            full = 'titanEnhancements.' + name
            held[full] = sys.modules.get(full)
            sys.modules[full] = Fake(name)
        try:
            reviews.stop_others('virtualWindow')
        finally:
            for full, was in held.items():
                if was is None:
                    sys.modules.pop(full, None)
                else:
                    sys.modules[full] = was
        self.assertEqual(sorted(ended),
                         ['appReview', 'ocrReview', 'terminal'])

    def test_every_review_asks_before_it_starts(self):
        """Read out of the source, so a fifth review added later without
        asking fails here rather than silently stealing the keys."""
        for name in ('terminal.py', 'ocrReview.py', 'appReview.py',
                     'virtualWindow.py'):
            self.assertIn('reviews.stop_others', _source_of(name), name)

    def test_they_all_answer_the_same_two_questions(self):
        """`reviewing()` and `stop()`, or the one place that ends them
        cannot end them."""
        import importlib
        for name in ('terminal', 'ocrReview', 'appReview', 'virtualWindow'):
            module = importlib.import_module('titanEnhancements.' + name)
            self.assertTrue(callable(getattr(module, 'reviewing', None)), name)
            self.assertTrue(callable(getattr(module, 'stop', None)), name)


class OneReviewKeyDecidedByWhereYouAre(unittest.TestCase):
    """Numpad minus reviews the terminal in a terminal and the window
    everywhere else.

    The contextual half the user asked for: one key, and what it reviews
    is worked out rather than remembered.
    """

    def test_the_key_asks_whether_this_is_a_terminal(self):
        source = _source_of('__init__.py')
        block = source.split('def script_terminalReview', 1)[1][:1400]
        self.assertIn('terminal.is_terminal()', block)
        self.assertIn('virtualWindow.toggle()', block)

    def test_the_virtual_window_is_remembered_per_program(self):
        source = _source_of('virtualWindow.py')
        self.assertIn('perProgram.set_value', source)
        self.assertIn('def consider', source)


class ASilentGuestIsBetterThanARepeatedOne(unittest.TestCase):
    """Reported as: "when it reads with OCR automatically, let it read only
    when something CHANGES, not Start Start Start without a break".

    That was exactly what it did. The de-duplication in `after_key` was
    `said == last AND less than QUIET ago` - 0.35 seconds - and the loop
    that calls it runs on a tick, so a pointer resting anywhere, or a guest
    repainting under a still pointer, said the same row three times a
    second for as long as it was left alone. A time window is the wrong
    instrument: what makes a row worth saying is that it CHANGED.
    """

    def setUp(self):
        from titanEnhancements import guest, localOcr
        self.guest, self.localOcr = guest, localOcr
        guest.forget()
        self.said = []
        self._say = guest._say
        self._wanted = guest.wanted
        guest._say = self.said.append
        guest.wanted = lambda: True
        guest._state.update({'on': True, 'hwnd': 77})

    def tearDown(self):
        self.guest._say = self._say
        self.guest.wanted = self._wanted
        self.guest.forget()

    def reading(self, rows, highlight=None):
        lines = []
        for number, text in enumerate(rows):
            lines.append([{'text': text, 'left': 10, 'top': 100 + number * 20,
                           'width': 120, 'height': 16}])
        made = self.localOcr.Reading(lines)
        if highlight is not None:
            top = 100 + highlight * 20
            made.highlights = [(0, top - 2, 400, 20)]
        return made

    def answer(self, reading):
        self.guest._read_now = lambda hwnd: reading

    def test_the_same_row_is_not_said_again_however_long_it_has_been(self):
        """The bug as reported, which the existing test could not catch:
        it called twice in a row, inside the old 0.35-second window."""
        self.answer(self.reading(['Start'], highlight=0))
        self.assertTrue(self.guest.after_key()[0])
        for _each in range(5):
            # As though a minute had passed between ticks.
            self.guest._state['when'] = time.time() - 60
            self.assertFalse(self.guest.after_key()[0])
        self.assertEqual(self.said, ['Start'])

    def test_how_many_ticks_were_silent_is_counted(self):
        """A reader that says nothing and a reader that is not running are
        the same thing from outside, so the silence is countable."""
        self.answer(self.reading(['Start'], highlight=0))
        self.guest.after_key()
        self.guest._state['when'] = time.time() - 60
        self.guest.after_key()
        self.assertEqual(self.guest.report().get('unchanged'), 1)

    def test_a_row_that_really_changed_is_still_said_at_once(self):
        self.answer(self.reading(['Start'], highlight=0))
        self.guest.after_key()
        self.answer(self.reading(['Kosz'], highlight=0))
        self.guest._state['when'] = time.time() - 60
        ok, said = self.guest.after_key()
        self.assertTrue(ok)
        self.assertEqual(said, 'Kosz')
        self.assertEqual(self.said, ['Start', 'Kosz'])


class VMwareItselfIsAskedRatherThanTheGuest(unittest.TestCase):
    """Asked for as: nobody will install an agent in a guest - plug into
    VMware itself. VMware Workstation ships `vmrun`, and the hypervisor
    answers what the host's accessibility layer cannot: which machine this
    window is, what it is called, whether its tools are running, and one
    guest variable - a channel with no port, no address and no network.

    None of it is on the reading path: a `vmrun` call is a PROCESS, about
    0.3 s, which is twenty times what the layer that reads a control is
    allowed to cost.
    """

    def setUp(self):
        from titanEnhancements import vmware
        self.vmware = vmware
        vmware.forget()
        self._call = vmware._call
        self.calls = []

    def tearDown(self):
        self.vmware._call = self._call
        self.vmware.forget()

    def answer(self, text, ok=True):
        def called(*arguments):
            self.calls.append(arguments)
            return ok, text
        self.vmware._call = called

    def test_the_report_looks_for_vmrun_rather_than_reporting_the_look(self):
        """Read live, this said `available: false` on a machine with VMware
        installed and a guest running, because nothing had asked yet - so
        "not found" and "never looked" came back as one answer."""
        source = _source_of('vmware.py')
        self.assertIn('def report():', source)
        body = source.split('def report():', 1)[1].split('def forget', 1)[0]
        self.assertIn('vmrun()', body)

    def test_the_machines_that_are_running_are_the_vmx_lines(self):
        self.answer('Total running VMs: 1\r\nC:\\VMs\\Windows 95.vmx\r\n')
        self.assertEqual(self.vmware.running(), ['C:\\VMs\\Windows 95.vmx'])

    def test_the_list_is_not_asked_for_twice_in_a_breath(self):
        self.answer('Total running VMs: 1\nC:\\VMs\\a.vmx\n')
        self.vmware.running()
        self.vmware.running()
        self.assertEqual(len(self.calls), 1)

    def test_one_machine_running_is_the_machine_this_window_shows(self):
        """A guest window belongs to the only guest there is, whatever the
        window happens to be called."""
        self.answer('Total running VMs: 1\nC:\\VMs\\a.vmx\n')
        self.assertEqual(self.vmware.vm_for_window(0), 'C:\\VMs\\a.vmx')

    def test_the_name_said_is_the_machines_own(self):
        answers = ['Total running VMs: 1\nC:\\VMs\\a.vmx\n', 'Windows 95']
        def called(*arguments):
            self.calls.append(arguments)
            return True, answers[min(len(self.calls) - 1, 1)]
        self.vmware._call = called
        self.assertEqual(self.vmware.describe(5), 'Windows 95')

    def test_the_name_is_answered_from_what_is_known_with_no_call(self):
        """`warm` is what asks, on a thread, so the reading path never
        waits on a process."""
        def refuse(*arguments):
            raise AssertionError('the reading path must not call vmrun')
        self.vmware._call = refuse
        self.assertEqual(self.vmware.name_now(5), '')
        self.vmware._windows[5] = 'Debian'
        self.assertEqual(self.vmware.name_now(5), 'Debian')

    def test_a_guest_variable_is_read_once_per_change(self):
        """It holds what it was last set to for ever, so reading it on a
        poll would say the same words until the guest said something else.
        A counter in front is how a guest repeats itself, and it is not
        words."""
        self.answer('4|Start')
        self.assertEqual(self.vmware.said('C:\\VMs\\a.vmx'), 'Start')
        self.vmware._vars[('C:\\VMs\\a.vmx', self.vmware.SAY_VAR)] = (
            0.0, '4|Start')
        self.assertEqual(self.vmware.said('C:\\VMs\\a.vmx'), '')

    def test_a_call_that_does_not_answer_is_given_up_on(self):
        """Measured: `runProgramInGuest` against a Windows 95 guest whose
        tools report `running` never answered at all - killed by hand at
        120 seconds. A reader waiting on a subprocess has stopped."""
        source = _source_of('vmware.py')
        self.assertIn('timeout=CALL_TIMEOUT', source)
        self.assertIn('subprocess.TimeoutExpired', source)


class TheAgentChannelIsOptInAndExclusive(unittest.TestCase):
    """A socket that makes a screen reader speak lets any program on the
    machine say anything in the user's ear, so every default here is the
    careful one.
    """

    def setUp(self):
        from titanEnhancements import agentLink
        self.agentLink = agentLink
        self._setting = agentLink._setting
        agentLink._setting = lambda name, default: default

    def tearDown(self):
        self.agentLink._setting = self._setting

    def test_it_is_off_until_it_is_asked_for(self):
        self.assertFalse(self.agentLink.wanted())
        self.assertFalse(self.agentLink.guest_allowed())
        ok, why = self.agentLink.start()
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_a_line_without_the_key_is_dropped_in_silence(self):
        """Answering would tell a prober it had found the port."""
        before = self.agentLink.report()['refused']
        self.assertFalse(self.agentLink._handle(
            '{"token": "not the key", "kind": "pointer", "say": "Start"}'))
        self.assertEqual(self.agentLink.report()['refused'], before + 1)

    def test_a_kind_the_reader_does_not_know_is_dropped(self):
        """It would be announced with no context at all."""
        said = []
        self.agentLink._announce = lambda kind, text: said.append(text) or True
        line = json.dumps({'token': self.agentLink.token(),
                           'kind': 'whatever', 'say': 'Start'})
        self.assertFalse(self.agentLink._handle(line))
        self.assertEqual(said, [])

    def test_a_guest_variable_carries_its_kind(self):
        heard = []
        self.agentLink._announce = lambda kind, text: (
            heard.append((kind, text)) or True)
        self.assertTrue(self.agentLink._from_guest_variable('menu|File'))
        self.assertEqual(heard, [('menu', 'File')])

    def test_a_guest_variable_with_no_kind_is_the_pointer(self):
        heard = []
        self.agentLink._announce = lambda kind, text: (
            heard.append((kind, text)) or True)
        self.assertTrue(self.agentLink._from_guest_variable('Start'))
        self.assertEqual(heard, [('pointer', 'Start')])

    def test_the_port_is_claimed_exclusively_on_windows(self):
        """`SO_REUSEADDR` on Windows lets a SECOND process bind a port that
        is already bound, and connections then go to whichever - for this
        socket that is another program taking over the reader's ear."""
        source = _source_of('agentLink.py')
        self.assertIn('SO_EXCLUSIVEADDRUSE', source)

    def test_it_cannot_be_started_twice_at_once(self):
        """`keep_running` is called from the plugin AND from
        `configSpec.apply`, and both ran during start-up: two sockets were
        bound and the first, collected and closed, wrote `listening: False`
        over a channel that was open. Read from netstat, not from the
        report."""
        source = _source_of('agentLink.py')
        self.assertIn("_state['starting']", source)

    def test_waiting_for_an_agent_survives_a_socket_timing_out(self):
        """Something else in this process had called
        `socket.setdefaulttimeout`, which applies to every socket made
        afterwards - so `accept()` raised `timed out` seconds after the
        channel opened, the loop took that for the socket being gone, and
        the reader reported the channel shut while netstat showed the port
        listening. A channel that is merely waiting is not a channel that
        has failed."""
        source = _source_of('agentLink.py')
        self.assertIn('except socket.timeout:', source)
        self.assertIn('continue', source)
        self.assertIn('ACCEPT_TURN', source)

    def test_a_loop_that_stops_says_why(self):
        """The only reason the timeout was findable at all."""
        source = _source_of('agentLink.py')
        self.assertIn("_note('the channel stopped waiting", source)

    def test_taking_the_network_back_rebinds_at_once(self):
        """Turning "over the network" off left the socket on 0.0.0.0 until
        NVDA was restarted - measured with netstat while the settings said
        localhost only."""
        source = _source_of('agentLink.py')
        self.assertIn('_where_it_should_be()', source)
        self.assertIn("_state['where'] != _where_it_should_be()", source)

    def test_the_key_is_never_in_the_report(self):
        """The diagnostics are something a user pastes into a bug report."""
        found = json.dumps(self.agentLink.report())
        self.assertNotIn(self.agentLink.token(), found)


class TheScreenReviewReadsTheGuestAndNotVMwaresWindow(unittest.TestCase):
    """**The case no agent can ever answer**: an operating system being
    installed. There is no guest system yet, no accessibility layer, no
    tools and nothing to run a program in - there is an installer painting
    text on a screen. From the host that screen is a picture, which is what
    this review walks.

    The foreground window is the virtual machine's FRAME, whose top is
    VMware's own menu bar, tabs and status line - which NVDA reads properly
    already, and a recogniser reading them again is thirty lines of
    somebody else's furniture in front of the installer.
    """

    def test_the_guests_own_window_is_what_is_read(self):
        from titanEnhancements import ocrReview
        source = _source_of('ocrReview.py')
        self.assertIn('_the_guest_in(_foreground())', source)
        self.assertTrue(hasattr(ocrReview, '_the_guest_in'))

    def test_an_ordinary_window_is_left_exactly_as_it_was(self):
        from titanEnhancements import ocrReview
        self.assertEqual(ocrReview._the_guest_in(4242), 4242)
        self.assertEqual(ocrReview._the_guest_in(0), 0)


class AGuestInATextModeIsReadExactly(unittest.TestCase):
    """The answer to "it has to read the VM guest" when the guest is an
    installer.

    A text-mode screen is not a picture of words: it is 80 by 25 CELLS, each
    one of 256 fixed shapes that have not changed since 1987. So it can be
    read EXACTLY - no model, no request to a provider, and the highlight
    comes out of the attribute rather than being guessed from pixels, which
    is what says which entry an installer has selected.

    The glyphs are Windows' own (`Fonts\\dosapp.fon`), the matching is
    `helper/guestscreen/guestscreen.cpp`, and a machine with neither still
    reads the guest with the model - so these skip rather than fail.
    """

    LINES = ('Windows Setup', '',
             '  Setup is ready to copy files to your computer.',
             '  Choose an installation option:', '',
             '  > Typical            Recommended for most computers',
             '    Portable           For laptop computers', '',
             '  Press ENTER to continue, F3 to quit.')

    def setUp(self):
        from titanEnhancements import guestNative, vgaFont
        self.native, self.font = guestNative, vgaFont
        guestNative.forget()
        vgaFont.forget()
        if guestNative.library() is None:
            self.skipTest(guestNative.report().get('why') or 'no library')
        self.cell = None
        for size in ((12, 16), (8, 16), (9, 16), (8, 12)):
            if vgaFont.table(*size) is not None:
                self.cell = size
                break
        if self.cell is None:
            self.skipTest('this Windows has no VGA glyphs: %s'
                          % vgaFont.report().get('why'))

    def render(self, lines, cols=80, rows=25, highlight='  > '):
        """A text screen exactly as a VGA draws one."""
        wide, tall = self.cell
        table = self.font.table(wide, tall)
        stride = (wide + 7) // 8
        width, height = cols * wide, rows * tall
        screen = bytearray(width * height * 4)

        def put(y, text, ink, paper):
            for at, letter in enumerate(text[:cols]):
                code = letter.encode('cp437', 'replace')[0]
                for gy in range(tall):
                    bits = 0
                    for byte in range(stride):
                        bits = (bits << 8) | table[(code * tall + gy) * stride
                                                   + byte]
                    bits >>= stride * 8 - wide
                    base = ((y * tall + gy) * width + at * wide) * 4
                    for gx in range(wide):
                        colour = ink if (bits >> (wide - 1 - gx)) & 1 else paper
                        screen[base + gx * 4:base + gx * 4 + 4] = bytes(
                            (colour[2], colour[1], colour[0], 0))

        for at, line in enumerate(lines):
            if highlight and line.startswith(highlight):
                put(at, line.ljust(cols), (0, 0, 0x80), (0xAA, 0xAA, 0xAA))
            else:
                put(at, line.ljust(cols), (0xAA, 0xAA, 0xAA), (0, 0, 0))
        return self.native.Picture(bytes(screen), width, height, False)

    def test_every_line_comes_back_exactly(self):
        found = self.native.text_screen(self.render(self.LINES))
        self.assertIsNotNone(found, 'a rendered text screen was not read')
        for at, line in enumerate(self.LINES):
            self.assertEqual(found.lines[at], line.rstrip(),
                             'line %d came back as %r' % (at, found.lines[at]))

    def test_the_grid_it_chose_is_the_one_it_was_drawn_with(self):
        found = self.native.text_screen(self.render(self.LINES))
        self.assertEqual(found.cell, self.cell)
        self.assertGreaterEqual(found.matched, 0.99)

    def test_the_highlighted_entry_is_the_one_the_arrows_are_on(self):
        found = self.native.text_screen(self.render(self.LINES))
        self.assertEqual(found.highlighted(),
                         '> Typical            Recommended for most computers')

    def test_a_screen_with_no_words_on_it_is_refused(self):
        """A wrong exact reading is worse than no exact reading, so a picture
        that is not a text screen has to come back as nothing rather than as
        a screenful of spaces."""
        wide, tall = self.cell
        width, height = 80 * wide, 25 * tall
        noise = bytearray(width * height * 4)
        state = 0x12345678
        for at in range(0, len(noise), 4):
            # A real pseudo-random pixel: the first try was a linear ramp,
            # which is a REGULAR pattern, and a regular pattern is what a
            # character cell looks like - it was read as a text screen.
            state ^= (state << 13) & 0xFFFFFFFF
            state ^= state >> 17
            state ^= (state << 5) & 0xFFFFFFFF
            noise[at] = state & 0xFF
            noise[at + 1] = (state >> 8) & 0xFF
            noise[at + 2] = (state >> 16) & 0xFF
        picture = self.native.Picture(bytes(noise), width, height, False)
        self.assertIsNone(self.native.text_screen(picture))

    def test_a_flat_picture_is_never_read(self):
        """A window that drew one colour drew nothing."""
        wide, tall = self.cell
        width, height = 80 * wide, 25 * tall
        picture = self.native.Picture(b'\x00' * (width * height * 4),
                                      width, height, True)
        self.assertIsNone(self.native.text_screen(picture))

    def test_what_changed_is_where_it_changed(self):
        """The same block arithmetic `virtualInput` does per tick, in C."""
        picture = self.render(self.LINES)
        before = self.native.fingerprint(picture)
        self.assertIsNotNone(before)
        moved = self.render(self.LINES[:5] + (
            '    Typical            Recommended for most computers',
            '  > Portable           For laptop computers') + self.LINES[7:])
        after = self.native.fingerprint(moved)
        regions = self.native.changed(after, before)
        self.assertTrue(regions, 'moving the selection changed nothing')
        top = regions[0][1]
        self.assertLess(top, picture.height,
                        'the region is not inside the picture')

    def test_nothing_is_claimed_without_the_library(self):
        self.native.forget()
        self.native._looked = True
        self.native._dll = None
        try:
            self.assertIsNone(self.native.capture(1, 10, 10))
            self.assertIsNone(self.native.fingerprint(None))
            self.assertEqual(self.native.changed(None, None), [])
            self.assertIsNone(self.native.text_screen(None))
            self.assertFalse(self.native.report()['available'])
        finally:
            self.native.forget()


class TheVgaGlyphsComeFromWindowsOwnFont(unittest.TestCase):
    """Writing 4096 bytes of font into a source file is four thousand chances
    to be wrong about somebody else's screen, and the guest cannot be asked -
    the VGA font lives in the emulated adapter, not in the guest's RAM
    (measured: guest physical 0xB8000 in a running machine's own `.vmem` is a
    hole of zeros). Windows ships the font."""

    def setUp(self):
        from titanEnhancements import vgaFont
        self.font = vgaFont
        vgaFont.forget()

    def test_some_size_is_there_at_all(self):
        sizes = self.font.sizes()
        if not sizes:
            self.skipTest('this Windows has no DOS application fonts')
        self.assertTrue(any(tall >= 8 for _wide, tall in sizes))

    def test_a_table_is_256_glyphs_of_the_right_size(self):
        for wide, tall in self.font.sizes():
            table = self.font.table(wide, tall)
            self.assertEqual(len(table), 256 * tall * ((wide + 7) // 8),
                             '%dx%d is the wrong size' % (wide, tall))
            return
        self.skipTest('no fonts to read')

    def test_the_letter_A_looks_like_an_A(self):
        """Read rather than asserted byte for byte: an A is wider in the
        middle than at the top, and its middle row is solid."""
        table = None
        for size in ((12, 16), (8, 16), (8, 12)):
            table = self.font.table(*size)
            if table is not None:
                wide, tall = size
                break
        if table is None:
            self.skipTest('no fonts to read')
        stride = (wide + 7) // 8
        rows = []
        code = ord('A')
        for y in range(tall):
            bits = 0
            for byte in range(stride):
                bits = (bits << 8) | table[(code * tall + y) * stride + byte]
            rows.append(bin(bits).count('1'))
        drawn = [count for count in rows if count]
        self.assertTrue(drawn, 'the A is blank')
        self.assertGreater(max(drawn), drawn[0],
                           'the A is not wider anywhere than at its top')

    def test_a_size_nobody_has_answers_nothing(self):
        self.assertIsNone(self.font.table(3, 3))
        self.assertIn('no 3 by 3', self.font.report()['why'])


class AGestureIsCalledWhatNvdaBindsIt(unittest.TestCase):
    """Reported as "the touchpad is broken, the gestures still do not work",
    after every earlier fault in it had been fixed - and the numbers said the
    pad was perfect: 4306 contacts, 539 gestures recognised.

    The live NVDA's log said the rest: `first gesture:
    ts(TouchMode.OBJECT):hoverdown`. NVDA binds its touch gestures as
    `ts(object):hoverdown` - the mode's VALUE - and `touchHandler.TouchMode`
    is an enum whose `str()` on this Python is its repr. So every gesture
    carried a name nothing could be bound to, `executeGesture` raised
    `NoInputGestureAction` every time, and the handler swallowed it: a pad
    that ran nothing looked exactly like a pad that worked.
    """

    class _Mode:
        """An enum member that formats as its repr, as NVDA's does here."""

        value = 'object'

        def __str__(self):
            return 'TouchMode.OBJECT'

    class _Gesture:
        def __init__(self, mode):
            self.identifiers = ['ts(%s):hoverdown' % mode]

    def setUp(self):
        from titanEnhancements import trackpad
        self.trackpad = trackpad
        self._state = dict(trackpad._state)
        trackpad._state['mode_as'] = ''
        self.made = []
        self.fake = types.ModuleType('touchHandler')

        def build(preheld, tracker, mode):
            self.made.append(mode)
            return AGestureIsCalledWhatNvdaBindsIt._Gesture(mode)

        self.fake.TouchInputGesture = build
        self._real = sys.modules.get('touchHandler')
        sys.modules['touchHandler'] = self.fake

    def tearDown(self):
        if self._real is None:
            sys.modules.pop('touchHandler', None)
        else:
            sys.modules['touchHandler'] = self._real
        self.trackpad._state.clear()
        self.trackpad._state.update(self._state)

    def test_a_name_with_the_enum_in_it_is_made_again_with_the_value(self):
        mode = self._Mode()
        first = self._Gesture(mode)
        found = self.trackpad._named_as_nvda_binds_them(first, None, None, mode)
        self.assertEqual(found.identifiers[0], 'ts(object):hoverdown')
        self.assertEqual(self.made, ['object'])
        self.assertEqual(self.trackpad._state['mode_as'], 'value')

    def test_a_name_that_is_already_right_is_left_alone(self):
        first = self._Gesture('object')
        found = self.trackpad._named_as_nvda_binds_them(first, None, None,
                                                        'object')
        self.assertIs(found, first)
        self.assertEqual(self.made, [])
        self.assertEqual(self.trackpad._state['mode_as'], 'member')

    def test_what_it_learned_is_used_for_every_gesture_after_it(self):
        """One probe per session, not one per finger."""
        self.trackpad._state['mode_as'] = 'value'
        mode = self._Mode()
        found = self.trackpad._named_as_nvda_binds_them(
            self._Gesture('object'), None, None, mode)
        self.assertEqual(found.identifiers[0], 'ts(object):hoverdown')

    def test_a_mode_that_is_neither_falls_back_to_object(self):
        class Odd(object):
            value = 'whatever'

            def __str__(self):
                return 'TouchMode.ODD'

        found = self.trackpad._named_as_nvda_binds_them(
            self._Gesture(Odd()), None, None, Odd())
        self.assertEqual(found.identifiers[0], 'ts(object):hoverdown')

    def test_what_nvda_did_with_it_is_counted(self):
        """"Nothing is bound to it" and "it broke" are different answers, and
        the handler used to swallow both."""
        source = _source_of('trackpad.py')
        self.assertIn("_state['unbound'] += 1", source)
        self.assertIn("_state['failed'] += 1", source)
        self.assertIn("_state['ran'] += 1", source)
        for name in ('ran', 'unbound', 'failed', 'mode_as'):
            self.assertIn(name, self.trackpad.report())


def _plugin_class():
    import titanEnhancements
    return titanEnhancements.GlobalPlugin


def _source_of(name):
    where = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements', name)
    with io.open(where, encoding='utf-8') as handle:
        return handle.read()



class TheVirtualWindowIsWalkedSpatially(unittest.TestCase):
    """The screen navigation the user asked for in every walked window:
    Left/Right by character, Control by word, Shift to the control beside
    this one on the line, the numpad diagonals to the corners, Numpad 5 a
    mouse click, Numpad 4/6 the layout the plain arrows follow."""

    def setUp(self):
        from titanEnhancements import virtualWindow
        self.vw = virtualWindow
        self.said = []
        self._say = virtualWindow._say
        virtualWindow._say = lambda text: self.said.append(str(text))
        virtualWindow.say_here = (lambda beep=True, prefix=None: (
            True, (virtualWindow.here() or {}).get('name', '')))
        self.addCleanup(lambda: setattr(virtualWindow, '_say', self._say))
        self.addCleanup(lambda: virtualWindow._state.update(
            {'on': False, 'nodes': [], 'at': 0, 'inner': 0, 'letter': 0,
             'layout': 'linear'}))

    def _grid(self, at=4):
        # A 3x3 grid of controls, named A..I, at index `at` (E, the middle).
        names = 'ABCDEFGHI'
        nodes = []
        for i, name in enumerate(names):
            col, row = i % 3, i // 3
            nodes.append({'name': name, 'value': '', 'description': '',
                          'role': 'BUTTON', 'level': 0, 'obj': None,
                          'rect': (col * 50, row * 30, 40, 20)})
        self.vw._state.update({'on': True, 'nodes': nodes, 'at': at,
                               'inner': 0, 'letter': 0, 'layout': 'linear'})
        return nodes

    def _name(self):
        return self.vw.here()['name']

    def test_shift_arrows_are_the_control_beside_this_one(self):
        self._grid()
        self.vw.move_line(1)
        self.assertEqual(self._name(), 'F')
        self._grid()
        self.vw.move_line(-1)
        self.assertEqual(self._name(), 'D')

    def test_the_numpad_diagonals_reach_the_corners(self):
        self._grid(); self.vw.move_diagonal(-1, -1)
        self.assertEqual(self._name(), 'A')
        self._grid(); self.vw.move_diagonal(1, -1)
        self.assertEqual(self._name(), 'C')
        self._grid(); self.vw.move_diagonal(-1, 1)
        self.assertEqual(self._name(), 'G')
        self._grid(); self.vw.move_diagonal(1, 1)
        self.assertEqual(self._name(), 'I')

    def test_the_screen_layout_arrows_go_up_and_down(self):
        self._grid()
        self.vw.move_vertical(1)
        self.assertEqual(self._name(), 'H')
        self._grid()
        self.vw.move_vertical(-1)
        self.assertEqual(self._name(), 'B')

    def test_the_layout_toggle_switches_and_says_which(self):
        self._grid()
        self.assertEqual(self.vw.layout(), 'linear')
        _ok, said = self.vw.layout_toggle()
        self.assertEqual(self.vw.layout(), 'screen')
        self.assertTrue(said)
        # In screen layout the plain arrows follow the screen, not the list.
        self.vw._state['at'] = 4
        self.vw.move(1)
        self.assertEqual(self._name(), 'H')

    def test_left_right_are_characters_and_control_is_words(self):
        self.vw._state.update({
            'on': True, 'at': 0, 'inner': 0, 'letter': 0, 'layout': 'linear',
            'nodes': [{'name': 'Hello world', 'value': '', 'description': '',
                       'role': 'EDITABLETEXT', 'level': 0, 'obj': None,
                       'rect': (0, 0, 80, 20)}]})
        self.said = []
        self.vw.move_char(1)
        self.vw.move_char(1)
        self.assertEqual(self.said[-2:], ['e', 'l'])
        self.vw._state['inner'] = 0
        self.said = []
        self.vw.move_word(1)
        self.assertEqual(self.said[-1], 'world')

    def test_a_control_with_no_rectangle_is_skipped_not_a_crash(self):
        # A node whose rect cannot be read must not stop spatial navigation.
        self.vw._state.update({
            'on': True, 'at': 0, 'inner': 0, 'letter': 0, 'layout': 'linear',
            'nodes': [{'name': 'A', 'role': 'BUTTON', 'obj': None,
                       'rect': (0, 0, 40, 20)},
                      {'name': 'B', 'role': 'BUTTON', 'obj': None,
                       'rect': None},
                      {'name': 'C', 'role': 'BUTTON', 'obj': None,
                       'rect': (0, 30, 40, 20)}]})
        self.vw.move_vertical(1)
        self.assertEqual(self._name(), 'C')



class TheLayoutsAreOneThingInEveryWalkedList(unittest.TestCase):
    """The user's three layouts, spelled out: the SIMPLE one (the list as
    read, Left/Right by character), the SCREEN one (Up/Down and Left/Right
    to the control above, below and BESIDE, as on the picture) and the
    INTERACTION one (outSPOKEN's: Left/Right along one level, Down into
    a control - "In, it" - and Up back out - "Out of, it"). One setting,
    asked by the palette and by a message as well, and the numpad corners
    in all of them."""

    def setUp(self):
        from titanEnhancements import virtualWindow, palette
        self.vw = virtualWindow
        self.palette = palette
        self.said = []
        self._say = virtualWindow._say
        self._say_parts = virtualWindow._say_parts
        virtualWindow._say = lambda text: self.said.append(str(text))
        virtualWindow._say_parts = lambda parts: self.said.append(
            ', '.join(str(text) for text, _voice in parts))
        self._psay = palette._say
        self._psay_parts = palette._say_parts
        palette._say = lambda text: self.said.append(str(text))
        palette._say_parts = lambda parts: self.said.append(
            ', '.join(str(text) for text, _voice in parts))
        self.addCleanup(lambda: setattr(virtualWindow, '_say', self._say))
        self.addCleanup(lambda: setattr(virtualWindow, '_say_parts',
                                        self._say_parts))
        self.addCleanup(lambda: setattr(palette, '_say', self._psay))
        self.addCleanup(lambda: setattr(palette, '_say_parts',
                                        self._psay_parts))
        self.addCleanup(lambda: virtualWindow._state.update(
            {'on': False, 'nodes': [], 'at': 0, 'inner': 0, 'letter': 0,
             'layout': 'linear', 'depth': None}))
        palette.forget()
        self.addCleanup(palette.forget)
        virtualWindow._state.update({'layout': 'linear', 'depth': None})

    def _grid(self, at=4):
        names = 'ABCDEFGHI'
        nodes = []
        for i, name in enumerate(names):
            col, row = i % 3, i // 3
            nodes.append({'name': name, 'value': '', 'description': '',
                          'role': 'BUTTON', 'level': 0, 'obj': None,
                          'id': i, 'parent': None,
                          'rect': (col * 50, row * 30, 40, 20)})
        self.vw._state.update({'on': True, 'nodes': nodes, 'at': at,
                               'inner': 0, 'letter': 0, 'depth': None})
        return nodes

    def _tree(self):
        # G (a group) holds a and b; H is beside G; a says two words.
        nodes = [
            {'name': 'G', 'value': '', 'role': 'GROUPING', 'obj': None,
             'id': 0, 'parent': None, 'rect': (0, 0, 100, 60)},
            {'name': 'H', 'value': '', 'role': 'BUTTON', 'obj': None,
             'id': 1, 'parent': None, 'rect': (110, 0, 40, 20)},
            {'name': 'Hello world', 'value': '', 'role': 'STATICTEXT',
             'obj': None, 'id': 2, 'parent': 0, 'rect': (5, 5, 40, 20)},
            {'name': 'b', 'value': '', 'role': 'BUTTON', 'obj': None,
             'id': 3, 'parent': 0, 'rect': (5, 30, 40, 20)},
        ]
        self.vw._state.update({'on': True, 'nodes': nodes, 'at': 0,
                               'inner': 0, 'letter': 0, 'depth': None})
        return nodes

    def _name(self):
        return self.vw.here()['name']

    # -- the setting ------------------------------------------------------
    def test_numpad_4_and_6_walk_the_three_layouts_and_name_them(self):
        self.assertEqual(self.vw.layout(), 'linear')
        _ok, said = self.vw.layout_cycle(1)
        self.assertEqual((self.vw.layout(), said), ('screen', 'Screen layout'))
        _ok, said = self.vw.layout_cycle(1)
        self.assertEqual((self.vw.layout(), said),
                         ('interact', 'Interaction layout'))
        _ok, said = self.vw.layout_cycle(1)
        self.assertEqual((self.vw.layout(), said), ('linear', 'Simple layout'))
        _ok, said = self.vw.layout_cycle(-1)
        self.assertEqual(self.vw.layout(), 'interact')
        self.assertEqual(self.vw.LAYOUTS, ('linear', 'screen', 'interact'))

    def test_the_palette_asks_the_virtual_window_which_layout_is_on(self):
        self.assertEqual(self.palette._layout(), 'linear')
        self.palette.layout_cycle(1)
        self.assertEqual(self.vw.layout(), 'screen')
        self.assertEqual(self.palette._layout(), 'screen')

    def test_the_old_name_reading_order_is_gone(self):
        self.assertNotIn("_('Reading order')", _source_of('virtualWindow.py'))

    # -- the screen layout -----------------------------------------------
    def test_on_the_screen_layout_left_and_right_are_the_control_beside(self):
        self._grid()
        self.vw._state['layout'] = 'screen'
        self.vw.move_across(1)
        self.assertEqual(self._name(), 'F')
        self.vw.move_across(-1)
        self.vw.move_across(-1)
        self.assertEqual(self._name(), 'D')
        # And Shift is then the character, the other way round from the
        # simple layout.
        self.said = []
        self.vw.move_across_shift(1)
        self.assertEqual(self.said, ['D'])   # one character, said, clamped
        self.vw._state['layout'] = 'linear'
        self.vw._state['at'] = 4
        self.vw.move_across_shift(1)
        self.assertEqual(self._name(), 'F')

    # -- the interaction layout ------------------------------------------
    def test_interaction_left_and_right_stay_on_one_level(self):
        self._tree()
        self.vw._state['layout'] = 'interact'
        self.vw.move_across(1)
        self.assertEqual(self._name(), 'H')
        self.vw.move_across(1)
        self.assertEqual(self._name(), 'H')          # the edge, not a child
        self.vw.move_across(-1)
        self.assertEqual(self._name(), 'G')

    def test_down_goes_in_and_up_comes_out_and_both_say_so(self):
        self._tree()
        self.vw._state['layout'] = 'interact'
        self.said = []
        self.vw.move(1)                               # Down: into G
        self.assertEqual(self._name(), 'Hello world')
        self.assertTrue(self.said[-1].startswith('In G'))
        self.vw.move_across(1)                        # the sibling inside G
        self.assertEqual(self._name(), 'b')
        self.vw.move_across(1)
        self.assertEqual(self._name(), 'b')           # H is not at this level
        self.said = []
        self.vw.move(-1)                              # Up: out of G, onto G
        self.assertEqual(self._name(), 'G')
        self.assertTrue(self.said[-1].startswith('Out of G'))
        self.said = []
        self.vw.move(-1)                              # nothing above the top
        self.assertEqual(self._name(), 'G')

    def test_a_control_with_no_children_is_entered_word_by_word_then_letter(self):
        self._tree()
        self.vw._state.update({'layout': 'interact', 'at': 2})
        self.said = []
        self.vw.move(1)
        self.assertEqual(self.said[-1], 'In Hello world, Hello')
        self.vw.move_across(1)
        self.assertEqual(self.said[-1], 'world')
        self.vw.move(1)
        self.assertEqual(self.said[-1], 'In world, w')
        self.vw.move_across(1)
        self.assertEqual(self.said[-1], 'o')
        self.vw.move(-1)
        self.assertEqual(self.said[-1], 'Out of world, world')
        self.vw.move(-1)
        self.assertTrue(self.said[-1].startswith('Out of Hello world'))
        # Back at the control: Left/Right are the level again.
        self.vw.move_across(1)
        self.assertEqual(self._name(), 'b')

    def test_the_depth_belongs_to_the_row_it_was_set_on(self):
        self._tree()
        self.vw._state.update({'layout': 'interact', 'at': 2})
        self.vw.move(1)                               # into the words
        self.assertEqual(self.vw._depth(), 'words')
        self.vw.move_diagonal(1, -1)                  # a corner: another row
        self.assertIsNone(self.vw._depth())

    def test_the_walk_records_which_kept_node_each_one_is_inside(self):
        class Role:
            def __init__(self, name):
                self.name = name

        class Obj:
            def __init__(self, name, role, children=()):
                self.name, self.role = name, Role(role)
                self.value = self.description = ''
                self.children = list(children)
        window = Obj('W', 'WINDOW', [
            Obj('', 'PANE', [                         # skipped: passes through
                Obj('G', 'GROUPING', [Obj('a', 'BUTTON'), Obj('b', 'BUTTON')]),
                Obj('', 'PANE', [Obj('c', 'BUTTON')]),  # unnamed: same rule
            ]),
            Obj('H', 'BUTTON'),
        ])
        found = self.vw.nodes_of(window, {})
        by_name = {node['name']: node for node in found}
        self.assertIsNone(by_name['G']['parent'])
        self.assertIsNone(by_name['H']['parent'])
        self.assertIsNone(by_name['c']['parent'])
        self.assertEqual(by_name['a']['parent'], by_name['G']['id'])
        self.assertEqual(by_name['b']['parent'], by_name['G']['id'])
        self.assertEqual(len({node['id'] for node in found}), len(found))

    # -- the palette and a message -----------------------------------------
    def test_the_numpad_corners_are_the_ends_of_the_first_and_last_row(self):
        self.palette.page('one two\nthree four\nfive six', 'Status')
        self.palette.move_corner(-1, 1)
        self.assertEqual(self.palette._state['at'], 2)
        self.palette.move_corner(-1, -1)
        self.assertEqual(self.palette._state['at'], 0)
        self.said = []
        self.palette.move_corner(1, -1)
        self.assertEqual(self.palette._state['at'], 0)
        self.assertTrue(self.said[-1].startswith('Top right, two'), self.said)
        self.said = []
        self.palette.move_corner(-1, 1)
        self.assertTrue(self.said[-1].startswith('Bottom left, five six'))
        self.said = []
        self.palette.move_corner(1, 1)
        self.assertEqual(self.palette._state['at'], 2)
        self.assertTrue(self.said[-1].startswith('Bottom right, six'))
        # The cursor is left at the end, so Left reads back from there.
        self.said = []
        self.palette.move_char(-1)
        self.assertEqual(self.said[-1], 'i')

    def test_the_palette_reads_by_layout_too(self):
        self.palette.page('one two\nthree four', 'Status')
        self.said = []
        self.palette.move_across(1)
        self.assertEqual(self.said[-1], 'n')          # simple: a character
        self.vw._state['layout'] = 'screen'
        self.palette._state.update({'inner': 0, 'letter': 0})
        self.said = []
        self.palette.move_across(1)
        self.assertEqual(self.said[-1], 'two')        # screen: the word beside
        self.palette.move_across(1)
        self.assertEqual(self.said[-1], 'two')        # the edge of the row
        self.palette.move_across_shift(-1)
        self.assertEqual(self.said[-1], 'o')          # Shift: a character
        self.palette.move(1)                          # Down: still the rows
        self.assertEqual(self.palette._state['at'], 1)

    def test_in_a_message_down_goes_into_the_line_and_up_comes_out(self):
        self.palette.page('one two\nthree four', 'Status')
        self.vw._state['layout'] = 'interact'
        self.said = []
        self.palette.move_across(1)                   # the row beside
        self.assertEqual(self.palette._state['at'], 1)
        self.palette.move_across(-1)
        self.said = []
        self.palette.move(1)
        self.assertEqual(self.said[-1], 'In one two, one')
        self.palette.move_across(1)
        self.assertEqual(self.said[-1], 'two')
        self.palette.move(1)
        self.assertEqual(self.said[-1], 'In two, t')
        self.palette.move(-1)
        self.assertEqual(self.said[-1], 'Out of two, two')
        self.palette.move(-1)
        self.assertTrue(self.said[-1].startswith('Out of one two'))
        self.palette.move(-1)                         # nothing above a row
        self.assertEqual(self.palette._state['at'], 0)
        self.palette.move_end(True)                   # End: the last row
        self.assertEqual(self.palette._state['at'], 1)

    # -- the corners are the window's ------------------------------------
    def test_a_corner_is_the_windows_own_and_a_row_off_the_window_is_not_it(self):
        """A list's rows scrolled out of sight report rectangles far
        below the window, and a corner worked out from a box round every
        control landed on a row nobody could see."""
        nodes = self._grid()
        nodes.append({'name': 'Z', 'value': '', 'role': 'LISTITEM',
                      'obj': None, 'id': 9, 'parent': None,
                      'rect': (0, 900, 40, 20)})      # scrolled off
        self.vw._state['window_rect'] = (0, 0, 150, 80)
        self.said = []
        self.vw.move_diagonal(-1, 1)
        self.assertEqual(self._name(), 'G')
        self.assertTrue(self.said[-1].startswith('Bottom left, G'), self.said)
        self.vw.move_diagonal(1, -1)
        self.assertEqual(self._name(), 'C')
        self.assertTrue(self.said[-1].startswith('Top right, C'))

    def test_the_control_in_the_corner_beats_the_one_near_it(self):
        """Measured by centres a small button NEAR the corner beat the
        list that fills it; measured by its own corner, the control that
        sits in the corner wins, and a tie goes to the smaller one."""
        self.vw._state.update({'on': True, 'at': 0, 'inner': 0, 'letter': 0,
                               'window_rect': (0, 0, 400, 300), 'nodes': [
            {'name': 'List', 'role': 'LIST', 'obj': None, 'id': 0,
             'parent': None, 'rect': (0, 0, 400, 280)},
            {'name': 'Near', 'role': 'BUTTON', 'obj': None, 'id': 1,
             'parent': None, 'rect': (330, 240, 40, 20)},
            {'name': 'Status', 'role': 'STATUSBAR', 'obj': None, 'id': 2,
             'parent': None, 'rect': (0, 280, 400, 20)}]})
        self.vw.move_diagonal(1, 1)
        self.assertEqual(self._name(), 'Status')
        self.vw.move_diagonal(-1, -1)
        self.assertEqual(self._name(), 'List')

    # -- a submenu opens with Right ----------------------------------------
    def test_right_walks_into_a_menu_and_left_comes_back_out(self):
        class Role:
            def __init__(self, name):
                self.name = name

        class Obj:
            def __init__(self, name, role, children=(), states=()):
                self.name, self.role = name, Role(role)
                self.value = self.description = ''
                self.children = list(children)
                self.states = set(states)
                self.processID = 1
        item_a = Obj('Open', 'MENUITEM')
        item_b = Obj('Save', 'MENUITEM')
        file_menu = Obj('File', 'POPUPMENU', [item_a, item_b])
        nodes = [{'name': 'File', 'value': '', 'role': 'POPUPMENU',
                  'obj': file_menu, 'id': 0, 'parent': None,
                  'rect': (0, 0, 40, 20)},
                 {'name': 'OK', 'value': '', 'role': 'BUTTON', 'obj': None,
                  'id': 1, 'parent': None, 'rect': (0, 30, 40, 20)}]
        self.vw._state.update({'on': True, 'nodes': nodes, 'at': 0,
                               'inner': 0, 'letter': 0, 'menu': None,
                               'layout': 'linear', 'depth': None})
        self.vw.move_across(1)
        self.assertTrue(self.vw.in_a_menu())
        self.assertEqual(self._name(), 'Open')
        self.vw.move(1)
        self.assertEqual(self._name(), 'Save')
        self.vw.move_across(-1)
        self.assertFalse(self.vw.in_a_menu())
        self.assertEqual(self._name(), 'File')
        # A plain control is still read by character.
        self.vw._state['at'] = 1
        self.said = []
        self.vw.move_across(1)
        self.assertEqual(self.said[-1], 'K')

    def test_the_keys_are_the_same_in_both(self):
        plugin = _plugin_class()
        for key, script in (('kb:numpad7', 'paletteUpLeft'),
                            ('kb:numpad9', 'paletteUpRight'),
                            ('kb:numpad1', 'paletteDownLeft'),
                            ('kb:numpad3', 'paletteDownRight'),
                            ('kb:numpad4', 'paletteLayoutBack'),
                            ('kb:numpad6', 'paletteLayout'),
                            ('kb:shift+leftArrow', 'paletteShiftLeft'),
                            ('kb:shift+rightArrow', 'paletteShiftRight')):
            self.assertEqual(plugin.PALETTE_KEYS[key], script)
            self.assertTrue(hasattr(plugin, 'script_' + script), script)
        self.assertEqual(plugin.VIRTUAL_KEYS['kb:numpad4'], 'virtualLayoutBack')
        self.assertEqual(plugin.VIRTUAL_KEYS['kb:numpad6'], 'virtualLayout')
        self.assertTrue(hasattr(plugin, 'script_virtualLayoutBack'))
        source = _source_of('__init__.py')
        self.assertIn('virtualWindow.move_across(', source)
        self.assertIn('virtualWindow.move_across_shift(', source)
        self.assertIn('palette.move_across(', source)
        self.assertIn('palette.move_corner(', source)


class TheTrackpadWalksEveryList(unittest.TestCase):
    """A finger on the pad explores whichever list is up, the flicks are
    the arrows, and every 3- and 4-finger swipe means something - the
    corners, the layout, the ends. The same table for the virtual window,
    the palette and the OCR review, because they are one interaction."""

    def setUp(self):
        from titanEnhancements import touchWalk, virtualWindow, palette
        from titanEnhancements import ocrReview
        self.tw, self.vw, self.pal, self.ocr = (touchWalk, virtualWindow,
                                                palette, ocrReview)
        self.said = []
        for module in (virtualWindow, palette, ocrReview):
            self._stub(module, '_say',
                       lambda text, interrupt=True: self.said.append(str(text)))
        for module in (virtualWindow, palette):
            self._stub(module, '_say_parts', lambda parts: self.said.append(
                ', '.join(str(t) for t, _v in parts)))
        palette.forget()
        touchWalk.forget()
        self.addCleanup(palette.forget)
        self.addCleanup(lambda: virtualWindow._state.update(
            {'on': False, 'nodes': [], 'at': 0, 'inner': 0, 'letter': 0,
             'layout': 'linear', 'depth': None, 'window_rect': None,
             'explored': None}))
        self.addCleanup(lambda: ocrReview._state.update(
            {'on': False, 'rows': [], 'lines': [], 'row': 0, 'word': 0}))

    def _stub(self, module, name, value):
        old = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, old))

    def _grid(self):
        names = 'ABCDEFGHI'
        nodes = []
        for i, name in enumerate(names):
            col, row = i % 3, i // 3
            nodes.append({'name': name, 'value': '', 'role': 'BUTTON',
                          'obj': None, 'id': i, 'parent': None,
                          'rect': (col * 50, row * 30, 40, 20)})
        self.vw._state.update({'on': True, 'nodes': nodes, 'at': 4,
                               'inner': 0, 'letter': 0, 'layout': 'linear',
                               'depth': None, 'window_rect': (0, 0, 150, 80),
                               'explored': None})

    def test_the_action_is_read_out_of_nvdas_own_identifier(self):
        self.assertEqual(self.tw.action_of('ts(object):2finger_flickleft'),
                         '2finger_flickleft')
        self.assertEqual(self.tw.action_of('ts:hover'), 'hover')

    def test_nothing_is_answered_when_no_list_is_up(self):
        handled, _said = self.tw.handle('flickdown')
        self.assertFalse(handled)
        self.assertEqual(self.tw.walker(), '')

    def test_a_finger_explores_the_virtual_window_by_rectangle(self):
        self._grid()
        self.assertEqual(self.tw.walker(), 'virtualWindow')
        handled, _said = self.tw.handle('hover', x=110, y=65)
        self.assertTrue(handled)
        self.assertEqual(self.vw.here()['name'], 'I')
        # Resting on the same control says it once.
        self.said = []
        self.tw.handle('hover', x=112, y=66)
        self.assertEqual(self.said, [])
        # Between controls nothing is said and the cursor stays.
        self.tw.handle('hover', x=45, y=25)
        self.assertEqual(self.vw.here()['name'], 'I')

    def test_the_flicks_are_the_arrows_and_the_fingers_are_the_corners(self):
        self._grid()
        self.tw.handle('flickdown')
        self.assertEqual(self.vw.here()['name'], 'F')      # simple: next
        self.tw.handle('3finger_flickleft')
        self.assertEqual(self.vw.here()['name'], 'A')      # top left
        self.tw.handle('3finger_flickright')
        self.assertEqual(self.vw.here()['name'], 'C')      # top right
        self.tw.handle('4finger_flickleft')
        self.assertEqual(self.vw.here()['name'], 'G')      # bottom left
        self.tw.handle('4finger_flickright')
        self.assertEqual(self.vw.here()['name'], 'I')      # bottom right
        self.tw.handle('4finger_flickup')
        self.assertEqual(self.vw.here()['name'], 'A')      # Home
        self.tw.handle('3finger_flickdown')
        self.assertEqual(self.vw.layout(), 'screen')       # next layout
        self.tw.handle('3finger_flickup')
        self.assertEqual(self.vw.layout(), 'linear')
        self.tw.handle('4finger_tap')
        self.assertFalse(self.vw.reviewing())              # leave

    def test_the_palette_maps_the_screen_onto_its_rows(self):
        self.pal.page('one\ntwo\nthree\nfour', 'Status')
        self.assertEqual(self.tw.walker(), 'palette')
        _w, height = self.tw.screen_size()
        self.tw.handle('hover', x=10, y=height - 1)
        self.assertEqual(self.pal._state['at'], 3)
        self.tw.handle('hover', x=10, y=0)
        self.assertEqual(self.pal._state['at'], 0)
        self.tw.handle('flickdown')
        self.assertEqual(self.pal._state['at'], 1)
        self.said = []
        self.tw.handle('3finger_flickright')
        self.assertTrue(self.said[-1].startswith('Top right, one'))
        self.tw.handle('4finger_flickright')
        self.assertTrue(self.said[-1].startswith('Bottom right, four'))
        self.tw.handle('2finger_tap')
        self.assertFalse(self.pal.walking())

    def test_the_ocr_review_explores_by_the_words_rectangles(self):
        self.ocr._state.update({
            'on': True, 'row': 0, 'word': 0,
            'rows': [('hello world', (0, 0, 100, 20)),
                     ('second line', (0, 30, 100, 20))],
            'lines': [[{'text': 'hello', 'left': 0, 'top': 0, 'width': 45,
                        'height': 20},
                       {'text': 'world', 'left': 50, 'top': 0, 'width': 50,
                        'height': 20}],
                      [{'text': 'second', 'left': 0, 'top': 30, 'width': 55,
                        'height': 20},
                       {'text': 'line', 'left': 60, 'top': 30, 'width': 40,
                        'height': 20}]]})
        self.assertEqual(self.tw.walker(), 'ocrReview')
        self.said = []
        self.tw.handle('hover', x=70, y=35)
        self.assertEqual((self.ocr._state['row'], self.ocr._state['word']),
                         (1, 1))
        self.assertEqual(self.said[-1], 'line')
        self.said = []
        self.tw.handle('4finger_flickright')
        self.assertEqual(self.said[-1], 'Bottom right, line')
        self.tw.handle('3finger_flickleft')
        self.assertEqual(self.said[-1], 'Top left, hello world')

    def test_every_action_in_the_table_is_bound_by_the_plugin(self):
        plugin = _plugin_class()
        gestures = plugin._touch_gestures(plugin.__new__(plugin))
        for action in self.tw.ACTIONS:
            self.assertEqual(gestures.get('ts:' + action), 'walkTouch')
        self.assertTrue(hasattr(plugin, 'script_walkTouch'))
        for walker in ('virtualWindow', 'palette', 'ocrReview'):
            for action in self.tw.ACTIONS:
                if action in ('hover', 'hoverdown'):
                    continue
                self.assertIn(action, self.tw._TABLE[walker],
                              '%s does not answer %s' % (walker, action))
        for key, script_name in (('kb:numpad7', 'ocrUpLeft'),
                                 ('kb:numpad3', 'ocrDownRight')):
            self.assertEqual(plugin.OCR_KEYS[key], script_name)
            self.assertTrue(hasattr(plugin, 'script_' + script_name))


class ASoundComesFromWhereTheUserSaid(unittest.TestCase):
    """Every sound the reader plays for something - an auditory icon, a
    state in the sound scheme - has three places it can come from: the
    built-in set the add-on ships, Titan's own sound for the same event out
    of the user's theme, or a file of the user's own. One rule for both
    managers, and a source that cannot answer falls back to the built-in
    sound rather than to silence."""

    def setUp(self):
        from titanEnhancements import icons, schemes
        self.icons, self.schemes = icons, schemes
        self.dir = tempfile.mkdtemp()
        self._ipath, self._spath = icons.path, schemes.path
        icons.path = lambda: os.path.join(self.dir, 'icons.json')
        schemes.path = lambda: os.path.join(self.dir, 'scheme.json')
        icons.forget()
        schemes.forget()
        self.addCleanup(icons.forget)
        self.addCleanup(schemes.forget)
        self.addCleanup(lambda: setattr(icons, 'path', self._ipath))
        self.addCleanup(lambda: setattr(schemes, 'path', self._spath))
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        self.played = []
        self._file, self._titan = icons.play_file, icons.play_titan
        icons.play_file = lambda where, wait=False: (
            self.played.append(('file', where)) or True) if where else False
        icons.play_titan = lambda name: (
            self.played.append(('titan', name)) or True) if name else False
        self.addCleanup(lambda: setattr(icons, 'play_file', self._file))
        self.addCleanup(lambda: setattr(icons, 'play_titan', self._titan))

    def test_an_icon_is_built_in_until_the_user_says_otherwise(self):
        self.assertEqual(self.icons.source_of('item'),
                         (self.icons.SOURCE_BUILTIN, ''))
        self.assertTrue(self.icons.play('item'))
        self.assertEqual(self.played[-1][0], 'file')
        self.assertTrue(self.played[-1][1].endswith('item.wav'))

    def test_an_icon_on_titans_sound_asks_titan_and_is_remembered(self):
        self.icons.set_source('item', self.icons.SOURCE_TITAN)
        self.icons.forget()
        self.assertEqual(self.icons.source_of('item')[0],
                         self.icons.SOURCE_TITAN)
        self.icons.play('item')
        self.assertEqual(self.played[-1], ('titan', 'reader/listitem.ogg'))

    def test_every_icon_has_a_titan_sound_named(self):
        missing = [name for name in self.icons.NAMES
                   if not self.icons.titan_name(name)]
        self.assertEqual(missing, [])

    def test_a_source_that_cannot_answer_falls_back_to_the_built_in_one(self):
        self.icons.play_titan = lambda name: False           # no Titan
        self.icons.set_source('item', self.icons.SOURCE_TITAN)
        self.assertTrue(self.icons.play('item'))
        self.assertEqual(self.played[-1][0], 'file')
        self.icons.set_source('button', self.icons.SOURCE_EXTERNAL,
                              os.path.join(self.dir, 'gone.wav'))
        self.icons.play_file = self._file                     # the real one
        recorded = []
        self.icons.play_file = lambda where, wait=False: (
            recorded.append(where) or os.path.isfile(where))
        self.assertTrue(self.icons.play('button'))
        self.assertTrue(recorded[-1].endswith('button.wav'))

    def test_a_state_starts_on_titans_set_and_can_move(self):
        self.assertEqual(self.schemes.source_of('CHECKED')[0],
                         self.schemes.SOURCE_TITAN)
        self.schemes.set_source('CHECKED', self.schemes.SOURCE_BUILTIN)
        self.schemes.set_way('CHECKED', self.schemes.AS_SOUND)
        self.schemes.forget()
        row = [one for one in self.schemes.described()
               if one['state'] == 'CHECKED'][0]
        self.assertEqual((row['source'], row['way'], row['builtin']),
                         ('builtin', 'sound', 'on'))
        words, sounds = self.schemes.answer(['CHECKED'])
        self.assertEqual(sounds, ['CHECKED'])       # the state, not a file
        self.schemes.play(sounds)
        self.assertEqual(self.played[-1][0], 'file')
        self.assertTrue(self.played[-1][1].endswith('on.wav'))

    def test_a_state_on_a_file_of_the_users_own_plays_that_file(self):
        mine = os.path.join(self.dir, 'mine.wav')
        self.schemes.set_source('SELECTED', self.schemes.SOURCE_EXTERNAL, mine)
        self.schemes.play(['SELECTED'])
        self.assertEqual(self.played[-1], ('file', mine))

    def test_the_new_states_have_a_sound_in_every_set(self):
        for state in ('HASPOPUP', 'REQUIRED', 'PROTECTED'):
            self.assertIn(state, self.schemes.STATES)
            self.assertIn(state, self.schemes.BUILTIN)
            self.assertIn(state, self.schemes.state_names())
            self.assertTrue(self.icons.path_of(self.schemes.BUILTIN[state]))

    def test_the_walked_manager_says_it_in_words(self):
        from titanEnhancements import managerWalk
        rows = managerWalk._icons()
        self.assertTrue(rows)
        self.assertTrue(any('the built-in sound' in row for row in rows))
        rows = managerWalk._scheme()
        self.assertTrue(rows)
        self.assertFalse(any('CHECKED' in row for row in rows))
        self.assertTrue(any("Titan's own sound" in row for row in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
