"""Dictation support for the voice assistant.

When an assistant hotkey is pressed while the keyboard focus sits in an editable
text field (any app - a browser field, an editor, a chat box), the assistant
should simply DICTATE: transcribe what the user says and type it into that
field, rather than running the command agent. This module provides the two
low-level pieces that behaviour needs:

* :func:`focused_editable` - is the system-wide focused control an editable text
  field? Uses UI Automation (via comtypes) so it works across arbitrary apps,
  and fails safe (returns False) whenever UIA is unavailable.
* :func:`type_at_focus` - type text at the current keyboard focus.

Both are best-effort and never raise.
"""

# UIA control-type ids for text-bearing controls (from UIAutomationClient).
_UIA_EDIT = 50004        # UIA_EditControlTypeId
_UIA_DOCUMENT = 50030    # UIA_DocumentControlTypeId
_UIA_PATTERN_VALUE = 10002   # UIA_ValuePatternId

# A single cached UIAutomation COM object (creating one per keypress is slow).
_uia = None


def _get_uia():
    """Return a cached IUIAutomation instance, or None if UIA is unavailable."""
    global _uia
    if _uia is not None:
        return _uia
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        import comtypes.client
        # Generate (once) and load the UIAutomationClient typelib, then create the
        # core automation object with its proper interface.
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
        _uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
    except Exception as e:
        print(f"[dictation] UI Automation unavailable: {e}")
        _uia = None
    return _uia


def focused_editable():
    """True if the currently focused control is an editable (not read-only) text
    field. Fails safe: any error -> False, so dictation never hijacks a hotkey
    when we cannot be sure a text field is focused."""
    uia = _get_uia()
    if uia is None:
        return False
    try:
        # COM must be initialised on this thread.
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        el = uia.GetFocusedElement()
        # "Nothing focused" arrives as a NULL interface pointer, which comtypes
        # wraps in an object rather than returning None; releasing one of those
        # later is an access violation, so treat it as no element at all.
        if el is None or not bool(el):
            return False
        try:
            ctype = el.CurrentControlType
        except Exception:
            return False
        if ctype not in (_UIA_EDIT, _UIA_DOCUMENT):
            return False
        # If a Value pattern says the field is read-only, it is not dictatable.
        try:
            pattern = el.GetCurrentPattern(_UIA_PATTERN_VALUE)
            if pattern is not None and bool(pattern):
                from comtypes.gen import UIAutomationClient as _UIA
                # QueryInterface, never comtypes.cast: cast is ctypes' cast and
                # does NOT take a reference, so both wrappers call Release on
                # the same pointer and the second one corrupts the heap.
                val = pattern.QueryInterface(_UIA.IUIAutomationValuePattern)
                if val.CurrentIsReadOnly:
                    return False
        except Exception:
            # No/unsupported Value pattern -> treat as editable (Edit/Document).
            pass
        return True
    except Exception as e:
        print(f"[dictation] focus check failed: {e}")
        return False


def type_at_focus(text):
    """Type ``text`` at the current keyboard focus. Best effort; returns True on
    success. Uses pynput so it works in the compiled build too."""
    text = str(text or '')
    if not text:
        return False
    try:
        from pynput.keyboard import Controller
        Controller().type(text)
        return True
    except Exception as e:
        print(f"[dictation] typing failed: {e}")
        return False
