# -*- coding: utf-8 -*-
"""What the shared modules ask of the add-on's ``voices`` - here.

The add-on's ``voices.py`` turns a control's parts into NVDA speech
commands (a pitch, a rate, a break per part) and is NVDA's alone, so it
was never vendored - and every walked list here (the palette, the virtual
window, the widget and application reviews) fell back on ``from . import
voices`` failing and said its row as ONE line joined with commas: "OK,
przycisk". This shim answers the same names out of this reader's own
speech, so a row is said the way the reader says a control - each part at
its own tone with the reader's pause between them: "OK" (pause)
"przycisk".
"""

from . import compat, elements

#: The voices the classes ship with - the same numbers `classes.SHIPPED`
#: keeps for exactly this reader, so the class manager shows one table.
try:
    from .classes import SHIPPED as _SHIPPED
    VOICES = {tag: dict(profile) for tag, profile in _SHIPPED.items()}
except Exception:                                    # noqa: BLE001
    VOICES = {}


def voice_of(tag):
    try:
        from . import classes
        return classes.voice_of(tag)
    except Exception:                                # noqa: BLE001
        return dict(VOICES.get(str(tag or ''), {}))


def sequence(parts, synth=None, separator=',', pause_ms=0):
    """``[(text, class)]`` as one utterance of separate parts."""
    return elements.sequence(parts)


def speak_sequence(sequence):
    """Speak a sequence :func:`sequence` built. ``True`` when it went.

    Queued like ``ui.message`` is, so a list's title asked for just before
    its first row is said FIRST - the row follows it after a pause rather
    than overtaking it.
    """
    speech = compat.speech
    if speech is None or not sequence:
        return False

    def speak():
        try:
            speech.speak(sequence)
        except Exception:                            # noqa: BLE001
            pass

    handler = compat.queueHandler
    if handler is not None:
        return bool(handler.queueFunction(handler.eventQueue, speak))
    speak()
    return True


def say_whole(tag, text, profile=None, interrupt=False):
    """A whole utterance in a class's own synthesizer is
    `compat.speech.speak_in_class` here; this answers that it did not."""
    return False


def pending_first():
    return None
