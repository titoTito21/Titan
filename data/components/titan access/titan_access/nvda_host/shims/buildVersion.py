# -*- coding: utf-8 -*-
"""NVDA's `buildVersion`. Titan Access answers as a current NVDA, so an
add-on chooses its newest code paths."""

version_year = 2025
version_major = 3
version_minor = 0
version_build = 0
version = '2025.3'
version_detailed = version
updateVersionType = 'stable'
copyrightYears = '2006-2025'
publisher = 'Titan Access'
name = 'NVDA'
longName = 'Titan Access (NVDA add-on host)'


def formatBuildVersionString():
    return version


def formatVersionForGUI(year, major, minor):
    return '%d.%d.%d' % (year, major, minor)


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
