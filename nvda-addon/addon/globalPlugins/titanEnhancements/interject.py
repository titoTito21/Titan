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

#: Titan's own sound for each kind - the ones Titan Access has always
#: played, which now live in the THEME (`sfx/<theme>/SRE/`) rather than
#: inside that optional component, so a Titan without it still has them and
#: a theme can replace any of them.
SOUNDS = {
    'question': 'question_dialog.ogg',
    'information': 'information_dialog.ogg',
    'warning': 'warning_dialog.ogg',
    'error': 'error_dialog.ogg',
}

#: The FLOOR, for a machine with no Titan running at all. A synthesised
#: tone is not what a dialog should sound like on this desktop - Titan has
#: real sounds for these and they are what the user knows - but this
#: add-on works with no Titan, and a dialog kind with no sound is a kind
#: that only exists while speech is on. `tones.beep` needs no synthesizer
#: and works with speech off entirely, which for a confirmation dialog is
#: the case worth covering.
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
_place = None             # (position, when)
_registered = False
_applied = 0
_placed = 0

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

    The SOUND is Titan's own - the one Titan Access has always played for
    that kind - and NVDA's ``tones.beep`` is the floor underneath it, for a
    machine where Titan is not running. Either way something is heard with
    speech off entirely, which for a confirmation dialog is the case worth
    covering.
    """
    name = str(kind or '').strip().lower()
    if name not in TONES:
        return {'armed': False, 'reason': f"there is no dialog kind '{kind}'"}
    if not _sound_for(name):
        hz, ms = TONES[name]
        if compat.tones is not None:
            try:
                compat.tones.beep(hz, ms)
            except Exception:                        # noqa: BLE001
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


def _sound_for(kind):
    """Titan's own sound for this kind of dialog. False when there is none.

    False means Titan is not running, and the caller then makes the tone
    itself - which is the whole reason this answers rather than just
    playing.
    """
    name = SOUNDS.get(kind, '')
    if not name:
        return False
    try:
        from . import earcons
        return bool(earcons.play_named(name))
    except Exception:                                # noqa: BLE001
        return False


def state_suffix(text='', **_):
    """Add a state to whatever is read next - "checked", "unchecked"."""
    message = str(text or '').strip()
    if not message:
        return {'armed': False, 'reason': 'there is nothing to add'}
    with _LOCK:
        globals()['_suffix'] = (message, time.time(), 0)
    return {'armed': True}


def prefix_next(text, voice='context'):
    """Say something IN FRONT of NVDA's own next report, in one utterance.

    For anything that adds to what NVDA says rather than replacing it -
    the part of the window the keyboard has just moved into, which a
    sighted person reads off the layout and a reader has no way to
    mention. In front, because it is the context the words that follow
    belong to; and in the SAME utterance, so it cannot be cut off by them.
    """
    said = str(text or '').strip()
    if not said:
        return False
    with _LOCK:
        globals()['_prefix'] = (said, time.time(), voice)
    return True


def place_next(position, pitch=0.0):
    """Speak the next utterance from ``position`` in the stereo image.

    This is how NVDA's OWN report of a control gets placed. Everywhere
    outside Titan's windows NVDA is the reader and is deliberately left to
    say what it says - but WHERE it is said from is not what it says, and
    placing it loses nothing. Arming it here rather than speaking in NVDA's
    place is the whole difference: the words are still NVDA's, in the
    user's own verbosity settings, with tables and landmarks and browse
    mode and everything else this add-on knows nothing about.

    One shot and short lived, like everything else armed in this module: a
    position that outlived the report it belongs to would pan whatever the
    user did next.
    """
    try:
        tone = float(pitch or 0.0)
    except (TypeError, ValueError):
        tone = 0.0
    value = None
    if position is not None:
        try:
            value = float(position)
        except (TypeError, ValueError):
            value = None
    if value is None and not tone:
        return False
    with _LOCK:
        globals()['_place'] = (value, time.time(), tone)
    return True


def placed():
    """How many utterances were really moved. For the status command."""
    return _placed


def clear(**_):
    with _LOCK:
        globals()['_prefix'] = None
        globals()['_suffix'] = None
        globals()['_place'] = None
    return {'cleared': True}


def registered():
    """Whether NVDA is really letting us change what it is about to say.

    The whole of the dialog kinds, the region prefixes and the menu word
    go through NVDA's speech filter, so a filter that never registered is
    all three of them silently doing nothing - and nothing anywhere says
    so.
    """
    return bool(_registered)


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
    global _applied, _placed
    sequence = list(speechSequence or [])
    try:
        _remember(sequence)
    except Exception:                                # noqa: BLE001
        pass
    try:
        sequence = _reading_voice(sequence)
    except Exception:                                # noqa: BLE001
        pass
    try:
        sequence = _origin_voice(sequence)
    except Exception:                                # noqa: BLE001
        pass
    try:
        # **Written down here because here is where it is really said.**
        # Anything earlier would record what was meant rather than what came
        # out, and anything later would be after the words had gone.
        _journal(sequence)
    except Exception:                                # noqa: BLE001
        pass
    try:
        with _LOCK:
            prefix = _prefix if _fresh(_prefix) else None
            suffix = _suffix if _fresh(_suffix) else None
            where = _place if _fresh(_place) else None
            if prefix is None and suffix is None and where is None:
                return sequence
            if not any(isinstance(part, str) and part.strip()
                       for part in sequence):
                # Nothing is being SAID - a beep, a braille-only update. The
                # arming waits for the utterance it was meant for.
                return sequence
            globals()['_prefix'] = None
            globals()['_suffix'] = None
            globals()['_place'] = None
        if prefix is not None:
            voice = prefix[2] if len(prefix) > 2 else KIND_PITCH
            sequence = _pitched(prefix[0], voice) + sequence
        if suffix is not None:
            offset = suffix[2] if len(suffix) > 2 else 0
            sequence = sequence + _pitched(suffix[0], offset)
        if prefix is not None or suffix is not None:
            _applied += 1
        if where is not None:
            from . import prosody
            before = len(sequence)
            tone = where[2] if len(where) > 2 else 0.0
            if tone:
                # A row: up and down rather than left and right.
                sequence = prosody.pitch_sequence(sequence, tone)
            elif where[0] is not None:
                sequence, _notes = prosody.place_sequence(sequence, where[0])
            # Both answer a fresh list, so identity says nothing; a longer
            # one is one that really gained the commands (or the tone that
            # stands in for them).
            if len(sequence) != before:
                _placed += 1
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


def _pitched(word, voice):
    """One word in its own voice, with every dial put back afterwards.

    ``voice`` is either a bare offset - Titan's -10..10, which is what
    arrives over the wire - or the name of a semantic class. Either way
    the number is CONVERTED rather than passed through: handed over
    unchanged, -4 is a four-point change on NVDA's hundred-point scale and
    the word comes out at the same tone as everything else.
    """
    if not voice or compat.PitchCommand is None:
        return [word]
    try:
        from . import voices
        built = voices.sequence([(word, voice)])
        return built or [word]
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


# --------------------------------------------------------------------------- #
# Reading text, in the voice for reading text
# --------------------------------------------------------------------------- #
#: How many utterances were spoken in the reading voice. For the
#: diagnostics command, which is the only way to tell "the class does
#: nothing" from "say all was never running".
_read_aloud = 0


def read_aloud():
    return _read_aloud


def _saying_all():
    """Whether NVDA is reading continuously right now.

    Say-all is the one thing a reader does that is not about a control: it
    is a document being read, it goes on for minutes, and it is exactly
    what somebody wants in a voice of its own - faster, or a different one
    entirely, so it is not mistaken for the reader talking about the screen.

    Asked of NVDA's own handler, and every one of the places it has lived:
    it moved from `sayAllHandler` to `speech.sayAll` and the class was
    renamed on the way, so an add-on that knows only one of them answers
    "no" for ever on the other and the feature is silently absent.
    """
    for reach in (lambda: __import__('speech.sayAll', fromlist=['SayAllHandler'])
                  .SayAllHandler.isRunning(),
                  lambda: __import__('sayAllHandler').isRunning()):
        try:
            return bool(reach())
        except Exception:                            # noqa: BLE001
            continue
    return False


def _reading_voice(sequence):
    """The `text` class, applied to a document being read aloud."""
    global _read_aloud
    if not sequence or not _saying_all():
        return sequence
    if not any(isinstance(part, str) and part.strip() for part in sequence):
        return sequence
    from . import classes
    from . import prosody
    from . import voices
    profile = classes.voice_of('text')
    if not profile:
        return sequence
    # **A synthesizer of its own is not applied HERE**, and that is not the
    # same as not applied at all. Say-all is NVDA's own machinery: it
    # tracks where it has got to by the indexes in the sequence it handed
    # its synth, so taking the words away to speak them somewhere else
    # leaves that machinery reading a document nobody can hear. The synthesizer
    # for reading text is arranged where NVDA already switches
    # one - its own say-all configuration profile, see the sayall_profile
    # module - and what is left for this filter is the dials, which are
    # real speech commands and can honestly be applied.
    on, off = voices._commands(profile, prosody.panner.current_synth())
    if not on:
        return sequence
    _read_aloud += 1
    return list(on) + list(sequence) + list(off)


# --------------------------------------------------------------------------- #
# Keyboard echo, a spelled word, a message, the controller
# --------------------------------------------------------------------------- #
#: How many utterances were coloured by where they came from, per class.
_by_origin = {}


def by_origin():
    return dict(_by_origin)


def _origin_voice(sequence):
    """The voice for what this utterance IS, not for what it says.

    `origin` marks an utterance while NVDA is still in the function that
    knows what kind it is - keyboard echo, a word being spelled, a message,
    what another program said through the controller - and this is where the
    mark is spent. Nothing here reads the words.

    **The dials go inside the utterance; a voice or a variant is put on the
    driver.** The first is exact and free. The second cannot be a command at
    all (see `voices.BY_SETTING`), and there is no utterance before this one
    to change the driver at the end of - so it is changed here, immediately
    before the sequence goes to the synth, and put back by a callback at the
    end of it. `speaking` keeps what is outstanding and restores it before
    the next change and on a timer, so the worst case is one utterance in
    the wrong voice rather than a session in it.
    """
    from . import origin
    mark = origin.current()
    if not mark or not sequence or not origin.wanted():
        return sequence
    if not any(isinstance(part, str) and part.strip() for part in sequence):
        return sequence
    from . import classes
    from . import prosody
    from . import voices
    profile = classes.voice_of(mark)
    if not profile:
        return sequence
    synth = prosody.panner.current_synth()
    on, off = voices._commands(profile, synth)
    named = voices._signature(profile)
    if not on and not named:
        return sequence
    _by_origin[mark] = _by_origin.get(mark, 0) + 1
    out = list(on) + list(sequence) + list(off)
    if named:
        from . import speaking
        speaking.become(named)
        out.extend(voices._boundary({}))
    return out


def _journal(sequence):
    """One line of what the reader said, with the way back to what said it.

    The words are what is in the sequence at this moment - commands and all
    the rest are not words - and the KIND comes from `origin`, which knows
    because NVDA knew while it was still in the function that produced it.
    """
    from . import journal
    from . import origin
    if not journal.wanted():
        return
    said = ' '.join(part for part in sequence if isinstance(part, str)
                    and part.strip())
    if said.strip():
        journal.note(said, kind=origin.current())
