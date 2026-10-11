# -*- coding: utf-8 -*-
"""NVDA add-ons installed in and run by Titan Access (`nvda_host`).

Run directly: ``python tests/test_titan_access_nvda_host.py``. A small
NVDA add-on is BUILT here - a global plugin with a script and a focus
handler, an app module, a synthesizer that streams PCM and reports its
indexes - packed as a real ``.nvda-addon`` and installed into a temporary
Titan Access home. Audio is silent (``TITAN_ACCESS_SILENT_AUDIO``); nothing
speaks or opens a window. Runs on Windows and Linux alike.
"""

import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'titan access')
for path in (ROOT, COMPONENT):
    if path not in sys.path:
        sys.path.insert(0, path)
HOME = tempfile.mkdtemp(prefix='ta_nvdahost_')
os.environ['APPDATA'] = HOME
os.environ['TITAN_ACCESS_SILENT_AUDIO'] = '1'

from titan_access.portable import readerHome                # noqa: E402

readerHome.folder = lambda: os.path.join(HOME, 'accessibility')

from titan_access import nvda_host                            # noqa: E402
from titan_access.nvda_host import external                   # noqa: E402

said = []

PLUGIN = '''
import globalPluginHandler
import ui
from scriptHandler import script
import addonHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    @script(description="Say hello", gesture="kb:NVDA+shift+z")
    def script_hello(self, gesture):
        ui.message(_("hello from the add-on"))

    def event_gainFocus(self, obj, nextHandler):
        if getattr(obj, "name", "") == "eat":
            ui.message("eaten")
            return
        nextHandler()
'''

APP_MODULE = '''
import appModuleHandler


class AppModule(appModuleHandler.AppModule):
    def event_gainFocus(self, obj, nextHandler):
        obj.seen_by_app_module = True
        nextHandler()
'''

SYNTH = '''
from collections import OrderedDict
import threading
import nvwave
from synthDriverHandler import (SynthDriver, VoiceInfo, synthIndexReached,
                                synthDoneSpeaking)
from speech.commands import IndexCommand, PitchCommand, BreakCommand


class SynthDriver(SynthDriver):
    name = "fakeSynth"
    description = "Fake synthesizer"
    supportedSettings = (SynthDriver.VoiceSetting(),
                         SynthDriver.VariantSetting(),
                         SynthDriver.RateSetting())
    supportedCommands = {IndexCommand, PitchCommand, BreakCommand}
    supportedNotifications = {synthIndexReached, synthDoneSpeaking}

    @classmethod
    def check(cls):
        return True

    def __init__(self):
        super().__init__()
        self._player = nvwave.WavePlayer(1, 16000, 16)
        self._voice = "one"
        self._variant = "compact"
        self._rate = 50
        self.spoken = []
        self.breaks = []
        self.paused = []

    def pause(self, switch):
        self.paused.append(switch)
        self._player.pause(switch)

    def speak(self, sequence):
        def work():
            for item in sequence:
                if isinstance(item, BreakCommand):
                    self.breaks.append(item.time)
                if isinstance(item, str):
                    self.spoken.append(item)
                    self._player.feed(b"\\x00\\x10" * 1600 * len(item))
                elif isinstance(item, IndexCommand):
                    self._player.feed(None, onDone=lambda i=item.index:
                                      synthIndexReached.notify(synth=self,
                                                               index=i))
            self._player.idle()
            synthDoneSpeaking.notify(synth=self)
        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        self._player.stop()

    def _get_availableVoices(self):
        return OrderedDict([("one", VoiceInfo("one", "Voice One", "pl")),
                            ("two", VoiceInfo("two", "Voice Two", "en"))])

    def _get_voice(self):
        return self._voice

    def _set_voice(self, value):
        self._voice = value
        # As Cerence: each voice has its own variants.
        if hasattr(self, "_availableVariants"):
            del self._availableVariants

    def _getAvailableVariants(self):
        if self._voice == "two":
            return OrderedDict([("pro", VoiceInfo("pro", "embedded-pro"))])
        return OrderedDict([("compact", VoiceInfo("compact", "embedded-compact")),
                            ("high", VoiceInfo("high", "embedded-high"))])

    def _get_variant(self):
        return self._variant

    def _set_variant(self, value):
        self._variant = value

    def _get_rate(self):
        return self._rate

    def _set_rate(self, value):
        self._rate = value
'''

