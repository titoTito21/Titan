# -*- coding: utf-8 -*-
"""NVDA's `addonAPIVersion`."""

CURRENT = (2025, 3, 0)
BACK_COMPAT_TO = (2025, 1, 0)


def formatForGUI(version):
    return '%d.%d.%d' % tuple(version)


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
