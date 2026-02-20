import wx
from translation import _
import os
import configparser
import threading
import subprocess
from pygame import mixer
from MediaCatalog import MediaCatalog  # Importowanie MediaCatalog z oddzielnego pliku
from Settings import SettingsWindow
from player import Player  # Import wbudowanego odtwarzacza
from YoutubeSearch import YoutubeSearchApp  # Importowanie modułu YoutubeSearch

# Screen reader / VoiceOver output via accessible_output3
try:
    import accessible_output3.outputs.auto as _ao3
    _ao3_speaker = _ao3.Auto()
except Exception:
    _ao3_speaker = None


class TTSThread(threading.Thread):
    """Lightweight TTS thread backed by accessible_output3.

    Falls back to `say` (macOS) / `espeak` (Linux) / SAPI (Windows)
    only when accessible_output3 is not available.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.message = None
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            if self.message:
                self._do_speak(self.message)
                self.message = None
            self._stop_event.wait(timeout=0.05)

    def _do_speak(self, message):
        try:
            if _ao3_speaker:
                _ao3_speaker.speak(message, interrupt=True)
                return
        except Exception:
            pass
        # Fallback when accessible_output3 unavailable
        try:
            if os.name == 'nt':
                import win32com.client as wincl
                wincl.Dispatch("SAPI.SpVoice").Speak(message)
            elif 'darwin' in os.sys.platform:
                subprocess.run(['say', message], check=False)
            else:
                subprocess.run(['spd-say', message], check=False)
        except Exception:
            pass

    def speak(self, message):
        self._do_speak(message)

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

        self.function_list = wx.ListBox(panel, choices=[_("Media Catalog"), _("YouTube Search")])
        self.function_list.SetName(_("TMedia functions"))
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

    def play_sound(self, sound_name, loop=False):
        if self.config.getboolean('DEFAULT', 'sound_effects', fallback=True):
            sound = self.sounds.get(sound_name)
            if sound:
                if loop:
                    return sound.play(-1) # -1 oznacza odtwarzanie w pętli
                else:
                    return sound.play() # Zwraca obiekt Channel
        return None # Zwraca None, jeśli efekty dźwiękowe są wyłączone lub dźwięk nie został znaleziony

    def stop_sound(self, sound_name=None, channel=None):
        if self.config.getboolean('DEFAULT', 'sound_effects', fallback=True):
            if channel:
                channel.stop()
            elif sound_name:
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
        media_catalog = MediaCatalog(self)
        media_catalog.Show()
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
