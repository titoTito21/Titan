# -*- coding: utf-8 -*-
"""The few things a shared module asks of the READER underneath it.

Markers, monitors and procedures need six answers from the reader they run
in: what window is in front, what has the focus, what is at a point on the
screen, how to put the focus on a control, how to do a control's own
action, and how to press a key. In NVDA every one of those is a call into
`api` or `keyboardHandler`, and the shared modules made those calls
directly - which is why, vendored into Titan Access, they imported cleanly
and could reach nothing: `import api` raised, the marker could not be found
again, the monitor read nothing, the procedure pressed no key.

This is the seam. In NVDA it answers out of NVDA; anywhere else the reader
installs :data:`hooks` - an object with the same six methods - and the
shared modules never know which. Titan Access's is
`titan_access/nvda_shape.py`, which also gives its own objects the
attribute names the shared modules read (`windowClassName`, `role.name`,
`children`, `location`).
"""

#: The reader underneath, when it is not NVDA: an object answering
#: ``foreground()``, ``focus()``, ``object_at(x, y)``, ``set_focus(obj)``,
#: ``navigate_to(obj)``, ``do_action(obj)``, ``send_key(name)`` and
#: ``type_text(text)``. Any of them may be missing; a missing one answers
#: None or False.
hooks = None


def _nvda_api():
    try:
        import api
        return api
    except Exception:                                # noqa: BLE001
        return None


def _hook(name):
    found = getattr(hooks, name, None) if hooks is not None else None
    return found if callable(found) else None


def foreground():
    """The window in front, or None."""
    api = _nvda_api()
    if api is not None:
        try:
            return api.getForegroundObject()
        except Exception:                            # noqa: BLE001
            return None
    ask = _hook('foreground')
    if ask is None:
        return None
    try:
        return ask()
    except Exception:                                # noqa: BLE001
        return None


def focus():
    """The control that has the keyboard, or None."""
    api = _nvda_api()
    if api is not None:
        try:
            return api.getFocusObject()
        except Exception:                            # noqa: BLE001
            return None
    ask = _hook('focus')
    if ask is None:
        return None
    try:
        return ask()
    except Exception:                                # noqa: BLE001
        return None


def object_at(x, y):
    """What is drawn at a point on the screen, or None."""
    api = _nvda_api()
    if api is not None:
        try:
            return api.getDesktopObject().objectFromPoint(int(x), int(y))
        except Exception:                            # noqa: BLE001
            return None
    ask = _hook('object_at')
    if ask is None:
        return None
    try:
        return ask(int(x), int(y))
    except Exception:                                # noqa: BLE001
        return None


def set_focus(obj):
    """Put the keyboard on this control. True when it was taken."""
    if obj is None:
        return False
    try:
        obj.setFocus()
        return True
    except Exception:                                # noqa: BLE001
        pass
    ask = _hook('set_focus')
    if ask is None:
        return False
    try:
        return bool(ask(obj))
    except Exception:                                # noqa: BLE001
        return False


def navigate_to(obj):
    """Put the READER's own cursor on a control that will not take the
    keyboard - NVDA's navigator object, Titan Access's announcement."""
    if obj is None:
        return False
    api = _nvda_api()
    if api is not None:
        try:
            api.setNavigatorObject(obj)
            return True
        except Exception:                            # noqa: BLE001
            return False
    ask = _hook('navigate_to')
    if ask is None:
        return False
    try:
        return bool(ask(obj))
    except Exception:                                # noqa: BLE001
        return False


def do_action(obj):
    """The control's OWN default action. True when it had one and did it."""
    if obj is None:
        return False
    try:
        if int(getattr(obj, 'actionCount', 0) or 0) > 0:
            obj.doAction(0)
            return True
    except Exception:                                # noqa: BLE001
        pass
    ask = _hook('do_action')
    if ask is None:
        return False
    try:
        return bool(ask(obj))
    except Exception:                                # noqa: BLE001
        return False


def send_key(name):
    """Press one key by NVDA's name (``control+s``, ``enter``, ``a``)."""
    name = str(name or '')
    if not name:
        return False
    try:
        import keyboardHandler
        keyboardHandler.KeyboardInputGesture.fromName(name).send()
        return True
    except Exception:                                # noqa: BLE001
        pass
    ask = _hook('send_key')
    if ask is None:
        return False
    try:
        return bool(ask(name))
    except Exception:                                # noqa: BLE001
        return False


def type_text(text):
    """Type text where the keyboard is, one key at a time."""
    ask = _hook('type_text')
    if ask is not None and _nvda_api() is None:
        try:
            return bool(ask(str(text)))
        except Exception:                            # noqa: BLE001
            return False
    for character in str(text or ''):
        if not send_key(character if character != ' ' else 'space'):
            return False
    return True
