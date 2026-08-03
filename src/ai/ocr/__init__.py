# -*- coding: utf-8 -*-
"""Titan AI OCR - an accessible mimic of an app that has no accessibility.

Some programs simply cannot be read: a game's custom-drawn menu, an installer
that paints its own widgets, a kiosk-style interface, a Java or Electron app
that exposes nothing. A screen reader has nothing to say about them because
there is nothing there to say.

This package builds the missing interface. It takes a picture of the window,
asks the AI to *read* it into a structured description of what is on screen -
regions, controls, their text, their state, where they are - merges that with
whatever Windows itself can still tell us, and renders the result as an ordinary
accessible Titan window: a tab bar of regions, a list of elements, Enter to
press one, F5 to look again. Pressing a row clicks the real control in the real
app, so the mimic is not a read-only report - it is a usable front end.

    capture.py     take the picture, and keep the transform that maps a pixel
                   in it back to a point on the real screen
    model.py       the Screen model the AI has to produce, and its validation
    recognizer.py  picture -> Screen: the vision call, the UIA merge, the
                   change detection that stops live mode burning requests
    actions.py     press a control for real (click / key), safely
    controls.py    one Element -> one real wx control, wired to the real app
    form_view.py   the controls rebuilt in a column inside the mimic
    overlay.py     the controls hooked onto the real window itself, each one
                   where the real one is - no second window at all
    mimic.py       the accessible window
    hotkeys.py     the global and Titan-UI shortcuts

Nothing here runs unless the user switches AI OCR on in Settings, AI features:
a scan sends a picture of their screen to the configured provider.

Related: the ``titan_talk`` gamepad mode does a much simpler, Gemini-only,
flat-list version of this for audio games. This package is the general one -
provider-agnostic, structured, and driven from the Titan UI.
"""

from src.ai.ocr.model import Element, Region, Screen        # noqa: F401
from src.ai.ocr.capture import Capture, capture_screen, capture_window  # noqa: F401

__all__ = ['Element', 'Region', 'Screen', 'Capture',
           'capture_screen', 'capture_window', 'show_ai_ocr',
           'show_ai_ocr_overlay']


def show_ai_ocr(parent=None, scope=None):
    """Open the AI OCR mimic for the window the user was just in.

    Imported lazily: this module is pulled in by settings and menu code that
    must not drag wx dialogs (or a vision SDK) in with it.
    """
    from src.ai.ocr.mimic import show_ai_ocr as _show
    return _show(parent=parent, scope=scope)


def show_ai_ocr_overlay(parent=None, scope=None):
    """Put accessible controls straight onto the window the user is in.

    The same reading, rendered onto the real window instead of into a window of
    Titan's own - control over control, window over window.
    """
    from src.ai.ocr.mimic import show_ai_ocr_overlay as _show
    return _show(parent=parent, scope=scope)
