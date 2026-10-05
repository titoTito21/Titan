# -*- coding: utf-8 -*-
import wx


class CustomCheckListBox(wx.CheckListBox):
    pass


class AutoWidthColumnListCtrl(wx.ListCtrl):
    def __init__(self, parent, id=wx.ID_ANY, autoSizeColumn='LAST',
                 itemTextCallable=None, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=0):
        super().__init__(parent, id, pos, size, style | wx.LC_REPORT)


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
