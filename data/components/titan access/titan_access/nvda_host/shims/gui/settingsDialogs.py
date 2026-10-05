# -*- coding: utf-8 -*-
"""NVDA's `gui.settingsDialogs`: an add-on's settings panel is a real wx
panel; the classes add-ons register are kept so Titan Access can offer
them (`nvda_host.settings_panels`)."""

import wx


class SettingsPanel(wx.Panel):
    title = ''
    helpId = ''

    def __init__(self, parent):
        super().__init__(parent)
        self.settingsSizer = wx.BoxSizer(wx.VERTICAL)
        self.makeSettings(self.settingsSizer)
        self.SetSizer(self.settingsSizer)

    def makeSettings(self, sizer):
        pass

    def onSave(self):
        pass

    def onDiscard(self):
        pass

    def onPanelActivated(self):
        self.Show()

    def onPanelDeactivated(self):
        self.Hide()

    def isValid(self):
        return True


class AutoSettingsMixin(object):
    pass


class _CategoryList(list):
    pass


class NVDASettingsDialog(object):
    categoryClasses = _CategoryList()


class SettingsDialog(wx.Dialog):
    title = ''

    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, title=self.title)
        self.settingsSizer = wx.BoxSizer(wx.VERTICAL)
        self.makeSettings(self.settingsSizer)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        self.settingsSizer.Add(buttons, 0, wx.ALL, 6)
        self.SetSizerAndFit(self.settingsSizer)
        self.Bind(wx.EVT_BUTTON, self._ok, id=wx.ID_OK)

    def makeSettings(self, sizer):
        pass

    def postInit(self):
        pass

    def onOk(self, evt):
        pass

    def _ok(self, evt):
        self.onOk(evt)
        self.Destroy()


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
