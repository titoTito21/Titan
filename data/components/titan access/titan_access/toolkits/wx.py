# -*- coding: utf-8 -*-
"""wxWidgets: native controls on every platform.

`wx.TextCtrl` on Windows IS an Edit (or RichEdit, with `wx.TE_RICH2`)
window, so it takes `WM_SETTEXT`; on Linux wxWidgets is GTK 3 and the
field is AT-SPI's. Titan's own windows are wxWidgets.
"""

from .base import Toolkit


class Wx(Toolkit):
    FRAMEWORKS = ('wx', 'python')
    NAME = 'wxWidgets'
    PLAN = ('win32', 'uia', 'atspi', 'msaa', 'keys')
    NOTE = ('wx.TextCtrl is a native Edit/RichEdit on Windows (WM_SETTEXT) '
            'and a GTK entry on Linux (AT-SPI).')


TOOLKIT = Wx()
