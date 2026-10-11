# -*- coding: utf-8 -*-
"""What an edit field IS, said the way a screen reader says it.

Two facts about a text control change how it is used, and both were
missing or wrong:

* **It takes several lines.** Enter in it is a new line, not the dialog's
  default button, and Up and Down move through the text rather than out
  of the field. Read as "Pole edycji" (pause) "wieloliniowe" - the type,
  then the fact, in the state's own voice.
* **It cannot be typed into.** Then it is not a field at all to the person
  using it, it is text to read: "tekst" (pause) "tylko do odczytu", which
  is what NVDA says for a read-only edit control.

The facts come from wherever the control keeps them: the state the
provider reported (AT-SPI's MULTI_LINE, UIA's ValuePattern.IsReadOnly,
MSAA's STATE_SYSTEM_READONLY), the Win32 window style (``ES_MULTILINE``,
``ES_READONLY``) for the classic EDIT and RichEdit family - which is also
every ``wx.TextCtrl`` - and, for a UI Automation document, the role
itself: a document is a page of text and always several lines.

A web page is never one of these: browse mode reads it, and calling the
page "Pole edycji" would be wrong on every site there is.
"""

import os

from titan_access.contracts import (
    ROLE_EDIT, ROLE_DOCUMENT, ROLE_TEXT, STATE_READONLY, STATE_MULTILINE,
)

#: UIA FrameworkId values of web content (the engine's own list).
WEB_FRAMEWORKS = {"chrome", "gecko", "webview", "edge", "blink"}

_ES_MULTILINE = 0x0004
_ES_READONLY = 0x0800
_GWL_STYLE = -16

_user32 = None
if os.name == "nt":
    try:
        import ctypes
        from ctypes import wintypes
        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.GetWindowLongW.restype = ctypes.c_long
        _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.GetClassNameW.restype = ctypes.c_int
        _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                          ctypes.c_int]
        _user32.IsWindow.restype = wintypes.BOOL
        _user32.IsWindow.argtypes = [wintypes.HWND]
    except Exception:                                # noqa: BLE001
        _user32 = None


def is_edit_class(class_name):
    """A real Win32 edit window: EDIT, the RichEdit family, Scintilla."""
    cls = (class_name or "").lower()
    return cls == "edit" or cls.startswith("richedit") \
        or cls.startswith("scintilla")


def _win32_style(obj):
    """The window style of the control's own edit window, or None.

    Only asked when the control IS an edit window (by its class): any other
    window's style bits mean something else entirely."""
    if _user32 is None:
        return None
    hwnd = int(getattr(obj, "hwnd", 0) or 0)
    if not hwnd:
        return None
    try:
        if not _user32.IsWindow(hwnd):
            return None
        cls = getattr(obj, "class_name", "") or ""
        if not is_edit_class(cls):
            import ctypes
            buf = ctypes.create_unicode_buffer(64)
            if _user32.GetClassNameW(hwnd, buf, 64) <= 0 \
                    or not is_edit_class(buf.value):
                return None
        return int(_user32.GetWindowLongW(hwnd, _GWL_STYLE)) & 0xFFFFFFFF
    except Exception:                                # noqa: BLE001
        return None


def is_web(obj):
    return (getattr(obj, "framework_id", "") or "").lower() in WEB_FRAMEWORKS


def is_text_field(obj):
    """An edit control or a non-web document - the controls this is about."""
    if obj is None:
        return False
    role = getattr(obj, "role", "")
    if role == ROLE_EDIT:
        return True
    return role == ROLE_DOCUMENT and not is_web(obj)


def _has(obj, state):
    try:
        return bool(obj.has(state))
    except Exception:                                # noqa: BLE001
        return state in (getattr(obj, "states", None) or ())


def is_read_only(obj):
    if _has(obj, STATE_READONLY):
        return True
    style = _win32_style(obj)
    return bool(style is not None and style & _ES_READONLY)


def is_multiline(obj):
    if _has(obj, STATE_MULTILINE):
        return True
    if getattr(obj, "role", "") == ROLE_DOCUMENT:
        return True
    style = _win32_style(obj)
    if style is not None:
        return bool(style & _ES_MULTILINE)
    # A control with no window of its own (WPF, WinUI) says nothing about
    # its lines; text that already has a line break in it is one that
    # takes them.
    value = getattr(obj, "value", "") or ""
    return "\n" in value or "\r" in value


def shape(obj):
    """``(kind_role, states)`` to announce for a text field, or None.

    *kind_role* is the role whose word is said as the control type -
    ``ROLE_EDIT`` ("Pole edycji") or ``ROLE_TEXT`` ("Tekst") - and *states*
    are what is said after it: ``[STATE_MULTILINE]`` for a field that takes
    several lines, ``[STATE_READONLY]`` for one that cannot be typed into.
    Read-only wins: text to read is text to read, however many lines it
    has. Anything that is not a text field answers None and is described
    as it always was.
    """
    if not is_text_field(obj):
        return None
    if is_read_only(obj):
        return ROLE_TEXT, [STATE_READONLY]
    if is_multiline(obj):
        return ROLE_EDIT, [STATE_MULTILINE]
    return ROLE_EDIT, []
