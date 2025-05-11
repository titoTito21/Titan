# Filename: settingsgui.py
import wx
import os
import sys
import subprocess
import traceback

# Importowanie modułu do kontroli głośności systemu (wymaga instalacji: pip install pycaw comtypes)
volume = None # Zmienna globalna do przechowywania obiektu kontroli głośności

if sys.platform == 'win32':
    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        print("INFO: Moduły pycaw i comtypes zaimportowane pomyślnie.")

        # Spróbuj zainicjalizować kontrolę głośności domyślnego urządzenia odtwarzającego
        try:
            devices = AudioUtilities.GetSpeakers() # Pobiera domyślne urządzenie odtwarzające
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            print("INFO: Kontrola głośności systemu zainicjalizowana dla domyślnego urządzenia.")
        except Exception as e:
            print(f"WARNING: Błąd inicjalizacji kontroli głośności systemu (domyślne urządzenie). Funkcja zmiany głośności będzie niedostępna: {e}")
            # traceback.print_exc() # Opcjonalnie: pokaż pełny traceback błędu inicjalizacji
            volume = None # Ustaw na None jeśli inicjalizacja nie powiedzie się

    except ImportError:
        print("WARNING: Biblioteka pycaw lub comtypes nie jest zainstalowana. Kontrola głośności systemu będzie niedostępna.")
        print("Aby zainstalować: pip install pycaw comtypes")
        comtypes = None
        AudioUtilities = None
        IAudioEndpointVolume = None
        cast = None
        POINTER = None
        CLSCTX_ALL = None
    except Exception as e:
        print(f"WARNING: Nieoczekiwany błąd podczas importu pycaw/comtypes: {e}")
        comtypes = None
        AudioUtilities = None
        IAudioEndpointVolume = None
        cast = None
        POINTER = None
        CLSCTX_ALL = None
else:
    print("INFO: Nie działa na Windows, pomijam import i inicjalizację pycaw.")
    comtypes = None
    AudioUtilities = None
    IAudioEndpointVolume = None
    cast = None
    POINTER = None
    CLSCTX_ALL = None


from settings import load_settings, save_settings
from sound import set_theme, initialize_sound, play_sound, resource_path
from tts import speak

SFX_DIR = resource_path('sfx')
SKINS_DIR = resource_path('skins')


