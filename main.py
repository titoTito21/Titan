import wx
import threading
import time
import os
import sys
from gui import TitanApp
from sound import play_startup_sound, initialize_sound, set_theme, play_sound
from bg5reader import speak
from settings import load_settings, save_settings, SETTINGS_FILE_PATH
from notificationcenter import create_notifications_file, NOTIFICATIONS_FILE_PATH
from shutdown_question import show_shutdown_dialog
from app_manager import find_application_by_shortname, open_application
from component_manager import ComponentManager
from menu import MenuBar  # Zakładam, że menu.py zawiera klasę MenuBar
import pywinusb
import pyaudio
import time
import speech_recognition as sr
import psutil
import keyboard


VERSION = "0.1.5"

def main():
    settings = load_settings()

    initialize_sound()

    theme = settings.get('sound', {}).get('theme', 'default')  # Pobierz temat dźwiękowy z ustawień
    set_theme(theme)
    
    # Inicjalizacja aplikacji wxPython
    app = wx.App(False)
    
    # Wyświetlenie okna dialogowego przed uruchomieniem głównego programu
    show_alpha_warning_dialog()
    
    if not settings.get('general', {}).get('quick_start', 'False').lower() in ['true', '1']:
        # Odtwarzanie dźwięku w osobnym wątku
        threading.Thread(target=play_startup_sound).start()
        time.sleep(1)  # Poczekaj 1 sekundę
        
        # Mówienie tekstu w osobnym wątku
        threading.Thread(target=speak, args=(f"Witamy w Titan: Wersja {VERSION}",)).start()
        time.sleep(3)  # Poczekaj 3 sekundy
    
    # Dodajemy główny katalog do sys.path
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))

    # Sprawdzenie argumentów wiersza poleceń
    if len(sys.argv) > 1:
        shortname = sys.argv[1]
        app_info = find_application_by_shortname(shortname)
        if app_info:
            file_path = sys.argv[2] if len(sys.argv) > 2 else None
            open_application(app_info, file_path)
            return

    # Uruchomienie GUI
    frame = TitanApp(None, title="Titan App Suite", version=VERSION)
    
    if settings.get('general', {}).get('confirm_exit', 'False').lower() in ['true', '1']:
        frame.Bind(wx.EVT_CLOSE, on_close)
    
    # Tworzenie paska menu
    menubar = MenuBar(frame)  # Tworzy pasek menu przy użyciu klasy MenuBar z menu.py
    frame.SetMenuBar(menubar)
    
    # Tworzenie okna ustawień
    from settingsgui import SettingsFrame
    settings_frame = SettingsFrame(None, title="Ustawienia")

    # Inicjalizacja ComponentManager
    component_manager = ComponentManager(menubar, settings_frame)
    component_manager.initialize_components(app)
    
    frame.Show()
    app.MainLoop()

def show_alpha_warning_dialog():
    # Odtwarzanie dźwięku dialog.ogg
    threading.Thread(target=play_sound, args=('dialog.ogg',)).start()
    
    # Treść dialogu
    dialog_content = (
        "Program Titan jest w fazie rozwoju alpha. Zaleca się nie używanie tego programu na codzienny użytek. "
        "Wersja alpha może zawierać poważne błędy, w aplikacjach Titana, jak i samym Titanie. "
        "Jeśli nie jesteś testerem lub nie jesteś gotów na test, natychmiast zamknij ten program. "
        "\u00A9 2024 TitoSoft"
    )  # \u00A9 to symbol ©
    
    # Utworzenie okna dialogowego
    dialog = wx.MessageDialog(
        None,
        dialog_content,
        "Titan Alpha",
        wx.OK | wx.CANCEL | wx.ICON_WARNING
    )
    
    # Wyświetlenie dialogu i oczekiwanie na odpowiedź użytkownika
    result = dialog.ShowModal()
    dialog.Destroy()
    
    # Odtwarzanie dźwięku dialogclose.ogg
    threading.Thread(target=play_sound, args=('dialogclose.ogg',)).start()
    
    if result == wx.ID_CANCEL:
        sys.exit()  # Zakończenie programu

def on_close(event):
    result = show_shutdown_dialog()
    if result == wx.ID_OK:
        event.Skip()  # Kontynuuj zamykanie
    else:
        event.Veto()  # Anuluj zamykanie

if __name__ == "__main__":
    # Upewnij się, że pliki ustawień i powiadomień istnieją
    if not os.path.exists(SETTINGS_FILE_PATH):
        save_settings({'sound': {'theme': 'default'}})

    if not os.path.exists(NOTIFICATIONS_FILE_PATH):
        create_notifications_file()
    
    main()
