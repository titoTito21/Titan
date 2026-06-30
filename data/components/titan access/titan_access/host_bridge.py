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


def announce(text, interrupt=True, pitch=0) -> bool:
    """Speak ``text`` as an exact phrase, replacing the reader's own next focus
    announcement for the element. ``pitch`` shifts the tone (negative = lower,
    e.g. for a region name). Returns True if Titan Access handled it."""
    eng = _engine()
    if eng is None:
        return False
    try:
        eng.announce_override(text, interrupt=interrupt, pitch_offset=pitch)
        return True
    except Exception:
        return False


def announce_segments(segments, interrupt=True) -> bool:
    """Speak ``[(text, pitch), ...]`` as one mixed-tone phrase, replacing the
    reader's own next focus announcement. For phrases that need more than one
    tone -- e.g. a dragged item name a little higher, then "at position N" at
    the neutral pitch. Returns True if Titan Access handled it."""
    eng = _engine()
    if eng is None:
        return False
    try:
        eng.announce_segments(segments, interrupt=interrupt)
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


def dialog_kind(kind) -> bool:
    """Declare the kind of the dialog about to be shown so Titan Access reads it
    as that type (e.g. "question") regardless of skin or icon detectability.

    ``kind`` is one of "question" / "information" / "warning" / "error". Call this
    immediately before showing a wx.MessageDialog whose icon a screen reader
    cannot reliably classify (skinned / generic dialogs). Returns True if Titan
    Access is running and took the hint; a no-op otherwise."""
    eng = _engine()
    if eng is None:
        return False
    try:
        eng.set_dialog_kind(kind)
        return True
    except Exception:
        return False


def role_label(text) -> bool:
    """Replace the control-type word in the reader's next focus announcement
    with ``text`` (e.g. "status bar item" instead of the generic "list item").
    Returns True if Titan Access handled it."""
    eng = _engine()
    if eng is None:
        return False
    try:
        eng.set_role_label(text)
        return True
    except Exception:
        return False


def push_focus(role="unknown", name="", value="", description="", help_text="",
               states=None, level=0, pos_in_set=0, size_of_set=0,
               automation_id="", class_name="", process_id=0, hwnd=0) -> bool:
    """Inject a focus event from a toolkit the platform a11y APIs cannot see.

    Tkinter (and similar) draw their widgets inside a single HWND, so UI
    Automation / MSAA expose nothing readable. An in-process Tk app describes
    its focused widget here; we build an :class:`AccessibleObject` (provider
    ``"tk"``) and run it through the engine's normal focus pipeline, so it flows
    through the **app-modules** layer and the standard announcer exactly like a
    UIA focus -- no Tk logic lives in the core reader. Returns True if Titan
    Access handled it (a standalone caller falls back to accessible_output3).
    """
    eng = _engine()
    if eng is None:
        return False
    try:
        from titan_access.contracts import AccessibleObject
        obj = AccessibleObject(
            name=name or "", role=role or "unknown", value=value or "",
            description=description or "", help_text=help_text or "",
            states=set(states or ()), level=int(level or 0),
            pos_in_set=int(pos_in_set or 0), size_of_set=int(size_of_set or 0),
            automation_id=automation_id or "", class_name=class_name or "",
            framework_id="tk", process_id=int(process_id or 0),
            hwnd=int(hwnd or 0), native=None, provider="tk",
        )
        # Run on the engine worker thread (its COM apartment / serialised state),
        # matching how UIA focus snapshots are handled.
        eng.post_to_worker(lambda: eng.on_focus(obj))
        return True
    except Exception:
        return False
