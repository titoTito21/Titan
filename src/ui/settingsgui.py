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
        from pycaw.pycaw import AudioUtilities
        print("INFO: Moduł pycaw zaimportowany pomyślnie.")

        # Spróbuj zainicjalizować kontrolę głośności domyślnego urządzenia odtwarzającego
        try:
            # Use safe COM initialization from com_fix module
            from src.system.com_fix import init_com_safe
            init_com_safe()

            devices = AudioUtilities.GetSpeakers() # Pobiera domyślne urządzenie odtwarzające
            # In newer pycaw versions (20251023+), EndpointVolume is a property, not a method
            volume = devices.EndpointVolume
            print("INFO: Kontrola głośności systemu zainicjalizowana dla domyślnego urządzenia.")
        except Exception as e:
            print(f"WARNING: Błąd inicjalizacji kontroli głośności systemu (domyślne urządzenie). Funkcja zmiany głośności będzie niedostępna: {e}")
            # traceback.print_exc() # Opcjonalnie: pokaż pełny traceback błędu inicjalizacji
            volume = None # Ustaw na None jeśli inicjalizacja nie powiedzie się

    except ImportError:
        print("WARNING: Biblioteka pycaw nie jest zainstalowana. Kontrola głośności systemu będzie niedostępna.")
        print("Aby zainstalować: pip install pycaw")
        AudioUtilities = None
    except Exception as e:
        print(f"WARNING: Nieoczekiwany błąd podczas importu pycaw: {e}")
        AudioUtilities = None
else:
    print("INFO: Nie działa na Windows, pomijam import i inicjalizację pycaw.")
    AudioUtilities = None


# Import accessible_output3 with COM safety
try:
    from src.system.com_fix import suppress_com_errors
    suppress_com_errors()
except (ImportError, Exception):
    pass

import accessible_output3.outputs.auto
from src.settings.settings import load_settings, save_settings, get_setting, set_setting
from src.titan_core.sound import set_theme, initialize_sound, play_sound, resource_path, set_sound_theme_volume
from src.controller.controller_vibrations import (
    vibrate_cursor_move, vibrate_menu_open, vibrate_menu_close, vibrate_selection,
    vibrate_focus_change, vibrate_error, vibrate_notification, test_vibration,
    set_vibration_enabled, set_vibration_strength, get_controller_info
)
from src.titan_core.translation import get_available_languages, get_available_languages_display, get_language_display_name, get_language_code_from_display_name, set_language
from src.titan_core.stereo_speech import get_stereo_speech
from src.system.system_monitor import restart_system_monitor
from src.titan_core.skin_manager import get_skin_manager, get_current_skin, apply_skin_to_window

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

SFX_DIR = resource_path('sfx')
SKINS_DIR = resource_path('skins')
speaker = accessible_output3.outputs.auto.Auto()


