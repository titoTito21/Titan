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


import accessible_output3.outputs.auto
from settings import load_settings, save_settings, get_setting, set_setting
from sound import set_theme, initialize_sound, play_sound, resource_path, set_sound_theme_volume
from translation import get_available_languages, set_language

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

SFX_DIR = resource_path('sfx')
SKINS_DIR = resource_path('skins')
speaker = accessible_output3.outputs.auto.Auto()


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

        self.notebook.AddPage(self.sound_panel, _("Sound"))
        self.notebook.AddPage(self.general_panel, _("General"))
        self.notebook.AddPage(self.interface_panel, _("Interface"))
        self.invisible_interface_panel = wx.Panel(self.notebook)
        self.notebook.AddPage(self.invisible_interface_panel, _("Invisible Interface"))

        self.InitSoundPanel()
        self.InitGeneralPanel()
        self.InitInterfacePanel()
        self.InitInvisibleInterfacePanel()

        if sys.platform == 'win32':
            self.windows_panel = wx.Panel(self.notebook)
            self.notebook.AddPage(self.windows_panel, _("Windows"))
            self.InitWindowsPanel()


        hbox = wx.BoxSizer(wx.HORIZONTAL)
        save_button = wx.Button(panel, label=_("Save"))
        save_button.Bind(wx.EVT_BUTTON, self.OnSave)
        save_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        cancel_button = wx.Button(panel, label=_("Cancel"))
        cancel_button.Bind(wx.EVT_BUTTON, self.OnCancel)
        cancel_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button, flag=wx.RIGHT, border=10)

        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 10)
        vbox.Add(hbox, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)

        self.SetSize((450, 450))
        self.SetTitle(_("Settings"))
        self.Centre()

    def InitSoundPanel(self):
        panel = self.sound_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        theme_label = wx.StaticText(panel, label=_("Select sound theme:"))
        vbox.Add(theme_label, flag=wx.LEFT | wx.TOP, border=10)

        self.theme_choice = wx.Choice(panel)
        self.theme_choice.Bind(wx.EVT_CHOICE, self.OnThemeSelected)
        self.theme_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        themes = []
        if os.path.exists(SFX_DIR):
            themes = [d for d in os.listdir(SFX_DIR) if os.path.isdir(os.path.join(SFX_DIR, d))]
        else:
            print(f"WARNING: SFX directory does not exist: {SFX_DIR}. No sound themes to choose from.")

        if not themes:
             themes = [_("No themes")]
             self.theme_choice.Enable(False)

        self.theme_choice.AppendItems(themes)
        vbox.Add(self.theme_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        self.stereo_sound_cb = wx.CheckBox(panel, label=_("Stereo sounds"))
        self.stereo_sound_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.stereo_sound_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.stereo_sound_cb, flag=wx.LEFT | wx.TOP, border=10)

        volume_label_text = _("Sound theme volume:")
        volume_label = wx.StaticText(panel, label=volume_label_text)
        vbox.Add(volume_label, flag=wx.LEFT | wx.TOP, border=10)

        self.theme_volume_slider = wx.Slider(panel, value=100, minValue=0, maxValue=100,
                                              style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.theme_volume_slider.SetName(volume_label_text)
        self.theme_volume_slider.Bind(wx.EVT_SLIDER, self.OnThemeVolumeChange)
        self.theme_volume_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.theme_volume_slider, flag=wx.LEFT | wx.EXPAND, border=10)

        panel.SetSizer(vbox)
        panel.Layout()

    def InitGeneralPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Language selection
        lang_label = wx.StaticText(self.general_panel, label=_("Language:"))
        vbox.Add(lang_label, flag=wx.LEFT | wx.TOP, border=10)

        self.lang_choice = wx.Choice(self.general_panel)
        self.lang_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        
        available_languages = get_available_languages()
        self.lang_choice.AppendItems(available_languages)
        vbox.Add(self.lang_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # Add a small spacer
        vbox.AddSpacer(10)

        self.quick_start_cb = wx.CheckBox(self.general_panel, label=_("Quick start"))
        self.quick_start_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.quick_start_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.quick_start_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.confirm_exit_cb = wx.CheckBox(self.general_panel, label=_("Confirm exit from Titan"))
        self.confirm_exit_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.confirm_exit_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.confirm_exit_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.general_panel.SetSizer(vbox)

    def InitInterfacePanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        skin_label = wx.StaticText(self.interface_panel, label=_("Select interface skin:"))
        vbox.Add(skin_label, flag=wx.LEFT | wx.TOP, border=10)

        self.skin_choice = wx.Choice(self.interface_panel)
        self.skin_choice.Bind(wx.EVT_CHOICE, self.OnSkinSelected)
        self.skin_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        skins = []
        if os.path.exists(SKINS_DIR):
            skins = [d for d in os.listdir(SKINS_DIR) if os.path.isdir(os.path.join(SKINS_DIR, d))]
        else:
             print(f"WARNING: Skins directory does not exist: {SKINS_DIR}. No skins to choose from.")


        skins.insert(0, _("Default")) # Always add "Default" option

        if len(skins) == 1 and skins[0] == _("Default"): # If only default is available
             self.skin_choice.Enable(False)
        else:
             self.skin_choice.Enable(True) # Make sure it's enabled if there are skins

        self.skin_choice.AppendItems(skins)

        vbox.Add(self.skin_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        self.interface_panel.SetSizer(vbox)


    def InitInvisibleInterfacePanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.announce_index_cb = wx.CheckBox(self.invisible_interface_panel, label=_("Announce item index"))
        self.announce_index_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.announce_index_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.announce_index_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.announce_widget_type_cb = wx.CheckBox(self.invisible_interface_panel, label=_("Announce widget type"))
        self.announce_widget_type_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.announce_widget_type_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.announce_widget_type_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.enable_titan_ui_cb = wx.CheckBox(self.invisible_interface_panel, label=_("Enable TitanUI support"))
        self.enable_titan_ui_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.enable_titan_ui_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.enable_titan_ui_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.announce_first_item_cb = wx.CheckBox(self.invisible_interface_panel, label=_("Announce first item in category"))
        self.announce_first_item_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.announce_first_item_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.announce_first_item_cb, flag=wx.LEFT | wx.TOP, border=10)

        titan_hotkey_label = wx.StaticText(self.invisible_interface_panel, label=_("Titan key:"))
        vbox.Add(titan_hotkey_label, flag=wx.LEFT | wx.TOP, border=10)

        self.titan_hotkey_ctrl = wx.TextCtrl(self.invisible_interface_panel)
        self.titan_hotkey_ctrl.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.titan_hotkey_ctrl, flag=wx.LEFT | wx.EXPAND, border=10)

        self.invisible_interface_panel.SetSizer(vbox)

    def InitWindowsPanel(self):
        panel = self.windows_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        sapi_settings_button = wx.Button(panel, label=_("Change SAPI settings"))
        sapi_settings_button.Bind(wx.EVT_BUTTON, self.OnSapiSettings)
        sapi_settings_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(sapi_settings_button, flag=wx.ALL | wx.EXPAND, border=10)

        ease_of_access_button = wx.Button(panel, label=_("Ease of Access"))
        ease_of_access_button.Bind(wx.EVT_BUTTON, self.OnEaseOfAccess)
        ease_of_access_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(ease_of_access_button, flag=wx.ALL | wx.EXPAND, border=10)

        volume_label_text = _("System volume:")
        volume_label = wx.StaticText(panel, label=volume_label_text)
        vbox.Add(volume_label, flag=wx.LEFT | wx.TOP, border=10)

        self.volume_slider = wx.Slider(panel, value=50, minValue=0, maxValue=100,
                                       style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.volume_slider.SetName(volume_label_text)
        self.volume_slider.Bind(wx.EVT_SLIDER, self.OnVolumeChange)
        self.volume_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        # Load initial system volume using pycaw (if initialized)
        global volume # Use the global volume variable
        if volume: # Check if pycaw initialization was successful
            try:
                 # GetMasterVolumeLevelScalar returns a value from 0.0 to 1.0
                 current_volume = int(volume.GetMasterVolumeLevelScalar() * 100)
                 self.volume_slider.SetValue(current_volume)
                 print(f"INFO: Initial system volume loaded: {current_volume}%")
            except Exception as e:
                 print(f"WARNING: Error reading initial system volume: {e}")
                 # traceback.print_exc() # Optionally: show full traceback
        else:
             # If pycaw is not available, disable the volume slider
             self.volume_slider.Enable(False)
             print("INFO: System volume control not available, slider disabled.")


        vbox.Add(self.volume_slider, flag=wx.ALL | wx.EXPAND, border=10)

        self.mute_checkbox = wx.CheckBox(panel, label=_("Disable sound card mute when Titan is running"))
        self.mute_checkbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.mute_checkbox.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)

        vbox.Add(self.mute_checkbox, flag=wx.ALL | wx.EXPAND, border=10)

        panel.SetSizer(vbox)
        panel.Layout()


    def load_settings_to_ui(self):
        # Language
        current_lang = get_setting('language', 'pl')
        if self.lang_choice.FindString(current_lang) != wx.NOT_FOUND:
            self.lang_choice.SetStringSelection(current_lang)
        else:
            self.lang_choice.SetStringSelection('pl')

        sound_settings = self.settings.get('sound', {})
        current_theme = sound_settings.get('theme', 'default')
        if self.theme_choice.FindString(current_theme) != wx.NOT_FOUND:
             self.theme_choice.SetStringSelection(current_theme)
        elif self.theme_choice.GetCount() > 0:
             if self.theme_choice.FindString("default") != wx.NOT_FOUND:
                 self.theme_choice.SetStringSelection("default")
             else:
                 self.theme_choice.SetSelection(0)

        stereo_sound_value = sound_settings.get('stereo_sound', 'False')
        self.stereo_sound_cb.SetValue(str(stereo_sound_value).lower() in ['true', '1'])

        theme_volume_value = sound_settings.get('theme_volume', '100')
        self.theme_volume_slider.SetValue(int(theme_volume_value))
        set_sound_theme_volume(int(theme_volume_value))


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
             if self.skin_choice.FindString(_("Default")) != wx.NOT_FOUND:
                  self.skin_choice.SetStringSelection(_("Default"))
             else:
                  self.skin_choice.SetSelection(0)

        invisible_interface_settings = self.settings.get('invisible_interface', {})
        self.announce_index_cb.SetValue(str(invisible_interface_settings.get('announce_index', 'False')).lower() in ['true', '1'])
        self.announce_widget_type_cb.SetValue(str(invisible_interface_settings.get('announce_widget_type', 'False')).lower() in ['true', '1'])
        self.enable_titan_ui_cb.SetValue(str(invisible_interface_settings.get('enable_titan_ui', 'False')).lower() in ['true', '1'])
        self.announce_first_item_cb.SetValue(str(invisible_interface_settings.get('announce_first_item', 'False')).lower() in ['true', '1'])
        self.titan_hotkey_ctrl.SetValue(invisible_interface_settings.get('titan_hotkey', ''))


        if hasattr(self, 'windows_panel'):
            windows_settings = self.settings.get('windows', {})
            mute_disabled = windows_settings.get('disable_mute_on_start', 'False')
            self.mute_checkbox.SetValue(str(mute_disabled).lower() in ['true', '1'])
            # Loading initial volume is now in InitWindowsPanel using pycaw


    def OnSapiSettings(self, event):
        try:
            cpl_file = "sapi.cpl"
            print(f"INFO: Attempting to open CPL file using os.startfile: {cpl_file}")
            os.startfile(cpl_file)
            print(f"INFO: os.startfile('{cpl_file}') executed successfully in OnSapiSettings.")

        except FileNotFoundError:
             print(f"ERROR: File {cpl_file} not found. (Very unlikely for sapi.cpl)")
             wx.MessageBox(_("Error: File {} not found. Make sure Windows is working correctly.").format(cpl_file), _("Error"), wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Unexpected error while opening CPL file in OnSapiSettings: {e}")
            wx.MessageBox(_("Unexpected error while opening SAPI settings:\n{}\n\nTechnical details in the console.").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
            traceback.print_exc()
        event.Skip()


    def OnEaseOfAccess(self, event):
        try:
            command = ["control.exe", "access.cpl"]
            print(f"INFO: Attempting to run command: {' '.join(command)}")
            result = subprocess.run(command, check=False, capture_output=True, text=True)

            if result.returncode != 0:
                error_message = _("Command '{}' finished with error code {}.\n").format(' '.join(command), result.returncode)
                if result.stdout:
                    error_message += f"Stdout:\n{result.stdout}\n"
                if result.stderr:
                    error_message += f"Stderr:\n{result.stderr}"
                print(f"ERROR: Subprocess error in OnEaseOfAccess:\n{error_message}")
                wx.MessageBox(_("Cannot open Ease of Access:\n{}\n\nTechnical details in the console.").format(error_message), _("Error"), wx.OK | wx.ICON_ERROR)
            else:
                print("INFO: Command executed successfully in OnEaseOfAccess.")

        except FileNotFoundError:
             print("ERROR: Executable control.exe not found.")
             wx.MessageBox(_("Error: Executable control.exe not found. Make sure Windows is working correctly."), _("Error"), wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Unexpected error while running subprocess in OnEaseOfAccess: {e}")
            wx.MessageBox(_("Unexpected error while opening Ease of Access:\n{}\n\nTechnical details in the console.").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
            traceback.print_exc()
        event.Skip()

    def OnVolumeChange(self, event):
        # Handler for the volume slider - changes system volume using pycaw
        volume_value = self.volume_slider.GetValue()
        print(f"Volume slider changed to: {volume_value}")

        global volume # Use the global volume variable
        if volume: # Check if pycaw initialization was successful
            try:
                # SetMasterVolumeLevelScalar sets the volume from 0.0 to 1.0
                volume.SetMasterVolumeLevelScalar(volume_value / 100.0, None)
                print(f"INFO: System volume set to: {volume_value}%")
            except Exception as e:
                print(f"WARNING: Error setting system volume: {e}")
                # traceback.print_exc() # Optionally: show full traceback
        else:
            print("WARNING: System volume control not available.")


        event.Skip()

    def OnSkinSelected(self, event):
        selected_skin = self.skin_choice.GetStringSelection()
        print(f"INFO: Skin selected: {selected_skin}")
        # TODO: Implement the logic for changing the interface skin in the main part of the application
        # This method only saves the selected skin in the settings.
        # The logic for applying the skin (e.g., changing colors, fonts, layout)
        # must be implemented in the code that builds/manages the GUI,
        # reading this setting on startup or after a change.


        event.Skip()


    def OnThemeSelected(self, event):
        theme = self.theme_choice.GetStringSelection()
        if theme != _("No themes"):
             set_theme(theme)
             initialize_sound()
             print(f"INFO: Sound theme selected: {theme}")

    def OnThemeVolumeChange(self, event):
        volume = self.theme_volume_slider.GetValue()
        set_sound_theme_volume(volume)
        play_sound('volume.ogg')
        event.Skip()

    def OnSave(self, event):
        # Save language setting
        selected_language = self.lang_choice.GetStringSelection()
        set_setting('language', selected_language)

        self.settings['sound'] = {
            'theme': self.theme_choice.GetStringSelection(),
            'stereo_sound': str(self.stereo_sound_cb.GetValue()),
            'theme_volume': str(self.theme_volume_slider.GetValue())
        }
        self.settings['general'] = {
            'quick_start': str(self.quick_start_cb.GetValue()),
            'confirm_exit': str(self.confirm_exit_cb.GetValue()),
            'language': selected_language
        }

        if 'interface' not in self.settings:
            self.settings['interface'] = {}
        self.settings['interface']['skin'] = self.skin_choice.GetStringSelection()

        self.settings['invisible_interface'] = {
            'announce_index': str(self.announce_index_cb.GetValue()),
            'announce_widget_type': str(self.announce_widget_type_cb.GetValue()),
            'enable_titan_ui': str(self.enable_titan_ui_cb.GetValue()),
            'announce_first_item': str(self.announce_first_item_cb.GetValue()),
            'titan_hotkey': self.titan_hotkey_ctrl.GetValue()
        }

        if hasattr(self, 'windows_panel'):
            self.settings['windows'] = {
                'disable_mute_on_start': str(self.mute_checkbox.GetValue())
                # TODO: Save the current slider volume value if needed on startup
                # (usually not necessary, as the system remembers the volume)
            }

        save_settings(self.settings)
        speaker.speak(_('Settings have been saved. Please restart the application for the language change to take full effect.'))
        print("INFO: Settings saved.")
        self.Close()

    def OnCancel(self, event):
        print("INFO: Settings canceled.")
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