# -*- coding: utf-8 -*-
"""A window the reader opens is in FRONT, with the keyboard in it.

The menu (Insert+C), the managers, the speech system dialog, the settings,
a question the reader asks, an NVDA add-on's dialog: the user asks for one
with a key while they are in some other program, and Windows refuses the
foreground to a process that does not already own it. `wx.Frame.Raise` and
`Show` are refused in silence - the window appears BEHIND the program the
user is in, the taskbar button flashes, and somebody who cannot see the
screen hears nothing and has to Alt+Tab to find what they asked for.

So every command of the reader says it is about to open something
(`expect`), and for a few seconds afterwards a watcher looks at this
process's own top-level windows. The first one that is new, or that moved
to the top of this process's windows (a window already open and merely
raised again), is given the foreground the way `hostWindow._take` does it:
attached to the foreground thread's input queue, which is what lifts the
refusal. Asked, not polled for ever: nothing runs between commands.

Not touched: the popup menu's own window (``#32768`` - activating it
closes it), tool windows (the walked lists' host takes the keyboard
itself, and Titan's shell furniture is not something the user asked for),
and anything smaller than a real window (the 1x1 frame a popup menu is
hosted on is taken by the menu code directly).
"""

import os
import sys
import threading
import time

_LOCK = threading.RLock()
_state = {'until': 0.0, 'known': None, 'top': 0, 'thread': None,
          'taken': 0, 'refused': 0, 'expected': 0}

#: How long after a command a window it opens is still taken to the front.
#: Long enough for a manager that reads a store or a dialog built on a
#: worker; short enough that a window something else opens later is left
#: where it appears.
WATCH_S = 5.0

#: How often the watcher looks while it is watching.
TICK = 0.05

_IS_WINDOWS = sys.platform.startswith('win')

_SKIP_CLASSES = {'#32768',               # a popup menu
                 'tooltips_class32', 'IME', 'MSCTFIME UI',
                 'wxDisplayHiddenFrame'}


def report():
    with _LOCK:
        return {key: value for key, value in _state.items()
                if key not in ('known', 'thread')}


def expect(seconds=WATCH_S, replace=False):
    """A command is about to open a window: take it to the front when it
    appears. Called again while watching, it only extends the watch - the
    windows that were already there stay the ones that were there.
    ``replace`` sets the end of the watch to exactly ``seconds`` from now
    (the popup menu watches while it is open, then a few seconds more)."""
    if not _IS_WINDOWS:
        return
    now = time.time()
    with _LOCK:
        _state['expected'] += 1
        _state['until'] = now + float(seconds) if replace else \
            max(_state['until'], now + float(seconds))
        running = _state['thread'] is not None and \
            _state['thread'].is_alive()
        if running:
            return
        windows = _our_windows()
        _state['known'] = set(windows)
        _state['top'] = windows[0] if windows else 0
        thread = threading.Thread(target=_watch,
                                  name='TitanAccessForeground', daemon=True)
        _state['thread'] = thread
    thread.start()


def take(hwnd):
    """Bring one window of ours to the front now. True when Windows agreed."""
    if not _IS_WINDOWS or not hwnd:
        return False
    try:
        from .portable import hostWindow
        took = bool(hostWindow._take(int(hwnd)))
    except Exception:                                # noqa: BLE001
        took = False
    with _LOCK:
        _state['taken' if took else 'refused'] += 1
    return took


def _watch():
    try:
        while True:
            with _LOCK:
                if time.time() > _state['until']:
                    return
                known = _state['known'] or set()
                top = _state['top']
            windows = _our_windows()
            if windows:
                fresh = [one for one in windows if one not in known]
                wanted = fresh[0] if fresh else (
                    windows[0] if windows[0] != top else 0)
                if wanted and not _is_foreground(wanted):
                    take(wanted)
                with _LOCK:
                    _state['known'] = set(windows) | known
                    _state['top'] = windows[0]
            time.sleep(TICK)
    except Exception:                                # noqa: BLE001
        pass
    finally:
        with _LOCK:
            _state['thread'] = None


def _is_foreground(hwnd):
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        return int(user32.GetForegroundWindow() or 0) == int(hwnd)
    except Exception:                                # noqa: BLE001
        return True


def _our_windows():
    """This process's visible, real top-level windows, top of the z-order
    first."""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:                                # noqa: BLE001
        return []
    user32 = ctypes.windll.user32
    pid = os.getpid()
    found = []
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowLongW.restype = ctypes.c_long

    def visit(hwnd, _param):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid:
                return True
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
                return True
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, name, 64)
            if name.value in _SKIP_CLASSES:
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if rect.right - rect.left < 40 or rect.bottom - rect.top < 30:
                return True
            if user32.IsIconic(hwnd):
                return True
            found.append(int(hwnd))
        except Exception:                            # noqa: BLE001
            pass
        return True
    try:
        user32.EnumWindows(proto(visit), 0)
    except Exception:                                # noqa: BLE001
        return []
    return found
