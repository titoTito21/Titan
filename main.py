import wx
import threading
import time
import os
import sys
import accessible_output3.outputs.auto
from gui import TitanApp
from sound import play_startup_sound, initialize_sound, set_theme, play_sound
from settings import get_setting, set_setting, load_settings, save_settings, SETTINGS_FILE_PATH
from translation import set_language
from notificationcenter import create_notifications_file, NOTIFICATIONS_FILE_PATH, start_monitoring
from shutdown_question import show_shutdown_dialog
from app_manager import find_application_by_shortname, open_application
from game_manager import *
from component_manager import ComponentManager
from menu import MenuBar

# Initialize translation system
_ = set_language(get_setting('language', 'pl'))

VERSION = "0.1.7.5"
speaker = accessible_output3.outputs.auto.Auto()

def main():
    settings = load_settings()
    # Set the LANG environment variable for the entire application and subprocesses
    lang = get_setting('language', 'pl')
    os.environ['LANG'] = lang
    os.environ['LANGUAGE'] = lang
    # Initialize translation system with the correct language
    global _
    _ = set_language(lang)

    initialize_sound()

    theme = settings.get('sound', {}).get('theme', 'default')  # Pobierz temat dźwiękowy z ustawień
    set_theme(theme)
    
    if not settings.get('general', {}).get('quick_start', 'False').lower() in ['true', '1']:
        # Odtwarzanie dźwięku w osobnym wątku
        threading.Thread(target=play_startup_sound).start()
        time.sleep(1)  # Poczekaj 1 sekundę
        
        # Mówienie tekstu w osobnym wątku
        threading.Thread(target=speaker.speak, args=(_("Welcome to Titan: Version {}").format(VERSION),)).start()
    
    # Dodajemy główny katalog do sys.path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))

    # Sprawdzenie argumentów wiersza poleceń
    if len(sys.argv) > 1:
        shortname = sys.argv[1]
        app_info = find_application_by_shortname(shortname)
        if app_info:
            file_path = sys.argv[2] if len(sys.argv) > 2 else None
            open_application(app_info, file_path)
            return True # Zwróć informację, że aplikacja została uruchomiona w trybie specjalnym
            
    return False

if __name__ == "__main__":
    # Set default settings if the file doesn't exist
    if not os.path.exists(SETTINGS_FILE_PATH):
        set_setting('language', 'pl')
        set_setting('theme', 'default', section='sound')

    if not os.path.exists(NOTIFICATIONS_FILE_PATH):
        create_notifications_file()
    
    # Uruchom logikę przed-GUI. Jeśli zwróci True, zakończ program.
    if main():
        sys.exit()

    # Inicjalizacja aplikacji wxPython w gł  wnym zakresie
    app = wx.App(False)
    settings = load_settings()
    
    # Show language warning if not Polish
    if get_setting('language', 'pl') != 'pl':
        play_sound('dialog.ogg')
        wx.MessageBox(
            _("Currently, translation system and international support is limited. To fully enjoy Titan, please use translation addon for your screen reader, or switch to Polish Language"),
            _("Titan"),
            wx.OK | wx.ICON_INFORMATION
        )
        play_sound('dialogclose.ogg')

    from settingsgui import SettingsFrame
    settings_frame = SettingsFrame(None, title=_("Settings"))

    component_manager = ComponentManager(settings_frame)
    component_manager.initialize_components(app)

    frame = TitanApp(None, title=_("Titan App Suite"), version=VERSION, settings=settings, component_manager=component_manager)
    
    # Bind the close event to the appropriate handler
    if settings.get('general', {}).get('confirm_exit', 'False').lower() in ['true', '1']:
        frame.Bind(wx.EVT_CLOSE, frame.on_close)
    else:
        frame.Bind(wx.EVT_CLOSE, frame.on_close_unconfirmed)
    
    frame.component_manager = component_manager
    menubar = MenuBar(frame)
    frame.SetMenuBar(menubar)

    
    
    frame.Show()
    app.MainLoop()
