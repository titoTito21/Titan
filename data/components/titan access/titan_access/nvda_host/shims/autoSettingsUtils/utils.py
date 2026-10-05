# -*- coding: utf-8 -*-
"""NVDA's `autoSettingsUtils.utils`."""


class StringParameterInfo(object):
    def __init__(self, id, displayName=None):
        self.id = id
        self.displayName = displayName


class UnsupportedConfigParameterError(NotImplementedError):
    pass


def paramToPercent(current, min, max):
    return int(round(float(current - min) / (max - min) * 100)) \
        if max != min else 0


def percentToParam(percent, min, max):
    return int(round(float(percent) / 100 * (max - min) + min))


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
