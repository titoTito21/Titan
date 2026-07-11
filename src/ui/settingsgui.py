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
from src.titan_core.sound import set_theme, initialize_sound, play_sound, resource_path, set_sound_theme_volume, play_focus_sound
from src.controller.controller_vibrations import (
    vibrate_cursor_move, vibrate_menu_open, vibrate_menu_close, vibrate_selection,
    vibrate_focus_change, vibrate_error, vibrate_notification, test_vibration,
    set_vibration_enabled, set_vibration_strength, set_haptic_mode, get_controller_info,
    set_speech_haptic_sync
)
from src.titan_core.translation import get_available_languages, get_available_languages_display, get_language_display_name, get_language_code_from_display_name, set_language
from src.titan_core.stereo_speech import get_stereo_speech
from src.system.system_monitor import restart_system_monitor
from src.titan_core.skin_manager import get_skin_manager, get_current_skin, apply_skin_to_window

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

SFX_DIR = resource_path('sfx')
SKINS_DIR = resource_path('skins')
# Lazy, shared speaker (see src/accessibility/lazy_speaker.py): keeps the
# accessible_output3 stack-walk cost out of import time.
from src.accessibility.lazy_speaker import LazySpeaker
speaker = LazySpeaker()


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _wx_key_to_string(keycode, modifiers):
    """Convert a wx keycode + modifier mask into a normalized string id like 'shift+f2' or 'grave'.

    Returns None for pure modifier keys (Shift alone, Ctrl alone, etc.)
    """
    # Pure modifier presses are ignored
    if keycode in (wx.WXK_SHIFT, wx.WXK_CONTROL, wx.WXK_ALT,
                   wx.WXK_RAW_CONTROL, wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT):
        return None

    parts = []
    if modifiers & wx.MOD_CONTROL:
        parts.append('ctrl')
    if modifiers & wx.MOD_ALT:
        parts.append('alt')
    if modifiers & wx.MOD_SHIFT:
        parts.append('shift')
    if modifiers & wx.MOD_WIN:
        parts.append('win')

    # Function keys
    if wx.WXK_F1 <= keycode <= wx.WXK_F24:
        parts.append('f{}'.format(keycode - wx.WXK_F1 + 1))
        return '+'.join(parts)

    # Named keys
    named = {
        wx.WXK_SPACE: 'space',
        wx.WXK_TAB: 'tab',
        wx.WXK_RETURN: 'enter',
        wx.WXK_NUMPAD_ENTER: 'enter',
        wx.WXK_ESCAPE: 'escape',
        wx.WXK_BACK: 'backspace',
        wx.WXK_DELETE: 'delete',
        wx.WXK_INSERT: 'insert',
        wx.WXK_HOME: 'home',
        wx.WXK_END: 'end',
        wx.WXK_PAGEUP: 'pageup',
        wx.WXK_PAGEDOWN: 'pagedown',
        wx.WXK_UP: 'up',
        wx.WXK_DOWN: 'down',
        wx.WXK_LEFT: 'left',
        wx.WXK_RIGHT: 'right',
    }
    if keycode in named:
        parts.append(named[keycode])
        return '+'.join(parts)

    # Letters and digits
    if 32 < keycode < 127:
        ch = chr(keycode).lower()
        if ch == '`':
            ch = 'grave'
        parts.append(ch)
        return '+'.join(parts)

    return None


