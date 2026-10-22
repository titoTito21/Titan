# -*- coding: utf-8 -*-
"""A message sent to another program's window, with a deadline.

`SendMessage` into another process waits for that process's GUI thread
to answer - for ever, if it has hung, or if it is busy inside a modal
loop that the message started (`BM_CLICK` on a button that opens a
dialog returns only when the dialog is closed). A screen reader's thread
must never wait like that: the whole reader goes quiet with it, and when
the thread waiting is one Titan's own window needs, Titan goes with it.

So every message the reader sends goes through here: answered within
*timeout_ms*, or ``None``. Its own `WinDLL` handle, so the argument
types set here do not leak into ``ctypes.windll.user32``, which other
modules type their own way.
"""

import sys

if sys.platform.startswith("win"):
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    _user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                     ctypes.c_size_t, ctypes.c_size_t]
else:                                                # pragma: no cover
    ctypes = None
    _user32 = None

SMTO_ABORTIFHUNG = 0x0002
#: What the reader waits for one message by default.
DEFAULT_MS = 1000


def send(hwnd, msg, wparam=0, lparam=0, timeout_ms=DEFAULT_MS):
    """The answer to *msg*, or ``None`` when the window did not answer in
    time (or is hung, or is gone)."""
    if _user32 is None or not hwnd:
        return None
    out = ctypes.c_size_t(0)
    try:
        if not _user32.SendMessageTimeoutW(
                int(hwnd), int(msg), int(wparam or 0), int(lparam or 0),
                SMTO_ABORTIFHUNG, int(timeout_ms), ctypes.byref(out)):
            return None
    except Exception:                                # noqa: BLE001
        return None
    return int(out.value)


def post(hwnd, msg, wparam=0, lparam=0):
    """Queue *msg* for the window and return at once."""
    if _user32 is None or not hwnd:
        return False
    try:
        return bool(_user32.PostMessageW(int(hwnd), int(msg),
                                         int(wparam or 0), int(lparam or 0)))
    except Exception:                                # noqa: BLE001
        return False
