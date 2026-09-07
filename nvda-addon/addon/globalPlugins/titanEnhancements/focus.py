# -*- coding: utf-8 -*-
"""Not saying the same thing twice, and knowing when to say nothing at all.

Two different silences live here.

**The first is one focus event.** Titan composes announcements NVDA cannot
compose - "Applications, 1 of 4, tab" for a row whose text is just
"Applications", the name of the shell group the keyboard has entered, the
count of search results. Titan announces, and then moves the focus; NVDA
then reads the object, and the user hears the same thing twice with the
second copy worse than the first. Titan's own answer until now was to stay
silent whenever the reader was not Titan Access, which loses the extra
information rather than the duplicate. So an announcement may carry
``replaces_focus``, and the very next focus event inside Titan's own process
is **read with speech muted**.

Muted rather than skipped, and that is the whole care in this module: NVDA's
``event_gainFocus`` does more than speak - it moves the review cursor,
updates braille, and lets the object cache itself - and a global plugin that
simply does not call ``nextHandler`` throws all of that away to stop one
sentence. Speech mode goes off for the length of the call and back
immediately after, so everything except the duplicate still happens.

**The second is the whole add-on.** If Titan Access is the reader, Titan is
already speaking through its own engine, and NVDA speaking as well is two
readers over each other. Titan says so (``stand_down``) and everything here
answers no until it says otherwise.
"""

import threading
import time

from . import compat

_LOCK = threading.RLock()
_replace_until = 0.0
_standing_down = False
_titan_pid = 0
_suppressed = 0
_titan_spoke = 0.0


# --------------------------------------------------------------------------- #
# Standing down for Titan Access
# --------------------------------------------------------------------------- #
def stand_down(down=True):
    global _standing_down
    with _LOCK:
        _standing_down = bool(down)
    return _standing_down


def standing_down():
    with _LOCK:
        return _standing_down


# --------------------------------------------------------------------------- #
# Whose window this is
# --------------------------------------------------------------------------- #
def set_titan_pid(pid):
    """Titan's own process id, told to us by Titan over the bus.

    **Matched by process, never by executable name.** Titan run from source
    is ``python.exe``, and an add-on that recognised Titan by that name
    would take over the focus reporting of every Python script on the
    machine.
    """
    global _titan_pid
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        value = 0
    with _LOCK:
        _titan_pid = value
    return value


def titan_pid():
    with _LOCK:
        return _titan_pid


def is_titan_object(obj):
    """Whether this NVDA object belongs to the Titan we are connected to."""
    pid = titan_pid()
    if not pid or obj is None:
        return False
    try:
        return int(getattr(obj, 'processID', 0) or 0) == pid
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# The one-event mark
# --------------------------------------------------------------------------- #
def replace_next(until):
    """Titan has just said what the next focus event would have said."""
    global _replace_until
    with _LOCK:
        _replace_until = float(until)


def take_mark():
    """Consume the mark. True at most once, and only while it is fresh."""
    global _replace_until
    with _LOCK:
        if _replace_until and time.time() <= _replace_until:
            _replace_until = 0.0
            return True
        _replace_until = 0.0
        return False


def suppressed():
    return _suppressed


# --------------------------------------------------------------------------- #
# Whether Titan is coordinating with us at all
# --------------------------------------------------------------------------- #
def note_titan_spoke():
    """Titan has announced something through this channel."""
    global _titan_spoke
    with _LOCK:
        _titan_spoke = time.time()


def spoke_at():
    with _LOCK:
        return _titan_spoke


def titan_coordinates():
    """Whether Titan is announcing THROUGH US rather than past us.

    This decides whether the add-on may stand in for NVDA's own report of a
    control, and the reason it has to be asked is a regression this add-on
    caused: reading every control in Titan in three tones also replaced the
    tab bar's report - and what made that row a TAB BAR was said by Titan,
    through `accessible_output3`, which this add-on never sees. The user
    heard the tab bar announcement disappear.

    A Titan whose `messages.py` predates the reader channel announces that
    way and never calls in here at all, so "has Titan ever announced
    through this channel" tells the two apart exactly. Until it has, NVDA's
    own reporting is left alone: taking it over to add three tones, and
    losing a sentence in the process, is not a trade worth making.
    """
    with _LOCK:
        return bool(_titan_spoke)


# --------------------------------------------------------------------------- #
# Muting, across NVDA's two spellings of it
# --------------------------------------------------------------------------- #
def _get_mode():
    speech = compat.speech
    if speech is None:
        return None, None
    state = getattr(speech, 'getState', None)
    if callable(state):
        try:
            return 'state', state().speechMode
        except Exception:                            # noqa: BLE001
            pass
    mode = getattr(speech, 'speechMode', None)
    if mode is not None:
        return 'attribute', mode
    return None, None


def _set_mode(kind, value):
    speech = compat.speech
    if speech is None or kind is None:
        return
    if kind == 'state':
        setter = getattr(speech, 'setSpeechMode', None)
        if callable(setter):
            try:
                setter(value)
            except Exception:                        # noqa: BLE001
                pass
        return
    try:
        speech.speechMode = value
    except Exception:                                # noqa: BLE001
        pass


def _off_value(kind):
    speech = compat.speech
    if speech is None:
        return None
    if kind == 'state':
        mode = getattr(speech, 'SpeechMode', None)
        return getattr(mode, 'off', None) if mode is not None else None
    return getattr(speech, 'speechMode_off', None)


def can_mute():
    """Whether this NVDA's speech can really be turned off and back.

    Asked, not assumed. A mute that quietly does nothing is the worst
    possible outcome for anything that stands in for NVDA's own report:
    NVDA reads the control, we read it again, and the user hears everything
    twice with no clue why.
    """
    kind, _previous = _get_mode()
    return kind is not None and _off_value(kind) is not None


