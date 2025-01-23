import wx
import os
import configparser
import threading
import subprocess
from pygame import mixer
from MediaCatalog import MediaCatalog  # Importowanie MediaCatalog z oddzielnego pliku
from Settings import SettingsWindow
from player import Player  # Import wbudowanego odtwarzacza
from YoutubeSearch import YoutubeSearchApp  # Importowanie modułu YoutubeSearch

class TTSThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.message = None
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            if self.message:
                self.speak(self.message)
                self.message = None

    def speak(self, message):
        if os.name == 'nt':  # Windows
            import win32com.client as wincl
            speaker = wincl.Dispatch("SAPI.SpVoice")
            speaker.Speak(message)
        elif 'darwin' in os.sys.platform:  # macOS
            subprocess.run(['say', message])
        elif os.name == 'posix':  # Linux
            subprocess.run(['espeak', message])

    def interrupt(self):
        self._stop_event.set()

    def set_message(self, message):
        self.message = message

class TMediaApp(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(TMediaApp, self).__init__(*args, **kwargs)

        self.SetTitle("TMedia")
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        self.config = self.load_settings()

        self.init_sounds()
        self.tts_thread = TTSThread()
        self.tts_thread.start()

        menubar = wx.MenuBar()
        fileMenu = wx.Menu()
        settings_item = fileMenu.Append(wx.ID_ANY, 'Ustawienia...')
        menubar.Append(fileMenu, '&Aplikacja')
        self.SetMenuBar(menubar)
        
        self.Bind(wx.EVT_MENU, self.open_settings, settings_item)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.function_list = wx.ListBox(panel, choices=["Katalog Mediów", "Wyszukiwarka YouTube"])
        vbox.Add(self.function_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        self.function_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_function_select)
        self.function_list.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        panel.SetSizer(vbox)

    def load_settings(self):
        config = configparser.ConfigParser()
        config_path = self.get_config_path()
        if not os.path.exists(os.path.dirname(config_path)):
            os.makedirs(os.path.dirname(config_path))
        if os.path.exists(config_path):
            config.read(config_path)
        else:
            config['DEFAULT'] = {
                'sound_effects': 'True',
                'tts_enabled': 'False',
                'player': 'tplayer'
            }
            with open(config_path, 'w') as configfile:
                config.write(configfile)
        return config

    def get_config_path(self):
        if os.name == 'nt':  # Windows
            return os.path.join(os.getenv('APPDATA'), 'Titosoft', 'Titan', 'appsettings', 'media.ini')
        elif os.name == 'posix':  # Linux, macOS
            if 'darwin' in os.sys.platform:  # macOS
                return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings', 'media.ini')
            else:  # Linux
                return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan', 'appsettings', 'media.ini')

    def init_sounds(self):
        mixer.init()
        self.sounds = {
            'ding': mixer.Sound('sfx/ding.ogg'),
            'done': mixer.Sound('sfx/done.ogg'),
            'enter': mixer.Sound('sfx/enter.ogg'),
            'enteringtplayer': mixer.Sound('sfx/enteringtplayer.ogg'),
            'sound_on': mixer.Sound('sfx/sound_on.ogg'),
            'loading': mixer.Sound('sfx/loading.ogg'),
            'click': mixer.Sound('sfx/click.ogg')
        }

    def play_sound(self, sound_name):
        if self.config.getboolean('DEFAULT', 'sound_effects', fallback=True):
            sound = self.sounds.get(sound_name)
            if sound:
                sound.play()

    def stop_sound(self, sound_name):
        if self.config.getboolean('DEFAULT', 'sound_effects', fallback=True):
            sound = self.sounds.get(sound_name)
            if sound:
                sound.stop()

    def speak_message(self, message):
        if self.config.getboolean('DEFAULT', 'tts_enabled', fallback=False):
            self.tts_thread.set_message(message)

    def on_function_select(self, event):
        selection = self.function_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.play_sound('enter')
            if selection == 0:
                self.speak_message("Ładowanie katalogu mediów")
                self.load_media_catalog()
            elif selection == 1:
                self.open_youtube_search()

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self.on_function_select(None)
        else:
            event.Skip()

    def load_media_catalog(self):
        print("Ładowanie katalogu mediów...")  # Debugging
        self.play_sound('loading')
        media_catalog = MediaCatalog(self)
        media_catalog.Show()
        print("MediaCatalog pokazany...")  # Debugging
        self.stop_sound('loading')
        self.play_sound('ding')

    def open_youtube_search(self):
        youtube_search = YoutubeSearchApp(self)
        youtube_search.Show()

    def open_settings(self, event):
        settings_window = SettingsWindow(self, self.config)
        settings_window.Show()

if __name__ == '__main__':
    app = wx.App()
    frame = TMediaApp(None)
    frame.Show()
    app.MainLoop()
