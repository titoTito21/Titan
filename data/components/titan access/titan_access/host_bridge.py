# -*- coding: utf-8 -*-
"""Host -> Titan Access bridge.

The TCE launcher hosts a few widgets whose meaning UI Automation cannot fully
expose to a screen reader:

* the **virtual tab bar** -- a synthetic first row injected into each list/tree
  view (``src/ui/gui.py``); UIA just sees an ordinary list item, so the reader
  cannot tell it is the tab bar or which view it represents;
* the **categories CheckListBox** in settings (``src/ui/settingsgui.py``);
  ``wx.CheckListBox`` does not surface its per-item check state through UIA on
  Windows, so the reader cannot announce checked / unchecked.

For those cases TCE (which *does* know the semantics) calls the helpers here to
push an exact announcement to the running reader. When Titan Access is not the
active reader every call is a cheap no-op and the caller falls back to its own
(accessible_output3) path.

This module lives inside the component package so it imports cleanly once the
component has put its directory on ``sys.path`` (see the component ``init.py``).
TCE imports it defensively: ``from titan_access.host_bridge import ...``.
"""


def _engine():
    """Return the running engine instance, or None when the reader is off."""
    try:
        from titan_access.engine import TitanAccessEngine
        eng = TitanAccessEngine.instance
        if eng is not None and getattr(eng, "running", False):
            return eng
    except Exception:
        pass
    return None


def is_active() -> bool:
    """True when Titan Access is the running screen reader."""
    return _engine() is not None


def announce(text, interrupt=True) -> bool:
    """Speak ``text`` as an exact phrase, replacing the reader's own next focus
    announcement for the element. Returns True if Titan Access handled it."""
    eng = _engine()
    if eng is None:
        return False
    try:
        eng.announce_override(text, interrupt=interrupt)
        return True
    except Exception:
        return False


def speak(text, interrupt=True) -> bool:
    """Speak ``text`` immediately through the reader, without suppressing any
    upcoming focus announcement. For state changes that fire no focus event
    (e.g. toggling a CheckListBox item in place). Returns True if handled."""
    eng = _engine()
    if eng is None:
        return False
    try:
        eng.speak(text, interrupt=interrupt)
        return True
    except Exception:
        return False


def state_suffix(text) -> bool:
    """Append ``text`` (a state word such as "checked") to the reader's next
    focus announcement. Returns True if Titan Access handled it."""
    eng = _engine()
    if eng is None:
        return False
    try:
        eng.set_state_suffix(text)
        return True
    except Exception:
        return False
