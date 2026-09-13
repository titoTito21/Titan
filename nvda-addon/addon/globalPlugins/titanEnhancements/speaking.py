# -*- coding: utf-8 -*-
"""Synthesizers, voices and variants - asked of NVDA, and driven directly.

:mod:`voices` carries a semantic class in the DIALS of the voice that is
already speaking, which is exact, cheap and belongs to the utterance it is
in. This module is the other half of the same idea and it is a different
mechanism, because what it does is different in kind: a class here does not
bend the current voice, it names **another voice, or another synthesizer
entirely**, and something has to go and get one.

**Why both, rather than only this one.** NVDA has real speech commands for
pitch, rate and volume; it has none at all for voice, variant, inflection or
synthesizer. Those can only be changed by SETTING them on a synth driver -
which is a change to the reader's own state, not to one utterance - so
everything here is written around putting them back, and around the one
thing that cannot be put back safely:

* **A different SYNTHESIZER is a whole utterance, never part of one.**
  Switching NVDA's own synth mid-sentence cancels what it is saying, so a
  class that names one is spoken by a driver of OUR OWN
  (:func:`speak_with`), instantiated once and kept. The user's synthesizer
  is never touched, never switched and never cancelled, which is the whole
  reason this is a second driver instead of `setSynth`.
* **A different VOICE or VARIANT of the SAME synthesizer** can be a part of
  an utterance, because it is one setting on the driver that is already
  speaking - set by a callback in the sequence and put back by another one,
  exactly as the panner does. What it costs is that a synth which flushes
  on a voice change will break the utterance there; that is the synth's
  behaviour and it is reported rather than hidden.

**Nothing here is required.** Every one of these can be absent - an NVDA
without the driver, a synth that has no variants, a voice that has been
uninstalled since the user chose it - and each one answers with what it can
rather than raising. A class whose voice cannot be honoured is spoken in the
plain one, which is what it sounded like before.
"""

import threading

from . import compat

_LOCK = threading.RLock()

#: name -> a driver of our own, kept for the life of the session. Making one
#: is slow (a SAPI voice enumeration, an eSpeak initialisation) and doing it
#: per notification would put that on the path of every announcement.
_drivers = {}

#: Names that have already failed. A synthesizer that will not start does
#: not get asked again every time somebody is notified of something.
_refused = {}


def forget():
    """Drop every driver of ours. Called when the user changes the table."""
    with _LOCK:
        held = list(_drivers.values())
        _drivers.clear()
        _refused.clear()
    for driver in held:
        try:
            driver.terminate()
        except Exception:                            # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# What this NVDA has
# --------------------------------------------------------------------------- #
def current():
    """NVDA's own synthesizer, or None."""
    handler = compat.synthDriverHandler
    if handler is None:
        return None
    try:
        return handler.getSynth()
    except Exception:                                # noqa: BLE001
        return None


def synthesizers():
    """``[(name, description)]`` - every synthesizer this NVDA can use.

    NVDA's own list, so a synthesizer the user installed yesterday is here
    and nothing has to be written down. The empty list is the honest answer
    outside NVDA, and the dialog then offers only "the one NVDA is using".
    """
    handler = compat.synthDriverHandler
    if handler is None:
        return []
    for asked in ('getSynthList', 'getSynthDriverList'):
        getter = getattr(handler, asked, None)
        if getter is None:
            continue
        try:
            rows = list(getter())
        except Exception:                            # noqa: BLE001
            continue
        out = []
        for row in rows:
            try:
                name, description = row[0], row[1]
            except Exception:                        # noqa: BLE001
                continue
            out.append((str(name), str(description or name)))
        if out:
            return out
    return []


def _driver_class(name):
    handler = compat.synthDriverHandler
    if handler is None:
        return None
    for asked in ('_getSynthDriver', 'getSynthDriver'):
        getter = getattr(handler, asked, None)
        if getter is None:
            continue
        try:
            return getter(str(name))
        except Exception:                            # noqa: BLE001
            continue
    return None


