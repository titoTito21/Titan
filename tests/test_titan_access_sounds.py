# -*- coding: utf-8 -*-
"""The synthesised sounds: the progress bar's rising beep and the tone a
walked list plays per row - generated, played, and NVDA's curves.

`tones.beep` from the shared modules used to look for `play_tone` on the
`sound_manager` MODULE (it is a method of the engine's manager) and
answered False for ever: every row tone of the palette, a message and the
virtual window was silent in Titan Access. The live part here drives a
REAL `wx.Gauge` in this process from 0 to 100 under the real engine and
asserts the beeps rose and travelled left to right and the value was
spoken every ten percent - the test the user asked for in as many words.

Run directly: ``python tests/test_titan_access_sounds.py``.
"""

import os
import sys
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN, os.path.join(COMPONENT, 'lib')):
    if path not in sys.path:
        sys.path.insert(0, path)

IS_WINDOWS = sys.platform.startswith('win')

# **Never the user's own stores.** The real engine reads and WRITES
# `%APPDATA%/titosoft/Titan`; a test that ran on it once flipped a setting
# the user then reported as a regression, and one that READS it depends on
# whatever scheme they chose a minute ago. A fresh folder: the defaults.
import tempfile as _tempfile
os.environ['APPDATA'] = _tempfile.mkdtemp(prefix='titan_access_test_')


class TheCurvesAreNvdas(unittest.TestCase):

    def test_the_progress_tone_is_110_hz_doubling_every_25_percent(self):
        from titan_access import progress_monitor as pm
        self.assertAlmostEqual(pm.tone_for_percent(0), 110.0)
        self.assertAlmostEqual(pm.tone_for_percent(25), 220.0)
        self.assertAlmostEqual(pm.tone_for_percent(50), 440.0)
        self.assertAlmostEqual(pm.tone_for_percent(100), 1760.0)
        self.assertEqual(pm.pan_for_percent(0), -1.0)
        self.assertEqual(pm.pan_for_percent(50), 0.0)
        self.assertEqual(pm.pan_for_percent(100), 1.0)

    def test_a_row_tone_is_high_at_the_top_and_low_at_the_bottom(self):
        from titan_access.portable import palette, compat
        heard = []
        old = compat.tones.beep
        compat.tones.beep = lambda hz, ms, left=50, right=50: heard.append(hz) or True
        try:
            palette._beep(0, 10)
            palette._beep(9, 10)
            palette._beep(5, 10)
        finally:
            compat.tones.beep = old
        self.assertEqual(heard[0], 1650)
        self.assertEqual(heard[1], 420)
        self.assertTrue(heard[0] > heard[2] > heard[1])


class TheToneShimReachesTheMixer(unittest.TestCase):

    def test_it_plays_through_the_engines_manager_with_a_pan(self):
        from titan_access.portable import compat
        from titan_access import engine as engine_module

        class Manager:
            played = []

            def play_tone(self, hz, ms, pan=0.0, gain=0.5):
                self.played.append((hz, ms, pan, gain))

        fake = type('E', (), {})()
        fake.sound = Manager()
        old = engine_module.TitanAccessEngine.instance
        engine_module.TitanAccessEngine.instance = fake
        try:
            self.assertTrue(compat.tones.beep(880, 30))
            self.assertTrue(compat.tones.beep(440, 30, left=100, right=0))
            self.assertTrue(compat.tones.beep(440, 30, left=0, right=100))
        finally:
            engine_module.TitanAccessEngine.instance = old
        self.assertEqual(Manager.played[0][:2], (880.0, 30))
        self.assertEqual(Manager.played[0][2], 0.0)
        self.assertEqual(Manager.played[1][2], -1.0)
        self.assertEqual(Manager.played[2][2], 1.0)

    def test_the_old_shape_would_have_found_nothing(self):
        from titan_access import sound_manager
        self.assertFalse(callable(getattr(sound_manager, 'play_tone', None)))
        self.assertTrue(callable(sound_manager.SoundManager.play_tone))


@unittest.skipUnless(IS_WINDOWS, 'a real mixer and a real gauge')
class TheTonesAreGeneratedAndPlayed(unittest.TestCase):

    def test_a_tone_is_a_sound_of_its_length_on_a_busy_channel(self):
        from titan_access.sound_manager import SoundManager
        manager = SoundManager(os.path.join(COMPONENT, 'sfx'))
        sound = manager._tone_sound(440.0, 40, 0.3)
        self.assertIsNotNone(sound)
        self.assertAlmostEqual(sound.get_length(), 0.04, places=2)
        manager.play_tone(440.0, 40, pan=0.0, gain=0.3)
        time.sleep(0.005)
        self.assertTrue(any(c.get_busy() for c in manager._active_channels))
        time.sleep(0.1)


