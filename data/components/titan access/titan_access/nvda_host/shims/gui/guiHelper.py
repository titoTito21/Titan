# -*- coding: utf-8 -*-
"""NVDA's `gui.guiHelper`: a labelled-control builder over a wx sizer."""

import wx

SPACE_BETWEEN_VERTICAL_DIALOG_ITEMS = 10
BORDER_FOR_DIALOGS = 10


class ButtonHelper(object):
    def __init__(self, orientation):
        self.sizer = wx.BoxSizer(orientation)

    def addButton(self, parent, *args, **kwargs):
        button = wx.Button(parent, *args, **kwargs)
        self.sizer.Add(button, 0, wx.ALL, 2)
        return button


class LabeledControlHelper(object):
    def __init__(self, parent, labelText, wxCtrlClass, **kwargs):
        self.sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.label = wx.StaticText(parent, label=labelText)
        self.control = wxCtrlClass(parent, **kwargs)
        self.sizer.Add(self.label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.sizer.Add(self.control, 1, wx.EXPAND)


class BoxSizerHelper(object):
    def __init__(self, parent, orientation=wx.VERTICAL, sizer=None):
        self.parent = parent
        self.sizer = sizer or wx.BoxSizer(orientation)

    def addItem(self, item, **kwargs):
        target = getattr(item, 'sizer', item)
        self.sizer.Add(target, kwargs.get('proportion', 0),
                       kwargs.get('flag', wx.EXPAND | wx.BOTTOM), 4)
        return getattr(item, 'control', item)

    def addLabeledControl(self, labelText, wxCtrlClass, **kwargs):
        helper = LabeledControlHelper(self.parent, labelText, wxCtrlClass,
                                      **kwargs)
        self.sizer.Add(helper.sizer, 0, wx.EXPAND | wx.BOTTOM, 4)
        return helper.control

    def addDialogDismissButtons(self, buttons, separated=False):
        target = getattr(buttons, 'sizer', buttons)
        self.sizer.Add(target, 0, wx.ALIGN_RIGHT | wx.TOP, 6)
        return buttons


def associateElements(first, second):
    sizer = wx.BoxSizer(wx.HORIZONTAL)
    sizer.Add(first, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
    sizer.Add(second, 1, wx.EXPAND)
    return sizer


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
