# -*- coding: utf-8 -*-
"""Qt: UI Automation since 5.11, MSAA before that.

Qt widgets are "alien" - not windows of their own - so nothing about them
can be reached with window messages. From Qt 5.11 the Windows platform
plugin is a UI Automation provider (a QLineEdit takes
`ValuePattern.SetValue`); Qt 5.10 and earlier were reached through an
MSAA bridge with no IAccessible2, whose `put_accValue` sets an editable
text. NVDA's own Qt app module predates 5.11 and no longer applies to it
(nvaccess/nvda#8604). A QML item often carries its text in the
DESCRIPTION rather than the name, which `read_text` falls back on.

Sources: github.com/nvaccess/nvda issues #8604 and #4258; Qt's
"Accessibility" documentation.
"""

from .base import Toolkit


class Qt(Toolkit):
    FRAMEWORKS = ('qt',)
    NAME = 'Qt'
    PLAN = ('uia', 'msaa', 'keys')
    READ = ('uia', 'msaa')
    NOTE = ('Qt widgets are not windows. Qt 5.11+ and Qt 6 are UI Automation '
            'providers (ValuePattern.SetValue on a line edit); Qt 5.10 and '
            'older answer MSAA only (nvaccess/nvda#8604). QML items may keep '
            'their text in the description.')

    def read_text(self, obj):
        found = Toolkit.read_text(self, obj)
        if found:
            return found
        described = str(getattr(obj, 'description', '') or '')
        return described or found


TOOLKIT = Qt()
