# -*- coding: utf-8 -*-
"""Understanding a spoken/typed playback position.

"Play from 50%", "from 49 minutes", "1:23:45", "chapter 3, 12 min" - the
player, the startup argument and Titan's AI tools all accept the same forms,
so however the user says where to start, it is parsed in exactly one place.

A position is parsed into ``(kind, value, track)``:
* ``kind='ms'``      - an absolute time in milliseconds;
* ``kind='percent'`` - a share of the item, which can only be turned into a
  time once VLC knows the length, so it is carried unresolved until then;
* ``track``          - an optional 0-based track for an audiobook
  ("chapter 3"), None when the user did not name one.

Both Polish and English wording is accepted: this is a Polish-first program
whose AI assistant speaks either language.
"""

import re

_TRACK_WORDS = r'(?:track|tracks|sciezka|ścieżka|sciezke|ścieżkę|utwor|utwór|' \
               r'chapter|rozdzial|rozdział|czesc|część|plik|file)'
_TRACK_RE = re.compile(_TRACK_WORDS + r'\s*(?:nr\.?|no\.?|#)?\s*(\d+)')
_PERCENT_RE = re.compile(r'^(\d+(?:[.,]\d+)?)\s*(?:%|proc\w*|percent\w*)$')
_CLOCK_RE = re.compile(r'^(\d{1,3}):([0-5]?\d)(?::([0-5]?\d))?$')
# The unit must not run into another letter ("1h20m" is one hour twenty, not
# a stray "h20m" word), but a digit may follow it directly.
_UNIT_RE = re.compile(r'(\d+(?:[.,]\d+)?)\s*'
                      r'(godzin\w*|godz\w*|hours?|hrs?|h|'
                      r'minut\w*|minutes?|mins?|min|m|'
                      r'sekund\w*|seconds?|secs?|sec|sek\w*|s)'
                      r'(?![a-ząćęłńóśźż])')
_BARE_RE = re.compile(r'^(\d+(?:[.,]\d+)?)$')

_HOUR = 3600000
_MINUTE = 60000
_SECOND = 1000


def _number(text):
    return float(text.replace(',', '.'))


def _unit_ms(value, unit):
    if unit.startswith(('h', 'g')):
        return value * _HOUR
    if unit.startswith('s'):
        return value * _SECOND
    return value * _MINUTE


def parse_position(text):
    """``(kind, value, track)`` or None when nothing was understood."""
    raw = (text or '').strip().lower()
    if not raw:
        return None

    track = None
    match = _TRACK_RE.search(raw)
    if match:
        track = max(0, int(match.group(1)) - 1)
        raw = (raw[:match.start()] + ' ' + raw[match.end():]).strip()
        raw = raw.strip(' ,;:-')
        if not raw:
            # "chapter 3" alone: the start of that track.
            return ('ms', 0, track)

    match = _PERCENT_RE.match(raw)
    if match:
        return ('percent', max(0.0, min(100.0, _number(match.group(1)))), track)

    match = _CLOCK_RE.match(raw)
    if match:
        first, second, third = match.groups()
        if third is None:                       # M:SS
            ms = int(first) * _MINUTE + int(second) * _SECOND
        else:                                   # H:MM:SS
            ms = int(first) * _HOUR + int(second) * _MINUTE + int(third) * _SECOND
        return ('ms', ms, track)

    units = _UNIT_RE.findall(raw)
    if units:
        total = sum(_unit_ms(_number(value), unit) for value, unit in units)
        return ('ms', int(total), track)

    match = _BARE_RE.match(raw)
    if match:
        # A bare number is minutes - "play from 49" means 49 minutes.
        return ('ms', int(_number(match.group(1)) * _MINUTE), track)

    return None


def resolve_position(parsed, length_ms=0):
    """Milliseconds for ``parsed``, or None when a percentage cannot be
    turned into a time yet because the length is still unknown."""
    if not parsed:
        return None
    kind, value, _track = parsed
    if kind == 'ms':
        return max(0, int(value))
    if not length_ms or length_ms <= 0:
        return None
    return max(0, min(int(length_ms - 1000), int(length_ms * value / 100.0)))


def describe_position(parsed):
    """Short human form of what was understood (for announcements)."""
    if not parsed:
        return ''
    kind, value, _track = parsed
    if kind == 'percent':
        return '%g%%' % value
    total = int(max(0, value)) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return '%d:%02d:%02d' % (hours, minutes, seconds)
    return '%d:%02d' % (minutes, seconds)
