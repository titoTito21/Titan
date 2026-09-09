# -*- coding: utf-8 -*-
"""Voice-lock: the class of a thing, carried by the voice rather than said.

Emacspeak's oldest and best idea. A screen reader that has to SAY what
something is spends a word on it every single time - "Save, button,
unavailable" - and the word is the same length whether or not the listener
already knew. Emacspeak gives each semantic class a voice of its own
instead: a heading, a comment, a disabled control and a value are heard
apart before a syllable of their content arrives, because the voice
changed. Titan Access already does a small version of this - the name at
the neutral tone, the control type lower, the state higher - and this is
the same idea with the rest of the dimensions the synthesizer has.

**Three dials, because that is what NVDA really carries.** Pitch, rate and
volume, as ``PitchCommand`` / ``RateCommand`` / ``VolumeCommand``, each of
which every synthesizer that declares it honours and every synthesizer that
does not simply drops. Nothing here invents a voice a synthesizer has not
got: a class whose dials this synth will not take is spoken in the plain
voice, which is what it sounded like before.

**The numbers are Titan Access's where Titan Access has one.** The name at
0, what a thing IS at -4, a state at +4 - so the two readers on this
desktop agree about what a control sounds like, and a user who moves
between them is not learning two vocabularies. Everything below that is
this module's, and every one of them is a difference somebody has to be
able to HEAR: a dial nobody notices is a dial that costs a speech command
per utterance for nothing.

**A class is never the only way something is said.** Emacspeak's mistake to
avoid is the one where the voice becomes load-bearing: a listener with a
synthesizer that flattens everything, or a braille display, must lose
nothing. So the words are still there - a disabled control still says so if
NVDA says so - and this only adds a way to hear it sooner.
"""

from . import compat

#: Titan's -10..10 onto NVDA's 0..100 settings. The same conversion
#: :mod:`prosody` does, and imported from there rather than repeated: a
#: scale written down twice is a scale that goes out of step.
def _offset(value):
    from . import prosody
    return prosody._offset(value)


#: Every semantic class this add-on can hear apart, and what it sounds
#: like. ``pitch``, ``rate`` and ``volume`` are Titan's -10..10.
VOICES = {
    # The three Titan Access already has. These numbers are not this
    # module's to choose.
    'name': {},
    'kind': {'pitch': -4},
    'state': {'pitch': 4},

    # What a row of a Titan application's list IS. A folder is something
    # you go INTO and a file is something you open, and in a file manager
    # that is the distinction the whole window is about - so they are two
    # voices rather than two words that both arrive after the name.
    'folder': {'pitch': -4, 'rate': -2},
    'file': {'pitch': -4},

    # The columns beside the name - a date, a size, a link. Said faster,
    # because they are what the listener skims past on the way to the next
    # row, and a fifth of a second saved on every row is most of a list.
    'detail': {'rate': 3},

    # Where the user now is: the folder the file manager just opened, the
    # document the editor just loaded. Slower and a little louder, because
    # it is the one part of the utterance that is not about the control.
    'context': {'pitch': -2, 'rate': -2, 'volume': 2},

    # "3 of 10". Quieter: it is orientation, not content.
    'place': {'rate': 2, 'volume': -2},

    # A control that cannot be used. Emacspeak's own answer, and the
    # clearest case for the whole idea: quieter and flatter says
    # "unavailable" before the word does, and in a menu of twenty items it
    # says it twenty times for no words at all.
    'disabled': {'pitch': -2, 'volume': -3},

    # Something the user should act on.
    'alert': {'pitch': 2, 'volume': 2},
}


def voice_of(tag):
    """The dials for one class. ``{}`` for anything not written down.

    A class nobody has defined is the plain voice rather than an error:
    this is read from a table that grows, and a name that has not arrived
    yet must degrade to "said normally".
    """
    if isinstance(tag, dict):
        return dict(tag)
    if isinstance(tag, (int, float)):
        # The older shape - a bare pitch offset - which is what every
        # existing caller passes and what Titan sends over the wire.
        return {'pitch': float(tag)}
    # **The user's own answer wins, and there is only one place that
    # knows it.** The table above is what this add-on ships with; the
    # class manager is where somebody says a dial is inaudible on their
    # synthesizer, or too much. Asking there rather than reading `VOICES`
    # directly is what keeps the manager from drifting away from what is
    # really spoken - a manager that showed one thing and the reader said
    # another would be worse than not having one.
    try:
        from . import classes
        return classes.voice_of(tag)
    except Exception:                                # noqa: BLE001
        return dict(VOICES.get(str(tag or ''), {}))


def _supported(synth, command):
    from . import prosody
    return prosody._supported(synth, command)


