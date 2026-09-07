# -*- coding: utf-8 -*-
"""Putting NVDA's speech where Titan says the thing is.

Titan's interface is built to be heard: a control on the left of the window
sounds on the left, the far row of a board is quieter and lower. Crossing
into NVDA that used to collapse to a flat, centred string, because the
NVDA controller protocol carries text and nothing else.

**It does not have to.** ``nvwave.WavePlayer.setVolume(left=, right=)`` sets
the volume of one channel of one stream, and it lives BELOW the synthesizer:
espeak, oneCore and - in current NVDA - even SAPI 5 feed their audio into
that player rather than opening a device of their own, and a 32-bit driver
running in NVDA's synth host reaches the same call through
``_bridge.components.services.nvwave.WavePlayerService.setVolume``. So the
panning applies to whatever voice the user has actually chosen, and a Titan
voice is an option rather than the price of admission.

Three things about it are deliberate:

* **Constant power, not a linear split.** A sound crossing the middle of a
  linear pan is 3 dB quieter exactly as it passes, which is the moment it is
  closest. Titan has already paid for that once, in Cling, where a clay
  pigeon thrown across the listener dipped as it went by; the fix there was
  ``cos``/``sin`` of a quarter turn, and it is the fix here.
* **The pan is restored, always.** A stream left panned is an NVDA that
  speaks out of one ear for the rest of the session, which is a far worse
  failure than never panning at all. Every application schedules its own
  undoing, and terminating the add-on restores unconditionally.
* **A mono stream is reported, not faked.** ``setVolume`` cannot separate
  channels that are not there. When the player has one channel this says so
  (``last_problem()``), the announcement still carries its pitch and its
  panned earcon, and the position is honestly lost.
"""

import math
import threading

from . import compat

#: How long a pan may stand before it is put back by force. An utterance
#: that never reports its end - a synth with no index support, a cancelled
#: sequence - must not leave the stream lopsided for ever.
MAX_PAN_SECONDS = 12.0

_LOCK = threading.RLock()
_problem = ''


def last_problem():
    """Why the last attempt to place a sound did not fully work, or ''."""
    return _problem


def _note(reason):
    global _problem
    _problem = str(reason or '')
    return False


def constant_power(position):
    """``position`` -1 (left) .. 0 (centre) .. 1 (right) -> (left, right).

    ``left**2 + right**2`` is 1 wherever it is, so a sound that travels
    across the listener - or a menu whose items are spread from one side to
    the other - keeps the same loudness the whole way.
    """
    try:
        value = float(position)
    except (TypeError, ValueError):
        value = 0.0
    value = max(-1.0, min(1.0, value))
    angle = (value + 1.0) * (math.pi / 4.0)      # 0 .. pi/2
    return math.cos(angle), math.sin(angle)


# --------------------------------------------------------------------------- #
# Layer one: the synthesizer's own stream
# --------------------------------------------------------------------------- #
#: Where a driver keeps its player. NVDA has no single accessor for this, so
#: the names are tried in order and a driver that keeps its player somewhere
#: else simply falls through to the session layer.
_PLAYER_ATTRIBUTES = ('_player', 'player', '_wavePlayer', 'wavePlayer')


def player_of(synth):
    """The ``WavePlayer`` a synth driver feeds, or None."""
    if synth is None:
        return None
    for name in _PLAYER_ATTRIBUTES:
        player = getattr(synth, name, None)
        if player is not None and hasattr(player, 'setVolume'):
            return player
    # eSpeak keeps its player in the module that wraps the library rather
    # than on the driver object.
    if getattr(synth, 'name', '') == 'espeak':
        try:
            from synthDrivers import _espeak
        except Exception:                            # noqa: BLE001
            return None
        player = getattr(_espeak, 'player', None)
        if player is not None and hasattr(player, 'setVolume'):
            return player
    return None


def current_synth():
    if compat.synthDriverHandler is None:
        return None
    try:
        return compat.synthDriverHandler.getSynth()
    except Exception:                                # noqa: BLE001
        return None


def channels_of(player):
    """How many channels the stream has, or 0 when it will not say."""
    try:
        return int(getattr(player, 'channels', 0) or 0)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Layer two: NVDA's own audio session
