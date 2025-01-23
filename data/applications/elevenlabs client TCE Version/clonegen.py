import wx
import gettext
_ = gettext.gettext

class VoiceCloningDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Voice Cloning"), size=(400, 300))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.name_label = wx.StaticText(panel, label=_("Voice Name:"))
        self.name_text_ctrl = wx.TextCtrl(panel)
        self.description_label = wx.StaticText(panel, label=_("Voice Description:"))
        self.description_text_ctrl = wx.TextCtrl(panel)
        self.path_label = wx.StaticText(panel, label=_("Path to Voice:"))
        self.path_text_ctrl = wx.TextCtrl(panel)
        self.path_button = wx.Button(panel, label=_("Browse..."))

        sizer.Add(self.name_label, 0, wx.ALL, 5)
        sizer.Add(self.name_text_ctrl, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.description_label, 0, wx.ALL, 5)
        sizer.Add(self.description_text_ctrl, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.path_label, 0, wx.ALL, 5)
        sizer.Add(self.path_text_ctrl, 0, wx.ALL | wx.EXPAND, 5)
        sizer.Add(self.path_button, 0, wx.ALL, 5)

        ok_button = wx.Button(panel, wx.ID_OK, _("OK"))
        cancel_button = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        sizer.Add(ok_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)
        sizer.Add(cancel_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)

        panel.SetSizer(sizer)

        self.Bind(wx.EVT_BUTTON, self.on_browse, self.path_button)

    def on_browse(self, event):
        with wx.FileDialog(self, _("Choose a file"), wildcard="All files (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            self.path_text_ctrl.SetValue(fileDialog.GetPath())

def clone_and_notify(parent, voice_name, voice_description, path):
    # Implementacja klonowania głosu
    pass