def _commands(voice, synth):
    """The DIAL commands for one voice, and the ones to put it back.

    Only pitch, rate and volume. Those are real speech commands: the synth
    is handed them as part of the utterance, so they take effect exactly
    where they sit and are put back exactly where they are put back.

    A voice, a variant and an inflection are NOT commands - see
    :data:`BY_SETTING` - and trying to make them behave like ones is the
    bug this module shipped with.
    """
    on, off = [], []
    for name, command in (('pitch', compat.PitchCommand),
                          ('rate', compat.RateCommand),
                          ('volume', compat.VolumeCommand)):
        amount = voice.get(name) or 0
        if not amount or command is None or not _supported(synth, command):
            continue
        try:
            on.append(command(offset=_offset(amount)))
            off.append(command(offset=0))
        except Exception:                            # noqa: BLE001
            continue
    return on, off


# --------------------------------------------------------------------------- #
# The parts of a voice that are not speech commands
# --------------------------------------------------------------------------- #
#: A voice, a variant and an inflection are SETTINGS on the driver. NVDA has
#: no speech command for any of them.
#:
#: **The obvious way to change one mid-utterance does not work, and this
#: module shipped with it.** A `CallbackCommand` looks like the answer - it
#: is what the panner uses - but it is not the same problem. Read out of
#: NVDA's own `speech/manager.py`: a sequence is split at
#: `EndUtteranceCommand` and sent to the synth ONE UTTERANCE AT A TIME, and
#: a callback is turned into an index whose function runs "when the synth
#: reaches this point" - which is when the audio for it has been PLAYED. By
#: then the whole utterance has long since been synthesized, so setting
#: `synth.variant` there changes nothing about the words around it. Asking
#: for the variant "quincy" on the control type did exactly nothing, which
#: is what a user reported.
#:
#: Pitch, rate and volume were never affected: those are `SynthParamCommand`s
#: the synth is HANDED inside the utterance, which is a different mechanism
#: with a different guarantee. That is why three dials worked and three did
#: not.
#:
#: So a part that wants one of these is spoken as its **own utterance**, and
#: the setting is applied by a callback at the END of the utterance before
#: it - the one moment NVDA guarantees is after the previous audio and
#: before the next utterance is handed over.
#:
#: **The first run is the one case that cannot be done that way**, because
#: there is no utterance before it: an utterance made only of commands is
#: built and returned, but its index never reaches the synth, so its
#: callback never runs (`_handleIndex` pops the callback only for an index
#: the synth reported). The only place left is immediately before
#: `speech.speak`, which is what :func:`pending_first` and
#: :func:`speak_sequence` are for.
BY_SETTING = ('voice', 'variant', 'inflection')


def _signature(voice):
    """What this part asks the DRIVER for, or ``{}``. Two parts with the
    same signature share an utterance; a different one starts a new one."""
    return {name: voice[name] for name in BY_SETTING
            if voice.get(name)}


def _boundary(profile):
    """``[apply, end]`` - change the driver, then start a new utterance.

    In this order and never the other way round: the callback has to be the
    last thing in the utterance that is ENDING, so that it fires on that
    utterance's own audio and the change is in place before NVDA hands the
    next one to the synth.
    """
    if compat.CallbackCommand is None or compat.EndUtteranceCommand is None:
        return []
    wanted = dict(profile or {})

    def change():
        try:
            from . import speaking
            speaking.become(wanted)
        except Exception:                            # noqa: BLE001
            pass

    try:
        return [compat.CallbackCommand(change, name='titanVoice'),
                compat.EndUtteranceCommand()]
    except Exception:                                # noqa: BLE001
        return []


#: What the NEXT `speak_sequence` has to put on the driver before it speaks,
#: and when it was worked out. Timestamped because a sequence that was built
#: and never spoken must not lend its voice to whatever is spoken next: a
#: stale answer is thrown away rather than used.
_pending = {'profile': None, 'at': 0.0}
PENDING_SECONDS = 0.5


def pending_first():
    """The first run's driver settings, if the last built sequence had any.

    Consumed: asking clears it, so it can be applied once and only once.
    """
    import time
    profile = _pending['profile']
    fresh = profile is not None and \
        (time.time() - _pending['at']) < PENDING_SECONDS
    _pending['profile'] = None
    return profile if fresh else None


def _remember_first(profile):
    import time
    _pending['profile'] = dict(profile) if profile else None
    _pending['at'] = time.time()


def speak_sequence(sequence):
    """Speak a sequence this module built. ``True`` when it was spoken.

    **The one place a built sequence should be handed to NVDA.** Everything
    inside the sequence takes care of itself; the FIRST run's driver
    settings cannot, for the reason written above, so they are put on here -
    as late as it is possible to put them on, which is immediately before
    the words that want them.
    """
    speech = compat.speech
    if speech is None or not sequence:
        return False
    profile = pending_first()
    if profile:
        try:
            from . import speaking
            speaking.become(profile)
        except Exception:                            # noqa: BLE001
            pass
    try:
        speech.speak(sequence)
        return True
    except Exception:                                # noqa: BLE001
        return False

