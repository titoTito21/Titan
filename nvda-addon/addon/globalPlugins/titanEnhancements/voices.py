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
def _commands(voice, synth):
    """The speech commands for one voice, and the ones to put it back."""
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
    named, restore = _named_commands(voice, synth)
    if named is not None:
        # In FRONT of the dials, and put back after them: a synthesizer
        # that resets its rate when its voice changes would otherwise be
        # handed the rate first and throw it away.
        on.insert(0, named)
        off.append(restore)
    return on, off


#: The parts of a voice NVDA has no speech command for. `PitchCommand` and
#: its two neighbours are real commands the synthesizer is HANDED; a voice,
#: a variant and an inflection are SETTINGS on the driver, and the only way
#: to change one part-way through an utterance is to reach in and set it at
#: the moment the speech gets there. That is what `CallbackCommand` is, and
#: it is the same mechanism the panner uses for the same reason.
#:
#: What it costs, said plainly: a synthesizer that flushes its buffer when
#: its voice changes will break the utterance at that point. That is the
#: synth's behaviour rather than a fault here, it is why the DIALS are
#: preferred wherever they will do, and it is why a whole message (see
#: `classes.WHOLE`) is spoken by a driver of our own instead.
BY_SETTING = ('voice', 'variant', 'inflection')


def _named_commands(voice, synth):
    """``(set, put back)`` for the parts that are driver settings, or
    ``(None, None)`` when this voice asks for none of them."""
    wanted = {name: voice.get(name) for name in BY_SETTING
              if voice.get(name)}
    if not wanted or compat.CallbackCommand is None or synth is None:
        return None, None
    try:
        from . import speaking
    except Exception:                                # noqa: BLE001
        return None, None
    held = {}

    def put_on():
        held.clear()
        try:
            held.update(speaking.apply_to(synth, wanted))
        except Exception:                            # noqa: BLE001
            pass

    def put_back():
        try:
            speaking.put_back(synth, dict(held))
        except Exception:                            # noqa: BLE001
            pass
        held.clear()

    try:
        return (compat.CallbackCommand(put_on, name='titanVoiceOn'),
                compat.CallbackCommand(put_back, name='titanVoiceOff'))
    except Exception:                                # noqa: BLE001
        return None, None


def sequence(parts, synth=None, separator=','):
    """``[(text, class)]`` -> one NVDA speech sequence.

    ONE utterance, so no part can be cut off by the part after it - which
    is the promise a reader saying three separate lines cannot make, and
    the reason Titan Access renders them together too.

    Every dial is put back at the end of the part that used it. A sequence
    that changed the rate and did not restore it leaves the reader talking
    that way for everything after it, which is the failure this module
    could most easily cause and the one thing it must not.
    """
    parts = [(str(text), tag) for text, tag in (parts or [])
             if str(text or '').strip()]
    if not parts:
        return []
    if synth is None:
        from . import panner
        synth = panner.current_synth()
    out = []
    for index, (text, tag) in enumerate(parts):
        # NVDA puts a space between the parts of a sequence itself, so the
        # separator is a bare comma - "text, " gives ",  " and a reader
        # that announces punctuation says the gap.
        if index != len(parts) - 1:
            text = text + separator
        on, off = _commands(voice_of(tag), synth)
        out.extend(on)
        out.append(text)
        out.extend(off)
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
