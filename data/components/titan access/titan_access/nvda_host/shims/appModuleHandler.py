# -*- coding: utf-8 -*-
"""NVDA's `appModuleHandler`: a module for ONE program."""

import os

from .baseObject import ScriptableObject


class AppModule(ScriptableObject):
    sleepMode = False

    def __init__(self, processID, appName=None):
        super().__init__()
        self.processID = processID
        self.appName = appName or getAppNameFromProcessID(processID)

    def terminate(self):
        pass

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        pass

    @property
    def productName(self):
        return self.appName

    @property
    def appPath(self):
        return ''


def getAppNameFromProcessID(processID, includeExt=False):
    try:
        import psutil
        name = psutil.Process(int(processID)).name()
    except Exception:                                # noqa: BLE001
        return ''
    if not includeExt:
        name = os.path.splitext(name)[0]
    return name.lower()


def getAppModuleForNVDAObject(obj):
    from titan_access import nvda_host
    return nvda_host.app_module_for(obj)


runningTable = {}


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
