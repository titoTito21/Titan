# -*- coding: utf-8 -*-
"""Windows Forms: native controls under a managed skin.

A `TextBox` is a real Edit window (class `WindowsForms10.EDIT.app...`) and
a `RichTextBox` a RichEdit one, so they take `WM_SETTEXT` like any Win32
edit control. Since .NET Framework 4.7.2 / .NET Core 3.0 Windows Forms
also has UI Automation providers, which are the way in for what is not an
edit window (a DataGridView cell being edited, for one).
"""

from .base import Toolkit


class WinForms(Toolkit):
    FRAMEWORKS = ('winforms',)
    NAME = 'Windows Forms'
    PLAN = ('win32', 'uia', 'msaa', 'keys')
    NOTE = ('TextBox and RichTextBox are native Edit/RichEdit windows '
            '(WindowsForms10.EDIT...) and take WM_SETTEXT; UI Automation '
            'covers the rest since .NET 4.7.2.')


TOOLKIT = WinForms()