def driver_for(name):
    """A synthesizer of OUR OWN by name, or None. Made once, then kept.

    Never NVDA's own instance: this one is spoken through directly, and
    borrowing the reader's driver would mean our notification cancelling
    whatever the reader was in the middle of saying.
    """
    key = str(name or '').strip()
    if not key:
        return None
    with _LOCK:
        held = _drivers.get(key)
        if held is not None:
            return held
        if key in _refused:
            return None
    # `getSynthInstance` is NVDA's own way of making one that is not the
    # reader's - it loads the driver's settings and initialises it exactly
    # as NVDA would, which building the class by hand does not. Read out of
    # `synthDriverHandler`; the class is the fallback for an NVDA that has
    # not got it.
    handler = compat.synthDriverHandler
    make = getattr(handler, 'getSynthInstance', None) if handler else None
    if callable(make):
        try:
            driver = make(key)
        except Exception as error:                   # noqa: BLE001
            with _LOCK:
                _refused[key] = str(error)
            return None
        if driver is not None:
            with _LOCK:
                _drivers[key] = driver
            return driver
    klass = _driver_class(key)
    if klass is None:
        with _LOCK:
            _refused[key] = 'this NVDA has no synthesizer called that'
        return None
    try:
        check = getattr(klass, 'check', None)
        if callable(check) and not check():
            with _LOCK:
                _refused[key] = 'that synthesizer says it cannot run here'
            return None
        driver = klass()
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _refused[key] = str(error)
        return None
    with _LOCK:
        _drivers[key] = driver
    return driver


def refused():
    """Why a synthesizer could not be started, by name. For the dialog."""
    with _LOCK:
        return dict(_refused)


def _synth_or_current(name):
    """The driver a profile names, or NVDA's own when it names none."""
    key = str(name or '').strip()
    return driver_for(key) if key else current()


def _ask(driver, name):
    """Read one of a driver's own properties. Never raises, for ANY reason.

    **`getattr` with a default is not enough here, and that was a crash.**
    These are `AutoPropertyObject` properties, so reading one CALLS the
    driver's getter - and `synthDriverHandler._getAvailableVariants` raises
    `NotImplementedError` for every synthesizer that has no variants, which
    `getattr`'s default does not catch (it catches `AttributeError` and
    nothing else). Choosing a voice on such a synthesizer in the voice-class
    manager therefore ended in an unhandled exception, with the dialog left
    half filled in; over a bridged driver (`rpyc`) the same thing arrives as
    a remote traceback, which is worse to read and no easier to catch.
    """
    if driver is None:
        return None
    try:
        return getattr(driver, name, None)
    except Exception:                                # noqa: BLE001
        return None


def has_setting(synth, field, wanted):
    """Whether the driver really has that voice or that variant.

    True, False, or **None for "it will not say"** - and the three are
    different answers. A driver that cannot be asked is not one to guess
    about, so None means "set it and see", which is what this always did.

    **Asking is the only way to find out.** Setting a voice a synthesizer
    has not got does not raise anywhere it can be caught: NVDA's eSpeak
    driver queues the change onto a thread of its own, so the failure is
    logged THERE - `espeak_SetVoiceByName: code 2` (EE_NOT_FOUND) - once
    per utterance, for as long as the class is used. Measured in a real
    log: 261 of them, from one class, in four minutes.
    """
    name = str(wanted or '').strip()
    if not name:
        return None
    collection = _ask(synth, 'availableVoices' if field == 'voice'
                      else 'availableVariants')
    if not collection:
        return None
    try:
        return name in {str(key) for key in collection.keys()}
    except Exception:                                # noqa: BLE001
        return None


def voices_of(name=''):
    """``[(id, label)]`` for a synthesizer - NVDA's own when unnamed."""
    synth = _synth_or_current(name)
    return _entries(_ask(synth, 'availableVoices'))


def variants_of(name='', voice=''):
    """``[(id, label)]`` - the variants of one voice of one synthesizer.

    The variant list belongs to the VOICE, and a synth answers about
    whichever voice it is set to - so the voice is put on first and put back
    afterwards. Asking without doing that lists the variants of a voice the
    user is not choosing, which is a list that looks right and is wrong.
    """
    synth = _synth_or_current(name)
    if synth is None:
        return []
    wanted = str(voice or '').strip()
    was = None
    if wanted:
        try:
            was = getattr(synth, 'voice', None)
            if was != wanted:
                synth.voice = wanted
            else:
                was = None
        except Exception:                            # noqa: BLE001
            was = None
    try:
        return _entries(_ask(synth, 'availableVariants'))
    finally:
        if was is not None:
            try:
                synth.voice = was
            except Exception:                        # noqa: BLE001
                pass


def _entries(collection):
    if not collection:
        return []
    out = []
    try:
        items = collection.items()
    except Exception:                                # noqa: BLE001
        return []
    for key, value in items:
        label = ''
        for attribute in ('displayName', 'name', 'description'):
            label = str(getattr(value, attribute, '') or '')
            if label:
                break
        out.append((str(key), label or str(key)))
    return out


def supports(synth, setting):
    """Whether this driver really has that dial.

    A synthesizer that does not is not an error and must not be reported as
    one: it is a class spoken in the plain voice, which is what it sounded
    like before there was a table at all.
    """
    if synth is None:
        return False
    try:
        asked = getattr(synth, 'supportedSettings', None)
        if asked:
            for item in asked:
                if str(getattr(item, 'id', '') or '') == setting:
                    return True
            return False
    except Exception:                                # noqa: BLE001
        pass
    return hasattr(synth, setting)


