# -*- coding: utf-8 -*-
"""NVDA's `speech`: what an add-on asks to be SAID goes to Titan Access's
own voice - the reader is the one speaking, whichever synthesizer it
speaks with."""

from enum import IntEnum

from . import commands                                          # noqa: F401


class SpeechMode(IntEnum):
    off = 0
    beeps = 1
    talk = 2
    onDemand = 3


speechMode = SpeechMode.talk


def _synth_value(name):
    try:
        from ..synthDriverHandler import getSynth as ours
        synth = ours()
        return int(getattr(synth, name, 50) or 50)
    except Exception:                                # noqa: BLE001
        return 50


def _text_of(sequence):
    parts = []
    for item in sequence or ():
        if isinstance(item, str):
            parts.append(item)
    return ' '.join(part for part in parts if part.strip())


def _reader_say(text, interrupt=False):
    text = str(text or '').strip()
    if not text:
        return
    try:
        from titan_access.engine import get_engine
        get_engine().speak(text, interrupt=bool(interrupt))
    except Exception:                                # noqa: BLE001
        print('[NVDA add-on] (speech) %s' % text)


def speak(speechSequence, symbolLevel=None, priority=None):
    _reader_say(_text_of(speechSequence))


def speakMessage(text, priority=None):
    _reader_say(text)


def speakText(text, reason=None, symbolLevel=None, priority=None):
    _reader_say(text)


def speakSpelling(text, locale=None, useCharacterDescriptions=False,
                  priority=None):
    _reader_say(' '.join(str(text or '')))


def speakObject(obj, reason=None, priority=None):
    try:
        from titan_access.engine import get_engine
        from titan_access import nvda_shape
        get_engine().announce_object(nvda_shape.original_of(obj))
    except Exception:                                # noqa: BLE001
        _reader_say(getattr(obj, 'name', ''))


def cancelSpeech():
    try:
        from titan_access.engine import get_engine
        get_engine().stop_speaking()
    except Exception:                                # noqa: BLE001
        pass


def pauseSpeech(switch):
    pass


def getState():
    class _State(object):
        speechMode = SpeechMode.talk
    return _State()


def setSpeechMode(mode):
    global speechMode
    speechMode = mode


class priorities(object):
    class Spri(IntEnum):
        NORMAL = 0
        NEXT = 1
        NOW = 2


Spri = priorities.Spri


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())


#: What NVDA puts between two chunks of text it hands a synthesizer (two
#: spaces) - Cerence and others join their chunks with it.
CHUNK_SEPARATOR = "  "
