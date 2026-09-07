# -*- coding: utf-8 -*-
"""Titan's own voices, as one more NVDA synthesizer.

Titan carries nine speech engines - Eloquence, DECtalk, BestSpeech, SMP,
Supertonic, Milena, ElevenLabs, eSpeak and SAPI 5 - behind one interface
that can render an utterance to memory rather than speak it
(``StereoSpeech._synthesize_segment``). This driver asks Titan for those
samples over the Action Bus and feeds them to NVDA's own ``WavePlayer``, so
they arrive through NVDA's audio device, NVDA's ducking and NVDA's volume,
and are cancelled by NVDA's own cancel.

**It is deliberately not the way positioned speech works.** Placing the
voice is done to whatever synthesizer the user already has, by setting the
per-channel volume of the stream underneath it; this driver is here so that
Titan's voices can be used everywhere in Windows, and as the guaranteed
fallback for a synthesizer whose own stream turns out to be mono and
therefore cannot be panned at all.

Two things about the design are worth knowing before changing it:

* **A turn is one request.** Titan renders the whole utterance and hands
  back the samples; nothing is streamed. That costs a round trip of latency
  per utterance and buys a driver with no state on Titan's side, which
  cannot be left half-speaking by a connection that drops.
* **The index is what makes say-all work.** NVDA marks points in the
  sequence with ``IndexCommand`` and expects to be told when speech reaches
  each one. So the sequence is cut at those marks, each piece is rendered
  and fed separately, and the index is reported as its piece begins to
  play. A driver that ignored them would speak perfectly and be unable to
  read a document.
"""

import threading
from collections import OrderedDict

from logHandler import log
from synthDriverHandler import (
    SynthDriver, VoiceInfo, synthDoneSpeaking, synthIndexReached,
)
import speech.commands as speechCommands

try:
    import nvwave
except Exception:                                    # noqa: BLE001
    nvwave = None


def _addon():
    """The add-on's own package, which owns the connection to Titan.

    Imported lazily and by name: a synth driver is imported by NVDA while it
    is enumerating what is installed, which can happen before the global
    plugin exists, and a driver that raised at import would take itself out
    of the list of synthesizers with no explanation anywhere the user looks.
    """
    from globalPlugins.titanEnhancements import link
    return link


#: Titan renders at whatever its engine produces; the driver resamples
#: nothing, so the format comes back with the samples.
DEFAULT_FORMAT = {'rate': 22050, 'channels': 1, 'width': 2}

#: A whole utterance has to be rendered before a sound is heard, so this is
#: the ceiling on how long a sentence may take before the driver gives up
#: and says nothing rather than speaking a minute late.
RENDER_TIMEOUT = 20.0


class _Piece:
    """One run of text between two index marks."""

    __slots__ = ('text', 'index', 'pitch', 'rate', 'volume', 'language')

    def __init__(self, text='', index=None, pitch=0, rate=0, volume=0,
                 language=''):
        self.text = text
        self.index = index
        self.pitch = pitch
        self.rate = rate
        self.volume = volume
        self.language = language


def split_sequence(sequence):
    """An NVDA speech sequence -> the pieces this driver renders.

    Prosody commands are folded into the piece they apply to rather than
    being sent as markup: Titan's renderer takes a pitch offset as a number
    on the same -10..10 scale NVDA's own offsets divide down to, so the
    conversion is arithmetic and not a second language to get wrong.
    """
    pieces = []
    pitch = rate = volume = 0
    language = ''
    pending_index = None
    text = []

    def flush():
        joined = ''.join(text).strip()
        if joined or pending_index is not None:
            pieces.append(_Piece(joined, pending_index, pitch, rate, volume,
                                 language))
        del text[:]

    for item in sequence:
        if isinstance(item, str):
            text.append(item)
            continue
        if isinstance(item, speechCommands.IndexCommand):
            flush()
            pending_index = item.index
            continue
        if isinstance(item, speechCommands.PitchCommand):
            flush()
            pending_index = None
            pitch = _to_titan(item)
            continue
        if isinstance(item, speechCommands.RateCommand):
            flush()
            pending_index = None
            rate = _to_titan(item)
            continue
        if isinstance(item, speechCommands.VolumeCommand):
            flush()
            pending_index = None
            volume = _to_titan(item)
            continue
        if isinstance(item, speechCommands.LangChangeCommand):
            flush()
            pending_index = None
            language = str(getattr(item, 'lang', '') or '')
            continue
        if isinstance(item, speechCommands.BreakCommand):
            text.append(' ')
            continue
        # Anything else - a callback, a beep, a wave file - is NVDA's own
        # and is handled by NVDA before it reaches a driver.
    flush()
    return [piece for piece in pieces
            if piece.text or piece.index is not None]


