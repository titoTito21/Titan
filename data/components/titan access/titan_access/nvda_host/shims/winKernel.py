# -*- coding: utf-8 -*-
"""NVDA's `winKernel`: kernel32 by name, Windows only."""

import sys

kernel32 = None
if sys.platform.startswith('win'):
    import ctypes
    kernel32 = ctypes.windll.kernel32


def GetTickCount():
    import time
    return int(time.monotonic() * 1000)


def __getattr__(name):
    if kernel32 is not None:
        found = getattr(kernel32, name, None) or \
            getattr(kernel32, name[:1].upper() + name[1:], None)
        if found is not None:
            return found
    raise AttributeError(name)
