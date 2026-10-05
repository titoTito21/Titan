# -*- coding: utf-8 -*-
"""How text gets INTO a control and OUT of it, one accessibility API at a
time.

A walked edit field keeps a copy of the text the user is editing, and the
copy is worthless unless the real control ends up holding the same thing.
Every accessibility API Windows (and Linux) has offers its own way to do
that, and each works for a different set of programs:

* **UI Automation** - `ValuePattern.SetValue`, refused when the pattern
  says `IsReadOnly`. WPF, WinUI/XAML, Windows Forms through its UIA
  provider, Qt 5.11+ and Qt 6, Chromium and Firefox. The text is read
  from `TextPattern.DocumentRange` when there is one, because a value is
  allowed to be shortened and a document's is.
* **MSAA** - `IAccessible::put_accValue`. Legacy controls, Qt before 5.11,
  Tk 9.1 (TIP 733: Tk chose MSAA on Windows). Many proxies refuse it,
  which is why it is asked after the others.
* **Win32** - `WM_SETTEXT` / `WM_GETTEXT` on the control's own window,
  when that window IS an edit control: Edit, RichEdit, Delphi's TEdit and
  TMemo, VB6's ThunderTextBox, Windows Forms' EDIT, wxWidgets' native
  text control. Exact, and needs no accessibility at all.
* **Java Access Bridge** - `setTextContents` (Java 7u6 and later).
* **AT-SPI** - `EditableText.set_text_contents`, on Linux.

None of them is tried on a control that is not an edit field, and every
one answers True only when the API itself said yes. The toolkit modules
beside this one decide the ORDER - what is right for Qt is wrong for Tk.
"""

import ctypes
import sys

_IS_WINDOWS = sys.platform.startswith('win')

#: Window classes that are an edit control, whatever program they are in.
#: Matched by prefix, case-insensitively.
EDIT_CLASSES = ('edit', 'richedit', 'richedit20', 'richedit50w',
                'riched20', 'riched32', 'tedit', 'tmemo', 'trichedit',
                'tmaskedit', 'tlabelededit', 'thundertextbox',
                'thunderrt6textbox', 'windowsforms10.edit',
                'windowsforms10.richedit', 'wxwindownr', 'atl:edit')

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
SMTO_ABORTIFHUNG = 0x0002
EM_SETSEL = 0x00B1


def _text(value):
    return str(value or '')


# --------------------------------------------------------------------------- #
# Win32
# --------------------------------------------------------------------------- #
def _class_name(hwnd):
    if not _IS_WINDOWS or not hwnd:
        return ''
    buffer = ctypes.create_unicode_buffer(256)
    try:
        ctypes.windll.user32.GetClassNameW(ctypes.c_void_p(int(hwnd)),
                                           buffer, 256)
    except Exception:                                # noqa: BLE001
        return ''
    return buffer.value or ''


def is_edit_window(hwnd):
    """Whether this window is itself an edit control."""
    name = _class_name(hwnd).lower()
    return bool(name) and any(name.startswith(one) for one in EDIT_CLASSES)


def _send(hwnd, message, wparam, lparam, timeout_ms=1500):
    result = ctypes.c_size_t(0)
    user32 = ctypes.windll.user32
    user32.SendMessageTimeoutW.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
    ok = user32.SendMessageTimeoutW(ctypes.c_void_p(int(hwnd)), message,
                                    wparam, lparam, SMTO_ABORTIFHUNG,
                                    timeout_ms, ctypes.byref(result))
    return bool(ok), int(result.value)


def win32_get(hwnd):
    """The whole text of an edit window, or None."""
    if not _IS_WINDOWS or not is_edit_window(hwnd):
        return None
    try:
        ok, length = _send(hwnd, WM_GETTEXTLENGTH, 0, None)
        if not ok:
            return None
        buffer = ctypes.create_unicode_buffer(length + 2)
        ok, _copied = _send(hwnd, WM_GETTEXT, length + 1,
                            ctypes.cast(buffer, ctypes.c_void_p))
        return buffer.value if ok else None
    except Exception:                                # noqa: BLE001
        return None


def win32_set(hwnd, text):
    """Replace an edit window's text. The caret is put at the end, which
    is where somebody who has just typed expects it."""
    if not _IS_WINDOWS or not is_edit_window(hwnd):
        return False
    try:
        buffer = ctypes.create_unicode_buffer(_text(text))
        ok, done = _send(hwnd, WM_SETTEXT, 0,
                         ctypes.cast(buffer, ctypes.c_void_p))
        if not (ok and done):
            return False
        length = len(_text(text))
        _send(hwnd, EM_SETSEL, length, ctypes.c_void_p(length))
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# UI Automation
# --------------------------------------------------------------------------- #
#: UI Automation's own pattern ids.
UIA_VALUE_PATTERN = 10002
UIA_TEXT_PATTERN = 10014


def _uia_control(obj):
    if getattr(obj, 'provider', '') != 'uia':
        return None
    native = getattr(obj, 'native', None)
    return native if hasattr(native, 'GetPattern') else None


def _uia_pattern(control, getter, pattern_id):
    """A pattern through the library's typed getter, or by its id - not
    every control class of `uiautomation` has every getter."""
    ask = getattr(control, getter, None)
    try:
        if callable(ask):
            return ask()
        return control.GetPattern(pattern_id)
    except Exception:                                # noqa: BLE001
        return None


