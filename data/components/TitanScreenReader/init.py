# -*- coding: utf-8 -*-
"""
Titan Screen Reader Component for TCE Launcher
A basic Windows screen reader using stereo speech positioning
"""

import os
import sys
import threading
import time
import configparser
import platform
import wx

# Import Windows UI Automation
try:
    import pywinauto
    from pywinauto import Desktop
    from pywinauto.win32structures import RECT
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False
    print("[Titan SR] Warning: pywinauto not installed. Screen reader will be disabled.")

# Import Windows API for focus tracking
try:
    import win32gui
    import win32process
    import win32con
    import win32api
    import ctypes
    from ctypes import wintypes
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("[Titan SR] Warning: pywin32 not installed. Screen reader will be disabled.")

# Import stereo speech
try:
    from stereo_speech import StereoSpeech
    STEREO_SPEECH_AVAILABLE = True
except ImportError:
    STEREO_SPEECH_AVAILABLE = False
    print("[Titan SR] Warning: stereo_speech not available.")

# Import accessibility output as fallback
try:
    from accessible_output3.outputs.auto import Auto
    ACCESSIBLE_OUTPUT_AVAILABLE = True
except ImportError:
    ACCESSIBLE_OUTPUT_AVAILABLE = False
    print("[Titan SR] Warning: accessible_output3 not available.")

# Import keyboard for keystroke echo
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("[Titan SR] Warning: keyboard not installed. Echo will be disabled.")

from sound import play_sound
from settings import get_setting

# Translation support
import gettext

# Component directory for translations
COMPONENT_DIR = os.path.dirname(__file__)
LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')

try:
    lang = get_setting('language', 'pl')
    # Look for translations in component's languages directory
    translation = gettext.translation('messages', localedir=LANGUAGES_DIR, languages=[lang], fallback=True)
    translation.install()
    _ = translation.gettext
except Exception as e:
    print(f"[Titan SR] Translation loading failed: {e}")
    def _(text):
        return text


# Paths
def get_config_path():
    """Get configuration file path based on platform"""
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA')
        config_dir = os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings')
    elif platform.system() == 'Darwin':  # macOS
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings')
    else:  # Linux
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, '.config', 'Titosoft', 'Titan', 'appsettings')

    if not os.path.exists(config_dir):
        os.makedirs(config_dir)

    config_path = os.path.join(config_dir, 'titan_screen_reader.ini')
    return config_path


CONFIG_PATH = get_config_path()

# Default settings
DEFAULT_SETTINGS = {
    'enabled': 'False',
    'voice_index': '0',
    'rate': '0',
    'pitch': '0',
    'volume': '100',
    'echo': 'True',
    'speak_role': 'True',
    'stereo_positioning': 'True'
}