# --------------------------------------------------------------------------- #
# Saying a whole utterance in another voice
# --------------------------------------------------------------------------- #
#: The dials a profile may set directly on a driver. NVDA's own names, so a
#: driver that has one has it under this name.
SETTINGS = ('rate', 'pitch', 'volume', 'inflection')

#: Titan's -10..10 onto NVDA's 0..100. One conversion, in `prosody`.
def _absolute(value, current):
    """A -10..10 offset applied to a 0..100 setting, kept inside it."""
    from . import prosody
    try:
        return max(0, min(100, int(round(float(current)
                                         + prosody._offset(value)))))
    except Exception:                                # noqa: BLE001
        return None


def apply_to(synth, profile):
    """Put a profile onto a driver. Answers what it changed, to put back.

    The voice first and the variant after it: a variant belongs to a voice,
    and setting one on the voice that is about to be replaced is setting it
    on nothing.
    """
    was = {}
    if synth is None or not profile:
        return was
    for field in ('voice', 'variant'):
        wanted = str(profile.get(field) or '').strip()
        if not wanted:
            continue
        # **Asked before it is set, because it cannot be asked after.**
        # A driver that does not have this dial at all, or does not have
        # this voice, is a class spoken in the plain voice - which is what
        # the docstring at the top of this module has always promised and
        # what it did not do: the failure happens on the driver's own
        # thread, where a `try` here catches nothing, so the only way to
        # keep that promise is not to make the change.
        if not supports(synth, field):
            continue
        if has_setting(synth, field, wanted) is False:
            continue
        try:
            held = _ask(synth, field)
            if held == wanted:
                continue
            setattr(synth, field, wanted)
            was[field] = held
        except Exception:                            # noqa: BLE001
            continue
    for field in SETTINGS:
        amount = profile.get(field)
        if not amount:
            continue
        if not supports(synth, field):
            continue
        try:
            held = getattr(synth, field)
            value = _absolute(amount, held)
            if value is None or value == held:
                continue
            setattr(synth, field, value)
            was[field] = held
        except Exception:                            # noqa: BLE001
            continue
    return was


def put_back(synth, was):
    """Undo :func:`apply_to`. Never raises: a dial left moved is a reader
    that goes on sounding wrong for everything after it."""
    if synth is None or not was:
        return
    for field, value in was.items():
        try:
            setattr(synth, field, value)
        except Exception:                            # noqa: BLE001
            continue


def speak_with(profile, text):
    """Say one whole thing in the voice a profile names. True when it did.

    Only for a class that is a MESSAGE - a notification, something another
    program said through the controller, a page being read - never for part
    of a control's reading. A different synthesizer cannot be part of an
    utterance: it is a different program producing the sound, and the two
    would talk over each other.
    """
    name = str((profile or {}).get('synth') or '').strip()
    if not name:
        return False
    synth = driver_for(name)
    if synth is None:
        return False
    words = str(text or '').strip()
    if not words:
        return False
    was = apply_to(synth, profile)
    try:
        synth.speak([words])
        return True
    except Exception:                                # noqa: BLE001
        return False
    finally:
        # The dials go back at once rather than when the speech ends. They
        # are read when `speak` is called, so the sound already carries
        # them, and holding them until the utterance finished would leave a
        # second notification arriving mid-sentence to be spoken with the
        # first one's voice.
        put_back(synth, was)


def stop():
    """Stop anything one of our own drivers is saying."""
    with _LOCK:
        held = list(_drivers.values())
    for driver in held:
        try:
            driver.cancel()
        except Exception:                            # noqa: BLE001
            pass

# --------------------------------------------------------------------------- #
# When the reader is told to be quiet, so are we
# --------------------------------------------------------------------------- #
#: NVDA's own `cancelSpeech`, kept so it can be put back exactly.
_cancel_was = None


def follow_cancel():
    """Stop our own drivers whenever NVDA's speech is cancelled.

    **A driver of ours is not in NVDA's speech queue**, which is the whole
    point of it - and it is also the one thing that goes wrong: pressing a
    key to shut the reader up reaches `synth.cancel()` on NVDA's
    synthesizer and nothing at all on ours, so a message being spoken
    elsewhere carries on over whatever the user asked for instead. There
    is no extension point for this, so `cancelSpeech` is wrapped, the way
    :mod:`origin` wraps the speech functions and for the same reason.

    Idempotent, and it puts back only what it put there.
    """
    global _cancel_was
    if _cancel_was is not None:
        return True
    speech = compat.speech
    original = getattr(speech, 'cancelSpeech', None) if speech else None
    if not callable(original):
        return False

    def wrapper(*args, **kwargs):
        try:
            stop()
        except Exception:                            # noqa: BLE001
            pass
        return original(*args, **kwargs)
    wrapper.__name__ = 'cancelSpeech'
    wrapper._titan_original = original
    try:
        setattr(speech, 'cancelSpeech', wrapper)
    except Exception:                                # noqa: BLE001
        return False
    _cancel_was = original
    return True


