# -*- coding: utf-8 -*-
"""NVDA's `systemUtils`."""

import os
import subprocess
import sys
import threading


def _isSecureDesktop():
    return False


def isRunningOnSecureDesktop():
    return False


def openUserConfigurationDirectory():
    from titan_access.nvda_host import config_folder
    path = config_folder()
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:                                # noqa: BLE001
        pass


def hasUiAccess():
    return False


def isLockScreenModeActive():
    return False


class ExecAndPump(threading.Thread):
    """Run a function on a thread and wait for it, keeping wx alive."""

    def __init__(self, func, *args, **kwargs):
        super().__init__(daemon=True)
        self.func, self.args, self.kwargs = func, args, kwargs
        self.threadExc = None
        self.funcRes = None
        self.start()
        while self.is_alive():
            self.join(0.05)
            try:
                import wx
                wx.Yield()
            except Exception:                        # noqa: BLE001
                pass
        if self.threadExc:
            raise self.threadExc

    def run(self):
        try:
            self.funcRes = self.func(*self.args, **self.kwargs)
        except Exception as error:                   # noqa: BLE001
            self.threadExc = error


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