class TitanScreenReader:
    """Main screen reader class"""

    def __init__(self):
        self.enabled = False
        self.stereo_speech = None
        self.fallback_speaker = None
        self.settings = configparser.ConfigParser()
        self.monitoring_thread = None
        self.running = False

        # Track both window AND control separately
        self.last_window_hwnd = None
        self.last_focused_hwnd = None

        # Load settings
        self.load_settings()

        # Initialize speech engines
        if STEREO_SPEECH_AVAILABLE:
            try:
                self.stereo_speech = StereoSpeech()
                print("[Titan SR] Stereo speech initialized")
            except Exception as e:
                print(f"[Titan SR] Failed to initialize stereo speech: {e}")

        if ACCESSIBLE_OUTPUT_AVAILABLE:
            try:
                self.fallback_speaker = Auto()
                print("[Titan SR] Fallback speaker initialized")
            except Exception as e:
                print(f"[Titan SR] Failed to initialize fallback speaker: {e}")

        # Keyboard hook for responsiveness and echo
        self.keyboard_hook_registered = False

    def load_settings(self):
        """Load settings from config file"""
        if not os.path.exists(CONFIG_PATH):
            # Create default config
            self.settings['TitanScreenReader'] = DEFAULT_SETTINGS
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                self.settings.write(f)
        else:
            self.settings.read(CONFIG_PATH, encoding='utf-8')
            if 'TitanScreenReader' not in self.settings:
                self.settings['TitanScreenReader'] = DEFAULT_SETTINGS
                with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                    self.settings.write(f)

    def save_settings(self):
        """Save settings to config file"""
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                self.settings.write(f)
        except Exception as e:
            print(f"[Titan SR] Error saving settings: {e}")

    def apply_settings(self):
        """Apply current settings to speech engines"""
        try:
            voice_index = int(self.settings['TitanScreenReader'].get('voice_index', '0'))
            rate = int(self.settings['TitanScreenReader'].get('rate', '0'))
            pitch = int(self.settings['TitanScreenReader'].get('pitch', '0'))
            volume = int(self.settings['TitanScreenReader'].get('volume', '100'))

            if self.stereo_speech:
                self.stereo_speech.set_voice(voice_index)
                self.stereo_speech.set_rate(rate)
                self.stereo_speech.set_volume(volume)
                # Pitch is applied per-speak call

            print(f"[Titan SR] Applied settings: voice={voice_index}, rate={rate}, pitch={pitch}, volume={volume}")
        except Exception as e:
            print(f"[Titan SR] Error applying settings: {e}")

    def stop_speech(self):
        """Stop current speech immediately - same as invisibleui.py"""
        try:
            if self.stereo_speech:
                self.stereo_speech.stop()
        except Exception as e:
            print(f"[Titan SR] Error stopping speech: {e}")

    def speak(self, text, position=0.0, interrupt=True):
        """Speak text with optional stereo positioning"""
        if not text:
            return

        try:
            # Always stop previous speech for responsiveness
            if interrupt:
                self.stop_speech()

            pitch = int(self.settings['TitanScreenReader'].get('pitch', '0'))
            stereo_enabled = self.settings['TitanScreenReader'].get('stereo_positioning', 'True').lower() == 'true'

            # Use stereo positioning if enabled
            if stereo_enabled and position != 0.0 and self.stereo_speech:
                self.stereo_speech.speak(text, position=position, pitch_offset=pitch, use_fallback=True)
            elif self.stereo_speech:
                self.stereo_speech.speak(text, position=0.0, pitch_offset=pitch, use_fallback=True)
            elif self.fallback_speaker:
                self.fallback_speaker.speak(text)
            else:
                print(f"[Titan SR] No TTS available: {text}")
        except Exception as e:
            print(f"[Titan SR] Error speaking: {e}")

    def enable(self):
        """Enable screen reader"""
        if not WIN32_AVAILABLE:
            self.speak(_("Screen reader cannot be enabled. Required libraries missing."))
            return False

        if self.enabled:
            return True

        self.enabled = True
        self.settings['TitanScreenReader']['enabled'] = 'True'
        self.save_settings()
        self.apply_settings()

        # Start monitoring thread
        self.running = True
        self.monitoring_thread = threading.Thread(target=self._monitor_focus, daemon=True)
        self.monitoring_thread.start()

        # Register keyboard hooks
        if KEYBOARD_AVAILABLE:
            self.register_keyboard_hooks()

        play_sound('ui/dialog.ogg')
        self.speak(_("Titan Screen Reader enabled"))
        print("[Titan SR] Screen reader enabled")
        return True

    def disable(self):
        """Disable screen reader"""
        if not self.enabled:
            return

        self.enabled = False
        self.settings['TitanScreenReader']['enabled'] = 'False'
        self.save_settings()

        # Stop monitoring
        self.running = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=2.0)

        # Unregister keyboard hooks
        if KEYBOARD_AVAILABLE:
            self.unregister_keyboard_hooks()

        play_sound('ui/dialogclose.ogg')
        self.speak(_("Titan Screen Reader disabled"))
        print("[Titan SR] Screen reader disabled")

    def toggle(self):
        """Toggle screen reader on/off"""
        if self.enabled:
            self.disable()
        else:
            self.enable()

    def register_keyboard_hooks(self):
        """Register keyboard hooks for navigation and responsiveness"""
        if not KEYBOARD_AVAILABLE or self.keyboard_hook_registered:
            return

        try:
            # Hook all key presses for interrupt and navigation
            keyboard.on_press(self._on_key_press)
            self.keyboard_hook_registered = True
            print("[Titan SR] Keyboard hooks registered")
        except Exception as e:
            print(f"[Titan SR] Failed to register keyboard hooks: {e}")

    def unregister_keyboard_hooks(self):
        """Unregister keyboard hooks"""
        if not KEYBOARD_AVAILABLE or not self.keyboard_hook_registered:
            return

        try:
            keyboard.unhook_all()
            self.keyboard_hook_registered = False
            print("[Titan SR] Keyboard hooks unregistered")
        except Exception as e:
            print(f"[Titan SR] Failed to unregister keyboard hooks: {e}")

    def _on_key_press(self, event):
        """Handle key press for speech interruption and echo (like NVDA)"""
        try:
            # CRITICAL: Always interrupt speech on any key press for responsiveness
            self.stop_speech()

            # Handle echo if enabled
            echo_enabled = self.settings['TitanScreenReader'].get('echo', 'True').lower() == 'true'
            if echo_enabled:
                # Echo printable characters (interrupt=False so echo doesn't interrupt itself)
                if len(event.name) == 1:
                    self.speak(event.name, position=0.0, interrupt=False)
                elif event.name == 'space':
                    self.speak(_("space"), position=0.0, interrupt=False)
                elif event.name == 'enter':
                    self.speak(_("enter"), position=0.0, interrupt=False)
                elif event.name == 'backspace':
                    self.speak(_("backspace"), position=0.0, interrupt=False)

        except Exception as e:
            print(f"[Titan SR] Error in key press handler: {e}")

    def _get_focused_control(self, window_hwnd):
        """Get focused control using GetGUIThreadInfo (more reliable than GetFocus)"""
        try:
            # Get thread ID of foreground window
            thread_id = win32process.GetWindowThreadProcessId(window_hwnd)[0]

            # Define GUITHREADINFO structure
            class GUITHREADINFO(ctypes.Structure):
                _fields_ = [
                    ('cbSize', wintypes.DWORD),
                    ('flags', wintypes.DWORD),
                    ('hwndActive', wintypes.HWND),
                    ('hwndFocus', wintypes.HWND),
                    ('hwndCapture', wintypes.HWND),
                    ('hwndMenuOwner', wintypes.HWND),
                    ('hwndMoveSize', wintypes.HWND),
                    ('hwndCaret', wintypes.HWND),
                    ('rcCaret', wintypes.RECT),
                ]

            gui_info = GUITHREADINFO()
            gui_info.cbSize = ctypes.sizeof(GUITHREADINFO)

            # Get GUI thread info
            if ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)):
                return gui_info.hwndFocus
            else:
                return None

        except Exception as e:
            print(f"[Titan SR] Error getting focused control: {e}")
            return None

    def _monitor_focus(self):
        """Monitor focus changes and speak focused elements (like NVDA)"""
        print("[Titan SR] Focus monitoring started")

        while self.running:
            try:
                # Get foreground window
                window_hwnd = win32gui.GetForegroundWindow()

                if not window_hwnd:
                    time.sleep(0.1)
                    continue

                # Check if WINDOW changed
                window_changed = (window_hwnd != self.last_window_hwnd)
                if window_changed:
                    self.last_window_hwnd = window_hwnd

                    # Read window title
                    try:
                        window_text = win32gui.GetWindowText(window_hwnd)
                        if window_text:
                            try:
                                rect = win32gui.GetWindowRect(window_hwnd)
                                position = self._calculate_stereo_position(rect)
                            except:
                                position = 0.0

                            self.speak(window_text, position=position)
                            print(f"[Titan SR] Window changed: {window_text}")
                    except Exception as e:
                        print(f"[Titan SR] Error reading window: {e}")

                # Get focused control using GetGUIThreadInfo (more reliable)
                focused_hwnd = self._get_focused_control(window_hwnd)

                # Also try GetFocus as fallback
                if not focused_hwnd:
                    try:
                        focused_hwnd = win32gui.GetFocus()
                    except:
                        focused_hwnd = None

                # Check if CONTROL changed
                control_changed = (focused_hwnd != self.last_focused_hwnd)

                if control_changed and focused_hwnd and focused_hwnd != window_hwnd:
                    self.last_focused_hwnd = focused_hwnd

                    # Read control
                    try:
                        control_text = win32gui.GetWindowText(focused_hwnd)

                        # Get position for stereo
                        try:
                            rect = win32gui.GetWindowRect(focused_hwnd)
                            position = self._calculate_stereo_position(rect)
                        except:
                            position = 0.0

                        # Get class name for role
                        try:
                            class_name = win32gui.GetClassName(focused_hwnd)
                        except:
                            class_name = None

                        # Build announcement
                        announcement_parts = []

                        if control_text:
                            announcement_parts.append(control_text)

                        # Add role if enabled
                        speak_role = self.settings['TitanScreenReader'].get('speak_role', 'True').lower() == 'true'
                        if speak_role and class_name:
                            role = self._get_role_name(class_name)
                            if role:
                                announcement_parts.append(role)

                        # Speak if we have something to say
                        if announcement_parts:
                            announcement = ", ".join(announcement_parts)
                            self.speak(announcement, position=position)
                            print(f"[Titan SR] Control changed: {announcement} (hwnd={focused_hwnd}, class={class_name})")
                        elif class_name:
                            # No text, but we have a control - at least speak the role
                            role = self._get_role_name(class_name)
                            if role:
                                self.speak(role, position=position)
                                print(f"[Titan SR] Control changed (no text): {role} (class={class_name})")

                    except Exception as e:
                        print(f"[Titan SR] Error reading control: {e}")

                # Check every 100ms for responsiveness
                time.sleep(0.1)

            except Exception as e:
                print(f"[Titan SR] Error in focus monitoring: {e}")
                time.sleep(0.5)

        print("[Titan SR] Focus monitoring stopped")


    def _get_role_name(self, class_name):
        """Get human-readable role name from Windows class name"""
        role_map = {
            'Button': _('button'),
            'Edit': _('edit'),
            'Static': _('text'),
            'ComboBox': _('combo box'),
            'ListBox': _('list box'),
            'ScrollBar': _('scroll bar'),
            'CheckBox': _('checkbox'),
            'RadioButton': _('radio button'),
            'TreeView': _('tree view'),
            'ListView': _('list view'),
            'TabControl': _('tab control'),
            'ToolbarWindow32': _('toolbar'),
            'StatusBar': _('status bar'),
            'MenuBar': _('menu bar'),
            'Dialog': _('dialog'),
            'Window': _('window')
        }

        return role_map.get(class_name, None)

    def _calculate_stereo_position(self, rect):
        """Calculate stereo position based on control position on screen"""
        try:
            # Get screen dimensions using win32api
            screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)

            # Calculate center X of control
            center_x = (rect[0] + rect[2]) / 2

            # Convert to stereo position (-1.0 to 1.0)
            # Left edge = -1.0, Center = 0.0, Right edge = 1.0
            position = (center_x / screen_width) * 2.0 - 1.0
            position = max(-1.0, min(1.0, position))

            return position
        except Exception as e:
            print(f"[Titan SR] Error calculating stereo position: {e}")
            return 0.0


