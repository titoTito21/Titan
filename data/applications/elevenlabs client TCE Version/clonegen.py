import wx
from translation import _
from elevenlabs.client import ElevenLabs
import os
import configparser

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
    """Clone voice using ElevenLabs API"""
    try:
        # Get API key from settings
        settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
        if not os.path.exists(settings_path):
            wx.MessageBox(_("No API key found. Please configure the API key in settings."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        config = configparser.ConfigParser()
        config.read(settings_path)
        api_key = config.get('Settings', 'api_key', fallback=None)

        if not api_key:
            wx.MessageBox(_("No API key found. Please configure the API key in settings."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        client = ElevenLabs(api_key=api_key)

        # Find audio files in the path
        audio_files = []
        if os.path.isdir(path):
            for file in os.listdir(path):
                if file.lower().endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a')):
                    audio_files.append(os.path.join(path, file))
        elif os.path.isfile(path) and path.lower().endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a')):
            audio_files = [path]

        if not audio_files:
            wx.MessageBox(_("No audio files found for cloning."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        # Clone voice using add voice API
        voice = client.voices.add(
            name=voice_name,
            description=voice_description,
            files=audio_files[:25]  # Limit to 25 files as per API limits
        )

        wx.MessageBox(_(f"Voice '{voice_name}' has been successfully cloned!"), _("Success"), wx.OK | wx.ICON_INFORMATION)

    except Exception as e:
        wx.MessageBox(_(f"Error cloning voice: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)
