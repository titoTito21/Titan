# -*- coding: utf-8 -*-
"""Window-Eyes' Windows and Actions, on NVDA's own object model.

Window-Eyes let you open a list of the windows that are there, walk into
one, and see what each control will actually DO - and then do it, without
having to get the keyboard to that control first. It is the thing that
answers "there is a button somewhere in this dialog and Tab will not reach
it", and it is a genuinely different question from "read me the screen":
this is about what can be done, not about what is written.

NVDA has everything needed and exposes none of it as a place to look. Every
`NVDAObject` carries the actions its control really offers -
``actionCount``, ``getActionName(index)``, ``doAction(index)`` - and those
come from the accessibility layer underneath, so they are the program's own
verbs: Press, Expand, Collapse, Check, Jump, Open. This puts them in a list.

Three rules, and each is a way this could have gone wrong:

* **Nothing is invented.** An action is one the control declares. There is
  no synthesised click, no coordinate, no key sent hopefully - if a control
  offers nothing, it is listed as offering nothing, which is a true and
  useful thing to be told.
* **The walk is bounded.** A window's object tree can be enormous, and a
  reader that walks all of it is a reader that has stopped answering. It is
  breadth-first with a ceiling, so what comes back is the top of the window
  - which is where the controls somebody is looking for actually are.
* **It never acts by itself.** Listing is free and changes nothing; doing
  is a separate keypress on a chosen row.
"""

from . import i18n

_ = i18n.install(globals())

#: How many objects are looked at while building the list of one window.
#: A tree can be tens of thousands of nodes deep in a browser; this is the
#: top of it, which is where a dialog's own controls are.
MAX_SEEN = 600

#: How many controls are offered. Past this the list is not something
#: anybody finds anything in anyway.
MAX_CONTROLS = 200

#: Roles that are furniture: they hold other things and do nothing
#: themselves, so listing them puts a hundred rows between the user and the
#: controls they came for.
SKIP = frozenset({'WINDOW', 'PANE', 'FRAME', 'CLIENT', 'GROUPING',
                  'SECTION', 'UNKNOWN'})


def _text(value):
    return str(value or '').strip()


def _role(obj):
    try:
        return _text(getattr(getattr(obj, 'role', None), 'name', '')).upper()
    except Exception:                                # noqa: BLE001
        return ''


def _role_said(obj):
    try:
        from . import context
        return _text(context.role_name(getattr(obj, 'role', None)))
    except Exception:                                # noqa: BLE001
        return ''


# --------------------------------------------------------------------------- #
# The windows
# --------------------------------------------------------------------------- #
def windows():
    """``[(label, obj)]`` - the top-level windows that are really there.

    NVDA's own desktop children, which is the same list its object
    navigation walks - so a window that is here is one the reader can
    already reach, and there is no second idea of what a window is.
    """
    try:
        import api
        desktop = api.getDesktopObject()
        children = list(desktop.children or [])
    except Exception:                                # noqa: BLE001
        return []
    found = []
    for obj in children:
        name = _text(getattr(obj, 'name', ''))
        if not name:
            continue
        try:
            if not getattr(obj, 'isFocusable', True) and not name:
                continue
        except Exception:                            # noqa: BLE001
            pass
        program = ''
        try:
            from . import perProgram
            program = _text(perProgram.application_of(obj))
        except Exception:                            # noqa: BLE001
            program = ''
        label = '%s (%s)' % (name, program) if program else name
        found.append((label, obj))
    return found


def foreground():
    try:
        import api
        return api.getForegroundObject()
    except Exception:                                # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# The controls in one
# --------------------------------------------------------------------------- #
def controls(window):
    """``[{'label', 'obj', 'actions'}]`` for one window.

    Breadth-first, because a dialog's own controls are near the top of its
    tree and a depth-first walk would spend the whole budget in the first
    branch it fell into.
    """
    if window is None:
        return []
    found, seen = [], 0
    queue = [window]
    while queue and seen < MAX_SEEN and len(found) < MAX_CONTROLS:
        obj = queue.pop(0)
        seen += 1
        try:
            queue.extend(list(obj.children or []))
        except Exception:                            # noqa: BLE001
            pass
        role = _role(obj)
        if role in SKIP:
            continue
        name = _text(getattr(obj, 'name', ''))
        value = _text(getattr(obj, 'value', ''))
        said = _role_said(obj)
        if not name and not value:
            # A control with nothing to call it is one nobody can pick out
            # of a list. It is skipped rather than listed as a blank row.
            continue
        label = name or value
        if said:
            label = '%s, %s' % (label, said)
        if value and value != name:
            label = '%s, %s' % (label, value)
        found.append({'label': label, 'obj': obj,
                      'actions': actions_of(obj)})
    return found


def actions_of(obj):
    """``[(index, name)]`` - what this control says it can do.

    The control's OWN verbs, from the accessibility layer: Press, Expand,
    Check, Jump. Nothing here invents one, so a control that offers nothing
    comes back empty - which is a true answer and a useful one.
    """
    out = []
    try:
        count = int(getattr(obj, 'actionCount', 0) or 0)
    except Exception:                                # noqa: BLE001
        return out
    for index in range(min(count, 8)):
        try:
            name = _text(obj.getActionName(index))
        except Exception:                            # noqa: BLE001
            continue
        if name:
            out.append((index, name))
    return out


def do(obj, index):
    """Do one of them. ``(ok, sentence)``."""
    try:
        name = _text(obj.getActionName(index))
    except Exception:                                # noqa: BLE001
        name = ''
    try:
        obj.doAction(index)
    except Exception as error:                       # noqa: BLE001
        # Translators: said when a control's own action failed. {why} is
        # what the program said.
        return False, _('That did not work: {why}').format(why=error)
    # Translators: said when a control's own action has been done. {what}
    # is the action's name, as the program calls it.
    return True, _('{what}.').format(what=name or _('Done'))


def focus(obj):
    """Put the keyboard on it, which is the other thing a list like this is
    for: a control Tab will not reach can still be worked."""
    try:
        obj.setFocus()
        # Translators: said when the keyboard is moved to a control.
        return True, _('Moved there.')
    except Exception as error:                       # noqa: BLE001
        # Translators: said when the keyboard cannot be moved to a control.
        return False, _('The keyboard could not be moved there: {why}').format(
            why=error)


def review(obj):
    """Put NVDA's own review cursor on it, for a control that cannot take
    the keyboard at all - which is most of what is interesting in a window
    somebody is examining."""
    try:
        import api
        api.setNavigatorObject(obj)
        # Translators: said when the review cursor is moved to a control.
        return True, _('The review cursor is there.')
    except Exception as error:                       # noqa: BLE001
        return False, _('The review cursor could not be moved there: '
                        '{why}').format(why=error)
