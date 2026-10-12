# -*- coding: utf-8 -*-
"""eSpeak NG in Titan and in Titan Access: every voice offered loads, each
voice has an id of its own, Polish speaks Polish whoever set the library's
voice last, and a variant (espeak-ng-data/voices/!v) is chosen apart.

Run directly: python tests/test_espeak_voices.py. Nothing is played: the
library is asked to synthesize into memory.
"""

import os
import sys
import tempfile
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='titan_espeak_')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'titan access'))

from src.titan_core import stereo_speech  # noqa: E402

DLL = stereo_speech.get_espeak_dll()
HAVE = bool(DLL and DLL.initialized)


@unittest.skipUnless(HAVE, "no eSpeak NG library on this machine")
class TheLibraryListsOnlyVoicesThatLoad(unittest.TestCase):

    def test_every_voice_has_its_own_id_and_loads(self):
        voices = DLL.list_voices()
        ids = [one['id'] for one in voices]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)), "two voices share an id")
        for voice_id in ids:
            self.assertTrue(DLL.set_voice(voice_id), voice_id)

    def test_mbrola_voices_only_where_mbrola_is(self):
        mbrola = [one for one in DLL.list_voices()
                  if one['identifier'].startswith('mb/')]
        if not DLL.mbrola_available():
            self.assertEqual(mbrola, [])

    def test_polish_is_there_and_keeps_its_old_id(self):
        polish = [one for one in DLL.list_voices() if one['id'] == 'pl']
        self.assertEqual(len(polish), 1)
        self.assertIn('Polish', polish[0]['name'])

    def test_variants_are_listed_apart(self):
        variants = DLL.list_variants()
        self.assertTrue(variants)
        ids = [one['id'] for one in variants]
        self.assertEqual(len(ids), len(set(ids)))
        voice_ids = {one['id'] for one in DLL.list_voices()}
        self.assertFalse(voice_ids & set(ids))

    def test_the_variant_files_are_read_when_the_library_lists_none(self):
        on_disk = DLL._variants_on_disk()
        if DLL.data_path and os.path.isdir(
                os.path.join(DLL.data_path, 'voices', '!v')):
            self.assertTrue(on_disk)
            names = [name for name, _file, _g in on_disk]
            self.assertTrue(all(names))


@unittest.skipUnless(HAVE, "no eSpeak NG library on this machine")
class EachCallerSpeaksInItsOwnVoice(unittest.TestCase):

    TEXT = 'Zażółć gęślą jaźń'

    def _length(self, caller):
        audio = DLL.synthesize_to_memory(self.TEXT, caller=caller)
        self.assertIsNotNone(audio)
        return len(audio)

    def test_polish_stays_polish_after_another_voice_is_loaded(self):
        polish = {'voice': 'pl', 'rate': 175, 'pitch': 50, 'volume': 100}
        first = self._length(polish)
        DLL.set_voice('en')
        DLL.set_rate(10)
        again = self._length(polish)
        self.assertLess(abs(first - again), 40)

    def test_two_callers_differ(self):
        slow = self._length({'voice': 'pl', 'rate': 120})
        fast = self._length({'voice': 'pl', 'rate': 400})
        self.assertGreater(slow, fast * 1.5)

    def test_a_variant_speaks(self):
        variant = DLL.list_variants()[0]['id']
        audio = DLL.synthesize_to_memory(
            'kot', caller={'voice': 'pl+' + variant})
        self.assertIsNotNone(audio)

    def test_the_engine_hands_over_voice_and_variant(self):
        class Engine:
            espeak_voice = 'pl'
            espeak_variant = 'Annie'
            espeak_rate, espeak_pitch, espeak_volume = 175, 50, 100
            _espeak_voice_spec = stereo_speech.StereoSpeech._espeak_voice_spec
        caller = stereo_speech.StereoSpeech._espeak_caller(Engine())
        self.assertEqual(caller['voice'], 'pl+Annie')
        Engine.espeak_voice = 'pl+f1'
        caller = stereo_speech.StereoSpeech._espeak_caller(Engine())
        self.assertEqual(caller['voice'], 'pl+f1')


class TheReaderOffersVoiceAndVariant(unittest.TestCase):

    class Settings:
        def __init__(self, values):
            self.values = values

        def get(self, section, key, default=None):
            return self.values.get(key, default)

        def get_bool(self, section, key, default=False):
            return bool(self.values.get(key, default))

    def test_an_old_voice_with_a_variant_is_split(self):
        from titan_access import speech_systems
        st = self.Settings({'OwnVoice': True, 'Synthesizer': 'espeak_dll',
                            'Voice': 'pl+f1'})
        self.assertEqual(speech_systems.current(st), ('espeak', 'espeak_dll',
                                                      'pl'))
        self.assertEqual(speech_systems.current_variant(st), 'f1')

    @unittest.skipUnless(HAVE, "no eSpeak NG library on this machine")
    def test_the_voice_list_has_no_flattened_variants(self):
        from titan_access import speech_systems
        speech_systems.forget_voices()
        voices = speech_systems.voices('espeak')
        self.assertTrue(voices)
        self.assertFalse([key for key, _label in voices if '+' in key])
        self.assertIn('pl', [key for key, _label in voices])
        variants = speech_systems.variants('espeak', 'pl')
        self.assertEqual(variants[0][0], '')
        self.assertGreater(len(variants), 1)

    def test_a_voice_saved_by_its_language_is_found(self):
        from titan_access.speech_adapter import _voice_index

        class Engine:
            def get_available_voices(self):
                return [{'id': 'gmw/en', 'display_name': 'English',
                         'language': 'en-gb'},
                        {'id': 'pl', 'display_name': 'Polish',
                         'language': 'pl'}]
        self.assertEqual(_voice_index(Engine(), 'en-gb'), 0)
        self.assertEqual(_voice_index(Engine(), 'pl'), 1)
        self.assertIsNone(_voice_index(Engine(), 'zz'))

    def test_an_older_titan_has_the_voice_pinned(self):
        from titan_access.speech_adapter import _pin_espeak
        calls = []

        class Dll:
            voice, rate, pitch, volume = 'en', 175, 50, 100

            def set_voice(self, voice):
                calls.append(voice)
                self.voice = voice

            def _set_parameter(self, param, value):
                calls.append((param, value))

        class OldEngine:
            engine = 'espeak_dll'
            espeak_dll = Dll()
            espeak_voice = 'pl'
            espeak_rate, espeak_pitch, espeak_volume = 300, 50, 100
        _pin_espeak(OldEngine())
        self.assertEqual(calls, ['pl', (1, 300)])


class ESpeakIsInThePublishedUpdate(unittest.TestCase):

    def test_espeak_is_not_left_out(self):
        sys.path.insert(0, os.path.join(ROOT, 'src', 'scripts'))
        import pack_release
        source = tempfile.mkdtemp()
        engines = os.path.join(source, 'data', 'titantts engines')
        for name in ('espeak', 'eloquence', 'DECTalk'):
            os.makedirs(os.path.join(engines, name))
        out = pack_release.expand_excludes(source,
                                           pack_release.DEFAULT_EXCLUDES)
        self.assertIn('data/titantts engines/eloquence', out)
        self.assertIn('data/titantts engines/DECTalk', out)
        self.assertNotIn('data/titantts engines/espeak', out)
        self.assertNotIn('data/titantts engines', out)
        self.assertIn('data/components/titan access', out)


if __name__ == '__main__':
    unittest.main()
