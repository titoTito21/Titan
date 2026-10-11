# -*- coding: utf-8 -*-
"""NVDA's `synthDriverHandler`: the base every NVDA synthesizer extends,
and the notifications by which it says where it has got to. In Titan
Access a synthesizer is EXTERNAL SYNTHESIS - a subsystem of the reader,
never one of Titan's own TTS engines."""

from collections import OrderedDict

from . import extensionPoints
from .autoSettingsUtils.driverSetting import (BooleanDriverSetting,
                                              DriverSetting,
                                              NumericDriverSetting)
from .autoSettingsUtils.utils import (paramToPercent,  # noqa: F401
                                      percentToParam, StringParameterInfo)
from .driverHandler import Driver

synthIndexReached = extensionPoints.Action()
synthDoneSpeaking = extensionPoints.Action()
synthChanged = extensionPoints.Action()
pre_synthSpeak = extensionPoints.Action()
pre_synthCancel = extensionPoints.Action()


class VoiceInfo(StringParameterInfo):
    def __init__(self, id, displayName, language=None):
        super().__init__(id, displayName)
        self.language = language


class LanguageInfo(StringParameterInfo):
    """A language - its display name worded from its id, as NVDA does."""

    def __init__(self, id, displayName=None):
        if displayName is None:
            from .languageHandler import getLanguageDescription
            displayName = getLanguageDescription(id)
        super().__init__(id, displayName)


class SynthDriver(Driver):
    name = ''
    description = ''
    supportedSettings = ()
    supportedCommands = frozenset()
    supportedNotifications = frozenset()

    @classmethod
    def LanguageSetting(cls):
        return DriverSetting('language', 'Language')

    @classmethod
    def VoiceSetting(cls):
        return DriverSetting('voice', '&Voice')

    @classmethod
    def VariantSetting(cls):
        return DriverSetting('variant', 'V&ariant')

    @classmethod
    def RateSetting(cls, minStep=1):
        return NumericDriverSetting('rate', '&Rate', True, minStep=minStep)

    @classmethod
    def RateBoostSetting(cls):
        return BooleanDriverSetting('rateBoost', 'Rate boos&t')

    @classmethod
    def VolumeSetting(cls, minStep=1):
        return NumericDriverSetting('volume', 'V&olume', True,
                                    defaultVal=100, minStep=minStep)

    @classmethod
    def PitchSetting(cls, minStep=1):
        return NumericDriverSetting('pitch', '&Pitch', True,
                                    minStep=minStep)

    @classmethod
    def InflectionSetting(cls, minStep=1):
        return NumericDriverSetting('inflection', '&Inflection', True,
                                    minStep=minStep)

    def speak(self, speechSequence):
        raise NotImplementedError

    def cancel(self):
        pass

    def pause(self, switch):
        pass

    def _get_language(self):
        return None

    # **Kept, as NVDA keeps them.** NVDA's own base class remembers the
    # lists in ``_availableVoices`` / ``_availableVariants`` and a driver
    # throws one away by deleting it - Cerence does exactly that when its
    # voice changes, because each voice has its own variants (compact,
    # embedded-pro, embedded-high). Asked afresh every time, the walked
    # settings and the dialog paid a database listing per row.
    def _get_availableVoices(self):
        if not hasattr(self, '_availableVoices'):
            self._availableVoices = self._getAvailableVoices()
        return self._availableVoices

    def _getAvailableVoices(self):
        return OrderedDict()

    def _get_availableVariants(self):
        if not hasattr(self, '_availableVariants'):
            self._availableVariants = self._getAvailableVariants()
        return self._availableVariants

    def _getAvailableVariants(self):
        return OrderedDict()

    def _paramToPercent(self, current, min, max):
        return paramToPercent(current, min, max)

    def _percentToParam(self, percent, min, max):
        return percentToParam(percent, min, max)

    def initSettings(self):
        pass


_current = [None]


def getSynth():
    return _current[0]


def setSynth(name, isFallback=False):
    return False


def getSynthList():
    from titan_access import nvda_host
    return [(one['name'], one['description'])
            for one in nvda_host.synthesizers()]


def getSynthInstance(name, asDefault=False):
    from titan_access import nvda_host
    return nvda_host.synth_instance(name)


def isDebugForSynthDriver():
    return False


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
