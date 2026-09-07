# -*- coding: utf-8 -*-
"""Titan's own cursor cues, played for what NVDA has just landed on.

Titan Access plays a sound for every element the focus reaches, and the
sound says three things at once before a word is spoken: WHAT it is
(``cursor.ogg`` for something you can act on, ``cursor_static.ogg`` for
something you can only read, ``caninteract.ogg`` for a pane you can enter),
WHERE it is (panned to the middle of the control, across the screen), and
for a list item WHERE IN THE LIST it is - the tone falls from 1.5 at the
top to 0.7 at the bottom, with ``edge.ogg`` at the first and last. Somebody
who works this way is oriented before the name arrives.

The rules and the numbers are Titan Access's own (``engine.py``'s
``_play_element_cue``, ``sound_manager.play_list_item``), including the one
that is easy to get backwards:

**Inside Titan's own windows, no cue is played.** Titan already plays its
own navigation sounds there, and a second set on top is clutter, not
information - Titan Access suppresses its cues in exactly the same place and
for exactly the same reason. So this is for everywhere ELSE: NVDA reading
the rest of the machine, with Titan's sounds.

It is **off by default**. It changes what every focus change on the whole
machine sounds like, which is not something to switch on for somebody
without being asked - and it needs Titan running, since Titan owns the
mixer, the theme and the 3D positioning.

**One thread, one slot, newest wins.** A focus event is not rare - holding
an arrow key down produces them faster than a round trip to Titan - so the
cue is handed to a worker with room for exactly one pending sound. A cue
that has been overtaken is not worth playing late; dropping it is what
keeps this from queueing behind itself.
"""

import threading

from . import compat

#: The cue for a control you can act on, one you can only read, and a
#: container object navigation has stepped into. Titan Access's own names.
SND_CURSOR = 'cursor.ogg'
SND_CURSOR_STATIC = 'cursor_static.ogg'
SND_CAN_INTERACT = 'caninteract.ogg'
SND_LIST_ITEM = 'listitem.ogg'
SND_EDGE = 'edge.ogg'

#: Roles that get the interactive cue (`_INTERACTIVE_ROLES` in engine.py).
INTERACTIVE = frozenset({
    'BUTTON', 'SPLITBUTTON', 'CHECKBOX', 'RADIOBUTTON', 'COMBOBOX', 'EDITABLETEXT',
    'SLIDER', 'SPINBUTTON', 'LINK', 'MENUITEM', 'MENUBAR', 'TAB',
    'SCROLLBAR', 'TABCONTROL', 'TOGGLEBUTTON', 'MENUBUTTON',
})

#: Roles that are a row in a collection (`_LIST_ITEM_ROLES`).
LIST_ITEM = frozenset({'LISTITEM', 'TREEVIEWITEM', 'TABLECELL', 'DATAITEM'})

#: A container you have stepped into rather than a control.
CONTAINER = frozenset({'PANE', 'GROUPING'})

#: The list-item tone: top of the list high, bottom low. Titan Access's
#: `play_list_item` - `1.5 - position * 0.8` - and the C# before it.
PITCH_TOP = 1.5
PITCH_SPAN = 0.8

_LOCK = threading.RLock()
_pending = None
_wake = threading.Event()
_worker = None
_running = False
_played = 0


# --------------------------------------------------------------------------- #
# What to play for this object
# --------------------------------------------------------------------------- #
def _role_name(obj):
    role = getattr(obj, 'role', None)
    return str(getattr(role, 'name', '') or '').upper()


def pan_for(obj):
    """Where the control is across the screen, -1 .. 1.

    The same mapping Titan Access uses (`pan_for_x`): the middle of the
    control against the width of the screen.
    """
    try:
        left, top, width, height = obj.location
    except Exception:                                # noqa: BLE001
        return 0.0
    if not width:
        return 0.0
    try:
        import api
        desktop = api.getDesktopObject()
        screen = desktop.location[2] if desktop is not None else 0
    except Exception:                                # noqa: BLE001
        screen = 0
    if not screen:
        return 0.0
    centre = left + width / 2.0
    return max(-1.0, min(1.0, (centre / float(screen)) * 2.0 - 1.0))


def list_pitch(index, count):
    """The tone for a row: the top of the list high, the bottom low."""
    if not count or count <= 1 or not index:
        return PITCH_TOP - PITCH_SPAN / 2.0
    where = (index - 1) / float(count - 1)
    return PITCH_TOP - max(0.0, min(1.0, where)) * PITCH_SPAN


def cues_for(obj, for_navigation=False):
    """``[(name, pan, pitch)]`` for one object - Titan Access's own rules."""
    if obj is None:
        return []
    role = _role_name(obj)
    pan = pan_for(obj)
    if role in LIST_ITEM:
        try:
            info = obj.positionInfo or {}
        except Exception:                            # noqa: BLE001
            info = {}
        index = info.get('indexInGroup') or 0
        count = info.get('similarItemsInGroup') or 0
        out = [(SND_LIST_ITEM, pan, list_pitch(index, count))]
        # The ends of a list are worth knowing without counting.
        if index and count and index in (1, count):
            out.append((SND_EDGE, pan, 1.0))
        return out
    if for_navigation and role in CONTAINER:
        return [(SND_CAN_INTERACT, pan, 1.0)]
    if role in INTERACTIVE:
        return [(SND_CURSOR, pan, 1.0)]
    return [(SND_CURSOR_STATIC, pan, 1.0)]


# --------------------------------------------------------------------------- #
# Playing it, without making NVDA wait for Titan
# --------------------------------------------------------------------------- #
def _pump():
    from .link import LINK
    global _pending, _played
    while _running:
        _wake.wait(0.5)
        _wake.clear()
        with _LOCK:
            cues, _pending = _pending, None
        if not cues or not _running:
            continue
        for name, pan, pitch in cues:
            if not _running:
                break
            try:
                LINK.bridge('sounds.play', timeout=3.0,
                            name='reader/' + name, pan=pan, pitch=pitch)
                _played += 1
            except Exception:                        # noqa: BLE001
                pass


def start():
    global _worker, _running
    with _LOCK:
        if _running:
            return
        _running = True
    _worker = threading.Thread(target=_pump, name='TitanEarcons', daemon=True)
    _worker.start()


def stop():
    global _running, _pending
    with _LOCK:
        _running = False
        _pending = None
    _wake.set()


def played():
    return _played


def wanted():
    from . import configSpec
    return bool(configSpec.read().get('earcons', False))


def announce(obj, for_navigation=False):
    """Play the cue for what the focus has just reached. Never waits.

    Answers whether a cue was handed over, which is what the tests read -
    and what the status command counts.
    """
    global _pending
    if not wanted():
        return False
    from . import focus
    from .link import LINK
    # Titan's own windows already sound like themselves.
    if focus.is_titan_object(obj):
        return False
    if not LINK.connected():
        return False
    cues = cues_for(obj, for_navigation)
    if not cues:
        return False
    start()
    with _LOCK:
        # Newest wins: a cue that has been overtaken by the next arrow key
        # is not worth playing late.
        _pending = cues
    _wake.set()
    return True
