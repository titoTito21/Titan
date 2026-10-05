# -*- coding: utf-8 -*-
"""Titan Access's knowledge of each toolkit, one module per toolkit.

What a window is WRITTEN IN decides how its controls are reached: a Delphi
TEdit takes a window message, a Qt line edit a UI Automation pattern, a
Swing field the Java Access Bridge, a Tkinter entry nothing at all but the
user's own keys. `portable.toolkit` already answers which toolkit a window
is (from the libraries its process has loaded, UI Automation's
FrameworkId, and the window class); this package answers what to DO with
that, for the reader's walked edit fields:

* :func:`mode` - how this control will be written: a provider method
  (``'uia'``, ``'msaa'``, ``'win32'``, ``'jab'``, ``'atspi'``) or
  ``'keys'`` (the user's own keys passed on to the real control);
* :func:`set_text` - write the whole text that way;
* :func:`read_text` - the control's whole text, to start the copy from.

The modules: `win32` (also MFC, VB6), `wpf` (Avalon), `winforms`, `qt`,
`tk` (Tkinter), `java` (Swing, JavaFX), `gtk`, `wx`, `vcl` (Delphi),
`web` (Chromium, Electron, Firefox), `xaml` (WinUI, UWP, Flutter) and
`drawn` (consoles, game engines).
"""

import threading

from . import drawn, gtk, java, qt, tk, vcl, web, win32, winforms, wpf, \
    wx, xaml
from .base import Toolkit

_LOCK = threading.RLock()

#: Every toolkit module, in the order a framework is looked up.
ALL = (wpf.TOOLKIT, winforms.TOOLKIT, qt.TOOLKIT, tk.TOOLKIT) \
    + java.TOOLKITS + (gtk.TOOLKIT, wx.TOOLKIT, vcl.TOOLKIT, web.TOOLKIT,
                       xaml.TOOLKIT, drawn.TOOLKIT, win32.TOOLKIT)

#: What a control is written with when nothing is known about it.
FALLBACK = win32.TOOLKIT

_counts = {'modes': {}, 'written': 0, 'refused': 0}


def by_framework(framework):
    framework = str(framework or '').lower()
    for one in ALL:
        if framework in one.FRAMEWORKS:
            return one
    return FALLBACK


def framework_of(obj):
    """`portable.toolkit`'s answer for the window this control is in."""
    try:
        from titan_access import nvda_shape
        from titan_access.portable import toolkit
        adapted = obj if hasattr(obj, 'processID') else nvda_shape.adapt(obj)
        return toolkit.of(adapted)[0]
    except Exception:                                # noqa: BLE001
        return ''


def for_obj(obj):
    return by_framework(framework_of(obj))


def mode(obj):
    """How this control will be written: a provider method or 'keys'."""
    one = for_obj(obj)
    found = one.mode(obj)
    with _LOCK:
        _counts['modes'][found] = _counts['modes'].get(found, 0) + 1
    return found


def set_text(obj, text, method=None):
    """Write the whole text. True when the control took it."""
    one = for_obj(obj)
    method = method or one.mode(obj)
    done = one.set_text(obj, text, method)
    with _LOCK:
        _counts['written' if done else 'refused'] += 1
    return done


def read_text(obj):
    """The control's whole text, or None when its toolkit cannot say."""
    return for_obj(obj).read_text(obj)


def report():
    with _LOCK:
        found = {'modes': dict(_counts['modes']),
                 'written': _counts['written'],
                 'refused': _counts['refused']}
    found['toolkits'] = [one.describe() for one in ALL]
    return found


__all__ = ['ALL', 'Toolkit', 'by_framework', 'for_obj', 'framework_of',
           'mode', 'read_text', 'report', 'set_text']
