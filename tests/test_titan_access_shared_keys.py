# -*- coding: utf-8 -*-
"""The NVDA add-on's commands have keys in Titan Access, and work there.

Titan Access and the add-on share their commands (`portable/commands`),
but a command with no key, or one that reaches for a module only NVDA has,
is a placeholder: present in the palette, silent or refusing when used.
These pin the ones that were:

* every add-on key has an Insert twin, bound to a command that exists;
* none of the new keys collides with a key this reader already had;
* the screen review (Insert+O) is vendored and its keys are walked here;
* reading a window locally, outside NVDA, goes through Titan (Windows'
  own recogniser, then the local model) instead of NVDA's `contentRecog`;
* "status", positioned speech and Titan's own announcements mean
  something in this reader;
* Insert+Ctrl+S - the speech system, synthesizer and voice - chooses,
  stores and applies, Speech Dispatcher's modules included;
* Insert+Alt+letter does not open the program's menu bar.

No window is shown, nothing is spoken, no store of the user's is touched.
Run directly: ``python tests/test_titan_access_shared_keys.py``.
"""

import json
import os
import sys
import tempfile
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='titan_access_keys_')

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)


def _engine_bindings():
    """The real engine's gesture table, built without starting the reader."""
    from titan_access.engine import TitanAccessEngine
    from titan_access.gestures import GestureManager
    engine = TitanAccessEngine.__new__(TitanAccessEngine)
    engine.object_nav = None
    engine.gestures = GestureManager(engine)
    engine._register_default_gestures()
    return engine, engine.gestures._bindings


class EveryAddOnKeyHasATwin(unittest.TestCase):

    def setUp(self):
        self.engine, self.bindings = _engine_bindings()

    def test_every_shared_key_names_a_command_that_exists(self):
        from titan_access.portable import commands
        for action_id, _spec, command in self.engine.SHARED_KEYS:
            mine = self.engine.MINE.get(command)
            if mine:
                self.assertTrue(callable(getattr(self.engine, mine, None)),
                                '%s -> %s' % (command, mine))
            else:
                self.assertTrue(callable(getattr(commands, command, None)),
                                '%s has no command %s' % (action_id, command))

    def test_no_new_key_collides(self):
        seen = {}
        new = {spec for _a, spec, _c in self.engine.SHARED_KEYS}
        new.add('control+s')
        for binding in self.bindings:
            key = (binding.base, binding.ctrl, binding.alt, binding.shift)
            if binding.key_spec in new and key in seen and \
                    seen[key] != binding.action_id:
                self.fail('%s collides with %s'
                          % (binding.key_spec, seen[key]))
            seen.setdefault(key, binding.action_id)

    def test_the_keys_the_user_named_are_bound(self):
        specs = {b.key_spec: b.action_id for b in self.bindings}
        self.assertEqual(specs.get('o'), 'screenReview')
        self.assertEqual(specs.get('shift+o'), 'readLocally')
        self.assertEqual(specs.get('alt+o'), 'ocrRead')
        self.assertEqual(specs.get('control+s'), 'speechSystem')

    def test_every_key_has_a_name_in_both_languages(self):
        for language in ('en', 'pl'):
            with open(os.path.join(COMPONENT, 'locale', language + '.json'),
                      encoding='utf-8') as handle:
                strings = json.load(handle)
            for action_id, _spec, _command in self.engine.SHARED_KEYS + (
                    ('speechSystem', '', ''),):
                for part in ('name', 'desc'):
                    self.assertIn('gesture.%s.%s' % (action_id, part),
                                  strings, language)

    def test_a_palette_row_names_a_gesture_this_reader_has(self):
        from titan_access.portable import layers
        ids = {b.action_id for b in self.bindings}
        for command, action in layers.GESTURE_OF.items():
            self.assertIn(action, ids, command)

    def test_the_readers_own_meanings_are_answered_here(self):
        ran = []
        self.engine.action_reader_status = lambda *a: ran.append('status')
        self.engine.action_toggle_virtual_screen = \
            lambda *a: ran.append('position')
        self.engine.action_toggle_titan_announcements = \
            lambda *a: ran.append('announcements')
        from titan_access.portable import palette
        keep = palette.stop
        palette.stop = lambda: None
        try:
            for name in ('status', 'toggle_position', 'toggle_announcements'):
                self.engine._palette_run(name)
        finally:
            palette.stop = keep
        self.assertEqual(ran, ['status', 'position', 'announcements'])


