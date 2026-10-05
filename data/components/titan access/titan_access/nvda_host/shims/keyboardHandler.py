# -*- coding: utf-8 -*-
"""NVDA's `keyboardHandler`: a key gesture, and sending one."""

from .inputCore import InputGesture


class KeyboardInputGesture(InputGesture):
    def __init__(self, modifiers=(), vkCode=0, scanCode=0, isExtended=False,
                 name=''):
        super().__init__()
        self.modifiers = tuple(modifiers)
        self.vkCode = vkCode
        self.scanCode = scanCode
        self.isExtended = isExtended
        self._name = str(name or '')
        self.mainKeyName = self._name.rsplit('+', 1)[-1]
        self.modifierNames = self._name.split('+')[:-1]

    @property
    def identifiers(self):
        return ('kb:' + self._name,)

    @classmethod
    def fromName(cls, name):
        return cls(name=str(name or '').lower())

    def send(self):
        from titan_access.portable import readerApi
        readerApi.send_key(self._name)


def getInputHook():
    return None


passKeyThroughCount = -1


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
