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
        for name in configSpec.SPEC:
            if name == 'enabled':
                continue          # the add-on as a whole, not a page switch
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
                     'tce.crossing('):
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
                                        'states', 'trackpad', 'focus'),
                                 used + ' is used but not imported')



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
        from titanEnhancements import configSpec
        before = configSpec.read
        try:
            for answer, wanted in (('ai', self.surface.MODE_NATIVE),
                                   ('both', self.surface.MODE_NATIVE),
                                   ('local', self.surface.MODE_LOCAL)):
                configSpec.read = lambda a=answer: dict(configSpec.defaults(),
                                                        ocrTier=a)
                self.assertEqual(
                    self.surface.mode_for(Fake(klass='WeirdInstaller')),
                    wanted, answer)
        finally:
            configSpec.read = before

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
        subprocess.run([sys.executable, installer, '--to', self.dir],
                       capture_output=True, text=True,
                       cwd=os.path.dirname(installer))
        self.assertFalse(os.path.exists(stray),
                         'a module that is no longer shipped is still there')

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
                                    "_('How this program is read')")

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


def _plugin_class():
    import titanEnhancements
    return titanEnhancements.GlobalPlugin


def _source_of(name):
    where = os.path.join(ADDON, 'globalPlugins', 'titanEnhancements', name)
    return io.open(where, encoding='utf-8').read()


if __name__ == "__main__":
    unittest.main(verbosity=2)