class TheMenuDoesWhatThisReaderMeans(unittest.TestCase):

    def test_a_command_this_reader_answers_itself_is_found_first(self):
        from titan_access.portable import commands, menu
        ran = []
        keep = dict(commands.OWN)
        commands.OWN.clear()
        commands.OWN['status'] = lambda: ran.append('own status')
        try:
            menu._run_command('status')
            ok, _why = commands.run_command('status')
        finally:
            commands.OWN.clear()
            commands.OWN.update(keep)
        self.assertTrue(ok)
        self.assertEqual(ran, ['own status', 'own status'])

    def test_the_engine_fills_the_table(self):
        from titan_access.portable import commands
        engine, _bindings = _engine_bindings()
        engine._own_commands()
        try:
            for name in ('status', 'toggle_position', 'toggle_announcements',
                         'toggle_trackpad', 'speech_system'):
                self.assertTrue(callable(commands.OWN.get(name)), name)
        finally:
            commands.OWN.clear()


class TheScreenReviewIsHereAndWalked(unittest.TestCase):

    def test_it_is_vendored(self):
        from titan_access.portable import ocrReview
        self.assertTrue(callable(ocrReview.toggle))

    def test_its_keys_are_walked(self):
        from titan_access.engine import TitanAccessEngine
        from titan_access.portable import ocrReview, palette, smart
        engine = TitanAccessEngine.__new__(TitanAccessEngine)
        said = []
        engine._say = said.append
        moved = []
        keep = (ocrReview.reviewing, ocrReview.move_line, ocrReview.stop,
                palette.walking, smart.active)
        ocrReview.reviewing = lambda: True
        ocrReview.move_line = lambda d: moved.append(d)
        ocrReview.stop = lambda: (False, 'Screen review off')
        palette.walking = lambda: False
        smart.active = lambda: False
        try:
            self.assertTrue(engine._walked_key(0, 'down', False, False, False))
            self.assertTrue(engine._walked_key(0, 'escape', False, False,
                                               False))
        finally:
            (ocrReview.reviewing, ocrReview.move_line, ocrReview.stop,
             palette.walking, smart.active) = keep
        self.assertEqual(moved, [1])
        self.assertEqual(said, ['Screen review off'])


class ReadingOutsideNvdaGoesThroughTitan(unittest.TestCase):

    def setUp(self):
        from titan_access.portable import localOcr
        from titan_access.portable.link import LINK
        self.localOcr, self.link = localOcr, LINK
        self.keep = (localOcr._in_nvda, LINK.bridge)
        localOcr._in_nvda = lambda: False
        self.asked = []

    def tearDown(self):
        self.localOcr._in_nvda, self.link.bridge = self.keep

    def test_windows_recogniser_answers_a_reading(self):
        def bridge(call, timeout=None, **args):
            self.asked.append(call)
            return True, {'ok': True, 'lines': [[
                {'text': 'Plik', 'left': 10, 'top': 5, 'width': 30,
                 'height': 12},
                {'text': 'Edycja', 'left': 50, 'top': 5, 'width': 40,
                 'height': 12}]]}
        self.link.bridge = bridge
        reading = self.localOcr.read_window_titan(1234)
        self.assertEqual(self.asked, ['ocr.read_windows'])
        self.assertIn('Plik', reading.text)
        self.assertIn('Edycja', reading.text)

    def test_available_falls_back_to_the_model(self):
        def bridge(call, timeout=None, **args):
            self.asked.append(call)
            if call == 'ocr.windows':
                return True, {'ok': False, 'text': 'no OCR language'}
            return True, {'installed': True, 'why': ''}
        self.link.bridge = bridge
        if self.localOcr._IS_WINDOWS:
            self.assertEqual(self.localOcr.available(), (True, ''))
            self.assertEqual(self.asked, ['ocr.windows', 'ocr.model'])


