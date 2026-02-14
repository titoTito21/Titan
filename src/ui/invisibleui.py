import threading
import time
import accessible_output3.outputs.auto

# keyboard module - works on Windows, may require root on Linux
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False
    print("Warning: keyboard module not available - hotkeys disabled")
from src.titan_core.sound import play_sound, play_focus_sound, play_endoflist_sound, play_statusbar_sound, play_applist_sound, play_voice_message, toggle_voice_message, is_voice_message_playing, is_voice_message_paused, resource_path, get_sfx_directory
from src.settings.settings import load_settings, get_setting
from src.titan_core.translation import set_language
from src.titan_core.app_manager import get_applications, open_application
from src.titan_core.game_manager import get_games, open_game
from src.titan_core.statusbar_applet_manager import StatusbarAppletManager
from src.titan_core.stereo_speech import get_stereo_speech, speak_stereo
from src.ui import componentmanagergui
from src.ui import settingsgui
import sys
from src.ui.help import show_help
import wx
import os
import importlib.util
import json
import traceback
import re
import platform
# F6 program switching removed
try:
    from src.network import telegram_client
    from src.network import messenger_client
except ImportError:
    telegram_client = None
    messenger_client = None
    print("Warning: Telegram/Messenger clients not available")

_ = set_language(get_setting('language', 'pl'))
# Thread-safe speaker initialization
speaker = None
speaker_lock = threading.Lock()

def get_safe_speaker():
    """Get speaker instance safely with proper threading and error handling"""
    # Skip speaker access during Python shutdown
    import sys
    if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
        return None

    global speaker
    if speaker is None:
        try:
            with speaker_lock:
                if speaker is None:  # Double-check pattern
                    try:
                        speaker = accessible_output3.outputs.auto.Auto()
                    except Exception as e:
                        print(f"Error initializing speaker: {e}")
                        return None
        except (RuntimeError, Exception):
            # Lock may not be available during shutdown
            return None
    return speaker

def cleanup_speaker():
    """Safely cleanup the speaker instance"""
    # Skip cleanup during Python shutdown
    import sys
    if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
        return

    global speaker
    try:
        with speaker_lock:
            if speaker is not None:
                try:
                    if hasattr(speaker, 'close'):
                        speaker.close()
                except (AttributeError, Exception):
                    pass  # Speaker may not have close method or may already be closed
                speaker = None
    except (RuntimeError, Exception):
        # Lock may not be available during shutdown
        pass

class GlobalHotKeys(threading.Thread):
    """Global hotkey handler using keyboard library without event suppression"""

    def __init__(self, hotkeys):
        super().__init__()
        self.hotkeys = hotkeys
        self.registered_hotkeys = []
        self.daemon = True
        self._stop_event = threading.Event()

    def run(self):
        """Run the hotkey listener with error handling"""
        try:
            if not self.hotkeys:
                return

            if not KEYBOARD_AVAILABLE:
                print("Keyboard module not available - hotkeys disabled")
                return

            # Register all hotkeys with suppression
            for hotkey_str, callback in self.hotkeys.items():
                # Convert pynput format to keyboard library format
                # '<ctrl>+<shift>+<up>' -> 'ctrl+shift+up'
                kb_hotkey = hotkey_str.replace('<', '').replace('>', '')

                try:
                    # Register hotkeys with event suppression to prevent system from processing them
                    hotkey_handle = keyboard.add_hotkey(kb_hotkey, callback, suppress=True)
                    self.registered_hotkeys.append((kb_hotkey, hotkey_handle))
                except Exception as e:
                    print(f"Error registering hotkey {kb_hotkey}: {e}")

            # Wait for stop event
            self._stop_event.wait()

        except Exception as e:
            print(f"Error in GlobalHotKeys thread: {e}")
        finally:
            self._cleanup()

    def stop(self):
        """Stop the hotkey listener safely"""
        try:
            self._stop_event.set()
        except Exception as e:
            print(f"Error in GlobalHotKeys.stop(): {e}")
        finally:
            self._cleanup()

    def _cleanup(self):
        """Clean up resources and unhook all hotkeys"""
        try:
            if not KEYBOARD_AVAILABLE:
                return

            # Unregister all hotkeys using the stored handles
            for kb_hotkey, hotkey_handle in self.registered_hotkeys:
                try:
                    keyboard.remove_hotkey(hotkey_handle)
                except Exception as e:
                    print(f"Error removing hotkey {kb_hotkey}: {e}")

            self.registered_hotkeys.clear()
        except Exception as e:
            print(f"Error in cleanup: {e}")

class BaseWidget:
    def __init__(self, speak_func):
        # speak_func jest metodą z InvisibleUI która już obsługuje stereo
        self.speak = speak_func
        self.view = None
        # Control type strings for translation
        self._control_types = {
            'slider': _("slider"),
            'button': _("button"), 
            'checkbox': _("checkbox"),
            'list item': _("list item")
        }
    
    def speak_with_position(self, text, position=0.0, pitch_offset=0):
        """
        Wypowiada tekst z pozycjonowaniem stereo dla widgetów.
        Używa tego samego systemu stereo speech co główny interface.
        
        Args:
            text (str): Tekst do wypowiedzenia
            position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo)
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
        """
        # Używaj bezpośrednio metody speak z InvisibleUI która obsługuje stereo
        self.speak(text, position=position, pitch_offset=pitch_offset)

    def set_border(self):
        if self.view:
            try:
                self.view.setStyleSheet("border: 1px solid black;")
            except AttributeError:
                pass

    def get_current_element(self):
        raise NotImplementedError

    def navigate(self, direction):
        """
        Navigates within the widget.
        Should return a tuple: (success, current_horizontal_index, total_horizontal_items).
        - success (bool): True if navigation was successful, False otherwise.
        - current_horizontal_index (int): The new index on the horizontal axis (e.g., column).
        - total_horizontal_items (int): The total number of items on the horizontal axis.
        For vertical navigation or widgets without a horizontal axis, this can return (success, 0, 1).
        """
        raise NotImplementedError

class VolumePanel(BaseWidget):
    def __init__(self, speak_func):
        super().__init__(speak_func)
        self.current_index = 0  # 0 = volume slider, 1 = mute button
        
        # COM interface cache to prevent hangs
        self._volume_interface = None
        self._com_initialized = False
        
        self.volume_level = self.get_current_volume()
        self.is_muted = self.get_mute_status()
        
        # Debounce timer for volume changes
        self._volume_timer = None
        
    def get_current_volume(self):
        """Get current system volume level as integer 0-100"""
        try:
            if platform.system() == "Windows":
                volume_interface = self._get_volume_interface()
                if volume_interface:
                    return int(volume_interface.GetMasterVolumeLevelScalar() * 100)
                else:
                    return 50
            else:
                # Linux fallback
                return 50
        except Exception as e:
            print(f"Error getting current volume: {e}")
            return 50
    
    def get_mute_status(self):
        """Get current mute status"""
        try:
            if platform.system() == "Windows":
                volume_interface = self._get_volume_interface()
                if volume_interface:
                    return volume_interface.GetMute()
                else:
                    return False
            else:
                return False
        except Exception as e:
            print(f"Error getting mute status: {e}")
            return False
    
    def _get_volume_interface(self):
        """Get cached volume interface to avoid COM initialization overhead"""
        # Skip COM operations during shutdown
        import sys
        if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
            return None

        if self._volume_interface is None and platform.system() == "Windows":
            try:
                from comtypes import CoInitializeEx, COINIT_APARTMENTTHREADED
                from pycaw.pycaw import AudioUtilities

                if not self._com_initialized:
                    try:
                        # Use apartment threading to avoid COM issues
                        CoInitializeEx(COINIT_APARTMENTTHREADED)
                        self._com_initialized = True
                    except OSError as e:
                        # COM may already be initialized in this thread
                        if e.winerror == -2147417850:  # RPC_E_CHANGED_MODE
                            self._com_initialized = True
                        else:
                            print(f"COM initialization failed: {e}")
                            return None
                    except Exception as e:
                        print(f"COM initialization failed: {e}")
                        return None

                # Timeout protection for COM calls
                import threading
                result = [None]
                error = [None]

                def get_interface():
                    try:
                        devices = AudioUtilities.GetSpeakers()
                        if devices is None:
                            error[0] = "No audio devices found"
                            return

                        # In newer pycaw versions (20251023+), EndpointVolume is a property
                        volume_interface = devices.EndpointVolume
                        if volume_interface is None:
                            error[0] = "Failed to get audio endpoint volume"
                            return

                        result[0] = volume_interface
                    except Exception as e:
                        error[0] = str(e)

                # Run COM operation with timeout using Event instead of blocking join()
                complete_event = threading.Event()

                def get_interface_with_event():
                    get_interface()
                    complete_event.set()

                thread = threading.Thread(target=get_interface_with_event, daemon=True)
                thread.start()

                # Wait for completion or timeout without blocking indefinitely
                if not complete_event.wait(timeout=2.0):
                    print("Warning: COM operation timed out")
                    return None

                if error[0]:
                    print(f"Error getting volume interface: {error[0]}")
                    return None

                self._volume_interface = result[0]

            except (ImportError, OSError, AttributeError) as e:
                print(f"Error initializing volume interface: {e}")
                return None
            except Exception as e:
                print(f"Unexpected error initializing volume interface: {e}")
                return None
        return self._volume_interface
    
    def cleanup(self):
        """Cleanup COM resources safely"""
        # Don't cleanup during Python shutdown
        import sys
        if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
            return

        try:
            if hasattr(self, '_volume_timer') and self._volume_timer:
                self._volume_timer.cancel()
                self._volume_timer = None
        except (AttributeError, Exception):
            pass

        try:
            if hasattr(self, '_volume_interface') and self._volume_interface:
                # Release COM object before uninitializing
                self._volume_interface = None
        except (AttributeError, Exception):
            pass

        try:
            if hasattr(self, '_com_initialized') and self._com_initialized:
                try:
                    import comtypes
                    # Only uninitialize if not shutting down
                    if not (hasattr(sys, 'is_finalizing') and sys.is_finalizing()):
                        comtypes.CoUninitialize()
                except (ImportError, OSError, Exception):
                    pass  # Prevent COM cleanup errors during shutdown
                self._com_initialized = False
        except (AttributeError, Exception):
            pass

    def __del__(self):
        """Destructor to cleanup COM resources"""
        # Skip cleanup during Python shutdown to prevent crashes
        import sys
        if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
            return
        try:
            if hasattr(self, '_com_initialized') and hasattr(self, '_volume_interface'):
                self.cleanup()
        except (AttributeError, OSError, Exception):
            pass  # Prevent segfaults during shutdown
    
    def set_volume(self, level):
        """Set system volume level (0-100) with debouncing"""
        # Update local value immediately for responsive UI
        self.volume_level = level
        
        # Debounce the actual COM call to prevent hangs
        if self._volume_timer:
            self._volume_timer.cancel()
        
        def update_volume():
            try:
                if platform.system() == "Windows":
                    volume_interface = self._get_volume_interface()
                    if volume_interface:
                        volume_interface.SetMasterVolumeLevelScalar(level / 100.0, None)
                        return True
                else:
                    # Linux implementation could be added here
                    return True
            except Exception as e:
                print(f"Error setting volume: {e}")
                return False
        
        import threading
        self._volume_timer = threading.Timer(0.1, update_volume)
        self._volume_timer.start()
        
        return True  # Return True immediately for responsive UI
    
    def toggle_mute(self):
        """Toggle mute status"""
        try:
            if platform.system() == "Windows":
                volume_interface = self._get_volume_interface()
                if volume_interface:
                    current_mute = volume_interface.GetMute()
                    volume_interface.SetMute(not current_mute, None)
                    self.is_muted = volume_interface.GetMute()
                    return True
            else:
                self.is_muted = not self.is_muted
                return True
        except Exception as e:
            print(f"Error toggling mute: {e}")
            return False
    
    def get_current_element(self):
        from settings import get_setting
        announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
        
        if self.current_index == 0:
            if announce_widget_type:
                return _("Volume {}%, {}").format(self.volume_level, _("slider"))
            else:
                return _("Volume: {}%").format(self.volume_level)
        else:
            if self.is_muted:
                if announce_widget_type:
                    return _("Unmute, {}").format(_("button"))
                else:
                    return _("Unmute")
            else:
                if announce_widget_type:
                    return _("Mute, {}").format(_("button"))
                else:
                    return _("Mute")
    
    def navigate(self, direction):
        if direction == "left":
            # Move to volume slider
            if self.current_index != 0:
                self.current_index = 0
                return (True, 0, 2)
        elif direction == "right":
            # Move to mute button  
            if self.current_index != 1:
                self.current_index = 1
                return (True, 1, 2)
        elif direction == "up":
            if self.current_index == 0:  # Only work on volume slider
                # Volume slider - increase by 5%
                new_volume = min(100, self.volume_level + 5)
                if self.set_volume(new_volume):
                    return (True, 0, 1)
        elif direction == "down":
            if self.current_index == 0:  # Only work on volume slider
                # Volume slider - decrease by 5%
                new_volume = max(0, self.volume_level - 5)
                if self.set_volume(new_volume):
                    return (True, 0, 1)
        
        return (False, self.current_index, 2)
    
    def activate_current_element(self):
        if self.current_index == 1:
            # Toggle mute
            if self.toggle_mute():
                self.is_muted = self.get_mute_status()
                if self.is_muted:
                    play_sound('core/mute.ogg' if os.path.exists(resource_path(os.path.join(get_sfx_directory(), 'core/mute.ogg'))) else 'core/SELECT.ogg')
                    self.speak(_("Muted"))
                else:
                    play_sound('core/unmute.ogg' if os.path.exists(resource_path(os.path.join(get_sfx_directory(), 'core/unmute.ogg'))) else 'core/SELECT.ogg')
                    self.speak(_("Unmuted"))