def _to_titan(command):
    """NVDA's offset on its 0..100 setting -> Titan's -10..10."""
    try:
        offset = int(getattr(command, 'offset', 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(-10, min(10, int(round(offset / 5.0))))


class SynthDriver(SynthDriver):
    name = 'titan'
    description = 'Titan'

    supportedSettings = (
        SynthDriver.VoiceSetting(),
        SynthDriver.RateSetting(),
        SynthDriver.PitchSetting(),
        SynthDriver.VolumeSetting(),
    )
    supportedCommands = {
        speechCommands.IndexCommand,
        speechCommands.PitchCommand,
        speechCommands.RateCommand,
        speechCommands.VolumeCommand,
        speechCommands.BreakCommand,
        speechCommands.LangChangeCommand,
    }
    supportedNotifications = {synthIndexReached, synthDoneSpeaking}

    @classmethod
    def check(cls):
        """Offer this synthesizer only when Titan can really be reached.

        A synthesizer in NVDA's list that cannot speak is worse than one
        that is absent: choosing it leaves the user with silence and no way
        back except the synthesizer ring.
        """
        try:
            from globalPlugins.titanEnhancements import titan_actions
            return bool(titan_actions._read_token())
        except Exception:                            # noqa: BLE001
            return False

    def __init__(self):
        super().__init__()
        self._voice = ''
        self._rate = 50
        self._pitch = 50
        self._volume = 100
        self._voices = None
        self._player = None
        self._queue = []
        self._queue_lock = threading.Condition()
        self._stop = threading.Event()
        self._generation = 0
        self._worker = threading.Thread(target=self._run, name='TitanSynth',
                                        daemon=True)
        self._worker.start()

    def terminate(self):
        self._stop.set()
        with self._queue_lock:
            self._queue = []
            self._queue_lock.notify_all()
        self._close_player()
        try:
            super().terminate()
        except Exception:                            # noqa: BLE001
            pass

    # ------------------------------------------------------------- speaking
    def speak(self, speechSequence):
        pieces = split_sequence(speechSequence)
        if not pieces:
            synthDoneSpeaking.notify(synth=self)
            return
        with self._queue_lock:
            self._queue.append((self._generation, pieces))
            self._queue_lock.notify_all()

    def cancel(self):
        """Stop now, and make sure nothing already queued speaks after it.

        The generation counter is what does the second half: a piece that
        was already being rendered when the cancel arrived comes back to a
        worker that can see it belongs to a turn nobody is listening to any
        more, and drops it instead of playing a sentence the user has
        already moved past.
        """
        with self._queue_lock:
            self._generation += 1
            self._queue = []
            self._queue_lock.notify_all()
        player = self._player
        if player is not None:
            try:
                player.stop()
            except Exception:                        # noqa: BLE001
                pass

    def pause(self, switch):
        player = self._player
        if player is None:
            return
        try:
            player.pause(bool(switch))
        except Exception:                            # noqa: BLE001
            pass

    # ------------------------------------------------------------- the work
    def _run(self):
        while not self._stop.is_set():
            with self._queue_lock:
                while not self._queue and not self._stop.is_set():
                    self._queue_lock.wait(0.25)
                if self._stop.is_set():
                    return
                generation, pieces = self._queue.pop(0)
            try:
                self._speak_pieces(generation, pieces)
            except Exception as error:               # noqa: BLE001
                log.error(f'Titan synthesizer: {error}')
            finally:
                if generation == self._generation:
                    synthDoneSpeaking.notify(synth=self)

    def _speak_pieces(self, generation, pieces):
        for piece in pieces:
            if generation != self._generation or self._stop.is_set():
                return
            if piece.index is not None:
                # Reported as the piece BEGINS, which is what NVDA's
                # cursor tracking and say-all are asking about.
                synthIndexReached.notify(synth=self, index=piece.index)
            if not piece.text:
                continue
            samples, audio_format = self._render(piece)
            if generation != self._generation or self._stop.is_set():
                return
            if not samples:
                continue
            self._feed(samples, audio_format)

    def _render(self, piece):
        link = _addon().LINK
        ok, data = link.bridge(
            'speech.render', timeout=RENDER_TIMEOUT,
            text=piece.text,
            engine=self._engine_of(self._voice),
            voice=self._voice_of(self._voice),
            pitch=piece.pitch + self._pitch_offset(),
            rate=piece.rate + self._rate_offset(),
            volume=piece.volume,
            language=piece.language)
        if not ok or not isinstance(data, dict):
            if ok is False:
                log.debugWarning(f'Titan would not render: {data}')
            return b'', DEFAULT_FORMAT
        import base64
        try:
            samples = base64.b64decode(data.get('pcm') or '')
        except Exception:                            # noqa: BLE001
            return b'', DEFAULT_FORMAT
        audio_format = {
            'rate': int(data.get('rate') or DEFAULT_FORMAT['rate']),
            'channels': int(data.get('channels') or DEFAULT_FORMAT['channels']),
            'width': int(data.get('width') or DEFAULT_FORMAT['width']),
        }
        return samples, audio_format

    # ----------------------------------------------------------- the player
    def _ensure_player(self, audio_format):
        """One player per format. Re-opened when Titan's engine changes.

        Opening a player per utterance is audible - the device is acquired
        and released around every sentence - so it is kept, and only a
        format that really differs is a reason to make a new one.
        """
        if nvwave is None:
            return None
        current = getattr(self, '_player_format', None)
        if self._player is not None and current == audio_format:
            return self._player
        self._close_player()
        try:
            self._player = nvwave.WavePlayer(
                channels=audio_format['channels'],
                samplesPerSec=audio_format['rate'],
                bitsPerSample=audio_format['width'] * 8,
                outputDevice=self._output_device())
            self._player_format = dict(audio_format)
        except Exception as error:                   # noqa: BLE001
            log.error(f'Titan synthesizer could not open the audio device: '
                      f'{error}')
            self._player = None
        return self._player

    def _output_device(self):
        try:
            import config
            return config.conf['audio']['outputDevice']
        except Exception:                            # noqa: BLE001
            return getattr(nvwave.WavePlayer, 'DEFAULT_DEVICE_KEY', None)

    def _close_player(self):
        player, self._player = self._player, None
        self._player_format = None
        if player is None:
            return
        try:
            player.close()
        except Exception:                            # noqa: BLE001
            pass

    def _feed(self, samples, audio_format):
        player = self._ensure_player(audio_format)
        if player is None:
            return
        try:
            player.feed(samples)
            player.idle()
        except Exception as error:                   # noqa: BLE001
            log.debugWarning(f'Titan synthesizer could not play: {error}')

    # ------------------------------------------------------------- settings
    def _pitch_offset(self):
        """NVDA's 0..100 pitch as Titan's -10..10 offset from the middle."""
        return int(round((self._pitch - 50) / 5.0))

    def _rate_offset(self):
        return int(round((self._rate - 50) / 5.0))

    @staticmethod
    def _engine_of(identifier):
        return str(identifier or '').split('|', 1)[0]

    @staticmethod
    def _voice_of(identifier):
        parts = str(identifier or '').split('|', 1)
        return parts[1] if len(parts) > 1 else ''

    def _getAvailableVoices(self):
        """Every engine Titan has, with every voice it offers.

        One NVDA "voice" is ``<engine>|<voice>``, because NVDA has one list
        and Titan has two levels. The engine's own name is kept in the
        displayed label so the user can tell an Eloquence voice from a SAPI
        one with the same name.
        """
        if self._voices is not None:
            return self._voices
        voices = OrderedDict()
        try:
            ok, data = _addon().LINK.bridge('speech.voices', timeout=15.0)
        except Exception:                            # noqa: BLE001
            ok, data = False, None
        if ok and isinstance(data, dict):
            for row in data.get('voices') or []:
                engine = str(row.get('engine') or '')
                voice = str(row.get('id') or '')
                if not engine:
                    continue
                identifier = f'{engine}|{voice}'
                label = str(row.get('label') or voice or engine)
                voices[identifier] = VoiceInfo(
                    identifier,
                    f'{label} ({engine})' if voice else engine,
                    str(row.get('language') or '') or None)
        if not voices:
            # A synthesizer with no voices at all cannot be selected, and
            # NVDA would fall back with no reason given. One honest entry
            # is better: it says what is wrong the moment it speaks.
            voices['titan|'] = VoiceInfo('titan|', 'Titan', None)
        self._voices = voices
        return voices

    def _get_voice(self):
        if not self._voice:
            self._voice = next(iter(self.availableVoices), '')
        return self._voice

    def _set_voice(self, value):
        self._voice = str(value or '')
        # The format usually changes with the engine, so the player is let
        # go rather than being handed samples it cannot play.
        self._close_player()

    def _get_rate(self):
        return self._rate

    def _set_rate(self, value):
        self._rate = max(0, min(100, int(value)))

    def _get_pitch(self):
        return self._pitch

    def _set_pitch(self, value):
        self._pitch = max(0, min(100, int(value)))

    def _get_volume(self):
        return self._volume

    def _set_volume(self, value):
        self._volume = max(0, min(100, int(value)))
