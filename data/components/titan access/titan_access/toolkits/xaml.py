# -*- coding: utf-8 -*-
"""WinUI, UWP (XAML) and Flutter: UI Automation providers.

XAML controls are automation peers like WPF's; a `TextBox` takes
`ValuePattern.SetValue`. Flutter on Windows maps its semantics tree onto
UI Automation as well.
"""

from .base import Toolkit


class Xaml(Toolkit):
    FRAMEWORKS = ('xaml', 'silverlight', 'flutter')
    NAME = 'WinUI / XAML'
    PLAN = ('uia', 'keys')
    READ = ('uia',)
    NOTE = 'XAML and Flutter are UI Automation providers: ValuePattern.SetValue.'


TOOLKIT = Xaml()
