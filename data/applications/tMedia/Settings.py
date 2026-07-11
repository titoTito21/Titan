import wx
import os
import sys
import platform
import configparser
import subprocess
from translation import _

try:
    from src.titan_core.skin_manager import apply_skin_to_window
except ImportError:
    apply_skin_to_window = None


def _apply_skin_to_tree(window):
    if not apply_skin_to_window or not window:
        return
    try:
        apply_skin_to_window(window)
    except Exception:
        return
    for child in window.GetChildren():
        _apply_skin_to_tree(child)

def get_config_path():
    _plat = platform.system()
    if _plat == 'Windows':
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings', 'media.ini')
    elif _plat == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings', 'media.ini')
    else:
        return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan', 'appsettings', 'media.ini')

class SettingsWindow(wx.Frame):
    def __init__(self, parent, config):
        super(SettingsWindow, self).__init__(parent, title=_("Settings"), size=(400, 300))

        self.config = config
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.sound_effects_checkbox = wx.CheckBox(panel, label=_("Sound feedback"))
        self.sound_effects_checkbox.SetValue(self.config.getboolean('DEFAULT', 'sound_effects', fallback=True))
        vbox.Add(self.sound_effects_checkbox, flag=wx.ALL, border=10)
        self.sound_effects_checkbox.Bind(wx.EVT_CHECKBOX, self.on_sound_checkbox)

        self.tts_checkbox = wx.CheckBox(panel, label=_("Speech output"))
        self.tts_checkbox.SetValue(self.config.getboolean('DEFAULT', 'tts_enabled', fallback=False))
        vbox.Add(self.tts_checkbox, flag=wx.ALL, border=10)

        player_choices = [_('Built-in player'), 'VLC Media Player']
        self.player_choice = wx.Choice(panel, choices=player_choices)

        player = self.config.get('DEFAULT', 'player', fallback='vlc')
        if player == 'vlc':
            self.player_choice.SetSelection(player_choices.index('VLC Media Player'))
        else:
            self.player_choice.SetSelection(player_choices.index(_('Built-in player')))

        vbox.Add(self.player_choice, flag=wx.ALL, border=10)

        save_button = wx.Button(panel, label=_("Save"))
        vbox.Add(save_button, flag=wx.ALL, border=10)
        save_button.Bind(wx.EVT_BUTTON, self.on_save)

        cancel_button = wx.Button(panel, label=_("Cancel"))
        vbox.Add(cancel_button, flag=wx.ALL, border=10)
        cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel)

        panel.SetSizer(vbox)
        _apply_skin_to_tree(self)

    def on_sound_checkbox(self, event):
        if self.sound_effects_checkbox.IsChecked():
            self.GetParent().play_sound('sound_on')

    def on_save(self, event):
        config_path = get_config_path()
        self.config['DEFAULT']['sound_effects'] = str(self.sound_effects_checkbox.IsChecked())
        self.config['DEFAULT']['tts_enabled'] = str(self.tts_checkbox.IsChecked())

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
        _plat = platform.system()
        if _plat == 'Darwin':
            subprocess.run(["brew", "install", "vlc"])
        elif _plat == 'Linux':
            for cmd in [["apt-get", "install", "-y", "vlc"],
                        ["dnf", "install", "-y", "vlc"],
                        ["pacman", "-S", "--noconfirm", "vlc"]]:
                if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                    subprocess.run(["sudo"] + cmd)
                    break
        else:
            subprocess.run(["powershell", "-Command",
                "(New-Object System.Net.WebClient).DownloadFile("
                "'https://get.videolan.org/vlc/last/win64/vlc-3.0.11-win64.exe',"
                " 'vlc_installer.exe'); Start-Process 'vlc_installer.exe' -Wait"])