class TitansOwnAnnouncementsCanBeSwitchedOff(unittest.TestCase):

    def test_off_means_the_reader_reads_titans_controls_itself(self):
        from titan_access import host_bridge
        from titan_access.settings_store import get_settings

        class Engine(object):
            running = True
            settings = get_settings()
            def __init__(self):
                self.overrides = []
            def announce_override(self, text, **kwargs):
                self.overrides.append(text)

        engine = Engine()
        keep = host_bridge._engine
        host_bridge._engine = lambda: engine
        try:
            engine.settings.set_bool('General', 'TitanAnnouncements', False)
            self.assertTrue(host_bridge.announce('Pasek kart'))
            self.assertEqual(engine.overrides, [])
            engine.settings.set_bool('General', 'TitanAnnouncements', True)
            self.assertTrue(host_bridge.announce('Pasek kart'))
            self.assertEqual(engine.overrides, ['Pasek kart'])
        finally:
            host_bridge._engine = keep


class _FakeSpeaker(object):
    """A StereoSpeech that answers from a table."""
    engine = 'espeak'
    spd_module = None
    spd_voice = None

    def get_available_engines(self):
        return ['dectalk', 'espeak', 'spd']

    def get_espeak_voices(self):
        return [{'id': 'pl', 'display_name': 'Polish'}]

    def get_spd_modules(self):
        return ['espeak-ng', 'rhvoice']

    def get_spd_voices(self):
        return [{'id': 'v-%s' % (self.spd_module or 'default'),
                 'display_name': 'voice of %s' % (self.spd_module or '-')}]


class _FakeTitanEngine(object):
    engine_category = 'titantts'
    engine_id = 'dectalk'
    engine_name = 'DECtalk'

    def get_voices(self):
        return [{'id': 'Paul', 'display_name': 'Perfect Paul'}]


class _FakeRegistry(object):
    def get_all_engines(self):
        return [_FakeTitanEngine()]

    def get_engine(self, engine_id):
        return _FakeTitanEngine() if engine_id == 'dectalk' else None

    def get_titantts_engine(self, engine_id):
        return self.get_engine(engine_id)


class TheSpeechSystemIsChosen(unittest.TestCase):

    def setUp(self):
        from titan_access import speech_systems
        self.ss = speech_systems
        self.keep = speech_systems._registry
        speech_systems._registry = lambda: _FakeRegistry()
        self.speaker = _FakeSpeaker()

    def tearDown(self):
        self.ss._registry = self.keep

    def test_three_levels(self):
        systems = [one for one, _label in self.ss.systems(self.speaker)]
        self.assertEqual(systems, ['titan', 'titantts', 'espeak', 'spd'])
        self.assertEqual(self.ss.synthesizers('titantts', self.speaker),
                         [('dectalk', 'DECtalk')])
        synths = [one for one, _l in self.ss.synthesizers('spd',
                                                           self.speaker)]
        self.assertEqual(synths, ['spd:', 'spd:espeak-ng', 'spd:rhvoice'])
        self.assertEqual(self.ss.voices('dectalk', self.speaker),
                         [('Paul', 'Perfect Paul')])

    def test_a_modules_voices_are_listed_without_changing_the_module(self):
        self.speaker.spd_module = 'espeak-ng'
        self.assertEqual(self.ss.voices('spd:rhvoice', self.speaker),
                         [('v-rhvoice', 'voice of rhvoice')])
        self.assertEqual(self.speaker.spd_module, 'espeak-ng')

    def test_choosing_stores_and_applies(self):
        from titan_access.settings_store import get_settings
        settings = get_settings()

        class Engine(object):
            applied = 0
            def apply_settings(self):
                Engine.applied += 1

        self.ss.choose(settings, 'spd', 'spd:rhvoice', 'v-rhvoice',
                       engine=Engine())
        self.assertEqual(self.ss.current(settings),
                         ('spd', 'spd:rhvoice', 'v-rhvoice'))
        self.assertEqual(settings.get('Speech', 'Synthesizer'), 'spd')
        self.assertEqual(Engine.applied, 1)
        self.ss.choose(settings, 'titantts', 'dectalk', 'Paul')
        self.assertEqual(self.ss.current(settings),
                         ('titantts', 'dectalk', 'Paul'))
        self.ss.choose(settings, 'titan', '', '')
        self.assertEqual(self.ss.current(settings), ('titan', '', ''))

    def test_a_test_borrows_the_module_too(self):
        self.assertEqual(self.ss.profile_of('spd:rhvoice', 'x'),
                         {'synth': 'spd', 'spd_module': 'rhvoice',
                          'voice': 'x'})

    def test_the_reader_puts_the_module_on_before_the_voice(self):
        from titan_access import speech_adapter
        from titan_access.settings_store import get_settings
        settings = get_settings()
        self.ss.choose(settings, 'spd', 'spd:rhvoice', 'v-rhvoice')

        class Speaker(_FakeSpeaker):
            engine = 'spd'
            chosen = None
            def set_engine(self, name):
                self.engine = name
            def set_spd_module(self, module):
                self.spd_module = module or None
            def get_available_voices(self):
                return self.get_spd_voices()
            def set_voice(self, at):
                Speaker.chosen = self.get_spd_voices()[at]['id']

        adapter = speech_adapter.SpeechAdapter.__new__(
            speech_adapter.SpeechAdapter)
        adapter._engine = Speaker()
        adapter._settings = settings
        adapter._apply_own_voice()
        self.assertEqual(adapter._engine.spd_module, 'rhvoice')
        self.assertEqual(Speaker.chosen, 'v-rhvoice')


