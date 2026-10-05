# -*- coding: utf-8 -*-
"""NVDA's `globalCommands`: the script categories add-ons name."""

SCRCAT_TEXTREVIEW = 'Text review'
SCRCAT_OBJECTNAVIGATION = 'Object navigation'
SCRCAT_SYSTEMCARET = 'System caret'
SCRCAT_MOUSE = 'Mouse'
SCRCAT_SPEECH = 'Speech'
SCRCAT_CONFIG = 'Configuration'
SCRCAT_BRAILLE = 'Braille'
SCRCAT_TOOLS = 'Tools'
SCRCAT_TOUCH = 'Touch screen'
SCRCAT_FOCUS = 'System focus'
SCRCAT_SYSTEM = 'System status'
SCRCAT_INPUT = 'Input'
SCRCAT_DOCUMENTFORMATTING = 'Document formatting'
SCRCAT_AUDIO = 'Audio'


class GlobalCommands(object):
    pass


commands = GlobalCommands()


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
