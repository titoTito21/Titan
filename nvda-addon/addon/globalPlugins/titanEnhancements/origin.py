# -*- coding: utf-8 -*-
"""Where an utterance CAME FROM, so it can be said in a voice of its own.

Keyboard echo in one voice, what another program says through the controller
in another, a spelled-out word in a third. Every screen reader that has ever
been good at this - Emacspeak first, JAWS' speech and sounds schemes after it
- rests on one thing: knowing which of those a piece of speech IS. NVDA knows
perfectly well when it speaks; by the time the words reach
`filter_speechSequence` they are a list of strings and nothing says where
they started.

**So the origin is taken where it is still known.** NVDA's speech package has
a named function per kind - `speakTypedCharacters`, `speakSpelling`,
`speakMessage`, `speakText` - and this wraps each of them to leave a mark for
the duration of the call. The filter reads the mark. Nothing is guessed from
the words, nothing is matched against a language, and a kind this add-on has
not heard of simply has no mark and is spoken exactly as before.

Two details that are the whole correctness of it:

* **The OUTERMOST mark wins.** `ui.message` is `speakMessage`, which calls
  `speakText`, so a notification would arrive marked as controller speech if
  the innermost call decided - and every message NVDA says about itself would
  be coloured as though another program had said it. The first mark on the
  way in is the one that means something; the ones under it are plumbing.
* **The mark is per THREAD.** Speech is queued from the main thread and from
  others (the controller's own RPC call is queued through `queueHandler`),
  and a mark left visible to another thread would colour whatever that
  thread happened to be saying at the same moment.

Wrapping module functions is done carefully and is undone: :func:`stop` puts
back exactly what was there, so an add-on that is disabled or updated leaves
NVDA as it found it. A function this NVDA has not got is not wrapped and is
recorded, rather than the whole layer failing because one name moved.
"""

import threading

from . import compat

#: NVDA's own function -> the semantic class that speech belongs to.
#:
#: `speakText` is last on purpose. It is what the controller client's
#: `nvdaController_speakText` queues (read out of NVDA's `NVDAHelper`:
#: `queueHandler.queueFunction(eventQueue, speech.speakText, text)`), and it
#: is also what `speakMessage` calls underneath - so it means "another
#: program said this" only when nothing outside it has already said what it
#: is. That is exactly what the outermost-wins rule delivers.
MARKS = (
    ('speakTypedCharacters', 'typed'),
    ('speakSpelling', 'spelling'),
    ('speakMessage', 'notification'),
    ('speakText', 'controller'),
)

_LOCK = threading.RLock()
_local = threading.local()
_wrapped = {}
_missing = {}
_seen = {}


def report():
    with _LOCK:
        return {'wrapped': sorted(_wrapped), 'missing': dict(_missing),
                'seen': dict(_seen)}


def _stack():
    held = getattr(_local, 'stack', None)
    if held is None:
        held = _local.stack = []
    return held


def current():
    """The class this utterance belongs to, or '' - the outermost mark."""
    held = _stack()
    return held[0] if held else ''


def push(mark):
    _stack().append(mark)


def pop():
    held = _stack()
    if held:
        held.pop()


def note(mark):
    with _LOCK:
        _seen[mark] = _seen.get(mark, 0) + 1


def _wrap(speech, name, mark):
    original = getattr(speech, name, None)
    if not callable(original):
        with _LOCK:
            _missing[name] = 'this NVDA has no speech.%s' % name
        return False

    def wrapper(*args, **kwargs):
        push(mark)
        if len(_stack()) == 1:
            note(mark)
        try:
            return original(*args, **kwargs)
        finally:
            pop()
    wrapper.__name__ = name
    wrapper.__doc__ = getattr(original, '__doc__', '')
    #: What was there before, so `stop` can put back exactly that - and so
    #: wrapping twice (a reload, a second start) cannot bury the real one
    #: under two layers of ours.
    wrapper._titan_original = original
    setattr(speech, name, wrapper)
    with _LOCK:
        _wrapped[name] = original
    return True


def start():
    """Mark every kind of speech NVDA has a name for. Idempotent."""
    speech = compat.speech
    if speech is None:
        return 0
    stop()
    done = 0
    for name, mark in MARKS:
        if _wrap(speech, name, mark):
            done += 1
    return done


def stop():
    """Put NVDA's own functions back, exactly as they were.

    The calling thread's marks go too. "We are not marking anything" and
    "there is a mark standing" cannot both be true, and a mark left on the
    stack by a call that never returned would colour everything said after
    it - which is the one failure this module could cause that the user
    would hear and never be able to explain.
    """
    del _stack()[:]
    speech = compat.speech
    with _LOCK:
        held = dict(_wrapped)
        _wrapped.clear()
    if speech is None:
        return
    for name, original in held.items():
        try:
            # Only OURS. If something else has wrapped it since, putting the
            # original back would throw that away - a reader is not the place
            # to win an argument with another add-on.
            standing = getattr(speech, name, None)
            if getattr(standing, '_titan_original', None) is original:
                setattr(speech, name, original)
        except Exception:                            # noqa: BLE001
            continue


def wanted():
    """Whether an utterance's origin should colour it at all."""
    from . import configSpec
    return bool(configSpec.read().get('speechOrigins', True))