class InvisibleUI:
    def __init__(self, main_frame, component_manager=None):
        self.main_frame = main_frame
        self.component_manager = component_manager
        self.categories = []
        self.current_category_index = 0
        self.current_element_index = 0
        self.active = False
        self.lock = threading.RLock()  # Use RLock to prevent deadlocks
        self.refresh_thread = None
        self.stop_event = threading.Event()
        self.hotkey_thread = None  # For keyboard library (Titan UI simple keys)
        self.in_widget_mode = False
        self.active_widget = None
        self.active_widget_name = None
        self.last_widget_element = None
        self.titan_ui_mode = False
        self.titan_ui_temporarily_disabled = False
        self.disabled_by_dialog = None
        self.titan_im_mode = None
        self.current_contacts = []
        self.current_groups = []
        self.current_chat_history = []
        self.current_chat_user = None
        self.titan_im_submenu = None
        self.current_voice_message_path = None
        self.current_selected_message = None
        self._shutdown_in_progress = False
        self.debug_log = []  # Store debug messages in memory

        # Game platform navigation state
        self.in_game_platform = False  # Track if we're inside a platform subfolder
        self.game_platform_backup = None  # Backup of Games category before entering platform

        # Safe initialization
        try:
            self.build_structure()
            # Apply IUI hooks from components after structure is built
            if self.component_manager:
                try:
                    self.component_manager.apply_iui_hooks(self)
                except Exception as e:
                    print(f"Warning: Failed to apply IUI hooks: {e}")
        except Exception as e:
            print(f"Error during InvisibleUI initialization: {e}")
            import traceback
            traceback.print_exc()
            # Write debug log to file
            try:
                with open("invisibleui_error.log", "w", encoding="utf-8") as f:
                    f.write(f"Error: {e}\n\n")
                    f.write("Debug log:\n")
                    for msg in self.debug_log:
                        f.write(msg + "\n")
                    f.write("\nFull traceback:\n")
                    traceback.print_exc(file=f)
            except:
                pass
    
    def __del__(self):
        """Safe cleanup on destruction"""
        # Skip cleanup during Python shutdown to prevent crashes
        import sys
        if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
            return
        try:
            if hasattr(self, '_shutdown_in_progress'):
                self._shutdown_in_progress = True
            if hasattr(self, 'stop_listening'):
                self.stop_listening()
        except Exception:
            pass  # Prevent segfaults during shutdown

    def refresh_status_bar(self):
        with self.lock:
            for category in self.categories:
                if category["name"] == _("Status Bar"):
                    category["elements"] = self.get_statusbar_items()
                    break

    def _run(self):
        while not self.stop_event.is_set():
            self.refresh_status_bar()
            time.sleep(1)

    def build_structure(self):
        try:
            self.debug_log.append("DEBUG: Getting applications...")
            apps_data = get_applications()
            self.debug_log.append(f"DEBUG: Apps data type: {type(apps_data)}, first item: {apps_data[0] if apps_data else 'empty'}")
            apps = [app['name'] for app in apps_data]
            self.debug_log.append(f"DEBUG: Apps list created successfully")
        except Exception as e:
            self.debug_log.append(f"ERROR in apps: {e}")
            import traceback
            import io
            buf = io.StringIO()
            traceback.print_exc(file=buf)
            self.debug_log.append(buf.getvalue())
            apps = []

        try:
            self.debug_log.append("DEBUG: Getting games by platform...")
            from src.titan_core.game_manager import get_games_by_platform
            games_by_platform = get_games_by_platform()
            self.debug_log.append(f"DEBUG: Games by platform: {games_by_platform.keys()}")

            # Store platform data for navigation
            self.games_by_platform_data = games_by_platform
            self.games_platform_subcategories = {}  # Store subcategories for each platform

            platform_order = ['Titan-Games', 'Steam', 'Battle.net']
            platform_names = []

            for platform in platform_order:
                if platform in games_by_platform and games_by_platform[platform]:
                    platform_name = _(platform)
                    platform_names.append(platform_name)
                    # Create subcategory for this platform
                    platform_games = [game['name'] for game in games_by_platform[platform]]
                    self.games_platform_subcategories[platform_name] = {
                        "name": platform_name,
                        "sound": "core/focus.ogg",
                        "elements": platform_games,
                        "action": self.launch_game_by_name,
                        "parent": "Games"
                    }

            # Create single Games category with platforms as elements
            if platform_names:
                games = platform_names
            else:
                games = [_("No games")]
                self.games_platform_subcategories = {}

            self.debug_log.append(f"DEBUG: Games category created with {len(platform_names)} platforms")
        except Exception as e:
            self.debug_log.append(f"ERROR in games: {e}")
            import traceback
            import io
            buf = io.StringIO()
            traceback.print_exc(file=buf)
            self.debug_log.append(buf.getvalue())
            games = [_("No games")]
            self.games_by_platform_data = {}
            self.games_platform_subcategories = {}

        try:
            self.debug_log.append("DEBUG: Loading widgets...")
            widgets = self.load_widgets()
            self.debug_log.append(f"DEBUG: Widgets loaded: {len(widgets)} widgets")
        except Exception as e:
            self.debug_log.append(f"ERROR in widgets: {e}")
            import traceback
            import io
            buf = io.StringIO()
            traceback.print_exc(file=buf)
            self.debug_log.append(buf.getvalue())
            widgets = []

        # Initialize statusbar applet manager
        try:
            self.debug_log.append("DEBUG: Loading statusbar applet manager...")
            self.statusbar_applet_manager = StatusbarAppletManager()
            self.debug_log.append(f"DEBUG: Loaded {len(self.statusbar_applet_manager.get_applet_names())} statusbar applets")
        except Exception as e:
            self.debug_log.append(f"ERROR loading statusbar applet manager: {e}")
            import traceback
            import io
            buf = io.StringIO()
            traceback.print_exc(file=buf)
            self.debug_log.append(buf.getvalue())
            self.statusbar_applet_manager = None

        def show_component_manager():
            if self.component_manager:
                # Auto-disable Titan UI when component manager dialog opens
                if self.titan_ui_mode:
                    self.temporarily_disable_titan_ui("component_manager")
                dialog = componentmanagergui.ComponentManagerDialog(self.main_frame, _("Component Manager"), self.component_manager)
                # Bind close event to re-enable Titan UI if it was disabled
                dialog.Bind(wx.EVT_CLOSE, lambda evt: self._on_dialog_close("component_manager", evt))
                dialog.ShowModal()
                # Re-enable Titan UI after modal dialog closes
                self._on_dialog_close("component_manager", None)
                dialog.Destroy()
            else:
                self.speak(_("Component manager is not available"))

        def show_settings():
            # Auto-disable Titan UI when settings dialog opens
            if self.titan_ui_mode:
                self.temporarily_disable_titan_ui("settings")
            # Use the existing settings_frame from main_frame instead of creating a new one
            settings_frame = getattr(self.main_frame, 'settings_frame', None)
            if settings_frame is None:
                # Fallback: create new one if not available (shouldn't happen in normal flow)
                settings_frame = settingsgui.SettingsFrame(None, title=_("Settings"))
            # Bind close event to re-enable Titan UI if it was disabled
            settings_frame.Bind(wx.EVT_CLOSE, lambda evt: self._on_dialog_close("settings", evt))
            settings_frame.Show()

        def safe_call_after(func):
            """Safely call wx.CallAfter only if main_frame exists"""
            try:
                if self.main_frame and hasattr(self.main_frame, 'IsShown'):
                    wx.CallAfter(func)
                else:
                    print("Cannot call wx.CallAfter - main_frame not available")
            except Exception as e:
                print(f"Error in safe_call_after: {e}")

        # DISABLED - Titan-Net login
        # def show_titan_net_login():
        #     """Show Titan-Net login dialog"""
        #     if self.main_frame and hasattr(self.main_frame, 'titan_client'):
        #         # Check if already logged in
        #         if hasattr(self.main_frame, 'active_services') and "titannet" in self.main_frame.active_services:
        #             self.speak(_("You are already logged in to Titan-Network"))
        #             return

        #         # Import show_login_dialog
        #         from titan_net_gui import show_login_dialog

        #         # Restore window from tray if needed
        #         if not self.main_frame.IsShown():
        #             self.main_frame.restore_from_tray()

        #         # Show login dialog
        #         logged_in, offline_mode = show_login_dialog(self.main_frame, self.main_frame.titan_client)

        #         if logged_in:
        #             # Store in active services
        #             if hasattr(self.main_frame, 'active_services'):
        #                 self.main_frame.active_services["titannet"] = {
        #                     "client": self.main_frame.titan_client,
        #                     "type": "titannet",
        #                     "name": "Titan-Net",
        #                     "online_users": [],
        #                     "unread_messages": {},
        #                     "user_data": {
        #                         "username": self.main_frame.titan_client.username,
        #                         "titan_number": self.main_frame.titan_client.titan_number
        #                     }
        #                 }

        #             # Update UI if methods exist
        #             if hasattr(self.main_frame, 'populate_network_list'):
        #                 self.main_frame.populate_network_list()
        #         elif offline_mode:
        #             # User chose offline mode
        #             # Application continues without Titan-Net connection
        #             pass
        #     else:
        #         self.speak(_("Titan-Net client not initialized"))

        # Main menu actions
        main_menu_actions = {
            _("Component Manager"): lambda: safe_call_after(show_component_manager),
            # _("Log in to Titan-Network"): lambda: safe_call_after(show_titan_net_login),  # DISABLED
            _("Program settings"): lambda: safe_call_after(show_settings),
            _("Help"): lambda: safe_call_after(show_help),
            _("Back to graphical interface"): lambda: safe_call_after(self.main_frame.restore_from_tray) if self.main_frame else None,
            _("Exit"): lambda: safe_call_after(lambda: self.main_frame.Close()) if self.main_frame else None
        }

        # Component menu actions
        component_menu_actions = {}
        if self.component_manager:
            component_menu_functions = self.component_manager.get_component_menu_functions()
            for name, func in component_menu_functions.items():
                # Wrap component function to ensure main window is shown
                def make_component_wrapper(component_func):
                    def wrapper(event):
                        # Restore window from tray if hidden
                        if self.main_frame and not self.main_frame.IsShown():
                            self.main_frame.restore_from_tray()
                            # Call component after a short delay to allow window to fully restore
                            wx.CallLater(200, component_func, None)
                        else:
                            wx.CallAfter(component_func, None)
                    return wrapper
                component_menu_actions[name] = make_component_wrapper(func)

        # Build Titan IM menu
        titan_im_elements = []
        if telegram_client:
            titan_im_elements.append(_("Telegram"))

        # Add web applications like in gui.py (remove native messenger client)
        titan_im_elements.append(_("Facebook Messenger"))
        titan_im_elements.append(_("WhatsApp"))
        titan_im_elements.append(_("Titan-Net (Beta)"))
        titan_im_elements.append(_("EltenLink (Beta)"))
        try:
            from src.network.im_module_manager import im_module_manager
            for name in im_module_manager.get_module_names():
                titan_im_elements.append(name)
        except Exception as _e:
            print(f"[IUI] IM modules: {_e}")

        if not titan_im_elements:
            titan_im_elements = [_("No IM clients available")]

        try:
            self.debug_log.append(f"DEBUG: Building categories...")
            self.debug_log.append(f"DEBUG: Widgets type: {type(widgets)}, content: {widgets}")

            # Build widget names safely
            if widgets:
                widget_names = []
                for i, w in enumerate(widgets):
                    self.debug_log.append(f"DEBUG: Widget {i}: type={type(w)}, value={w}")
                    widget_names.append(w['name'])
                self.debug_log.append(f"DEBUG: Widget names created: {widget_names}")
            else:
                widget_names = [_("No widgets found")]

            self.debug_log.append(f"DEBUG: Getting status bar items...")
            statusbar_items = self.get_statusbar_items()
            self.debug_log.append(f"DEBUG: Status bar items: {statusbar_items}")

            # Build main categories
            self.categories = [
                {"name": _("Applications"), "sound": "core/focus.ogg", "elements": apps if apps else [_("No applications")], "action": self.launch_app_by_name},
                {"name": _("Games"), "sound": "core/focus.ogg", "elements": games, "action": self.expand_game_platform}
            ]

            # Add remaining categories
            self.categories.extend([
                {"name": _("Widgets"), "sound": "core/focus.ogg", "elements": widget_names, "action": self.activate_widget, "widget_data": widgets},
                {"name": _("Titan IM"), "sound": "titannet/iui.ogg", "elements": titan_im_elements, "action": self.activate_titan_im},
                {"name": _("Status Bar"), "sound": "statusbar.ogg", "elements": statusbar_items, "action": self.activate_statusbar_item},
                {"name": _("Menu"), "sound": "ui/applist.ogg", "elements": list(main_menu_actions.keys()), "action": lambda name: main_menu_actions[name]()}
            ])
            self.debug_log.append(f"DEBUG: Categories built successfully")
        except Exception as e:
            self.debug_log.append(f"ERROR building categories: {e}")
            import traceback
            import io
            buf = io.StringIO()
            traceback.print_exc(file=buf)
            self.debug_log.append(buf.getvalue())
            raise

        # Add Components as a separate category if there are any component menu actions
        if component_menu_actions:
            self.categories.append({"name": _("Components"), "sound": "applist.ogg", "elements": list(component_menu_actions.keys()), "action": lambda name: component_menu_actions.get(name, lambda event: self.speak(_("Component not found")))(None)})


    def load_widgets(self):
        widgets = []
        try:
            # Get project root directory (supports PyInstaller and Nuitka)
            applets_dir = resource_path(os.path.join('data', 'applets'))
            if not os.path.exists(applets_dir):
                return widgets

            for applet_name in os.listdir(applets_dir):
                try:
                    applet_dir = os.path.join(applets_dir, applet_name)
                    if not os.path.isdir(applet_dir):
                        continue

                    # Sprawdź plik init.py dla wstecznej zgodności
                    init_file = os.path.join(applet_dir, 'init.py')
                    if os.path.exists(init_file):
                        try:
                            spec = importlib.util.spec_from_file_location(applet_name, init_file)
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)

                            info = module.get_widget_info()
                            widgets.append({
                                "name": info["name"],
                                "type": info["type"],
                                "module": module
                            })
                            continue # Przejdź do następnego apletu
                        except Exception as e:
                            print(f"Error loading widget from init.py '{applet_name}': {e}")
                            try:
                                self.speak(_("Error loading widget: {}").format(applet_name))
                            except:
                                pass  # Don't crash if speak fails

                    # Nowy system oparty na applet.json i main.py
                    json_path = os.path.join(applet_dir, 'applet.json')
                    main_py_path = os.path.join(applet_dir, 'main.py')

                    if os.path.exists(json_path) and os.path.exists(main_py_path):
                        try:
                            spec = importlib.util.spec_from_file_location(f"applets.{applet_name}.main", main_py_path)
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[spec.name] = module
                            spec.loader.exec_module(module)

                            # Po załadowaniu modułu, gettext wewnątrz niego jest już aktywny
                            info = module.get_widget_info()

                            widgets.append({
                                "name": info.get("name", applet_name),
                                "type": info.get("type", "grid"),
                                "module": module
                            })
                        except Exception as e:
                            print(f"Error loading applet '{applet_name}': {e}")
                            traceback.print_exc() # Print full traceback for debugging
                            try:
                                self.speak(_("Error loading widget: {}").format(applet_name))
                            except:
                                pass  # Don't crash if speak fails
                except Exception as e:
                    print(f"Error processing applet folder '{applet_name}': {e}")
                    continue  # Continue with next applet
        except Exception as e:
            print(f"Critical error in load_widgets: {e}")
            traceback.print_exc()  # traceback already imported at module level
        return widgets

    def get_statusbar_items(self):
        # Import here to avoid circular imports
        from src.ui.gui import get_current_time, get_battery_status, get_volume_level, get_network_status
        
        # If GUI is initialized, get from statusbar_listbox
        if self.main_frame and hasattr(self.main_frame, 'statusbar_listbox'):
            return [self.main_frame.statusbar_listbox.GetString(i) for i in range(self.main_frame.statusbar_listbox.GetCount())]
        
        # Otherwise, generate status items directly (for minimized mode)
        try:
            items = [
                _("Clock: {}").format(get_current_time()),
                _("Battery level: {}").format(get_battery_status()),
                _("Volume: {}").format(get_volume_level()),
                get_network_status()
            ]

            # Add statusbar applets
            if hasattr(self, 'statusbar_applet_manager') and self.statusbar_applet_manager:
                for applet_name in self.statusbar_applet_manager.get_applet_names():
                    try:
                        text = self.statusbar_applet_manager.get_applet_text(applet_name)
                        items.append(text)
                    except Exception as e:
                        print(f"Error getting statusbar applet '{applet_name}': {e}")

            return items
        except Exception as e:
            print(f"Error getting status bar items: {e}")
            return [_("No status bar data")]

    def speak(self, text, interrupt=True, position=0.0, pitch_offset=0):
        """
        Wypowiada tekst z opcjonalnym pozycjonowaniem stereo i kontrolą wysokości.

        Args:
            text (str): Tekst do wypowiedzenia
            interrupt (bool): Czy przerwać poprzednią mowę
            position (float): Pozycja stereo od -1.0 (lewo) do 1.0 (prawo), 0.0 = środek
            pitch_offset (int): Przesunięcie wysokości głosu -10 do +10
        """
        # Skip during Python shutdown
        import sys
        if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
            return

        print(f"DEBUG: speak() called with text='{text}', interrupt={interrupt}, position={position}, pitch_offset={pitch_offset}")
        try:
            if not text or self._shutdown_in_progress:
                print("DEBUG: Skipping speech - no text or shutdown in progress")
                return
                
            # Validate parameters to prevent crashes
            try:
                text = str(text)
                position = max(-1.0, min(1.0, float(position)))
                pitch_offset = max(-10, min(10, int(pitch_offset)))
            except (ValueError, TypeError) as e:
                print(f"Invalid speech parameters: {e}")
                return
                
            # Check stereo speech setting safely
            try:
                stereo_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() == 'true'
                
                if stereo_enabled:
                    def speak_with_stereo():
                        try:
                            if self._shutdown_in_progress:
                                return
                            # Zatrzymaj poprzednią mowę jeśli interrupt=True
                            if interrupt:
                                try:
                                    stereo_speech = get_stereo_speech()
                                    if stereo_speech:
                                        stereo_speech.stop()
                                except Exception as e:
                                    print(f"Error stopping stereo speech: {e}")
                            
                            speak_stereo(text, position=position, pitch_offset=pitch_offset, async_mode=True)
                        except Exception as e:
                            print(f"Error in stereo speech: {e}")
                            # Fallback to regular TTS
                            self._speak_fallback(text, interrupt)
                    
                    # Use daemon thread with timeout protection
                    thread = threading.Thread(target=speak_with_stereo, daemon=True)
                    thread.start()
                else:
                    # Standard TTS without stereo
                    def speak_regular():
                        try:
                            if self._shutdown_in_progress:
                                return
                            self._speak_fallback(text, interrupt)
                        except Exception as e:
                            print(f"Error in regular speech: {e}")
                    
                    thread = threading.Thread(target=speak_regular, daemon=True)
                    thread.start()
                    
            except Exception as e:
                print(f"Error getting speech setting: {e}")
                self._speak_fallback(text, interrupt)
                
        except Exception as e:
            print(f"Critical error in speak method: {e}")
    
    def _speak_fallback(self, text, interrupt=True):
        """Safe fallback speech method"""
        try:
            if self._shutdown_in_progress:
                return
            safe_speaker = get_safe_speaker()
            if safe_speaker:
                safe_speaker.speak(text, interrupt=interrupt)
        except Exception as e:
            print(f"Error in fallback speech: {e}")

    def navigate_category(self, step):
        new_index = None
        num_categories = 0
        old_index = 0
        try:
            # Safety check for lock and shutdown
            if (not hasattr(self, 'lock') or self.lock is None or 
                self._shutdown_in_progress):
                return
                
            # Use timeout to prevent deadlocks
            try:
                if not self.lock.acquire(timeout=1.0):
                    print("Warning: Could not acquire navigation lock")
                    return
            except Exception as e:
                print(f"Error acquiring navigation lock: {e}")
                return
                
            try:
                if self.in_widget_mode: 
                    return
                
                # Safety checks
                if not hasattr(self, 'categories') or not self.categories:
                    try:
                        play_endoflist_sound()
                    except Exception as e:
                        print(f"Error playing end of list sound: {e}")
                    return
                
                # Validate and fix indices
                if not isinstance(self.current_category_index, int) or self.current_category_index < 0:
                    self.current_category_index = 0
                
                num_categories = len(self.categories)
                if self.current_category_index >= num_categories:
                    self.current_category_index = max(0, num_categories - 1)
                    
                old_index = self.current_category_index
                new_index = self.current_category_index + step
            finally:
                self.lock.release()
        
            if new_index is not None and 0 <= new_index < num_categories:
                self.current_category_index = new_index
                self.current_element_index = 0
                
                try:
                    new_category = self.categories[new_index]
                    if not isinstance(new_category, dict):
                        print(f"Invalid category at index {new_index}")
                        play_endoflist_sound()
                        return
                except (IndexError, TypeError, AttributeError) as e:
                    print(f"Error accessing category {new_index}: {e}")
                    play_endoflist_sound()
                    return
                
                statusbar_index = -1
                try:
                    statusbar_index = [c.get('name', '') for c in self.categories].index(_("Status Bar"))
                except (ValueError, AttributeError, KeyError):
                    pass

                try:
                    if statusbar_index != -1 and old_index == statusbar_index and (new_index == statusbar_index - 1 or new_index == statusbar_index + 1):
                        play_applist_sound()
                    else:
                        category_name = new_category.get('name', '')
                        if category_name == _("Status Bar"):
                            play_statusbar_sound()
                        else:
                            pan = 0.5
                            if num_categories > 1:
                                pan = new_index / (num_categories - 1)
                            play_sound(new_category.get('sound', 'core/focus.ogg'), pan=pan)
                except Exception as e:
                    play_focus_sound()  # Fallback sound
                    print(f"Error playing category sound: {e}")
                
                try:
                    speak_text = new_category.get('name', 'Unknown category')
                    if get_setting('announce_first_item', 'False', section='invisible_interface').lower() == 'true':
                        elements = new_category.get('elements', [])
                        if elements:
                            speak_text += f", {elements[0]}"
                    
                    # Calculate position for category (vertical navigation)
                    stereo_position = 0.0  # Categories don't use left-right panning
                    pitch_offset = 0
                    if num_categories > 1:
                        # Vertical pitch - higher categories = higher pitch, lower = lower pitch
                        pitch_offset = int((0.5 - (new_index / (num_categories - 1))) * 10)  # Range -5 to +5
                        # Stereo remains 0.0 (center) for category navigation
                    
                    self.speak(speak_text, position=stereo_position, pitch_offset=pitch_offset)
                except Exception as e:
                    print(f"Error speaking category: {e}")
                    try:
                        self.speak("Category")
                    except:
                        pass
            else:
                play_endoflist_sound()
        except Exception as e:
            print(f"Critical error in navigate_category: {e}")
            try:
                play_endoflist_sound()
            except:
                pass

    def navigate_element(self, step):
        category = None
        try:
            # Safety checks
            if self._shutdown_in_progress or not hasattr(self, 'lock'):
                return
                
            # Use timeout to prevent deadlocks
            try:
                if not self.lock.acquire(timeout=1.0):
                    print("Warning: Could not acquire element navigation lock")
                    return
            except Exception as e:
                print(f"Error acquiring element navigation lock: {e}")
                return
                
            try:
                if self.in_widget_mode: 
                    return
                
                if (not hasattr(self, 'categories') or not self.categories or 
                    self.current_category_index >= len(self.categories) or
                    self.current_category_index < 0):
                    play_endoflist_sound()
                    return
                
                try:
                    category = self.categories[self.current_category_index]
                    if not isinstance(category, dict):
                        print(f"Invalid category structure at index {self.current_category_index}")
                        play_endoflist_sound()
                        return
                except (IndexError, TypeError, AttributeError) as e:
                    print(f"Error accessing category: {e}")
                    play_endoflist_sound()
                    return
            finally:
                self.lock.release()
                
            if category is None:
                play_endoflist_sound()
                return
                
            elements = category.get('elements', [])
            num_elements = len(elements)
            if num_elements == 0:
                play_endoflist_sound()
                return
                
            # Ensure current index is within bounds
            if self.current_element_index < 0:
                self.current_element_index = 0
            elif self.current_element_index >= num_elements:
                self.current_element_index = num_elements - 1

            new_index = self.current_element_index + step
            
            if 0 <= new_index < num_elements:
                self.current_element_index = new_index
                
                try:
                    element_name = elements[self.current_element_index]
                    if not element_name or element_name == "":
                        play_endoflist_sound()
                        return
                except (IndexError, TypeError):
                    play_endoflist_sound()
                    return
                
                try:
                    # Pan the sound based on the element's position in the list
                    pan = 0
                    if num_elements > 1:
                        pan = new_index / (num_elements - 1)
                    play_focus_sound(pan=pan)
                except Exception as e:
                    play_focus_sound()  # Fallback
                    print(f"Error playing element focus sound: {e}")
                
                try:
                    announce_index = get_setting('announce_index', 'False', section='invisible_interface').lower() == 'true'
                    announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
                    
                    speak_text = str(element_name)
                    if announce_index:
                        speak_text += ", " + _("{} of {}").format(self.current_element_index + 1, num_elements)
                    
                    try:
                        if announce_widget_type and category.get('name') == _("Widgets") and 'widget_data' in category:
                            widget_data = category.get('widget_data', [])
                            if self.current_element_index < len(widget_data):
                                widget_type = widget_data[self.current_element_index].get('type', '')
                                speak_text += f", {_('button') if widget_type == 'button' else _('widget')}"
                    except Exception as e:
                        print(f"Error adding widget type announcement: {e}")
                    
                    try:
                        # Add web app type announcement for Titan IM menu
                        if announce_widget_type and category.get('name') == _("Titan IM"):
                            if element_name in [_("Facebook Messenger"), _("WhatsApp")]:
                                speak_text += f", {_('web application')}"
                    except Exception as e:
                        print(f"Error adding web app announcement: {e}")
                    
                    # Calculate stereo position for element (horizontal only, no pitch)
                    stereo_position = 0.0
                    pitch_offset = 0  # Elements don't use pitch, only stereo left-right
                    if num_elements > 1:
                        # Pan horizontally (0.0-1.0)
                        pan = new_index / (num_elements - 1)
                        # Convert pan to stereo position (-1.0 to 1.0)
                        stereo_position = (pan * 2.0) - 1.0
                        # Pitch = 0 for left-right navigation
                    
                    self.speak(speak_text, position=stereo_position, pitch_offset=pitch_offset)
                except Exception as e:
                    print(f"Error speaking element: {e}")
                    try:
                        self.speak(str(element_name))
                    except:
                        self.speak("Element")
            else:
                play_endoflist_sound()
        except Exception as e:
            print(f"Critical error in navigate_element: {e}")
            try:
                play_endoflist_sound()
            except:
                pass

    def activate_element(self):
        try:
            with self.lock:
                if self.in_widget_mode:
                    try:
                        if self.active_widget and hasattr(self.active_widget, 'activate_current_element'):
                            self.active_widget.activate_current_element()
                        return
                    except Exception as e:
                        print(f"Error activating widget element: {e}")
                        try:
                            self.speak(_("Widget activation error"))
                        except:
                            pass
                        return

                if not self.categories or self.current_category_index >= len(self.categories):
                    return
                
                try:
                    category = self.categories[self.current_category_index]
                except (IndexError, TypeError):
                    return
                
                elements = category.get('elements', [])
                if not elements or self.current_element_index >= len(elements):
                    return
                
                # Ensure current element index is valid
                if self.current_element_index < 0:
                    self.current_element_index = 0
                elif self.current_element_index >= len(elements):
                    self.current_element_index = len(elements) - 1
                    
                # Check for empty states
                try:
                    first_element = elements[0] if elements else ""
                    if first_element in [_("No applications"), _("No games"), _("No widgets found"), _("Loading messages..."), ""]:
                        if first_element == _("Loading messages..."):
                            self.speak(_("Messages are loading, please wait"))
                        return
                except (IndexError, TypeError):
                    return
                
                try:
                    element_name = elements[self.current_element_index]
                    if not element_name or element_name == "":
                        return
                except (IndexError, TypeError):
                    return
                
                try:
                    # Special handling for chat history with voice messages
                    if (self.titan_ui_mode and self.titan_im_mode and 
                        self.titan_im_submenu == 'history'):
                        # Check if current element contains voice message
                        self.check_for_voice_message(element_name)
                        if self.current_voice_message_path:
                            # This is a voice message - toggle play/pause
                            self.handle_voice_message_toggle()
                            return
                except Exception as e:
                    print(f"Error handling voice message: {e}")
                
                try:
                    play_sound('core/SELECT.ogg')
                except Exception as e:
                    print(f"Error playing selection sound: {e}")
                
                try:
                    if element_name in [_("Back to graphical interface"), _("Exit")]:
                        self.stop_listening()
                except Exception as e:
                    print(f"Error stopping listener: {e}")

                action = category.get('action')
                if action:
                    try:
                        category_name = category.get('name', '')
                        if category_name == _("Widgets"):
                            widget_data_list = category.get('widget_data', [])
                            if self.current_element_index < len(widget_data_list):
                                widget_data = widget_data_list[self.current_element_index]
                                action(widget_data)
                            else:
                                print(f"Widget data index out of range: {self.current_element_index}")
                        else:
                            action(element_name)
                    except Exception as e:
                        try:
                            self.speak(_("Error during activation"))
                        except:
                            pass
                        print(f"Error activating element '{element_name}': {e}")
        except Exception as e:
            print(f"Critical error in activate_element: {e}")
            try:
                self.speak(_("Activation error"))
            except:
                pass

    def activate_widget(self, widget_data):
        try:
            widget_type = widget_data['type']
            module = widget_data['module']

            if widget_type == "button":
                try:
                    self.active_widget = module.get_widget_instance(self.speak)
                    self.active_widget.activate_current_element()
                except Exception as e:
                    print(f"Error activating button widget: {e}")
                    import traceback
                    traceback.print_exc()
                    self.speak(_("Error activating widget"))
            elif widget_type == "grid":
                try:
                    self.last_widget_element = None  # Reset przy wejściu do nowego widgetu
                    self.active_widget = module.get_widget_instance(self.speak)
                    self.active_widget_name = widget_data['name']
                    self.enter_widget_mode()
                except Exception as e:
                    print(f"Error activating grid widget: {e}")
                    import traceback
                    traceback.print_exc()
                    self.speak(_("Error activating widget"))
                    # Reset state on error
                    self.active_widget = None
                    self.active_widget_name = None
            else:
                self.speak(_("Invalid widget type: {}").format(widget_type))
        except Exception as e:
            print(f"Critical error in activate_widget: {e}")
            import traceback
            traceback.print_exc()
            self.speak(_("Error activating widget"))
            # Reset state on error
            self.active_widget = None
            self.active_widget_name = None

    def enter_widget_mode(self):
        """Enter widget mode with enhanced error handling and debugging."""
        print("DEBUG: Entering widget mode...")
        
        try:
            # Validate widget state first
            if not self.active_widget:
                print("ERROR: No active widget when entering widget mode")
                return
            
            if not hasattr(self.active_widget, 'get_current_element'):
                print("ERROR: Active widget missing get_current_element method")
                self.active_widget = None
                return
            
            print(f"DEBUG: Setting widget mode for: {self.active_widget_name}")
            self.in_widget_mode = True
            
            # Set border safely
            print("DEBUG: Setting widget border...")
            try:
                if self.active_widget and hasattr(self.active_widget, 'set_border'):
                    self.active_widget.set_border()
                    print("DEBUG: Widget border set successfully")
                else:
                    print("DEBUG: Widget has no set_border method - skipping")
            except Exception as e:
                print(f"WARNING: Failed to set widget border: {e}")
            
            # Play sound safely
            print("DEBUG: Playing widget sound...")
            try:
                play_sound("ui/widget.ogg")
                print("DEBUG: Widget sound played successfully")
            except Exception as e:
                print(f"WARNING: Failed to play widget sound: {e}")
            
            # Get widget info safely with extra validation
            print("DEBUG: Getting widget current element...")
            try:
                # Test if widget's get_current_element works
                current_element = self.active_widget.get_current_element()
                print(f"DEBUG: Widget current element: '{current_element}'")
                
                if current_element is None:
                    current_element = _("Unknown element")
                    print("DEBUG: Widget returned None, using fallback")
                elif not isinstance(current_element, str):
                    current_element = str(current_element)
                    print("DEBUG: Converting non-string element to string")
                
                widget_info = f"{_('In widget')}: {self.active_widget_name}, {current_element}"
                self.last_widget_element = current_element
                print(f"DEBUG: Widget info prepared: '{widget_info}'")
                
            except Exception as e:
                print(f"ERROR: Failed to get widget current element: {e}")
                import traceback
                traceback.print_exc()
                widget_info = f"{_('In widget')}: {self.active_widget_name}, {_('Error getting element')}"
                self.last_widget_element = None
            
            # Speak safely with additional timeout
            print("DEBUG: Speaking widget info...")
            try:
                # Use a thread with timeout for speaking to prevent hang
                import threading
                import time
                
                speak_complete = threading.Event()
                speak_error = [None]  # List to store error from thread
                
                def safe_speak():
                    try:
                        self.speak(widget_info)
                        speak_complete.set()
                    except Exception as e:
                        speak_error[0] = e
                        speak_complete.set()
                
                speak_thread = threading.Thread(target=safe_speak, daemon=True)
                speak_thread.start()
                
                # Wait max 3 seconds for speech
                if speak_complete.wait(timeout=3.0):
                    if speak_error[0]:
                        print(f"ERROR: Speech failed: {speak_error[0]}")
                    else:
                        print("DEBUG: Widget info spoken successfully")
                else:
                    print("ERROR: Speech timeout - continuing without speech")
                    
            except Exception as e:
                print(f"ERROR: Critical failure in speech system: {e}")
                import traceback
                traceback.print_exc()
            
            # Update hotkeys safely in background
            print("DEBUG: Updating hotkeys...")
            try:
                import threading
                
                def update_hotkeys_safe():
                    try:
                        start_time = time.time()
                        self._update_hotkeys()
                        elapsed = time.time() - start_time
                        print(f"DEBUG: Hotkey update completed in {elapsed:.2f} seconds")
                        if elapsed > 2.0:
                            print(f"WARNING: Hotkey update took {elapsed:.2f} seconds")
                    except Exception as e:
                        print(f"ERROR: Failed to update hotkeys in widget mode: {e}")
                        import traceback
                        traceback.print_exc()
                
                # Update hotkeys in background to prevent hang
                hotkey_thread = threading.Thread(target=update_hotkeys_safe, daemon=True)
                hotkey_thread.start()
                print("DEBUG: Hotkey update thread started")
                
            except Exception as e:
                print(f"ERROR: Failed to start hotkey update: {e}")
                import traceback
                traceback.print_exc()
            
            print("DEBUG: Widget mode entry completed successfully")
            
        except Exception as e:
            print(f"CRITICAL ERROR entering widget mode: {e}")
            import traceback
            traceback.print_exc()
            
            # Reset state on error
            print("DEBUG: Resetting widget state due to error")
            self.in_widget_mode = False
            self.active_widget = None
            self.active_widget_name = None
            
            # Try to announce the error
            try:
                self.speak(_("Error entering widget mode"))
            except:
                print("ERROR: Cannot speak error message")

    def exit_widget_mode(self):
        """Exit widget mode with comprehensive cleanup"""
        if not self.in_widget_mode or self._shutdown_in_progress:
            return

        try:
            # Special handling for volume panel
            if isinstance(self.active_widget, VolumePanel):
                self.exit_volume_panel_mode()
                return

            # Special handling for WiFi panel
            try:
                import tce_system_net
                if isinstance(self.active_widget, tce_system_net.WiFiPanel):
                    self.exit_wifi_panel_mode()
                    return
            except (ImportError, AttributeError):
                pass

            # Cleanup any widget resources
            if self.active_widget and hasattr(self.active_widget, 'cleanup'):
                try:
                    self.active_widget.cleanup()
                except Exception as e:
                    print(f"Error cleaning up widget: {e}")

            self.in_widget_mode = False
            self.active_widget = None
            self.active_widget_name = None
            self.last_widget_element = None

            try:
                play_sound("ui/widgetclose.ogg")
            except Exception as e:
                print(f"Error playing widget close sound: {e}")

            # Speak in background thread to prevent freezing
            def speak_exit():
                try:
                    self.speak(_("Out of widget"))
                except Exception as e:
                    print(f"Error speaking widget exit message: {e}")

            speak_thread = threading.Thread(target=speak_exit, daemon=True)
            speak_thread.start()

            # Update hotkeys directly - _update_hotkeys already handles threading
            try:
                self._update_hotkeys()
            except Exception as e:
                print(f"Error updating hotkeys after widget exit: {e}")

        except Exception as e:
            print(f"Critical error in exit_widget_mode: {e}")
            # Force cleanup even on error
            self.in_widget_mode = False
            self.active_widget = None

    def navigate_widget(self, direction):
        print(f"DEBUG: Navigate widget called with direction: {direction}")
        try:
            if not self.active_widget:
                print("ERROR: No active widget for navigation")
                play_endoflist_sound()
                return
                
            if not hasattr(self.active_widget, 'navigate'):
                print("ERROR: Active widget has no navigate method")
                play_endoflist_sound()
                return
            
            print(f"DEBUG: Calling widget.navigate({direction})")
            try:
                navigation_result = self.active_widget.navigate(direction)
                print(f"DEBUG: Widget navigate returned: {navigation_result}")
            except Exception as e:
                print(f"ERROR: Widget navigation failed: {e}")
                import traceback
                traceback.print_exc()
                play_endoflist_sound()
                return
            
            success = False
            pan = 0.5  # Default centered

            try:
                if isinstance(navigation_result, tuple) and len(navigation_result) >= 2:
                    # New format: (success, current_horizontal_index, total_horizontal_items)
                    success = navigation_result[0]
                    if len(navigation_result) >= 3 and navigation_result[2] > 1:
                        h_index = navigation_result[1] 
                        h_total = navigation_result[2]
                        pan = h_index / (h_total - 1)
                elif isinstance(navigation_result, bool):
                    # Older format: success
                    success = navigation_result
                    if direction == "left":
                        pan = 0.0
                    elif direction == "right":
                        pan = 1.0
            except Exception as e:
                print(f"Error processing navigation result: {e}")
                success = False
            
            if not success:
                try:
                    play_endoflist_sound()
                except Exception as e:
                    print(f"Error playing end of list sound: {e}")
            else:
                try:
                    play_focus_sound(pan=pan)
                except Exception as e:
                    play_focus_sound()  # Fallback
                    print(f"Error playing focus sound with pan: {e}")
                
                # Always try to get and speak the current element when navigation succeeds
                print("DEBUG: Getting current widget element after successful navigation")
                try:
                    current_element = self.active_widget.get_current_element()
                    print(f"DEBUG: Widget current element: '{current_element}'")
                    
                    if current_element:
                        # Calculate stereo position for widget elements
                        stereo_position = 0.0
                        pitch_offset = 0
                        if pan != 0.5:  # If not centered
                            # Convert pan (0.0-1.0) to stereo position (-1.0 to 1.0)
                            stereo_position = (pan * 2.0) - 1.0
                            
                            # Widget navigation - check movement direction
                            if direction in ["up", "down"]:
                                # Pitch only for up/down navigation in widgets
                                pitch_offset = int((0.5 - pan) * 4)  # Subtler effect for widgets
                        
                        print(f"DEBUG: Stereo position: {stereo_position}, pitch: {pitch_offset}")
                        
                        # Speak if element changed or is new
                        if current_element != self.last_widget_element:
                            print(f"DEBUG: Element changed from '{self.last_widget_element}' to '{current_element}' - speaking")
                            self.last_widget_element = current_element
                            
                            # Use safe speak with timeout like in enter_widget_mode
                            import threading
                            speak_complete = threading.Event()
                            speak_error = [None]
                            
                            def safe_speak_nav():
                                try:
                                    self.speak(current_element, position=stereo_position, pitch_offset=pitch_offset)
                                    speak_complete.set()
                                except Exception as e:
                                    speak_error[0] = e
                                    speak_complete.set()
                            
                            speak_thread = threading.Thread(target=safe_speak_nav, daemon=True)
                            speak_thread.start()
                            
                            # Wait max 2 seconds for speech during navigation
                            if speak_complete.wait(timeout=2.0):
                                if speak_error[0]:
                                    print(f"ERROR: Navigation speech failed: {speak_error[0]}")
                                else:
                                    print("DEBUG: Navigation speech completed successfully")
                            else:
                                print("ERROR: Navigation speech timeout")
                        else:
                            print("DEBUG: Element unchanged - not speaking")
                        
                except Exception as e:
                    print(f"ERROR: Failed to get/speak widget element: {e}")
                    import traceback
                    traceback.print_exc()
                    
        except Exception as e:
            print(f"Critical error in navigate_widget: {e}")
            try:
                play_endoflist_sound()
            except:
                pass

    def launch_app_by_name(self, name):
        app = next((app for app in get_applications() if app.get("name") == name), None)
        if app: open_application(app)
        else: self.speak(_("Application not found: {}").format(name))

    def launch_game_by_name(self, name):
        # Remove any extra whitespace
        clean_name = name.strip()

        # Search for game in stored platform data
        if hasattr(self, 'games_by_platform_data'):
            for platform, games_list in self.games_by_platform_data.items():
                game = next((g for g in games_list if g.get("name") == clean_name), None)
                if game:
                    open_game(game)
                    return

        # Fallback: search all games
        game = next((game for game in get_games() if game.get("name") == clean_name), None)
        if game:
            open_game(game)
        else:
            self.speak(_("Game not found: {}").format(clean_name))

    def expand_game_platform(self, platform_name):
        """Expand into a game platform folder (Steam, Battle.net, Titan-Games)"""
        try:
            # Check if this is the "No games" placeholder
            if platform_name == _("No games"):
                return

            # Get the platform subcategory
            if not hasattr(self, 'games_platform_subcategories'):
                self.speak(_("Platform not found"))
                return

            platform_subcat = self.games_platform_subcategories.get(platform_name)
            if not platform_subcat:
                self.speak(_("Platform not found"))
                return

            # Play expansion sound
            play_sound("ui/focus_expanded.ogg")

            # Backup current Games category
            games_category_index = None
            for i, cat in enumerate(self.categories):
                if cat.get('name') == _("Games"):
                    games_category_index = i
                    self.game_platform_backup = cat.copy()
                    break

            if games_category_index is None:
                self.speak(_("Games category not found"))
                return

            # Replace Games category with platform subcategory
            # Add "Back" element at the beginning
            platform_elements = [_("Back")] + platform_subcat['elements']
            self.categories[games_category_index] = {
                "name": platform_subcat['name'],
                "sound": "core/focus.ogg",
                "elements": platform_elements,
                "action": self.handle_platform_element,
                "is_platform_expanded": True
            }

            # Set state
            self.in_game_platform = True
            self.current_element_index = 0

            # Announce first element (Back)
            self.speak(_("Back"))

        except Exception as e:
            print(f"Error expanding game platform: {e}")
            import traceback
            traceback.print_exc()
            self.speak(_("Error expanding platform"))

    def handle_platform_element(self, element_name):
        """Handle activation of element in platform view (Back or game name)"""
        try:
            if element_name == _("Back"):
                self.collapse_game_platform()
            else:
                # Launch the game
                self.launch_game_by_name(element_name)
        except Exception as e:
            print(f"Error handling platform element: {e}")
            self.speak(_("Error"))

    def collapse_game_platform(self):
        """Go back from platform view to Games category"""
        try:
            # Play collapse sound
            play_sound("ui/focus_collabsed.ogg")

            # Find and restore Games category
            games_category_index = None
            for i, cat in enumerate(self.categories):
                if cat.get('is_platform_expanded'):
                    games_category_index = i
                    break

            if games_category_index is None or self.game_platform_backup is None:
                self.speak(_("Error returning"))
                return

            # Restore original Games category
            self.categories[games_category_index] = self.game_platform_backup

            # Reset state
            self.in_game_platform = False
            self.game_platform_backup = None
            self.current_element_index = 0

            # Announce we're back in Games
            self.speak(_("Games"))

        except Exception as e:
            print(f"Error collapsing game platform: {e}")
            import traceback
            traceback.print_exc()
            self.speak(_("Error returning"))

    def activate_statusbar_item(self, item_string):
        actions = {
            _("Clock:"): self.main_frame.open_time_settings,
            _("Battery level:"): self.main_frame.open_power_settings,
            _("Volume:"): self.activate_volume_panel,
        }
        for key, action in actions.items():
            if key in item_string:
                if key == _("Volume:"):
                    action()
                else:
                    wx.CallAfter(action)
                return
        
        # Special handling for network status since get_network_status() returns a raw string
        if any(keyword in item_string.lower() for keyword in ['połączono', 'connected', 'wifi', 'ethernet', 'nie połączono', 'disconnected', 'network']):
            wx.CallAfter(self.main_frame.open_network_settings)
            return

        # Check statusbar applets
        # Strategy: Check if item matches applet pattern (not exact text, since values change)
        if hasattr(self, 'statusbar_applet_manager') and self.statusbar_applet_manager:
            for applet_name in self.statusbar_applet_manager.get_applet_names():
                try:
                    # Get a fresh applet text to check the pattern
                    self.statusbar_applet_manager.update_applet_cache(applet_name)
                    applet_text = self.statusbar_applet_manager.get_applet_text(applet_name)

                    # Extract pattern keywords from applet text (words before colons)
                    import re
                    applet_keywords = re.findall(r'(\w+):', applet_text)
                    item_keywords = re.findall(r'(\w+):', item_string)

                    # Check if item has same keyword pattern as applet
                    if applet_keywords and item_keywords and set(applet_keywords) == set(item_keywords):
                        print(f"IUI: Statusbar applet detected: '{applet_name}' (pattern match: {applet_keywords}) - activating...")
                        wx.CallAfter(self.statusbar_applet_manager.activate_applet, applet_name, self.main_frame)
                        return
                except Exception as e:
                    print(f"Error activating statusbar applet '{applet_name}': {e}")

        self.speak(_("No action for this item"))
    
    def activate_volume_panel(self):
        """Activate volume control panel"""
        self.active_widget = VolumePanel(self.speak)
        self.active_widget_name = _("Volume Panel")
        self.enter_volume_panel_mode()
    
    def enter_volume_panel_mode(self):
        """Enter volume panel widget mode"""
        self.in_widget_mode = True
        play_sound("ui/focus_expanded.ogg")
        # Update volume levels when entering
        self.active_widget.volume_level = self.active_widget.get_current_volume()
        self.active_widget.is_muted = self.active_widget.get_mute_status()

        widget_info = self.active_widget.get_current_element()
        self.last_widget_element = self.active_widget.get_current_element()
        self.speak(widget_info)

        # Update hotkeys in background to prevent blocking
        def background_hotkey_update():
            try:
                self._update_hotkeys()
            except Exception as e:
                print(f"Error updating hotkeys after volume panel entry: {e}")

        threading.Thread(target=background_hotkey_update, daemon=True).start()
    
    def exit_volume_panel_mode(self):
        """Exit volume panel mode with special sound"""
        if not self.in_widget_mode: return

        # Cleanup volume panel resources
        if hasattr(self.active_widget, 'cleanup'):
            self.active_widget.cleanup()

        self.in_widget_mode = False
        self.active_widget = None
        self.active_widget_name = None
        self.last_widget_element = None
        play_sound("ui/focus_collapsed.ogg")
        self.speak(_("Exiting volume panel"))

        # Update hotkeys directly - _update_hotkeys already handles threading
        try:
            self._update_hotkeys()
        except Exception as e:
            print(f"Error updating hotkeys after volume panel exit: {e}")
    
    def exit_wifi_panel_mode(self):
        """Exit WiFi panel mode with special sound"""
        if not self.in_widget_mode: return
        self.in_widget_mode = False
        self.active_widget = None
        self.active_widget_name = None
        self.last_widget_element = None
        play_sound("ui/focus_collapsed.ogg")

        # Titan UI is always enabled
        self.speak(_("Exiting WiFi manager, returning to Titan UI"))

        # Update hotkeys directly - _update_hotkeys already handles threading
        try:
            self._update_hotkeys()
        except Exception as e:
            print(f"Error updating hotkeys after WiFi panel exit: {e}")
    
    def activate_titan_im(self, platform_name):
        """Activate Titan IM platform (Telegram/Messenger/WhatsApp)"""
        if platform_name == _("No IM clients available"):
            self.speak(_("No IM clients available"))
            return
        
        # Handle web apps like in gui.py
        if platform_name == _("Facebook Messenger"):
            return self.open_messenger_webview()
        elif platform_name == _("WhatsApp"):
            return self.open_whatsapp_webview()
        elif platform_name == _("Titan-Net (Beta)") or platform_name == _("Titan-Net"):
            return self.open_titannet()
        elif platform_name == _("EltenLink (Beta)"):
            return self.open_eltenlink()

        # Try dynamic IM modules
        try:
            from src.network.im_module_manager import im_module_manager
            if im_module_manager.open_module(platform_name, getattr(self, 'main_frame', None)):
                return
        except Exception as _e:
            print(f"[IUI] IM module open: {_e}")

        # Set current platform for native clients
        if platform_name == _("Telegram"):
            self.titan_im_mode = 'telegram'
        else:
            return
        
        # Check if connected with safe error handling
        is_connected = False
        try:
            if self.titan_im_mode == 'telegram' and telegram_client:
                is_connected = telegram_client.is_connected()
        except Exception as e:
            print(f"Error checking Telegram connection: {e}")
            self.speak(_("Error checking connection to {}").format(platform_name))
            return
        
        if not is_connected:
            self.speak(_("Not connected to {}").format(platform_name))
            return
        
        # Create submenu
        submenu_elements = [_("Contacts"), _("Groups"), _("Back")]
        
        # Add submenu category
        titan_im_submenu_category = {
            "name": _("{} Menu").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": submenu_elements,
            "action": self.activate_titan_im_submenu,
            "parent_mode": self.titan_im_mode
        }
        
        # Insert submenu after current category
        current_index = self.current_category_index
        self.categories.insert(current_index + 1, titan_im_submenu_category)
        
        # Navigate to submenu
        self.current_category_index += 1
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'core/focus.ogg'))
        self.speak(f"{category['name']}, {category['elements'][0]}")
    
    def activate_titan_im_submenu(self, submenu_name):
        """Activate Titan IM submenu item"""
        if submenu_name == _("Back"):
            # Remove submenu and go back
            self.categories.pop(self.current_category_index)
            self.current_category_index -= 1
            self.current_element_index = 0
            self.titan_im_submenu = None
            
            category = self.categories[self.current_category_index]
            play_sound(category.get('sound', 'core/focus.ogg'))
            self.speak(f"{category['name']}, {category['elements'][self.current_element_index]}")
            return
        
        if submenu_name == _("Contacts"):
            self.load_titan_im_contacts()
        elif submenu_name == _("Groups"):
            self.load_titan_im_groups()
    
    def load_titan_im_contacts(self):
        """Load contacts for current IM platform"""
        contacts = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            contacts = telegram_client.get_contacts()
        elif self.titan_im_mode == 'messenger' and messenger_client:
            conversations = messenger_client.get_conversations()
            # Convert conversations to contact format
            contacts = [{'username': conv['name'], 'type': 'contact'} for conv in conversations]
        
        if not contacts:
            contacts = [_("No contacts")]
        else:
            contacts = [contact['username'] for contact in contacts]
        
        self.current_contacts = contacts
        
        # Create contacts category
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        contacts_category = {
            "name": _("{} Contacts").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": contacts + [_("Back")],
            "action": self.activate_titan_im_contact,
            "parent_mode": self.titan_im_mode
        }
        
        # Replace current submenu with contacts
        self.categories[self.current_category_index] = contacts_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'core/focus.ogg'))
        self.speak(f"{category['name']}, {len(contacts)} {_('contacts')}, {category['elements'][0]}")
    
    def load_titan_im_groups(self):
        """Load groups for current IM platform"""
        groups = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            groups = telegram_client.get_group_chats()
        elif self.titan_im_mode == 'messenger' and messenger_client:
            # Messenger doesn't separate groups clearly, so we skip for now
            groups = []
        
        if not groups:
            groups = [_("No groups")]
        else:
            groups = [group['name'] if 'name' in group else group.get('title', 'Unknown') for group in groups]
        
        self.current_groups = groups
        
        # Create groups category
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        groups_category = {
            "name": _("{} Groups").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": groups + [_("Back")],
            "action": self.activate_titan_im_group,
            "parent_mode": self.titan_im_mode
        }
        
        # Replace current submenu with groups
        self.categories[self.current_category_index] = groups_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'core/focus.ogg'))
        self.speak(f"{category['name']}, {len(groups)} {_('groups')}, {category['elements'][0]}")
    
    def activate_titan_im_contact(self, contact_name):
        """Activate contact to view chat history"""
        if contact_name == _("Back") or contact_name == _("No contacts"):
            self.go_back_to_titan_im_submenu()
            return
        
        self.current_chat_user = contact_name
        self.load_chat_history(contact_name)
    
    def activate_titan_im_group(self, group_name):
        """Activate group to view chat history"""
        if group_name == _("Back") or group_name == _("No groups"):
            self.go_back_to_titan_im_submenu()
            return
        
        self.current_chat_user = group_name
        self.load_group_chat_history(group_name)
    
    def load_chat_history(self, contact_name):
        """Load private chat history"""
        self.current_chat_history = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            # Request chat history - this will be received via callback
            telegram_client.get_chat_history(contact_name)
        elif self.titan_im_mode == 'messenger' and messenger_client:
            # Messenger doesn't have direct history API in current implementation
            pass
        
        # Create temporary history view
        self.show_chat_history_view(contact_name, is_group=False)
    
    def load_group_chat_history(self, group_name):
        """Load group chat history"""
        self.current_chat_history = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            # Request group chat history - this will be received via callback
            telegram_client.get_group_chat_history(group_name)
        elif self.titan_im_mode == 'messenger' and messenger_client:
            # Messenger group history not implemented
            pass
        
        # Create temporary history view
        self.show_chat_history_view(group_name, is_group=True)
    
    def show_chat_history_view(self, chat_name, is_group=False):
        """Show chat history interface"""
        # Create history elements - will be populated by callback
        history_elements = [_("Loading messages..."), _("Send message"), _("Back")]
        
        chat_type = _("Group") if is_group else _("Contact")
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        
        history_category = {
            "name": _("{} {} - {}").format(platform_name, chat_type, chat_name),
            "sound": "titannet/iui.ogg",
            "elements": history_elements,
            "action": self.activate_chat_history_item,
            "parent_mode": self.titan_im_mode,
            "chat_name": chat_name,
            "is_group": is_group
        }
        
        # Replace current category with history view
        self.categories[self.current_category_index] = history_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'core/focus.ogg'))
        self.speak(f"{category['name']}, {category['elements'][0]}")
    
    def activate_chat_history_item(self, item_name):
        """Activate chat history item"""
        if item_name == _("Back"):
            self.go_back_to_titan_im_submenu()
            return
        elif item_name == _("Send message"):
            self.show_send_message_dialog()
            return
        elif item_name == _("Loading messages..."):
            self.speak(_("Messages are loading, please wait"))
            return
        
        # Store current selected message
        self.current_selected_message = item_name
        
        # Check if this message contains voice message
        self.check_for_voice_message(item_name)
        
        # This is a message - read it
        self.speak(item_name)
    
    def check_for_voice_message(self, message_text):
        """Check if message contains voice message and extract path"""
        # Look for voice message patterns like [Voice: path/to/file.ogg]
        voice_pattern = r'\[Voice:\s*([^\]]+)\]'
        match = re.search(voice_pattern, message_text)
        
        if match:
            voice_path = match.group(1).strip()
            self.current_voice_message_path = voice_path
            play_sound('titannet/voice_select.ogg')
        else:
            self.current_voice_message_path = None
    
    def handle_voice_message_toggle(self):
        """Handle play/pause of voice messages"""
        if self.current_voice_message_path:
            success = toggle_voice_message()
            if success:
                if is_voice_message_playing():
                    play_sound('titannet/voice_play.ogg')
                    self.speak(_("Playing voice message"))
                elif is_voice_message_paused():
                    play_sound('titannet/voice_pause.ogg')
                    self.speak(_("Voice message paused"))
            else:
                # Try to start playing the voice message
                if play_voice_message(self.current_voice_message_path):
                    play_sound('titannet/voice_play.ogg')
                    self.speak(_("Playing voice message"))
                else:
                    play_sound('core/error.ogg')
                    self.speak(_("Error playing voice message"))
        else:
            self.speak(_("No voice message selected"))
    
    def handle_titan_enter(self):
        """Handle Titan+Enter key combination for voice message playback and widget actions"""
        try:
            if self._shutdown_in_progress:
                return
                
            # Handle widget mode first
            if self.in_widget_mode and self.active_widget:
                try:
                    # Check if widget has handle_titan_enter method
                    if hasattr(self.active_widget, 'handle_titan_enter'):
                        self.active_widget.handle_titan_enter()
                        return
                except Exception as e:
                    print(f"Error in widget handle_titan_enter: {e}")
                    return
            
            if (self.titan_ui_mode and self.titan_im_mode and 
                self.titan_im_submenu == 'history'):
                try:
                    # Check if current element contains voice message
                    if (self.current_category_index < len(self.categories) and
                        self.categories[self.current_category_index]['elements'] and
                        self.current_element_index < len(self.categories[self.current_category_index]['elements'])):
                        
                        category = self.categories[self.current_category_index]
                        element_name = category['elements'][self.current_element_index]
                        self.check_for_voice_message(element_name)
                        if self.current_voice_message_path:
                            self.handle_voice_message_toggle()
                            return
                except Exception as e:
                    print(f"Error in voice message handling: {e}")
            
            # If not in a voice message context, just speak current element
            if self.titan_ui_mode:
                try:
                    if (self.current_category_index < len(self.categories) and
                        self.categories[self.current_category_index]['elements'] and
                        self.current_element_index < len(self.categories[self.current_category_index]['elements'])):
                        
                        category = self.categories[self.current_category_index]
                        element_name = category['elements'][self.current_element_index]
                        self.speak(element_name)
                except Exception as e:
                    print(f"Error speaking current element: {e}")
                    
        except Exception as e:
            print(f"Critical error in handle_titan_enter: {e}")
    
    def show_send_message_dialog(self):
        """Show dialog to send message"""
        if not self.current_chat_user:
            return
        
        def show_dialog():
            # Auto-disable Titan UI when message dialog opens
            if self.titan_ui_mode:
                self.temporarily_disable_titan_ui("send_message_dialog")
            
            dlg = wx.TextEntryDialog(
                None,
                _("Enter message to send to {}:").format(self.current_chat_user),
                _("Send Message")
            )
            
            if dlg.ShowModal() == wx.ID_OK:
                message = dlg.GetValue()
                if message.strip():
                    self.send_titan_im_message(self.current_chat_user, message)
            
            # Re-enable Titan UI after dialog closes
            self._on_dialog_close("send_message_dialog", None)
            dlg.Destroy()
        
        wx.CallAfter(show_dialog)
    
    def send_titan_im_message(self, recipient, message):
        """Send message through current IM platform"""
        success = False
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            # Check if it's a group
            category = self.categories[self.current_category_index]
            if category.get('is_group', False):
                success = telegram_client.send_group_message(recipient, message)
            else:
                success = telegram_client.send_message(recipient, message)
        elif self.titan_im_mode == 'messenger' and messenger_client:
            success = messenger_client.send_message(recipient, message)
        
        if success:
            self.speak(_("Message sent to {}").format(recipient))
        else:
            self.speak(_("Failed to send message"))
    
    def go_back_to_titan_im_submenu(self):
        """Go back to Titan IM submenu"""
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        submenu_elements = [_("Contacts"), _("Groups"), _("Back")]
        
        titan_im_submenu_category = {
            "name": _("{} Menu").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": submenu_elements,
            "action": self.activate_titan_im_submenu,
            "parent_mode": self.titan_im_mode
        }
        
        self.categories[self.current_category_index] = titan_im_submenu_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'core/focus.ogg'))
        self.speak(f"{category['name']}, {category['elements'][0]}")
    
    def update_chat_history(self, history_data):
        """Update chat history when received from callback"""
        if not history_data or history_data.get('type') not in ['chat_history', 'group_chat_history']:
            return
        
        messages = history_data.get('messages', [])
        
        # Format messages for display
        formatted_messages = []
        for msg in messages[-10:]:  # Show last 10 messages
            sender = msg.get('sender_username', 'Unknown')
            text = msg.get('message', '')
            timestamp = msg.get('timestamp', '')
            voice_file = msg.get('voice_file', '')  # Path to voice message file
            
            # Format timestamp
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                time_str = dt.strftime('%H:%M')
            except:
                time_str = ''
            
            if text or voice_file:
                message_content = text
                
                # Add voice message indicator
                if voice_file:
                    voice_indicator = f"[Voice: {voice_file}]"
                    if message_content:
                        message_content += f" {voice_indicator}"
                    else:
                        message_content = f"{_('Voice message')} {voice_indicator}"
                
                if time_str:
                    formatted_msg = f"[{time_str}] {sender}: {message_content}"
                else:
                    formatted_msg = f"{sender}: {message_content}"
                formatted_messages.append(formatted_msg)
        
        # Update current category if it's a chat history view
        if (self.current_category_index < len(self.categories) and 
            'chat_name' in self.categories[self.current_category_index]):
            
            category = self.categories[self.current_category_index]
            
            # Replace loading message with actual history
            new_elements = formatted_messages + [_("Send message"), _("Back")]
            category['elements'] = new_elements
            
            # Announce update
            if formatted_messages:
                self.speak(_("Chat history loaded, {} messages").format(len(formatted_messages)))
            else:
                self.speak(_("No messages in chat history"))

    def start_listening(self, rebuild=True):
        """Start listening with comprehensive error handling and safety checks"""
        try:
            if self.active:
                return

            # Reset shutdown flag when starting - this allows restart after stop_listening
            self._shutdown_in_progress = False
            self.active = True

            try:
                self.stop_event.clear()
            except Exception as e:
                print(f"Error clearing stop event: {e}")

            try:
                self.speak(_("Invisible interface active"))
            except Exception as e:
                print(f"Error speaking activation message: {e}")
            
            if rebuild:
                try:
                    self.build_structure()
                except Exception as e:
                    print(f"Error building structure: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Register callbacks for message history updates
            try:
                if telegram_client and hasattr(telegram_client, 'add_message_callback'):
                    telegram_client.add_message_callback(self._handle_im_message_callback)
                if messenger_client and hasattr(messenger_client, 'add_message_callback'):
                    messenger_client.add_message_callback(self._handle_im_message_callback)
            except Exception as e:
                print(f"Error registering IM callbacks: {e}")
            
            # Start refresh thread
            try:
                if not self.refresh_thread or not self.refresh_thread.is_alive():
                    self.refresh_thread = threading.Thread(target=self._run, daemon=True)
                    self.refresh_thread.start()
            except Exception as e:
                print(f"Error starting refresh thread: {e}")

            # Update hotkeys last
            try:
                self._update_hotkeys()
            except Exception as e:
                print(f"Error updating hotkeys: {e}")
                
            # F6 program switching removed - using only pynput hotkeys
                
        except Exception as e:
            print(f"Critical error in start_listening: {e}")
            import traceback
            traceback.print_exc()
            self.active = False
            self._shutdown_in_progress = True
        
    def _handle_im_message_callback(self, message_data):
        """Handle incoming message callbacks from IM clients"""
        try:
            if message_data.get('type') in ['chat_history', 'group_chat_history']:
                # Update chat history in UI thread safely
                try:
                    if self.main_frame and hasattr(self.main_frame, 'IsShown'):
                        wx.CallAfter(self.update_chat_history, message_data)
                except Exception as e:
                    print(f"Error calling wx.CallAfter for chat history: {e}")
        except Exception as e:
            print(f"Error handling IM message callback: {e}")

    def stop_listening(self):
        """Stop listening with comprehensive cleanup and error handling"""
        # Skip cleanup during Python shutdown
        import sys
        if hasattr(sys, 'is_finalizing') and sys.is_finalizing():
            return

        try:
            if not hasattr(self, 'active') or not self.active:
                return

            self.active = False
            # Don't set _shutdown_in_progress here - only in finally block for true errors
            # This allows restart after stop_listening
            self.titan_ui_mode = False
            self.in_widget_mode = False
            self.titan_im_mode = None
            self.titan_im_submenu = None
            self.current_chat_user = None

            # Key blocking removed - using only pynput hotkeys

            # Signal threads to stop
            try:
                if hasattr(self, 'stop_event'):
                    self.stop_event.set()
            except Exception as e:
                print(f"Error setting stop event: {e}")
            
            # Stop hotkey thread first (can block)
            try:
                if hasattr(self, 'hotkey_thread') and self.hotkey_thread:
                    self.hotkey_thread.stop()
                    time.sleep(0.1)  # Reduced sleep time
                    self.hotkey_thread = None
            except Exception as e:
                print(f"Error stopping keyboard hotkey thread: {e}")

            # Clean up refresh thread (don't block on join - daemon thread will stop on exit)
            try:
                if hasattr(self, 'refresh_thread') and self.refresh_thread:
                    if self.refresh_thread.is_alive():
                        print("INFO: Refresh thread still running (will stop automatically as daemon)")
                    self.refresh_thread = None
            except Exception as e:
                print(f"Error cleaning up refresh thread: {e}")

            # Clean up active widget
            try:
                if hasattr(self, 'active_widget') and self.active_widget:
                    if hasattr(self.active_widget, 'cleanup'):
                        self.active_widget.cleanup()
                    self.active_widget = None
            except Exception as e:
                print(f"Error cleaning up active widget: {e}")
            
            # Clean up speaker resources
            try:
                cleanup_speaker()
            except Exception as e:
                print(f"Error cleaning up speaker: {e}")
            
            # F6 hook cleanup removed - using only pynput hotkeys
                
        except Exception as e:
            print(f"Critical error in stop_listening: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Ensure we're marked as inactive even on error
            self.active = False
            # Don't set _shutdown_in_progress here - it prevents restart

    def _update_hotkeys(self):
        """Update hotkeys for Titan UI - simple keys only"""
        # Run the entire hotkey update in a background thread to prevent freezing
        def _update_hotkeys_async():
            try:
                if self._shutdown_in_progress:
                    return

                # Stop existing hotkey thread safely
                if self.hotkey_thread:
                    try:
                        self.hotkey_thread.stop()
                        time.sleep(0.1)
                    except Exception as e:
                        print(f"Error stopping keyboard hotkey thread: {e}")
                    finally:
                        self.hotkey_thread = None

                # Titan UI hotkeys - simple keys without modifiers
                keyboard_hotkeys = {}

                try:
                    # The tilde key is always available to toggle TUI mode
                    keyboard_hotkeys['`'] = self._safe_toggle_titan_ui
                    # Titan+Enter for voice message playback
                    keyboard_hotkeys['`+<enter>'] = self._safe_handle_titan_enter
                except Exception as e:
                    print(f"Error setting titan UI hotkeys: {e}")

                # Navigation hotkeys - simple arrows in Titan UI mode
                # Only register navigation keys when Titan UI is enabled
                if self.titan_ui_mode:
                    if self.in_widget_mode:
                        # Simple arrows for widget navigation
                        if not self.titan_ui_temporarily_disabled:
                            keyboard_hotkeys.update({
                                '<up>': lambda: self.navigate_widget('up'),
                                '<down>': lambda: self.navigate_widget('down'),
                                '<left>': lambda: self.navigate_widget('left'),
                                '<right>': lambda: self.navigate_widget('right'),
                                '<enter>': self.activate_element,
                                '<space>': self.activate_element,
                                '<backspace>': self.exit_widget_mode,
                                '<esc>': self.exit_widget_mode,
                            })
                    else:
                        # Simple arrows for main view navigation
                        if not self.titan_ui_temporarily_disabled:
                            keyboard_hotkeys.update({
                                '<up>': lambda: self.navigate_category(-1),
                                '<down>': lambda: self.navigate_category(1),
                                '<left>': lambda: self.navigate_element(-1),
                                '<right>': lambda: self.navigate_element(1),
                                '<enter>': self.activate_element,
                                '<space>': self.activate_element,
                            })

                # Create keyboard hotkey thread for Titan UI
                if keyboard_hotkeys and not self._shutdown_in_progress:
                    try:
                        start_time = time.time()
                        new_keyboard_thread = GlobalHotKeys(keyboard_hotkeys)
                        new_keyboard_thread.start()
                        self.hotkey_thread = new_keyboard_thread

                        elapsed = time.time() - start_time
                        if elapsed > 1.0:
                            print(f"Warning: Keyboard hotkey thread creation took {elapsed:.2f} seconds")
                        print(f"Keyboard hotkeys registered: {list(keyboard_hotkeys.keys())}")
                    except Exception as e:
                        print(f"Error creating/starting keyboard hotkey thread: {e}")
                        self.hotkey_thread = None

            except Exception as e:
                print(f"Critical error in _update_hotkeys_async: {e}")
                import traceback
                traceback.print_exc()

        # Start the async update in a background thread to prevent freezing
        try:
            update_thread = threading.Thread(target=_update_hotkeys_async, daemon=True)
            update_thread.start()
        except Exception as e:
            print(f"Error starting hotkey update thread: {e}")

    def temporarily_disable_titan_ui(self, dialog_name):
        """Temporarily disable Titan UI when a dialog opens"""
        if self.titan_ui_mode and not self.titan_ui_temporarily_disabled:
            self.titan_ui_temporarily_disabled = True
            self.disabled_by_dialog = dialog_name
            print(f"Titan UI temporarily disabled by {dialog_name}")
    
    def _on_dialog_close(self, dialog_name, event):
        """Handle dialog close event to re-enable Titan UI if needed"""
        if (self.titan_ui_temporarily_disabled and 
            self.disabled_by_dialog == dialog_name):
            
            # Re-enable Titan UI
            self.titan_ui_temporarily_disabled = False
            self.disabled_by_dialog = None
            print(f"Titan UI re-enabled after {dialog_name} dialog closed")
        
        if event:
            event.Skip()
    
    def _safe_on_dialog_close(self, dialog_name, event):
        """Safe wrapper for dialog close to prevent crashes in compiled version"""
        try:
            if self._shutdown_in_progress:
                return
                
            self._on_dialog_close(dialog_name, event)
        except Exception as e:
            print(f"Error in _safe_on_dialog_close for {dialog_name}: {e}")
            # Force cleanup on error
            try:
                if self.titan_ui_temporarily_disabled and self.disabled_by_dialog == dialog_name:
                    self.titan_ui_temporarily_disabled = False
                    self.disabled_by_dialog = None
            except:
                pass
    
    def _safe_toggle_titan_ui(self):
        """Safe wrapper for toggle_titan_ui_mode to prevent hotkey crashes"""
        try:
            import threading
            # Run in separate thread to avoid blocking hotkey system
            thread = threading.Thread(target=self.toggle_titan_ui_mode, daemon=True)
            thread.start()
        except Exception as e:
            print(f"Error in _safe_toggle_titan_ui: {e}")
    
    def _safe_handle_titan_enter(self):
        """Safe wrapper for handle_titan_enter to prevent hotkey crashes"""
        try:
            import threading
            # Run in separate thread to avoid blocking hotkey system
            thread = threading.Thread(target=self.handle_titan_enter, daemon=True)
            thread.start()
        except Exception as e:
            print(f"Error in _safe_handle_titan_enter: {e}")

    def toggle_titan_ui_mode(self):
        """Toggle Titan UI mode with crash protection"""
        try:
            if self._shutdown_in_progress:
                return
                
            self.titan_ui_mode = not self.titan_ui_mode
            
            try:
                if self.titan_ui_mode:
                    play_sound('ui/tui_open.ogg')
                    self.speak(_("Titan UI on"))
                else:
                    play_sound('ui/tui_close.ogg')
                    self.speak(_("Titan UI off"))
                    # Reset temporary disable state when turning off
                    self.titan_ui_temporarily_disabled = False
                    self.disabled_by_dialog = None
            except Exception as e:
                print(f"Error in titan UI toggle sound/speech: {e}")
                
            try:
                self._update_hotkeys()
            except Exception as e:
                print(f"Error updating hotkeys after Titan UI toggle: {e}")
                
        except Exception as e:
            print(f"Critical error in toggle_titan_ui_mode: {e}")
            # Ensure we don't get stuck in a bad state
            try:
                self.titan_ui_mode = False
                self.titan_ui_temporarily_disabled = False
                self.disabled_by_dialog = None
            except:
                pass
    
    def open_messenger_webview(self):
        """Open Messenger WebView like in gui.py"""
        try:
            # Check if we have a valid main frame
            if not self.main_frame or self._shutdown_in_progress:
                self.speak(_("Cannot open Messenger - application not ready"))
                return
                
            import messenger_webview
            
            # Auto-disable Titan UI when webview opens
            if self.titan_ui_mode:
                self.temporarily_disable_titan_ui("messenger_webview")
            
            # Get announce_widget_type setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
            
            def launch_messenger():
                try:
                    # Additional safety check in wx.CallAfter
                    if self._shutdown_in_progress or not self.main_frame:
                        return
                        
                    messenger_window = messenger_webview.show_messenger_webview(self.main_frame)
                    if messenger_window and not messenger_window.IsBeingDeleted():
                        # Safely bind close event to re-enable Titan UI when webview closes
                        try:
                            messenger_window.Bind(wx.EVT_CLOSE, lambda evt: self._safe_on_dialog_close("messenger_webview", evt))
                        except Exception as bind_error:
                            print(f"Warning: Could not bind close event: {bind_error}")
                            
                        # Speak announcement safely
                        try:
                            if announce_widget_type:
                                self.speak(_("Messenger, web application"))
                            else:
                                self.speak(_("Messenger"))
                        except Exception as speak_error:
                            print(f"Warning: Could not speak messenger announcement: {speak_error}")
                    else:
                        # Re-enable Titan UI if window creation failed
                        self._safe_on_dialog_close("messenger_webview", None)
                        
                except Exception as launch_error:
                    print(f"Error in launch_messenger: {launch_error}")
                    # Re-enable Titan UI on error
                    self._safe_on_dialog_close("messenger_webview", None)
                    try:
                        self.speak(_("Error opening Messenger WebView"))
                    except:
                        pass
            
            # Use safer wx.CallAfter with error handling
            try:
                wx.CallAfter(launch_messenger)
            except Exception as callafter_error:
                print(f"Error with wx.CallAfter: {callafter_error}")
                # Re-enable Titan UI if CallAfter fails
                self._safe_on_dialog_close("messenger_webview", None)
                self.speak(_("Error opening Messenger WebView"))
            
        except ImportError:
            print("Messenger WebView module not available")
            self.speak(_("Messenger WebView not available"))
        except Exception as e:
            print(f"Error opening Messenger WebView from invisible UI: {e}")
            # Re-enable Titan UI on any error
            self._safe_on_dialog_close("messenger_webview", None)
            try:
                self.speak(_("Error opening Messenger WebView"))
            except:
                pass
    
    def activate_wifi_interface(self):
        """Activate WiFi interface for invisible UI as a panel"""
        try:
            # Interrupt speech for smooth operation
            try:
                speaker.stop()
            except (AttributeError, Exception):
                pass
            
            import tce_system_net
            
            # Check if PyWiFi is available
            if not tce_system_net.PYWIFI_AVAILABLE:
                self.speak(_("WiFi functionality requires pywifi library. Install with: pip install pywifi"))
                return
            
            # Create WiFi panel like volume panel
            self.active_widget = tce_system_net.WiFiPanel(self.speak)
            self.active_widget_name = _("WiFi Manager")
            self.enter_wifi_panel_mode()
            
        except Exception as e:
            print(f"Error opening WiFi interface from invisible UI: {e}")
            self.speak(_("Error opening WiFi interface"))
    
    def enter_wifi_panel_mode(self):
        """Enter WiFi panel mode"""
        self.in_widget_mode = True
        play_sound("ui/focus_expanded.ogg")
        
        # Initial announcement
        widget_info = self.active_widget.get_current_element()
        self.last_widget_element = self.active_widget.get_current_element()
        self.speak(_("WiFi Manager") + ", " + widget_info)
        
        # Update hotkeys to enable arrow keys immediately if Titan UI is enabled
        self._update_hotkeys()
    
    def open_whatsapp_webview(self):
        """Open WhatsApp WebView like in gui.py"""
        try:
            # Check if we have a valid main frame
            if not self.main_frame or self._shutdown_in_progress:
                self.speak(_("Cannot open WhatsApp - application not ready"))
                return
                
            import whatsapp_webview
            
            # Auto-disable Titan UI when webview opens
            if self.titan_ui_mode:
                self.temporarily_disable_titan_ui("whatsapp_webview")
            
            # Get announce_widget_type setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
            
            def launch_whatsapp():
                try:
                    # Additional safety check in wx.CallAfter
                    if self._shutdown_in_progress or not self.main_frame:
                        return
                        
                    whatsapp_window = whatsapp_webview.show_whatsapp_webview(self.main_frame)
                    if whatsapp_window and not whatsapp_window.IsBeingDeleted():
                        # Safely bind close event to re-enable Titan UI when webview closes
                        try:
                            whatsapp_window.Bind(wx.EVT_CLOSE, lambda evt: self._safe_on_dialog_close("whatsapp_webview", evt))
                        except Exception as bind_error:
                            print(f"Warning: Could not bind close event: {bind_error}")
                            
                        # Speak announcement safely
                        try:
                            if announce_widget_type:
                                self.speak(_("WhatsApp, web application"))
                            else:
                                self.speak(_("WhatsApp"))
                        except Exception as speak_error:
                            print(f"Warning: Could not speak WhatsApp announcement: {speak_error}")
                    else:
                        # Re-enable Titan UI if window creation failed
                        self._safe_on_dialog_close("whatsapp_webview", None)
                        
                except Exception as launch_error:
                    print(f"Error in launch_whatsapp: {launch_error}")
                    # Re-enable Titan UI on error
                    self._safe_on_dialog_close("whatsapp_webview", None)
                    try:
                        self.speak(_("Error opening WhatsApp WebView"))
                    except:
                        pass
            
            # Use safer wx.CallAfter with error handling
            try:
                wx.CallAfter(launch_whatsapp)
            except Exception as callafter_error:
                print(f"Error with wx.CallAfter: {callafter_error}")
                # Re-enable Titan UI if CallAfter fails
                self._safe_on_dialog_close("whatsapp_webview", None)
                self.speak(_("Error opening WhatsApp WebView"))
            
        except ImportError:
            print("WhatsApp WebView module not available")
            self.speak(_("WhatsApp WebView not available"))
        except Exception as e:
            print(f"Error opening WhatsApp WebView from invisible UI: {e}")
            # Re-enable Titan UI on any error
            self._safe_on_dialog_close("whatsapp_webview", None)
            try:
                self.speak(_("Error opening WhatsApp WebView"))
            except:
                pass

    def open_titannet(self):
        """Open Titan-Net GUI window"""
        try:
            # Check if we have a valid main frame
            if not self.main_frame or self._shutdown_in_progress:
                self.speak(_("Cannot open Titan-Net - application not ready"))
                return

            # Check if titan_client exists
            if not hasattr(self.main_frame, 'titan_client'):
                self.speak(_("Titan-Net client not available"))
                return

            # Auto-disable Titan UI when Titan-Net window opens
            if self.titan_ui_mode:
                self.temporarily_disable_titan_ui("titannet_window")

            # Get announce_widget_type setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'

            def launch_titannet():
                try:
                    # Additional safety check in wx.CallAfter
                    if self._shutdown_in_progress or not self.main_frame:
                        return

                    # Check if logged in
                    if self.main_frame.titan_logged_in:
                        # Already logged in - open main window
                        from src.network.titan_net_gui import show_titan_net_window

                        if self.main_frame.titan_client.is_connected:
                            titannet_window = show_titan_net_window(self.main_frame, self.main_frame.titan_client)

                            if titannet_window and not titannet_window.IsBeingDeleted():
                                # Safely bind close event to re-enable Titan UI
                                try:
                                    titannet_window.Bind(wx.EVT_CLOSE, lambda evt: self._safe_on_dialog_close("titannet_window", evt))
                                except Exception as bind_error:
                                    print(f"Warning: Could not bind close event: {bind_error}")

                                # Speak announcement safely
                                try:
                                    if announce_widget_type:
                                        self.speak(_("Titan-Net, application"))
                                    else:
                                        self.speak(_("Titan-Net"))
                                except Exception as speak_error:
                                    print(f"Warning: Could not speak Titan-Net announcement: {speak_error}")
                            else:
                                # Re-enable Titan UI if window creation failed
                                self._safe_on_dialog_close("titannet_window", None)
                        else:
                            self.speak(_("Not connected to Titan-Net server"))
                            self._safe_on_dialog_close("titannet_window", None)

                    else:
                        # Not logged in - show login dialog
                        from src.network.titan_net_gui import show_login_dialog

                        logged_in, offline_mode = show_login_dialog(self.main_frame, self.main_frame.titan_client)

                        if logged_in:
                            self.main_frame.titan_logged_in = True
                            self.main_frame.titan_username = self.main_frame.titan_client.username

                            # Setup callbacks
                            self.main_frame.setup_titannet_callbacks()

                            # Open main window
                            from src.network.titan_net_gui import show_titan_net_window
                            titannet_window = show_titan_net_window(self.main_frame, self.main_frame.titan_client)

                            if titannet_window and not titannet_window.IsBeingDeleted():
                                try:
                                    titannet_window.Bind(wx.EVT_CLOSE, lambda evt: self._safe_on_dialog_close("titannet_window", evt))
                                except Exception as bind_error:
                                    print(f"Warning: Could not bind close event: {bind_error}")

                                # Speak announcement
                                try:
                                    if announce_widget_type:
                                        self.speak(_("Titan-Net, application"))
                                    else:
                                        self.speak(_("Titan-Net"))
                                except Exception as speak_error:
                                    print(f"Warning: Could not speak Titan-Net announcement: {speak_error}")
                            else:
                                self._safe_on_dialog_close("titannet_window", None)

                        elif offline_mode:
                            self.speak(_("Offline mode selected"))
                            self._safe_on_dialog_close("titannet_window", None)
                        else:
                            self.speak(_("Login cancelled"))
                            self._safe_on_dialog_close("titannet_window", None)

                except Exception as launch_error:
                    print(f"Error in launch_titannet: {launch_error}")
                    import traceback
                    traceback.print_exc()
                    # Re-enable Titan UI on error
                    self._safe_on_dialog_close("titannet_window", None)
                    try:
                        self.speak(_("Error opening Titan-Net"))
                    except:
                        pass

            # Use safer wx.CallAfter with error handling
            try:
                wx.CallAfter(launch_titannet)
            except Exception as callafter_error:
                print(f"Error with wx.CallAfter: {callafter_error}")
                # Re-enable Titan UI if CallAfter fails
                self._safe_on_dialog_close("titannet_window", None)
                self.speak(_("Error opening Titan-Net"))

        except ImportError as ie:
            print(f"Titan-Net module not available: {ie}")
            import traceback
            traceback.print_exc()
            self.speak(_("Titan-Net not available"))
        except Exception as e:
            print(f"Error opening Titan-Net from invisible UI: {e}")
            import traceback
            traceback.print_exc()
            # Re-enable Titan UI on any error
            self._safe_on_dialog_close("titannet_window", None)
            try:
                self.speak(_("Error opening Titan-Net"))
            except:
                pass

    def open_eltenlink(self):
        """Open EltenLink (Beta) GUI window"""
        try:
            # Check if we have a valid main frame
            if not self.main_frame or self._shutdown_in_progress:
                self.speak(_("Cannot open EltenLink (Beta) - application not ready"))
                return

            # Auto-disable Titan UI when EltenLink window opens
            if self.titan_ui_mode:
                self.temporarily_disable_titan_ui("eltenlink_window")

            # Get announce_widget_type setting
            announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'

            def launch_eltenlink():
                try:
                    # Additional safety check in wx.CallAfter
                    if self._shutdown_in_progress or not self.main_frame:
                        return

                    # Show EltenLink login dialog
                    from src.eltenlink_client.elten_gui import show_elten_login

                    eltenlink_window = show_elten_login(self.main_frame)

                    if eltenlink_window and not eltenlink_window.IsBeingDeleted():
                        # Safely bind close event to re-enable Titan UI
                        try:
                            eltenlink_window.Bind(wx.EVT_CLOSE, lambda evt: self._safe_on_dialog_close("eltenlink_window", evt))
                        except Exception as bind_error:
                            print(f"Warning: Could not bind close event: {bind_error}")

                        # Speak announcement safely
                        try:
                            if announce_widget_type:
                                self.speak(_("EltenLink (Beta), application"))
                            else:
                                self.speak(_("EltenLink (Beta)"))
                        except Exception as speak_error:
                            print(f"Warning: Could not speak EltenLink (Beta) announcement: {speak_error}")
                    else:
                        # Re-enable Titan UI if window creation failed
                        self._safe_on_dialog_close("eltenlink_window", None)
                        self.speak(_("Login cancelled"))

                except Exception as launch_error:
                    print(f"Error in launch_eltenlink: {launch_error}")
                    import traceback
                    traceback.print_exc()
                    # Re-enable Titan UI on error
                    self._safe_on_dialog_close("eltenlink_window", None)
                    try:
                        self.speak(_("Error opening EltenLink (Beta)"))
                    except:
                        pass

            # Use safer wx.CallAfter with error handling
            try:
                wx.CallAfter(launch_eltenlink)
            except Exception as callafter_error:
                print(f"Error with wx.CallAfter: {callafter_error}")
                # Re-enable Titan UI if CallAfter fails
                self._safe_on_dialog_close("eltenlink_window", None)
                self.speak(_("Error opening EltenLink (Beta)"))

        except ImportError as ie:
            print(f"EltenLink (Beta) module not available: {ie}")
            import traceback
            traceback.print_exc()
            self.speak(_("EltenLink (Beta) not available"))
        except Exception as e:
            print(f"Error opening EltenLink (Beta) from invisible UI: {e}")
            import traceback
            traceback.print_exc()
            # Re-enable Titan UI on any error
            self._safe_on_dialog_close("eltenlink_window", None)
            try:
                self.speak(_("Error opening EltenLink (Beta)"))
            except:
                pass

    def show_start_menu(self):
        """Pokaż klasyczne Menu Start gdy aplikacja jest zminimalizowana"""
        try:
            # Sprawdź czy aplikacja główna ma start menu
            if hasattr(self.main_frame, 'start_menu') and self.main_frame.start_menu:
                import platform
                if platform.system() == "Windows":
                    # Pokaż menu Start
                    wx.CallAfter(self.main_frame.start_menu.show_menu)
                    self.speak(_("Menu Start"))
        except Exception as e:
            print(f"Error showing start menu from invisible UI: {e}")
    
# F6 program switching method removed