class SettingsFrame(wx.Frame):
    def __init__(self, *args, component_manager=None, **kw):
        super(SettingsFrame, self).__init__(*args, **kw)

        self.settings = load_settings()
        self.component_manager = component_manager

        # Debounce timers for sliders to prevent hangs
        self.rate_timer = None
        self.speech_volume_timer = None
        self.theme_volume_timer = None

        # Settings categories system
        self.categories = {}  # {name: panel}
        self.category_order = []  # List of category names in order
        self.current_category_panel = None
        self.category_save_callbacks = {}  # {category_name: save_callback}
        self.category_load_callbacks = {}  # {category_name: load_callback}
        self.is_initializing = True  # Flag to prevent sounds during initialization

        self.InitUI()
        # Don't play sound during initialization
        vibrate_menu_open()  # Add vibration for opening settings

        # Bind close event to hide instead of destroy
        self.Bind(wx.EVT_CLOSE, self.OnClose)

        self.load_settings_to_ui()

        # Load component settings after UI is initialized
        self.load_component_settings()

        # Apply skin settings after UI is loaded
        self.apply_skin_settings()

        # Initialization complete - allow sounds to play
        self.is_initializing = False

    def Show(self, show=True):
        """Override Show to refresh categories before displaying"""
        if show:
            # Check if the frame and its widgets are still valid
            try:
                # Try to access a basic window property to verify frame is alive
                _ = self.GetTitle()
            except RuntimeError:
                print("[SettingsFrame] WARNING: Frame has been destroyed, cannot show")
                return False

            print("[SettingsFrame] >>>>> Show() called - forcing category refresh <<<<<")
            # Always refresh categories before showing
            try:
                self.force_rebuild_categories()
                # Reload all settings including component settings
                self.load_settings_to_ui()
                self.load_component_settings()
            except RuntimeError as e:
                print(f"[SettingsFrame] Widget access error (frame may be destroyed): {e}")
                return False
            except Exception as e:
                print(f"[SettingsFrame] Error refreshing settings: {e}")
                import traceback
                traceback.print_exc()

        result = super().Show(show)

        # Set focus to category list when showing the window
        if show and result:
            try:
                self.category_list.SetFocus()
                print("[SettingsFrame] Focus set to category list")
            except (RuntimeError, AttributeError) as e:
                print(f"[SettingsFrame] Could not set focus to category list: {e}")

        return result

    def force_rebuild_categories(self):
        """Force complete rebuild of category list"""
        print("[SettingsFrame] ***** FORCE REBUILD STARTING *****")

        # Check if category_list is still valid before accessing it
        try:
            # Try to access a property to verify widget is still alive
            _ = self.category_list.GetCount()
        except (RuntimeError, AttributeError):
            print("[SettingsFrame] WARNING: category_list is not valid, skipping rebuild")
            return

        # Get current selection
        current_selection = self.category_list.GetSelection()
        current_category = None
        if current_selection != wx.NOT_FOUND and current_selection < len(self.category_order):
            current_category = self.category_order[current_selection]

        # Completely clear and rebuild
        self.category_list.Clear()

        print(f"[SettingsFrame] Total categories to add: {len(self.category_order)}")
        print(f"[SettingsFrame] Categories: {self.category_order}")

        # Add all categories
        for idx, category_name in enumerate(self.category_order):
            print(f"[SettingsFrame] Adding [{idx}]: {category_name}")
            self.category_list.Append(category_name)

        # Force GUI update
        self.category_list.Update()
        self.category_list.Refresh()
        self.Layout()

        # Restore selection or select first
        if current_category and current_category in self.category_order:
            new_index = self.category_order.index(current_category)
            self.category_list.SetSelection(new_index)
        elif self.category_list.GetCount() > 0:
            self.category_list.SetSelection(0)
            if len(self.category_order) > 0:
                self.ShowCategory(self.category_order[0])

        print(f"[SettingsFrame] ***** FORCE REBUILD COMPLETE - List has {self.category_list.GetCount()} items *****")


    def InitUI(self):
        panel = wx.Panel(self)

        # Create horizontal sizer for list and content
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left panel - category list
        left_panel = wx.Panel(panel)
        left_vbox = wx.BoxSizer(wx.VERTICAL)

        category_list_label = wx.StaticText(left_panel, label=_("Kategoria ustawień"))
        left_vbox.Add(category_list_label, flag=wx.ALL, border=5)

        self.category_list = wx.ListBox(left_panel)
        self.category_list.Bind(wx.EVT_LISTBOX, self.OnCategorySelected)
        self.category_list.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        left_vbox.Add(self.category_list, 1, wx.EXPAND | wx.ALL, 5)

        left_panel.SetSizer(left_vbox)
        main_sizer.Add(left_panel, 0, wx.EXPAND | wx.ALL, 5)

        # Right panel - settings content (scrollable)
        self.content_panel = wx.ScrolledWindow(panel)
        self.content_panel.SetScrollRate(5, 5)
        self.content_sizer = wx.BoxSizer(wx.VERTICAL)
        self.content_panel.SetSizer(self.content_sizer)

        main_sizer.Add(self.content_panel, 1, wx.EXPAND | wx.ALL, 5)

        # Initialize core settings panels
        self.InitCoreCategories()

        # Buttons
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        save_button = wx.Button(panel, label=_("Save"))
        save_button.Bind(wx.EVT_BUTTON, self.OnSave)
        save_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        cancel_button = wx.Button(panel, label=_("Cancel"))
        cancel_button.Bind(wx.EVT_BUTTON, self.OnCancel)
        cancel_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button, flag=wx.RIGHT, border=10)

        # Main layout
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(main_sizer, 1, wx.EXPAND | wx.ALL, 10)
        vbox.Add(hbox, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)

        panel.SetSizer(vbox)

        self.SetSize((800, 600))
        self.SetTitle(_("Settings"))
        self.Centre()

        # Rebuild category list from registered categories
        self.rebuild_category_list()

    def InitCoreCategories(self):
        """Initialize core settings categories"""
        # Create panels for each category
        self.general_panel = wx.Panel(self.content_panel)
        self.sound_panel = wx.Panel(self.content_panel)
        self.interface_panel = wx.Panel(self.content_panel)
        self.invisible_interface_panel = wx.Panel(self.content_panel)
        self.environment_panel = wx.Panel(self.content_panel)
        self.system_monitor_panel = wx.Panel(self.content_panel)
        self.stereo_speech_panel = wx.Panel(self.content_panel)

        # Register categories
        self.register_category(_("General"), self.general_panel)
        self.register_category(_("Sound"), self.sound_panel)
        self.register_category(_("Interface"), self.interface_panel)
        self.register_category(_("Invisible Interface"), self.invisible_interface_panel)
        self.register_category(_("Environment"), self.environment_panel)
        self.register_category(_("System Monitor"), self.system_monitor_panel)
        self.register_category(_("Titan TTS"), self.stereo_speech_panel)

        if sys.platform == 'win32':
            self.windows_panel = wx.Panel(self.content_panel)
            self.register_category(_("Windows"), self.windows_panel)

        # Initialize panels
        self.InitGeneralPanel()
        self.InitSoundPanel()
        self.InitInterfacePanel()
        self.InitInvisibleInterfacePanel()
        self.InitEnvironmentPanel()
        self.InitSystemMonitorPanel()
        self.InitStereoSpeechPanel()

        if sys.platform == 'win32':
            self.InitWindowsPanel()

    def register_category(self, name, panel, save_callback=None, load_callback=None):
        """
        Register a settings category

        Args:
            name: Display name of the category
            panel: wx.Panel containing the settings controls
            save_callback: Optional function to call when saving settings
                          Signature: save_callback(panel) -> None
            load_callback: Optional function to call when loading settings
                          Signature: load_callback(panel) -> None
        """
        print(f"[SettingsFrame] register_category called for: {name}")
        print(f"[SettingsFrame] is_initializing: {self.is_initializing}")

        if name not in self.categories:
            self.categories[name] = panel
            self.category_order.append(name)
            print(f"[SettingsFrame] Added {name} to category_order (now has {len(self.category_order)} items)")
            # Only append to list if we're not initializing (list will be rebuilt later)
            if not self.is_initializing:
                self.category_list.Append(name)
                print(f"[SettingsFrame] Appended {name} directly to list")
            else:
                print(f"[SettingsFrame] Skipped append (initializing)")
            panel.Hide()
            if save_callback:
                self.category_save_callbacks[name] = save_callback
            if load_callback:
                self.category_load_callbacks[name] = load_callback
        else:
            print(f"[SettingsFrame] Category {name} already registered")

    def rebuild_category_list(self):
        """Rebuild the category list from category_order"""
        print(f"[SettingsFrame] ========== rebuild_category_list called ==========")
        print(f"[SettingsFrame] category_order: {self.category_order}")
        print(f"[SettingsFrame] categories keys: {list(self.categories.keys())}")

        self.category_list.Clear()
        for category_name in self.category_order:
            print(f"[SettingsFrame] Adding to list: {category_name}")
            self.category_list.Append(category_name)

        print(f"[SettingsFrame] List now has {self.category_list.GetCount()} items")

        # Force visual update
        self.category_list.Refresh()
        self.category_list.Update()

        # Select first category if none selected
        if self.category_list.GetCount() > 0 and self.category_list.GetSelection() == wx.NOT_FOUND:
            print(f"[SettingsFrame] Selecting first category: {self.category_order[0]}")
            self.category_list.SetSelection(0)
            self.ShowCategory(self.category_order[0])

        print(f"[SettingsFrame] ========== rebuild complete ==========")

    def ShowCategory(self, category_name):
        """Show the selected category panel"""
        if category_name not in self.categories:
            return

        # Hide current panel
        if self.current_category_panel:
            self.current_category_panel.Hide()

        # Show new panel
        panel = self.categories[category_name]

        # Clear content sizer
        self.content_sizer.Clear()

        # Add new panel
        self.content_sizer.Add(panel, 1, wx.EXPAND | wx.ALL, 10)
        panel.Show()

        self.current_category_panel = panel

        # Refresh layout
        self.content_panel.Layout()
        self.content_panel.FitInside()

        # Play category switch sound only if not initializing
        if not self.is_initializing:
            play_sound('ui/switch_category.ogg')
            vibrate_focus_change()

    def OnCategorySelected(self, event):
        """Handle category selection"""
        selection = self.category_list.GetSelection()
        if selection != wx.NOT_FOUND:
            category_name = self.category_order[selection]
            self.ShowCategory(category_name)

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

        available_languages = get_available_languages_display()
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

        self.announce_first_item_cb = wx.CheckBox(self.invisible_interface_panel, label=_("Announce first item in category"))
        self.announce_first_item_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.announce_first_item_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.announce_first_item_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.invisible_interface_panel.SetSizer(vbox)

    def InitEnvironmentPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.announce_screen_lock_cb = wx.CheckBox(self.environment_panel, label=_("Announce screen locking state"))
        self.announce_screen_lock_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.announce_screen_lock_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.announce_screen_lock_cb, flag=wx.LEFT | wx.TOP, border=10)

        if sys.platform == 'win32':
            self.windows_e_hook_cb = wx.CheckBox(self.environment_panel, label=_("Modify system interface"))
            self.windows_e_hook_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
            self.windows_e_hook_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
            vbox.Add(self.windows_e_hook_cb, flag=wx.LEFT | wx.TOP, border=10)
        else:
            self.windows_e_hook_cb = None

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
        """Initialize the Titan TTS Settings panel"""
        panel = self.stereo_speech_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Enable stereo speech checkbox
        self.stereo_speech_cb = wx.CheckBox(panel, label=_("Enable Titan TTS"))
        self.stereo_speech_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.stereo_speech_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.stereo_speech_cb, flag=wx.LEFT | wx.TOP, border=10)

        # Engine selection
        engine_label = wx.StaticText(panel, label=_("Speech engine:"))
        vbox.Add(engine_label, flag=wx.LEFT | wx.TOP, border=10)

        self.engine_choice = wx.Choice(panel)
        self.engine_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.engine_choice.Bind(wx.EVT_CHOICE, self.OnEngineChanged)
        vbox.Add(self.engine_choice, flag=wx.LEFT | wx.EXPAND, border=10)

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

        # --- ElevenLabs-specific controls (shown only when ElevenLabs engine selected) ---
        self.elevenlabs_api_key_label = wx.StaticText(panel, label=_("ElevenLabs API Key:"))
        vbox.Add(self.elevenlabs_api_key_label, flag=wx.LEFT | wx.TOP, border=10)

        self.elevenlabs_api_key_ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
        self.elevenlabs_api_key_ctrl.SetToolTip(_("Your ElevenLabs API key. Get it from elevenlabs.io"))
        self.elevenlabs_api_key_ctrl.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.elevenlabs_api_key_ctrl.Bind(wx.EVT_KILL_FOCUS, self.OnElevenLabsApiKeyChanged)
        vbox.Add(self.elevenlabs_api_key_ctrl, flag=wx.LEFT | wx.EXPAND, border=10)

        # Initially hidden - shown only when ElevenLabs engine is selected
        self.elevenlabs_api_key_label.Hide()
        self.elevenlabs_api_key_ctrl.Hide()

        panel.SetSizer(vbox)
        panel.Layout()

    def load_component_settings(self):
        """Load settings from all component categories"""
        for category_name, load_callback in self.category_load_callbacks.items():
            if category_name in self.categories:
                try:
                    panel = self.categories[category_name]
                    load_callback(panel)
                    print(f"Loaded settings for category: {category_name}")
                except Exception as e:
                    print(f"Error loading settings for category {category_name}: {e}")
                    import traceback
                    traceback.print_exc()

    def load_settings_to_ui(self):
        # Language
        current_lang = get_setting('language', 'pl')
        current_lang_display = get_language_display_name(current_lang)
        if self.lang_choice.FindString(current_lang_display) != wx.NOT_FOUND:
            self.lang_choice.SetStringSelection(current_lang_display)
        else:
            self.lang_choice.SetStringSelection(get_language_display_name('pl'))

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
        self.announce_first_item_cb.SetValue(str(invisible_interface_settings.get('announce_first_item', 'False')).lower() in ['true', '1'])

        environment_settings = self.settings.get('environment', {})
        self.announce_screen_lock_cb.SetValue(str(environment_settings.get('announce_screen_lock', 'True')).lower() in ['true', '1'])
        if self.windows_e_hook_cb is not None:
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

        if hasattr(self, 'windows_panel'):
            windows_settings = self.settings.get('windows', {})
            mute_disabled = windows_settings.get('disable_mute_on_start', 'False')
            self.mute_checkbox.SetValue(str(mute_disabled).lower() in ['true', '1'])
            # Loading initial volume is now in InitWindowsPanel using pycaw


    def OnSapiSettings(self, event):
        if sys.platform != 'win32':
            wx.MessageBox(_("This feature is only available on Windows."), _("Information"), wx.OK | wx.ICON_INFORMATION)
            event.Skip()
            return
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
        if sys.platform != 'win32':
            wx.MessageBox(_("This feature is only available on Windows."), _("Information"), wx.OK | wx.ICON_INFORMATION)
            event.Skip()
            return
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
        # Get old settings before saving to check for changes
        old_settings = load_settings()
        old_startup_mode = old_settings.get('general', {}).get('startup_mode', 'normal')
        old_language = old_settings.get('general', {}).get('language', 'pl')

        # Save language setting (convert display name to code)
        selected_language_display = self.lang_choice.GetStringSelection()
        selected_language = get_language_code_from_display_name(selected_language_display)
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
            'announce_first_item': str(self.announce_first_item_cb.GetValue()),
            'stereo_speech': str(self.stereo_speech_cb.GetValue())  # Keep for backward compatibility
        }

        env_settings = {
            'announce_screen_lock': str(self.announce_screen_lock_cb.GetValue()),
            'enable_tce_sounds': str(self.enable_tce_sounds_cb.GetValue())
        }
        if self.windows_e_hook_cb is not None:
            env_settings['windows_e_hook'] = str(self.windows_e_hook_cb.GetValue())
        self.settings['environment'] = env_settings

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
            # Get current engine from display name
            engine_display = self.engine_choice.GetStringSelection()
            engine = self._display_to_engine(engine_display)

            # Get voice (dict-based engines save ID, string-based save name)
            stereo_speech = get_stereo_speech()
            voice_index = self.voice_choice.GetSelection()
            voice_value = ''

            if voice_index >= 0:
                voices = stereo_speech.get_available_voices()
                if voice_index < len(voices):
                    if isinstance(voices[voice_index], dict):
                        voice_value = voices[voice_index]['id']
                    else:
                        voice_value = self.voice_choice.GetStringSelection()

            # Save ElevenLabs API key if present
            elevenlabs_api_key = self.elevenlabs_api_key_ctrl.GetValue().strip()
            if elevenlabs_api_key:
                try:
                    stereo_speech_obj = get_stereo_speech()
                    if hasattr(stereo_speech_obj, 'set_elevenlabs_api_key'):
                        stereo_speech_obj.set_elevenlabs_api_key(elevenlabs_api_key)
                except Exception as e:
                    print(f"Error applying ElevenLabs API key on save: {e}")

            self.settings['stereo_speech'] = {
                'engine': engine,
                'voice': voice_value,
                'rate': str(self.rate_slider.GetValue()),
                'volume': str(self.speech_volume_slider.GetValue()),
                'elevenlabs_api_key': elevenlabs_api_key,
            }

        if hasattr(self, 'windows_panel'):
            self.settings['windows'] = {
                'disable_mute_on_start': str(self.mute_checkbox.GetValue())
                # TODO: Save the current slider volume value if needed on startup
                # (usually not necessary, as the system remembers the volume)
            }

        save_settings(self.settings)

        # Call save callbacks for component categories
        for category_name, save_callback in self.category_save_callbacks.items():
            if category_name in self.categories:
                try:
                    panel = self.categories[category_name]
                    save_callback(panel)
                    print(f"Saved settings for category: {category_name}")
                except Exception as e:
                    print(f"Error saving settings for category {category_name}: {e}")
                    import traceback
                    traceback.print_exc()

        # Restart system monitor with new settings
        try:
            restart_system_monitor()
        except Exception as e:
            print(f"Warning: Could not restart system monitor: {e}")

        # Check if startup mode or language changed to provide appropriate message
        if old_startup_mode != startup_mode or old_language != selected_language:
            speaker.speak(_('Settings have been saved. Please restart the application for changes to take full effect.'))
        else:
            speaker.speak(_('Settings have been saved.'))
        print("INFO: Settings saved.")
        self.Close()

    def OnCancel(self, event):
        print("INFO: Settings canceled.")
        self.Close()

    def OnClose(self, event):
        """Handle window close event - hide instead of destroy"""
        print("INFO: Settings window closing - hiding instead of destroying.")
        self.Hide()
        # Don't call event.Skip() or Destroy() - we want to keep the window alive

    def apply_skin_settings(self):
        """Apply current skin settings to settings window using skin manager"""
        try:
            skin = get_current_skin()

            # Apply window colors
            apply_skin_to_window(self)

            # Apply to all panels recursively
            def apply_to_children(parent):
                for child in parent.GetChildren():
                    if isinstance(child, wx.Panel):
                        apply_skin_to_window(child)
                        apply_to_children(child)

            apply_to_children(self)

            # Apply to all category panels
            for category_panel in self.categories.values():
                apply_skin_to_window(category_panel)
                apply_to_children(category_panel)

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

    def _get_engine_display_names(self):
        """Get mapping between engine IDs and display names."""
        return {
            'espeak': 'eSpeak NG',
            'sapi5': 'SAPI5',
            'say': _('macOS Speech'),
            'spd': _('Speech Dispatcher'),
            'elevenlabs': 'ElevenLabs TTS',
        }

    def _engine_to_display(self, engine_id):
        """Convert engine ID to display name."""
        return self._get_engine_display_names().get(engine_id, engine_id)

    def _display_to_engine(self, display_name):
        """Convert display name to engine ID."""
        reverse = {v: k for k, v in self._get_engine_display_names().items()}
        return reverse.get(display_name, display_name)

    def load_stereo_speech_settings(self):
        """Load stereo speech settings from file"""
        self.engine_choice.Clear()
        stereo_speech = get_stereo_speech()
        available_engines = stereo_speech.get_available_engines()

        # Add engine options with display names
        for engine in available_engines:
            self.engine_choice.Append(self._engine_to_display(engine))

        # Load settings
        stereo_settings = self.settings.get('stereo_speech', {})
        invisible_interface_settings = self.settings.get('invisible_interface', {})

        # Load enabled state
        stereo_enabled = str(invisible_interface_settings.get('stereo_speech', 'False')).lower() in ['true', '1']
        self.stereo_speech_cb.SetValue(stereo_enabled)

        # Load engine selection
        engine = stereo_settings.get('engine', 'espeak')
        stereo_speech.set_engine(engine)

        # Set engine in UI
        display_name = self._engine_to_display(engine)
        if self.engine_choice.FindString(display_name) != wx.NOT_FOUND:
            self.engine_choice.SetStringSelection(display_name)

        # If no engines available, set first one
        if self.engine_choice.GetSelection() == wx.NOT_FOUND and self.engine_choice.GetCount() > 0:
            self.engine_choice.SetSelection(0)

        # Load ElevenLabs API key (before loading voices so the API call can succeed)
        elevenlabs_api_key = stereo_settings.get('elevenlabs_api_key', '')
        self.elevenlabs_api_key_ctrl.SetValue(elevenlabs_api_key)
        if elevenlabs_api_key:
            try:
                stereo_speech_obj = get_stereo_speech()
                if hasattr(stereo_speech_obj, 'set_elevenlabs_api_key'):
                    stereo_speech_obj.set_elevenlabs_api_key(elevenlabs_api_key)
            except Exception as e:
                print(f"Error setting ElevenLabs API key from settings: {e}")

        # Show/hide ElevenLabs controls based on loaded engine
        is_elevenlabs = (engine == 'elevenlabs')
        self.elevenlabs_api_key_label.Show(is_elevenlabs)
        self.elevenlabs_api_key_ctrl.Show(is_elevenlabs)

        # Load voices for current engine
        self.load_available_voices()

        # Set voice
        voice = stereo_settings.get('voice', '')
        if voice:
            voices = stereo_speech.get_available_voices()
            # Dict-based voices (eSpeak, say, spd) — match by ID
            if voices and isinstance(voices[0], dict):
                for i, v in enumerate(voices):
                    if v.get('id') == voice:
                        self.voice_choice.SetSelection(i)
                        stereo_speech.set_voice(i)
                        break
            else:
                # String-based voices (SAPI5) — match by name
                if self.voice_choice.FindString(voice) != wx.NOT_FOUND:
                    self.voice_choice.SetStringSelection(voice)
                    try:
                        voice_index = self.voice_choice.GetSelection()
                        if voice_index >= 0:
                            stereo_speech.set_voice(voice_index)
                    except Exception as e:
                        print(f"Error setting initial voice: {e}")

        # If no voice selected, select first one
        if self.voice_choice.GetSelection() == wx.NOT_FOUND and self.voice_choice.GetCount() > 0:
            self.voice_choice.SetSelection(0)
            try:
                stereo_speech.set_voice(0)
            except Exception as e:
                print(f"Error setting default voice: {e}")

        # Set rate
        rate = int(stereo_settings.get('rate', '0'))
        self.rate_slider.SetValue(rate)
        # Apply rate to stereo speech
        try:
            stereo_speech.set_rate(rate)
        except Exception as e:
            print(f"Error setting initial rate: {e}")

        # Set volume
        volume = int(stereo_settings.get('volume', '100'))
        self.speech_volume_slider.SetValue(volume)
        # Apply volume to stereo speech
        try:
            stereo_speech.set_volume(volume)
        except Exception as e:
            print(f"Error setting initial volume: {e}")

    def load_available_voices(self):
        """Load available voices for current engine"""
        self.voice_choice.Clear()

        try:
            stereo_speech = get_stereo_speech()
            voices = stereo_speech.get_available_voices()

            if voices:
                for voice in voices:
                    if isinstance(voice, dict):
                        self.voice_choice.Append(voice.get('display_name', str(voice)))
                    else:
                        self.voice_choice.Append(str(voice))
                print(f"Loaded {len(voices)} voices for engine {stereo_speech.get_engine()}")
            else:
                self.voice_choice.Append(_("Default voice"))
        except Exception as e:
            print(f"Error loading voices: {e}")
            import traceback
            traceback.print_exc()
            self.voice_choice.Append(_("Default voice"))

    def OnEngineChanged(self, event):
        """Handle speech engine change"""
        play_sound('core/FOCUS.ogg')

        try:
            engine_selection = self.engine_choice.GetSelection()
            if engine_selection >= 0:
                display_name = self.engine_choice.GetString(engine_selection)
                engine_id = self._display_to_engine(display_name)
                stereo_speech = get_stereo_speech()
                stereo_speech.set_engine(engine_id)
                self.load_available_voices()

                # Show/hide ElevenLabs-specific controls
                is_elevenlabs = (engine_id == 'elevenlabs')
                self.elevenlabs_api_key_label.Show(is_elevenlabs)
                self.elevenlabs_api_key_ctrl.Show(is_elevenlabs)
                self.stereo_speech_panel.Layout()
                self.content_panel.FitInside()
        except Exception as e:
            print(f"Error setting engine: {e}")

        event.Skip()

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

    def OnElevenLabsApiKeyChanged(self, event):
        """Apply ElevenLabs API key immediately when the field loses focus."""
        try:
            api_key = self.elevenlabs_api_key_ctrl.GetValue().strip()
            if api_key:
                stereo_speech = get_stereo_speech()
                if hasattr(stereo_speech, 'set_elevenlabs_api_key'):
                    stereo_speech.set_elevenlabs_api_key(api_key)
                    # Reload voices now that a key is available
                    self.load_available_voices()
        except Exception as e:
            print(f"Error applying ElevenLabs API key: {e}")
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