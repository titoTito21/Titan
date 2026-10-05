# -*- coding: utf-8 -*-
"""NVDA's `winUser`: the user32 calls add-ons use most, and the rest of
user32 by name. Windows only; elsewhere every call answers nothing."""

import sys

_IS_WINDOWS = sys.platform.startswith('win')
user32 = None
if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

MB_OK = 0
MB_ICONERROR = 0x10
MB_ICONINFORMATION = 0x40
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
WM_CLOSE = 0x0010
SW_SHOWNORMAL = 1


def getForegroundWindow():
    return user32.GetForegroundWindow() if user32 else 0


def setForegroundWindow(hwnd):
    return user32.SetForegroundWindow(hwnd) if user32 else 0


def getClassName(hwnd):
    if not user32:
        return ''
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def getWindowText(hwnd):
    if not user32:
        return ''
    buffer = ctypes.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, buffer, 1024)
    return buffer.value


def getCursorPos():
    if not user32:
        return (0, 0)
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point


def setCursorPos(x, y):
    return user32.SetCursorPos(int(x), int(y)) if user32 else 0


def mouse_event(flags, x, y, data, extra):
    if user32:
        user32.mouse_event(int(flags), int(x), int(y), int(data), int(extra))


def getWindowThreadProcessID(hwnd):
    if not user32:
        return (0, 0)
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return (pid.value, tid)


def sendMessage(hwnd, msg, wParam, lParam):
    return user32.SendMessageW(hwnd, msg, wParam, lParam) if user32 else 0


def MessageBox(hwnd, text, caption, type):
    return user32.MessageBoxW(hwnd, text, caption, type) if user32 else 0


def __getattr__(name):
    if user32 is not None:
        found = getattr(user32, name, None) or \
            getattr(user32, name[:1].upper() + name[1:], None)
        if found is not None:
            return found
    raise AttributeError(name)
