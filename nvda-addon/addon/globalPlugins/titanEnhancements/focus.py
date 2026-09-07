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


class muted:
    """Speech off for the length of a ``with`` block, then back as it was.

    Restoring what was THERE rather than setting 'talk' is the point: a user
    who has NVDA in beeps mode, or has muted speech deliberately, must not
    have it turned on again by a Titan announcement.
    """

    def __init__(self):
        self._kind = None
        self._previous = None

    def __enter__(self):
        kind, previous = _get_mode()
        off = _off_value(kind)
        if kind is None or off is None:
            return self
        self._kind, self._previous = kind, previous
        _set_mode(kind, off)
        return self

    def __exit__(self, *_exception):
        if self._kind is not None:
            _set_mode(self._kind, self._previous)
        self._kind = None
        return False


def handle_gain_focus(obj, next_handler):
    """The global plugin's ``event_gainFocus``, factored out to be testable.

    True when the report was muted.
    """
    global _suppressed
    if not is_titan_object(obj) or not take_mark():
        next_handler()
        return False
    _suppressed += 1
    with muted():
        next_handler()
    return True
