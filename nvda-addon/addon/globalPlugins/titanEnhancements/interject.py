# -*- coding: utf-8 -*-
"""Titan Access's own habits, in NVDA.

Titan's reader does three things to what it is ABOUT to say, and every one
of them is a thing Titan knows and the platform does not:

* **A dialog is read as the kind of dialog it is** - a question, a warning,
  an error - with an earcon and the word said a little lower. Titan says so
  itself (``host_bridge.dialog_kind``) because the icon is not reliably
  detectable through a skin, and a confirmation the user cannot tell from a
  notice is a confirmation they will answer wrongly.
* **A state is added to the control that has just been read** - "checked",
  "unchecked" - when the state is Titan's own and the platform has no way to
  report it.
* **The control-type word is replaced** - "status bar item" instead of the
  generic "list item".

None of it reached NVDA. This module is the first two, and it is deliberate
that the third is not: see :func:`capabilities`.

**It is done with NVDA's own filter, not by speaking over it.**
``speech.extensions.filter_speechSequence`` is where NVDA lets an add-on
change what is about to be spoken, so the kind word is part of the SAME
utterance as the dialog's own report and cannot be cut off by it. Saying it
separately is what Titan had to do through ``accessible_output3``, and it is
why that path needed a 500 ms delay and still lost races.

Everything armed here is **one shot and short lived**. Titan arms it and
then does the thing - shows the dialog, ticks the box - which is
milliseconds later; an arming that outlived that would attach itself to
whatever the user did next, which is worse than not having it.
"""

import threading
import time

from . import compat

#: How long an armed word waits for the utterance it belongs to. Titan arms
#: it immediately before the dialog is shown, so this only has to cover the
#: dialog coming up.
WINDOW = 2.0

#: The tone for each kind, in hertz. Chosen the way NVDA's own error tone
#: is: a question rises, a warning sits low, an error is lower still, so
#: they are told apart without a word being said.
TONES = {
    'question': (660, 60),
    'information': (440, 50),
    'warning': (330, 80),
    'error': (220, 110),
}

#: How much lower the kind word is said than the rest. This is Titan
#: Access's own `_REGION_PITCH` (`titan_access/context_presenter.py`) and
#: not a number chosen here: the word is ABOUT the dialog rather than part
#: of it, and it must sound the same in both readers or the user has two
#: vocabularies for one desktop.
KIND_PITCH = -4

#: Warning leads with the type word and then the title; the others read the
#: title first and the type word after it. Titan Access's own rule
#: (`_DIALOG_KIND_TYPE_FIRST`), for the reason a warning exists: the user
#: should know it is a warning before they know what it is about.
KIND_FIRST = frozenset({'warning'})

_LOCK = threading.RLock()
_prefix = None            # (text, when)
_suffix = None            # (text, when)
_registered = False
_applied = 0

#: The last few things NVDA actually said, and who asked for them. "The
#: announcement is gone" is a report with no evidence in it, and there are
#: three different things it can mean - it was never sent, it was sent and
#: something cancelled it, or it was said and something else was said over
#: the top. Only a log of what was really spoken tells them apart. This is
#: the same answer the Elten renderer arrived at, for the same reason.
LOG_KEEP = 12
_log = []
_ours = 0.0


def mine():
    """Mark the next utterance as this add-on's own."""
    global _ours
    _ours = time.time()


def spoken_log():
    with _LOCK:
        return list(_log)


def last_spoken_at():
    with _LOCK:
        return _log[-1][0] if _log else 0.0


def _fresh(armed):
    return armed is not None and (time.time() - armed[1]) < WINDOW


# --------------------------------------------------------------------------- #
# Arming
# --------------------------------------------------------------------------- #
def dialog_kind(kind='', label='', **_):
    """Say what kind of dialog is about to appear, and play its tone.

    ``label`` is the word, sent by Titan: it is the SAME word Titan Access
    says ("Pytanie", "Uwaga!"), in the user's own language, and inventing
    one here would give them two vocabularies for one desktop. English
    names are the floor for a Titan too old to send one.

    The tone is NVDA's own ``tones.beep``, which needs no synthesizer and
    works when speech is off entirely - which for a confirmation dialog is
    the case worth covering.
    """
    name = str(kind or '').strip().lower()
    if name not in TONES:
        return {'armed': False, 'reason': f"there is no dialog kind '{kind}'"}
    hz, ms = TONES[name]
    if compat.tones is not None:
        try:
            compat.tones.beep(hz, ms)
        except Exception:                            # noqa: BLE001
            pass
    word = str(label or '').strip() or name
    with _LOCK:
        if name in KIND_FIRST:
            globals()['_prefix'] = (word, time.time())
            globals()['_suffix'] = None
        else:
            globals()['_prefix'] = None
            globals()['_suffix'] = (word, time.time(), KIND_PITCH)
    return {'armed': True, 'kind': name, 'said': word}


