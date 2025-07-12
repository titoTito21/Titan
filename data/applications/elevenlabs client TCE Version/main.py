import wx
from translation import _
from elevenlabs import voices, set_api_key
import os
import configparser
import key_dialog
from menu_bar import MenuBar
from database import VoiceDatabaseDialog
from generator import Generator
from support_dialog import SupportDialog
from clonegen import VoiceCloningDialog, clone_and_notify
from settings import SettingsDialog
from tplayer import TPlayer  # Upewniamy się, że importujemy poprawną klasę

class ElevenLabsClient(wx.Frame):
    def __init__(self, parent, title):
        super(ElevenLabsClient, self).__init__(parent, title=title, size=(500, 400))

        self.generator = Generator(self)
        self.InitUI()
        self.Centre()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        vbox.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        voices_label = wx.StaticText(panel, label="Głosy:")
        vbox.Add(voices_label, 0, wx.LEFT | wx.TOP, 10)
        self.voices = [voice.name for voice in voices()]
        self.voice_choice = wx.Choice(panel, choices=self.voices)
        vbox.Add(self.voice_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        self.generate_button = wx.Button(panel, label="Generuj")
        self.generate_button.Bind(wx.EVT_BUTTON, self.generator.OnGenerate)
        vbox.Add(self.generate_button, 0, wx.EXPAND | wx.ALL, 10)

        self.play_button = wx.Button(panel, label="&Odtwórz")
        self.play_button.Bind(wx.EVT_BUTTON, self.generator.OnPlay)
        self.play_button.Disable()  # Domyślnie wyłączony
        vbox.Add(self.play_button, 0, wx.EXPAND | wx.ALL, 10)

        self.save_button = wx.Button(panel, label="&Zapisz na dysku")
        self.save_button.Bind(wx.EVT_BUTTON, self.generator.OnSave)
        vbox.Add(self.save_button, 0, wx.EXPAND | wx.ALL, 10)

        self.progress_bar = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        vbox.Add(self.progress_bar, 0, wx.EXPAND | wx.ALL, 10)

        # Dodanie paska menu
        menu_bar = MenuBar(self)
        self.SetMenuBar(menu_bar)
        panel.SetSizer(vbox)

    def OnVoiceCloning(self, event):
        dialog = VoiceCloningDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            voice_name = dialog.name_text_ctrl.GetValue()
            voice_description = dialog.description_text_ctrl.GetValue()
            path = dialog.path
            clone_and_notify(self, voice_name, voice_description, path)

    def OnSetApiKey(self, event):
        dialog = key_dialog.ApiKeyDialog(self)
        if dialog.ShowModal() == wx.ID_OK:
            with open('API_key.tkf', 'w') as file:
                file.write(f'API_key="{dialog.api_key_value}"')
                
            wx.MessageBox(
                "Aby użyć klucza API, program musi zostać zrestartowany, aby odświeżyć listę głosów i odblokować funkcje premium elevenlabs.io",
                "Klient Eleven Labs",
                wx.OK | wx.ICON_INFORMATION
            )

    def OnVoiceDatabase(self, event):
        support_dlg = SupportDialog(self)
        support_dlg.ShowModal()
        support_dlg.Destroy()
        db_dlg = VoiceDatabaseDialog(self)
        db_dlg.ShowModal()
        db_dlg.Destroy()

    def OnClientSettings(self, event):
        settings_dlg = SettingsDialog(self)
        if settings_dlg.ShowModal() == wx.ID_OK:
            settings_dlg.SaveSettings()
            wx.MessageBox("Ustawienia zostały zapisane.", "Ustawienia klienta", wx.OK | wx.ICON_INFORMATION)
        settings_dlg.Destroy()

    def OnPlayTPlayer(self, event):
        tplayer_dlg = TPlayerDialog(self)
        tplayer_dlg.ShowModal()
        tplayer_dlg.Destroy()

if __name__ == '__main__':
    settings_path = r'%appdata%\Titosoft\Titan\Additional apps\elevenlabsclient.ini'
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    if os.path.exists(settings_path):
        config = configparser.ConfigParser()
        config.read(settings_path)
        api_key = config.get('Settings', 'api_key', fallback=None)
        if api_key:
            set_api_key(api_key)
    
    app = wx.App()
    frame = ElevenLabsClient(None, title='Klient ElevenLabs')
    frame.Show()
    app.MainLoop()
