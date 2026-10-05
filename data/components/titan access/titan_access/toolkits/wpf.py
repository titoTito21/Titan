# -*- coding: utf-8 -*-
"""WPF ("Avalon"): UI Automation is its native accessibility.

Every WPF control is an `AutomationPeer`; a `TextBox` supports
ValuePattern (and TextPattern, read-only, for the reader), so its text is
replaced with `ValuePattern.SetValue` - Microsoft's own documented way to
change a text control's content. A `RichTextBox` exposes TextPattern but
no ValuePattern, and a `PasswordBox` refuses to give its value, so both are
written with the user's keys. Lists are often VIRTUALIZED: an item off
the screen is a placeholder until `VirtualizedItemPattern.Realize` is
called (.NET 4, with ItemContainerPattern to find it) - which is what
`realize` does before a row is read.

Sources: learn.microsoft.com - "UI Automation TextPattern Overview",
"VirtualizedItemPattern Class", "UI Automation of a WPF Custom Control".
"""

from . import providers
from .base import Toolkit

UIA_VIRTUALIZED_ITEM_PATTERN = 10020


class Wpf(Toolkit):
    FRAMEWORKS = ('wpf',)
    NAME = 'WPF'
    PLAN = ('uia', 'keys')
    READ = ('uia',)
    NOTE = ('WPF speaks UI Automation natively: a TextBox takes '
            'ValuePattern.SetValue; a RichTextBox has only TextPattern and a '
            'PasswordBox hides its value, so those take the keys. Virtualized '
            'list items are placeholders until VirtualizedItemPattern.Realize.')

    def mode(self, obj):
        if str(getattr(obj, 'role', '')) == 'password':
            return 'keys'
        return Toolkit.mode(self, obj)

    @staticmethod
    def realize(obj):
        """Make a virtualized item a real element. True when it was one."""
        control = providers._uia_control(obj)
        if control is None:
            return False
        try:
            pattern = control.GetPattern(UIA_VIRTUALIZED_ITEM_PATTERN)
            if pattern is None:
                return False
            pattern.Realize()
            return True
        except Exception:                            # noqa: BLE001
            return False


TOOLKIT = Wpf()