def state_suffix(text='', **_):
    """Add a state to whatever is read next - "checked", "unchecked"."""
    message = str(text or '').strip()
    if not message:
        return {'armed': False, 'reason': 'there is nothing to add'}
    with _LOCK:
        globals()['_suffix'] = (message, time.time(), 0)
    return {'armed': True}


def clear(**_):
    with _LOCK:
        globals()['_prefix'] = None
        globals()['_suffix'] = None
    return {'cleared': True}


def applied():
    """How many utterances have been changed. For the status command."""
    return _applied


# --------------------------------------------------------------------------- #
# Changing what NVDA is about to say
# --------------------------------------------------------------------------- #
def _filter(speechSequence=None, **_kwargs):
    """NVDA's filter: return the sequence, changed or not.

    Registered filters must never raise - NVDA would then say nothing at all
    - and must return a sequence whatever happens.
    """
    global _applied
    sequence = list(speechSequence or [])
    try:
        _remember(sequence)
    except Exception:                                # noqa: BLE001
        pass
    try:
        with _LOCK:
            prefix = _prefix if _fresh(_prefix) else None
            suffix = _suffix if _fresh(_suffix) else None
            if prefix is None and suffix is None:
                return sequence
            if not any(isinstance(part, str) and part.strip()
                       for part in sequence):
                # Nothing is being SAID - a beep, a braille-only update. The
                # arming waits for the utterance it was meant for.
                return sequence
            globals()['_prefix'] = None
            globals()['_suffix'] = None
        if prefix is not None:
            sequence = _pitched(prefix[0], KIND_PITCH) + sequence
        if suffix is not None:
            offset = suffix[2] if len(suffix) > 2 else 0
            sequence = sequence + _pitched(suffix[0], offset)
        _applied += 1
    except Exception:                                # noqa: BLE001
        return list(speechSequence or [])
    return sequence


def _remember(sequence):
    """Write down what is about to be said, and whether we asked for it."""
    global _ours
    words = ' '.join(part for part in sequence
                     if isinstance(part, str) and part.strip()).strip()
    if not words:
        return
    now = time.time()
    with _LOCK:
        ours = bool(_ours and (now - _ours) < 0.5)
        _ours = 0.0
        _log.append((now, 'addon' if ours else 'nvda', words[:120]))
        del _log[:-LOG_KEEP]


def _pitched(word, offset):
    """One word at its own tone, with the tone put back afterwards.

    The offset is Titan's -10..10 and NVDA's is its own 0..100 setting, so
    it is converted rather than passed through - handed over unchanged, -4
    is a four-point change on a hundred-point scale and the word comes out
    at the same tone as everything else.
    """
    if not offset or compat.PitchCommand is None:
        return [word]
    from . import prosody
    try:
        return [compat.PitchCommand(offset=prosody._offset(offset)), word,
                compat.PitchCommand(offset=0)]
    except Exception:                                # noqa: BLE001
        return [word]


def start():
    """Register the filter. Idempotent, and honest when it cannot."""
    global _registered
    if _registered:
        return True
    extensions = compat.speechExtensions
    filter_ = getattr(extensions, 'filter_speechSequence', None) \
        if extensions is not None else None
    if filter_ is None:
        return False
    try:
        filter_.register(_filter)
    except Exception:                                # noqa: BLE001
        return False
    _registered = True
    return True


def stop():
    """Take the filter out again.

    A filter left registered by an add-on that has gone is a function NVDA
    calls for every utterance for the rest of the session, into a module
    that may no longer be importable.
    """
    global _registered
    clear()
    if not _registered:
        return
    extensions = compat.speechExtensions
    filter_ = getattr(extensions, 'filter_speechSequence', None) \
        if extensions is not None else None
    if filter_ is not None:
        try:
            filter_.unregister(_filter)
        except Exception:                            # noqa: BLE001
            pass
    _registered = False


def available():
    """Whether this NVDA lets an add-on change what is about to be said."""
    return _registered


def capabilities():
    """What of Titan Access's habits this NVDA can really do.

    ``role_label`` is deliberately absent. Replacing the control-type word
    means finding it inside a sequence NVDA has already built, in the user's
    own language, among the name and the states - and getting that wrong
    changes the name of the control rather than its type, which is worse
    than not doing it. Titan folds the role into its own sentence instead,
    which is what a capability answering no is FOR.
    """
    return {'dialog_kind': _registered, 'state_suffix': _registered,
            'role_label': False}
