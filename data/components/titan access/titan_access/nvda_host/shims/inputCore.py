# -*- coding: utf-8 -*-
"""NVDA's `inputCore`: a gesture and the map of gestures to scripts."""

from .baseObject import AutoPropertyObject
from . import extensionPoints

decide_executeGesture = extensionPoints.Decider()


class NoInputGestureAction(LookupError):
    pass


class InputGesture(AutoPropertyObject):
    identifiers = ()
    displayName = ''
    isModifier = False
    shouldPreventSystemIdle = False
    reportInInputHelp = True

    @property
    def normalizedIdentifiers(self):
        return [normalizeGestureIdentifier(one) for one in self.identifiers]

    def send(self):
        pass


def normalizeGestureIdentifier(identifier):
    identifier = str(identifier or '').lower()
    if ':' not in identifier:
        return identifier
    source, keys = identifier.split(':', 1)
    parts = keys.split('+')
    mods = sorted(part for part in parts[:-1])
    return '%s:%s' % (source, '+'.join(mods + parts[-1:]))


class _Manager(object):
    userGestureMap = None

    def executeGesture(self, gesture):
        raise NoInputGestureAction


manager = _Manager()
SCRCAT_MISC = 'Miscellaneous'


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