# Global screen reader instance
_screen_reader: TitanScreenReader = None


def get_screen_reader() -> TitanScreenReader:
    """Get the global screen reader instance"""
    global _screen_reader
    if _screen_reader is None:
        _screen_reader = TitanScreenReader()
    return _screen_reader


def show_settings_dialog(parent=None):
    """Show Titan Screen Reader settings dialog"""
    try:
        sr = get_screen_reader()

        # Create dialog
        dlg = wx.Dialog(parent, wx.ID_ANY, _("Titan Screen Reader Settings"), size=(500, 500))
        panel = wx.Panel(dlg)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Enable screen reader checkbox
        enable_cb = wx.CheckBox(panel, label=_("Enable Screen Reader"))
        enable_cb.SetValue(sr.enabled)
        vbox.Add(enable_cb, flag=wx.ALL, border=10)

        # Voice selection
        voice_sizer = wx.BoxSizer(wx.HORIZONTAL)
        voice_label = wx.StaticText(panel, label=_("Voice:"))
        voice_sizer.Add(voice_label, flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)

        # Get available voices
        voices = []
        if sr.stereo_speech:
            voices = sr.stereo_speech.get_available_voices()

        voice_choice = wx.Choice(panel, choices=voices if voices else [_("No voices available")])
        current_voice = int(sr.settings['TitanScreenReader'].get('voice_index', '0'))
        if voices and 0 <= current_voice < len(voices):
            voice_choice.SetSelection(current_voice)
        elif voices:
            voice_choice.SetSelection(0)

        voice_sizer.Add(voice_choice, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(voice_sizer, flag=wx.ALL | wx.EXPAND, border=10)

        # Rate slider
        rate_sizer = wx.BoxSizer(wx.HORIZONTAL)
        rate_label = wx.StaticText(panel, label=_("Rate:"))
        rate_sizer.Add(rate_label, flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)

        current_rate = int(sr.settings['TitanScreenReader'].get('rate', '0'))
        rate_slider = wx.Slider(panel, value=current_rate, minValue=-10, maxValue=10, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        rate_sizer.Add(rate_slider, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(rate_sizer, flag=wx.ALL | wx.EXPAND, border=10)

        # Pitch slider
        pitch_sizer = wx.BoxSizer(wx.HORIZONTAL)
        pitch_label = wx.StaticText(panel, label=_("Pitch:"))
        pitch_sizer.Add(pitch_label, flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)

        current_pitch = int(sr.settings['TitanScreenReader'].get('pitch', '0'))
        pitch_slider = wx.Slider(panel, value=current_pitch, minValue=-10, maxValue=10, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        pitch_sizer.Add(pitch_slider, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(pitch_sizer, flag=wx.ALL | wx.EXPAND, border=10)

        # Volume slider
        volume_sizer = wx.BoxSizer(wx.HORIZONTAL)
        volume_label = wx.StaticText(panel, label=_("Volume:"))
        volume_sizer.Add(volume_label, flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)

        current_volume = int(sr.settings['TitanScreenReader'].get('volume', '100'))
        volume_slider = wx.Slider(panel, value=current_volume, minValue=0, maxValue=100, style=wx.SL_HORIZONTAL | wx.SL_LABELS)
        volume_sizer.Add(volume_slider, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        vbox.Add(volume_sizer, flag=wx.ALL | wx.EXPAND, border=10)

        # Echo checkbox
        echo_cb = wx.CheckBox(panel, label=_("Echo (speak typed characters)"))
        echo_enabled = sr.settings['TitanScreenReader'].get('echo', 'True').lower() == 'true'
        echo_cb.SetValue(echo_enabled)
        vbox.Add(echo_cb, flag=wx.ALL, border=10)

        # Speak role checkbox
        speak_role_cb = wx.CheckBox(panel, label=_("Speak control type"))
        speak_role = sr.settings['TitanScreenReader'].get('speak_role', 'True').lower() == 'true'
        speak_role_cb.SetValue(speak_role)
        vbox.Add(speak_role_cb, flag=wx.ALL, border=10)

        # Stereo positioning checkbox
        stereo_cb = wx.CheckBox(panel, label=_("Stereo positioning"))
        stereo_enabled = sr.settings['TitanScreenReader'].get('stereo_positioning', 'True').lower() == 'true'
        stereo_cb.SetValue(stereo_enabled)
        vbox.Add(stereo_cb, flag=wx.ALL, border=10)

        # Status info
        status_text = _("Status: ") + (_("Enabled") if sr.enabled else _("Disabled"))
        status_label = wx.StaticText(panel, label=status_text)
        vbox.Add(status_label, flag=wx.ALL, border=10)

        # Buttons
        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, wx.ID_OK, _("Save"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, _("Cancel"))
        test_btn = wx.Button(panel, wx.ID_ANY, _("Test Voice"))
        buttons_sizer.Add(save_btn, flag=wx.ALL, border=5)
        buttons_sizer.Add(cancel_btn, flag=wx.ALL, border=5)
        buttons_sizer.Add(test_btn, flag=wx.ALL, border=5)
        vbox.Add(buttons_sizer, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        # Test voice handler
        def on_test(event):
            # Apply temporary settings for test
            test_voice_index = voice_choice.GetSelection()
            test_rate = rate_slider.GetValue()
            test_pitch = pitch_slider.GetValue()
            test_volume = volume_slider.GetValue()

            if sr.stereo_speech:
                sr.stereo_speech.set_voice(test_voice_index)
                sr.stereo_speech.set_rate(test_rate)
                sr.stereo_speech.set_volume(test_volume)

                # Test with stereo positioning
                if stereo_cb.GetValue():
                    sr.stereo_speech.speak(_("Left channel test"), position=-1.0, pitch_offset=test_pitch, use_fallback=True)
                    time.sleep(1)
                    sr.stereo_speech.speak(_("Center test"), position=0.0, pitch_offset=test_pitch, use_fallback=True)
                    time.sleep(1)
                    sr.stereo_speech.speak(_("Right channel test"), position=1.0, pitch_offset=test_pitch, use_fallback=True)
                else:
                    sr.stereo_speech.speak(_("This is a voice test"), position=0.0, pitch_offset=test_pitch, use_fallback=True)

        test_btn.Bind(wx.EVT_BUTTON, on_test)

        # Save handler
        def on_save(event):
            # Save settings
            enabled = enable_cb.GetValue()
            sr.settings['TitanScreenReader']['enabled'] = str(enabled)
            sr.settings['TitanScreenReader']['voice_index'] = str(voice_choice.GetSelection())
            sr.settings['TitanScreenReader']['rate'] = str(rate_slider.GetValue())
            sr.settings['TitanScreenReader']['pitch'] = str(pitch_slider.GetValue())
            sr.settings['TitanScreenReader']['volume'] = str(volume_slider.GetValue())
            sr.settings['TitanScreenReader']['echo'] = str(echo_cb.GetValue())
            sr.settings['TitanScreenReader']['speak_role'] = str(speak_role_cb.GetValue())
            sr.settings['TitanScreenReader']['stereo_positioning'] = str(stereo_cb.GetValue())
            sr.save_settings()

            # Apply settings
            sr.apply_settings()

            # Enable/disable screen reader
            if enabled and not sr.enabled:
                sr.enable()
            elif not enabled and sr.enabled:
                sr.disable()

            # Update echo
            echo_enabled = echo_cb.GetValue()
            if echo_enabled and not sr.echo_enabled and sr.enabled:
                sr.enable_echo()
            elif not echo_enabled and sr.echo_enabled:
                sr.disable_echo()

            dlg.EndModal(wx.ID_OK)

        save_btn.Bind(wx.EVT_BUTTON, on_save)
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CANCEL))

        panel.SetSizer(vbox)
        dlg.ShowModal()
        dlg.Destroy()

    except Exception as e:
        print(f"[Titan SR] Error showing settings dialog: {e}")
        import traceback
        traceback.print_exc()

        if parent:
            wx.MessageBox(f"Error opening settings: {e}", "Error", wx.OK | wx.ICON_ERROR, parent)


def on_settings_menu_action(event):
    """Menu action handler"""
    show_settings_dialog(None)


def add_menu(component_manager):
    """Register menu item"""
    try:
        component_manager.register_menu_function(_("Titan Screen Reader..."), on_settings_menu_action)
        print("[Titan SR] Menu registered")
    except Exception as e:
        print(f"[Titan SR] Error registering menu: {e}")


def add_settings(settings_frame):
    """Add settings panel (optional)"""
    pass


def initialize(app=None):
    """Initialize component"""
    try:
        print("[Titan SR] Initializing Titan Screen Reader...")

        # Check dependencies
        if not WIN32_AVAILABLE:
            print("[Titan SR] pywin32 not available - component disabled")
            return

        if not PYWINAUTO_AVAILABLE:
            print("[Titan SR] pywinauto not available - component disabled")
            return

        # Initialize screen reader
        sr = get_screen_reader()

        # Auto-enable if previously enabled
        if sr.settings['TitanScreenReader'].get('enabled', 'False').lower() == 'true':
            sr.enable()

        print("[Titan SR] Titan Screen Reader initialized")

    except Exception as e:
        print(f"[Titan SR] Error during initialization: {e}")
        import traceback
        traceback.print_exc()


def shutdown():
    """Shutdown component"""
    global _screen_reader

    try:
        print("[Titan SR] Shutting down Titan Screen Reader...")

        if _screen_reader:
            _screen_reader.disable()
            _screen_reader = None

        print("[Titan SR] Titan Screen Reader shutdown complete")

    except Exception as e:
        print(f"[Titan SR] Error during shutdown: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    # Test component
    print("Testing Titan Screen Reader Component...")
    print(f"pywinauto available: {PYWINAUTO_AVAILABLE}")
    print(f"pywin32 available: {WIN32_AVAILABLE}")
    print(f"stereo_speech available: {STEREO_SPEECH_AVAILABLE}")
    print(f"keyboard available: {KEYBOARD_AVAILABLE}")

    initialize()

    sr = get_screen_reader()
    print(f"Screen reader enabled: {sr.enabled}")

    # Enable for testing
    if not sr.enabled:
        sr.enable()

    print("Screen reader running. Press Ctrl+C to exit.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        shutdown()
        print("Component test completed!")