class KeyCaptureDialog(wx.Dialog):
    """Modal dialog that captures the next key combination pressed by the user."""

    def __init__(self, parent, current_label=''):
        super().__init__(parent, title=_("Capture Titan UI key"),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.captured_key = None

        vbox = wx.BoxSizer(wx.VERTICAL)

        prompt = wx.StaticText(self, label=_(
            "Press the key or key combination you want to use as the Titan UI key.\n"
            "Press Escape twice to cancel."))
        vbox.Add(prompt, flag=wx.ALL, border=10)

        self.captured_label = wx.StaticText(
            self,
            label=_("Current: {}").format(current_label) if current_label else _("Waiting for input...")
        )
        vbox.Add(self.captured_label, flag=wx.ALL | wx.EXPAND, border=10)

        btn_sizer = wx.StdDialogButtonSizer()
        self.ok_btn = wx.Button(self, wx.ID_OK)
        self.ok_btn.Enable(False)
        cancel_btn = wx.Button(self, wx.ID_CANCEL)
        btn_sizer.AddButton(self.ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        self.SetSizer(vbox)
        self.Fit()
        self.Centre()

        # Capture every keystroke
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._last_was_escape = False

    def _on_char_hook(self, event):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()

        # Two presses of Escape (with no modifiers) cancel the dialog.
        if keycode == wx.WXK_ESCAPE and modifiers == wx.MOD_NONE:
            if self._last_was_escape:
                self.EndModal(wx.ID_CANCEL)
                return
            self._last_was_escape = True
            self.captured_label.SetLabel(_("Press Escape again to cancel, or press another key."))
            return
        self._last_was_escape = False

        # After a key has been captured and the OK button is focused,
        # Space should activate it (just like Enter) instead of being
        # re-captured as the new Titan UI key.
        if (self.captured_key is not None
                and keycode == wx.WXK_SPACE
                and modifiers == wx.MOD_NONE
                and self.FindFocus() is self.ok_btn):
            self.EndModal(wx.ID_OK)
            return

        key_string = _wx_key_to_string(keycode, modifiers)
        if key_string is None:
            # Modifier-only press — ignore, wait for the actual key.
            return

        self.captured_key = key_string
        # Build a friendly display label using the parent's formatter when available
        try:
            parent = self.GetParent()
            display = parent._format_titan_ui_key(key_string) if hasattr(parent, '_format_titan_ui_key') else key_string
        except Exception:
            display = key_string
        self.captured_label.SetLabel(_("Captured: {}").format(display))
        self.ok_btn.Enable(True)
        self.ok_btn.SetFocus()


class SettingsFrame(wx.Frame):
    # Sound mode choice indices -> stored values (none/stereo/3d).
    _SOUND_MODE_VALUES = ['none', 'stereo', '3d']
    # Haptic mode choice indices -> stored values.
    _HAPTIC_MODE_VALUES = ['sync', 'discrete', 'off']

    def __init__(self, *args, component_manager=None, **kw):
        super(SettingsFrame, self).__init__(*args, **kw)

        self.settings = load_settings()
        self.component_manager = component_manager

        # Debounce timers for sliders to prevent hangs
        self.rate_timer = None
        self.pitch_timer = None
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
                _title = self.GetTitle()
            except RuntimeError:
                print("[SettingsFrame] WARNING: Frame has been destroyed, cannot show")
                return False

            print("[SettingsFrame] >>>>> Show() called - forcing category refresh <<<<<")
            # Always refresh categories before showing
            try:
                # Re-read from disk so changes made elsewhere while this window
                # was hidden (quick settings, buffer engine settings, 3D
                # calibration) are reflected instead of a stale snapshot.
                self.settings = load_settings()
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

        # Register/unregister in window switcher
        try:
            from src.ui.window_switcher import register_window, unregister_window
            if show and result:
                register_window(_("Settings"), window=self, category='app')
            elif not show:
                unregister_window(_("Settings"))
        except Exception:
            pass

        # Set focus to category list when showing the window
        if show and result:
            try:
                self.category_list.SetFocus()
                print("[SettingsFrame] Focus set to category list")
            except (RuntimeError, AttributeError) as e:
                print(f"[SettingsFrame] Could not set focus to category list: {e}")

        return result

    def _gamepad_connected(self):
        """Return True if at least one game controller is currently connected."""
        try:
            import pygame
            if not pygame.get_init():
                pygame.init()
            if not pygame.joystick.get_init():
                pygame.joystick.init()
            pygame.event.pump()
            return pygame.joystick.get_count() > 0
        except Exception as e:
            print(f"[SettingsFrame] Gamepad detection failed: {e}")
            return False

    def _sync_controller_category(self):
        """Show the Game controller category only while a gamepad is connected."""
        name = _("Game controller")
        connected = self._gamepad_connected()
        registered = name in self.categories

        if connected and not registered:
            self.categories[name] = self.controller_panel
            self.category_order.append(name)
            self.controller_panel.Hide()
            print("[SettingsFrame] Gamepad present - added Game controller category")
        elif not connected and registered:
            del self.categories[name]
            if name in self.category_order:
                self.category_order.remove(name)
            if self.current_category_panel is self.controller_panel:
                self.controller_panel.Hide()
                self.current_category_panel = None
            print("[SettingsFrame] No gamepad - removed Game controller category")

    def force_rebuild_categories(self):
        """Force complete rebuild of category list"""
        print("[SettingsFrame] ***** FORCE REBUILD STARTING *****")

        # Add/remove the Game controller category based on live gamepad presence.
        self._sync_controller_category()

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

        category_list_label = wx.StaticText(left_panel, label=_("Settings category"))
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
        # Game controller panel is built up-front but only registered as a
        # category while a gamepad is connected (see _sync_controller_category).
        self.controller_panel = wx.Panel(self.content_panel)

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

        # Titan-Net category (only if credentials are configured)
        self._titan_net_available = False
        try:
            from src.settings.titan_im_config import load_titan_im_config
            im_config = load_titan_im_config()
            if im_config.get('titannet_username') and im_config.get('titannet_autologin'):
                self._titan_net_available = True
                self.titan_net_panel = wx.Panel(self.content_panel)
                self.register_category(_("Titan-Net"), self.titan_net_panel)
        except Exception as e:
            print(f"[SettingsFrame] Titan-Net category not available: {e}")

        # Initialize panels
        self.InitGeneralPanel()
        self.InitSoundPanel()
        self.InitInterfacePanel()
        self.InitInvisibleInterfacePanel()
        self.InitEnvironmentPanel()
        self.InitSystemMonitorPanel()
        self.InitStereoSpeechPanel()
        self.InitControllerPanel()

        if sys.platform == 'win32':
            self.InitWindowsPanel()

        if self._titan_net_available:
            self.InitTitanNetPanel()

        # Register the Game controller category now if a pad is already present.
        self._sync_controller_category()

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

    def open_at_category(self, category_name):
        """Show the settings window pre-selected on ``category_name``.

        Used by components (e.g. the Titan Access screen-reader menu) that want
        to jump the user straight to their own settings category. Falls back to
        simply showing the window if the category is not registered. Must be
        called on the GUI thread (wrap with wx.CallAfter from worker threads).
        """
        if not self.Show(True):
            return False
        try:
            self.Raise()
        except Exception:
            pass
        # force_rebuild_categories() ran inside Show(); the category list is now
        # in sync with category_order, so select by index and show the panel.
        try:
            if category_name in self.category_order:
                idx = self.category_order.index(category_name)
                self.category_list.SetSelection(idx)
                self.ShowCategory(category_name)
                self.category_list.SetFocus()
                return True
        except Exception as e:
            print(f"[SettingsFrame] open_at_category error: {e}")
        return True

    def InitSoundPanel(self):
        panel = self.sound_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        theme_label = wx.StaticText(panel, label=_("Select sound theme:"))
        vbox.Add(theme_label, flag=wx.LEFT | wx.TOP, border=10)

        self.theme_choice = wx.Choice(panel)
        self.theme_choice.Bind(wx.EVT_CHOICE, self.OnThemeSelected)
        self.theme_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)

        themes = []
        try:
            from src.titan_core.sound import get_available_sfx_themes
            themes = get_available_sfx_themes()
        except Exception:
            if os.path.exists(SFX_DIR):
                themes = [d for d in os.listdir(SFX_DIR)
                          if os.path.isdir(os.path.join(SFX_DIR, d))]
            else:
                print(f"WARNING: SFX directory does not exist: {SFX_DIR}. No sound themes to choose from.")

        if not themes:
             themes = [_("No themes")]
             self.theme_choice.Enable(False)

        self.theme_choice.AppendItems(themes)
        vbox.Add(self.theme_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # Sound positioning mode: None / Stereo / 3D (HRTF virtual surround).
        # Governs left/right (and, in 3D, up/down) placement of UI sounds and Titan TTS.
        sound_mode_label = wx.StaticText(panel, label=_("Sound positioning mode:"))
        vbox.Add(sound_mode_label, flag=wx.LEFT | wx.TOP, border=10)

        self.sound_mode_choice = wx.Choice(panel)
        self.sound_mode_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.sound_mode_choice.Bind(wx.EVT_CHOICE, self.OnSoundModeChanged)
        # Index order maps to _SOUND_MODE_VALUES below.
        self.sound_mode_choice.AppendItems([_("None"), _("Stereo"), _("3D")])
        vbox.Add(self.sound_mode_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # 3D room calibration: measures the room's echo and applies a matching
        # reverb. The button toggles between calibrating and removing the saved
        # profile, and is only shown while the 3D mode is selected.
        self.calibrate_3d_btn = wx.Button(panel, label=_("Calibrate 3D sound"))
        self.calibrate_3d_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.calibrate_3d_btn.Bind(wx.EVT_BUTTON, self.OnCalibrate3D)
        vbox.Add(self.calibrate_3d_btn, flag=wx.LEFT | wx.TOP, border=10)
        self._update_calibrate_button()

        self.use_skin_sound_theme_cb = wx.CheckBox(panel, label=_("Use skin's sound theme"))
        self.use_skin_sound_theme_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.use_skin_sound_theme_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.use_skin_sound_theme_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.fallback_to_default_theme_cb = wx.CheckBox(panel, label=_("Use equivalent from default theme when a sound is unavailable in the selected sound theme"))
        self.fallback_to_default_theme_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.fallback_to_default_theme_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.fallback_to_default_theme_cb, flag=wx.LEFT | wx.TOP, border=10)

        volume_label_text = _("Sound theme volume:")
        volume_label = wx.StaticText(panel, label=volume_label_text)
        vbox.Add(volume_label, flag=wx.LEFT | wx.TOP, border=10)

        self.theme_volume_slider = wx.Slider(panel, value=100, minValue=0, maxValue=100,
                                              style=wx.SL_HORIZONTAL)
        self.theme_volume_slider.SetLabel(volume_label_text)
        self.theme_volume_slider.Bind(wx.EVT_SLIDER, self.OnThemeVolumeChange)
        self.theme_volume_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.theme_volume_slider, flag=wx.LEFT | wx.EXPAND, border=10)

        panel.SetSizer(vbox)
        panel.Layout()

    def InitControllerPanel(self):
        """Game controller settings (vibration / haptics). Shown only when a pad
        is connected; see _sync_controller_category."""
        panel = self.controller_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Controller vibration mode.
        # Audio-synced rumble follows each sound's loudness (like phone haptics);
        # discrete fires fixed pulses per UI event; off disables vibration.
        haptic_label = wx.StaticText(panel, label=_("Controller vibration:"))
        vbox.Add(haptic_label, flag=wx.LEFT | wx.TOP, border=10)

        self.haptic_mode_choice = wx.Choice(panel)
        self.haptic_mode_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.haptic_mode_choice.Bind(wx.EVT_CHOICE, self.OnHapticModeChanged)
        # Index order maps to _HAPTIC_MODE_VALUES.
        self.haptic_mode_choice.AppendItems([_("Audio-synced"), _("Discrete pulses"), _("Off")])
        vbox.Add(self.haptic_mode_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        haptic_strength_text = _("Vibration strength:")
        haptic_strength_label = wx.StaticText(panel, label=haptic_strength_text)
        vbox.Add(haptic_strength_label, flag=wx.LEFT | wx.TOP, border=10)

        self.haptic_strength_slider = wx.Slider(panel, value=80, minValue=0, maxValue=100,
                                                style=wx.SL_HORIZONTAL)
        self.haptic_strength_slider.SetLabel(haptic_strength_text)
        self.haptic_strength_slider.Bind(wx.EVT_SLIDER, self.OnHapticStrengthChange)
        self.haptic_strength_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.haptic_strength_slider, flag=wx.LEFT | wx.EXPAND, border=10)

        self.haptic_test_btn = wx.Button(panel, label=_("Test vibration"))
        self.haptic_test_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.haptic_test_btn.Bind(wx.EVT_BUTTON, self.OnTestVibration)
        vbox.Add(self.haptic_test_btn, flag=wx.LEFT | wx.TOP, border=10)

        # Experimental accessibility option: feel spoken text as controller
        # rumble. Aimed at deaf / hard-of-hearing users; off by default and works
        # regardless of the vibration mode above.
        self.speech_haptic_sync_cb = wx.CheckBox(
            panel,
            label=_("Synchronize vibration with speech, for deaf and hard of hearing (experimental)"))
        self.speech_haptic_sync_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.speech_haptic_sync_cb.Bind(wx.EVT_CHECKBOX, self.OnSpeechHapticSyncChanged)
        vbox.Add(self.speech_haptic_sync_cb, flag=wx.LEFT | wx.TOP, border=10)

        panel.SetSizer(vbox)
        panel.Layout()
        # This panel is registered as a category manually (see
        # _sync_controller_category), so it never goes through register_category,
        # which is what hides every other panel. Hide it here explicitly -
        # otherwise it stays shown and overlaps whatever category is selected
        # (the "controller settings appear everywhere" bug).
        panel.Hide()

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
        self.startup_mode_choice.Bind(wx.EVT_CHOICE, self.OnStartupModeChanged)
        startup_modes = [_("Normal (Graphical interface)"), _("Minimized (Invisible interface)"), _("Classic Mode"), _("Custom")]
        self.startup_mode_choice.AppendItems(startup_modes)
        vbox.Add(self.startup_mode_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # Add a small spacer
        vbox.AddSpacer(10)

        # --- Launcher selection (visible when Custom mode is selected) ---
        self.launcher_label = wx.StaticText(self.general_panel, label=_("Available launchers:"))
        vbox.Add(self.launcher_label, flag=wx.LEFT | wx.TOP, border=10)

        self.launcher_listbox = wx.ListBox(self.general_panel)
        self.launcher_listbox.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.launcher_listbox.Bind(wx.EVT_LISTBOX, self.OnLauncherSelected)
        vbox.Add(self.launcher_listbox, flag=wx.LEFT | wx.EXPAND, border=10)

        self.launcher_desc_label = wx.StaticText(self.general_panel, label=_("Launcher description:"))
        vbox.Add(self.launcher_desc_label, flag=wx.LEFT | wx.TOP, border=10)

        self.launcher_description = wx.TextCtrl(self.general_panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 80))
        self.launcher_description.SetLabel(_("Launcher description:"))
        vbox.Add(self.launcher_description, flag=wx.LEFT | wx.EXPAND, border=10)

        # Populate launcher list
        self._launcher_configs = []
        try:
            from src.titan_core.launcher_manager import LauncherManager
            lm = LauncherManager()
            self._launcher_configs = lm.get_available_launchers()
            for lc in self._launcher_configs:
                self.launcher_listbox.Append(lc.name)
        except Exception as e:
            print(f"[SettingsFrame] Error loading launchers: {e}")

        # --- Categories checklist (visible when GUI/IUI/Klango is selected) ---
        self.categories_label = wx.StaticText(self.general_panel, label=_("Categories:"))
        vbox.Add(self.categories_label, flag=wx.LEFT | wx.TOP, border=10)

        self._category_ids = ['apps', 'games', 'network']
        category_names = [_("Applications"), _("Games"), _("Titan IM")]
        self.categories_checklist = wx.CheckListBox(self.general_panel, choices=category_names)
        self.categories_checklist.SetLabel(_("Categories:"))
        self.categories_checklist.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.categories_checklist.Bind(wx.EVT_CHECKLISTBOX, self.OnCategoryChecklistToggle)
        self.categories_checklist.Bind(wx.EVT_LISTBOX, self.OnCategoryChecklistSelect)
        self._categories_last_announced_idx = -1
        # Default: all checked
        for i in range(len(category_names)):
            self.categories_checklist.Check(i, True)
        vbox.Add(self.categories_checklist, flag=wx.LEFT | wx.EXPAND, border=10)

        vbox.AddSpacer(10)

        # Initially hide launcher controls (default mode is normal)
        self.launcher_label.Hide()
        self.launcher_listbox.Hide()
        self.launcher_desc_label.Hide()
        self.launcher_description.Hide()

        self.quick_start_cb = wx.CheckBox(self.general_panel, label=_("Quick start"))
        self.quick_start_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.quick_start_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.quick_start_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.confirm_exit_cb = wx.CheckBox(self.general_panel, label=_("Confirm exit from Titan"))
        self.confirm_exit_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.confirm_exit_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.confirm_exit_cb, flag=wx.LEFT | wx.TOP, border=10)

        vbox.AddSpacer(10)

        # When TCE is minimized
        self._minimize_action_values = ['tray', 'invisible_ui', 'nothing']
        minimize_choices = [
            _("Minimize to system tray"),
            _("Enable invisible interface"),
            _("Nothing"),
        ]
        self.minimize_action_radio = wx.RadioBox(
            self.general_panel,
            label=_("When TCE is minimized:"),
            choices=minimize_choices,
            majorDimension=1,
            style=wx.RA_SPECIFY_COLS,
        )
        self.minimize_action_radio.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.minimize_action_radio.Bind(wx.EVT_RADIOBOX, self.OnRadioBox)
        vbox.Add(self.minimize_action_radio, flag=wx.LEFT | wx.TOP | wx.EXPAND, border=10)

        # Alt+F4 keyboard shortcut
        self._alt_f4_action_values = ['close', 'tray']
        alt_f4_choices = [
            _("Close environment"),
            _("Minimize to system tray"),
        ]
        self.alt_f4_action_radio = wx.RadioBox(
            self.general_panel,
            label=_("Alt+F4 keyboard shortcut:"),
            choices=alt_f4_choices,
            majorDimension=1,
            style=wx.RA_SPECIFY_COLS,
        )
        self.alt_f4_action_radio.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.alt_f4_action_radio.Bind(wx.EVT_RADIOBOX, self.OnRadioBox)
        vbox.Add(self.alt_f4_action_radio, flag=wx.LEFT | wx.TOP | wx.EXPAND, border=10)

        # Titan UI key
        self._titan_ui_key_value = 'grave'
        self.titan_ui_key_btn = wx.Button(
            self.general_panel,
            label=_("Titan UI key: {}").format(self._format_titan_ui_key(self._titan_ui_key_value)),
        )
        self.titan_ui_key_btn.Bind(wx.EVT_BUTTON, self.OnCaptureTitanUIKey)
        self.titan_ui_key_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.titan_ui_key_btn, flag=wx.LEFT | wx.TOP | wx.EXPAND, border=10)

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

        if sys.platform == 'win32':
            self.register_titan_tts_sapi_cb = wx.CheckBox(self.environment_panel, label=_("Register Titan TTS as SAPI5 voice"))
            self.register_titan_tts_sapi_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
            self.register_titan_tts_sapi_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
            vbox.Add(self.register_titan_tts_sapi_cb, flag=wx.LEFT | wx.TOP, border=10)
        else:
            self.register_titan_tts_sapi_cb = None

        # Copilot key remapping (Windows only, when Copilot key detected)
        self.copilot_remap_cb = None
        self.copilot_key_choice = None
        if sys.platform == 'win32':
            try:
                from src.system.copilot_key import detect_copilot_key, REPLACEMENT_KEYS
                if detect_copilot_key():
                    self.copilot_remap_cb = wx.CheckBox(self.environment_panel, label=_("Replace Copilot key"))
                    self.copilot_remap_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
                    self.copilot_remap_cb.Bind(wx.EVT_CHECKBOX, self.OnCopilotRemapChanged)
                    vbox.Add(self.copilot_remap_cb, flag=wx.LEFT | wx.TOP, border=10)

                    self.copilot_key_choice = wx.Choice(self.environment_panel)
                    self.copilot_key_choice.SetLabel(_("Replacement key"))
                    for _vk, name in REPLACEMENT_KEYS:
                        self.copilot_key_choice.Append(_(name))
                    self.copilot_key_choice.SetSelection(0)
                    self.copilot_key_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
                    self.copilot_key_choice.Bind(wx.EVT_CHOICE, self.OnCopilotKeyChoiceChanged)
                    self.copilot_key_choice.Enable(False)
                    vbox.Add(self.copilot_key_choice, flag=wx.LEFT | wx.EXPAND | wx.TOP, border=10)
            except Exception as e:
                print(f"[Settings] Copilot key detection error: {e}")

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

        # Low and critical battery alerts
        self.monitor_battery_alerts_cb = wx.CheckBox(panel, label=_("Announce low and critical battery levels"))
        self.monitor_battery_alerts_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.monitor_battery_alerts_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.monitor_battery_alerts_cb, flag=wx.LEFT | wx.TOP, border=10)

        battery_low_label = wx.StaticText(panel, label=_("Low battery level:"))
        vbox.Add(battery_low_label, flag=wx.LEFT | wx.TOP, border=10)

        self.battery_low_choice = wx.Choice(panel)
        self.battery_low_options = ['10%', '15%', '20%', '25%', '30%']
        self.battery_low_choice.AppendItems(self.battery_low_options)
        self.battery_low_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.battery_low_choice, flag=wx.LEFT | wx.EXPAND, border=10)

        # Low battery sound selection (previews the sound on selection)
        battery_low_sound_label = wx.StaticText(panel, label=_("Low battery sound:"))
        vbox.Add(battery_low_sound_label, flag=wx.LEFT | wx.TOP, border=10)

        self.battery_low_sound_list = wx.ListBox(panel)
        # (value, display label, preview sound file)
        self.battery_low_sound_options = [
            ('random', _("Random"), None),
            ('external', _("External"), 'system/low_battery1.ogg'),
            ('internal', _("Internal"), 'system/low_battery2.ogg'),
        ]
        self.battery_low_sound_list.AppendItems([label for _v, label, _s in self.battery_low_sound_options])
        self.battery_low_sound_list.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.battery_low_sound_list.Bind(wx.EVT_LISTBOX, self.OnBatteryLowSoundSelect)
        vbox.Add(self.battery_low_sound_list, flag=wx.LEFT | wx.EXPAND, border=10)

        battery_critical_label = wx.StaticText(panel, label=_("Critical battery level:"))
        vbox.Add(battery_critical_label, flag=wx.LEFT | wx.TOP, border=10)

        self.battery_critical_choice = wx.Choice(panel)
        self.battery_critical_options = ['3%', '5%', '7%', '10%']
        self.battery_critical_choice.AppendItems(self.battery_critical_options)
        self.battery_critical_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.battery_critical_choice, flag=wx.LEFT | wx.EXPAND, border=10)

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
                                       style=wx.SL_HORIZONTAL)
        self.volume_slider.SetLabel(volume_label_text)
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

    def InitTitanNetPanel(self):
        """Initialize Titan-Net settings panel with server configuration, audio business card, and notifications."""
        panel = self.titan_net_panel
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Server Configuration section
        server_group = wx.StaticBox(panel, label=_("Server Configuration"))
        server_sizer = wx.StaticBoxSizer(server_group, wx.VERTICAL)

        # Server Host
        host_hbox = wx.BoxSizer(wx.HORIZONTAL)
        host_label = wx.StaticText(panel, label=_("Server host:"))
        host_hbox.Add(host_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.server_host_ctrl = wx.TextCtrl(panel)
        self.server_host_ctrl.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        host_hbox.Add(self.server_host_ctrl, 1, wx.EXPAND)
        server_sizer.Add(host_hbox, 0, wx.EXPAND | wx.ALL, 5)

        # Ports
        ports_hbox = wx.BoxSizer(wx.HORIZONTAL)
        
        # WebSocket Port
        ws_port_label = wx.StaticText(panel, label=_("WebSocket port:"))
        ports_hbox.Add(ws_port_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.server_port_ctrl = wx.TextCtrl(panel)
        self.server_port_ctrl.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        ports_hbox.Add(self.server_port_ctrl, 1, wx.EXPAND | wx.RIGHT, 10)

        # HTTP Port
        http_port_label = wx.StaticText(panel, label=_("HTTP port:"))
        ports_hbox.Add(http_port_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.http_port_ctrl = wx.TextCtrl(panel)
        self.http_port_ctrl.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        ports_hbox.Add(self.http_port_ctrl, 1, wx.EXPAND)
        
        server_sizer.Add(ports_hbox, 0, wx.EXPAND | wx.ALL, 5)
        
        vbox.Add(server_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # Description
        desc_text = _("Audio business card allows you to personalize sounds that other users hear when you log in, send a message, or view your profile.")
        desc_label = wx.StaticText(panel, label=desc_text)
        desc_label.Wrap(500)
        vbox.Add(desc_label, flag=wx.LEFT | wx.TOP | wx.RIGHT, border=10)

        vbox.AddSpacer(10)

        # Business card enable checkbox
        self.business_card_cb = wx.CheckBox(panel, label=_("Custom business card"))
        self.business_card_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.business_card_cb.Bind(wx.EVT_CHECKBOX, self.OnBusinessCardToggle)
        vbox.Add(self.business_card_cb, flag=wx.LEFT | wx.TOP, border=10)

        vbox.AddSpacer(5)

        # Sound file wildcards
        self._audio_wildcard = _("Audio files") + " (*.wav;*.ogg;*.mp3)|*.wav;*.ogg;*.mp3"
        self._avatar_wildcard = _("Audio files") + " (*.wav;*.ogg)|*.wav;*.ogg"

        # Store selected paths
        self._sound_paths = {
            'login': '',
            'logout': '',
            'new_message': '',
            'avatar': '',
        }

        # Login sound
        self.login_sound_btn = wx.Button(panel, label=_("Login sound"))
        self.login_sound_btn.Bind(wx.EVT_BUTTON, lambda e: self._browse_sound('login', self._audio_wildcard))
        self.login_sound_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.login_sound_btn, flag=wx.LEFT | wx.TOP | wx.EXPAND, border=10)

        # Logout sound
        self.logout_sound_btn = wx.Button(panel, label=_("Logout sound"))
        self.logout_sound_btn.Bind(wx.EVT_BUTTON, lambda e: self._browse_sound('logout', self._audio_wildcard))
        self.logout_sound_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.logout_sound_btn, flag=wx.LEFT | wx.TOP | wx.EXPAND, border=10)

        # New message sound
        self.new_message_sound_btn = wx.Button(panel, label=_("New message sound"))
        self.new_message_sound_btn.Bind(wx.EVT_BUTTON, lambda e: self._browse_sound('new_message', self._audio_wildcard))
        self.new_message_sound_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.new_message_sound_btn, flag=wx.LEFT | wx.TOP | wx.EXPAND, border=10)

        # Avatar audio
        self.avatar_sound_btn = wx.Button(panel, label=_("Avatar audio"))
        self.avatar_sound_btn.Bind(wx.EVT_BUTTON, lambda e: self._browse_sound('avatar', self._avatar_wildcard))
        self.avatar_sound_btn.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.avatar_sound_btn, flag=wx.LEFT | wx.TOP | wx.EXPAND, border=10)

        # Store references for enable/disable
        self._business_card_controls = [
            self.login_sound_btn,
            self.logout_sound_btn,
            self.new_message_sound_btn,
            self.avatar_sound_btn,
        ]
        # Initially disabled
        for ctrl in self._business_card_controls:
            ctrl.Enable(False)

        vbox.AddSpacer(15)

        # Notification checkboxes
        self.notify_login_logout_cb = wx.CheckBox(panel, label=_("Notify on user login/logout"))
        self.notify_login_logout_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.notify_login_logout_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.notify_login_logout_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.notify_new_apps_cb = wx.CheckBox(panel, label=_("Notify on new applications"))
        self.notify_new_apps_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.notify_new_apps_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.notify_new_apps_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.notify_private_msg_cb = wx.CheckBox(panel, label=_("Notify on new private messages"))
        self.notify_private_msg_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.notify_private_msg_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.notify_private_msg_cb, flag=wx.LEFT | wx.TOP, border=10)

        self.notify_chat_msg_cb = wx.CheckBox(panel, label=_("Notify on new chat messages"))
        self.notify_chat_msg_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.notify_chat_msg_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        vbox.Add(self.notify_chat_msg_cb, flag=wx.LEFT | wx.TOP, border=10)

        panel.SetSizer(vbox)
        panel.Layout()

    def OnBusinessCardToggle(self, event):
        """Enable/disable business card controls."""
        enabled = self.business_card_cb.GetValue()
        for ctrl in self._business_card_controls:
            ctrl.Enable(enabled)
        if not self.is_initializing:
            play_sound('ui/switch_category.ogg')

    def _browse_sound(self, sound_type, wildcard):
        """Open file dialog for selecting a business card sound."""
        max_sec = 30 if sound_type == 'avatar' else 9
        btn_labels = {
            'login': _("Login sound"),
            'logout': _("Logout sound"),
            'new_message': _("New message sound"),
            'avatar': _("Avatar audio"),
        }
        title = btn_labels.get(sound_type, sound_type) + f" (max {max_sec}s)"
        dlg = wx.FileDialog(self, title, wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            if not self._validate_audio_duration(path, max_sec):
                _show_skinned_message(
                    _("The file '{}' exceeds the maximum duration of {} seconds.").format(
                        os.path.basename(path), max_sec),
                    _("Error"), wx.OK | wx.ICON_ERROR)
                dlg.Destroy()
                return
            self._sound_paths[sound_type] = path
            # Update button label to show selected filename
            btn = {
                'login': self.login_sound_btn,
                'logout': self.logout_sound_btn,
                'new_message': self.new_message_sound_btn,
                'avatar': self.avatar_sound_btn,
            }[sound_type]
            btn.SetLabel(f"{btn_labels[sound_type]}: {os.path.basename(path)}")
            play_sound('ui/switch_category.ogg')
        dlg.Destroy()

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
                                     style=wx.SL_HORIZONTAL)
        self.rate_slider.SetLabel(_("Speech rate"))
        self.rate_slider.Bind(wx.EVT_SLIDER, self.OnRateChanged)
        self.rate_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.rate_slider, flag=wx.LEFT | wx.EXPAND, border=10)

        # Pitch slider
        pitch_label = wx.StaticText(panel, label=_("Pitch:"))
        vbox.Add(pitch_label, flag=wx.LEFT | wx.TOP, border=10)

        self.pitch_slider = wx.Slider(panel, value=0, minValue=-10, maxValue=10,
                                      style=wx.SL_HORIZONTAL)
        self.pitch_slider.SetLabel(_("Pitch"))
        self.pitch_slider.Bind(wx.EVT_SLIDER, self.OnPitchChanged)
        self.pitch_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.pitch_slider, flag=wx.LEFT | wx.EXPAND, border=10)

        # Volume slider
        volume_label = wx.StaticText(panel, label=_("Speech volume:"))
        vbox.Add(volume_label, flag=wx.LEFT | wx.TOP, border=10)

        self.speech_volume_slider = wx.Slider(panel, value=100, minValue=0, maxValue=100,
                                              style=wx.SL_HORIZONTAL)
        self.speech_volume_slider.SetLabel(_("Speech volume"))
        self.speech_volume_slider.Bind(wx.EVT_SLIDER, self.OnSpeechVolumeChanged)
        self.speech_volume_slider.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        vbox.Add(self.speech_volume_slider, flag=wx.LEFT | wx.EXPAND, border=10)

        # --- Dynamic engine config controls (rendered from engine.get_config_fields()) ---
        self._engine_config_sizer = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self._engine_config_sizer, flag=wx.LEFT | wx.EXPAND, border=10)
        self._engine_config_controls = {}  # key -> (label_widget, value_widget, field_descriptor)

        # Legacy attributes for backward compatibility
        self.elevenlabs_api_key_label = None
        self.elevenlabs_api_key_ctrl = None

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

        # Sound mode (none/stereo/3d). Migrate from legacy stereo_sound /
        # stereo_speech when the new key is absent, mirroring sound.get_sound_mode().
        mode = str(sound_settings.get('sound_mode', '')).strip().lower()
        if mode not in self._SOUND_MODE_VALUES:
            legacy_stereo = str(sound_settings.get('stereo_sound', 'False')).lower() in ['true', '1']
            legacy_speech = str(self.settings.get('invisible_interface', {}).get(
                'stereo_speech', 'False')).lower() in ['true', '1']
            mode = 'stereo' if (legacy_stereo or legacy_speech) else 'none'
        self.sound_mode_choice.SetSelection(self._SOUND_MODE_VALUES.index(mode))
        self._update_calibrate_button()

        use_skin_sound_theme_value = sound_settings.get('use_skin_sound_theme', 'False')
        self.use_skin_sound_theme_cb.SetValue(str(use_skin_sound_theme_value).lower() in ['true', '1'])

        fallback_to_default_theme_value = sound_settings.get('fallback_to_default_theme', 'False')
        self.fallback_to_default_theme_cb.SetValue(str(fallback_to_default_theme_value).lower() in ['true', '1'])

        theme_volume_value = sound_settings.get('theme_volume', '100')
        self.theme_volume_slider.SetValue(int(theme_volume_value))
        set_sound_theme_volume(int(theme_volume_value))

        # Game controller (vibration) settings - widgets always exist even when
        # the category is hidden, so populate them unconditionally.
        controller_settings = self.settings.get('controller', {})
        haptic_mode = str(controller_settings.get('haptic_mode', 'sync')).lower()
        if haptic_mode not in self._HAPTIC_MODE_VALUES:
            haptic_mode = 'sync'
        self.haptic_mode_choice.SetSelection(self._HAPTIC_MODE_VALUES.index(haptic_mode))
        try:
            strength_pct = int(round(float(controller_settings.get('vibration_strength', '0.8')) * 100))
        except (TypeError, ValueError):
            strength_pct = 80
        self.haptic_strength_slider.SetValue(max(0, min(100, strength_pct)))
        speech_haptic_value = controller_settings.get('speech_haptic_sync', 'False')
        self.speech_haptic_sync_cb.SetValue(str(speech_haptic_value).lower() in ['true', '1'])

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
        elif startup_mode_value == 'launcher':
            self.startup_mode_choice.SetSelection(3)
        else:
            self.startup_mode_choice.SetSelection(0)

        # Load launcher selection
        saved_launcher = general_settings.get('launcher', '')
        if saved_launcher:
            for i, lc in enumerate(self._launcher_configs):
                if lc.folder_name == saved_launcher:
                    self.launcher_listbox.SetSelection(i)
                    self.launcher_description.SetValue(lc.description or _("No description available."))
                    break

        # Load minimize action
        minimize_action_value = general_settings.get('minimize_action', 'invisible_ui')
        if minimize_action_value not in self._minimize_action_values:
            minimize_action_value = 'invisible_ui'
        self.minimize_action_radio.SetSelection(
            self._minimize_action_values.index(minimize_action_value))

        # Load Alt+F4 action
        alt_f4_action_value = general_settings.get('alt_f4_action', 'close')
        if alt_f4_action_value not in self._alt_f4_action_values:
            alt_f4_action_value = 'close'
        self.alt_f4_action_radio.SetSelection(
            self._alt_f4_action_values.index(alt_f4_action_value))

        # Load Titan UI key
        self._titan_ui_key_value = general_settings.get('titan_ui_key', 'grave') or 'grave'
        self.titan_ui_key_btn.SetLabel(
            _("Titan UI key: {}").format(self._format_titan_ui_key(self._titan_ui_key_value)))

        # Load visible categories
        visible_cats = general_settings.get('visible_categories', 'apps,games,network')
        cat_list = [c.strip() for c in visible_cats.split(',')]
        for i, cat_id in enumerate(self._category_ids):
            self.categories_checklist.Check(i, cat_id in cat_list)

        # Show/hide conditional UI based on startup mode
        is_custom = (startup_mode_value == 'launcher')
        self.launcher_label.Show(is_custom)
        self.launcher_listbox.Show(is_custom)
        self.launcher_desc_label.Show(is_custom)
        self.launcher_description.Show(is_custom)
        self.categories_label.Show(not is_custom)
        self.categories_checklist.Show(not is_custom)
        self.general_panel.Layout()

        interface_settings = self.settings.get('interface', {})
        current_skin = interface_settings.get('skin', _('Default'))
        # Also accept legacy Polish skin name
        if current_skin == 'Domyślna':
            current_skin = _('Default')
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
        if self.register_titan_tts_sapi_cb is not None:
            self.register_titan_tts_sapi_cb.SetValue(str(environment_settings.get('register_titan_tts_sapi', 'False')).lower() in ['true', '1'])

        # Copilot key settings
        if self.copilot_remap_cb is not None:
            enabled = str(environment_settings.get('copilot_remap', 'False')).lower() in ['true', '1']
            self.copilot_remap_cb.SetValue(enabled)
            self.copilot_key_choice.Enable(enabled)
            copilot_key_vk = int(environment_settings.get('copilot_replacement_vk', '0'))
            if copilot_key_vk and self.copilot_key_choice is not None:
                from src.system.copilot_key import REPLACEMENT_KEYS
                for idx, (vk, _name) in enumerate(REPLACEMENT_KEYS):
                    if vk == copilot_key_vk:
                        self.copilot_key_choice.SetSelection(idx)
                        break

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

        # Low and critical battery alerts
        self.monitor_battery_alerts_cb.SetValue(str(system_monitor_settings.get('monitor_battery_alerts', 'True')).lower() in ['true', '1'])

        low_value = '{}%'.format(system_monitor_settings.get('battery_low_threshold', 20))
        if low_value in self.battery_low_options:
            self.battery_low_choice.SetSelection(self.battery_low_options.index(low_value))
        else:
            self.battery_low_choice.SetSelection(self.battery_low_options.index('20%'))

        critical_value = '{}%'.format(system_monitor_settings.get('battery_critical_threshold', 5))
        if critical_value in self.battery_critical_options:
            self.battery_critical_choice.SetSelection(self.battery_critical_options.index(critical_value))
        else:
            self.battery_critical_choice.SetSelection(self.battery_critical_options.index('5%'))

        # Low battery sound selection
        low_sound_value = str(system_monitor_settings.get('battery_low_sound', 'random'))
        low_sound_values = [v for v, _l, _s in self.battery_low_sound_options]
        if low_sound_value in low_sound_values:
            self.battery_low_sound_list.SetSelection(low_sound_values.index(low_sound_value))
        else:
            self.battery_low_sound_list.SetSelection(low_sound_values.index('random'))

        # Load stereo speech settings
        self.load_stereo_speech_settings()

        if hasattr(self, 'windows_panel'):
            windows_settings = self.settings.get('windows', {})
            mute_disabled = windows_settings.get('disable_mute_on_start', 'False')
            self.mute_checkbox.SetValue(str(mute_disabled).lower() in ['true', '1'])
            # Loading initial volume is now in InitWindowsPanel using pycaw

        # Load Titan-Net settings
        if self._titan_net_available:
            self.load_titan_net_settings()

    def load_titan_net_settings(self):
        """Load Titan-Net settings from titan_im_config."""
        try:
            from src.settings.titan_im_config import load_titan_im_config
            config = load_titan_im_config()
            tn = config.get('titannet_settings', {})

            # Load Server Configuration
            self.server_host_ctrl.SetValue(tn.get('server_host', 'titosofttitan.com'))
            self.server_port_ctrl.SetValue(str(tn.get('server_port', 8001)))
            self.http_port_ctrl.SetValue(str(tn.get('http_port', 8000)))

            self.business_card_cb.SetValue(tn.get('business_card_enabled', False))
            # Enable/disable file pickers based on business card state
            enabled = self.business_card_cb.GetValue()
            for ctrl in self._business_card_controls:
                ctrl.Enable(enabled)

            # Load saved sound paths and update button labels
            btn_labels = {
                'login': (_("Login sound"), self.login_sound_btn),
                'logout': (_("Logout sound"), self.logout_sound_btn),
                'new_message': (_("New message sound"), self.new_message_sound_btn),
                'avatar': (_("Avatar audio"), self.avatar_sound_btn),
            }
            for key, config_key in [('login', 'login_sound_path'), ('logout', 'logout_sound_path'),
                                     ('new_message', 'new_message_sound_path'), ('avatar', 'avatar_sound_path')]:
                path = tn.get(config_key, '')
                if path:
                    self._sound_paths[key] = path
                    label, btn = btn_labels[key]
                    btn.SetLabel(f"{label}: {os.path.basename(path)}")

            # Notification checkboxes
            self.notify_login_logout_cb.SetValue(tn.get('notify_login_logout', True))
            self.notify_new_apps_cb.SetValue(tn.get('notify_new_apps', True))
            self.notify_private_msg_cb.SetValue(tn.get('notify_private_messages', True))
            self.notify_chat_msg_cb.SetValue(tn.get('notify_chat_messages', True))
        except Exception as e:
            print(f"[SettingsFrame] Error loading Titan-Net settings: {e}")

    def save_titan_net_settings(self):
        """Save Titan-Net settings to titan_im_config and upload sounds to server."""
        try:
            from src.settings.titan_im_config import load_titan_im_config, save_titan_im_config

            config = load_titan_im_config()

            # Validate ports
            try:
                server_port = int(self.server_port_ctrl.GetValue())
                http_port = int(self.http_port_ctrl.GetValue())
            except ValueError:
                server_port = 8001
                http_port = 8000

            tn_settings = {
                'server_host': self.server_host_ctrl.GetValue().strip() or 'titosofttitan.com',
                'server_port': server_port,
                'http_port': http_port,
                'business_card_enabled': self.business_card_cb.GetValue(),
                'login_sound_path': self._sound_paths.get('login', ''),
                'logout_sound_path': self._sound_paths.get('logout', ''),
                'new_message_sound_path': self._sound_paths.get('new_message', ''),
                'avatar_sound_path': self._sound_paths.get('avatar', ''),
                'notify_login_logout': self.notify_login_logout_cb.GetValue(),
                'notify_new_apps': self.notify_new_apps_cb.GetValue(),
                'notify_private_messages': self.notify_private_msg_cb.GetValue(),
                'notify_chat_messages': self.notify_chat_msg_cb.GetValue(),
            }

            config['titannet_settings'] = tn_settings
            save_titan_im_config(config)

            # Update active client if available
            try:
                app = wx.GetApp()
                if app:
                    for window in app.GetTopLevelWindows():
                        if hasattr(window, 'titan_client'):
                            window.titan_client.update_server_config(
                                tn_settings['server_host'],
                                tn_settings['server_port'],
                                tn_settings['http_port']
                            )
            except Exception as e:
                print(f"[SettingsFrame] Error updating active client: {e}")

            # Upload sounds to server if business card is enabled
            if self.business_card_cb.GetValue():
                self._upload_business_card_sounds()

            print("[SettingsFrame] Titan-Net settings saved.")
        except Exception as e:
            print(f"[SettingsFrame] Error saving Titan-Net settings: {e}")
            import traceback
            traceback.print_exc()

    def _validate_audio_duration(self, file_path, max_seconds):
        """Validate that an audio file does not exceed max_seconds duration."""
        if not file_path or not os.path.exists(file_path):
            return True  # No file selected = valid

        try:
            import wave
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.wav':
                with wave.open(file_path, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    duration = frames / float(rate)
                    return duration <= max_seconds
            # For ogg/mp3, try pygame
            try:
                import pygame
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                snd = pygame.mixer.Sound(file_path)
                duration = snd.get_length()
                return duration <= max_seconds
            except Exception:
                pass
        except Exception as e:
            print(f"[SettingsFrame] Cannot validate audio duration: {e}")
        return True  # If we can't check, allow it

    def _upload_business_card_sounds(self):
        """Upload business card sounds to Titan-Net server in background.
        Uses the existing logged-in client if available."""
        sound_map = {k: v for k, v in self._sound_paths.items() if v and os.path.exists(v)}
        if not sound_map:
            return

        def upload_thread():
            temp_client = None
            try:
                from src.network.titan_net import TitanNetClient
                from src.settings.titan_im_config import load_titan_im_config

                # Find existing connected client by searching all top-level windows
                # (GetTopWindow() may return SettingsFrame instead of TitanApp)
                client = None
                try:
                    app = wx.GetApp()
                    if app:
                        for window in app.GetTopLevelWindows():
                            if hasattr(window, 'titan_client'):
                                c = window.titan_client
                                if c and c.is_connected and c.user_id and c.username:
                                    client = c
                                    break
                except Exception:
                    pass

                if client:
                    print("[SettingsFrame] Using existing Titan-Net connection for sound upload")
                else:
                    # No connected client - silently login with saved credentials
                    config = load_titan_im_config()
                    username = config.get('titannet_username', '')
                    password = config.get('titannet_password', '')
                    if not username or not password:
                        print("[SettingsFrame] No saved Titan-Net credentials for sound upload")
                        return

                    temp_client = TitanNetClient(
                        server_host=self.server_host_ctrl.GetValue().strip() or 'titosofttitan.com',
                        server_port=int(self.server_port_ctrl.GetValue() or 8001),
                        http_port=int(self.http_port_ctrl.GetValue() or 8000)
                    )
                    result = temp_client.login(username, password)
                    if not result.get('success'):
                        print(f"[SettingsFrame] Silent login failed: {result.get('message')}")
                        return
                    client = temp_client
                    print("[SettingsFrame] Silent login successful for sound upload")

                # Upload each sound
                for sound_type, path in sound_map.items():
                    result = client.upload_user_sound(path, sound_type)
                    if result.get('success'):
                        print(f"[SettingsFrame] Uploaded {sound_type} sound successfully")
                    else:
                        print(f"[SettingsFrame] Failed to upload {sound_type}: {result.get('error')}")
            except Exception as e:
                print(f"[SettingsFrame] Error uploading sounds: {e}")
            finally:
                # Disconnect temp client if we created one
                # Server-side check ensures other sessions stay active
                if temp_client:
                    try:
                        temp_client.logout()
                    except Exception:
                        pass

        import threading
        t = threading.Thread(target=upload_thread, daemon=True)
        t.start()

    def OnSapiSettings(self, event):
        if sys.platform != 'win32':
            _show_skinned_message(_("This feature is only available on Windows."), _("Information"), wx.OK | wx.ICON_INFORMATION)
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
                _show_skinned_message(_("Cannot open SAPI settings:\n{}\n\nTechnical details in the console.").format(error_message), _("Error"), wx.OK | wx.ICON_ERROR)
            else:
                print("INFO: SAPI settings command executed successfully.")

        except FileNotFoundError:
            print("ERROR: Executable control.exe not found.")
            _show_skinned_message(_("Error: Executable control.exe not found. Make sure Windows is working correctly."), _("Error"), wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Unexpected error while opening SAPI settings: {e}")
            _show_skinned_message(_("Unexpected error while opening SAPI settings:\n{}\n\nTechnical details in the console.").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
            traceback.print_exc()
        event.Skip()


    def OnEaseOfAccess(self, event):
        if sys.platform != 'win32':
            _show_skinned_message(_("This feature is only available on Windows."), _("Information"), wx.OK | wx.ICON_INFORMATION)
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
                    _show_skinned_message(_("Cannot open Ease of Access:\n{}\n\nTechnical details in the console.").format(error_message), _("Error"), wx.OK | wx.ICON_ERROR)
                else:
                    print("INFO: Legacy Ease of Access command executed successfully.")
            else:
                print("INFO: Modern Ease of Access settings opened successfully.")

        except FileNotFoundError:
            print("ERROR: Executable not found.")
            _show_skinned_message(_("Error: Cannot find accessibility settings. Make sure Windows is working correctly."), _("Error"), wx.OK | wx.ICON_ERROR)
        except Exception as e:
            print(f"ERROR: Unexpected error while opening Ease of Access: {e}")
            _show_skinned_message(_("Unexpected error while opening Ease of Access:\n{}\n\nTechnical details in the console.").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
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

    def OnStartupModeChanged(self, event):
        """Show/hide launcher or categories controls based on startup mode."""
        sel = self.startup_mode_choice.GetSelection()
        is_custom = (sel == 3)

        # Launcher controls
        self.launcher_label.Show(is_custom)
        self.launcher_listbox.Show(is_custom)
        self.launcher_desc_label.Show(is_custom)
        self.launcher_description.Show(is_custom)

        # Categories controls
        self.categories_label.Show(not is_custom)
        self.categories_checklist.Show(not is_custom)

        self.general_panel.Layout()
        self.content_panel.FitInside()

    def OnLauncherSelected(self, event):
        """Update launcher description when a launcher is selected."""
        sel = self.launcher_listbox.GetSelection()
        if sel != wx.NOT_FOUND and sel < len(self._launcher_configs):
            config = self._launcher_configs[sel]
            self.launcher_description.SetValue(config.description or _("No description available."))

    def OnRadioBox(self, event):
        play_sound('core/SELECT.ogg')
        vibrate_selection()
        event.Skip()

    def _format_titan_ui_key(self, key_string):
        """Convert internal key id (e.g. 'grave', 'shift+f2') into a human-readable label."""
        if not key_string:
            return _("Not set")
        parts = [p.strip() for p in key_string.split('+') if p.strip()]
        names = {
            'ctrl': _("Ctrl"),
            'shift': _("Shift"),
            'alt': _("Alt"),
            'win': _("Win"),
            'cmd': _("Cmd"),
            'grave': _("Accent"),
            'space': _("Space"),
            'tab': _("Tab"),
            'enter': _("Enter"),
            'escape': _("Escape"),
            'backspace': _("Backspace"),
            'delete': _("Delete"),
            'insert': _("Insert"),
            'home': _("Home"),
            'end': _("End"),
            'pageup': _("Page Up"),
            'pagedown': _("Page Down"),
            'up': _("Up"),
            'down': _("Down"),
            'left': _("Left"),
            'right': _("Right"),
        }
        display_parts = []
        for p in parts:
            if p in names:
                display_parts.append(names[p])
            elif p.startswith('f') and p[1:].isdigit():
                display_parts.append(p.upper())
            else:
                display_parts.append(p)
        return '+'.join(display_parts)

    def OnCaptureTitanUIKey(self, event):
        """Open a dialog that captures the next key combination from the user."""
        dlg = KeyCaptureDialog(self, current_label=self._format_titan_ui_key(self._titan_ui_key_value))
        try:
            apply_skin_to_window(dlg)
        except Exception:
            pass
        if dlg.ShowModal() == wx.ID_OK and dlg.captured_key:
            self._titan_ui_key_value = dlg.captured_key
            self.titan_ui_key_btn.SetLabel(
                _("Titan UI key: {}").format(self._format_titan_ui_key(self._titan_ui_key_value))
            )
            play_sound('ui/X.ogg')
            speaker.speak(_("Titan UI key set to {}").format(
                self._format_titan_ui_key(self._titan_ui_key_value)))
        dlg.Destroy()

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

    def OnHapticModeChanged(self, event):
        """Persist the controller vibration mode and play a preview."""
        try:
            mode = self._HAPTIC_MODE_VALUES[max(0, self.haptic_mode_choice.GetSelection())]
            set_haptic_mode(mode)
            # Audible/haptic confirmation; in 'sync' mode this sound also drives a pulse.
            play_sound('core/SELECT.ogg')
        except Exception as e:
            print(f"Error changing haptic mode: {e}")
        event.Skip()

    def OnHapticStrengthChange(self, event):
        """Persist controller vibration strength."""
        try:
            set_vibration_strength(self.haptic_strength_slider.GetValue() / 100.0)
        except Exception as e:
            print(f"Error changing vibration strength: {e}")
        event.Skip()

    def OnTestVibration(self, event):
        """Fire a test vibration so the user can feel the current strength."""
        try:
            test_vibration()
        except Exception as e:
            print(f"Error testing vibration: {e}")
        event.Skip()

    def OnSpeechHapticSyncChanged(self, event):
        """Persist the experimental speech-synced haptics toggle."""
        try:
            set_speech_haptic_sync(self.speech_haptic_sync_cb.GetValue())
        except Exception as e:
            print(f"Error changing speech haptic sync: {e}")
        event.Skip()

    def OnSoundModeChanged(self, event):
        # Persist immediately so the preview sound uses the new mode, then play a
        # focus sound so the user can hear the positioning effect.
        try:
            mode = self._SOUND_MODE_VALUES[max(0, self.sound_mode_choice.GetSelection())]
            set_setting('sound_mode', mode, 'sound')
            set_setting('stereo_sound', str(mode != 'none'), 'sound')
            self.settings.setdefault('sound', {})['sound_mode'] = mode
            self.settings['sound']['stereo_sound'] = str(mode != 'none')
        except Exception as e:
            print(f"Error applying sound mode: {e}")
        self._update_calibrate_button()
        try:
            play_focus_sound(pan=1.0, elevation=0.6)
        except Exception:
            pass
        event.Skip()

    def _current_sound_mode(self):
        try:
            return self._SOUND_MODE_VALUES[max(0, self.sound_mode_choice.GetSelection())]
        except Exception:
            return 'none'

    def _is_3d_calibrated(self):
        try:
            return get_setting('reverb_enabled', 'False', 'sound').lower() in ('true', '1')
        except Exception:
            return False

    def _update_calibrate_button(self):
        """Show the calibrate/remove button only in 3D and label it by state."""
        btn = getattr(self, 'calibrate_3d_btn', None)
        if btn is None:
            return
        if self._current_sound_mode() == '3d':
            btn.SetLabel(_("Remove calibration profile") if self._is_3d_calibrated()
                         else _("Calibrate 3D sound"))
            btn.Show()
        else:
            btn.Hide()
        try:
            btn.GetParent().Layout()
        except Exception:
            pass

    def _speak_message(self, text):
        """Speak a status message via Titan TTS when enabled, else screen reader."""
        try:
            from src.titan_core import tce_speech
            tce_speech.speak(text)
        except Exception:
            try:
                speaker.speak(text)
            except Exception:
                pass

    def OnCalibrate3D(self, event):
        # If already calibrated, this button removes the saved room profile.
        if self._is_3d_calibrated():
            try:
                set_setting('reverb_enabled', 'False', 'sound')
                self.settings.setdefault('sound', {})['reverb_enabled'] = 'False'
                from src.titan_core import spatial_audio
                spatial_audio.clear_reverb()
            except Exception as e:
                print(f"Error removing calibration profile: {e}")
            self._update_calibrate_button()
            self._speak_message(_("Calibration profile removed"))
            event.Skip()
            return

        # Otherwise run a room calibration in the background.
        self.calibrate_3d_btn.Disable()
        self._speak_message(_("Calibration, please wait"))

        def _worker():
            ok = False
            try:
                from src.titan_core import sound_calibration
                sound_calibration.calibrate()
                ok = True
            except Exception as e:
                print(f"3D calibration error: {e}")
                ok = False

            def _finish():
                if ok:
                    self.settings.setdefault('sound', {})['reverb_enabled'] = 'True'
                    self._speak_message(_("Calibration complete"))
                else:
                    self._speak_message(_("Error while calibrating"))
                self.calibrate_3d_btn.Enable()
                self._update_calibrate_button()
            wx.CallAfter(_finish)

        threading.Thread(target=_worker, daemon=True).start()
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

        sound_mode_value = self._SOUND_MODE_VALUES[max(0, self.sound_mode_choice.GetSelection())]
        self.settings['sound'] = {
            'theme': self.theme_choice.GetStringSelection(),
            'sound_mode': sound_mode_value,
            # Keep legacy stereo_sound in sync for out-of-tree readers.
            'stereo_sound': str(sound_mode_value != 'none'),
            'use_skin_sound_theme': str(self.use_skin_sound_theme_cb.GetValue()),
            'fallback_to_default_theme': str(self.fallback_to_default_theme_cb.GetValue()),
            'theme_volume': str(self.theme_volume_slider.GetValue())
        }
        startup_mode_selection = self.startup_mode_choice.GetSelection()
        if startup_mode_selection == 1:
            startup_mode = 'minimized'
        elif startup_mode_selection == 2:
            startup_mode = 'klango'
        elif startup_mode_selection == 3:
            startup_mode = 'launcher'
        else:
            startup_mode = 'normal'

        # Build visible categories from checklist
        checked_cats = []
        for i, cat_id in enumerate(self._category_ids):
            if self.categories_checklist.IsChecked(i):
                checked_cats.append(cat_id)
        if not checked_cats:
            # At least one category must be selected
            checked_cats = ['apps']
            self.categories_checklist.Check(0, True)

        # Get selected launcher folder name
        launcher_folder = ''
        sel = self.launcher_listbox.GetSelection()
        if sel != wx.NOT_FOUND and sel < len(self._launcher_configs):
            launcher_folder = self._launcher_configs[sel].folder_name

        # Read new general fields
        try:
            minimize_action_value = self._minimize_action_values[self.minimize_action_radio.GetSelection()]
        except Exception:
            minimize_action_value = 'invisible_ui'
        try:
            alt_f4_action_value = self._alt_f4_action_values[self.alt_f4_action_radio.GetSelection()]
        except Exception:
            alt_f4_action_value = 'close'

        self.settings['general'] = {
            'quick_start': str(self.quick_start_cb.GetValue()),
            'confirm_exit': str(self.confirm_exit_cb.GetValue()),
            'startup_mode': startup_mode,
            'language': selected_language,
            'launcher': launcher_folder,
            'visible_categories': ','.join(checked_cats),
            'minimize_action': minimize_action_value,
            'alt_f4_action': alt_f4_action_value,
            'titan_ui_key': self._titan_ui_key_value or 'grave',
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
        sapi_new_value = None
        sapi_old_value = None
        if self.register_titan_tts_sapi_cb is not None:
            sapi_new_value = self.register_titan_tts_sapi_cb.GetValue()
            sapi_old_value = str(self.settings.get('environment', {}).get(
                'register_titan_tts_sapi', 'False')).lower() in ['true', '1']
            env_settings['register_titan_tts_sapi'] = str(sapi_new_value)
        if self.copilot_remap_cb is not None:
            env_settings['copilot_remap'] = str(self.copilot_remap_cb.GetValue())
            if self.copilot_key_choice is not None:
                from src.system.copilot_key import REPLACEMENT_KEYS
                idx = self.copilot_key_choice.GetSelection()
                if 0 <= idx < len(REPLACEMENT_KEYS):
                    env_settings['copilot_replacement_vk'] = str(REPLACEMENT_KEYS[idx][0])
        self.settings['environment'] = env_settings

        # Apply SAPI5 registration only if the checkbox state actually changed.
        # Elevation (UAC) is triggered interactively here; startup sync stays silent.
        if self.register_titan_tts_sapi_cb is not None and sapi_new_value != sapi_old_value:
            try:
                from src.tts.sapi_registration import apply_sapi_registration
                apply_sapi_registration(sapi_new_value, interactive=True)
                try:
                    from src.tts import sapi_pipe_server
                    if sapi_new_value:
                        sapi_pipe_server.start()
                    else:
                        sapi_pipe_server.stop()
                except Exception as _e2:
                    print(f"[Settings] SAPI pipe server toggle failed: {_e2}")
            except Exception as _e:
                print(f"[Settings] SAPI registration apply failed: {_e}")

        # Save system monitor settings
        volume_monitor_options = ['none', 'sound', 'speech', 'both']
        battery_announce_options = ['1%', '10%', '15%', '25%', 'never']
        
        self.settings['system_monitor'] = {
            'volume_monitor': volume_monitor_options[self.volume_monitor_choice.GetSelection()],
            'battery_announce_interval': battery_announce_options[self.battery_announce_choice.GetSelection()],
            'monitor_charger': str(self.monitor_charger_cb.GetValue()),
            'monitor_battery_alerts': str(self.monitor_battery_alerts_cb.GetValue()),
            'battery_low_threshold': int(self.battery_low_options[self.battery_low_choice.GetSelection()].rstrip('%')),
            'battery_critical_threshold': int(self.battery_critical_options[self.battery_critical_choice.GetSelection()].rstrip('%')),
            'battery_low_sound': self.battery_low_sound_options[self.battery_low_sound_list.GetSelection()][0]
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

            stereo_speech_settings = {
                'engine': engine,
                'voice': voice_value,
                'rate': str(self.rate_slider.GetValue()),
                'pitch': str(self.pitch_slider.GetValue()),
                'volume': str(self.speech_volume_slider.GetValue()),
            }

            # Save dynamic engine config controls with prefix engine.{id}.{key}
            for ctrl_key, (label, ctrl, field) in self._engine_config_controls.items():
                value = self._get_config_control_value(ctrl, field)
                setting_key = f'engine.{engine}.{ctrl_key}'
                stereo_speech_settings[setting_key] = value

                # Apply config to engine immediately
                stereo_speech_obj = get_stereo_speech()
                if stereo_speech_obj:
                    stereo_speech_obj.set_engine_config(engine, ctrl_key, value)

            # Preserve engine configs for other engines (not currently selected)
            old_settings = self.settings.get('stereo_speech', {})
            for old_key, old_value in old_settings.items():
                if old_key.startswith('engine.') and old_key not in stereo_speech_settings:
                    stereo_speech_settings[old_key] = old_value

            self.settings['stereo_speech'] = stereo_speech_settings

        if hasattr(self, 'windows_panel'):
            self.settings['windows'] = {
                'disable_mute_on_start': str(self.mute_checkbox.GetValue())
                # TODO: Save the current slider volume value if needed on startup
                # (usually not necessary, as the system remembers the volume)
            }

        # Game controller (vibration / haptics) settings. These also persist
        # immediately through their live event handlers, but include them in the
        # main Save flow too so the gamepad panel behaves like every other panel.
        # Only the keys this panel owns are written; the final merge below keeps
        # other controller keys (e.g. controller_mode) intact.
        try:
            haptic_mode_value = self._HAPTIC_MODE_VALUES[max(0, self.haptic_mode_choice.GetSelection())]
        except Exception:
            haptic_mode_value = 'sync'
        controller_section = self.settings.get('controller', {})
        controller_section.update({
            'haptic_mode': haptic_mode_value,
            'vibration_strength': str(self.haptic_strength_slider.GetValue() / 100.0),
            'speech_haptic_sync': str(self.speech_haptic_sync_cb.GetValue()),
        })
        self.settings['controller'] = controller_section

        # Re-read the on-disk settings and merge our GUI-built sections on top
        # at the key level, so values written elsewhere since this dialog opened
        # (quick settings, buffer engine settings, 3D calibration reverb_*) are
        # preserved instead of being clobbered by this dialog's snapshot.
        disk_settings = load_settings()
        for section, values in self.settings.items():
            base = disk_settings.get(section, {})
            base.update(values)
            disk_settings[section] = base
        self.settings = disk_settings
        save_settings(self.settings)

        # Save Titan-Net settings
        if self._titan_net_available:
            self.save_titan_net_settings()

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
        # Unregister from window switcher
        try:
            from src.ui.window_switcher import unregister_window
            unregister_window(_("Settings"))
        except Exception:
            pass
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

    def OnBatteryLowSoundSelect(self, event):
        """Preview the low battery sound when its list item is selected."""
        try:
            index = self.battery_low_sound_list.GetSelection()
            if 0 <= index < len(self.battery_low_sound_options):
                _value, _label, sound_file = self.battery_low_sound_options[index]
                if sound_file is None:
                    # "Random" entry: preview a random one of the two sounds
                    import random
                    sound_file = random.choice(['system/low_battery1.ogg', 'system/low_battery2.ogg'])
                play_sound(sound_file)
        except Exception as e:
            print(f"Error previewing low battery sound: {e}")
        event.Skip()

    def OnCheckBox(self, event):
        if event.IsChecked():
            play_sound('ui/X.ogg')
            vibrate_selection()  # Add vibration for checkbox checked
        else:
            play_sound('core/FOCUS.ogg')
            vibrate_focus_change()  # Add vibration for checkbox unchecked
        event.Skip()

    def OnCategoryChecklistToggle(self, event):
        """Handle check/uncheck on the categories CheckListBox.

        wx.CheckListBox does not expose item check state to screen readers
        on Windows, so we delegate to the accessibility helper which plays
        ui/cb_listitem_checked.ogg and — 500 ms later, only when a real
        screen reader is running — speaks just "checked" / "unchecked"
        (the item name is already read by the SR on focus).
        """
        try:
            idx = event.GetInt()
        except Exception:
            idx = event.GetSelection() if hasattr(event, 'GetSelection') else -1

        if idx is None or idx < 0:
            event.Skip()
            return

        try:
            checked = self.categories_checklist.IsChecked(idx)
        except Exception:
            event.Skip()
            return

        self._categories_last_announced_idx = idx

        try:
            from src.accessibility.messages import announce_checklist_item_toggle
            announce_checklist_item_toggle(checked)
        except Exception as e:
            print(f"[SettingsFrame] announce_checklist_item_toggle error: {e}")

        event.Skip()

    def OnCategoryChecklistSelect(self, event):
        """Announce the check state while arrowing across CheckListBox rows.

        Screen readers read the item name on focus but not its check state,
        so for each navigation that lands on a new row we emit the same
        sound + delayed "checked" / "unchecked" announcement as on toggle.
        Re-selecting the already-announced row is a no-op so we don't spam
        the audio when the event fires redundantly.
        """
        try:
            idx = event.GetSelection()
        except Exception:
            idx = -1

        if idx is None or idx < 0:
            event.Skip()
            return

        if idx == getattr(self, '_categories_last_announced_idx', -1):
            event.Skip()
            return

        try:
            checked = self.categories_checklist.IsChecked(idx)
        except Exception:
            event.Skip()
            return

        self._categories_last_announced_idx = idx

        try:
            from src.accessibility.messages import announce_checklist_item_navigation
            announce_checklist_item_navigation(checked)
        except Exception as e:
            print(f"[SettingsFrame] announce_checklist_item_navigation error: {e}")

        event.Skip()

    def _rebuild_engine_config_controls(self, engine_id):
        """
        Dynamically create config controls based on the engine's get_config_fields().

        Destroys old controls and creates new ones for the selected engine.
        """
        panel = self.stereo_speech_panel

        # Destroy existing dynamic controls
        for key, (label, ctrl, field) in self._engine_config_controls.items():
            if label:
                label.Destroy()
            if ctrl:
                ctrl.Destroy()
        self._engine_config_controls = {}
        self._engine_config_sizer.Clear()

        # Get engine's config fields from registry
        try:
            from src.tts.engine_registry import get_engine_registry
            registry = get_engine_registry()
            if not registry:
                panel.Layout()
                self.content_panel.FitInside()
                return

            engine = registry.get_engine(engine_id)
            if not engine or not hasattr(engine, 'get_config_fields'):
                panel.Layout()
                self.content_panel.FitInside()
                return

            fields = engine.get_config_fields()
            if not fields:
                panel.Layout()
                self.content_panel.FitInside()
                return

            for field in fields:
                field_key = field.get('key', '')
                field_label = field.get('label', field_key)
                field_type = field.get('type', 'text')
                field_tooltip = field.get('tooltip', '')
                field_default = field.get('default', '')

                # Checkboxes carry their label inside the widget for screen reader accessibility.
                # All other types use a separate StaticText label above the control.
                is_checkbox = (field_type == 'checkbox')
                if is_checkbox:
                    label_widget = None
                else:
                    label_widget = wx.StaticText(panel, label=field_label)
                    self._engine_config_sizer.Add(label_widget, flag=wx.TOP, border=5)

                # Create control based on type
                ctrl = None
                if field_type == 'password':
                    ctrl = wx.TextCtrl(panel, style=wx.TE_PASSWORD)
                    ctrl.SetValue(str(field_default))
                    ctrl.Bind(wx.EVT_KILL_FOCUS, self._on_engine_config_changed)
                elif field_type == 'text':
                    ctrl = wx.TextCtrl(panel)
                    ctrl.SetValue(str(field_default))
                    ctrl.Bind(wx.EVT_KILL_FOCUS, self._on_engine_config_changed)
                elif field_type == 'choice':
                    ctrl = wx.Choice(panel)
                    options = field.get('options', [])
                    for val, display in options:
                        ctrl.Append(display)
                    # Select default
                    for i, (val, display) in enumerate(options):
                        if val == field_default:
                            ctrl.SetSelection(i)
                            break
                    if ctrl.GetSelection() == wx.NOT_FOUND and ctrl.GetCount() > 0:
                        ctrl.SetSelection(0)
                    ctrl.Bind(wx.EVT_CHOICE, self._on_engine_config_changed)
                elif field_type == 'slider':
                    min_val = field.get('min', 0)
                    max_val = field.get('max', 100)
                    ctrl = wx.Slider(panel, value=int(field_default or min_val),
                                     minValue=min_val, maxValue=max_val,
                                     style=wx.SL_HORIZONTAL)
                    ctrl.SetLabel(field_label)
                    ctrl.Bind(wx.EVT_SLIDER, self._on_engine_config_changed)
                elif field_type == 'checkbox':
                    # Label is embedded in the CheckBox widget so screen readers
                    # (NVDA, JAWS) announce it when the control receives focus.
                    ctrl = wx.CheckBox(panel, label=field_label)
                    ctrl.SetValue(bool(field_default))
                    ctrl.Bind(wx.EVT_CHECKBOX, self._on_engine_config_changed)

                if ctrl:
                    if field_tooltip:
                        ctrl.SetToolTip(field_tooltip)
                    ctrl.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
                    # Checkboxes must NOT be expanded — wx.EXPAND on a checkbox
                    # makes it fill the full sizer width and can render as a button
                    # in some Windows themes / accessibility tools.
                    if field_type == 'checkbox':
                        self._engine_config_sizer.Add(ctrl, flag=wx.TOP, border=5)
                    else:
                        self._engine_config_sizer.Add(ctrl, flag=wx.EXPAND | wx.TOP, border=2)
                    self._engine_config_controls[field_key] = (label_widget, ctrl, field)

        except Exception as e:
            print(f"[Settings] Error building engine config controls: {e}")
            import traceback
            traceback.print_exc()

        panel.Layout()
        self.content_panel.FitInside()

    def _on_engine_config_changed(self, event):
        """Handle changes to dynamic engine config controls - apply immediately."""
        try:
            engine_display = self.engine_choice.GetStringSelection()
            engine_id = self._display_to_engine(engine_display)

            stereo_speech = get_stereo_speech()
            if not stereo_speech:
                event.Skip()
                return

            for key, (label, ctrl, field) in self._engine_config_controls.items():
                value = self._get_config_control_value(ctrl, field)
                stereo_speech.set_engine_config(engine_id, key, value)

            # Reload voices if API key or similar config changed
            field_key = None
            for k, (l, c, f) in self._engine_config_controls.items():
                if c == event.GetEventObject():
                    field_key = k
                    break

            if field_key in ('api_key',):
                self.load_available_voices()

        except Exception as e:
            print(f"[Settings] Error applying engine config: {e}")
        event.Skip()

    def _get_config_control_value(self, ctrl, field):
        """Extract value from a dynamic config control."""
        field_type = field.get('type', 'text')
        if field_type in ('text', 'password'):
            return ctrl.GetValue().strip()
        elif field_type == 'choice':
            sel = ctrl.GetSelection()
            options = field.get('options', [])
            if 0 <= sel < len(options):
                return options[sel][0]
            return field.get('default', '')
        elif field_type == 'slider':
            return str(ctrl.GetValue())
        elif field_type == 'checkbox':
            return str(ctrl.GetValue())
        return ''

    def _get_engine_display_names(self):
        """Get mapping between engine IDs and display names from registry."""
        try:
            from src.tts.engine_registry import get_engine_registry
            registry = get_engine_registry()
            if registry:
                names = {}
                for engine in registry.get_all_engines():
                    names[engine.engine_id] = engine.engine_name
                return names
        except Exception as e:
            print(f"[Settings] Error getting engine names from registry: {e}")
        # Fallback
        return {
            'espeak': 'eSpeak NG',
            'sapi5': 'SAPI5',
            'say': _('macOS Speech'),
            'spd': _('Speech Dispatcher'),
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

        # Backward compat: migrate old elevenlabs_api_key to new format
        old_api_key = stereo_settings.get('elevenlabs_api_key', '')
        new_api_key_key = 'engine.elevenlabs.api_key'
        if old_api_key and new_api_key_key not in stereo_settings:
            stereo_settings[new_api_key_key] = old_api_key

        # Load engine-specific config from settings and apply to engine
        stereo_speech_obj = get_stereo_speech()
        if stereo_speech_obj:
            for setting_key, value in stereo_settings.items():
                if setting_key.startswith('engine.'):
                    parts = setting_key.split('.', 2)  # engine.{id}.{key}
                    if len(parts) == 3:
                        eng_id, cfg_key = parts[1], parts[2]
                        stereo_speech_obj.set_engine_config(eng_id, cfg_key, value)

        # Build dynamic engine config controls for current engine
        self._rebuild_engine_config_controls(engine)

        # Load saved values into dynamic controls
        for ctrl_key, (label, ctrl, field) in self._engine_config_controls.items():
            setting_key = f'engine.{engine}.{ctrl_key}'
            saved_value = stereo_settings.get(setting_key, '')
            if saved_value:
                field_type = field.get('type', 'text')
                if field_type in ('text', 'password'):
                    ctrl.SetValue(saved_value)
                elif field_type == 'choice':
                    options = field.get('options', [])
                    for i, (val, display) in enumerate(options):
                        if val == saved_value:
                            ctrl.SetSelection(i)
                            break
                elif field_type == 'slider':
                    try:
                        ctrl.SetValue(int(saved_value))
                    except (ValueError, TypeError):
                        pass
                elif field_type == 'checkbox':
                    ctrl.SetValue(saved_value.lower() in ('true', '1'))

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

        # Set pitch
        pitch = int(stereo_settings.get('pitch', '0'))
        self.pitch_slider.SetValue(pitch)
        # Apply pitch to stereo speech
        try:
            stereo_speech.set_pitch(pitch)
        except Exception as e:
            print(f"Error setting initial pitch: {e}")

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

                # Rebuild dynamic engine config controls
                self._rebuild_engine_config_controls(engine_id)

                # Refresh the Titan Buffer System TTS category so its
                # parameters reflect the newly selected engine.
                try:
                    from src.buffers import tts_buffer
                    tts_buffer.refresh()
                except Exception as _be:
                    print(f"Error refreshing TTS buffer: {_be}")
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
        """Legacy handler - now handled by _on_engine_config_changed."""
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

    def OnPitchChanged(self, event):
        """Handle pitch slider change"""
        if self.pitch_timer:
            self.pitch_timer.cancel()

        pitch = self.pitch_slider.GetValue()

        def update_pitch():
            try:
                stereo_speech = get_stereo_speech()
                stereo_speech.set_pitch(pitch)
                play_sound('core/FOCUS.ogg')
            except Exception as e:
                print(f"Error setting pitch: {e}")

        self.pitch_timer = threading.Timer(0.2, update_pitch)
        self.pitch_timer.start()

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

    def OnCopilotRemapChanged(self, event):
        """Handle Copilot remap checkbox change"""
        enabled = self.copilot_remap_cb.GetValue()
        if self.copilot_key_choice is not None:
            self.copilot_key_choice.Enable(enabled)
        try:
            from src.system.copilot_key import install_hook, uninstall_hook, REPLACEMENT_KEYS
            if enabled:
                idx = self.copilot_key_choice.GetSelection() if self.copilot_key_choice else 0
                vk = REPLACEMENT_KEYS[idx][0] if 0 <= idx < len(REPLACEMENT_KEYS) else REPLACEMENT_KEYS[0][0]
                install_hook(vk)
            else:
                uninstall_hook()
        except Exception as e:
            print(f"[Settings] Copilot hook toggle error: {e}")
        event.Skip()

    def OnCopilotKeyChoiceChanged(self, event):
        """Handle Copilot replacement key choice change"""
        if not self.copilot_remap_cb or not self.copilot_remap_cb.GetValue():
            event.Skip()
            return
        try:
            from src.system.copilot_key import set_replacement_key, REPLACEMENT_KEYS
            idx = self.copilot_key_choice.GetSelection()
            if 0 <= idx < len(REPLACEMENT_KEYS):
                set_replacement_key(REPLACEMENT_KEYS[idx][0])
        except Exception as e:
            print(f"[Settings] Copilot key choice error: {e}")
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