def uia_get(obj):
    """The text through TextPattern (the whole document), then Value."""
    control = _uia_control(obj)
    if control is None:
        return None
    try:
        pattern = _uia_pattern(control, 'GetTextPattern', UIA_TEXT_PATTERN)
        if pattern is not None:
            found = pattern.DocumentRange.GetText(-1)
            if isinstance(found, str):
                return found
    except Exception:                                # noqa: BLE001
        pass
    try:
        pattern = _uia_pattern(control, 'GetValuePattern', UIA_VALUE_PATTERN)
        if pattern is not None:
            return _text(pattern.Value)
    except Exception:                                # noqa: BLE001
        pass
    return None


def uia_can_set(obj):
    control = _uia_control(obj)
    if control is None:
        return False
    try:
        pattern = _uia_pattern(control, 'GetValuePattern', UIA_VALUE_PATTERN)
        return pattern is not None and not bool(pattern.IsReadOnly)
    except Exception:                                # noqa: BLE001
        return False


def uia_set(obj, text):
    if not uia_can_set(obj):
        return False
    try:
        _uia_pattern(_uia_control(obj), 'GetValuePattern',
                     UIA_VALUE_PATTERN).SetValue(_text(text))
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# MSAA
# --------------------------------------------------------------------------- #
def _iaccessible(hwnd):
    """The IAccessible of a window's client area, or None."""
    if not _IS_WINDOWS or not hwnd:
        return None
    try:
        import comtypes.client
        comtypes.client.GetModule('oleacc.dll')
        from comtypes.gen.Accessibility import IAccessible  # type: ignore
        pointer = ctypes.POINTER(IAccessible)()
        ctypes.oledll.oleacc.AccessibleObjectFromWindow(
            ctypes.c_void_p(int(hwnd)), ctypes.c_long(-4),   # OBJID_CLIENT
            ctypes.byref(IAccessible._iid_), ctypes.byref(pointer))
        return pointer if pointer else None
    except Exception:                                # noqa: BLE001
        return None


def msaa_get(obj):
    acc = _iaccessible(getattr(obj, 'hwnd', 0))
    if acc is None:
        return None
    try:
        return _text(acc.accValue(0))
    except Exception:                                # noqa: BLE001
        return None


def msaa_set(obj, text):
    """`put_accValue` on the control's own window. Only for an MSAA object
    that IS its window's client - a child of a list has no window of its
    own, and writing its parent's value would be writing the wrong
    control."""
    if getattr(obj, 'provider', '') not in ('msaa', 'uia', 'ia2'):
        return False
    acc = _iaccessible(getattr(obj, 'hwnd', 0))
    if acc is None:
        return False
    try:
        acc._IAccessible__com__set_accValue(0, _text(text))
    except Exception:                                # noqa: BLE001
        return False
    # Many proxies answer S_OK and change nothing: believe the control.
    try:
        return _text(acc.accValue(0)) == _text(text)
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Java Access Bridge
# --------------------------------------------------------------------------- #
def jab_get(obj):
    native = getattr(obj, 'native', None)
    if getattr(obj, 'provider', '') != 'jab' or native is None:
        return None
    try:
        return native.text(limit=200000)
    except Exception:                                # noqa: BLE001
        return None


def jab_set(obj, text):
    native = getattr(obj, 'native', None)
    if getattr(obj, 'provider', '') != 'jab' or native is None:
        return False
    try:
        return bool(native.set_text(_text(text)))
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# AT-SPI (Linux)
# --------------------------------------------------------------------------- #
def _atspi():
    try:
        from titan_access import atspi_focus
        return atspi_focus.atspi()
    except Exception:                                # noqa: BLE001
        return None


def atspi_get(obj):
    native = getattr(obj, 'native', None)
    if getattr(obj, 'provider', '') != 'atspi' or native is None:
        return None
    Atspi = _atspi()
    if Atspi is None:
        return None
    try:
        count = Atspi.Text.get_character_count(native)
        return _text(Atspi.Text.get_text(native, 0, count))
    except Exception:                                # noqa: BLE001
        return None


def atspi_set(obj, text):
    native = getattr(obj, 'native', None)
    if getattr(obj, 'provider', '') != 'atspi' or native is None:
        return False
    Atspi = _atspi()
    if Atspi is None:
        return False
    try:
        return bool(Atspi.EditableText.set_text_contents(native,
                                                         _text(text)))
    except Exception:                                # noqa: BLE001
        return False


#: Every way in, by name - what the toolkit modules list in their plans.
SETTERS = {'uia': uia_set, 'msaa': msaa_set, 'jab': jab_set,
           'atspi': atspi_set,
           'win32': lambda obj, text: win32_set(getattr(obj, 'hwnd', 0),
                                                text)}
GETTERS = {'uia': uia_get, 'msaa': msaa_get, 'jab': jab_get,
           'atspi': atspi_get,
           'win32': lambda obj: win32_get(getattr(obj, 'hwnd', 0))}


def can(method, obj):
    """Whether ``method`` can write this control - asked BEFORE writing,
    so a field is never half-written one way and then another."""
    if method == 'uia':
        return uia_can_set(obj)
    if method == 'win32':
        return is_edit_window(getattr(obj, 'hwnd', 0))
    if method == 'jab':
        native = getattr(obj, 'native', None)
        return getattr(obj, 'provider', '') == 'jab' and \
            hasattr(native, 'set_text')
    if method == 'atspi':
        return getattr(obj, 'provider', '') == 'atspi'
    if method == 'msaa':
        return bool(getattr(obj, 'hwnd', 0)) and \
            msaa_get(obj) is not None
    return False