#: A synthesizer like Cerence or Samsung: it reports an index when it has
#: MADE the audio up to it (not when it is played), has no BreakCommand,
#: pads every part with 0.2 s of near-silence, and says it is done only
#: once its player has played everything.
MADE_SYNTH = '''
import threading
import nvwave
import speech
from synthDriverHandler import (SynthDriver, synthIndexReached,
                                synthDoneSpeaking)
from speech.commands import IndexCommand, PitchCommand


class SynthDriver(SynthDriver):
    name = "madeSynth"
    description = "Reports indexes as it makes the audio"
    supportedSettings = ()
    supportedCommands = {IndexCommand, PitchCommand}
    supportedNotifications = {synthIndexReached, synthDoneSpeaking}

    @classmethod
    def check(cls):
        return True

    def __init__(self):
        super().__init__()
        self._player = nvwave.WavePlayer(1, 16000, 16)
        self.joined = speech.CHUNK_SEPARATOR.join(["a", "b"])

    def speak(self, sequence):
        def work():
            for item in sequence:
                if isinstance(item, str):
                    self._player.feed(b"\\x00\\x10" * 1600 * len(item)
                                      + b"\\x05\\x00" * 3200)
                elif isinstance(item, IndexCommand):
                    synthIndexReached.notify(synth=self, index=item.index)
            self._player.feed(b"", onDone=lambda: synthDoneSpeaking.notify(
                synth=self))
        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        self._player.stop()
'''

LOCALE_PO = '''msgid "hello from the add-on"
msgstr "witaj z dodatku"
'''


def _mo(po_text):
    """A gettext .mo from msgid/msgstr pairs (enough for one string)."""
    import struct
    pairs = {}
    msgid = None
    for line in po_text.splitlines():
        if line.startswith('msgid '):
            msgid = line[7:-1]
        elif line.startswith('msgstr ') and msgid is not None:
            pairs[msgid] = line[8:-1]
    keys = sorted(pairs)
    ids = b''.join(k.encode() + b'\0' for k in keys)
    strs = b''.join(pairs[k].encode() + b'\0' for k in keys)
    start = 7 * 4 + 16 * len(keys)
    offsets, at = [], 0
    for k in keys:
        offsets.append((len(k.encode()), start + at))
        at += len(k.encode()) + 1
    voffsets, at = [], 0
    for k in keys:
        voffsets.append((len(pairs[k].encode()), start + len(ids) + at))
        at += len(pairs[k].encode()) + 1
    out = struct.pack('Iiiiiii', 0x950412de, 0, len(keys), 7 * 4,
                      7 * 4 + 8 * len(keys), 0, 0)
    for length, offset in offsets:
        out += struct.pack('ii', length, offset)
    for length, offset in voffsets:
        out += struct.pack('ii', length, offset)
    return out + ids + strs


def build_addon(where, name='demoAddon'):
    path = os.path.join(where, name + '.nvda-addon')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('manifest.ini', textwrap.dedent('''\
            name = %s
            summary = "A demo add-on"
            version = 1.0
            description = """Several
            lines"""
            ''' % name))
        archive.writestr('globalPlugins/demo.py', PLUGIN)
        archive.writestr('appModules/demoapp.py', APP_MODULE)
        archive.writestr('synthDrivers/fakeSynth.py', SYNTH)
        archive.writestr('synthDrivers/madeSynth.py', MADE_SYNTH)
        archive.writestr('locale/pl/LC_MESSAGES/nvda.mo', _mo(LOCALE_PO))
    return path


class Engine(object):
    current_object = None

    def speak(self, text, interrupt=True, **_kwargs):
        said.append(str(text))

    def post_to_worker(self, func):
        func()


class Obj(object):
    def __init__(self, name):
        self.name = name
        self.role = 'button'
        self.processID = 0


