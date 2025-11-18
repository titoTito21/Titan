# Filename: settingsgui.py
import wx
import os
import sys
import subprocess
import traceback
import configparser
import threading
import time

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
            # Use safe COM initialization from com_fix module
            from com_fix import init_com_safe
            init_com_safe()
            
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


# Import accessible_output3 with COM safety
try:
    from com_fix import suppress_com_errors
    suppress_com_errors()
except (ImportError, Exception):
    pass

import accessible_output3.outputs.auto
from settings import load_settings, save_settings, get_setting, set_setting
from sound import set_theme, initialize_sound, play_sound, resource_path, set_sound_theme_volume
from controller_vibrations import (
    vibrate_cursor_move, vibrate_menu_open, vibrate_menu_close, vibrate_selection,
    vibrate_focus_change, vibrate_error, vibrate_notification, test_vibration,
    set_vibration_enabled, set_vibration_strength, get_controller_info
)
from translation import get_available_languages, set_language
from stereo_speech import get_stereo_speech
from system_monitor import restart_system_monitor

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

SFX_DIR = resource_path('sfx')
SKINS_DIR = resource_path('skins')
speaker = accessible_output3.outputs.auto.Auto()


class SettingsFrame(wx.Frame):
    def __init__(self, *args, **kw):
        super(SettingsFrame, self).__init__(*args, **kw)

        self.settings = load_settings()
        
        # Debounce timers for sliders to prevent hangs
        self.rate_timer = None
        self.speech_volume_timer = None
        self.theme_volume_timer = None

        self.InitUI()
        play_sound('ui/sectionchange.ogg')
        vibrate_menu_open()  # Add vibration for opening settings

        self.load_settings_to_ui()
        
        # Apply skin settings after UI is loaded
        self.apply_skin_settings()


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
        self.environment_panel = wx.Panel(self.notebook)
        self.notebook.AddPage(self.environment_panel, _("Environment"))

        # Add System Monitor tab
        self.system_monitor_panel = wx.Panel(self.notebook)
        self.notebook.AddPage(self.system_monitor_panel, _("System Monitor"))

        # Dodaj zakładkę Stereo Speech Settings (będzie ukryta/pokazana dynamicznie)
        self.stereo_speech_panel = wx.Panel(self.notebook)

        self.InitSoundPanel()
        self.InitGeneralPanel()
        self.InitInterfacePanel()
        self.InitInvisibleInterfacePanel()
        self.InitEnvironmentPanel()
        self.InitSystemMonitorPanel()
        self.InitStereoSpeechPanel()

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

        # Startup mode selection
        startup_mode_label = wx.StaticText(self.general_panel, label=_("Startup mode:"))
        vbox.Add(startup_mode_label, flag=wx.LEFT | wx.TOP, border=10)

        self.startup_mode_choice = wx.Choice(self.general_panel)
        self.startup_mode_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        startup_modes = [_("Normal (Graphical interface)"), _("Minimized (Invisible interface)"), _("Classic Mode")]
        self.startup_mode_choice.AppendItems(startup_modes)
        vbox.Add(self.startup_mode_choice, flag=wx.LEFT | wx.EXPAND, border=10)

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

        self.stereo_speech_cb = wx.CheckBox(self.invisible_interface_panel, label=_("Stereo speech (Using SAPI)"))
        self.stereo_speech_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.stereo_speech_cb.Bind(wx.EVT_CHECKBOX, self.OnStereoSpeechChanged)
        vbox.Add(self.stereo_speech_cb, flag=wx.LEFT | wx.TOP, border=10)

        titan_hotkey_label = wx.StaticText(self.invisible_interface_panel, label=_("Titan key:"))
        vbox.Add(titan_hotkey_label, flag=wx.LEFT | wx.TOP, border=10)

        self.titan_hotkey_ctrl = wx.TextCtrl(self.invisible_interface_panel)
        self.titan_hotkey_ctrl.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.titan_hotkey_ctrl, flag=wx.LEFT | wx.EXPAND, border=10)

        self.invisible_interface_panel.SetSizer(vbox)

    def InitEnvironmentPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.announce_screen_lock_cb = wx.CheckBox(self.environment_panel, label=_("Announce screen locking state"))
        self.announce_screen_lock_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.announce_screen_lock_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.announce_screen_lock_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.windows_e_hook_cb = wx.CheckBox(self.environment_panel, label=_("Modify system interface"))
        self.windows_e_hook_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.windows_e_hook_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.windows_e_hook_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.enable_tce_sounds_cb = wx.CheckBox(self.environment_panel, label=_("Enable TCE sounds outside environment"))
        self.enable_tce_sounds_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.enable_tce_sounds_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.enable_tce_sounds_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.environment_panel.SetSizer(vbox)

    def InitSystemMonitorPanel(self):
        panel = self.system_monitor_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Volume Monitor section
        volume_monitor_label = wx.StaticText(panel, label=_("Volume Monitor:"))
        vbox.Add(volume_monitor_label, flag=wx.LEFT | wx.TOP, border=10)

        self.volume_monitor_choice = wx.Choice(panel)
        volume_monitor_options = [_("None"), _("Sound only"), _("Speech only"), _("Sound and speech")]
        self.volume_monitor_choice.AppendItems(volume_monitor_options)
        self.volume_monitor_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.volume_monitor_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # Battery Level Announcement section
        battery_announce_label = wx.StaticText(panel, label=_("Announce battery level every:"))
        vbox.Add(battery_announce_label, flag=wx.LEFT | wx.TOP, border=10)

        self.battery_announce_choice = wx.Choice(panel)
        battery_announce_options = [_("1%"), _("10%"), _("15%"), _("25%"), _("Never")]
        self.battery_announce_choice.AppendItems(battery_announce_options)
        self.battery_announce_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.battery_announce_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # Charger Connection Monitoring
        self.monitor_charger_cb = wx.CheckBox(panel, label=_("Monitor charger connection and disconnection"))
        self.monitor_charger_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.monitor_charger_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.monitor_charger_cb, flag=wx.LEFT | wx.TOP, border=10)

        panel.SetSizer(vbox)

    def InitWindowsPanel(self):
        panel = self.windows_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        # sapi_settings_button = wx.Button(panel, label=_("Change SAPI settings"))
        # sapi_settings_button.Bind(wx.EVT_BUTTON, self.OnSapiSettings)
        # sapi_settings_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        # vbox.Add(sapi_settings_button, flag=wx.ALL | wx.EXPAND, border=10)

        # ease_of_access_button = wx.Button(panel, label=_("Ease of Access"))
        # ease_of_access_button.Bind(wx.EVT_BUTTON, self.OnEaseOfAccess)
        # ease_of_access_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        # vbox.Add(ease_of_access_button, flag=wx.ALL | wx.EXPAND, border=10)

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

    def InitStereoSpeechPanel(self):
        """Initialize the Stereo Speech Settings panel"""
        panel = self.stereo_speech_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Voice selection
        voice_label = wx.StaticText(panel, label=_("Voice:"))
        vbox.Add(voice_label, flag=wx.LEFT | wx.TOP, border=10)

        self.voice_choice = wx.Choice(panel)
        self.voice_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.voice_choice.Bind(wx.EVT_CHOICE, self.OnVoiceChanged)
        vbox.Add(self.voice_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # Rate slider
        rate_label = wx.StaticText(panel, label=_("Speech rate:"))
        vbox.Add(rate_label, flag=wx.LEFT | wx.TOP, border=10)

        self.rate_slider = wx.Slider(panel, value=0, minValue=-10, maxValue=10,
                                     style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.rate_slider.SetName(_("Speech rate"))
        self.rate_slider.Bind(wx.EVT_SLIDER, self.OnRateChanged)
        self.rate_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.rate_slider, flag=wx.LEFT | wx.EXPAND, border=10)

        # Volume slider
        volume_label = wx.StaticText(panel, label=_("Speech volume:"))
        vbox.Add(volume_label, flag=wx.LEFT | wx.TOP, border=10)

        self.speech_volume_slider = wx.Slider(panel, value=100, minValue=0, maxValue=100,
                                              style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        self.speech_volume_slider.SetName(_("Speech volume"))
        self.speech_volume_slider.Bind(wx.EVT_SLIDER, self.OnSpeechVolumeChanged)
        self.speech_volume_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.speech_volume_slider, flag=wx.LEFT | wx.EXPAND, border=10)

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

        startup_mode_value = general_settings.get('startup_mode', 'normal')
        if startup_mode_value == 'minimized':
            self.startup_mode_choice.SetSelection(1)
        elif startup_mode_value == 'klango':
            self.startup_mode_choice.SetSelection(2)
        else:
            self.startup_mode_choice.SetSelection(0)

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
        self.stereo_speech_cb.SetValue(str(invisible_interface_settings.get('stereo_speech', 'False')).lower() in ['true', '1'])
        self.titan_hotkey_ctrl.SetValue(invisible_interface_settings.get('titan_hotkey', ''))

        environment_settings = self.settings.get('environment', {})
        self.announce_screen_lock_cb.SetValue(str(environment_settings.get('announce_screen_lock', 'True')).lower() in ['true', '1'])
        self.windows_e_hook_cb.SetValue(str(environment_settings.get('windows_e_hook', 'False')).lower() in ['true', '1'])
        self.enable_tce_sounds_cb.SetValue(str(environment_settings.get('enable_tce_sounds', 'False')).lower() in ['true', '1'])

        # Load system monitor settings
        system_monitor_settings = self.settings.get('system_monitor', {})
        
        # Volume monitor setting
        volume_monitor = system_monitor_settings.get('volume_monitor', 'sound')
        volume_monitor_mapping = {'none': 0, 'sound': 1, 'speech': 2, 'both': 3}
        self.volume_monitor_choice.SetSelection(volume_monitor_mapping.get(volume_monitor, 1))
        
        # Battery announce interval
        battery_announce = system_monitor_settings.get('battery_announce_interval', '10%')
        battery_mapping = {'1%': 0, '10%': 1, '15%': 2, '25%': 3, 'never': 4}
        self.battery_announce_choice.SetSelection(battery_mapping.get(battery_announce, 1))
        
        # Charger monitoring
        self.monitor_charger_cb.SetValue(str(system_monitor_settings.get('monitor_charger', 'True')).lower() in ['true', '1'])

        # Load stereo speech settings
        self.load_stereo_speech_settings()

        # Show/hide stereo speech panel based on checkbox state
        self.update_stereo_speech_panel_visibility()

        if hasattr(self, 'windows_panel'):
            windows_settings = self.settings.get('windows', {})
            mute_disabled = windows_settings.get('disable_mute_on_start', 'False')
            self.mute_checkbox.SetValue(str(mute_disabled).lower() in ['true', '1'])
            # Loading initial volume is now in InitWindowsPanel using pycaw


    def OnSapiSettings(self, event):
        try:
            # Use subprocess to run control panel command for SAPI settings
            command = ["control.exe", "sapi.cpl"]
            print(f"INFO: Attempting to run command: {' '.join(command)}")
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            
            if result.returncode != 0:
                error_message = _("Command '{}' finished with error code {}.\n").format(' '.join(command), result.returncode)
                if result.stdout:
                    error_message += f"Stdout:\n{result.stdout}\n"
                if result.stderr:
                    error_message += f"Stderr:\n{result.stderr}"
                print(f"ERROR: Subprocess error in OnSapiSettings:\n{error_message}")
                wx.MessageBox(_("Cannot open SAPI settings:\n{}\n\nTechnical details in the console.").format(error_message), _("Error"), wx.OK | wx.ICON_ERROR)
            else:
                print("INFO: SAPI settings command executed successfully.")

        except FileNotFoundError:
            print("ERROR: Executable control.exe not found.")
            wx.MessageBox(_("Error: Executable control.exe not found. Make sure Windows is working correctly."), _("Error"), wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Unexpected error while opening SAPI settings: {e}")
            wx.MessageBox(_("Unexpected error while opening SAPI settings:\n{}\n\nTechnical details in the console.").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
            traceback.print_exc()
        event.Skip()


    def OnEaseOfAccess(self, event):
        try:
            # Try modern Settings app first (Windows 10/11)
            command = ["ms-settings:easeofaccess"]
            print(f"INFO: Attempting to run command: {' '.join(command)}")
            result = subprocess.run(command, check=False, capture_output=True, text=True, shell=True)
            
            if result.returncode != 0:
                print("INFO: Modern Settings app failed, trying legacy Control Panel...")
                # Fallback to legacy control panel
                command = ["control.exe", "access.cpl"]
                print(f"INFO: Attempting to run legacy command: {' '.join(command)}")
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
                    print("INFO: Legacy Ease of Access command executed successfully.")
            else:
                print("INFO: Modern Ease of Access settings opened successfully.")

        except FileNotFoundError:
            print("ERROR: Executable not found.")
            wx.MessageBox(_("Error: Cannot find accessibility settings. Make sure Windows is working correctly."), _("Error"), wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Unexpected error while opening Ease of Access: {e}")
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
        
        # Debounce the sound to prevent audio spam during rapid navigation
        if self.theme_volume_timer:
            self.theme_volume_timer.cancel()

        self.theme_volume_timer = threading.Timer(0.1, lambda: play_sound('system/volume.ogg'))
        self.theme_volume_timer.start()
        
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
        startup_mode_selection = self.startup_mode_choice.GetSelection()
        if startup_mode_selection == 1:
            startup_mode = 'minimized'
        elif startup_mode_selection == 2:
            startup_mode = 'klango'
        else:
            startup_mode = 'normal'
        self.settings['general'] = {
            'quick_start': str(self.quick_start_cb.GetValue()),
            'confirm_exit': str(self.confirm_exit_cb.GetValue()),
            'startup_mode': startup_mode,
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
            'stereo_speech': str(self.stereo_speech_cb.GetValue()),
            'titan_hotkey': self.titan_hotkey_ctrl.GetValue()
        }

        self.settings['environment'] = {
            'announce_screen_lock': str(self.announce_screen_lock_cb.GetValue()),
            'windows_e_hook': str(self.windows_e_hook_cb.GetValue()),
            'enable_tce_sounds': str(self.enable_tce_sounds_cb.GetValue())
        }

        # Save system monitor settings
        volume_monitor_options = ['none', 'sound', 'speech', 'both']
        battery_announce_options = ['1%', '10%', '15%', '25%', 'never']
        
        self.settings['system_monitor'] = {
            'volume_monitor': volume_monitor_options[self.volume_monitor_choice.GetSelection()],
            'battery_announce_interval': battery_announce_options[self.battery_announce_choice.GetSelection()],
            'monitor_charger': str(self.monitor_charger_cb.GetValue())
        }

        # Save stereo speech settings if enabled
        if self.stereo_speech_cb.GetValue():
            self.settings['stereo_speech'] = {
                'voice': self.voice_choice.GetStringSelection(),
                'rate': str(self.rate_slider.GetValue()),
                'volume': str(self.speech_volume_slider.GetValue())
            }

        if hasattr(self, 'windows_panel'):
            self.settings['windows'] = {
                'disable_mute_on_start': str(self.mute_checkbox.GetValue())
                # TODO: Save the current slider volume value if needed on startup
                # (usually not necessary, as the system remembers the volume)
            }

        save_settings(self.settings)
        
        # Restart system monitor with new settings
        try:
            restart_system_monitor()
        except Exception as e:
            print(f"Warning: Could not restart system monitor: {e}")
        
        speaker.speak(_('Settings have been saved. Please restart the application for the language change to take full effect.'))
        print("INFO: Settings saved.")
        self.Close()

    def OnCancel(self, event):
        print("INFO: Settings canceled.")
        self.Close()
    
    def apply_skin_settings(self):
        """Apply current skin settings to settings window"""
        try:
            interface_settings = self.settings.get('interface', {})
            skin_name = interface_settings.get('skin', 'default')
            
            skin_path = os.path.join(SKINS_DIR, skin_name, "skin.ini")
            if not os.path.exists(skin_path):
                print(f"WARNING: Skin file not found: {skin_path}")
                return
            
            config = configparser.ConfigParser()
            config.read(skin_path, encoding='utf-8')
            
            colors = dict(config.items('Colors')) if config.has_section('Colors') else {}
            fonts = dict(config.items('Fonts')) if config.has_section('Fonts') else {}
            
            # Apply colors
            if colors:
                # Convert hex colors to wx.Colour
                def hex_to_wx_colour(hex_color):
                    hex_color = hex_color.lstrip('#')
                    return wx.Colour(int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))
                
                # Apply background colors
                frame_bg = colors.get('frame_background_color', '#C0C0C0')
                panel_bg = colors.get('panel_background_color', '#C0C0C0')
                
                self.SetBackgroundColour(hex_to_wx_colour(frame_bg))
                
                # Apply to all panels
                for child in self.GetChildren():
                    if isinstance(child, wx.Panel):
                        child.SetBackgroundColour(hex_to_wx_colour(panel_bg))
                        # Apply to notebook panels
                        if hasattr(child, 'notebook'):
                            for page_idx in range(child.notebook.GetPageCount()):
                                page = child.notebook.GetPage(page_idx)
                                page.SetBackgroundColour(hex_to_wx_colour(panel_bg))
            
            # Apply fonts
            if fonts:
                default_size = int(fonts.get('default_font_size', 9))
                default_face = fonts.get('default_font_face', 'MS Sans Serif')
                
                font = wx.Font(default_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName=default_face)
                self.SetFont(font)
            
            # Refresh the window
            self.Refresh()
            
        except Exception as e:
            print(f"Error applying skin to settings window: {e}")

    def OnFocus(self, event):
        play_sound('core/FOCUS.ogg')
        vibrate_focus_change()  # Add vibration for focus changes
        event.Skip()

    def OnSelect(self, event):
        play_sound('core/SELECT.ogg')
        vibrate_selection()  # Add vibration for selections
        event.Skip()

    def OnCheckBox(self, event):
        if event.IsChecked():
            play_sound('ui/X.ogg')
            vibrate_selection()  # Add vibration for checkbox checked
        else:
            play_sound('core/FOCUS.ogg')
            vibrate_focus_change()  # Add vibration for checkbox unchecked
        event.Skip()

    def OnStereoSpeechChanged(self, event):
        """Handle stereo speech checkbox change"""
        if event.IsChecked():
            play_sound('ui/X.ogg')
            vibrate_selection()  # Add vibration for stereo speech enabled
        else:
            play_sound('core/FOCUS.ogg')
            vibrate_focus_change()  # Add vibration for stereo speech disabled
        
        # Update panel visibility
        self.update_stereo_speech_panel_visibility()
        event.Skip()

    def update_stereo_speech_panel_visibility(self):
        """Show or hide the stereo speech panel based on checkbox state"""
        stereo_enabled = self.stereo_speech_cb.GetValue()
        
        # Find if stereo speech panel is already added
        stereo_panel_index = -1
        for i in range(self.notebook.GetPageCount()):
            if self.notebook.GetPage(i) == self.stereo_speech_panel:
                stereo_panel_index = i
                break
        
        if stereo_enabled and stereo_panel_index == -1:
            # Add the panel if not present
            self.notebook.AddPage(self.stereo_speech_panel, _("Stereo Speech Settings"))
        elif not stereo_enabled and stereo_panel_index != -1:
            # Remove the panel if present
            self.notebook.RemovePage(stereo_panel_index)

    def load_stereo_speech_settings(self):
        """Load stereo speech settings from file"""
        # Load voices
        self.load_available_voices()
        
        # Load settings
        stereo_settings = self.settings.get('stereo_speech', {})
        
        # Set voice
        voice = stereo_settings.get('voice', '')
        if voice and self.voice_choice.FindString(voice) != wx.NOT_FOUND:
            self.voice_choice.SetStringSelection(voice)
            # Apply voice to stereo speech
            try:
                voice_index = self.voice_choice.GetSelection()
                if voice_index >= 0:
                    stereo_speech = get_stereo_speech()
                    stereo_speech.set_voice(voice_index)
            except Exception as e:
                print(f"Error setting initial voice: {e}")
        elif self.voice_choice.GetCount() > 0:
            self.voice_choice.SetSelection(0)
        
        # Set rate
        rate = int(stereo_settings.get('rate', '0'))
        self.rate_slider.SetValue(rate)
        # Apply rate to stereo speech
        try:
            stereo_speech = get_stereo_speech()
            stereo_speech.set_rate(rate)
        except Exception as e:
            print(f"Error setting initial rate: {e}")
        
        # Set volume
        volume = int(stereo_settings.get('volume', '100'))
        self.speech_volume_slider.SetValue(volume)
        # Apply volume to stereo speech
        try:
            stereo_speech = get_stereo_speech()
            stereo_speech.set_volume(volume)
        except Exception as e:
            print(f"Error setting initial volume: {e}")

    def load_available_voices(self):
        """Load available SAPI voices"""
        self.voice_choice.Clear()
        
        try:
            stereo_speech = get_stereo_speech()
            voices = stereo_speech.get_available_voices()
            
            if voices:
                for voice in voices:
                    self.voice_choice.Append(voice)
            else:
                self.voice_choice.Append(_("Default voice"))
        except Exception as e:
            print(f"Error loading SAPI voices: {e}")
            self.voice_choice.Append(_("Default voice"))

    def OnVoiceChanged(self, event):
        """Handle voice selection change"""
        play_sound('core/FOCUS.ogg')

        try:
            voice_index = self.voice_choice.GetSelection()
            if voice_index >= 0:
                stereo_speech = get_stereo_speech()
                stereo_speech.set_voice(voice_index)
        except Exception as e:
            print(f"Error setting voice: {e}")

        event.Skip()

    def OnRateChanged(self, event):
        """Handle rate slider change"""
        # Debounce the stereo speech calls to prevent hangs
        if self.rate_timer:
            self.rate_timer.cancel()
        
        rate = self.rate_slider.GetValue()
        
        def update_rate():
            try:
                stereo_speech = get_stereo_speech()
                stereo_speech.set_rate(rate)
                play_sound('core/FOCUS.ogg')
            except Exception as e:
                print(f"Error setting rate: {e}")
        
        self.rate_timer = threading.Timer(0.2, update_rate)
        self.rate_timer.start()
        
        event.Skip()

    def OnSpeechVolumeChanged(self, event):
        """Handle speech volume slider change"""
        # Debounce the stereo speech calls to prevent hangs
        if self.speech_volume_timer:
            self.speech_volume_timer.cancel()
        
        volume = self.speech_volume_slider.GetValue()
        
        def update_volume():
            try:
                stereo_speech = get_stereo_speech()
                stereo_speech.set_volume(volume)
                play_sound('core/FOCUS.ogg')
            except Exception as e:
                print(f"Error setting volume: {e}")
        
        self.speech_volume_timer = threading.Timer(0.2, update_volume)
        self.speech_volume_timer.start()
        
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