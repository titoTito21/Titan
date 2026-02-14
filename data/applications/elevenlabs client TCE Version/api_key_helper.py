import wx
import webbrowser
import os
import configparser
from translation import _

class ApiKeyRequiredDialog(wx.Dialog):
    """Dialog shown when API key is required but not configured"""

    def __init__(self, parent):
        super().__init__(parent, title=_("API Key Required"), size=(450, 250))

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Icon and title
        title_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Warning icon (using system icon)
        icon = wx.ArtProvider.GetBitmap(wx.ART_WARNING, wx.ART_MESSAGE_BOX, (48, 48))
        icon_bitmap = wx.StaticBitmap(panel, bitmap=icon)
        title_sizer.Add(icon_bitmap, 0, wx.ALL, 10)

        # Message
        message_box = wx.BoxSizer(wx.VERTICAL)
        title_text = wx.StaticText(panel, label=_("No API key configured"))
        font = title_text.GetFont()
        font.PointSize += 2
        font = font.Bold()
        title_text.SetFont(font)
        message_box.Add(title_text, 0, wx.ALL, 5)

        info_text = wx.StaticText(panel, label=_(
            "To use this feature, you need an ElevenLabs API key.\n\n"
            "You can get your API key for free from ElevenLabs."
        ))
        message_box.Add(info_text, 0, wx.ALL, 5)

        title_sizer.Add(message_box, 1, wx.EXPAND | wx.ALL, 5)
        vbox.Add(title_sizer, 0, wx.EXPAND)

        # Separator
        vbox.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Get API Key button
        self.get_key_button = wx.Button(panel, label=_("Get API Key (Free)"))
        self.get_key_button.Bind(wx.EVT_BUTTON, self.OnGetApiKey)
        button_sizer.Add(self.get_key_button, 0, wx.ALL, 5)

        # Settings button
        self.settings_button = wx.Button(panel, label=_("Open Settings"))
        self.settings_button.Bind(wx.EVT_BUTTON, self.OnOpenSettings)
        button_sizer.Add(self.settings_button, 0, wx.ALL, 5)

        # Cancel button
        self.cancel_button = wx.Button(panel, wx.ID_CANCEL, label=_("Cancel"))
        button_sizer.Add(self.cancel_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        # Help text
        help_text = wx.StaticText(panel, label=_(
            "After getting your API key, paste it in:\n"
            "File → Client Settings → API Key"
        ))
        help_font = help_text.GetFont()
        help_font.PointSize -= 1
        help_text.SetFont(help_font)
        help_text.SetForegroundColour(wx.Colour(100, 100, 100))
        vbox.Add(help_text, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)
        self.Centre()

    def OnGetApiKey(self, event):
        """Open ElevenLabs API key page"""
        url = "https://elevenlabs.io/app/settings/api-keys"
        webbrowser.open(url)

        wx.MessageBox(
            _("Opening ElevenLabs API settings in your browser.\n\n"
              "1. Sign up or log in to ElevenLabs\n"
              "2. Copy your API key\n"
              "3. Paste it in: File → Client Settings"),
            _("Get API Key"),
            wx.OK | wx.ICON_INFORMATION
        )

    def OnOpenSettings(self, event):
        """Open client settings"""
        from settings import SettingsDialog

        settings_dlg = SettingsDialog(self)
        if settings_dlg.ShowModal() == wx.ID_OK:
            # Check if API key was set
            settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')
            if os.path.exists(settings_path):
                config = configparser.ConfigParser()
                config.read(settings_path)
                api_key = config.get('Settings', 'api_key', fallback=None)

                if api_key and api_key.strip() != "":
                    wx.MessageBox(
                        _("API key configured successfully!\n\nPlease restart the feature to use it."),
                        _("Success"),
                        wx.OK | wx.ICON_INFORMATION
                    )
                    self.EndModal(wx.ID_OK)
                    return

        settings_dlg.Destroy()


def check_api_key(parent):
    """
    Check if API key is configured, show helpful dialog if not.
    Returns True if API key is configured, False otherwise.
    """
    settings_path = os.path.expandvars(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')

    # Check if settings file exists
    if not os.path.exists(settings_path):
        dlg = ApiKeyRequiredDialog(parent)
        dlg.ShowModal()
        dlg.Destroy()
        return False

    # Check if API key is set
    config = configparser.ConfigParser()
    config.read(settings_path)
    api_key = config.get('Settings', 'api_key', fallback=None)

    if not api_key or api_key.strip() == "":
        dlg = ApiKeyRequiredDialog(parent)
        dlg.ShowModal()
        dlg.Destroy()
        return False

    return True