def sequence(parts, synth=None, separator=','):
    """``[(text, class)]`` -> one NVDA speech sequence.

    **One utterance per VOICE**, and one utterance in the ordinary case
    where every part shares the reader's own voice. That is the promise
    worth keeping - no part cut off by the part after it, which is why
    Titan Access renders them together too - and it can only be kept for
    parts a single utterance can carry.

    A part that asks for a different voice, variant or inflection cannot
    share one: those are settings on the driver, not commands inside the
    utterance, and a driver setting changed by a callback lands after the
    audio around it has already been made. So such a part starts its own
    utterance, and the change is made at the end of the one before it -
    see :data:`BY_SETTING` for why that is the only moment that works.

    Every dial is put back at the end of the part that used it, and every
    driver setting is put back at the end of the sequence. A sequence that
    changed the rate and did not restore it leaves the reader talking that
    way for everything after it, which is the failure this module could
    most easily cause and the one thing it must not.
    """
    parts = [(str(text), tag) for text, tag in (parts or [])
             if str(text or '').strip()]
    _remember_first(None)
    if not parts:
        return []
    if synth is None:
        from . import panner
        synth = panner.current_synth()
    out = []
    standing = {}
    for index, (text, tag) in enumerate(parts):
        # NVDA puts a space between the parts of a sequence itself, so the
        # separator is a bare comma - "text, " gives ",  " and a reader
        # that announces punctuation says the gap.
        if index != len(parts) - 1:
            text = text + separator
        voice = voice_of(tag)
        wanted = _signature(voice)
        if wanted != standing:
            if index == 0:
                # Nothing has been said yet, so there is no utterance to
                # attach a callback to. This one is put on immediately
                # before the words, by `speak_sequence`.
                _remember_first(wanted)
            else:
                out.extend(_boundary(wanted))
            standing = wanted
        on, off = _commands(voice, synth)
        out.extend(on)
        out.append(text)
        out.extend(off)
    if standing:
        # Put the driver back. Not optional and not best effort: a variant
        # left on is every word the reader says afterwards in the wrong
        # voice.
        out.extend(_boundary({}))
    return out


def can_hear_the_difference():
    """Whether this synthesizer takes any of the three dials at all.

    Asked so that a caller can say the WORD instead when the voice cannot
    carry the class - which is the whole reason the words were never taken
    out.
    """
    from . import panner
    synth = panner.current_synth()
    return any(_supported(synth, command)
               for command in (compat.PitchCommand, compat.RateCommand,
                               compat.VolumeCommand))


# --------------------------------------------------------------------------- #
# A whole message, in a voice of its own
# --------------------------------------------------------------------------- #
def say_whole(tag, text, profile=None, interrupt=False):
    """Say one whole thing in the class ``tag``'s voice. True when it did.

    **This is the half a speech command cannot do.** A notification, what
    another program said through the controller, a page being read - each of
    those is a MESSAGE rather than part of a control's reading, and what a
    listener most wants from it is not a bent version of the reading voice
    but a plainly different one: a different voice, a different variant, or
    a different synthesizer altogether, so it is known for what it is before
    a word of it is parsed.

    A different synthesizer is why this exists and why it is separate from
    :func:`sequence`. It cannot be part of an utterance - it is a second
    program producing sound, and the two would talk over each other - so it
    is only ever offered for the classes in :data:`classes.WHOLE`, and this
    is where that is enforced rather than trusted.

    ``False`` means "nothing special was done", and every caller answers it
    by speaking the message the ordinary way. That is the whole degradation
    story: a class with no voice of its own, a synthesizer that will not
    start, an NVDA without the driver - all of them end here, and the user
    hears the message.
    """
    words = str(text or '').strip()
    if not words:
        return False
    try:
        from . import classes
    except Exception:                                # noqa: BLE001
        return False
    if not classes.is_whole(tag):
        return False
    wanted = dict(profile) if profile is not None else classes.voice_of(tag)
    if not str(wanted.get('synth') or '').strip():
        # No synthesizer of its own, so there is nothing here the ordinary
        # path cannot do better: it keeps the message in NVDA's own speech
        # queue, where it can be interrupted and where braille follows it.
        return False
    try:
        from . import speaking
    except Exception:                                # noqa: BLE001
        return False
    if interrupt:
        try:
            speaking.stop()
        except Exception:                            # noqa: BLE001
            pass
    return speaking.speak_with(wanted, words)


def dials_of(tag):
    """A class's profile as the three numbers `prosody.build` understands.

    So a class that names no synthesizer still colours a message: the same
    table, applied through NVDA's own commands, which is what keeps a
    notification recognisable on a machine with one synthesizer.
    """
    profile = voice_of(tag)
    return {name: profile.get(name) or 0
            for name in ('pitch', 'rate', 'volume')}
