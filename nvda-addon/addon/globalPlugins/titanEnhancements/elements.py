# -*- coding: utf-8 -*-
"""A control, read the way Titan Access reads one: three parts, three tones.

Titan's own reader does not say "Save button" in one breath. It says the
NAME at the neutral tone, the CONTROL TYPE a little lower and the STATE a
little higher, and that is not decoration - it is how somebody working by
ear tells a button called "Save" from a list item called "Save button",
without either being labelled out loud. A user who has spent a year in
Titan hears the shape before they hear the words.

NVDA says all of it at one pitch, so moving from Titan Access to NVDA loses
the shape. This module rebuilds it, and the numbers, the order and the list
of states are **read out of Titan Access** (`titan_access/accessible.py`)
rather than chosen here: two readers on one desktop that disagree about
what a control sounds like is worse than one that is merely flat.

    name (+ value)      @  0
    control type        @ -4
    states              @ +4
    description         @  0
    "3 of 10"           @  0
    "level 2"           @  0

**The words are NVDA's own.** The role and the states are asked of
`controlTypes`, so they are the user's language and the vocabulary their
reader already uses - Titan translating them again would be a second set of
words for one screen.

**Focus is implied and never said.** `_STATE_ORDER` is Titan Access's list,
and "focusable" and "focused" are deliberately not in it: everything the
reader reports has the focus, so saying so is noise on every single control.
"""

from . import compat
from . import context

#: Titan Access's own pitches (`titan_access/accessible.py`).
NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4

#: The states Titan Access says, in the order it says them. Names as NVDA's
#: `controlTypes.State` spells them; anything this NVDA has not got is
#: skipped rather than being an error, because the set moves between
#: versions.
STATE_ORDER = (
    'SELECTED', 'CHECKED', 'HALFCHECKED', 'EXPANDED', 'COLLAPSED',
    'PRESSED', 'UNAVAILABLE', 'READONLY', 'REQUIRED', 'PROTECTED',
    'BUSY', 'HASPOPUP', 'OFFSCREEN',
)

#: Roles for which "not checked" is worth saying. A check box that is
#: neither checked nor half checked carries no state at all, so its state
#: would be silent - and the state of a check box is the whole of what it
#: is for.
_CHECKABLE = ('CHECKBOX', 'CHECKMENUITEM')


def _state(name):
    types = compat.controlTypes
    if types is None:
        return None
    state = getattr(types, 'State', None)
    if state is None:
        return None
    return getattr(state, name, None)


def _role_is(obj, *names):
    for name in names:
        types = compat.controlTypes
        role = getattr(getattr(types, 'Role', None), name, None) \
            if types is not None else None
        if role is not None and getattr(obj, 'role', None) == role:
            return True
    return False


def _name_of(obj):
    """The name, with the value after it where a control has both.

    A field is its name AND what is in it, and Titan Access says both at the
    neutral tone because they are one thing: "Address, titosoft.com".
    """
    name = str(getattr(obj, 'name', '') or '').strip()
    try:
        value = str(obj.value or '').strip()
    except Exception:                                # noqa: BLE001
        value = ''
    if value and value != name:
        return f'{name}, {value}' if name else value
    return name


def _states_of(obj):
    """The states worth saying, in Titan Access's order, in NVDA's words."""
    try:
        present = set(obj.states or ())
    except Exception:                                # noqa: BLE001
        present = set()
    words = []
    for name in STATE_ORDER:
        state = _state(name)
        if state is not None and state in present:
            words.extend(context.state_names([state]))
    if _role_is(obj, *_CHECKABLE):
        checked = _state('CHECKED')
        half = _state('HALFCHECKED')
        if (checked is None or checked not in present) \
                and (half is None or half not in present):
            words.extend(context.state_names([_state('UNCHECKED')])
                         if _state('UNCHECKED') is not None else [])
    return [word for word in words if word]


def _position_of(obj):
    """"3 of 10" and "level 2", in NVDA's own words where it has them."""
    try:
        info = obj.positionInfo or {}
    except Exception:                                # noqa: BLE001
        return []
    out = []
    index = info.get('indexInGroup')
    count = info.get('similarItemsInGroup')
    if index and count:
        out.append(_of(index, count))
    level = info.get('level')
    if level:
        out.append(_level(level))
    return out


def _of(index, count):
    try:
        import translationHandler                    # noqa: F401
    except Exception:                                # noqa: BLE001
        pass
    # NVDA's own wording for this is built inside its speech module and is
    # not offered as a function, so the shape is written out. It is the one
    # string here that is not NVDA's own, which is why it is a translatable
    # message of the add-on's rather than a bare format.
    from . import i18n
    translate = i18n.install({})
    # Translators: an item's place in a list, e.g. "3 of 10".
    return translate('{index} of {count}').format(index=index, count=count)


def _level(level):
    from . import i18n
    translate = i18n.install({})
    # Translators: how deep an item is in a tree, e.g. "level 2".
    return translate('level {level}').format(level=level)


def describe(obj):
    """``[(text, pitch)]`` for one control, or ``[]`` when there is nothing.

    Never raises: it is called from a focus handler, and an exception there
    is a reader that has stopped reporting.
    """
    if obj is None:
        return []
    try:
        segments = []
        name = _name_of(obj)
        if name:
            segments.append((name, NAME_PITCH))
        role = context.role_name(getattr(obj, 'role', None))
        if role:
            segments.append((role, ROLE_PITCH))
        for state in _states_of(obj):
            segments.append((state, STATE_PITCH))
        try:
            description = str(obj.description or '').strip()
        except Exception:                            # noqa: BLE001
            description = ''
        if description and description != name:
            segments.append((description, NAME_PITCH))
        for extra in _position_of(obj):
            segments.append((extra, NAME_PITCH))
        if not segments and role:
            segments.append((role, NAME_PITCH))
        return segments
    except Exception:                                # noqa: BLE001
        return []


def sequence(segments):
    """The segments as one NVDA speech sequence, each part at its own tone.

    ONE utterance, so no part can be cut off by the part after it - which is
    the thing a reader saying three separate lines cannot promise, and the
    reason Titan Access renders them together too.

    **The pitches are CONVERTED, not passed through.** Titan says -10..10;
    NVDA's `PitchCommand` offsets its own 0..100 setting, so Titan's -4
    handed over unchanged is a four-point change on a hundred-point scale -
    which is a difference nobody can hear. It was written that way, and what
    reached the user was three parts at what sounded like one tone. `prosody`
    is the one place that knows the conversion (`SCALE`), so it does it here
    too rather than the number being scaled in two places by hand.
    """
    if not segments:
        return []
    from . import prosody
    if not can_pitch():
        return [', '.join(text for text, _pitch in segments)]
    out = []
    for index, (text, pitch) in enumerate(segments):
        out.append(compat.PitchCommand(offset=prosody._offset(pitch)))
        # NVDA puts a space between the parts of a sequence itself, so the
        # separator is a bare comma - "text, " gives ",  " and a reader that
        # announces punctuation says the gap.
        out.append(text if index == len(segments) - 1 else text + ',')
    out.append(compat.PitchCommand(offset=0))
    return out


def can_pitch():
    """Whether the three tones are really three tones on this NVDA.

    Asks the SYNTHESIZER, not only NVDA: a driver that does not declare
    `PitchCommand` has it dropped silently, and the parts then come out at
    one tone with nothing saying why.
    """
    if compat.PitchCommand is None:
        return False
    from . import panner
    synth = panner.current_synth()
    if synth is None:
        return False
    try:
        return compat.PitchCommand in synth.supportedCommands
    except Exception:                                # noqa: BLE001
        return False
