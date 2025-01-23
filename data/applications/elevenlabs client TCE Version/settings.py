import wx
import configparser
import os

class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Ustawienia klienta", size=(400, 300))

        self.panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        api_key_label = wx.StaticText(self.panel, label="Klucz API:")
        vbox.Add(api_key_label, 0, wx.ALL, 5)
        self.api_key_text = wx.TextCtrl(self.panel)
        vbox.Add(self.api_key_text, 0, wx.EXPAND | wx.ALL, 5)

        playback_mode_label = wx.StaticText(self.panel, label="Tryb odtwarzania:")
        vbox.Add(playback_mode_label, 0, wx.ALL, 5)

        self.playback_mode_choice = wx.Choice(self.panel, choices=["mpv (domyślny)", "t player (nowy, lecz mniej stabilny)"])
        vbox.Add(self.playback_mode_choice, 0, wx.EXPAND | wx.ALL, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(self.panel, label="OK")
        close_button = wx.Button(self.panel, label="Anuluj")
        hbox.Add(ok_button, 1, wx.EXPAND | wx.ALL, 5)
        hbox.Add(close_button, 1, wx.EXPAND | wx.ALL, 5)

        vbox.Add(hbox, 0, wx.ALIGN_CENTER)

        self.panel.SetSizer(vbox)

        self.Bind(wx.EVT_BUTTON, self.OnOk, ok_button)
        self.Bind(wx.EVT_BUTTON, self.OnClose, close_button)

        self.load_settings()

    def load_settings(self):
        config = configparser.ConfigParser()
        config.read(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini')

        api_key = config.get('Settings', 'api_key', fallback="")
        playback_mode = config.get('Settings', 'playback_mode', fallback='mpv')

        self.api_key_text.SetValue(api_key)
        if playback_mode == 'mpv':
            self.playback_mode_choice.SetSelection(0)
        else:
            self.playback_mode_choice.SetSelection(1)

    def OnOk(self, event):
        config = configparser.ConfigParser()
        config['Settings'] = {
            'api_key': self.api_key_text.GetValue(),
            'playback_mode': 'mpv' if self.playback_mode_choice.GetSelection() == 0 else 'tplayer'
        }

        os.makedirs(r'%appdata%\Titosoft\Titan\Additional apps', exist_ok=True)
        with open(r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini', 'w') as configfile:
            config.write(configfile)

        self.Close()

    def OnClose(self, event):
        self.Close()
