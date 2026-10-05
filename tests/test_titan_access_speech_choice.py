# -*- coding: utf-8 -*-
"""Speech system, synthesizer and voice are ONE choice, offered the same way
everywhere: the speech system dialog (Insert+Ctrl+S), the settings page,
the walked settings (Insert+Ctrl+G), the settings ring and the TPad.

They used to be four different things: the dialog had three levels with
the NVDA add-on synthesizers; the page and the walk had Titan's flat
engine list and the voices of whatever engine was speaking; the TPad
cycled that flat list on the live engine without saving - which, with an
external synthesizer chosen, changed nothing at all.

A fixed set of systems, synthesizers and voices stands behind
`speech_systems` here, so what is checked is the plumbing, on any
machine. Run directly: ``python tests/test_titan_access_speech_choice.py``.
Nothing speaks, plays or opens a window; the store is a temporary one.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)
HOME = tempfile.mkdtemp(prefix='ta_speechchoice_')
os.environ['APPDATA'] = HOME

from titan_access import speech_systems                       # noqa: E402
from titan_access import settings_schema as schema            # noqa: E402
from titan_access import settings_walk                        # noqa: E402
from titan_access.settings_store import get_settings          # noqa: E402

SYSTEMS = [('titan', "Titan's own voice"), ('titantts', 'Titan TTS'),
           ('sapi5', 'SAPI 5'), ('nvda', 'NVDA add-ons')]
SYNTHS = {'titan': [('', 'Titan')],
          'titantts': [('eloquence', 'Eloquence'), ('dectalk', 'DECtalk')],
          'sapi5': [('sapi5', 'SAPI 5')],
          'nvda': [('nvda:CerenceTTS', 'Cerence'),
                   ('nvda:samsungGalaxyVoices', 'Samsung')]}
VOICES = {'eloquence': [('pl-1', 'Polish'), ('en-1', 'English')],
          'dectalk': [('paul', 'Paul')],
          'sapi5': [('Paulina', 'Paulina')],
          'nvda:CerenceTTS': [('Zosia', 'Zosia'), ('Ewa', 'Ewa')],
          'nvda:samsungGalaxyVoices': [('pl_PL_f00', 'Polish woman')]}


class Reader(object):
    """The running reader, as the choice is told to it."""

    def __init__(self):
        self.settings = get_settings()
        self.applied = 0
        self.said = []

    def apply_settings(self, reason=''):
        self.applied += 1
        self.settings = get_settings()

    def speak(self, text, interrupt=False, **_kwargs):
        self.said.append(str(text))

    def play(self, *_args, **_kwargs):
        pass


def _entry(kind):
    for _sid, _title, rows in settings_walk.SCHEMA:
        for row in rows:
            if row[3] == kind:
                return row
    raise AssertionError(kind)


class OneChoiceEverywhere(unittest.TestCase):

    def setUp(self):
        self.kept = (speech_systems.systems, speech_systems.synthesizers,
                     speech_systems._voices_now)
        speech_systems.systems = lambda engine=None: list(SYSTEMS)
        speech_systems.synthesizers = \
            lambda system, engine=None: list(SYNTHS.get(system, []))
        speech_systems._voices_now = \
            lambda synth, engine=None: list(VOICES.get(synth, []))
        speech_systems.forget_voices()
        settings_walk._scope['program'] = None
        self.reader = Reader()
        speech_systems.choose(self.reader.settings, 'titan', '', '', None)

    def tearDown(self):
        (speech_systems.systems, speech_systems.synthesizers,
         speech_systems._voices_now) = self.kept
        speech_systems.forget_voices()
        settings_walk._scope['program'] = None

    def _now(self):
        return speech_systems.current(get_settings())

    # -- the schema ------------------------------------------------------ #
    def test_the_three_levels_are_described_once(self):
        kinds = [entry.kind for entry in schema.entries()
                 if entry.kind in schema.SPEECH_LEVELS]
        self.assertEqual(kinds, list(schema.SPEECH_LEVELS))
        for kind in ('engines', ):
            self.assertNotIn(kind, [e.kind for e in schema.entries()])
        # The ring steps through all three, in the dialog's order.
        ring = [schema.find(*one).kind for one in schema.RING
                if schema.find(*one) is not None]
        found = [kind for kind in ring if kind in schema.SPEECH_LEVELS]
        self.assertEqual(found, list(schema.SPEECH_LEVELS))

    # -- the walked settings ----------------------------------------------- #
    def test_the_walk_offers_what_the_dialog_offers(self):
        system, synth, voice = (_entry(k) for k in schema.SPEECH_LEVELS)
        self.assertEqual(settings_walk._options(system),
                         speech_systems.systems())
        settings_walk.set_value(system, 'nvda', self.reader)
        self.assertEqual(self._now(), ('nvda', 'nvda:CerenceTTS', ''))
        self.assertEqual(settings_walk._options(synth), SYNTHS['nvda'])
        self.assertEqual(settings_walk._options(voice),
                         VOICES['nvda:CerenceTTS'])
        settings_walk.set_value(synth, 'nvda:samsungGalaxyVoices',
                                self.reader)
        # Opening the voice level lists them; one is picked from it.
        self.assertEqual(settings_walk._options(voice),
                         VOICES['nvda:samsungGalaxyVoices'])
        settings_walk.set_value(voice, 'pl_PL_f00', self.reader)
        self.assertEqual(self._now(), ('nvda', 'nvda:samsungGalaxyVoices',
                                       'pl_PL_f00'))
        self.assertEqual(settings_walk.value_word(
            voice, settings_walk.value_of(voice)), 'Polish woman')
        self.assertGreaterEqual(self.reader.applied, 3)

    def test_a_voice_is_named_without_waiting_for_the_synthesizer(self):
        voice = _entry('voices')
        speech_systems.choose(get_settings(), 'titantts', 'eloquence',
                              'pl-1', None)
        asked = []
        speech_systems._voices_now = \
            lambda synth, engine=None: asked.append(synth) or []
        speech_systems.forget_voices()
        # Not known yet: the id is said, and the list is read on a thread.
        self.assertEqual(settings_walk.value_word(voice, 'pl-1'), 'pl-1')

    def test_a_profile_takes_the_whole_choice(self):
        from titan_access import profiles
        synth = _entry('synthesizer')
        settings_walk._scope['program'] = 'game.exe'
        try:
            settings_walk.set_value(_entry('speech_system'), 'sapi5',
                                    self.reader)
            settings_walk.set_value(synth, 'sapi5', self.reader)
            self.assertEqual(profiles.get('game.exe', 'Speech', 'OwnVoice'),
                             'true')
            self.assertEqual(profiles.get('game.exe', 'Speech',
                                          'Synthesizer'), 'sapi5')
            self.assertEqual(settings_walk.value_of(synth), 'sapi5')
        finally:
            settings_walk._scope['program'] = None
            profiles.remove('game.exe')
        # The store itself was left alone.
        self.assertEqual(self._now()[0], 'titan')

    # -- the TPad ---------------------------------------------------------- #
    def test_the_tpad_moves_the_same_three_levels(self):
        from titan_access import dial
        manager = dial.DialManager(self.reader)
        for name in (dial.SPEECH_SYSTEM, dial.SYNTHESIZER, dial.VOICE):
            self.assertIn(name, manager._categories)
        manager._index = manager._categories.index(dial.SPEECH_SYSTEM)
        manager.handle_key('numpad2')                     # Titan TTS
        self.assertEqual(self._now(), ('titantts', 'eloquence', ''))
        self.assertEqual(self.reader.said[-1], 'Titan TTS')
        manager._index = manager._categories.index(dial.SYNTHESIZER)
        manager.handle_key('numpad2')
        self.assertEqual(self._now()[1], 'dectalk')
        manager._index = manager._categories.index(dial.VOICE)
        manager.handle_key('numpad2')
        self.assertEqual(self._now(), ('titantts', 'dectalk', 'paul'))
        self.assertEqual(self.reader.said[-1], 'Paul')
        # What the TPad chose is what the walked settings show.
        self.assertEqual(settings_walk.value_of(_entry('voices')), 'paul')
        self.assertGreaterEqual(self.reader.applied, 3)

    def test_the_tpad_reaches_external_synthesizers(self):
        from titan_access import dial
        manager = dial.DialManager(self.reader)
        manager._index = manager._categories.index(dial.SPEECH_SYSTEM)
        manager.handle_key('numpad8')                     # back: NVDA
        self.assertEqual(self._now()[:2], ('nvda', 'nvda:CerenceTTS'))

    def test_titans_own_voice_has_no_synthesizer_to_step(self):
        from titan_access import dial
        manager = dial.DialManager(self.reader)
        manager._index = manager._categories.index(dial.SYNTHESIZER)
        manager.handle_key('numpad2')
        self.assertEqual(self._now(), ('titan', '', ''))
        self.assertTrue(self.reader.said)

    # -- the settings page -------------------------------------------------- #
    def test_the_page_offers_and_writes_the_same(self):
        try:
            import wx
        except Exception:                            # noqa: BLE001
            self.skipTest('no wx')
        app = wx.GetApp() or wx.App(False)
        from titan_access import settings_panel
        frame = wx.Frame(None)
        try:
            panel = settings_panel.build_panel(frame, 'speech')
            self.assertEqual(
                [panel.cmb_system.GetString(i)
                 for i in range(panel.cmb_system.GetCount())],
                [label for _k, label in SYSTEMS])
            speech_systems.choose(get_settings(), 'nvda',
                                  'nvda:CerenceTTS', 'Ewa', None)
            settings_panel.load_panel(panel)
            self.assertEqual(settings_panel._chosen_system(panel), 'nvda')
            self.assertEqual(settings_panel._chosen_synth(panel),
                             'nvda:CerenceTTS')
            for _ in range(50):                      # the voices' worker
                app.Yield()
                if panel._voice_ids:
                    break
                import time
                time.sleep(0.02)
            self.assertEqual(panel._voice_ids, ['Zosia', 'Ewa'])
            self.assertEqual(panel.cmb_voice.GetStringSelection(), 'Ewa')
            panel.cmb_synth.SetSelection(1)
            settings_panel._fill_voices(panel, keep='')
            for _ in range(50):
                app.Yield()
                if panel._voice_ids == ['pl_PL_f00']:
                    break
                import time
                time.sleep(0.02)
            settings_panel.save_panel(panel)
            self.assertEqual(self._now(), ('nvda', 'nvda:samsungGalaxyVoices',
                                           'pl_PL_f00'))
            panel.Destroy()
        finally:
            frame.Destroy()


if __name__ == '__main__':
    unittest.main(verbosity=1)
