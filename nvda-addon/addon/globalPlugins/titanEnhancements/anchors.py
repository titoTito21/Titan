# -*- coding: utf-8 -*-
"""Remembering a control, and finding it again.

Two things in this add-on point at a control that is not on the screen right
now: a **monitor** watches one, and a **place marker** goes back to one. They
are different features and they need exactly the same answer to the same
hard question - *what about this control will still be true the next time
the program is opened?* - so they ask it here rather than each having a copy
that drifts.

**Only a STRONG anchor names a control.** `labels.key_of` says whether the
key it built is the program's own name for the control - an automation id, a
dialog control id - or one made out of where the control sits among its
siblings. The second moves the moment a toolbar gains a button, so a thing
anchored to it would quietly start pointing at the control next door, which
is worse than not pointing at anything: a marker that jumps somewhere wrong
is one the user acts on.

Where there is no strong anchor there is still a POINT - where the control
is on the screen - and that is offered instead, marked as what it is. It is
weaker and it is honest, and for a status line at the bottom of a window it
is perfectly good.
"""

from . import i18n

_ = i18n.install(globals())

BY_CONTROL = 'control'
BY_POINT = 'point'
BY_AREA = 'area'


def _text(value):
    return str(value or '').strip()


def program_of(obj=None):
    try:
        from . import perProgram
        return _text(perProgram.application_of(obj))
    except Exception:                                # noqa: BLE001
        return ''


def describe(obj):
    """What to call this control in a list, when the user names nothing."""
    for attribute in ('name', 'value', 'windowText', 'windowClassName'):
        try:
            said = _text(getattr(obj, attribute, ''))
        except Exception:                            # noqa: BLE001
            said = ''
        if said:
            return said
    # Translators: what an unnamed control is called in a list.
    return _('this control')


def rect_of(obj):
    try:
        location = obj.location
        if hasattr(location, 'left'):
            return (int(location.left), int(location.top),
                    int(location.width), int(location.height))
        return tuple(int(value) for value in location)
    except Exception:                                # noqa: BLE001
        return None


def strong_key(obj):
    """The program's own name for this control, or ''.

    A weak key is deliberately refused here rather than returned with a
    flag: every caller wants the same thing from it, and a caller that
    forgot to check the flag would be pointing at the wrong control.
    """
    try:
        from . import labels
        key, strong = labels.key_of(obj)
    except Exception:                                # noqa: BLE001
        return ''
    return key if strong else ''


def anchor_for(obj):
    """``{kind, program, where|point}`` for this control, or None.

    None only when the control is nowhere at all - no name of its own and no
    place on the screen - which is a control nothing could find again.
    """
    if obj is None:
        return None
    key = strong_key(obj)
    if key:
        return {'kind': BY_CONTROL, 'program': program_of(obj), 'where': key}
    rect = rect_of(obj)
    if not rect:
        return None
    return {'kind': BY_POINT, 'program': program_of(obj),
            'point': [rect[0] + rect[2] // 2, rect[1] + rect[3] // 2]}


#: How many objects are looked at while hunting for an anchored control.
#: Bounded because this runs when the user presses a key and a walk of a
#: browser's whole tree is a reader that has stopped answering.
MAX_SEEN = 400


def find(anchor):
    """The control this anchor points at, if it is on the screen now.

    Only inside the program the anchor was made in, and only through NVDA's
    own tree. A search that ranged over the whole desktop would eventually
    find a control that matched and was not the one meant.
    """
    if not anchor:
        return None
    kind = anchor.get('kind')
    if kind == BY_POINT:
        return at_point(anchor.get('point'))
    wanted = _text(anchor.get('where'))
    if not wanted:
        return None
    try:
        import api
        from . import labels
        window = api.getForegroundObject()
    except Exception:                                # noqa: BLE001
        return None
    if window is None:
        return None
    if anchor.get('program') and program_of(window) != anchor['program']:
        return None
    seen, queue = 0, [window]
    while queue and seen < MAX_SEEN:
        obj = queue.pop(0)
        seen += 1
        try:
            if labels.key_of(obj)[0] == wanted:
                return obj
            queue.extend(list(obj.children or [])[:40])
        except Exception:                            # noqa: BLE001
            continue
    return None


def at_point(point):
    if not point or len(point) != 2:
        return None
    try:
        import api
        return api.getDesktopObject().objectFromPoint(int(point[0]),
                                                      int(point[1]))
    except Exception:                                # noqa: BLE001
        return None
