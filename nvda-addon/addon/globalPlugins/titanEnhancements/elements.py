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
#: **These are the DEFAULTS of the classes, not what a reading is built
#: with.** Every part of a control's reading is tagged with the NAME of its
#: semantic class - name, kind, state - so that the voice table is asked
#: for it.
#:
#: It used to be tagged with these numbers, and that is exactly why nothing
#: the user set for the control type ever did anything: a NUMBER is answered
#: with a bare pitch and the table is never looked at. A rate, a voice, a
#: variant, a synthesizer - all of it was written down, shown in the dialog
#: and thrown away at the one moment it mattered. The dials only ever
#: appeared to work because these numbers are what the classes default to.
NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4

#: What is read when the table cannot be asked - outside NVDA, or before
#: the store has been opened. The order this add-on has always used, which
#: is Titan Access's own and NVDA's: the name, then what it is, then its
#: state.
PARTS_FALLBACK = ('name', 'kind', 'state', 'value', 'description', 'place')

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


def _unavailable(obj):
    """Whether this control is there and cannot be used."""
    state = _state('UNAVAILABLE')
    if state is None:
        return False
    try:
        return state in (obj.states or ())
    except Exception:                                # noqa: BLE001
        return False


def _states_of(obj):
    """The states worth saying, in Titan Access's order, in NVDA's words.

    **A state the user has given a SOUND is played rather than said.** That
    is the sound scheme (:mod:`schemes`), and it is applied here because
    here is the one place a control's states are turned into words - so
    there is no second list of states to keep in step, and a state nobody
    has touched goes through exactly as it always did.
    """
    try:
        present = set(obj.states or ())
    except Exception:                                # noqa: BLE001
        present = set()
    # Kept in lockstep - the state's own NAME beside the words NVDA gives
    # it - because a state can be more than one word and matching two lists
    # by position afterwards is how the wrong word gets dropped.
    said = []
    for name in STATE_ORDER:
        state = _state(name)
        if state is None or state not in present:
            continue
        for word in context.state_names([state]):
            if word:
                said.append((name, word))
    if _role_is(obj, *_CHECKABLE):
        checked = _state('CHECKED')
        half = _state('HALFCHECKED')
        if (checked is None or checked not in present) \
                and (half is None or half not in present) \
                and _state('UNCHECKED') is not None:
            for word in context.state_names([_state('UNCHECKED')]):
                if word:
                    said.append(('UNCHECKED', word))
    return _sounded(said)


