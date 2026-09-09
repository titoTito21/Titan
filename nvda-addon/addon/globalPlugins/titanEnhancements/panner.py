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


def screen_position(obj):
    """Where a control is across the screen, -1 (left) .. 1 (right).

    The one implementation of it. Titan Access places its focus cue by the
    middle of the control against the width of the screen
    (``a11y.screen_position`` / ``pan_for_x``), and this is the same
    arithmetic - so a control that sounds on the left under Titan's own
    reader sounds on the left under this one.

    **This is what makes positioned speech work at all on a machine where
    Titan sends no position.** Titan announces a position for the few
    things whose place it knows - a shell group, a board - and 0 for
    everything else, so a panner fed only by Titan's announcements had
    nothing to place: "positioned speech is on and nothing moves". The
    screen knows where every control is, and NVDA is the thing looking at
    the screen.

    ``None`` when it cannot be worked out, which is different from centre:
    a caller must not pan to the middle just because it could not ask.
    """
    if obj is None:
        return None
    try:
        location = obj.location
        left, _top, width, _height = (location.left, location.top,
                                      location.width, location.height) \
            if hasattr(location, 'left') else location
    except Exception:                                # noqa: BLE001
        return None
    try:
        width = float(width or 0)
        left = float(left)
    except (TypeError, ValueError):
        return None
    if width <= 0:
        return None
    screen = _screen_width()
    if not screen:
        return None
    centre = left + width / 2.0
    return max(-1.0, min(1.0, (centre / float(screen)) * 2.0 - 1.0))


#: A row of a list is not placed left and right - it is placed UP and DOWN.
#: Panning a list by where it happens to sit on the screen says the same
#: thing about every row in it, which is nothing; what a reader wants to
#: know from a row is how far down the list it is. Titan Access has always
#: said that with the TONE of the row's cue (`play_list_item`: 1.5 at the
#: top falling to 0.7 at the bottom), and this is the same idea applied to
#: the voice, in the add-on's own vocabulary: the same size of step it
#: already uses for the control type (-4) and the state (+4), so a list
#: does not suddenly speak in a range nothing else on this desktop uses.
LIST_PITCH_TOP = 4.0
LIST_PITCH_SPAN = 8.0

#: What counts as a row. NVDA's own role names, upper-cased - the same set
#: the cursor cues use, kept there because that is where it was first
#: written down.
def list_pitch(index, count):
    """The tone for a row: the top of the list high, the bottom low.

    ``0`` for anything that is not really a row in a list - a list of one,
    or a control whose place among its siblings NVDA will not say. A pitch
    of nought is the voice exactly as it was, which is the honest answer to
    "I do not know where this is".
    """
    try:
        index = int(index or 0)
        count = int(count or 0)
    except (TypeError, ValueError):
        return 0.0
    if count <= 1 or index <= 0:
        return 0.0
    where = max(0.0, min(1.0, (index - 1) / float(count - 1)))
    return LIST_PITCH_TOP - where * LIST_PITCH_SPAN


def _screen_width():
    """How wide the desktop is, asked once and remembered.

    It is read on the focus path, and `api.getDesktopObject().location` is
    a call into the accessibility tree for a number that changes when
    somebody plugs a monitor in and at no other time.
    """
    import time
    kept = _SCREEN['width']
    if kept and (time.time() - _SCREEN['at']) < SCREEN_SECONDS:
        return kept
    width = 0
    try:
        if compat.api is not None:
            desktop = compat.api.getDesktopObject()
            location = desktop.location if desktop is not None else None
            if location is not None:
                width = int(location[2] if not hasattr(location, 'width')
                            else location.width)
    except Exception:                                # noqa: BLE001
        width = 0
    if width <= 0:
        try:
            import ctypes
            width = int(ctypes.windll.user32.GetSystemMetrics(0))
        except Exception:                            # noqa: BLE001
            width = 0
    _SCREEN['width'] = width
    _SCREEN['at'] = time.time()
    return width


def _screen_height():
    """How tall the desktop is, asked once and remembered. See above."""
    import time
    kept = _SCREEN['height']
    if kept and (time.time() - _SCREEN['at']) < SCREEN_SECONDS:
        return kept
    height = 0
    try:
        if compat.api is not None:
            desktop = compat.api.getDesktopObject()
            location = desktop.location if desktop is not None else None
            if location is not None:
                height = int(location[3] if not hasattr(location, 'height')
                             else location.height)
    except Exception:                                # noqa: BLE001
        height = 0
    if height <= 0:
        try:
            import ctypes
            height = int(ctypes.windll.user32.GetSystemMetrics(1))
        except Exception:                            # noqa: BLE001
            height = 0
    _SCREEN['height'] = height
    return height


# --------------------------------------------------------------------------- #
# Which way a place is carried: across, or up and down
# --------------------------------------------------------------------------- #
#: **Panning is not reliable on every machine, and pitch is.**
#:
#: There are two layers under `place()` and only one of them is per
#: utterance. A synthesizer that feeds a stereo `WavePlayer` can have that
#: one stream's channels moved, and that is exact. Everything else - which
#: includes eSpeak, NVDA's own default and a MONO synthesizer - falls
#: through to NVDA's whole audio SESSION, and a session is not an
#: utterance: it is put back on a timer, so a line longer than
#: `MAX_PAN_SECONDS` snaps back in the middle of itself, a restore can land
#: inside the next line, and everything NVDA says while it stands is moved
#: whether or not it was ever meant to be. That is what "it is not smooth,
#: it cuts sometimes" is, and no amount of care in this module fixes it:
#: the mechanism is the wrong shape for the job on that machine.
#:
#: A PITCH is the right shape. `PitchCommand` belongs to the utterance it is
#: in, it is put back at the end of the part that used it, nothing is armed
#: on a timer, and every synthesizer that declares it takes it. This add-on
#: already carries a place that way where panning could never have worked -
#: a ROW is said high at the top of a list and low at the bottom - so this
#: is that same answer offered for a control's place on the screen.
#:
#: Three answers, and the user's own: 'pitch' (the default), 'pan', 'both'.
POSITION_PITCH = 'pitch'
POSITION_PAN = 'pan'
POSITION_BOTH = 'both'
POSITION_WAYS = (POSITION_PITCH, POSITION_PAN, POSITION_BOTH)


