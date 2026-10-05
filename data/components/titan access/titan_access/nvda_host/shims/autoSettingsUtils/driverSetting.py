# -*- coding: utf-8 -*-
"""NVDA's `autoSettingsUtils.driverSetting`: what a synthesizer says it
can be set to - a choice, a number, a switch."""


class DriverSetting(object):
    def __init__(self, id, displayNameWithAccelerator='', availableInSettingsRing=False,
                 defaultVal=None, displayName=None, useConfig=True):
        self.id = id
        self.displayNameWithAccelerator = displayNameWithAccelerator
        self.displayName = displayName or \
            str(displayNameWithAccelerator or id).replace('&', '')
        self.availableInSettingsRing = availableInSettingsRing
        self.defaultVal = defaultVal
        self.useConfig = useConfig


class NumericDriverSetting(DriverSetting):
    def __init__(self, id, displayNameWithAccelerator='', availableInSettingsRing=False,
                 defaultVal=50, minVal=0, maxVal=100, minStep=1,
                 normalStep=5, largeStep=10, displayName=None,
                 useConfig=True):
        super().__init__(id, displayNameWithAccelerator,
                         availableInSettingsRing, defaultVal, displayName,
                         useConfig)
        self.minVal, self.maxVal = minVal, maxVal
        self.minStep, self.normalStep, self.largeStep = (minStep, normalStep,
                                                         largeStep)


class BooleanDriverSetting(DriverSetting):
    def __init__(self, id, displayNameWithAccelerator='', availableInSettingsRing=False,
                 displayName=None, defaultVal=False, useConfig=True):
        super().__init__(id, displayNameWithAccelerator,
                         availableInSettingsRing, defaultVal, displayName,
                         useConfig)


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
