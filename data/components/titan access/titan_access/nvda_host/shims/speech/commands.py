# -*- coding: utf-8 -*-
"""NVDA's `speech.commands`: what a speech sequence is made of besides
text. A synthesizer receives these and turns them into its own markup."""


class SpeechCommand(object):
    pass


class SynthCommand(SpeechCommand):
    pass


class SynthParamCommand(SynthCommand):
    isDefault = False


class IndexCommand(SynthCommand):
    def __init__(self, index):
        self.index = index

    def __repr__(self):
        return 'IndexCommand(%r)' % self.index


class CharacterModeCommand(SynthParamCommand):
    def __init__(self, state):
        self.state = state
        self.isDefault = not state


class LangChangeCommand(SynthParamCommand):
    def __init__(self, lang):
        self.lang = lang
        self.isDefault = not lang


class BreakCommand(SynthCommand):
    def __init__(self, time=0):
        self.time = time


class EndUtteranceCommand(SpeechCommand):
    pass


class BaseProsodyCommand(SynthParamCommand):
    settingName = None

    def __init__(self, offset=0, multiplier=1):
        if offset != 0 and multiplier != 1:
            raise ValueError('offset and multiplier are exclusive')
        self._offset = offset
        self._multiplier = multiplier
        self.isDefault = offset == 0 and multiplier == 1

    @property
    def defaultValue(self):
        from . import _synth_value
        return _synth_value(self.settingName)

    @property
    def multiplier(self):
        if self._offset == 0:
            return self._multiplier
        base = self.defaultValue or 50
        return float(base + self._offset) / base if base else 1

    @property
    def offset(self):
        if self._multiplier == 1:
            return self._offset
        base = self.defaultValue or 50
        return int(base * self._multiplier - base)

    @property
    def newValue(self):
        base = self.defaultValue or 50
        if self._offset:
            return base + self._offset
        return int(base * self._multiplier)


class PitchCommand(BaseProsodyCommand):
    settingName = 'pitch'


class VolumeCommand(BaseProsodyCommand):
    settingName = 'volume'


class RateCommand(BaseProsodyCommand):
    settingName = 'rate'


class PhonemeCommand(SynthCommand):
    def __init__(self, ipa, text=None):
        self.ipa = ipa
        self.text = text


class BaseCallbackCommand(SpeechCommand):
    def run(self):
        pass


class CallbackCommand(BaseCallbackCommand):
    def __init__(self, callback, name=None):
        self._callback = callback
        self._name = name

    def run(self):
        self._callback()


class BeepCommand(SpeechCommand):
    def __init__(self, hz, length, left=50, right=50):
        self.hz, self.length, self.left, self.right = hz, length, left, right


class WaveFileCommand(SpeechCommand):
    def __init__(self, fileName):
        self.fileName = fileName


class ConfigProfileTriggerCommand(SpeechCommand):
    def __init__(self, trigger, enter=True):
        self.trigger, self.enter = trigger, enter


class SuppressUnicodeNormalizationCommand(SpeechCommand):
    def __init__(self, state=True):
        self.state = state


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