def position_way():
    """How the user has asked for a place to be carried."""
    try:
        from . import configSpec
        answer = str(configSpec.read().get('positionAs') or '').strip()
    except Exception:                                # noqa: BLE001
        answer = ''
    return answer if answer in POSITION_WAYS else POSITION_PITCH


def may_pan():
    return position_way() in (POSITION_PAN, POSITION_BOTH)


def may_pitch():
    return position_way() in (POSITION_PITCH, POSITION_BOTH)


def screen_pitch(obj):
    """Where a control is DOWN the screen, as a pitch. High at the top.

    The vertical axis on purpose. A pitch that rose and fell with the
    control's place across the screen would be an arbitrary code the user
    has to learn; high at the top and low at the bottom is the one mapping
    everybody already has, it is the same direction this add-on already
    uses for a row's place in a list, and it is Titan Access's own.

    The range is `list_pitch`'s, so a control and a row speak in the same
    vocabulary rather than a screen suddenly using a span nothing else on
    this desktop uses. ``0.0`` when it cannot be worked out, which is the
    voice exactly as it was - the honest answer to "I do not know".
    """
    if obj is None:
        return 0.0
    try:
        location = obj.location
        top, height = (location.top, location.height) \
            if hasattr(location, 'top') else (location[1], location[3])
        top = float(top)
        height = float(height or 0)
    except Exception:                                # noqa: BLE001
        return 0.0
    screen = _screen_height()
    if not screen:
        return 0.0
    centre = top + height / 2.0
    where = max(0.0, min(1.0, centre / float(screen)))
    return LIST_PITCH_TOP - where * LIST_PITCH_SPAN


def pitch_for_position(position):
    """A place given as a pan, -1 .. 1, carried as a pitch instead.

    For a caller that has only ever had the one number - Titan announces a
    position for the few things whose place it knows, and it is a place
    ACROSS. Reading order is what settles the direction: first is high and
    last is low, exactly as a list is, so the two cannot disagree.
    """
    try:
        value = max(-1.0, min(1.0, float(position)))
    except (TypeError, ValueError):
        return 0.0
    return LIST_PITCH_TOP - ((value + 1.0) / 2.0) * LIST_PITCH_SPAN


#: The desktop's width, and how long it may be believed.
_SCREEN = {'width': 0, 'height': 0, 'at': 0.0}
SCREEN_SECONDS = 30.0


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
        #: NVDA's own audio session's per-channel volume, found once. See
        #: `_place_session` for why this must not be looked up per
        #: utterance.
        self._volume = None
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
        """Move NVDA's own audio session. **Found once, not per utterance.**

        `_own_session()` is `AudioUtilities.GetAllSessions()` - a COM walk
        of every audio session on the machine - and this is reached from a
        `CallbackCommand`, which runs on NVDA's MAIN thread at the moment
        speech reaches that point. Doing the walk there is a COM
        enumeration per spoken control, and on the default synthesizer
        (eSpeak is mono, so the stream layer always declines) that is every
        placed utterance there is. Measured as NVDA's own watchdog
        reporting freezes; it had never shown up before because nothing
        was asking for a position at all.

        The interface is the same one for the life of NVDA's audio session,
        so it is kept. A call that fails throws it away and asks again -
        the device can change under it, which is exactly what happens when
        the user moves the headphones.
        """
        volume = self._session_volume()
        if volume is None:
            return False
        try:
            volume.SetChannelVolume(0, float(left), None)
            volume.SetChannelVolume(1, float(right), None)
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                self._volume = None
                self._session_capable = None
            return _note(f'the audio session refused a channel volume: '
                         f'{error}')
        with _LOCK:
            self._panned_session = volume
        return True

    def _session_volume(self):
        """The per-channel volume of NVDA's own audio session, or None."""
        with _LOCK:
            kept = self._volume
        if kept is not None:
            return kept
        session = _own_session()
        if session is None:
            return None
        volume = _session_channel_volume(session)
        if volume is None:
            _note("NVDA's audio session does not expose per-channel volume")
            return None
        try:
            count = int(volume.GetChannelCount())
        except Exception as error:                   # noqa: BLE001
            _note(f'the audio session would not say how many channels it '
                  f'has: {error}')
            return None
        if count != 2:
            _note(f"NVDA's audio session has {count} channels instead of 2, "
                  f"so it cannot be panned")
            return None
        with _LOCK:
            self._volume = volume
        return volume

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
                # The device has gone - the headphones were unplugged
                # mid-utterance. Ask for it again next time rather than
                # holding an interface that answers nothing.
                with _LOCK:
                    self._volume = None
                    self._session_capable = None

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
            found = None
            try:
                session = _own_session()
                if session is not None:
                    volume = _session_channel_volume(session)
                    if volume is not None:
                        answer = int(volume.GetChannelCount()) == 2
                        if answer:
                            found = volume
            except Exception as error:               # noqa: BLE001
                _note(f'the audio session would not say how many channels '
                      f'it has: {error}')
            with _LOCK:
                self._session_capable = answer
                # The probe already did the walk; throwing away what it
                # found meant the first placed utterance did it again, on
                # the main thread.
                if found is not None:
                    self._volume = found
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