class muted:
    """Speech off for the length of a ``with`` block, then back as it was.

    Restoring what was THERE rather than setting 'talk' is the point: a user
    who has NVDA in beeps mode, or has muted speech deliberately, must not
    have it turned on again by a Titan announcement.

    ``worked`` says whether it really happened, because a caller that was
    going to speak in NVDA's place needs to know that NVDA has been kept
    quiet before it does.
    """

    def __init__(self):
        self._kind = None
        self._previous = None
        self.worked = False

    def __enter__(self):
        kind, previous = _get_mode()
        off = _off_value(kind)
        if kind is None or off is None:
            return self
        self._kind, self._previous = kind, previous
        _set_mode(kind, off)
        self.worked = True
        return self

    def __exit__(self, *_exception):
        if self._kind is not None:
            _set_mode(self._kind, self._previous)
        self._kind = None
        return False


#: How many focus reports were read in Titan Access's three tones instead
#: of NVDA's one. Shown by the status command, because "it is not doing it"
#: and "it is doing it and you cannot hear the difference" are different
#: problems.
_pitched = 0


def pitched():
    return _pitched


def handle_gain_focus(obj, next_handler):
    """The global plugin's ``event_gainFocus``, factored out to be testable.

    Three outcomes, and the order matters.

    1. Titan has just SAID what this event would say (``replaces_focus``):
       the report is muted and nothing replaces it.
    2. Otherwise, inside Titan's own windows, the control is read the way
       Titan's own reader reads one - the name, then the type lower, then
       the state higher, in one utterance. NVDA's own report is muted and
       ours takes its place.
    3. Everywhere else NVDA is the reader and is left entirely alone. That
       line is deliberate: NVDA's reporting outside Titan knows about
       tables, landmarks, browse mode and a hundred things this does not,
       and replacing it wholesale to gain three tones would be a trade
       nobody asked for.

    Returns 'replaced', 'pitched' or None.
    """
    global _suppressed, _pitched
    if not is_titan_object(obj):
        # Outside Titan, NVDA is the reader and is left alone - but Titan's
        # own cursor cues can still be played over it, which is where they
        # belong: Titan's own windows already make their own sounds.
        _cue(obj)
        next_handler()
        return None
    if take_mark():
        _suppressed += 1
        with muted():
            next_handler()
        return 'replaced'
    if not _pitched_wanted() or not titan_coordinates():
        next_handler()
        return None
    if not can_mute():
        # Speaking in NVDA's place without being able to keep it quiet is
        # every control announced twice. Better one tone than two voices.
        next_handler()
        return None
    from . import elements
    segments = elements.describe(obj)
    if not segments or not elements.can_pitch():
        next_handler()
        return None
    # Muted rather than skipped, for the reason this whole module exists:
    # `event_gainFocus` also moves the review cursor, updates braille and
    # lets the object cache itself, and none of that should be lost to
    # change how one sentence sounds.
    with muted():
        next_handler()
    _say_unless_titan_does(elements.sequence(segments))
    _pitched += 1
    return 'pitched'


#: Reading a control is IMMEDIATE. There is no delay here and there must
#: not be one.
#:
#: Titan announces some controls itself - the tab bar says "Tab bar, tab,
#: Applications, 1 of 6", which is three things the row's own text does not
#: carry - and either it or the focus event can land first. Waiting a beat
#: to find out which was tried and was the wrong trade: it put that delay
#: in front of EVERY control, and a reader that answers a moment late is a
#: reader that feels broken, which is a worse fault than the one it fixed.
#:
#: The race is settled the way a screen reader settles every other race
#: instead: whoever speaks second and means to interrupt, wins. Titan's
#: announcement carries `interrupt`, so it cancels this and is heard; and
#: an announcement that arrives FIRST leaves a mark, which is checked
#: before a word of this is spoken. What that costs when Titan is second is
#: the first syllable of a row name, which is what every screen reader
#: sounds like when something more important arrives.
PITCH_DELAY_MS = 0

_pending_read = [0]


def cancel_pending_read():
    """Titan has spoken: whatever this was about to read is not wanted."""
    _pending_read[0] += 1


def _say_unless_titan_does(sequence):
    """Read the control, unless Titan has already said something about it."""
    marker = _pending_read[0] = _pending_read[0] + 1
    since = spoke_at()

    def now_or_never():
        if _pending_read[0] != marker:
            return                       # a newer focus has overtaken this
        if spoke_at() != since or take_mark():
            # Titan spoke about this focus first. Its sentence carries what
            # the row's own text cannot, so it wins, and the mark is
            # consumed here rather than eating the NEXT control's report.
            global _suppressed
            _suppressed += 1
            return
        _speak(sequence)

    if PITCH_DELAY_MS <= 0:
        now_or_never()
        return
    try:
        import core
        core.callLater(PITCH_DELAY_MS, now_or_never)
    except Exception:                                # noqa: BLE001
        now_or_never()


def _cue(obj):
    try:
        from . import earcons
        earcons.announce(obj)
    except Exception:                                # noqa: BLE001
        pass


def _pitched_wanted():
    from . import configSpec
    return bool(configSpec.read().get('pitchedFocus', True))


def _speak(sequence):
    speech = compat.speech
    if speech is None or not sequence:
        return
    try:
        from . import interject
        interject.mine()
    except Exception:                                # noqa: BLE001
        pass
    try:
        speech.speak(sequence)
    except Exception:                                # noqa: BLE001
        pass
