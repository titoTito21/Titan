# -*- coding: utf-8 -*-
"""NVDA's `globalVars`: where NVDA's configuration lives is, for an
add-on in Titan Access, its own folder in the user's data."""

import os


class _AppArgs(object):
    secure = False
    launcher = False
    minimal = False
    disableAddons = False
    noLogging = False

    @property
    def configPath(self):
        from titan_access.nvda_host import config_folder
        return config_folder()


appArgs = _AppArgs()
appArgsExtra = []
appPid = os.getpid()
appDir = os.path.dirname(os.path.abspath(__file__))
focusObject = None
foregroundObject = None
navigatorObject = None
mouseObject = None
reviewPosition = None
reviewPositionObj = None
lastProgressValue = 0
settingsRing = None
exitCode = 0


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