def unfollow_cancel():
    """Put NVDA's own `cancelSpeech` back, and only if it is still ours."""
    global _cancel_was
    original = _cancel_was
    _cancel_was = None
    speech = compat.speech
    if original is None or speech is None:
        return False
    try:
        standing = getattr(speech, 'cancelSpeech', None)
        # Only OURS. Something else may have wrapped it since, and a
        # reader is not the place to win an argument with another add-on.
        if getattr(standing, '_titan_original', None) is original:
            setattr(speech, 'cancelSpeech', original)
            return True
    except Exception:                                # noqa: BLE001
        pass
    return False



# --------------------------------------------------------------------------- #
# The reader's own driver, changed and always changed back
# --------------------------------------------------------------------------- #
#: What we have put on NVDA's OWN synthesizer and not yet taken off, as
#: ``{setting: what it was}``.
#:
#: **This is the safety net, and it is not optional.** A voice or a variant
#: is a setting on the reader's driver, so a reading that changes one and is
#: then cut short - the user presses a key, speech is cancelled, the callback
#: that would have put it back never fires - leaves every word the reader
#: says afterwards in the wrong voice. There is no way to make that
#: impossible, so it is made harmless instead: whatever is outstanding is put
#: back before the next change and again on a timer, so the worst case is one
#: reading in the wrong voice rather than a session in it.
_standing = {}
_undo_at = None

#: How long an outstanding change may stand with nothing putting it back.
#: Longer than a reading and shorter than a user noticing.
UNDO_SECONDS = 2.0


def standing():
    with _LOCK:
        return dict(_standing)


def name_of(synth):
    """What a driver calls itself, or ''. Never raises."""
    return str(_ask(synth, 'name') or '').strip()


def for_another_synth(profile, synth=None):
    """Whether this profile's voice belongs to a DIFFERENT synthesizer.

    A voice id means nothing outside the synthesizer it came from. The
    user's own table had `controller` set to sapi5_32's
    `HKEY_LOCAL_MACHINE\\...\\RHVoice\\Natan` while NVDA was running
    eSpeak, and that name was pushed into eSpeak once per notification -
    which is the reported swarm of errors, and it was in the log 261 times.

    A profile that names no synthesizer is not a different one: it was
    chosen for whatever the user is using, and `has_setting` is what
    catches it if they have since changed synthesizer.
    """
    wanted = str((profile or {}).get('synth') or '').strip()
    if not wanted:
        return False
    here = name_of(synth if synth is not None else current())
    return bool(here) and wanted != here


def become(profile):
    """Put ``profile``'s driver settings on NVDA's own synthesizer.

    An empty profile means "be the reader's own voice again", which is what
    the end of every sequence asks for.

    **A voice belonging to another synthesizer is left behind here.** This
    is the one place a profile can reach a driver it was not chosen for:
    :func:`speak_with` goes to the driver the profile NAMES, and a class
    that names one is supposed to go there - but the dials of such a class
    still travel through the ordinary sequence, and the voice used to
    travel with them.
    """
    synth = current()
    if synth is None:
        return False
    restore_standing(synth)
    wanted = {name: value for name, value in (profile or {}).items() if value}
    if for_another_synth(profile, synth):
        wanted.pop('voice', None)
        wanted.pop('variant', None)
    if not wanted:
        return True
    was = apply_to(synth, wanted)
    if not was:
        return False
    with _LOCK:
        _standing.update(was)
    _arm_undo()
    return True


def restore_standing(synth=None):
    """Put back whatever is outstanding. Safe to call at any time."""
    with _LOCK:
        was = dict(_standing)
        _standing.clear()
    if not was:
        return False
    put_back(synth if synth is not None else current(), was)
    return True


def _arm_undo():
    """A timer that puts the driver back if nothing else does.

    Through NVDA's own `core.callLater` where there is one, because this
    touches the synthesizer and belongs on the main thread; a plain timer is
    the fallback for a test, where there is no NVDA and nothing to race.
    """
    global _undo_at
    try:
        import core
        core.callLater(int(UNDO_SECONDS * 1000), restore_standing)
        return
    except Exception:                                # noqa: BLE001
        pass
    try:
        _undo_at = threading.Timer(UNDO_SECONDS, restore_standing)
        _undo_at.daemon = True
        _undo_at.start()
    except Exception:                                # noqa: BLE001
        pass
