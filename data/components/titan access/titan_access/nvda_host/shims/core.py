# -*- coding: utf-8 -*-
"""NVDA's `core`: later, and the moments NVDA announces."""

import threading

from . import extensionPoints

postNvdaStartup = extensionPoints.Action()
preNvdaExit = extensionPoints.Action()


def callLater(delay, callable, *args, **kwargs):
    try:
        import wx
        if wx.GetApp() is not None:
            return wx.CallLater(int(delay), callable, *args, **kwargs)
    except Exception:                                # noqa: BLE001
        pass
    timer = threading.Timer(max(0.0, float(delay) / 1000.0), callable,
                            args=args, kwargs=kwargs)
    timer.daemon = True
    timer.start()
    return timer


def requestPump():
    pass


def restart(disableAddons=False, debugLogging=False):
    pass


def triggerNVDAExit(newNVDA=None):
    return False


def isMainThread():
    return threading.current_thread() is threading.main_thread()


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
