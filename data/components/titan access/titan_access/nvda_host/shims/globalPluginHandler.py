# -*- coding: utf-8 -*-
"""NVDA's `globalPluginHandler`: a plugin that is always running."""

from .baseObject import ScriptableObject

runningPlugins = set()


class GlobalPlugin(ScriptableObject):
    def __init__(self):
        super().__init__()

    def terminate(self):
        pass

    def chooseNVDAObjectOverlayClasses(self, obj, clsList):
        pass


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