class TheHost(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from titan_access.nvda_host.shims import languageHandler
        languageHandler.getLanguage = lambda: 'pl'
        cls.package = build_addon(HOME)
        ok, why = nvda_host.install(cls.package)
        assert ok, why
        import titan_access.engine as engine_module
        cls.keep_get = getattr(engine_module, 'get_engine', None)
        engine_module.get_engine = lambda: Engine()
        nvda_host.load(Engine())

    @classmethod
    def tearDownClass(cls):
        nvda_host.unload()
        from titan_access.nvda_host import importer
        importer.uninstall()
        import titan_access.engine as engine_module
        if cls.keep_get is not None:
            engine_module.get_engine = cls.keep_get

    def setUp(self):
        del said[:]

    def test_installed_from_the_file_with_its_manifest(self):
        record = nvda_host.by_name('demoAddon')
        self.assertIsNotNone(record)
        self.assertEqual(record['summary'], 'A demo add-on')
        self.assertEqual(record['manifest']['description'], 'Several\nlines')
        self.assertEqual(set(record['kinds']),
                         {'globalPlugins', 'appModules', 'synthDrivers'})
        self.assertTrue(record['path'].startswith(HOME))

    def test_the_global_plugin_runs_with_its_translation(self):
        self.assertTrue(any(type(p).__module__ == 'globalPlugins.demo'
                            for p in nvda_host._state['plugins']),
                        nvda_host.report()['errors'])
        identifier = nvda_host.identifier_of('z', shift=True, reader=True)
        self.assertIn(identifier, [one[0] for one in nvda_host.gestures()])
        # Run the script directly (the host queues it on wx otherwise).
        plugin = [p for p in nvda_host._state['plugins']
                  if type(p).__module__ == 'globalPlugins.demo'][0]
        plugin.script_hello(None)
        self.assertEqual(said, ['witaj z dodatku'])

    def test_the_focus_chain_with_next_handler(self):
        self.assertTrue(nvda_host.fire_event('gainFocus', Obj('ok')))
        self.assertFalse(nvda_host.fire_event('gainFocus', Obj('eat')))
        self.assertIn('eaten', said)

    def test_external_synthesis(self):
        synths = nvda_host.synthesizers()
        self.assertEqual(sorted((s['name'], s['error']) for s in synths),
                         [('fakeSynth', ''), ('madeSynth', '')])
        self.assertEqual(external.voices('nvda:fakeSynth'),
                         [('one', 'Voice One'), ('two', 'Voice Two')])
        from titan_access.nvda_host.shims import nvwave
        before = nvwave.fed_bytes[0]
        started = time.time()
        self.assertTrue(external.speak_parts(
            'nvda:fakeSynth', [('Zapisz', 0), ('przycisk', -4)],
            timeout=10))
        self.assertLess(time.time() - started, 5)
        self.assertGreater(nvwave.fed_bytes[0], before)
        synth = nvda_host.synth_instance('fakeSynth')
        self.assertEqual(synth.spoken[-2:], ['Zapisz', 'przycisk'])
        external.set_levels('nvda:fakeSynth', rate=80)
        self.assertEqual(synth.rate, 80)
        self.assertTrue(external.set_voice('nvda:fakeSynth', 'two'))
        self.assertEqual(synth.voice, 'two')

    def test_one_instance_however_many_ask_and_none_retired_by_a_look(self):
        """RHVoice was started nineteen times in one session: two threads
        asking at once made two instances, and listing another
        synthesizer's voices terminated the one the reader spoke with."""
        nvda_host.unload()
        nvda_host.load(Engine())
        found = []

        def ask():
            found.append(nvda_host.synth_instance('fakeSynth'))
        threads = [threading.Thread(target=ask) for _ in range(6)]
        for one in threads:
            one.start()
        for one in threads:
            one.join(10)
        self.assertEqual(len(set(map(id, found))), 1)
        speaking = found[0]
        terminated = []
        speaking.terminate = lambda: terminated.append(True)
        nvda_host.synth_instance('madeSynth')
        self.assertIs(nvda_host.synth_instance('fakeSynth'), speaking)
        self.assertEqual(terminated, [])
        del speaking.terminate

    def test_a_synthesizer_that_stops_answering_is_started_again(self):
        """Nothing fed and no index: the reader used to wait a minute per
        utterance - silent, which from outside is a reader that hung."""
        dead = nvda_host.synth_instance('fakeSynth')
        dead.speak = lambda sequence: None
        kept = external.FIRST_SOUND_S
        external.FIRST_SOUND_S = 0.4
        before = external.report()['stalled']
        started = time.time()
        try:
            said = external.speak_parts('nvda:fakeSynth', [('Zapisz', 0)],
                                        timeout=30)
        finally:
            external.FIRST_SOUND_S = kept
        self.assertFalse(said)
        self.assertLess(time.time() - started, 3)
        self.assertEqual(external.report()['stalled'], before + 1)
        fresh = nvda_host.synth_instance('fakeSynth')
        self.assertIsNot(fresh, dead)
        self.assertTrue(external.speak_parts('nvda:fakeSynth',
                                             [('Zapisz', 0)], timeout=10))

    def test_a_new_instance_is_given_the_chosen_voice(self):
        """Reported as "the external synthesizer speaks in some default
        voice, not the one I set": an instance retired (stalled, or pushed
        out of KEEP_RUNNING by looking at other synthesizers' voices) was
        made again on its default voice."""
        external.set_voice('nvda:fakeSynth', 'two')
        external.set_levels('nvda:fakeSynth', rate=70)
        nvda_host.retire_synth('fakeSynth')
        synth = nvda_host.synth_instance('fakeSynth')
        self.assertEqual(external._synth('nvda:fakeSynth').voice, 'two')
        self.assertEqual(synth.rate, 70)
        # A voice may be named by what it is called, too.
        self.assertTrue(external.set_voice('nvda:fakeSynth', 'voice one'))
        self.assertEqual(synth.voice, 'one')
        self.assertFalse(external.set_voice('nvda:fakeSynth', 'nobody'))
        self.assertEqual(synth.voice, 'one')
        external.set_voice('nvda:fakeSynth', 'one')

    def test_variants_belong_to_a_voice(self):
        """Cerence installs a voice as compact, embedded-pro or
        embedded-high; the variant is a fourth level after the voice."""
        synth = nvda_host.synth_instance('fakeSynth')
        external.set_voice('nvda:fakeSynth', 'one')
        self.assertEqual(external.variants('nvda:fakeSynth'),
                         [('compact', 'embedded-compact'),
                          ('high', 'embedded-high')])
        # Another voice's variants are asked without changing the voice.
        self.assertEqual(external.variants('nvda:fakeSynth', 'two'),
                         [('pro', 'embedded-pro')])
        self.assertEqual(synth.voice, 'one')
        self.assertTrue(external.set_variant('nvda:fakeSynth', 'high'))
        self.assertEqual(external.variant('nvda:fakeSynth'), 'high')
        # One the voice has not got is refused, and nothing changes.
        self.assertFalse(external.set_variant('nvda:fakeSynth', 'pro'))
        self.assertEqual(synth.variant, 'high')
        # A synthesizer with no variant setting has no variants.
        self.assertEqual(external.variants('nvda:madeSynth'), [])

    def test_the_reader_puts_its_variant_on(self):
        from titan_access import speech_systems
        speech_systems.forget_voices()
        self.assertEqual(
            speech_systems.variants('nvda:fakeSynth', 'one'),
            [('compact', 'embedded-compact'), ('high', 'embedded-high')])
        self.assertEqual(speech_systems.variants('sapi5', 'x'), [])
        wanted = speech_systems.settings_for('nvda', 'nvda:fakeSynth', 'one',
                                             'high')
        self.assertEqual(wanted[('Speech', 'Variant')], 'high')

        class Store(dict):
            def get(self, section, key, default=None):
                return dict.get(self, (section, key), default)

            def get_bool(self, section, key, default=False):
                value = dict.get(self, (section, key), default)
                return value is True or str(value).lower() == 'true'

            def get_int(self, section, key, default=0):
                return int(dict.get(self, (section, key), default))

            def set(self, section, key, value):
                self[(section, key)] = value

            def set_bool(self, section, key, value):
                self[(section, key)] = bool(value)

            def save(self):
                pass
        store = Store()
        speech_systems.choose(store, 'nvda', 'nvda:fakeSynth', 'one',
                              variant='compact')
        said = speech_systems.step(store, 'variant')
        self.assertEqual(said, 'embedded-high')
        self.assertEqual(store[('Speech', 'Variant')], 'high')
        # A new voice starts on its own default variant.
        speech_systems.step(store, 'voice')
        self.assertEqual(store[('Speech', 'Variant')], '')
        from titan_access.speech_adapter import SpeechAdapter
        adapter = SpeechAdapter.__new__(SpeechAdapter)
        store[('Speech', 'Voice')] = 'one'
        store[('Speech', 'Variant')] = 'high'
        adapter._settings = store
        adapter._apply_external('nvda:fakeSynth', warm=False)
        synth = nvda_host.synth_instance('fakeSynth')
        self.assertEqual((synth.voice, synth.variant), ('one', 'high'))

    def test_a_disabled_add_on_does_not_run(self):
        nvda_host.set_enabled('demoAddon', False)
        try:
            nvda_host.reload()
            self.assertEqual(nvda_host._state['plugins'], [])
            self.assertEqual(nvda_host.synthesizers(), [])
        finally:
            nvda_host.set_enabled('demoAddon', True)
            nvda_host.reload()


class OnlyAddOnCodeSeesNvdasNames(unittest.TestCase):

    def test_ordinary_code_gets_no_stand_in(self):
        from titan_access.nvda_host import importer
        importer.install([nvda_host.folder()])
        for name in ('api', 'config', 'speech', 'ui', 'tones'):
            module = sys.modules.get(name)
            self.assertFalse(module is not None and 'nvda_host' in
                             str(getattr(module, '__name__', '')), name)
        try:
            import controlTypes                       # noqa: F401
            got_it = True
        except ImportError:
            got_it = False
        self.assertFalse(got_it)

    def test_a_name_no_stand_in_has_is_harmless_and_reported(self):
        from titan_access.nvda_host.shims import braille, missing
        thing = braille.SomethingNobodyWrote
        self.assertTrue(isinstance(thing, type))
        self.assertIsNone(thing()())
        self.assertIn('braille.SomethingNobodyWrote', missing)


class SpeechXmlIsValidSsml(unittest.TestCase):

    def test_attributes_nest_and_balance(self):
        from xml.dom import minidom
        from titan_access.nvda_host.shims import speechXml
        from titan_access.nvda_host.shims.speech import commands
        xml = speechXml.SsmlConverter('pl_PL').convertToXml([
            'Ala', commands.PitchCommand(multiplier=2), 'ma',
            commands.LangChangeCommand('en_US'), 'cat',
            commands.PitchCommand(), commands.IndexCommand(7), 'end'])
        document = minidom.parseString(xml)
        self.assertEqual(document.documentElement.tagName, 'speak')
        self.assertEqual(document.documentElement.getAttribute('xml:lang'),
                         'pl-PL')
        self.assertIn('<prosody pitch="200%">ma', xml)
        self.assertIn('<mark name="7"/>', xml)
        self.assertIn('xml:lang="en-US"', xml)


class MigratingFromNvda(unittest.TestCase):

    def test_migrate_copies_and_skips_titans_own(self):
        nvda = os.path.join(HOME, 'nvda', 'addons')
        for name in ('fromNvda', 'titanEnhancements'):
            os.makedirs(os.path.join(nvda, name), exist_ok=True)
            with open(os.path.join(nvda, name, 'manifest.ini'), 'w') as f:
                f.write('name = %s\nsummary = x\nversion = 1\n' % name)
        self.assertEqual([one[0] for one in nvda_host.migratable()],
                         ['fromNvda'])
        self.assertTrue(nvda_host.migration_wanted())
        done = nvda_host.migrate()
        self.assertEqual(done, [('fromNvda', True, '')])
        self.assertIsNotNone(nvda_host.by_name('fromNvda'))
        self.assertFalse(nvda_host.migration_wanted())
        nvda_host.remove('fromNvda')


class PausesReachTheSynthesizer(unittest.TestCase):
    """A pause between the parts, and pausing speech itself."""

    @classmethod
    def setUpClass(cls):
        TheHost.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        TheHost.tearDownClass.__func__(cls)

    def test_the_gap_between_parts_is_a_break(self):
        synth = nvda_host.synth_instance('fakeSynth')
        del synth.breaks[:]
        self.assertTrue(external.speak_parts(
            'nvda:fakeSynth', [('Zapisz', 0), ('przycisk', -4),
                               ('zaznaczony', 4)], gap_ms=180, timeout=10))
        self.assertEqual(synth.breaks, [180, 180])

    def test_a_synthesizer_without_breaks_still_pauses(self):
        synth = nvda_host.synth_instance('fakeSynth')
        from titan_access.nvda_host.shims.speech import commands
        kept = type(synth).supportedCommands
        type(synth).supportedCommands = {commands.IndexCommand,
                                         commands.PitchCommand}
        try:
            del synth.spoken[:]
            before = external.report()['silences_inserted']
            self.assertTrue(external.speak_parts(
                'nvda:fakeSynth', [('a', 0), ('b', 0), ('c', 0)],
                gap_ms=300, timeout=10))
            self.assertEqual(synth.spoken[-3:], ['a', 'b', 'c'])
            # The silence is put into the player between the parts (where
            # it lands in the audio: `WhatIsPlayed`).
            self.assertEqual(external.report()['silences_inserted'],
                             before + 2)
        finally:
            type(synth).supportedCommands = kept

    def test_no_gap_no_break(self):
        synth = nvda_host.synth_instance('fakeSynth')
        del synth.breaks[:]
        external.speak_parts('nvda:fakeSynth', [('a', 0), ('b', 0)],
                             timeout=10)
        self.assertEqual(synth.breaks, [])

    def test_pause_reaches_the_driver(self):
        synth = nvda_host.synth_instance('fakeSynth')
        del synth.paused[:]
        self.assertTrue(external.pause('nvda:fakeSynth', True))
        self.assertTrue(external.pause('nvda:fakeSynth', False))
        self.assertEqual(synth.paused, [True, False])

    def test_a_paused_wait_does_not_time_out(self):
        state = {'paused': True}
        import threading
        threading.Timer(0.6, lambda: state.update(paused=False)).start()
        started = time.time()
        ok = external.speak_parts('nvda:fakeSynth', [('a', 0)], timeout=0.3,
                                  paused=lambda: state['paused'])
        self.assertTrue(ok)
        self.assertGreater(time.time() - started, 0.5)


class TheReaderPausesWithShift(unittest.TestCase):

    def _adapter(self):
        from titan_access import speech_adapter
        adapter = speech_adapter.SpeechAdapter.__new__(
            speech_adapter.SpeechAdapter)
        import threading
        adapter._settings = type('S', (), {
            'get_bool': lambda self, *a: False,
            'get': lambda self, *a: ''})()
        adapter._q_lock = threading.Lock()
        adapter._seq_lock = threading.Lock()
        adapter._queue = []
        adapter._current = object()
        adapter._generation = 0
        adapter._seq_id = 0
        adapter._wake = threading.Event()
        adapter._tts_channel_getter = False
        adapter._mode = 'print'
        adapter._engine = None
        adapter._speaking_until = 0.0
        return adapter

    def test_toggle_and_stop(self):
        adapter = self._adapter()
        self.assertTrue(adapter.toggle_pause())
        self.assertTrue(adapter.paused)
        self.assertFalse(adapter.toggle_pause())
        adapter.toggle_pause()
        adapter.stop()
        self.assertFalse(adapter.paused)

    def test_nothing_to_pause_is_not_a_pause(self):
        adapter = self._adapter()
        adapter._current = None
        self.assertFalse(adapter.toggle_pause())
        self.assertFalse(adapter.paused)

    def test_shift_alone_and_shift_with_a_letter(self):
        from titan_access import keyboard_hook
        calls = []

        class Engine(object):
            def on_pause_speech_key(self):
                calls.append('pause')

            def __getattr__(self, name):
                return lambda *a, **k: False
        hook = keyboard_hook.KeyboardHook.__new__(keyboard_hook.KeyboardHook)
        hook.engine = Engine()
        for name, value in (('_ctrl', False), ('_alt', False),
                            ('_shift', False), ('_reader_mod', False),
                            ('_mod_used', False), ('_ralt', False),
                            ('_word', []), ('_user32', None)):
            setattr(hook, name, value)
        hook._is_reader_modifier = lambda vk, extended: False
        hook._modifier_pressed = lambda name: None
        hook._process(0xA0, 0x2A, 0, True)        # Shift down
        hook._process(0xA0, 0x2A, 0, False)       # Shift up, alone
        self.assertEqual(calls, ['pause'])
        hook._process(0xA0, 0x2A, 0, True)
        try:
            hook._process(0x41, 0x1E, 0, True)    # A, while Shift is held
        except Exception:                          # noqa: BLE001
            pass
        hook._process(0xA0, 0x2A, 0, False)
        self.assertEqual(calls, ['pause'])


class NvdasConfigurationModel(unittest.TestCase):

    def test_a_spec_with_many_sections_and_types(self):
        from titan_access.nvda_host.shims import config
        speech = config.conf['speech']
        self.assertFalse(speech.isSet('Probe'))
        speech['Probe'] = {}
        speech['Probe'].spec.update({
            'voices': {'__many__': {
                'rate': 'integer(default=130,min=50,max=400)',
                'variant': 'string(default=None)'}},
            'auto': {'enabled': 'boolean(default=false)',
                     'lang': 'string(default=en)'}})
        probe = speech['Probe']
        self.assertTrue(speech.isSet('Probe'))
        self.assertEqual(probe['voices']['Ewa']['rate'], 130)
        self.assertIsNone(probe['voices']['Ewa'].get('variant'))
        self.assertIs(probe['auto']['enabled'], False)
        self.assertEqual(probe['auto']['lang'], 'en')
        dict.__setitem__(probe['voices']['Ewa'], 'rate', '150')
        self.assertEqual(probe['voices']['Ewa']['rate'], 150)   # typed

    def test_language_info_words_itself(self):
        from titan_access.nvda_host.shims.synthDriverHandler import \
            LanguageInfo
        self.assertEqual(LanguageInfo('pl_PL').displayName, 'Polski (PL)')
        self.assertIsNone(LanguageInfo('xx_YY').displayName)


class MigratingDataAndSettings(unittest.TestCase):

    def test_an_addons_data_and_its_ini_section_come_along(self):
        nvda = os.path.join(HOME, 'nvda2')
        addons = os.path.join(nvda, 'addons', 'dataAddon')
        os.makedirs(os.path.join(addons, 'synthDrivers'), exist_ok=True)
        with open(os.path.join(addons, 'manifest.ini'), 'w') as handle:
            handle.write('name = dataAddon\nsummary = d\nversion = 1\n')
        with open(os.path.join(addons, 'synthDrivers', 'dataSynth.py'),
                  'w') as handle:
            handle.write('# nothing\n')
        os.makedirs(os.path.join(nvda, 'dataSynth-voices'), exist_ok=True)
        with open(os.path.join(nvda, 'dataSynth-voices', 'v.bin'),
                  'wb') as handle:
            handle.write(b'voice')
        with open(os.path.join(nvda, 'nvda.ini'), 'w') as handle:
            handle.write('[speech]\n\t[[dataSynth]]\n\t\trate = 77\n')
        keep = nvda_host.nvda_addons_folder
        nvda_host.nvda_addons_folder = lambda: os.path.join(nvda, 'addons')
        state = nvda_host._read_state()
        try:
            done = nvda_host.migrate()
        finally:
            nvda_host.nvda_addons_folder = keep
            nvda_host._write_state(state)     # the first-run question stays
            self.addCleanup(nvda_host.remove, 'dataAddon')
        self.assertIn(('dataAddon', True, ''), done)
        self.assertTrue(os.path.isfile(os.path.join(
            nvda_host.config_folder(), 'dataSynth-voices', 'v.bin')))
        from titan_access.nvda_host.shims import config
        try:
            import configobj                          # noqa: F401
        except ImportError:
            self.skipTest('configobj is not installed here')
        self.assertEqual(config.conf['speech']['dataSynth']['rate'], '77')


class _FakeDevice(object):
    """A sound device that plays in real time and keeps what it played -
    what the user would have HEARD, without a sound."""

    played = []
    streams = []
    #: How much the device asks for at a time. A real WASAPI or MME device
    #: asks for far more than 10 ms at once.
    block_ms = 10

    class RawOutputStream(object):
        def __init__(self, samplerate, channels, dtype, callback,
                     blocksize=0, **_kwargs):
            self.rate = int(samplerate)
            self.frame = int(channels) * 2
            self.callback = callback
            self.running = False
            _FakeDevice.streams.append(self)

        def start(self):
            self.running = True

            def loop():
                while self.running:
                    block = self.rate * _FakeDevice.block_ms // 1000
                    out = bytearray(block * self.frame)
                    self.callback(out, block, None, None)
                    # Kept in 10 ms pieces, which is what `_runs` counts.
                    piece = (self.rate // 100) * self.frame
                    for at in range(0, len(out), piece):
                        _FakeDevice.played.append(
                            (self, bytes(out[at:at + piece])))
                    time.sleep(_FakeDevice.block_ms / 1000.0)
            threading.Thread(target=loop, daemon=True).start()

        def stop(self):
            self.running = False

        def close(self):
            self.running = False

    @staticmethod
    def query_hostapis():
        return []


def _runs(played, loud=1000):
    """``[(loud?, milliseconds)]`` of 16-bit mono at 16 kHz, in 10 ms."""
    import array
    loud_streams = [stream for stream, block in played
                    if any(abs(v) > loud for v in array.array('h', block))]
    mine = loud_streams[0] if loud_streams else None
    runs = []
    for stream, block in played:
        if stream is not mine:
            continue
        samples = array.array('h', block)
        is_loud = any(abs(v) > loud for v in samples)
        if runs and runs[-1][0] == is_loud:
            runs[-1][1] += 10
        else:
            runs.append([is_loud, 10])
    while runs and not runs[0][0]:
        runs.pop(0)
    while runs and not runs[-1][0]:
        runs.pop()
    return [tuple(run) for run in runs]


class WhatIsPlayed(unittest.TestCase):
    """What a user hears from an external synthesizer: the pauses between
    the parts, the padding cut, and an utterance over only when heard."""

    @classmethod
    def setUpClass(cls):
        TheHost.setUpClass.__func__(cls)
        cls.kept_device = sys.modules.get('sounddevice')
        sys.modules['sounddevice'] = _FakeDevice
        os.environ['TITAN_ACCESS_SILENT_AUDIO'] = '0'

    @classmethod
    def tearDownClass(cls):
        os.environ['TITAN_ACCESS_SILENT_AUDIO'] = '1'
        for stream in _FakeDevice.streams:
            stream.running = False
        if cls.kept_device is not None:
            sys.modules['sounddevice'] = cls.kept_device
        else:
            sys.modules.pop('sounddevice', None)
        TheHost.tearDownClass.__func__(cls)

    def _say(self, name, parts, gap):
        nvda_host.synth_instance(name)
        time.sleep(0.05)
        del _FakeDevice.played[:]
        started = time.time()
        self.assertTrue(external.speak_parts('nvda:' + name, parts,
                                             gap_ms=gap, timeout=10))
        took = time.time() - started
        time.sleep(0.05)
        return took, _runs(_FakeDevice.played)

    def test_a_synth_that_reports_as_it_makes_is_waited_for(self):
        # Two parts of 0.1 s with a 300 ms pause: the call returns only
        # once they have been PLAYED, not when the index was reported.
        took, runs = self._say('madeSynth', [('a', 0), ('b', 0)], 300)
        self.assertGreaterEqual(took, 0.45, runs)
        self.assertEqual([loud for loud, _ms in runs], [True, False, True],
                         runs)
        # The pause is the pause asked for - the synth's own 0.2 s of
        # padding is cut, not added to it.
        self.assertTrue(260 <= runs[1][1] <= 380, runs)

    def test_a_synth_that_reports_as_it_plays_gets_its_pause(self):
        synth = nvda_host.synth_instance('fakeSynth')
        from titan_access.nvda_host.shims.speech import commands
        kept = type(synth).supportedCommands
        type(synth).supportedCommands = {commands.IndexCommand,
                                         commands.PitchCommand}
        try:
            _took, runs = self._say('fakeSynth', [('a', 0), ('b', 0)], 300)
        finally:
            type(synth).supportedCommands = kept
        self.assertEqual([loud for loud, _ms in runs], [True, False, True],
                         runs)
        self.assertTrue(250 <= runs[1][1] <= 400, runs)

    def test_a_pause_is_a_pause_and_not_a_cut_word(self):
        """RHVoice: "no pauses, only cuts". A synthesizer that reports an
        index as its audio is PLAYED puts the pause in from that callback;
        a device that asks for 60 ms at a time had already started the
        next part when the silence went in, so the second word was heard
        cut in two around the pause. The playing holds AT the index now."""
        synth = nvda_host.synth_instance('fakeSynth')
        from titan_access.nvda_host.shims.speech import commands
        kept = type(synth).supportedCommands
        type(synth).supportedCommands = {commands.IndexCommand,
                                         commands.PitchCommand}
        _FakeDevice.block_ms = 60
        try:
            _took, runs = self._say('fakeSynth', [('ab', 0), ('cd', 0)],
                                    300)
        finally:
            type(synth).supportedCommands = kept
            _FakeDevice.block_ms = 10
        # Two words, one pause between them - not three or four pieces.
        self.assertEqual([loud for loud, _ms in runs], [True, False, True],
                         runs)
        self.assertTrue(250 <= runs[1][1] <= 420, runs)
        # And the second word is whole: 0.2 s of it, like the first.
        self.assertTrue(abs(runs[2][1] - runs[0][1]) <= 20, runs)

    def test_rapid_interruptions_never_hang_or_leak(self):
        """A key held down: every utterance interrupted by the next, a
        couple of hundred times. Each must give up within a tick of being
        told, nothing may be left playing, and no thread may be left
        behind."""
        import random
        from titan_access.nvda_host.shims import nvwave
        nvda_host.synth_instance('madeSynth')
        time.sleep(0.05)
        threads = threading.active_count()
        slowest = 0.0
        for at in range(200):
            told = [None]

            def cancelled():
                return told[0] is not None
            worker = threading.Thread(
                target=external.speak_parts,
                args=('nvda:madeSynth', [('abcdef', 0), ('xyz', -4)],
                      cancelled, 5.0, 120))
            worker.start()
            time.sleep(random.uniform(0, 0.03))
            told[0] = time.time()
            worker.join(2.0)
            self.assertFalse(worker.is_alive(), 'utterance %d hung' % at)
            slowest = max(slowest, time.time() - told[0])
        self.assertLess(slowest, 0.5)
        time.sleep(0.2)
        self.assertTrue(nvwave.drained())
        self.assertLessEqual(threading.active_count(), threads + 3)
        # And it still speaks to the end afterwards.
        took, runs = self._say('madeSynth', [('a', 0), ('b', 0)], 300)
        self.assertEqual([loud for loud, _ms in runs], [True, False, True],
                         runs)

    def test_the_padding_in_front_is_not_waited_through(self):
        from titan_access.nvda_host.shims import nvwave
        player = nvwave.WavePlayer(1, 16000, 16)
        nvwave.begin_utterance()
        player.feed(b'\x00\x00' * 4000 + b'\x00\x10' * 1600)
        with player._lock:
            self.assertLess(len(player._buffer), (1600 + 400) * 2)
        player.close()

    def test_a_voice_turned_right_down_is_never_cut(self):
        from titan_access.nvda_host.shims import nvwave
        player = nvwave.WavePlayer(1, 16000, 16)
        nvwave.begin_utterance()
        quiet = b'\x50\x00' * 16000                 # a whole second, faint
        player.pause(True)
        player.feed(quiet)
        with player._lock:
            kept = len(player._buffer)
        self.assertGreaterEqual(kept, len(quiet) - 400 * 32)
        self.assertEqual(player.trim_tail(), 0)
        player.close()


class AddOnsLikeCerenceRun(unittest.TestCase):
    """What Cerence and Samsung Galaxy Voices needed that NVDA has."""

    def test_the_chunk_separator_is_nvdas(self):
        from titan_access.nvda_host.shims import speech
        self.assertEqual(speech.CHUNK_SEPARATOR, '  ')

    def test_what_nvda_keeps_for_an_add_on_is_brought_and_never_over(self):
        nvda = tempfile.mkdtemp(prefix='ta_nvda_')
        os.makedirs(os.path.join(nvda, 'addons', 'demoAddon'))
        voices = os.path.join(nvda, 'demoAddon', 'voices', 'pl')
        os.makedirs(voices)
        with open(os.path.join(voices, 'model.bin'), 'w') as handle:
            handle.write('voice')
        with open(os.path.join(nvda, 'demoAddon', 'settings.json'),
                  'w') as handle:
            handle.write('nvda')
        with open(os.path.join(nvda, 'unrelated.txt'), 'w') as handle:
            handle.write('x')
        ours = os.path.join(nvda_host.config_folder(), 'demoAddon')
        os.makedirs(ours, exist_ok=True)
        with open(os.path.join(ours, 'settings.json'), 'w') as handle:
            handle.write('ours')
        keep = nvda_host.nvda_addons_folder
        nvda_host.nvda_addons_folder = lambda: os.path.join(nvda, 'addons')
        try:
            record = {'name': 'demoAddon', 'path': tempfile.mkdtemp()}
            nvda_host.bring_missing_data([record])
        finally:
            nvda_host.nvda_addons_folder = keep
        self.assertTrue(os.path.isfile(os.path.join(ours, 'voices', 'pl',
                                                    'model.bin')))
        with open(os.path.join(ours, 'settings.json')) as handle:
            self.assertEqual(handle.read(), 'ours')
        self.assertFalse(os.path.exists(os.path.join(
            nvda_host.config_folder(), 'unrelated.txt')))


if __name__ == '__main__':
    unittest.main()
