# -*- coding: utf-8 -*-
"""What the shared modules ask of the add-on's ``elements`` - here.

The add-on's ``elements.py`` is the NVDA half of describing a control: it
reads NVDA's role and state enums, builds an NVDA speech sequence out of
pitched parts, and asks NVDA's synthesizer whether it can pitch at all.
None of that is portable and it was never vendored - so the virtual
window, the widget review and the application review, which ask it for
the states of a row and for one utterance out of pitched parts, failed on
``cannot import name 'elements'`` the moment they were opened here.

This is the shim beside the shared modules (like ``i18n``, ``compat`` and
``link``): the same names, answered out of this reader's own tables. A
state is looked up in Titan Access's own catalogue; a sequence is the
words of the parts, which ``compat.speech`` says as one line; and the
tones are the ones ``accessible.describe`` uses, so a row read through
the virtual window sounds like the same row read on the focus path.
"""

from . import i18n

_ = i18n.install(globals())

NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4
DETAIL_PITCH = -2

PARTS_FALLBACK = ('name', 'kind', 'state', 'value', 'description', 'place')

#: The states worth saying, in the order Titan Access says them.
STATE_ORDER = (
    'CHECKED', 'HALFCHECKED', 'PRESSED', 'SELECTED', 'EXPANDED', 'COLLAPSED',
    'UNAVAILABLE', 'READONLY', 'REQUIRED', 'BUSY', 'HASPOPUP', 'PROTECTED',
)

_CHECKABLE = ('CHECKBOX', 'CHECKMENUITEM')

#: NVDA's state names -> this reader's state keys.
_TO_KEY = {
    'CHECKED': 'checked', 'HALFCHECKED': 'partially_checked',
    'PRESSED': 'pressed', 'SELECTED': 'selected', 'EXPANDED': 'expanded',
    'COLLAPSED': 'collapsed', 'UNAVAILABLE': 'unavailable',
    'READONLY': 'readonly', 'REQUIRED': 'required', 'BUSY': 'busy',
    'HASPOPUP': 'haspopup', 'PROTECTED': 'protected',
    'UNCHECKED': 'unchecked',
}


def _text(value):
    return str(value or '').strip()


def _state_word(name):
    try:
        from .. import localization
        word = localization.state_label(_TO_KEY.get(name, name.lower()))
    except Exception:                                # noqa: BLE001
        word = ''
    if word and word != _TO_KEY.get(name, name.lower()):
        return word
    return name.lower().replace('_', ' ')


def _names_of(states):
    """The upper-case NAMES of an object's states, whatever they are."""
    out = []
    for state in states or ():
        name = getattr(state, 'name', None)
        out.append(_text(name if name is not None else state).upper())
    return out


def _role_is(obj, *names):
    role = getattr(obj, 'role', None)
    have = _text(getattr(role, 'name', None) if role is not None
                 and hasattr(role, 'name') else role).upper()
    return have in names


def _name_of(obj):
    """The name, with the value after it where a control has both."""
    name = _text(getattr(obj, 'name', ''))
    try:
        value = _text(obj.value)
    except Exception:                                # noqa: BLE001
        value = ''
    if value and value != name:
        return '%s, %s' % (name, value) if name else value
    return name


def _unavailable(obj):
    try:
        return 'UNAVAILABLE' in _names_of(obj.states)
    except Exception:                                # noqa: BLE001
        return False


def _states_of(obj):
    """The states worth saying, in Titan Access's order, in its words.

    A state the user has given a SOUND is played rather than said - the
    sound scheme (:mod:`schemes`), applied here as the add-on applies it
    in its own ``elements``.
    """
    try:
        present = set(_names_of(obj.states))
    except Exception:                                # noqa: BLE001
        present = set()
    said = []
    for name in STATE_ORDER:
        if name in present:
            said.append((name, _state_word(name)))
    if _role_is(obj, *_CHECKABLE) and 'CHECKED' not in present \
            and 'HALFCHECKED' not in present:
        said.append(('UNCHECKED', _state_word('UNCHECKED')))
    return _sounded(said)


def _sounded(said):
    try:
        from . import schemes
    except Exception:                                # noqa: BLE001
        return [word for _name, word in said]
    try:
        words, sounds = schemes.answer([name for name, _word in said])
        if sounds:
            schemes.play(sounds)
    except Exception:                                # noqa: BLE001
        return [word for _name, word in said]
    kept = list(words or [])
    out = []
    for name, word in said:
        if name in kept:
            kept.remove(name)
            out.append(word)
    return out


def _position_of(obj):
    """"3 of 10" and "level 2", as the control reports them."""
    out = []
    try:
        index = int(getattr(obj, 'positionInfo', {}).get('indexInGroup', 0)
                    or 0)
        count = int(getattr(obj, 'positionInfo', {}).get('similarItemsInGroup',
                                                           0) or 0)
    except Exception:                                # noqa: BLE001
        index = count = 0
    if index and count:
        # Translators: a row's place in its list.
        out.append(_('{index} of {count}').format(index=index, count=count))
    return out


def describe(obj):
    """``[(text, voice class)]`` for a control - the shape the add-on's
    ``elements.describe`` answers, out of this reader's own describer."""
    if obj is None:
        return []
    original = getattr(obj, 'original', obj)
    try:
        from .. import accessible
        from ..settings_store import get_settings
        made = accessible.describe(original, get_settings())
    except Exception:                                # noqa: BLE001
        made = []
    out = []
    for seg in made:
        text = _text(seg[0]) if seg else ''
        pitch = seg[1] if len(seg) > 1 else NAME_PITCH
        if text:
            out.append((text, pitch))
    return out


def sequence(segments):
    """The parts as one utterance. There are no speech commands here, so
    it is the words joined - and `compat.speech.speak` says a list of
    strings as one line, nothing dropped."""
    if not segments:
        return []
    words = []
    for seg in segments:
        try:
            text = _text(seg[0])
        except Exception:                            # noqa: BLE001
            text = _text(seg)
        if text:
            words.append(text)
    return [', '.join(words)] if words else []


def can_pitch():
    """Whether a sequence carries tones. Here it never does: the tones are
    applied by the engine's own concatenated speech, not by a command."""
    return False
