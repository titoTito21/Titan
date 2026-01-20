import wx
import os
import configparser
import subprocess

# Funkcja określająca ścieżkę do pliku konfiguracyjnego w zależności od platformy
def get_config_path():
    if os.name == 'nt':  # Windows
        return os.path.join(os.getenv('APPDATA'), 'Titosoft', 'Titan', 'appsettings', 'media.ini')
    elif os.name == 'posix':  # Linux, macOS
        if 'darwin' in os.sys.platform:  # macOS
            return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings', 'media.ini')
        else:  # Linux
            return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan', 'appsettings', 'media.ini')

class SettingsWindow(wx.Frame):
    def __init__(self, parent, config):
        super(SettingsWindow, self).__init__(parent, title="Ustawienia", size=(400, 300))

        self.config = config
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.sound_effects_checkbox = wx.CheckBox(panel, label="Informowanie przy pomocy dźwięków")
        self.sound_effects_checkbox.SetValue(self.config.getboolean('DEFAULT', 'sound_effects', fallback=True))
        vbox.Add(self.sound_effects_checkbox, flag=wx.ALL, border=10)
        self.sound_effects_checkbox.Bind(wx.EVT_CHECKBOX, self.on_sound_checkbox)

        self.tts_checkbox = wx.CheckBox(panel, label="Oznajmianie za pomocą mowy")
        self.tts_checkbox.SetValue(self.config.getboolean('DEFAULT', 'tts_enabled', fallback=False))
        vbox.Add(self.tts_checkbox, flag=wx.ALL, border=10)

        player_choices = ['Wbudowany odtwarzacz', 'VLC Media Player']
        self.player_choice = wx.Choice(panel, choices=player_choices)
        
        # Ustawienie domyślnej wartości
        player = self.config.get('DEFAULT', 'player', fallback='vlc')
        if player == 'vlc':
            self.player_choice.SetSelection(player_choices.index('VLC Media Player'))
        else:
            self.player_choice.SetSelection(player_choices.index('Wbudowany odtwarzacz'))

        vbox.Add(self.player_choice, flag=wx.ALL, border=10)

        save_button = wx.Button(panel, label="Zapisz")
        vbox.Add(save_button, flag=wx.ALL, border=10)
        save_button.Bind(wx.EVT_BUTTON, self.on_save)

        cancel_button = wx.Button(panel, label="Anuluj")
        vbox.Add(cancel_button, flag=wx.ALL, border=10)
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)

        panel.SetSizer(vbox)

    def on_sound_checkbox(self, event):
        if self.sound_effects_checkbox.IsChecked():
            self.GetParent().play_sound('sound_on')

    def on_save(self, event):
        config_path = get_config_path()
        self.config['DEFAULT']['sound_effects'] = str(self.sound_effects_checkbox.IsChecked())
        self.config['DEFAULT']['tts_enabled'] = str(self.tts_checkbox.IsChecked())
        
        # Zapis wyboru odtwarzacza
        if self.player_choice.GetStringSelection() == 'VLC Media Player':
            self.config['DEFAULT']['player'] = 'vlc'
        else:
            self.config['DEFAULT']['player'] = 'wbudowany'

        with open(config_path, 'w') as configfile:
            self.config.write(configfile)
        self.Close()

    def on_cancel(self, event):
        self.Close()

    def install_vlc(self):
        if os.name == 'nt':  # Windows
            subprocess.run(["powershell", "-Command", "(New-Object System.Net.WebClient).DownloadFile('https://get.videolan.org/vlc/last/win64/vlc-3.0.11-win64.exe', 'vlc_installer.exe'); Start-Process 'vlc_installer.exe' -Wait"])
        elif os.name == 'posix':  # Linux
            subprocess.run(["sudo", "apt-get", "install", "-y", "vlc"])
        elif 'darwin' in os.sys.platform:  # macOS
            subprocess.run(["brew", "install", "vlc"])
