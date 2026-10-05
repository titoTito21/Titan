# -*- coding: utf-8 -*-
"""How a walked edit field reaches the REAL control.

The virtual window walks a copy of a field's text - the lines are its
rows, the characters what Left and Right say. That copy used to be put
back with ``obj.value = text``, and neither reader's objects take that:
NVDA's ``value`` is a read-only property and so is Titan Access's. So the
user typed, heard every letter, and the real field never changed - which
is not editing, it is pretending to.

A field is reached the way its TOOLKIT allows, and :data:`PLANS` is that
knowledge, one line per toolkit, best first:

* ``uia`` - UI Automation's ValuePattern.SetValue (WPF, WinUI, Qt 5.11+);
* ``msaa`` - IAccessible::put_accValue (old Qt, Tk 9.1, legacy controls);
* ``win32`` - WM_SETTEXT on an Edit/RichEdit window (Win32, Windows Forms,
  Delphi's VCL, wxWidgets);
* ``jab`` - the Java Access Bridge's setTextContents (Swing);
* ``atspi`` - AT-SPI's EditableText (Linux);
* ``keys`` - the user's own keys passed on to the real control, focused
  for them: the only way into Tk before 9.1, GTK on Windows, a console, a
  game, and the right way into a web page, whose scripts ignore a value
  set through accessibility.

Titan Access answers these through its own `toolkits` package (one module
per toolkit, with its quirks); in NVDA they are answered here, with
NVDA's own objects. Both readers use the same plan, and a test fails if
the two disagree.
"""

import ctypes

#: The ways to write a field in each toolkit, best first. The keys are
#: `toolkit`'s own framework names; '' is a window nothing could identify.
PLANS = {
    'wpf': ('uia', 'keys'),
    'winforms': ('win32', 'uia', 'msaa', 'keys'),
    'qt': ('uia', 'msaa', 'keys'),
    'tk': ('keys',),
    'java': ('jab', 'keys'),
    'javafx': ('uia', 'keys'),
    'gtk': ('atspi', 'keys'),
    'wx': ('win32', 'uia', 'atspi', 'msaa', 'keys'),
    'python': ('win32', 'uia', 'atspi', 'msaa', 'keys'),
    'vcl': ('win32', 'msaa', 'uia', 'keys'),
    'chromium': ('keys',), 'cef': ('keys',), 'electron': ('keys',),
    'gecko': ('keys',), 'mshtml': ('keys',), 'sciter': ('keys',),
    'xaml': ('uia', 'keys'), 'silverlight': ('uia', 'keys'),
    'flutter': ('uia', 'keys'),
    'console': ('keys',), 'unity': ('keys',), 'godot': ('keys',),
    'sdl': ('keys',),
    'win32': ('win32', 'uia', 'msaa', 'keys'),
    'mfc': ('win32', 'uia', 'msaa', 'keys'),
    'vb6': ('win32', 'uia', 'msaa', 'keys'),
    'directui': ('win32', 'uia', 'msaa', 'keys'),
    '': ('win32', 'uia', 'msaa', 'keys'),
}

#: Window classes that are an edit control, whatever program they are in.
EDIT_CLASSES = ('edit', 'richedit', 'richedit20', 'richedit50w',
                'riched20', 'riched32', 'tedit', 'tmemo', 'trichedit',
                'tmaskedit', 'tlabelededit', 'thundertextbox',
                'thunderrt6textbox', 'windowsforms10.edit',
                'windowsforms10.richedit', 'wxwindownr', 'atl:edit')

WM_SETTEXT = 0x000C
SMTO_ABORTIFHUNG = 0x0002


def _text(value):
    return str(value or '')


def plan_for(obj):
    try:
        from . import toolkit
        framework = toolkit.of(obj)[0]
    except Exception:                                # noqa: BLE001
        framework = ''
    return PLANS.get(framework, PLANS[''])


# --------------------------------------------------------------------------- #
# NVDA's own objects
# --------------------------------------------------------------------------- #
def _value_pattern(obj):
    try:
        import UIAHandler
        return obj._getUIAPattern(UIAHandler.UIA_ValuePatternId,
                                  UIAHandler.IUIAutomationValuePattern)
    except Exception:                                # noqa: BLE001
        return None


def _is_edit_window(obj):
    name = _text(getattr(obj, 'windowClassName', '')).lower()
    return bool(name) and any(name.startswith(one) for one in EDIT_CLASSES)


def can(method, obj):
    """Whether ``method`` can write this control, asked before writing."""
    if obj is None:
        return False
    if method == 'uia':
        pattern = _value_pattern(obj)
        try:
            return pattern is not None and not pattern.CurrentIsReadOnly
        except Exception:                            # noqa: BLE001
            return False
    if method == 'msaa':
        return getattr(obj, 'IAccessibleObject', None) is not None
    if method == 'win32':
        return _is_edit_window(obj) and bool(getattr(obj, 'windowHandle', 0))
    if method == 'jab':
        context = getattr(obj, 'jabContext', None)
        return context is not None and hasattr(context, 'setTextContents')
    return False


def mode(obj):
    """How this control will be written: a method of the plan, or 'keys'."""
    for method in plan_for(obj):
        if method == 'keys':
            return 'keys'
        if can(method, obj):
            return method
    return 'keys'


def set_text(obj, text, method):
    """Write the whole text with ``method``. True when the control took it."""
    text = _text(text)
    try:
        if method == 'uia':
            pattern = _value_pattern(obj)
            if pattern is None:
                return False
            pattern.SetValue(text)
            return True
        if method == 'msaa':
            acc = obj.IAccessibleObject
            child = getattr(obj, 'IAccessibleChildID', 0) or 0
            acc._IAccessible__com__set_accValue(child, text)
            # Many proxies say yes and change nothing: believe the control.
            return _text(acc.accValue(child)) == text
        if method == 'win32':
            result = ctypes.c_size_t(0)
            buffer = ctypes.create_unicode_buffer(text)
            ctypes.windll.user32.SendMessageTimeoutW(
                ctypes.c_void_p(int(obj.windowHandle)), WM_SETTEXT, 0,
                ctypes.cast(buffer, ctypes.c_void_p), SMTO_ABORTIFHUNG,
                1500, ctypes.byref(result))
            return bool(result.value)
        if method == 'jab':
            return bool(obj.jabContext.setTextContents(text))
    except Exception:                                # noqa: BLE001
        return False
    return False


def read_text(obj):
    """The control's whole text, or None. NVDA's text info is the one
    answer that works for every kind of field it can read at all."""
    if obj is None:
        return None
    try:
        import textInfos
        return _text(obj.makeTextInfo(textInfos.POSITION_ALL).text)
    except Exception:                                # noqa: BLE001
        pass
    try:
        found = getattr(obj, 'value', None)
        return _text(found) if found is not None else None
    except Exception:                                # noqa: BLE001
        return None