# --------------------------------------------------------------------------- #
# This is the mechanism NVDA's own Sound Split uses, and it is the fallback
# rather than the first choice for one reason: it pans EVERYTHING NVDA is
# producing, including its own beeps and any wave file it happens to be
# playing, where the stream layer touches only the speech.
def _own_session():
    try:
        from pycaw.utils import AudioUtilities
    except Exception as error:                       # noqa: BLE001
        _note(f'pycaw is not available: {error}')
        return None
    try:
        import globalVars
        pid = int(getattr(globalVars, 'appPid', 0) or 0)
    except Exception:                                # noqa: BLE001
        import os
        pid = os.getpid()
    try:
        for session in AudioUtilities.GetAllSessions():
            if int(getattr(session, 'ProcessId', -1) or -1) == pid:
                return session
    except Exception as error:                       # noqa: BLE001
        _note(f'the audio sessions could not be read: {error}')
    return None


def _session_channel_volume(session):
    getter = getattr(session, 'channelAudioVolume', None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:                                # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# The panner
# --------------------------------------------------------------------------- #
class Panner:
    """Places NVDA's speech, and always puts it back.

    One instance is kept for the life of the add-on. It is not re-entrant by
    accident: a second ``place`` while one is standing simply moves the
    stream again, and the single ``restore`` at the end puts both back,
    because there is only ever one stream to put back.
    """

    def __init__(self):
        self._panned_player = None
        self._panned_session = None
        self._timer = None
        self._session_capable = None
        self._session_probing = False
        self.enabled = True

    # ------------------------------------------------------------- placing
    def place(self, position, prefer_session=False):
        """Pan the speech that is about to be produced. True when it took."""
        if not self.enabled:
            return False
        left, right = constant_power(position)
        if abs(left - right) < 1e-6:
            # Dead centre is what the stream is already, and setting it
            # anyway is a COM call per announcement for no change at all.
            self.restore()
            return True
        placed = False
        if not prefer_session:
            placed = self._place_stream(left, right)
        if not placed:
            placed = self._place_session(left, right)
        if placed:
            self._arm_restore()
        return placed

    def _place_stream(self, left, right):
        if not compat.can_pan_streams():
            return False
        player = player_of(current_synth())
        if player is None:
            return _note('this synthesizer does not feed a WavePlayer, so its '
                         'own stream cannot be panned')
        count = channels_of(player)
        if count == 1:
            return _note('this synthesizer produces one channel, so there is '
                         'no second channel to move the sound into')
        try:
            player.setVolume(left=left, right=right)
        except Exception as error:                   # noqa: BLE001
            return _note(f'the stream would not take a per-channel volume: '
                         f'{error}')
        with _LOCK:
            self._panned_player = player
        return True

    def _place_session(self, left, right):
        session = _own_session()
        if session is None:
            return False
        volume = _session_channel_volume(session)
        if volume is None:
            return _note("NVDA's audio session does not expose per-channel "
                         "volume")
        try:
            count = int(volume.GetChannelCount())
        except Exception as error:                   # noqa: BLE001
            return _note(f'the audio session would not say how many channels '
                         f'it has: {error}')
        if count != 2:
            return _note(f"NVDA's audio session has {count} channels instead "
                         f"of 2, so it cannot be panned")
        try:
            volume.SetChannelVolume(0, float(left), None)
            volume.SetChannelVolume(1, float(right), None)
        except Exception as error:                   # noqa: BLE001
            return _note(f'the audio session refused a channel volume: '
                         f'{error}')
        with _LOCK:
            self._panned_session = volume
        return True

    # ----------------------------------------------------------- restoring
    def _arm_restore(self):
        with _LOCK:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(MAX_PAN_SECONDS, self.restore)
            self._timer.daemon = True
            self._timer.start()

    def restore(self):
        """Put both channels back to full. Safe to call at any time."""
        with _LOCK:
            player = self._panned_player
            volume = self._panned_session
            timer = self._timer
            self._panned_player = None
            self._panned_session = None
            self._timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:                        # noqa: BLE001
                pass
        if player is not None:
            try:
                player.setVolume(all=1.0)
            except Exception:                        # noqa: BLE001
                pass
        if volume is not None:
            try:
                volume.SetChannelVolume(0, 1.0, None)
                volume.SetChannelVolume(1, 1.0, None)
            except Exception:                        # noqa: BLE001
                pass

    # ------------------------------------------------------------ reporting
    def can_place(self):
        """Whether the voice can be placed AT ALL, by either layer.

        This has to ask about both, and did not, which is the whole of "there
        is no positioned speech" on an ordinary machine. eSpeak - NVDA's
        default synthesizer - produces ONE channel, so there is no second
        channel to move the sound into and the stream layer cannot do it.
        The session layer can: it is NVDA's own audio session, the same
        mechanism NVDA's Sound Split uses, and it does not care how many
        channels the synth makes. `place()` has always fallen back to it.
        `report()` did not know it existed, so Titan was told the voice
        could not be placed, sent no position, and the fallback it was told
        about was never reached.
        """
        return bool(self._stream_can() or self._session_can())

    def _stream_can(self):
        player = player_of(current_synth())
        return bool(player is not None and channels_of(player) != 1
                    and compat.can_pan_streams())

    def _session_can(self):
        """Whether NVDA's own audio session has two channels to move between.

        **Never blocks, and that is not an optimisation.** Finding out is a
        COM walk of every audio session on the machine, and this is reached
        from `capabilities()` - the one call Titan makes to decide what it
        may send, with a two-and-a-half second patience and a twenty-second
        memory of the answer. A first call that took longer than that made
        Titan cache an EMPTY capability set: no position, no pitch, and
        nothing marked as replacing a focus report, so NVDA read every
        control and the add-on read it again on top. Everything twice, from
        one slow COM call inside a question that had to be instant.

        So the answer is whatever has been worked out already, and working
        it out happens on a thread of its own. Until it comes back the
        answer is "no", which costs a tone on the first control after
        NVDA starts and nothing else.
        """
        with _LOCK:
            cached = self._session_capable
            probing = self._session_probing
        if cached is not None:
            return cached
        if not probing:
            self.probe_session()
        return False

    def probe_session(self):
        """Work out whether the audio session can be panned, off the path."""
        with _LOCK:
            if self._session_probing or self._session_capable is not None:
                return
            self._session_probing = True

        def look():
            answer = False
            try:
                session = _own_session()
                if session is not None:
                    volume = _session_channel_volume(session)
                    if volume is not None:
                        answer = int(volume.GetChannelCount()) == 2
            except Exception as error:               # noqa: BLE001
                _note(f'the audio session would not say how many channels '
                      f'it has: {error}')
            with _LOCK:
                self._session_capable = answer
                self._session_probing = False
        threading.Thread(target=look, name='TitanPannerProbe',
                         daemon=True).start()

    def why_not(self):
        """Why the voice cannot be placed, in one sentence, before trying.

        `_note` only records a reason while something is being PLACED, so a
        machine that has never tried reported "cannot" with no reason at
        all - a feature quietly missing, which is the thing this add-on
        exists not to do.
        """
        if self.can_place():
            return ''
        recorded = last_problem()
        if recorded:
            return recorded
        synth = current_synth()
        player = player_of(synth)
        if not compat.can_pan_streams():
            stream = ('this NVDA cannot set the volume of one channel of a '
                      'stream')
        elif player is None:
            stream = ('this synthesizer does not feed a WavePlayer this '
                      'add-on can reach')
        elif channels_of(player) == 1:
            stream = ('this synthesizer produces one channel, so there is no '
                      'second channel to move the sound into')
        else:
            stream = 'the stream cannot be panned'
        return (stream + ", and NVDA's own audio session cannot be panned "
                "either")

    def report(self):
        """What panning this NVDA can actually do, in one dict."""
        synth = current_synth()
        player = player_of(synth)
        return {
            'synth': str(getattr(synth, 'name', '') or ''),
            'has_setVolume': compat.can_pan_streams(),
            'player': player is not None,
            'channels': channels_of(player),
            'stream_panning': self._stream_can(),
            'session_panning': self._session_can(),
            'can_place': self.can_place(),
            'problem': self.why_not(),
        }


#: The one panner. A second would fight the first over the same stream.
PANNER = Panner()