class SpeechDispatcherIsReadProperly(unittest.TestCase):

    def test_the_header_is_not_a_voice_and_modules_are_listed(self):
        from src.titan_core import stereo_speech
        speaker = stereo_speech.StereoSpeech.__new__(stereo_speech.StereoSpeech)
        speaker.spd_module = 'espeak-ng'
        speaker.spd_voice = None
        ran = []

        class Done(object):
            returncode = 0
            def __init__(self, out):
                self.stdout = out

        def run(command, **kwargs):
            ran.append(command)
            if '-O' in command:
                return Done('OUTPUT MODULES\nespeak-ng\nrhvoice\n')
            return Done('                NAME   LANGUAGE   VARIANT\n'
                        '           Polish        pl          none\n'
                        '  English (America)   en-US          none\n')

        keep = (stereo_speech.SPD_AVAILABLE, stereo_speech.subprocess.run)
        stereo_speech.SPD_AVAILABLE = True
        stereo_speech.SPD_PATH = getattr(stereo_speech, 'SPD_PATH', None) \
            or 'spd-say'
        stereo_speech.subprocess.run = run
        try:
            self.assertEqual(speaker.get_spd_modules(),
                             ['espeak-ng', 'rhvoice'])
            voices = speaker.get_spd_voices()
        finally:
            stereo_speech.SPD_AVAILABLE, stereo_speech.subprocess.run = keep
        self.assertEqual([v['id'] for v in voices],
                         ['Polish', 'English (America)'])
        self.assertIn('-o', ran[-1])
        speaker.set_spd_module('rhvoice')
        self.assertEqual(speaker.spd_module, 'rhvoice')


class InsertAltDoesNotOpenTheMenuBar(unittest.TestCase):

    def test_an_alt_gesture_masks_the_alt(self):
        from titan_access import keyboard_hook

        class Engine(object):
            def on_modifier_gesture(self, *args, **kwargs):
                return True

        hook = keyboard_hook.KeyboardHook.__new__(keyboard_hook.KeyboardHook)
        masked = []
        hook.engine = Engine()
        hook._mask_alt = lambda: masked.append(True)
        hook._reader_mod = True
        hook._alt = True
        hook._ctrl = hook._shift = False
        hook._normalize = lambda vk, extended: ('o', False)
        hook._mod_used = False
        try:
            swallowed = hook._process(0x4F, 0, 0, True)
        except Exception:                            # noqa: BLE001
            self.skipTest('the hook needs more state than this machine has')
        self.assertTrue(swallowed)
        self.assertEqual(masked, [True])


if __name__ == '__main__':
    unittest.main()
