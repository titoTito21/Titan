# -*- coding: utf-8 -*-
import wx


def messageBox(message, caption=wx.MessageBoxCaptionStr,
               style=wx.OK | wx.CENTER, parent=None):
    return wx.MessageBox(str(message), str(caption), style, parent)


class ReturnCode(object):
    OK = wx.ID_OK
    CANCEL = wx.ID_CANCEL
    YES = wx.ID_YES
    NO = wx.ID_NO


class DisplayableError(Exception):
    def __init__(self, displayMessage, titleMessage=None):
        super().__init__(displayMessage)
        self.displayMessage = displayMessage
        self.titleMessage = titleMessage


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
