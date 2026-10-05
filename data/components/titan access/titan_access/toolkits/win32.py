# -*- coding: utf-8 -*-
"""Native Win32, MFC and Visual Basic 6: the standard edit control.

An Edit or RichEdit control is a window of its own, so `WM_SETTEXT` and
`WM_GETTEXT` reach it exactly, need no accessibility at all and cannot be
refused by a proxy. Windows' own MSAA/UIA proxies cover the rest.
"""

from .base import Toolkit


class Win32(Toolkit):
    FRAMEWORKS = ('win32', 'mfc', 'vb6', 'directui', '')
    NAME = 'Win32'
    PLAN = ('win32', 'uia', 'msaa', 'keys')
    NOTE = ('Standard controls are windows of their own: an Edit or '
            'RichEdit takes WM_SETTEXT directly. Windows proxies them for '
            'MSAA and UI Automation, which cover everything else.')


TOOLKIT = Win32()
