# -*- coding: utf-8 -*-
"""Punctuation, capital letters and numbers: how text is turned into words.

A character read on its own always says its name - that is what a reader
is for. Inside TEXT - a line, a word, a typed echo, a document read
continuously - how much punctuation is said is a level the user chooses
(``Symbols/PunctuationLevel``: none, some, most, all), the way every
screen reader has it: at *some* a full stop and a comma are said and a
hash is not; at *all* every symbol is a word.

A capital letter is said as the user chose (``Symbols/CapitalLetters``):
nothing, the word "capital" in front, a short beep, or a higher pitch -
which is what Titan Access's own three-tone announcements make cheap. A
number is read whole, digit by digit, or in pairs (``Symbols/NumbersAs``).

Everything here is pure text: no wx, no Win32, the same on Linux.
"""

import re

from titan_access import localization as loc

LEVELS = ('none', 'some', 'most', 'all')

#: The level at which a symbol starts being SAID inside text. Everything
#: not listed is a word at 'all' only.
_SOME = set('.,!?@')
_MOST = set(';:-=+*/#$%&()"')
_ALL_ONLY = set('_\\^[]{}<>\'`~|')

_DIGITS = re.compile(r'\d{2,}')


def _rank(level):
    try:
        return LEVELS.index(str(level or 'some').strip().lower())
    except ValueError:
        return 1


def level_of_symbol(ch):
    """'some' | 'most' | 'all' - at which level the symbol is spoken; ''
    for a character that is not a symbol."""
    if ch in _SOME:
        return 'some'
    if ch in _MOST:
        return 'most'
    if ch in _ALL_ONLY:
        return 'all'
    return ''


def name_of(ch):
    """The spoken name of one symbol in the reader's language, or ''."""
    try:
        found = loc._special_chars().get(ch)
    except Exception:                                # noqa: BLE001
        found = None
    return found or ''


def spoken_at(ch, level):
    """Whether *ch*, inside text, is said as a word at *level*."""
    own = level_of_symbol(ch)
    if not own:
        return False
    return _rank(own) <= _rank(level)


def digits(text, mode):
    """A run of digits as the mode wants: whole, 'digits' one by one,
    'pairs' two by two from the left."""
    mode = str(mode or 'whole').strip().lower()
    if mode == 'digits':
        return _DIGITS.sub(lambda m: ' '.join(m.group(0)), text)
    if mode == 'pairs':
        def pair(match):
            run = match.group(0)
            return ' '.join(run[i:i + 2] for i in range(0, len(run), 2))
        return _DIGITS.sub(pair, text)
    return text


def process_text(text, level='some', numbers='whole'):
    """Text as it is to be spoken: symbols at or below *level* said as
    their names, digits grouped as *numbers* wants. Space and newline
    are never named inside text - they are the pauses."""
    if not text:
        return text
    out = []
    for ch in text:
        if ch in (' ', '\n', '\r', '\t'):
            out.append(ch)
        elif spoken_at(ch, level):
            out.append(' %s ' % (name_of(ch) or ch))
        else:
            out.append(ch)
    said = ''.join(out)
    said = digits(said, numbers)
    return re.sub(r'[ \t]{2,}', ' ', said).strip()


def trim_leading(text):
    """``(text without its indent, indent length)``."""
    stripped = text.lstrip(' \t')
    return stripped, len(text) - len(stripped)


# --------------------------------------------------------------------------- #
# What the settings say
# --------------------------------------------------------------------------- #
def punctuation_level(settings):
    try:
        return str(settings.get('Symbols', 'PunctuationLevel', 'some') or 'some')
    except Exception:                                # noqa: BLE001
        return 'some'


def numbers_mode(settings):
    try:
        return str(settings.get('Symbols', 'NumbersAs', 'whole') or 'whole')
    except Exception:                                # noqa: BLE001
        return 'whole'


def capital_mode(settings):
    try:
        return str(settings.get('Symbols', 'CapitalLetters', 'pitch') or 'pitch')
    except Exception:                                # noqa: BLE001
        return 'pitch'


def capital_pitch(settings):
    try:
        return max(1, min(10, int(settings.get_int('Symbols', 'CapitalPitchOffset', 3))))
    except Exception:                                # noqa: BLE001
        return 3


def trim_wanted(settings):
    try:
        return bool(settings.get_bool('Symbols', 'TrimLeadingWhitespace', True))
    except Exception:                                # noqa: BLE001
        return True


def text_for_speech(text, settings):
    """A line or a word, as the settings want it said."""
    return process_text(text, punctuation_level(settings), numbers_mode(settings))


def describe_char(ch, settings, phonetic=False):
    """How ONE character is to be said: ``(text, pitch offset, beep)``.

    The name of a symbol always; a letter by itself or phonetically; a
    capital as the setting says - the word in front, a beep beside, a
    higher pitch, or nothing of the kind.
    """
    if not ch:
        return '', 0, False
    text = name_of(ch)
    is_capital = ch.isalpha() and ch.isupper()
    if not text:
        if phonetic and ch.isalpha():
            text = loc.phonetic_letter(ch.lower())
        else:
            text = ch.lower() if is_capital else ch
    pitch = 0
    beep = False
    if is_capital:
        mode = capital_mode(settings)
        if mode == 'word':
            text = loc.L('symbols.capital', text)
        elif mode == 'beep':
            beep = True
        elif mode == 'pitch':
            pitch = capital_pitch(settings)
    return text, pitch, beep