class _Recorder:
    supports_pitch = True

    def __init__(self, settings=None):
        pass

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0, voice=None):
        SAID.append(str(text))

    speak_async = speak

    def speak_segments(self, segments, gap_ms=0):
        SAID.append(' | '.join(str(s[0]) for s in segments))

    def stop(self):
        pass

    is_speaking = False

    def apply_settings(self):
        pass

    def set_rate(self, *a):
        pass

    def current_rate(self):
        return 0

    def set_volume(self, *a):
        pass

    def set_pitch(self, *a):
        pass

    def set_engine(self, *a):
        pass

    def set_voice(self, *a):
        pass

    def get_voices(self):
        return []

    def get_engines(self):
        return []

    def wait_until_done(self, *a, **k):
        return True

    def wait_for_queue(self, *a, **k):
        return True

    def pending_count(self):
        return 0


SAID = []


@unittest.skipUnless(IS_WINDOWS, 'the real engine and a real wx.Gauge')
class AProgressBarIsHeardRising(unittest.TestCase):
    """The real engine, a real gauge, 0 to 100: the beeps rise and travel
    from left to right, the value is spoken every ten percent."""

    def test_a_gauge_from_0_to_100(self):
        import wx
        import titan_access.keyboard_hook as hook
        import titan_access.speech_adapter as speech
        old_hook, old_speech = hook.KeyboardHook.start, speech.SpeechAdapter
        hook.KeyboardHook.start = lambda self: self
        speech.SpeechAdapter = _Recorder
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None, title='Pasek postępu (test)')
        panel = wx.Panel(frame)
        gauge = wx.Gauge(panel, range=100, size=(300, 24))
        gauge.SetName('Postęp')
        frame.SetSize((400, 120))
        frame.Show()
        from titan_access.engine import TitanAccessEngine
        from titan_access import progress_monitor as pm
        engine = TitanAccessEngine()
        beeps = []
        problems = []

        def driver():
            try:
                engine.start()
                time.sleep(1.5)
                sound = engine.sound
                real = sound.play_tone

                def recording(frequency=880.0, duration_ms=25, pan=0.0, gain=0.5):
                    beeps.append((round(float(frequency), 1), round(float(pan), 2)))
                    return real(frequency, duration_ms, pan=pan, gain=gain)
                sound.play_tone = recording
                engine._compute_is_tce_foreground = lambda: True
                engine._tce_fg_cache = None
                import uiautomation as auto
                control = auto.ControlFromHandle(int(gauge.GetHandle()))
                obj = engine.provider.element_to_object(control)
                if obj is None or obj.role != 'progressbar':
                    problems.append('the gauge is not a progress bar to UIA: %r'
                                    % (getattr(obj, 'role', None),))
                    return
                engine.progress.on_focus(obj)
                for value in range(0, 101, 5):
                    wx.CallAfter(gauge.SetValue, value)
                    time.sleep(pm._TICK_S * 2.5)
                time.sleep(0.6)
                if len(beeps) < 10:
                    problems.append('too few beeps: %r' % (beeps,))
                    return
                hzs = [hz for hz, _pan in beeps]
                pans = [pan for _hz, pan in beeps]
                if not all(b >= a for a, b in zip(hzs, hzs[1:])):
                    problems.append('the beeps did not rise: %r' % (hzs,))
                if not (pans[0] <= -0.8 and pans[-1] >= 0.8):
                    problems.append('the beeps did not travel left to right: %r' % (pans,))
                if hzs[0] > 130 or hzs[-1] < 1500:
                    problems.append('the curve is not 110 to 1760 Hz: %r' % (hzs,))
                # The monitor's own words, not a status bar that happens to
                # carry a percent sign: "{n} procent" / "{n} percent", and
                # "gotowe" / "complete" at the end.
                from titan_access.localization import L
                word = L('progress.percent', 10).replace('10', '').strip()
                spoken = [s for s in SAID if s.strip().endswith(word)
                          and s.strip()[:-len(word)].strip().isdigit()]
                if len(spoken) < 5:
                    problems.append('the value was not spoken every ten percent: %r'
                                    % (SAID,))
                if L('progress.complete') not in SAID:
                    problems.append('the end was not said: %r' % (SAID,))
            except Exception as error:               # noqa: BLE001
                import traceback
                problems.append('driver raised: %s\n%s' % (error, traceback.format_exc()))
            finally:
                try:
                    engine.stop()
                finally:
                    wx.CallAfter(frame.Destroy)
                    wx.CallAfter(app.ExitMainLoop)
        thread = threading.Thread(target=driver, daemon=True)
        thread.start()
        try:
            app.MainLoop()
        finally:
            hook.KeyboardHook.start = old_hook
            speech.SpeechAdapter = old_speech
        thread.join(timeout=10.0)
        self.assertEqual(problems, [])
        print('beeps:', beeps[:3], '...', beeps[-2:], 'spoken:',
              [s for s in SAID if 'procent' in s or 'percent' in s or s in ('gotowe', 'complete')][:12],
              flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=1)
