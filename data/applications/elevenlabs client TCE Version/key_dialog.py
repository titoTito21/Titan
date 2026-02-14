import wx
from translation import _

class ApiKeyDialog(wx.Dialog):
    def __init__(self, parent):
        super(ApiKeyDialog, self).__init__(parent, title=_("Set API Key"), size=(300, 150))

        vbox = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(self, label=_("Your elevenlabs.io API key:"))
        vbox.Add(label, 0, wx.EXPAND | wx.ALL, 10)

        self.api_key_ctrl = wx.TextCtrl(self)
        vbox.Add(self.api_key_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        hbox = wx.BoxSizer(wx.HORIZONTAL)

        ok_button = wx.Button(self, wx.ID_OK, label=_("OK"))
        cancel_button = wx.Button(self, wx.ID_CANCEL, label=_("Cancel"))

        hbox.Add(ok_button, 1, wx.EXPAND | wx.ALL, 5)
        hbox.Add(cancel_button, 1, wx.EXPAND | wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.SetSizer(vbox)

    @property
    def api_key_value(self):
        return self.api_key_ctrl.GetValue()
