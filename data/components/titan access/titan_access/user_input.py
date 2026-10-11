# -*- coding: utf-8 -*-
"""Has the user done anything since a moment? (keyboard or mouse)

A focus event the user did not cause is rarely news. The Windows taskbar
says so most plainly: a button is focused with Win+T or Tab, read, and
about a second later - when its thumbnail comes up - focused AGAIN, by UI
Automation or by an MSAA event that arrives too late to be recognised as
the same focus change. Both were read: "the button, and a second later the
button again". The question that settles it is whether the user pressed or
moved anything between the two.

Windows answers it with ``GetLastInputInfo`` (keyboard and mouse, the
whole session). A key's own release arrives a moment AFTER the focus event
it caused, so input up to ``SETTLE_S`` after a moment is that same
keystroke, not a new one. Elsewhere there is no answer, and None says so.
"""

import ctypes
import sys
import time

SETTLE_S = 0.3


def last_input_time():
    """``time.time()`` of the user's last input, or None when unknown."""
    if not sys.platform.startswith('win'):
        return None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now_tick = ctypes.windll.kernel32.GetTickCount()
        age = ((now_tick - info.dwTime) & 0xFFFFFFFF) / 1000.0
        return time.time() - age
    except Exception:                                # noqa: BLE001
        return None


def acted_since(moment, last=None):
    """True when the user pressed or moved something after ``moment``
    (beyond the settling of the keystroke that caused it); True as well
    when nobody can tell - then nothing is suppressed."""
    when = (last or last_input_time)()
    if when is None:
        return True
    return when > moment + SETTLE_S
