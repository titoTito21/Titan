# -*- coding: utf-8 -*-
"""NVDA's `driverHandler`."""

from .autoSettingsUtils.autoSettings import AutoSettings
from .autoSettingsUtils.driverSetting import (BooleanDriverSetting,  # noqa
                                              DriverSetting,
                                              NumericDriverSetting)


class Driver(AutoSettings):
    name = ''
    description = ''

    def __init__(self):
        super().__init__()

    def terminate(self):
        pass

    @classmethod
    def check(cls):
        return False


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
