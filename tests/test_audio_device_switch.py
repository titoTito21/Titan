# -*- coding: utf-8 -*-
"""The sound follows the headphones.

Run it directly:  python tests/test_audio_device_switch.py

The bug these are about: plug headphones in, unplug them, plug them back in,
and Titan is silent. SDL opens one audio stream when Titan starts and keeps it
for the life of the process, so on Windows it belongs to whichever endpoint was
the default at that moment - Windows moving the default to the speakers and
back does not move an open stream, and `pygame.mixer.get_init()` still reports
an initialised mixer the whole time, which is why every "was the mixer torn
down" check in sound.py looked right and heard nothing.

Two halves, and both are tested here: audio_devices decides WHEN the sound has
to move (and, just as importantly, when it must NOT - re-opening the mixer cuts
whatever is being spoken), and sound.reopen_audio() moves it.

Nothing here plays a sound. The mixer is opened and closed, which is silent.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..')))

import pygame                                              # noqa: E402

from src.platform_utils import IS_WINDOWS                  # noqa: E402
from src.titan_core import audio_devices                   # noqa: E402
from src.titan_core import sound                           # noqa: E402
from src.titan_core import spatial_audio                   # noqa: E402


def tearDownModule():
    """Never leave a watcher thread registered with Windows behind."""
    audio_devices.stop(1.0)
    try:
        if pygame.mixer.get_init():
            pygame.mixer.quit()
    except Exception:
        pass


HEADPHONES = '{0.0.0.00000000}.{headphones}'
SPEAKERS = '{0.0.0.00000000}.{speakers}'
MONITOR = '{0.0.0.00000000}.{monitor}'


class WhenTheSoundHasToMove(unittest.TestCase):
    """audio_devices._is_change - the whole decision, in one function."""

    def test_the_default_endpoint_became_another_one(self):
        """Headphones unplugged: Windows moves the default to the speakers."""
        before = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS}))
        after = (SPEAKERS, frozenset({SPEAKERS}))
        self.assertTrue(audio_devices._is_change(before, after))

    def test_the_headphones_came_back(self):
        before = (SPEAKERS, frozenset({SPEAKERS}))
        after = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS}))
        self.assertTrue(audio_devices._is_change(before, after))

    def test_the_device_in_use_went_away_without_the_default_moving(self):
        """A jack that stops being active while Windows still names it."""
        before = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS}))
        after = (HEADPHONES, frozenset({SPEAKERS}))
        self.assertTrue(audio_devices._is_change(before, after))

    def test_every_playback_device_disappeared(self):
        before = (HEADPHONES, frozenset({HEADPHONES}))
        after = ('', frozenset())
        self.assertTrue(audio_devices._is_change(before, after))

    def test_another_device_appearing_is_not_about_us(self):
        """A monitor with speakers switched on must not cut off speech."""
        before = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS}))
        after = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS, MONITOR}))
        self.assertFalse(audio_devices._is_change(before, after))

    def test_a_device_we_never_used_disappearing_is_not_about_us_either(self):
        before = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS, MONITOR}))
        after = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS}))
        self.assertFalse(audio_devices._is_change(before, after))

    def test_nothing_at_all_changed(self):
        state = (HEADPHONES, frozenset({HEADPHONES, SPEAKERS}))
        self.assertFalse(audio_devices._is_change(state, state))

    def test_a_question_that_could_not_be_asked_is_not_a_change(self):
        """No pycaw, no COM, no hardware: silence is not news."""
        state = (HEADPHONES, frozenset({HEADPHONES}))
        self.assertFalse(audio_devices._is_change(None, state))
        self.assertFalse(audio_devices._is_change(state, None))
        self.assertFalse(audio_devices._is_change(None, None))


@unittest.skipUnless(IS_WINDOWS, "the endpoints are read through Windows")
class ReadingTheEndpoints(unittest.TestCase):

    def test_the_signature_is_the_default_and_the_active_set(self):
        signature = audio_devices._read_signature()
        if signature is None:
            self.skipTest("no pycaw / no audio hardware on this machine")
        default_id, active = signature
        self.assertIsInstance(default_id, str)
        self.assertIsInstance(active, frozenset)
        if default_id:
            self.assertIn(default_id, active,
                          "the default endpoint is not among the active ones")

    def test_reading_it_twice_in_a_row_says_nothing_changed(self):
        first = audio_devices._read_signature()
        second = audio_devices._read_signature()
        if first is None or second is None:
            self.skipTest("no pycaw / no audio hardware on this machine")
        self.assertFalse(audio_devices._is_change(first, second))

    def test_the_default_device_has_a_name(self):
        self.assertIsInstance(audio_devices.default_playback_name(), str)


@unittest.skipUnless(IS_WINDOWS, "there is nothing to watch elsewhere")
class TheWatcher(unittest.TestCase):

    def setUp(self):
        audio_devices.stop(1.0)
        self.calls = []

    def tearDown(self):
        audio_devices.stop(1.0)

    def test_it_starts_and_stops(self):
        started = audio_devices.start(self.calls.append)
        if not started:
            self.skipTest("pycaw not installed")
        self.assertTrue(audio_devices.is_watching())
        audio_devices.stop(2.0)
        self.assertFalse(audio_devices.is_watching())

    def test_windows_is_registered_to_tell_us(self):
        """The trap: importing comtypes puts the thread that does it into an
        STA, and a notification client registered in an STA is only called
        back from a message pump this thread has not got. If start() ever
        stops importing it on the CALLING thread, this is what notices."""
        if not audio_devices.start(self.calls.append):
            self.skipTest("pycaw not installed")
        for _ in range(20):
            if audio_devices._client is not None:
                break
            time.sleep(0.1)
        self.assertIsNotNone(audio_devices._client,
                             "Windows is not telling us about device changes; "
                             "only the poll is left")

    def test_starting_twice_is_one_thread(self):
        if not audio_devices.start(self.calls.append):
            self.skipTest("pycaw not installed")
        first = audio_devices._thread
        self.assertTrue(audio_devices.start(self.calls.append))
        self.assertIs(audio_devices._thread, first)

    def test_it_says_nothing_while_nothing_changes(self):
        """The expensive mistake: re-opening the mixer for no reason."""
        if not audio_devices.start(self.calls.append):
            self.skipTest("pycaw not installed")
        audio_devices.check_now()
        time.sleep(1.0)
        self.assertEqual(self.calls, [],
                         "the sound was moved though no device changed")

    def test_a_handler_that_raises_does_not_take_the_watcher_down(self):
        def explode(_device_id):
            raise RuntimeError("boom")

        if not audio_devices.start(explode):
            self.skipTest("pycaw not installed")
        # Force one delivery through the same path a real change takes.
        audio_devices._signature = ('{nothing like a real endpoint}',
                                    frozenset())
        audio_devices.check_now()
        time.sleep(1.5)
        self.assertTrue(audio_devices.is_watching(),
                        "the watcher died with the handler")


class MovingTheSound(unittest.TestCase):
    """sound.reopen_audio() - the mixer really is opened again."""

    @classmethod
    def setUpClass(cls):
        if not sound.initialize_sound():
            raise unittest.SkipTest("no audio device on this machine")

    def test_the_mixer_is_alive_afterwards(self):
        self.assertTrue(sound.reopen_audio(reason='test'))
        self.assertIsNotNone(pygame.mixer.get_init())
        self.assertTrue(sound._mixer_initialized)

    def test_the_format_is_the_one_it_had(self):
        """Re-opening must not quietly resample every voice from now on."""
        before = pygame.mixer.get_init()
        sound.reopen_audio(reason='test')
        self.assertEqual(pygame.mixer.get_init(), before)

    def test_the_dedicated_channels_come_back(self):
        sound.reopen_audio(reason='test')
        self.assertIsNotNone(sound.background_channel)
        self.assertIsNotNone(sound.voice_message_channel)
        self.assertIsNotNone(sound.ai_tts_channel)
        self.assertIsNotNone(sound.tts_speech_channel)
        self.assertGreaterEqual(pygame.mixer.get_num_channels(),
                                sound._TOTAL_CHANNELS)

    def test_speech_can_still_be_played(self):
        """get_tts_channel() is what every TTS engine reaches Titan through."""
        sound.reopen_audio(reason='test')
        channel = sound.get_tts_channel()
        self.assertIsNotNone(channel)
        self.assertFalse(channel.get_busy())

    def test_a_voice_message_is_not_left_believing_it_is_playing(self):
        sound.voice_message_playing = True
        sound.voice_message_paused = True
        sound.reopen_audio(reason='test')
        self.assertFalse(sound.voice_message_playing)
        self.assertFalse(sound.voice_message_paused)
        self.assertIsNone(sound.current_voice_message)

    def test_listeners_are_told(self):
        told = []
        sound.add_reopen_listener(lambda: told.append(True))
        try:
            sound.reopen_audio(reason='test')
        finally:
            sound._reopen_listeners.clear()
        self.assertEqual(len(told), 1)

    def test_a_listener_that_raises_does_not_stop_the_others(self):
        told = []

        def explode():
            raise RuntimeError("boom")

        sound.add_reopen_listener(explode)
        sound.add_reopen_listener(lambda: told.append(True))
        try:
            self.assertTrue(sound.reopen_audio(reason='test'))
        finally:
            sound._reopen_listeners.clear()
        self.assertEqual(len(told), 1)

    def test_the_same_listener_is_only_registered_once(self):
        told = []

        def listener():
            told.append(True)

        sound.add_reopen_listener(listener)
        sound.add_reopen_listener(listener)
        try:
            sound.reopen_audio(reason='test')
        finally:
            sound.remove_reopen_listener(listener)
        self.assertEqual(len(told), 1)

    def test_sound_can_be_played_after_the_move(self):
        """A real file, on a real channel - loaded, not heard: volume 0."""
        sound.reopen_audio(reason='test')
        path = os.path.join(os.path.dirname(__file__), '..', 'sfx', 'default',
                            'core', 'click.ogg')
        if not os.path.exists(path):
            self.skipTest("the default theme is not in this checkout")
        clip = pygame.mixer.Sound(path)
        self.assertGreater(clip.get_length(), 0.0)


class TheRaceWithSpeech(unittest.TestCase):
    """Re-opening the mixer is a moment with no mixer at all, and the TTS
    layer used to answer that moment by opening one of its own - one of them
    mono, at eSpeak's sample rate - which is what the whole program would have
    sounded like from then on."""

    @classmethod
    def setUpClass(cls):
        if not sound.initialize_sound():
            raise unittest.SkipTest("no audio device on this machine")

    def test_the_tts_layer_asks_titan_first(self):
        from src.titan_core import stereo_speech
        before = pygame.mixer.get_init()
        self.assertTrue(stereo_speech._ensure_mixer(frequency=16000,
                                                    channels=1, buffer=512))
        self.assertEqual(pygame.mixer.get_init(), before,
                         "speech re-opened the mixer in a format of its own")

    def test_it_opens_titans_format_when_there_is_no_mixer(self):
        from src.titan_core import stereo_speech
        pygame.mixer.quit()
        sound._mixer_initialized = False
        self.assertTrue(stereo_speech._ensure_mixer(frequency=16000,
                                                    channels=1, buffer=512))
        self.assertEqual(pygame.mixer.get_init(),
                         (sound._MIXER_FREQUENCY, sound._MIXER_SIZE,
                          sound._MIXER_CHANNELS))

    def test_no_playback_path_opens_the_mixer_behind_titans_back(self):
        """The trap for whoever adds the next engine."""
        source = open(os.path.join(os.path.dirname(__file__), '..', 'src',
                                   'titan_core', 'stereo_speech.py'),
                      encoding='utf-8').read()
        body = source.split('def _ensure_mixer', 1)[1]
        body = body.split('def _spatial_ok', 1)[1]
        self.assertNotIn('pygame.mixer.init()', body,
                         "a speech path opens the mixer itself again; use "
                         "_ensure_mixer() so it is Titan's format, on the "
                         "device the user is listening to")


class TheSpatialBackend(unittest.TestCase):
    """OpenAL binds to the default device the same way, and gets stuck the
    same way, so it is given up too."""

    def test_reopening_one_that_was_never_opened_does_nothing(self):
        tried = spatial_audio._init_tried
        try:
            spatial_audio._init_tried = False
            spatial_audio.reopen()          # must not raise
            self.assertFalse(spatial_audio._init_ok)
        finally:
            spatial_audio._init_tried = tried

    def test_reopening_makes_the_next_sound_open_the_device_again(self):
        tried, ok = spatial_audio._init_tried, spatial_audio._init_ok
        try:
            spatial_audio._init_tried = True
            spatial_audio._init_ok = False
            spatial_audio.reopen()
            self.assertFalse(spatial_audio._init_tried,
                             "the next sound would reuse the closed device")
            self.assertFalse(spatial_audio._reverb_loaded,
                             "the room calibration belongs to the old device")
        finally:
            spatial_audio._init_tried, spatial_audio._init_ok = tried, ok


class TheWiring(unittest.TestCase):
    """The trap for whoever changes this next."""

    def test_initialising_the_sound_starts_the_watch(self):
        source = open(os.path.join(os.path.dirname(__file__), '..', 'src',
                                   'titan_core', 'sound.py'),
                      encoding='utf-8').read()
        head = source.split('def _fire_haptics')[0]
        self.assertIn('follow_playback_device()', head,
                      "initialize_sound() no longer starts the device watch, "
                      "so Titan will not follow the headphones")

    def test_titan_stops_watching_before_it_quits_the_mixer(self):
        """gui.py exits with os._exit(), which runs no atexit handler."""
        source = open(os.path.join(os.path.dirname(__file__), '..', 'src',
                                   'ui', 'gui.py'), encoding='utf-8').read()
        self.assertIn('audio_devices.stop(', source)
        self.assertLess(source.index('audio_devices.stop('),
                        source.index('_pg_cleanup.mixer.quit()'),
                        "the watch must stop before the mixer does")

    def test_the_watch_is_windows_only(self):
        if IS_WINDOWS:
            self.skipTest("this machine is Windows")
        self.assertFalse(audio_devices.start(lambda _id: None))


if __name__ == '__main__':
    unittest.main(verbosity=2)