def _sounded(said):
    """Swap the states the scheme answers with a sound, and play them.

    ``said`` is ``[(state name, word)]``. What comes back is the words that
    are still to be spoken - which for a scheme nobody has touched is all of
    them, unchanged and in the same order.
    """
    if not said:
        return []
    words = [word for _name, word in said]
    try:
        from . import schemes
        keep, sounds = schemes.answer([name for name, _word in said])
    except Exception:                                # noqa: BLE001
        return words
    if not sounds:
        return words
    kept = list(keep)
    out = []
    for name, word in said:
        if name in kept:
            kept.remove(name)            # one word per state answered
            out.append(word)
    try:
        schemes.play(sounds)
    except Exception:                                # noqa: BLE001
        pass
    return out


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
    # **What the user has decided about THIS control, first.** JAWS'
    # customised control, and the reason it comes before everything else
    # is `silent`: a control somebody has switched off must not be
    # described by the reader module, by Titan, or by anything below -
    # asking later would mean working out an announcement in order to
    # throw it away, and would let one of the paths above answer first.
    custom = {}
    try:
        from . import labels
        custom = labels.custom_of(obj)
    except Exception:                                # noqa: BLE001
        custom = {}
    if custom.get('silent'):
        return []
    # Which Titan add-on's window this is, if any - worked out once and used
    # twice, because asking it is a lookup and an unbound name here would
    # silently cost the status-bar wording below.
    _application = None
    try:
        # **What a Titan application says its own row is.** A row of the
        # file manager's list is a file or a folder, with a date and a
        # type beside it, and NVDA reading it as "list item" throws all of
        # that away. The application knows; Titan knows which process the
        # application is; so this is asked before anything is guessed.
        from . import semantics
        known, _application = semantics.describe(obj)
        if known:
            return known
    except Exception:                                # noqa: BLE001
        pass
    try:
        # **Every part is worked out, and the ORDER is the user's.**
        #
        # "Checked, check box" and "check box, checked" are the same three
        # facts in two orders, and which is right is a matter of what
        # somebody is used to - JAWS, NVDA, Window-Eyes and Titan Access do
        # not agree, and neither do two users of any one of them. So this
        # builds a part at a time into a table and `classes.parts_read()`
        # says which of them are wanted and in what order. A part that is
        # switched off is not built at all, so an unwanted one costs
        # nothing rather than being made and thrown away.
        made = {}

        def part(name, build):
            if name in wanted and name not in made:
                try:
                    made[name] = build() or []
                except Exception:                    # noqa: BLE001
                    made[name] = []

        try:
            from . import classes
            wanted = classes.parts_read()
        except Exception:                            # noqa: BLE001
            wanted = list(PARTS_FALLBACK)

        name = _name_of(obj)

        def _the_name():
            # Emacspeak's own case, and the clearest one for saying a class
            # with the VOICE: a control that cannot be used is heard as
            # unusable before the word arrives, and in a menu of twenty
            # items that is twenty times the word is not needed.
            voice = str(custom.get('voice') or '').strip()
            if not voice:
                voice = 'disabled' if _unavailable(obj) else 'name'
            return [(name, voice)] if name else []

        def _the_kind():
            role = context.role_name(getattr(obj, 'role', None))
            try:
                # **What TITAN calls this control**, where Titan calls it
                # something NVDA's role name cannot know - a slot of the
                # status bar arrives as a list item, because that is what
                # Titan's status bar is built out of. Titan Access has
                # always said "status bar item" there, and a user moving
                # between the two readers must not have to learn two
                # vocabularies for one desktop.
                from . import tce
                role = tce.role_word(obj, _application, role)
            except Exception:                        # noqa: BLE001
                pass
            try:
                # **"Unknown" is not a kind of control, it is the absence
                # of an answer.** NVDA spells a top-level window it cannot
                # classify `Role.UNKNOWN`, whose displayString is the word
                # "unknown" in the user's own language - measured live on
                # a real session: "ELTEN 3.0.3, nieznane". That tells the
                # user nothing at the one moment they most need telling,
                # and something IS knowable: Windows will say whether this
                # is an application, a game, a little box that will go
                # away again, the desktop, or a dialog. So the word is
                # replaced rather than added to - two type words for one
                # control is worse than the wrong one.
                from . import windowKind
                if windowKind.is_unknown_word(role):
                    kind, _how = windowKind.kind_of(obj)
                    role = windowKind.word(kind) or role
            except Exception:                        # noqa: BLE001
                pass
            # **What the user calls it wins.** A "pane" the program uses
            # as a toolbar is a toolbar to the person using it, and they
            # are the one who has to hear it on every arrival.
            said = str(custom.get('role_word') or '').strip()
            if said:
                role = said
            return [(role, 'kind')] if role else []

        def _the_state():
            return [(state, 'state') for state in _states_of(obj)]

        def _the_value():
            try:
                value = str(obj.value or '').strip()
            except Exception:                        # noqa: BLE001
                return []
            # NVDA folds a control's value into what it reads as the name
            # for some controls, and saying it twice is worse than not
            # saying it at all.
            return [(value, 'value')] if value and value != name else []

        def _the_description():
            try:
                described = str(obj.description or '').strip()
            except Exception:                        # noqa: BLE001
                return []
            return [(described, 'description')] if described and \
                described != name else []

        def _the_place():
            return [(extra, 'place') for extra in _position_of(obj)]

        part('name', _the_name)
        part('kind', _the_kind)
        part('state', _the_state)
        part('value', _the_value)
        part('description', _the_description)
        part('place', _the_place)

        segments = []
        for chosen in wanted:
            segments.extend(made.get(chosen) or [])
        # **A note ADDS; a label replaces.** That is the whole difference
        # between the two, and it is why a note is said last and always:
        # it is what somebody wanted said about this control that nothing
        # else was going to say.
        note = str(custom.get('note') or '').strip()
        if note:
            segments.append((note, 'detail'))
        if not segments:
            # Something has to be said. A control with no name, and whose
            # every other part the user has switched off, would otherwise
            # be read as silence - which is a reader that has stopped
            # working, not a reader obeying a preference.
            segments = made.get('kind') or _the_kind()
            segments = [(text, 'kind') for text, _voice in segments]
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
    from . import voices
    if not can_pitch() and not voices.can_hear_the_difference():
        return [', '.join(str(text) for text, _voice in segments)]
    # One builder for every part of this add-on that speaks. A segment
    # carries either a bare pitch (Titan's own -10..10, which is what
    # arrives over the wire) or the NAME of a semantic class - a folder, a
    # detail, a disabled control - which is a whole voice rather than one
    # dial. `voices.voice_of` reads both, so nothing had to be respelled.
    return voices.sequence(segments)


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
