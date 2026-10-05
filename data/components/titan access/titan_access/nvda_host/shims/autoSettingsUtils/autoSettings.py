# -*- coding: utf-8 -*-
"""NVDA's `autoSettingsUtils.autoSettings`."""

from ..baseObject import AutoPropertyObject


class AutoSettings(AutoPropertyObject):
    supportedSettings = ()

    @classmethod
    def getId(cls):
        return getattr(cls, 'name', cls.__name__)

    @classmethod
    def _get_preInitSettings(cls):
        return ()

    def loadSettings(self, onlyChanged=False):
        pass

    def saveSettings(self):
        pass

    def isSupported(self, settingID):
        return any(getattr(one, 'id', None) == settingID
                   for one in self.supportedSettings)


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
