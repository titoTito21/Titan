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

import io
import json
import os
import sys
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
    plugin: instance attributes, which is what ``dir()`` shows the Input
    Gestures dialog."""


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
        # The Input Gestures dialog walks dir() looking for script_*.
        gestures.install(self.plugin, gestures.catalogue_from_addons(sample()))
        found = [name for name in dir(self.plugin)
                 if name.startswith('script_')]
        self.assertEqual(sorted(found), ['script_titan_tnotes_create_note',
                                         'script_titan_tnotes_read'])

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

    def test_the_session_is_asked_once(self):
        self.panner.PANNER._session_capable = None
        asked = []
        original = self.panner._own_session
        self.panner._own_session = lambda: asked.append(1)
        try:
            self.panner.PANNER._session_can()
            self.panner.PANNER._session_can()
        finally:
            self.panner._own_session = original
        self.assertEqual(len(asked), 1,
                         'reading every audio session on the machine is a '
                         'COM walk, not something to do per announcement')

    def test_a_tone_does_not_stand_in_for_a_position_that_is_applied(self):
        from titanEnhancements import prosody
        self.panner.PANNER._session_capable = True
        sequence, notes = prosody.build({'text': 'left', 'position': -1.0})
        self.assertNotIn('tone', ' '.join(notes).lower())


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

    def test_the_panel_saves_everything_the_spec_declares(self):
        from titanEnhancements import configSpec
        from titanEnhancements import settingsPanel
        source = io.open(settingsPanel.__file__, encoding='utf-8').read()
        for name in configSpec.SPEC:
            if name == 'enabled':
                continue          # the add-on as a whole, not a page switch
            self.assertIn("'{}':".format(name), source,
                          "the settings page never writes " + name)

    def test_a_switch_the_page_writes_is_one_the_spec_knows(self):
        from titanEnhancements import configSpec
        from titanEnhancements import settingsPanel
        import re
        source = io.open(settingsPanel.__file__, encoding='utf-8').read()
        saved = re.search(r'configSpec\.write\(\{(.+?)\}\)', source,
                          re.S)
        self.assertIsNotNone(saved)
        for name in re.findall(r"'([A-Za-z]+)':", saved.group(1)):
            self.assertIn(name, configSpec.SPEC, name)

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
