# -*- coding: utf-8 -*-
"""The native keyboard hook (`lib/titan_keyhook.dll`), from Python.

Windows gives a low-level keyboard hook a few hundred milliseconds to
answer each key and UNHOOKS one that is late once too often - silently,
so a reader whose hook callback is Python goes on believing it has the
keyboard while every key goes past it. The DLL owns the hook on a thread
of its own and answers Windows within a deadline whatever Python is
doing: the decision is asked of Python on a second thread, a late answer
is thrown away (that one key goes through to the application), and a
watchdog puts the hooks back when Windows saw input the hooks did not.

This module is the whole of the Python side: load the DLL, hand it a
decider, read its counters. `keyboard_hook.KeyboardHook` asks for it
first and keeps its own `SetWindowsHookEx` for a machine without the DLL,
so nothing here is required - only better.
"""

import ctypes
import os
import platform
import threading

_LOCK = threading.RLock()
_dll = None
_dll_error = ''

#: The deadline Python is held to for one key, in milliseconds. Windows'
#: own LowLevelHooksTimeout defaults to 300; well inside it.
DEFAULT_TIMEOUT_MS = 150

_IS_WINDOWS = platform.system() == 'Windows'

if _IS_WINDOWS:
    from ctypes import wintypes
    DECIDER = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                 ctypes.c_uint, ctypes.c_uint,
                                 ctypes.c_ulonglong)

    class TitanHookStatus(ctypes.Structure):
        _fields_ = [
            ('installed', ctypes.c_uint), ('events', ctypes.c_uint),
            ('swallowed', ctypes.c_uint), ('passed', ctypes.c_uint),
            ('late', ctypes.c_uint), ('reinstalls', ctypes.c_uint),
            ('mouseEvents', ctypes.c_uint), ('lastKeyTick', ctypes.c_uint),
            ('lastInputTick', ctypes.c_uint), ('timeoutMs', ctypes.c_uint),
            ('longestWaitMs', ctypes.c_uint),
        ]
else:
    DECIDER = None
    TitanHookStatus = None


def dll_path():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, 'lib', 'titan_keyhook.dll')


def _load():
    """The DLL, loaded once. None with the reason in `why_not()`."""
    global _dll, _dll_error
    with _LOCK:
        if _dll is not None:
            return _dll or None
        if not _IS_WINDOWS:
            _dll_error = 'not Windows'
            _dll = False
            return None
        path = dll_path()
        if not os.path.isfile(path):
            _dll_error = 'lib/titan_keyhook.dll is not built'
            _dll = False
            return None
        try:
            dll = ctypes.WinDLL(path)
            dll.TitanHook_Install.restype = ctypes.c_int
            dll.TitanHook_Install.argtypes = [DECIDER, ctypes.c_uint]
            dll.TitanHook_Uninstall.restype = None
            dll.TitanHook_Uninstall.argtypes = []
            dll.TitanHook_SetTimeout.restype = ctypes.c_int
            dll.TitanHook_SetTimeout.argtypes = [ctypes.c_uint]
            dll.TitanHook_Status.restype = ctypes.c_int
            dll.TitanHook_Status.argtypes = [ctypes.POINTER(TitanHookStatus)]
            dll.TitanHook_Rehook.restype = ctypes.c_int
            dll.TitanHook_Rehook.argtypes = []
            dll.TitanHook_IsWindowResponding.restype = ctypes.c_int
            dll.TitanHook_IsWindowResponding.argtypes = [wintypes.HWND,
                                                         ctypes.c_uint]
        except Exception as error:                   # noqa: BLE001
            _dll_error = str(error)
            _dll = False
            return None
        _dll = dll
        return dll


def available():
    return _load() is not None


def why_not():
    _load()
    return _dll_error


class NativeHook(object):
    """One installed hook. `decider(vk, scan, flags, is_down, extra)` is
    Python's answer - truthy to swallow the key - asked on the DLL's own
    decider thread, never on the hook thread."""

    def __init__(self, decider, timeout_ms=DEFAULT_TIMEOUT_MS):
        self._decider = decider
        self._callback = None
        self.installed = False
        self.timeout_ms = int(timeout_ms or DEFAULT_TIMEOUT_MS)
        self.errors = 0

    def _decide(self, vk, scan, flags, is_down, extra):
        try:
            return 1 if self._decider(int(vk), int(scan), int(flags),
                                      bool(is_down), int(extra)) else 0
        except Exception:                            # noqa: BLE001
            self.errors += 1
            return 0

    def install(self):
        dll = _load()
        if dll is None or self.installed:
            return self.installed
        # The callback object must outlive the hook: the DLL holds only
        # the address, and a collected one is a jump into freed memory.
        self._callback = DECIDER(self._decide)
        self.installed = bool(dll.TitanHook_Install(self._callback,
                                                    self.timeout_ms))
        return self.installed

    def uninstall(self):
        dll = _load()
        if dll is not None and self.installed:
            try:
                dll.TitanHook_Uninstall()
            except Exception:                        # noqa: BLE001
                pass
        self.installed = False

    def set_timeout(self, ms):
        dll = _load()
        if dll is None or not self.installed:
            return False
        self.timeout_ms = int(ms)
        return bool(dll.TitanHook_SetTimeout(int(ms)))

    def rehook(self):
        dll = _load()
        return bool(dll and self.installed and dll.TitanHook_Rehook())

    def status(self):
        return status()


def status():
    """The DLL's own counters, as a dict; empty when it is not there."""
    dll = _load()
    if dll is None:
        return {'available': False, 'why_not': _dll_error}
    box = TitanHookStatus()
    if not dll.TitanHook_Status(ctypes.byref(box)):
        return {'available': True}
    found = {name: int(getattr(box, name)) for name, _t in box._fields_}
    found['available'] = True
    return found


def window_responding(hwnd, timeout_ms=300):
    """Whether a window answers, asked with a deadline.

    1 answering, 0 hung, -1 not a window - and None when the DLL is not
    there, which callers treat as "go ahead", exactly as before.
    """
    dll = _load()
    if dll is None:
        return None
    try:
        return int(dll.TitanHook_IsWindowResponding(int(hwnd or 0),
                                                    int(timeout_ms)))
    except Exception:                                # noqa: BLE001
        return None