class SettingsFrame(wx.Frame):
    def __init__(self, *args, **kw):
        super(SettingsFrame, self).__init__(*args, **kw)

        self.settings = load_settings()

        self.InitUI()
        play_sound('sectionchange.ogg')

        self.load_settings_to_ui()


    def InitUI(self):
        panel = wx.Panel(self)
        self.notebook = wx.Notebook(panel)

        self.sound_panel = wx.Panel(self.notebook)
        self.general_panel = wx.Panel(self.notebook)
        self.interface_panel = wx.Panel(self.notebook)

        self.notebook.AddPage(self.sound_panel, "Dźwięk")
        self.notebook.AddPage(self.general_panel, "Ogólne")
        self.notebook.AddPage(self.interface_panel, "Interfejs")

        self.InitSoundPanel()
        self.InitGeneralPanel()
        self.InitInterfacePanel()

        if sys.platform == 'win32':
            self.windows_panel = wx.Panel(self.notebook)
            self.notebook.AddPage(self.windows_panel, "Windows")
            self.InitWindowsPanel()


        hbox = wx.BoxSizer(wx.HORIZONTAL)
        save_button = wx.Button(panel, label="Zapisz")
        save_button.Bind(wx.EVT_BUTTON, self.OnSave)
        save_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        cancel_button = wx.Button(panel, label="Anuluj")
        cancel_button.Bind(wx.EVT_BUTTON, self.OnCancel)
        cancel_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button, flag=wx.RIGHT, border=10)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 10)
        vbox.Add(hbox, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)

        self.SetSize((450, 450))
        self.SetTitle("Ustawienia")
        self.Centre()

    def InitSoundPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        theme_label = wx.StaticText(self.sound_panel, label="Wybierz temat dźwiękowy:")
        vbox.Add(theme_label, flag=wx.LEFT | wx.TOP, border=10)

        self.theme_choice = wx.Choice(self.sound_panel)
        self.theme_choice.Bind(wx.EVT_CHOICE, self.OnThemeSelected)
        self.theme_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        themes = []
        if os.path.exists(SFX_DIR):
            themes = [d for d in os.listdir(SFX_DIR) if os.path.isdir(os.path.join(SFX_DIR, d))]
        else:
            print(f"WARNING: Katalog SFX nie istnieje: {SFX_DIR}. Brak tematów dźwiękowych do wyboru.")

        if not themes:
             themes = ["Brak tematów"]
             self.theme_choice.Enable(False)

        self.theme_choice.AppendItems(themes)

        vbox.Add(self.theme_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        self.sound_panel.SetSizer(vbox)

    def InitGeneralPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.quick_start_cb = wx.CheckBox(self.general_panel, label="Szybki start")
        self.quick_start_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.quick_start_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.quick_start_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.confirm_exit_cb = wx.CheckBox(self.general_panel, label="Potwierdź wyjście z Titana")
        self.confirm_exit_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.confirm_exit_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.confirm_exit_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.general_panel.SetSizer(vbox)

    def InitInterfacePanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        skin_label = wx.StaticText(self.interface_panel, label="Wybierz skórkę interfejsu:")
        vbox.Add(skin_label, flag=wx.LEFT | wx.TOP, border=10)

        self.skin_choice = wx.Choice(self.interface_panel)
        self.skin_choice.Bind(wx.EVT_CHOICE, self.OnSkinSelected)
        self.skin_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        skins = []
        if os.path.exists(SKINS_DIR):
            skins = [d for d in os.listdir(SKINS_DIR) if os.path.isdir(os.path.join(SKINS_DIR, d))]
        else:
             print(f"WARNING: Katalog skórek nie istnieje: {SKINS_DIR}. Brak skórek do wyboru.")


        skins.insert(0, "Domyślna") # Zawsze dodaj opcję "Domyślna"

        if len(skins) == 1 and skins[0] == "Domyślna": # Jeśli tylko domyślna dostępna
             self.skin_choice.Enable(False)
        else:
             self.skin_choice.Enable(True) # Upewnij się, że jest włączony jeśli są skórki

        self.skin_choice.AppendItems(skins)

        vbox.Add(self.skin_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        self.interface_panel.SetSizer(vbox)


    def InitWindowsPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        sapi_settings_button = wx.Button(self.windows_panel, label="Zmień ustawienia SAPI")
        sapi_settings_button.Bind(wx.EVT_BUTTON, self.OnSapiSettings)
        sapi_settings_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(sapi_settings_button, flag=wx.ALL | wx.EXPAND, border=10)

        ease_of_access_button = wx.Button(self.windows_panel, label="Ułatwienia dostępu")
        ease_of_access_button.Bind(wx.EVT_BUTTON, self.OnEaseOfAccess)
        ease_of_access_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(ease_of_access_button, flag=wx.ALL | wx.EXPAND, border=10)

        volume_label = wx.StaticText(self.windows_panel, label="Głośność systemu:")
        vbox.Add(volume_label, flag=wx.LEFT | wx.TOP, border=10)

        self.volume_slider = wx.Slider(self.windows_panel, value=50, minValue=0, maxValue=100,
                                       style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.OnVolumeChange)
        self.volume_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        # Wczytaj początkową wartość głośności systemu przy użyciu pycaw (jeśli zainicjalizowano)
        global volume # Użyj globalnej zmiennej volume
        if volume: # Sprawdź czy inicjalizacja pycaw się powiodła
            try:
                 # GetMasterVolumeLevelScalar zwraca wartość od 0.0 do 1.0
                 current_volume = int(volume.GetMasterVolumeLevelScalar() * 100)
                 self.volume_slider.SetValue(current_volume)
                 print(f"INFO: Wczytano początkową głośność systemu: {current_volume}%")
            except Exception as e:
                 print(f"WARNING: Błąd odczytu początkowej głośności systemu: {e}")
                 # traceback.print_exc() # Opcjonalnie: pokaż pełny traceback
        else:
             # Jeśli pycaw niedostępny, wyłącz suwak głośności
             self.volume_slider.Enable(False)
             print("INFO: Kontrola głośności systemu niedostępna, suwak wyłączony.")


        vbox.Add(self.volume_slider, flag=wx.ALL | wx.EXPAND, border=10)

        self.mute_checkbox = wx.CheckBox(self.windows_panel, label="Wyłącz wyciszenie karty dźwiękowej, kiedy Titan jest uruchomiony")
        self.mute_checkbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.mute_checkbox.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)

        vbox.Add(self.mute_checkbox, flag=wx.ALL | wx.EXPAND, border=10)


        self.windows_panel.SetSizer(vbox)


    def load_settings_to_ui(self):
        sound_settings = self.settings.get('sound', {})
        current_theme = sound_settings.get('theme', 'default')
        if self.theme_choice.FindString(current_theme) != wx.NOT_FOUND:
             self.theme_choice.SetStringSelection(current_theme)
        elif self.theme_choice.GetCount() > 0:
             if self.theme_choice.FindString("default") != wx.NOT_FOUND:
                 self.theme_choice.SetStringSelection("default")
             else:
                 self.theme_choice.SetSelection(0)


        general_settings = self.settings.get('general', {})
        quick_start_value = general_settings.get('quick_start', 'False')
        self.quick_start_cb.SetValue(str(quick_start_value).lower() in ['true', '1'])

        confirm_exit_value = general_settings.get('confirm_exit', 'False')
        self.confirm_exit_cb.SetValue(str(confirm_exit_value).lower() in ['true', '1'])

        interface_settings = self.settings.get('interface', {})
        current_skin = interface_settings.get('skin', 'Domyślna')
        if self.skin_choice.FindString(current_skin) != wx.NOT_FOUND:
             self.skin_choice.SetStringSelection(current_skin)
        elif self.skin_choice.GetCount() > 0:
             if self.skin_choice.FindString("Domyślna") != wx.NOT_FOUND:
                  self.skin_choice.SetStringSelection("Domyślna")
             else:
                  self.skin_choice.SetSelection(0)


        if hasattr(self, 'windows_panel'):
            windows_settings = self.settings.get('windows', {})
            mute_disabled = windows_settings.get('disable_mute_on_start', 'False')
            self.mute_checkbox.SetValue(str(mute_disabled).lower() in ['true', '1'])
            # Wczytywanie głośności początkowej jest teraz w InitWindowsPanel przy użyciu pycaw


    def OnSapiSettings(self, event):
        try:
            cpl_file = "sapi.cpl"
            print(f"INFO: Próba otwarcia pliku CPL przy użyciu os.startfile: {cpl_file}")
            os.startfile(cpl_file)
            print(f"INFO: os.startfile('{cpl_file}') uruchomione pomyślnie w OnSapiSettings.")

        except FileNotFoundError:
             print(f"ERROR: Nie znaleziono pliku {cpl_file}. (Bardzo mało prawdopodobne dla sapi.cpl)")
             wx.MessageBox(f"Błąd: Nie znaleziono pliku {cpl_file}. Upewnij się, że system Windows działa poprawnie.", "Błąd", wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Nieoczekiwany błąd podczas otwierania pliku CPL w OnSapiSettings: {e}")
            wx.MessageBox(f"Nieoczekiwany błąd podczas otwierania ustawień SAPI:\n{e}\n\nSzczegóły techniczne w konsoli.", "Błąd", wx.OK | wx.ICON_ERROR)
            traceback.print_exc()
        event.Skip()


    def OnEaseOfAccess(self, event):
        try:
            command = ["control.exe", "access.cpl"]
            print(f"INFO: Próba uruchomienia komendy: {' '.join(command)}")
            result = subprocess.run(command, check=False, capture_output=True, text=True)

            if result.returncode != 0:
                error_message = f"Komenda '{' '.join(command)}' zakończyła się błędem {result.returncode}.\n"
                if result.stdout:
                    error_message += f"Stdout:\n{result.stdout}\n"
                if result.stderr:
                    error_message += f"Stderr:\n{result.stderr}"
                print(f"ERROR: Błąd subprocess w OnEaseOfAccess:\n{error_message}")
                wx.MessageBox(f"Nie można otworzyć ułatwień dostępu:\n{error_message}\n\nSzczegóły techniczne w konsoli.", "Błąd", wx.OK | wx.ICON_ERROR)
            else:
                print("INFO: Komenda uruchomiona pomyślnie w OnEaseOfAccess.")

        except FileNotFoundError:
             print("ERROR: Nie znaleziono pliku wykonywalnego control.exe.")
             wx.MessageBox("Błąd: Nie znaleziono pliku wykonywalnego control.exe. Upewnij się, że system Windows działa poprawnie.", "Błąd", wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Nieoczekiwany błąd podczas uruchamiania subprocess w OnEaseOfAccess: {e}")
            wx.MessageBox(f"Nieoczekiwany błąd podczas otwierania ułatwień dostępu:\n{e}\n\nSzczegóły techniczne w konsoli.", "Błąd", wx.OK | wx.ICON_ERROR)
            traceback.print_exc()
        event.Skip()

    def OnVolumeChange(self, event):
        # Handler dla suwaka głośności - zmienia głośność systemu przy użyciu pycaw
        volume_value = self.volume_slider.GetValue()
        print(f"Suwak głośności zmieniony na: {volume_value}")

        global volume # Użyj globalnej zmiennej volume
        if volume: # Sprawdź czy inicjalizacja pycaw się powiodła
            try:
                # SetMasterVolumeLevelScalar ustawia głośność od 0.0 do 1.0
                volume.SetMasterVolumeLevelScalar(volume_value / 100.0, None)
                print(f"INFO: Ustawiono głośność systemu na: {volume_value}%")
            except Exception as e:
                print(f"WARNING: Błąd ustawiania głośności systemu: {e}")
                # traceback.print_exc() # Opcjonalnie: pokaż pełny traceback
        else:
            print("WARNING: Kontrola głośności systemu niedostępna.")


        event.Skip()

    def OnSkinSelected(self, event):
        selected_skin = self.skin_choice.GetStringSelection()
        print(f"INFO: Wybrano skórkę: {selected_skin}")
        # TODO: Zaimplementować logikę zmiany skórki interfejsu w głównej części aplikacji
        # Ta metoda tylko zapisuje wybraną skórkę w ustawieniach.
        # Logika zastosowania skórki (np. zmiana kolorów, czcionek, układu)
        # musi być zaimplementowana w kodzie, który buduje/zarządza interfejsem GUI,
        # odczytując to ustawienie przy starcie lub po zmianie.


        event.Skip()


    def OnThemeSelected(self, event):
        theme = self.theme_choice.GetStringSelection()
        if theme != "Brak tematów":
             set_theme(theme)
             initialize_sound()
             print(f"INFO: Wybrano temat dźwiękowy: {theme}")

    def OnSave(self, event):
        self.settings['sound'] = {'theme': self.theme_choice.GetStringSelection()}
        self.settings['general'] = {
            'quick_start': str(self.quick_start_cb.GetValue()),
            'confirm_exit': str(self.confirm_exit_cb.GetValue())
        }

        self.settings['interface'] = {
            'skin': self.skin_choice.GetStringSelection()
        }

        if hasattr(self, 'windows_panel'):
            self.settings['windows'] = {
                'disable_mute_on_start': str(self.mute_checkbox.GetValue())
                # TODO: Zapisać aktualną wartość głośności suwaka jeśli jest potrzebna przy starcie
                # (zazwyczaj nie jest potrzebne, bo system pamięta głośność)
            }

        save_settings(self.settings)
        speak('Ustawienia zostały zapisane')
        print("INFO: Ustawienia zapisane.")
        self.Close()

    def OnCancel(self, event):
        print("INFO: Ustawienia anulowane.")
        self.Close()

    def OnFocus(self, event):
        play_sound('focus.ogg')
        event.Skip()

    def OnSelect(self, event):
        play_sound('select.ogg')
        event.Skip()

    def OnCheckBox(self, event):
        if event.IsChecked():
            play_sound('x.ogg')
        else:
            play_sound('focus.ogg')
        event.Skip()


# Przykład użycia (do testowania samego pliku settingsgui.py)
if __name__ == '__main__':
    # Dummy implementations for dependencies
    def load_settings():
        print("Dummy load_settings called")
        return {
            'sound': {'theme': 'default'},
            'general': {'quick_start': 'False', 'confirm_exit': 'True'},
            'interface': {'skin': 'Domyślna'},
            'windows': {'disable_mute_on_start': 'False'}
        }

    def save_settings(settings):
        print("Dummy save_settings called with:", settings)

    def set_theme(theme):
        print(f"Dummy set_theme called with: {theme}")

    def initialize_sound():
        print("Dummy initialize_sound called")

    def play_sound(sound_file):
        print(f"Dummy play_sound called with: {sound_file}")

    def resource_path(path):
         base_dir = os.path.dirname(os.path.abspath(__file__))
         dummy_dir = os.path.join(base_dir, "dummy_" + path)
         if not os.path.exists(dummy_dir):
             os.makedirs(dummy_dir)
             if path == 'sfx':
                 os.makedirs(os.path.join(dummy_dir, "default"))
                 os.makedirs(os.path.join(dummy_dir, "theme1"))
             elif path == 'skins':
                  os.makedirs(os.path.join(dummy_dir, "skin_dark"))
                  os.makedirs(os.path.join(dummy_dir, "skin_light"))
         print(f"Dummy resource_path called with: {path}, returning {dummy_dir}")
         return dummy_dir

    def speak(text):
        print(f"Dummy speak called with: {text}")


    # Dummy pycaw objects for testing on non-Windows or without pycaw installed
    if 'volume' not in globals() or volume is None:
        print("INFO: Używam dummy obiektu volume do testów.")
        class DummyAudioEndpointVolume:
             def GetMasterVolumeLevelScalar(self):
                 return 0.5 # Zwróć 50% dummy głośności
             def SetMasterVolumeLevelScalar(self, value, data):
                 print(f"Dummy SetMasterVolumeLevelScalar called with: {value}")
        volume = DummyAudioEndpointVolume()


    app = wx.App(False)
    frame = SettingsFrame(None, title="Test Ustawień GUI")
    frame.Show()
    app.MainLoop()