import pygame
import os
import sys
import threading
import time
import accessible_output3.outputs.auto
from app_manager import get_applications, open_application
from game_manager import get_games, open_game
from notifications import get_current_time, get_battery_status, get_volume_level, get_network_status
from sound import initialize_sound, play_focus_sound, play_select_sound, play_statusbar_sound, play_sound
from translation import set_language
from settings import get_setting, set_setting
from component_manager import ComponentManager
from help import show_help

# Import stereo speech functionality
try:
    from stereo_speech import speak_stereo
    STEREO_SPEECH_AVAILABLE = True
except ImportError:
    STEREO_SPEECH_AVAILABLE = False
    print("Warning: stereo_speech module not available")

# Import wx for GUI mode
try:
    import wx
    WX_AVAILABLE = True
except ImportError:
    WX_AVAILABLE = False

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Initialize screen reader output with stereo support
speaker = accessible_output3.outputs.auto.Auto()

def speak_klango(text, position=0.0, pitch_offset=0, interrupt=True):
    """
    Speak text using the same method as IUI.
    Position: -1.0 (left) to 1.0 (right), 0.0 (center)
    """
    try:
        # Check stereo speech setting safely (same as IUI)
        try:
            stereo_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() == 'true'
            
            if stereo_enabled and STEREO_SPEECH_AVAILABLE:
                def speak_with_stereo():
                    try:
                        # Zatrzymaj poprzednią mowę jeśli interrupt=True
                        if interrupt:
                            try:
                                from stereo_speech import get_stereo_speech
                                stereo_speech = get_stereo_speech()
                                if stereo_speech:
                                    stereo_speech.stop()
                            except Exception as e:
                                print(f"Error stopping stereo speech: {e}")
                        
                        speak_stereo(text, position=position, pitch_offset=pitch_offset, async_mode=True)
                    except Exception as e:
                        print(f"Error in stereo speech: {e}")
                        # Fallback to regular TTS
                        speaker.output(text)
                
                # Use daemon thread with timeout protection (same as IUI)
                thread = threading.Thread(target=speak_with_stereo, daemon=True)
                thread.start()
            else:
                # Standard TTS without stereo (same as IUI)
                def speak_regular():
                    try:
                        if interrupt and hasattr(speaker, 'stop'):
                            speaker.stop()
                        speaker.output(text)
                    except Exception as e:
                        print(f"Error in standard speech: {e}")
                
                # Use daemon thread for consistency
                thread = threading.Thread(target=speak_regular, daemon=True)
                thread.start()
                
        except Exception as e:
            print(f"Error in speech configuration: {e}")
            # Final fallback
            speaker.output(text)
            
    except Exception as e:
        print(f"Critical error in speak_klango: {e}")
        # Final fallback
        try:
            speaker.output(text)
        except:
            pass

class KlangoMode:
    def __init__(self, version):
        """Initialize Klango Mode interface."""
        self.version = version
        self.running = False
        self.menu_open = False
        self.current_menu = None
        self.current_item = 0
        self.menu_stack = []
        
        # Initialize pygame without display (only audio and events)
        try:
            # Set SDL to not require display
            os.environ['SDL_VIDEODRIVER'] = 'dummy'
            pygame.mixer.pre_init()
            pygame.mixer.init()
            pygame.init()
            print("Pygame initialized in headless mode")
        except pygame.error as e:
            print(f"Pygame initialization error: {e}")
            # Try fallback initialization
            try:
                pygame.init()
                print("Pygame initialized with fallback method")
            except Exception as fallback_error:
                print(f"Pygame fallback initialization failed: {fallback_error}")
        
        # Initialize sound system
        initialize_sound()
        
        # Load settings for stereo support
        self._stereo_sound_enabled = None
        self._stereo_speech_enabled = None
        self._load_stereo_settings()
        
        # Initialize component manager
        self.component_manager = ComponentManager()
        
        # Define main menu structure
        self.main_menu = [
            {"name": _("Applications"), "type": "submenu", "items": [], "expanded": False},
            {"name": _("Games"), "type": "submenu", "items": [], "expanded": False},
            {"name": _("Titan IM"), "type": "submenu", "items": [
                {"name": _("Telegram"), "type": "action", "action": self.open_telegram},
                {"name": _("Messenger"), "type": "action", "action": self.open_messenger},
                {"name": _("WhatsApp"), "type": "action", "action": self.open_whatsapp}
            ], "expanded": False},
            {"name": _("Status Bar"), "type": "submenu", "items": [
                {"name": _("Current Time"), "type": "action", "action": self.announce_time},
                {"name": _("Battery Status"), "type": "action", "action": self.announce_battery},
                {"name": _("Volume Level"), "type": "action", "action": self.announce_volume}
            ], "expanded": False},
            {"name": _("Program"), "type": "submenu", "items": [
                {"name": _("Settings"), "type": "action", "action": self.open_settings},
                {"name": _("Component Manager"), "type": "action", "action": self.open_component_manager},
                {"name": _("Help"), "type": "action", "action": self.show_help},
                {"name": _("Exit"), "type": "action", "action": self.exit_program}
            ], "expanded": False},
            {"name": _("Components"), "type": "submenu", "items": [], "expanded": False}
        ]
        
        # Load applications and games
        self.load_applications()
        self.load_games()
        self.load_components()
        self.load_status_bar_items()
        
        # Disable Windows+M minimize
        self.disable_win_minimize()
    
    def load_applications(self):
        """Load applications into the menu."""
        try:
            apps = get_applications()
            app_items = []
            for app in apps:
                app_items.append({
                    "name": app.get('name', app.get('shortname', 'Unknown')),
                    "type": "action",
                    "action": lambda a=app: self.launch_application(a)
                })
            self.main_menu[0]["items"] = app_items
        except Exception as e:
            print(f"Error loading applications: {e}")
            self.main_menu[0]["items"] = []
    
    def load_games(self):
        """Load games into the menu."""
        try:
            games = get_games()
            game_items = []
            for game in games:
                game_items.append({
                    "name": game.get('name', 'Unknown Game'),
                    "type": "action",
                    "action": lambda g=game: self.launch_game(g)
                })
            self.main_menu[1]["items"] = game_items
        except Exception as e:
            print(f"Error loading games: {e}")
            self.main_menu[1]["items"] = []
    
    def load_components(self):
        """Load components into the menu."""
        try:
            component_items = []
            if self.component_manager:
                component_menu_functions = self.component_manager.get_component_menu_functions()
                for name, func in component_menu_functions.items():
                    component_items.append({
                        "name": name,
                        "type": "action",
                        "action": lambda f=func: self.execute_component_function(f)
                    })
            self.main_menu[5]["items"] = component_items
        except Exception as e:
            print(f"Error loading components: {e}")
            self.main_menu[5]["items"] = []
    
    def load_status_bar_items(self):
        """Load status bar items with same names as GUI but console actions."""
        try:
            from notifications import get_current_time, get_battery_status, get_volume_level, get_network_status
            
            status_items = [
                {"name": _("Clock: {}").format(get_current_time()), "type": "action", "action": self.announce_time},
                {"name": _("Battery level: {}").format(get_battery_status()), "type": "action", "action": self.announce_battery},
                {"name": _("Volume: {}").format(get_volume_level()), "type": "action", "action": self.announce_volume},
                {"name": get_network_status(), "type": "action", "action": self.announce_network}
            ]
            print(f"DEBUG: Status bar items loaded successfully: {[item['name'] for item in status_items]}")
            # Update Status Bar submenu (index 3 in main menu)
            self.main_menu[3]["items"] = status_items
        except Exception as e:
            print(f"Error loading status bar items: {e}")
            # Fallback to simple announcements
            fallback_items = [
                {"name": _("Current Time"), "type": "action", "action": self.announce_time},
                {"name": _("Battery Status"), "type": "action", "action": self.announce_battery},
                {"name": _("Volume Level"), "type": "action", "action": self.announce_volume}
            ]
            print(f"DEBUG: Using fallback status bar items: {[item['name'] for item in fallback_items]}")
            self.main_menu[3]["items"] = fallback_items
    
    def announce_network(self):
        """Announce network status."""
        try:
            from notifications import get_network_status
            network_str = get_network_status()
            speak_klango(f"{_('Network')}: {network_str}")
        except Exception as e:
            print(f"Error getting network status: {e}")
            speak_klango(_("Error getting network status"))
    
    def disable_win_minimize(self):
        """Disable Windows+M minimize functionality."""
        try:
            import ctypes
            from ctypes import wintypes
            import ctypes.wintypes
            
            # Constants for Windows API
            WH_KEYBOARD_LL = 13
            WM_KEYDOWN = 0x0100
            WM_SYSKEYDOWN = 0x0104
            VK_LWIN = 0x5B
            VK_RWIN = 0x5C
            VK_M = 0x4D
            
            # Hook procedure to intercept Win+M
            def low_level_keyboard_proc(nCode, wParam, lParam):
                if nCode >= 0:
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        # Get key info
                        kbd_struct = ctypes.cast(lParam, ctypes.POINTER(ctypes.wintypes.POINT)).contents
                        vk_code = kbd_struct.x  # Virtual key code is in x field for KBDLLHOOKSTRUCT
                        
                        # Check for Win+M combination
                        win_key_pressed = (ctypes.windll.user32.GetAsyncKeyState(VK_LWIN) & 0x8000) or \
                                        (ctypes.windll.user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
                        
                        if win_key_pressed and vk_code == VK_M:
                            # Block the key combination
                            return 1
                
                # Call next hook
                return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)
            
            # Set up the hook
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32
            
            # Define hook procedure type
            HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            
            # Install the hook
            hook_proc = HOOKPROC(low_level_keyboard_proc)
            self.keyboard_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_proc, 
                                                        kernel32.GetModuleHandleW(None), 0)
            
            if self.keyboard_hook:
                print("Win+M minimize disabled successfully")
            else:
                print("Failed to disable Win+M minimize")
                
        except Exception as e:
            print(f"Could not disable Win+M: {e}")
    
    def cleanup_hooks(self):
        """Cleanup keyboard hooks on exit."""
        try:
            if hasattr(self, 'keyboard_hook') and self.keyboard_hook:
                ctypes.windll.user32.UnhookWindowsHookEx(self.keyboard_hook)
                print("Keyboard hook cleaned up")
        except Exception as e:
            print(f"Error cleaning up hooks: {e}")
    
    def run(self):
        """Main event loop for Klango Mode."""
        self.running = True
        
        # Announce startup
        print("Starting Klango Mode...")
        # Remove startup announcement as requested
        print("Klango Mode is now running. Controls:")
        print("- Press 'M' to open menu")
        print("- Press 'A'/'D' to navigate left/right between menu items")
        print("- Press 'W'/'S' to collapse/expand menu items")
        print("- Press Enter to activate menu item")
        print("- Press ESC to close menu")
        print("- Press 'Q' to quit")
        
        # Remove debug channel test messages
        
        try:
            import msvcrt
            while self.running:
                # Check for keyboard input
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    self.handle_console_keypress(key)
                
                # Small delay to prevent high CPU usage
                time.sleep(0.1)
        except ImportError:
            # Fallback to pygame events if msvcrt not available
            try:
                clock = pygame.time.Clock()
                while self.running:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            self.running = False
                        elif event.type == pygame.KEYDOWN:
                            self.handle_keypress(event.key, event.mod)
                    
                    clock.tick(10)  # Lower FPS to reduce CPU usage
            except:
                # Final fallback - simple input loop
                while self.running:
                    try:
                        user_input = input("Press Alt to open menu, 'q' to quit: ")
                        if user_input.lower() == 'q':
                            self.running = False
                        elif user_input.lower() == 'alt' or user_input == '':
                            if not self.menu_open:
                                self.open_main_menu()
                    except (EOFError, KeyboardInterrupt):
                        self.running = False
        
        # Cleanup before exit
        self.cleanup_hooks()
        try:
            pygame.quit()
        except:
            pass
    
    def handle_console_keypress(self, key):
        """Handle console keyboard input."""
        try:
            # Convert bytes to character
            if isinstance(key, bytes):
                key = key.decode('utf-8')
            
            # Handle special keys
            if key == '\x1b':  # ESC key
                if self.menu_open:
                    self.close_menu()
                else:
                    self.running = False
            elif key == '\r' or key == '\n':  # Enter key
                if self.menu_open:
                    self.activate_current_item()
                else:
                    self.open_main_menu()
            elif key == 'q' or key == 'Q':
                self.running = False
            elif key == 'm' or key == 'M':  # 'M' for Menu
                if not self.menu_open:
                    self.open_main_menu()
                else:
                    # Close menu if already open
                    self.close_menu()
            elif self.menu_open:
                # Menu navigation - Left/Right for menu items, Up/Down for expand/collapse
                if key == 'a' or key == 'A':  # A for left (previous item)
                    self.navigate_left()
                elif key == 'd' or key == 'D':  # D for right (next item)
                    self.navigate_right()
                elif key == 'w' or key == 'W':  # W for up (collapse)
                    self.collapse_item()
                elif key == 's' or key == 'S':  # S for down (expand)
                    self.expand_item()
            else:
                # Arrow key guidance when menu is not open
                if key == 'a' or key == 'A' or key == 'd' or key == 'D' or key == 'w' or key == 'W' or key == 's' or key == 'S':
                    speak_klango(_("To open a menu, press alt"))
        except Exception as e:
            print(f"Error handling keypress: {e}")
    
    def handle_keypress(self, key, mod):
        """Handle keyboard input."""
        # Alt key opens main menu
        if key == pygame.K_LALT or key == pygame.K_RALT:
            if not self.menu_open:
                self.open_main_menu()
            return
        
        # If no menu is open, provide guidance for arrow keys
        if not self.menu_open:
            # Arrow key guidance when menu is not open
            if key in [pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN]:
                speak_klango(_("To open a menu, press alt"))
            return
        
        # Navigation keys
        if key == pygame.K_UP:
            self.navigate_up()
        elif key == pygame.K_DOWN:
            self.navigate_down()
        elif key == pygame.K_RETURN:
            self.activate_current_item()
        elif key == pygame.K_ESCAPE:
            self.close_menu()
    
    def open_main_menu(self):
        """Open the main menu."""
        self.menu_open = True
        self.current_menu = self.main_menu
        self.current_item = 0
        self.menu_stack = []
        
        # Play context menu opening sound and announce menu
        play_sound("contextmenu.ogg")
        speak_klango(_("Menu"), position=0.0, pitch_offset=0, interrupt=True)
        
        # Announce current item
        if self.current_menu:
            # Calculate stereo position for current item
            if len(self.current_menu) > 1:
                stereo_position = -1.0 + (2.0 * self.current_item / (len(self.current_menu) - 1))
            else:
                stereo_position = 0.0
            speak_klango(self.current_menu[self.current_item]["name"], position=stereo_position, pitch_offset=0, interrupt=True)
    
    def navigate_left(self):
        """Navigate left (previous item) in the menu."""
        if self.current_menu and len(self.current_menu) > 0:
            # Hard boundaries - don't wrap around
            if self.current_item > 0:
                self.current_item -= 1
                self.play_focus_sound_stereo()
                
                # Use stereo speech if enabled
                item_name = self.current_menu[self.current_item]["name"]
                if self.is_stereo_speech_enabled():
                    # Calculate stereo position like IUI: left (index 0) to right (last index)
                    num_elements = len(self.current_menu)
                    if num_elements > 1:
                        # Pan horizontally (0.0-1.0)
                        pan = self.current_item / (num_elements - 1)
                        # Convert pan to stereo position (-1.0 to 1.0)
                        stereo_position = (pan * 2.0) - 1.0
                    else:
                        stereo_position = 0.0
                    speak_klango(item_name, position=stereo_position, pitch_offset=0, interrupt=True)
                else:
                    speak_klango(item_name, position=0.0, pitch_offset=0, interrupt=True)
            else:
                # At beginning - play boundary sound
                play_sound("endoflist.ogg")
    
    def navigate_right(self):
        """Navigate right (next item) in the menu."""
        if self.current_menu and len(self.current_menu) > 0:
            # Hard boundaries - don't wrap around
            if self.current_item < len(self.current_menu) - 1:
                self.current_item += 1
                self.play_focus_sound_stereo()
                
                # Use stereo speech if enabled
                item_name = self.current_menu[self.current_item]["name"]
                if self.is_stereo_speech_enabled():
                    # Calculate stereo position like IUI: left (index 0) to right (last index)
                    num_elements = len(self.current_menu)
                    if num_elements > 1:
                        # Pan horizontally (0.0-1.0)
                        pan = self.current_item / (num_elements - 1)
                        # Convert pan to stereo position (-1.0 to 1.0)
                        stereo_position = (pan * 2.0) - 1.0
                    else:
                        stereo_position = 0.0
                    speak_klango(item_name, position=stereo_position, pitch_offset=0, interrupt=True)
                else:
                    speak_klango(item_name, position=0.0, pitch_offset=0, interrupt=True)
            else:
                # At end - play boundary sound
                play_sound("endoflist.ogg")
    
    def expand_item(self):
        """Expand current submenu item (Down key/S) and enter it directly."""
        if not self.current_menu or self.current_item >= len(self.current_menu):
            return
        
        item = self.current_menu[self.current_item]
        if item["type"] == "submenu":
            # Enter submenu directly without expanding/collapsing states
            self.activate_current_item()
        else:
            # If it's an action item, execute it
            self.activate_current_item()
    
    def collapse_item(self):
        """Go back to parent menu (Up key/W)."""
        # If we're in a submenu, go back to parent
        if self.menu_stack:
            self.close_menu()
        # If we're in main menu, do nothing
        return
    
    # Legacy methods for compatibility
    def navigate_up(self):
        """Navigate up in the menu (legacy - now collapse)."""
        self.collapse_item()
    
    def navigate_down(self):
        """Navigate down in the menu (legacy - now expand)."""
        self.expand_item()
    
    def activate_current_item(self):
        """Activate the current menu item."""
        if not self.current_menu or self.current_item >= len(self.current_menu):
            return
        
        item = self.current_menu[self.current_item]
        
        if item["type"] == "submenu":
            # Open submenu
            self.open_submenu(item)
        elif item["type"] == "action":
            # Execute action
            play_select_sound()
            if "action" in item and callable(item["action"]):
                try:
                    item["action"]()
                except Exception as e:
                    print(f"Error executing action: {e}")
                    speak_klango(_("Error executing action"))
    
    def open_submenu(self, submenu_item):
        """Open a submenu."""
        if "items" not in submenu_item or not submenu_item["items"]:
            speak_klango(_("Empty menu"), position=0.0, pitch_offset=0, interrupt=True)
            return
        
        # Play focus extended sound
        self.play_focus_extended_sound()
        
        # Save current menu state
        self.menu_stack.append({
            "menu": self.current_menu,
            "item": self.current_item
        })
        
        # Switch to submenu
        self.current_menu = submenu_item["items"]
        self.current_item = 0
        
        # Announce first item with higher pitch for expansion
        first_item_name = self.current_menu[self.current_item]["name"]
        
        # Calculate stereo position for first item
        if len(self.current_menu) > 1:
            stereo_position = -1.0  # First item is always leftmost
        else:
            stereo_position = 0.0
            
        speak_klango(first_item_name, position=stereo_position, pitch_offset=30, interrupt=True)
    
    def close_menu(self):
        """Close current menu or submenu."""
        if self.menu_stack:
            # Return to parent menu - play collapse sound
            play_sound("focus_collabsed.ogg")
            parent = self.menu_stack.pop()
            self.current_menu = parent["menu"]
            self.current_item = parent["item"]
            
            # Announce current item with lower pitch for collapse
            # Calculate stereo position for current item
            if len(self.current_menu) > 1:
                stereo_position = -1.0 + (2.0 * self.current_item / (len(self.current_menu) - 1))
            else:
                stereo_position = 0.0
            speak_klango(self.current_menu[self.current_item]["name"], position=stereo_position, pitch_offset=-30, interrupt=True)
        else:
            # Close main menu
            self.menu_open = False
            self.current_menu = None
            self.current_item = 0
            play_sound("contextmenuclose.ogg")
            # Remove menu closed message
    
    def play_focus_sound_stereo(self):
        """Play regular focus sound with stereo support."""
        try:
            # Check if stereo sound is enabled
            if self.is_stereo_sound_enabled() and self.current_menu:
                # Calculate pan position based on current item
                pan = 0
                if len(self.current_menu) > 1:
                    pan = self.current_item / (len(self.current_menu) - 1)
                play_focus_sound(pan=pan)
            else:
                play_focus_sound()
        except Exception as e:
            print(f"Could not play focus sound: {e}")
            play_focus_sound()  # Fallback
    
    def play_focus_extended_sound(self):
        """Play focus_extended.ogg sound."""
        try:
            if self.is_stereo_sound_enabled():
                play_sound("focus_expanded.ogg")
            else:
                play_sound("focus_expanded.ogg")
        except Exception as e:
            print(f"Could not play focus_expanded sound: {e}")
    
    def play_focus_collapsed_sound(self):
        """Play focus_collapsed.ogg sound."""
        try:
            if self.is_stereo_sound_enabled():
                play_sound("focus_collabsed.ogg")
            else:
                play_sound("focus_collabsed.ogg")
        except Exception as e:
            print(f"Could not play focus_collabsed sound: {e}")
    
    def _load_stereo_settings(self):
        """Load stereo settings from configuration."""
        try:
            # Load stereo sound setting (from sound section)
            self._stereo_sound_enabled = get_setting('stereo_sound', 'False', section='sound').lower() in ['true', '1']
            
            # Load stereo speech setting (from invisible_interface section) 
            self._stereo_speech_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() in ['true', '1']
        except:
            self._stereo_sound_enabled = False
            self._stereo_speech_enabled = False
    
    def is_stereo_sound_enabled(self):
        """Check if stereo sound is enabled in settings."""
        if self._stereo_sound_enabled is None:
            self._load_stereo_settings()
        return self._stereo_sound_enabled
    
    def is_stereo_speech_enabled(self):
        """Check if stereo speech is enabled in settings."""
        if self._stereo_speech_enabled is None:
            self._load_stereo_settings()
        return self._stereo_speech_enabled
    
    # Action methods
    def launch_application(self, app):
        """Launch an application."""
        try:
            # Launch without announcement
            open_application(app)
            self.close_menu()
        except Exception as e:
            print(f"Error launching application: {e}")
            speak_klango(_("Error launching application"))
    
    def launch_game(self, game):
        """Launch a game."""
        try:
            # Launch without announcement
            open_game(game)
            self.close_menu()
        except Exception as e:
            print(f"Error launching game: {e}")
            speak_klango(_("Error launching game"))
    
    def open_telegram(self):
        """Open Telegram."""
        try:
            # Import telegram client safely
            telegram_client = None
            try:
                import telegram_client
                if telegram_client and telegram_client.is_connected():
                    # Open without announcement
                    # Create Telegram submenu
                    telegram_submenu = [
                        {"name": _("Contacts"), "type": "action", "action": self.show_telegram_contacts},
                        {"name": _("Groups"), "type": "action", "action": self.show_telegram_groups},
                        {"name": _("Back"), "type": "action", "action": self.close_titan_im_submenu}
                    ]
                    self.open_custom_submenu(_("Telegram Menu"), telegram_submenu)
                else:
                    speak_klango(_("Not connected to {}").format("Telegram"))
            except Exception as e:
                print(f"Error with Telegram: {e}")
                speak_klango(_("Telegram client not available"))
            
        except Exception as e:
            print(f"Error opening Telegram: {e}")
            speak_klango(_("Error opening Telegram"))
    
    def open_messenger(self):
        """Open Facebook Messenger."""
        try:
            # Open without announcement
            # Import messenger webview
            try:
                from messenger_webview import show_messenger_webview
                show_messenger_webview()
                self.close_menu()
            except Exception as e:
                print(f"Error with Messenger: {e}")
                speak_klango(_("Messenger not available"), position=0.0, pitch_offset=0, interrupt=True)
        except Exception as e:
            print(f"Error opening Messenger: {e}")
            speak_klango(_("Error opening Messenger"), position=0.0, pitch_offset=0, interrupt=True)
    
    def open_whatsapp(self):
        """Open WhatsApp."""
        try:
            # Open without announcement
            # Import whatsapp webview
            try:
                from whatsapp_webview import show_whatsapp_webview
                show_whatsapp_webview()
                self.close_menu()
            except Exception as e:
                print(f"Error with WhatsApp: {e}")
                speak_klango(_("WhatsApp not available"), position=0.0, pitch_offset=0, interrupt=True)
        except Exception as e:
            print(f"Error opening WhatsApp: {e}")
            speak_klango(_("Error opening WhatsApp"), position=0.0, pitch_offset=0, interrupt=True)
    
    def open_custom_submenu(self, title, items):
        """Open a custom submenu."""
        # Save current menu state
        self.menu_stack.append({
            "menu": self.current_menu,
            "item": self.current_item
        })
        
        # Switch to custom submenu
        self.current_menu = items
        self.current_item = 0
        
        # Announce submenu and first item
        speak_klango(title)
        if self.current_menu:
            # Calculate stereo position for current item
            if len(self.current_menu) > 1:
                stereo_position = -1.0 + (2.0 * self.current_item / (len(self.current_menu) - 1))
            else:
                stereo_position = 0.0
            speak_klango(self.current_menu[self.current_item]["name"], position=stereo_position, pitch_offset=0, interrupt=True)
    
    def show_telegram_contacts(self):
        """Show Telegram contacts."""
        try:
            speak_klango(_("Loading contacts"))
            # TODO: Implement contact loading from telegram_client
            self.close_menu()
        except Exception as e:
            print(f"Error loading contacts: {e}")
            speak_klango(_("Error loading contacts"))
    
    def show_telegram_groups(self):
        """Show Telegram groups."""
        try:
            speak_klango(_("Loading groups"))
            # TODO: Implement group loading from telegram_client
            self.close_menu()
        except Exception as e:
            print(f"Error loading groups: {e}")
            speak_klango(_("Error loading groups"))
    
    def close_titan_im_submenu(self):
        """Close Titan IM submenu."""
        self.close_menu()
    
    def announce_time(self):
        """Announce current time."""
        try:
            time_str = get_current_time()
            speak_klango(f"{_('Current time')}: {time_str}")
        except Exception as e:
            print(f"Error getting time: {e}")
            speak_klango(_("Error getting time"))
    
    def announce_battery(self):
        """Announce battery status."""
        try:
            battery_str = get_battery_status()
            speak_klango(f"{_('Battery')}: {battery_str}")
        except Exception as e:
            print(f"Error getting battery status: {e}")
            speak_klango(_("Error getting battery status"))
    
    def announce_volume(self):
        """Announce volume level."""
        try:
            volume_str = get_volume_level()
            speak_klango(f"{_('Volume')}: {volume_str}")
        except Exception as e:
            print(f"Error getting volume level: {e}")
            speak_klango(_("Error getting volume level"))
    
    def open_settings(self):
        """Open settings."""
        try:
            # Open without announcement
            if WX_AVAILABLE:
                from settingsgui import SettingsFrame
                settings_frame = SettingsFrame(None, title=_("Settings"))
                settings_frame.Show()
            self.close_menu()
        except Exception as e:
            print(f"Error opening settings: {e}")
            speak_klango(_("Error opening settings"))
    
    def open_component_manager(self):
        """Open component manager."""
        try:
            # Open without announcement
            if WX_AVAILABLE:
                from componentmanagergui import ComponentManagerDialog
                if ComponentManagerDialog and self.component_manager:
                    manager_dialog = ComponentManagerDialog(None, title=_("Component Manager"), component_manager=self.component_manager)
                    manager_dialog.ShowModal()
                    manager_dialog.Destroy()
                elif not ComponentManagerDialog:
                    speak_klango(_("Cannot load Component Manager (componentmanagergui.py not found)"))
                elif not self.component_manager:
                    speak_klango(_("Component Manager has not been initialized."))
            self.close_menu()
        except Exception as e:
            print(f"Error opening component manager: {e}")
            speak_klango(_("Error opening component manager"))
    
    def show_help(self):
        """Show help."""
        try:
            # Open without announcement
            show_help()
            self.close_menu()
        except Exception as e:
            print(f"Error showing help: {e}")
            speak_klango(_("Error showing help"))
    
    def exit_program(self):
        """Exit the program using exactly same method as GUI."""
        try:
            from shutdown_question import show_shutdown_dialog
            confirm_exit = self.settings.get('general', {}).get('confirm_exit', 'False').lower() in ['true', '1']
            
            if confirm_exit:
                result = show_shutdown_dialog()
                if result == wx.ID_OK:
                    self.shutdown_app()
                else:
                    print("INFO: Shutdown canceled by user.")
                    speak_klango(_("Exit cancelled"), position=0.0, pitch_offset=0, interrupt=True)
            else:
                self.shutdown_app()
        except Exception as e:
            print(f"Error in exit_program: {e}")
            self.shutdown_app()
    
    def shutdown_app(self):
        """Handles the complete shutdown of the application using same method as GUI."""
        print("INFO: Shutting down application...")
        
        # Hide window immediately for user feedback
        self.Hide()
        
        # Safely disconnect from Telegram if connected
        def safe_shutdown():
            try:
                # Stop system hooks before shutdown
                try:
                    from tce_system import stop_system_hooks
                    stop_system_hooks()
                    print("INFO: System hooks stopped")
                except Exception as e:
                    print(f"Warning: Error stopping system hooks: {e}")
                
                print("INFO: Application terminating now.")
                os._exit(0)
                
            except Exception as e:
                print(f"Critical error during shutdown: {e}")
                os._exit(1)
        
        # Start shutdown in a separate thread
        import threading
        shutdown_thread = threading.Thread(target=safe_shutdown, daemon=True)
        shutdown_thread.start()
    
    def activate_component(self, component):
        """Activate a component."""
        try:
            component_name = component.get('name', 'Unknown Component')
            speak_klango(f"{_('Activating component')}: {component_name}")
            
            # Use component manager to activate the component
            if hasattr(self.component_manager, 'activate_component'):
                self.component_manager.activate_component(component)
            else:
                # Fallback: try to execute component directly
                if 'path' in component:
                    import subprocess
                    subprocess.Popen([component['path']], shell=True)
            
            self.close_menu()
        except Exception as e:
            print(f"Error activating component: {e}")
            speak_klango(_("Error activating component"))
    
    def execute_component_function(self, func):
        """Execute a component function (same as IUI implementation)."""
        try:
            if callable(func):
                # Component functions in IUI expect a parent frame parameter
                # For Klango mode, we pass None since it's console-based
                func(None)
                self.close_menu()
            else:
                speak_klango(_("Invalid component function"))
        except Exception as e:
            print(f"Error executing component function: {e}")
            speak_klango(_("Error executing component function"))

class KlangoFrame(wx.Frame):
    def __init__(self, parent, title, version, settings, component_manager, gui_frame=None):
        """Initialize Klango Mode interface as a wx Frame."""
        super().__init__(parent, title=title, size=(1, 1))  # Minimal size
        self.version = version
        self.settings = settings
        self.component_manager = component_manager
        self.settings_frame = parent  # Reference to settings frame for GUI functions
        self.gui_frame = gui_frame  # Reference to GUI frame for Titan IM functionality
        self.menu_open = False
        self.current_menu = None
        self.current_item = 0
        self.menu_stack = []
        
        # Hide the frame completely
        self.SetPosition((-10000, -10000))  # Move off-screen
        
        # Initialize sound system
        initialize_sound()
        
        # Load settings for stereo support
        self._stereo_sound_enabled = None
        self._stereo_speech_enabled = None
        self._load_stereo_settings()
        
        # Define main menu structure
        self.main_menu = [
            {"name": _("Applications"), "type": "submenu", "items": [], "expanded": False},
            {"name": _("Games"), "type": "submenu", "items": [], "expanded": False},
            {"name": _("Titan IM"), "type": "submenu", "items": [
                {"name": _("Telegram"), "type": "action", "action": self.open_telegram},
                {"name": _("Messenger"), "type": "action", "action": self.open_messenger},
                {"name": _("WhatsApp"), "type": "action", "action": self.open_whatsapp}
            ], "expanded": False},
            {"name": _("Status Bar"), "type": "submenu", "items": [
                {"name": _("Current Time"), "type": "action", "action": self.announce_time},
                {"name": _("Battery Status"), "type": "action", "action": self.announce_battery},
                {"name": _("Volume Level"), "type": "action", "action": self.announce_volume}
            ], "expanded": False},
            {"name": _("Program"), "type": "submenu", "items": [
                {"name": _("Settings"), "type": "action", "action": self.open_settings},
                {"name": _("Component Manager"), "type": "action", "action": self.open_component_manager},
                {"name": _("Help"), "type": "action", "action": self.show_help},
                {"name": _("Exit"), "type": "action", "action": self.exit_program}
            ], "expanded": False},
            {"name": _("Components"), "type": "submenu", "items": [], "expanded": False}
        ]
        
        # Load applications and games
        self.load_applications()
        self.load_games()
        self.load_components()
        self.load_status_bar_items()
        
        # Bind keyboard events
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        
        # Set focus to receive keyboard events
        self.SetCanFocus(True)
        
        # Announce startup
        wx.CallAfter(self.announce_startup)
    
    def announce_startup(self):
        """Announce startup and test stereo speech if enabled."""
        # Remove startup announcement as requested
        pass
        
        # Remove debug channel test messages
    
    def load_applications(self):
        """Load applications into the menu."""
        try:
            apps = get_applications()
            app_items = []
            for app in apps:
                app_items.append({
                    "name": app.get('name', app.get('shortname', 'Unknown')),
                    "type": "action",
                    "action": lambda a=app: self.launch_application(a)
                })
            self.main_menu[0]["items"] = app_items
        except Exception as e:
            self.main_menu[0]["items"] = []
    
    def load_games(self):
        """Load games into the menu."""
        try:
            games = get_games()
            game_items = []
            for game in games:
                game_items.append({
                    "name": game.get('name', _('Unknown Game')),
                    "type": "action",
                    "action": lambda g=game: self.launch_game(g)
                })
            self.main_menu[1]["items"] = game_items
        except Exception as e:
            self.main_menu[1]["items"] = []
    
    def load_components(self):
        """Load components into the menu."""
        try:
            component_items = []
            if self.component_manager:
                component_menu_functions = self.component_manager.get_component_menu_functions()
                for name, func in component_menu_functions.items():
                    component_items.append({
                        "name": name,
                        "type": "action",
                        "action": lambda f=func: self.execute_component_function(f)
                    })
            self.main_menu[5]["items"] = component_items
        except Exception as e:
            print(f"Error loading components: {e}")
            self.main_menu[5]["items"] = []
    
    def load_status_bar_items(self):
        """Load status bar items like IUI using GUI functions."""
        try:
            from notifications import get_current_time, get_battery_status, get_volume_level, get_network_status
            
            status_items = [
                {"name": _("Clock: {}").format(get_current_time()), "type": "action", "action": self.gui_open_time_settings},
                {"name": _("Battery level: {}").format(get_battery_status()), "type": "action", "action": self.gui_open_power_settings},
                {"name": _("Volume: {}").format(get_volume_level()), "type": "action", "action": self.gui_open_volume_mixer},
                {"name": get_network_status(), "type": "action", "action": self.gui_open_network_settings}
            ]
            # Update Status Bar submenu (index 3 in main menu)
            self.main_menu[3]["items"] = status_items
        except Exception as e:
            print(f"Error loading status bar items: {e}")
            # Fallback to simple announcements
            self.main_menu[3]["items"] = [
                {"name": _("Current Time"), "type": "action", "action": self.announce_time},
                {"name": _("Battery Status"), "type": "action", "action": self.announce_battery},
                {"name": _("Volume Level"), "type": "action", "action": self.announce_volume}
            ]
    
    def on_key_down(self, event):
        """Handle keyboard input."""
        keycode = event.GetKeyCode()
        
        # Alt key toggles main menu
        if keycode == wx.WXK_ALT:
            if not self.menu_open:
                self.open_main_menu()
            else:
                self.close_menu()
            return
        
        # Ctrl+Q to quit
        if event.ControlDown() and keycode == ord('Q'):
            self.exit_program()
            return
        
        # If no menu is open, provide guidance for arrow keys
        if not self.menu_open:
            # Arrow key guidance when menu is not open
            if keycode in [wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_UP, wx.WXK_DOWN]:
                speak_klango(_("To open a menu, press alt"))
            event.Skip()
            return
        
        # Navigation keys - Left/Right for menu items, Up/Down for expand/collapse
        if keycode == wx.WXK_LEFT:
            self.navigate_left()
        elif keycode == wx.WXK_RIGHT:
            self.navigate_right()
        elif keycode == wx.WXK_UP:
            self.collapse_item()
        elif keycode == wx.WXK_DOWN:
            self.expand_item()
        elif keycode == wx.WXK_RETURN:
            self.activate_current_item()
        elif keycode == wx.WXK_ESCAPE:
            self.close_menu()
        else:
            event.Skip()
    
    def open_main_menu(self):
        """Open the main menu."""
        self.menu_open = True
        self.current_menu = self.main_menu
        self.current_item = 0
        self.menu_stack = []
        
        # Play context menu opening sound and announce menu
        play_sound("contextmenu.ogg")
        speak_klango(_("Menu"), position=0.0, pitch_offset=0, interrupt=True)
        
        # Announce current item
        if self.current_menu:
            # Calculate stereo position for current item
            if len(self.current_menu) > 1:
                stereo_position = -1.0 + (2.0 * self.current_item / (len(self.current_menu) - 1))
            else:
                stereo_position = 0.0
            speak_klango(self.current_menu[self.current_item]["name"], position=stereo_position, pitch_offset=0, interrupt=True)
    
    def navigate_left(self):
        """Navigate left (previous item) in the menu."""
        if self.current_menu and len(self.current_menu) > 0:
            # Hard boundaries - don't wrap around
            if self.current_item > 0:
                self.current_item -= 1
                self.play_focus_sound_stereo()
                
                # Use stereo speech if enabled
                item_name = self.current_menu[self.current_item]["name"]
                if self.is_stereo_speech_enabled():
                    # Calculate stereo position like IUI: left (index 0) to right (last index)
                    num_elements = len(self.current_menu)
                    if num_elements > 1:
                        # Pan horizontally (0.0-1.0)
                        pan = self.current_item / (num_elements - 1)
                        # Convert pan to stereo position (-1.0 to 1.0)
                        stereo_position = (pan * 2.0) - 1.0
                    else:
                        stereo_position = 0.0
                    speak_klango(item_name, position=stereo_position, pitch_offset=0, interrupt=True)
                else:
                    speak_klango(item_name, position=0.0, pitch_offset=0, interrupt=True)
            else:
                # At beginning - play boundary sound
                play_sound("endoflist.ogg")
    
    def navigate_right(self):
        """Navigate right (next item) in the menu."""
        if self.current_menu and len(self.current_menu) > 0:
            # Hard boundaries - don't wrap around
            if self.current_item < len(self.current_menu) - 1:
                self.current_item += 1
                self.play_focus_sound_stereo()
                
                # Use stereo speech if enabled
                item_name = self.current_menu[self.current_item]["name"]
                if self.is_stereo_speech_enabled():
                    # Calculate stereo position like IUI: left (index 0) to right (last index)
                    num_elements = len(self.current_menu)
                    if num_elements > 1:
                        # Pan horizontally (0.0-1.0)
                        pan = self.current_item / (num_elements - 1)
                        # Convert pan to stereo position (-1.0 to 1.0)
                        stereo_position = (pan * 2.0) - 1.0
                    else:
                        stereo_position = 0.0
                    speak_klango(item_name, position=stereo_position, pitch_offset=0, interrupt=True)
                else:
                    speak_klango(item_name, position=0.0, pitch_offset=0, interrupt=True)
            else:
                # At end - play boundary sound
                play_sound("endoflist.ogg")
    
    def expand_item(self):
        """Enter current submenu item (Down arrow) directly."""
        if not self.current_menu or self.current_item >= len(self.current_menu):
            return
        
        item = self.current_menu[self.current_item]
        if item["type"] == "submenu":
            # Enter submenu directly without expanding/collapsing states
            self.activate_current_item()
        else:
            # If it's an action item, execute it
            self.activate_current_item()
    
    def collapse_item(self):
        """Go back to parent menu (Up arrow)."""
        # If we're in a submenu, go back to parent
        if self.menu_stack:
            self.close_menu()
        # If we're in main menu, do nothing
        return
    
    def activate_current_item(self):
        """Activate the current menu item."""
        if not self.current_menu or self.current_item >= len(self.current_menu):
            return
        
        item = self.current_menu[self.current_item]
        
        if item["type"] == "submenu":
            # Open submenu
            self.open_submenu(item)
        elif item["type"] == "action":
            # Execute action
            play_select_sound()
            if "action" in item and callable(item["action"]):
                try:
                    item["action"]()
                except Exception as e:
                    print(f"Error executing action: {e}")
                    speak_klango(_("Error executing action"))
    
    def open_submenu(self, submenu_item):
        """Open a submenu."""
        if "items" not in submenu_item or not submenu_item["items"]:
            speak_klango(_("Empty menu"), position=0.0, pitch_offset=0, interrupt=True)
            return
        
        # Play focus extended sound
        self.play_focus_extended_sound()
        
        # Save current menu state
        self.menu_stack.append({
            "menu": self.current_menu,
            "item": self.current_item
        })
        
        # Switch to submenu
        self.current_menu = submenu_item["items"]
        self.current_item = 0
        
        # Announce first item with higher pitch for expansion
        first_item_name = self.current_menu[self.current_item]["name"]
        
        # Calculate stereo position for first item
        if len(self.current_menu) > 1:
            stereo_position = -1.0  # First item is always leftmost
        else:
            stereo_position = 0.0
            
        speak_klango(first_item_name, position=stereo_position, pitch_offset=30, interrupt=True)
    
    def close_menu(self):
        """Close current menu or submenu."""
        if self.menu_stack:
            # Return to parent menu - play collapse sound
            play_sound("focus_collabsed.ogg")
            parent = self.menu_stack.pop()
            self.current_menu = parent["menu"]
            self.current_item = parent["item"]
            
            # Announce current item with lower pitch for collapse
            # Calculate stereo position for current item
            if len(self.current_menu) > 1:
                stereo_position = -1.0 + (2.0 * self.current_item / (len(self.current_menu) - 1))
            else:
                stereo_position = 0.0
            speak_klango(self.current_menu[self.current_item]["name"], position=stereo_position, pitch_offset=-30, interrupt=True)
        else:
            # Close main menu
            self.menu_open = False
            self.current_menu = None
            self.current_item = 0
            play_sound("contextmenuclose.ogg")
            # Remove menu closed message
    
    def play_focus_sound_stereo(self):
        """Play regular focus sound with stereo support."""
        try:
            # Check if stereo sound is enabled
            if self.is_stereo_sound_enabled() and self.current_menu:
                # Calculate pan position based on current item
                pan = 0
                if len(self.current_menu) > 1:
                    pan = self.current_item / (len(self.current_menu) - 1)
                play_focus_sound(pan=pan)
            else:
                play_focus_sound()
        except Exception as e:
            print(f"Could not play focus sound: {e}")
            play_focus_sound()  # Fallback
    
    def play_focus_extended_sound(self):
        """Play focus_extended.ogg sound."""
        try:
            if self.is_stereo_sound_enabled():
                play_sound("focus_expanded.ogg")
            else:
                play_sound("focus_expanded.ogg")
        except Exception as e:
            print(f"Could not play focus_expanded sound: {e}")
    
    def play_focus_collapsed_sound(self):
        """Play focus_collapsed.ogg sound."""
        try:
            if self.is_stereo_sound_enabled():
                play_sound("focus_collabsed.ogg")
            else:
                play_sound("focus_collabsed.ogg")
        except Exception as e:
            print(f"Could not play focus_collabsed sound: {e}")
    
    def _load_stereo_settings(self):
        """Load stereo settings from configuration."""
        try:
            # Load stereo sound setting (from sound section)
            self._stereo_sound_enabled = get_setting('stereo_sound', 'False', section='sound').lower() in ['true', '1']
            
            # Load stereo speech setting (from invisible_interface section) 
            self._stereo_speech_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() in ['true', '1']
        except:
            self._stereo_sound_enabled = False
            self._stereo_speech_enabled = False
    
    def is_stereo_sound_enabled(self):
        """Check if stereo sound is enabled in settings."""
        if self._stereo_sound_enabled is None:
            self._load_stereo_settings()
        return self._stereo_sound_enabled
    
    def is_stereo_speech_enabled(self):
        """Check if stereo speech is enabled in settings."""
        if self._stereo_speech_enabled is None:
            self._load_stereo_settings()
        return self._stereo_speech_enabled
    
    # Action methods
    def launch_application(self, app):
        """Launch an application."""
        try:
            # Launch without announcement
            open_application(app)
            self.close_menu()
        except Exception as e:
            print(f"Error launching application: {e}")
            speak_klango(_("Error launching application"))
    
    def launch_game(self, game):
        """Launch a game."""
        try:
            # Launch without announcement
            open_game(game)
            self.close_menu()
        except Exception as e:
            print(f"Error launching game: {e}")
            speak_klango(_("Error launching game"))
    
    def open_telegram(self):
        """Open Telegram."""
        try:
            # Import telegram client safely
            telegram_client = None
            try:
                import telegram_client
                if telegram_client and telegram_client.is_connected():
                    # Open without announcement
                    # Create Telegram submenu
                    telegram_submenu = [
                        {"name": _("Contacts"), "type": "action", "action": self.show_telegram_contacts},
                        {"name": _("Groups"), "type": "action", "action": self.show_telegram_groups},
                        {"name": _("Back"), "type": "action", "action": self.close_titan_im_submenu}
                    ]
                    self.open_custom_submenu(_("Telegram Menu"), telegram_submenu)
                else:
                    speak_klango(_("Not connected to {}").format("Telegram"))
            except Exception as e:
                print(f"Error with Telegram: {e}")
                speak_klango(_("Telegram client not available"))
            
        except Exception as e:
            print(f"Error opening Telegram: {e}")
            speak_klango(_("Error opening Telegram"))
    
    def open_messenger(self):
        """Open Facebook Messenger."""
        try:
            # Open without announcement
            # Import messenger webview
            try:
                from messenger_webview import show_messenger_webview
                show_messenger_webview()
                self.close_menu()
            except Exception as e:
                print(f"Error with Messenger: {e}")
                speak_klango(_("Messenger not available"), position=0.0, pitch_offset=0, interrupt=True)
        except Exception as e:
            print(f"Error opening Messenger: {e}")
            speak_klango(_("Error opening Messenger"), position=0.0, pitch_offset=0, interrupt=True)
    
    def open_whatsapp(self):
        """Open WhatsApp."""
        try:
            # Open without announcement
            # Import whatsapp webview
            try:
                from whatsapp_webview import show_whatsapp_webview
                show_whatsapp_webview()
                self.close_menu()
            except Exception as e:
                print(f"Error with WhatsApp: {e}")
                speak_klango(_("WhatsApp not available"), position=0.0, pitch_offset=0, interrupt=True)
        except Exception as e:
            print(f"Error opening WhatsApp: {e}")
            speak_klango(_("Error opening WhatsApp"), position=0.0, pitch_offset=0, interrupt=True)
    
    def open_custom_submenu(self, title, items):
        """Open a custom submenu."""
        # Save current menu state
        self.menu_stack.append({
            "menu": self.current_menu,
            "item": self.current_item
        })
        
        # Switch to custom submenu
        self.current_menu = items
        self.current_item = 0
        
        # Announce submenu and first item
        speak_klango(title)
        if self.current_menu:
            # Calculate stereo position for current item
            if len(self.current_menu) > 1:
                stereo_position = -1.0 + (2.0 * self.current_item / (len(self.current_menu) - 1))
            else:
                stereo_position = 0.0
            speak_klango(self.current_menu[self.current_item]["name"], position=stereo_position, pitch_offset=0, interrupt=True)
    
    def show_telegram_contacts(self):
        """Show Telegram contacts."""
        try:
            speak_klango(_("Loading contacts"))
            # TODO: Implement contact loading from telegram_client
            self.close_menu()
        except Exception as e:
            print(f"Error loading contacts: {e}")
            speak_klango(_("Error loading contacts"))
    
    def show_telegram_groups(self):
        """Show Telegram groups."""
        try:
            speak_klango(_("Loading groups"))
            # TODO: Implement group loading from telegram_client
            self.close_menu()
        except Exception as e:
            print(f"Error loading groups: {e}")
            speak_klango(_("Error loading groups"))
    
    def close_titan_im_submenu(self):
        """Close Titan IM submenu."""
        self.close_menu()
    
    def announce_time(self):
        """Announce current time."""
        try:
            time_str = get_current_time()
            speak_klango(f"{_('Current time')}: {time_str}")
        except Exception as e:
            print(f"Error getting time: {e}")
            speak_klango(_("Error getting time"))
    
    def announce_battery(self):
        """Announce battery status."""
        try:
            battery_str = get_battery_status()
            speak_klango(f"{_('Battery')}: {battery_str}")
        except Exception as e:
            print(f"Error getting battery status: {e}")
            speak_klango(_("Error getting battery status"))
    
    def announce_volume(self):
        """Announce volume level."""
        try:
            volume_str = get_volume_level()
            speak_klango(f"{_('Volume')}: {volume_str}")
        except Exception as e:
            print(f"Error getting volume level: {e}")
            speak_klango(_("Error getting volume level"))
    
    def open_settings(self):
        """Open settings."""
        try:
            # Open without announcement
            from settingsgui import SettingsFrame
            settings_frame = SettingsFrame(self, title=_("Settings"))
            settings_frame.Show()
            self.close_menu()
        except Exception as e:
            print(f"Error opening settings: {e}")
            speak_klango(_("Error opening settings"))
    
    def open_component_manager(self):
        """Open component manager."""
        try:
            # Open without announcement
            from componentmanagergui import ComponentManagerDialog
            if ComponentManagerDialog and self.component_manager:
                manager_dialog = ComponentManagerDialog(self, title=_("Component Manager"), component_manager=self.component_manager)
                manager_dialog.ShowModal()
                manager_dialog.Destroy()
            elif not ComponentManagerDialog:
                speak_klango(_("Cannot load Component Manager (componentmanagergui.py not found)"))
            elif not self.component_manager:
                speak_klango(_("Component Manager has not been initialized."))
            self.close_menu()
        except Exception as e:
            print(f"Error opening component manager: {e}")
            speak_klango(_("Error opening component manager"))
    
    def show_help(self):
        """Show help."""
        try:
            # Open without announcement
            show_help()
            self.close_menu()
        except Exception as e:
            print(f"Error showing help: {e}")
            speak_klango(_("Error showing help"))
    
    def activate_component(self, component):
        """Activate a component."""
        try:
            component_name = component.get('name', _('Unknown Component'))
            speak_klango(f"{_('Activating component')}: {component_name}")
            
            # Use component manager to activate the component
            if hasattr(self.component_manager, 'activate_component'):
                self.component_manager.activate_component(component)
            else:
                # Fallback: try to execute component directly
                if 'path' in component:
                    import subprocess
                    subprocess.Popen([component['path']], shell=True)
            
            self.close_menu()
        except Exception as e:
            print(f"Error activating component: {e}")
            speak_klango(_("Error activating component"))
    
    def execute_component_function(self, func):
        """Execute a component function (same as IUI implementation)."""
        try:
            if callable(func):
                # Component functions in IUI expect a parent frame parameter
                # For Klango mode in wx mode, we pass self as the parent frame
                func(self)
                self.close_menu()
            else:
                speak_klango(_("Invalid component function"))
        except Exception as e:
            print(f"Error executing component function: {e}")
            speak_klango(_("Error executing component function"))
    
    def gui_open_time_settings(self):
        """Open time settings using same method as GUI."""
        try:
            import subprocess
            import platform
            if platform.system() == "Windows":
                subprocess.run(["timedate.cpl"], check=True)
                speak_klango(_("Time settings opened"))
            self.close_menu()
        except Exception as e:
            print(f"Could not open time settings: {e}")
            speak_klango(_("Could not open time settings"))
    
    def gui_open_power_settings(self):
        """Open power settings using same method as GUI."""
        try:
            import subprocess
            import platform
            if platform.system() == "Windows":
                subprocess.run(["powercfg.cpl"], check=True)
                speak_klango(_("Power settings opened"))
            self.close_menu()
        except Exception as e:
            print(f"Could not open power settings: {e}")
            speak_klango(_("Could not open power settings"))
    
    def gui_open_volume_mixer(self):
        """Open volume mixer using same method as GUI."""
        try:
            import subprocess
            import platform
            if platform.system() == "Windows":
                subprocess.run(["sndvol.exe"], check=True)
                speak_klango(_("Volume mixer opened"))
            self.close_menu()
        except Exception as e:
            print(f"Could not open volume mixer: {e}")
            speak_klango(_("Could not open volume mixer"))
    
    def gui_open_network_settings(self):
        """Open network settings using same method as GUI."""
        try:
            import subprocess
            import platform
            if platform.system() == "Windows":
                subprocess.run(["ncpa.cpl"], check=True)
                speak_klango(_("Network settings opened"))
            self.close_menu()
        except Exception as e:
            print(f"Could not open network settings: {e}")
            speak_klango(_("Could not open network settings"))
    
    def _load_stereo_settings(self):
        """Load stereo settings from configuration."""
        try:
            # Load stereo sound setting (from sound section)
            self._stereo_sound_enabled = get_setting('stereo_sound', 'False', section='sound').lower() in ['true', '1']
            
            # Load stereo speech setting (from invisible_interface section) 
            self._stereo_speech_enabled = get_setting('stereo_speech', 'False', section='invisible_interface').lower() in ['true', '1']
        except:
            self._stereo_sound_enabled = False
            self._stereo_speech_enabled = False
    
    def is_stereo_sound_enabled(self):
        """Check if stereo sound is enabled in settings."""
        if self._stereo_sound_enabled is None:
            self._load_stereo_settings()
        return self._stereo_sound_enabled
    
    def is_stereo_speech_enabled(self):
        """Check if stereo speech is enabled in settings."""
        if self._stereo_speech_enabled is None:
            self._load_stereo_settings()
        return self._stereo_speech_enabled
    
    def exit_program(self):
        """Exit the program using exactly same method as GUI."""
        try:
            from shutdown_question import show_shutdown_dialog
            confirm_exit = self.settings.get('general', {}).get('confirm_exit', 'False').lower() in ['true', '1']
            
            if confirm_exit:
                result = show_shutdown_dialog()
                if result == wx.ID_OK:
                    self.shutdown_app()
                else:
                    print("INFO: Shutdown canceled by user.")
                    speak_klango(_("Exit cancelled"), position=0.0, pitch_offset=0, interrupt=True)
            else:
                self.shutdown_app()
        except Exception as e:
            print(f"Error in exit_program: {e}")
            self.shutdown_app()
    
    def shutdown_app(self):
        """Handles the complete shutdown of the application using same method as GUI."""
        print("INFO: Shutting down application...")
        
        # Hide window immediately for user feedback
        self.Hide()
        
        # Safely disconnect from Telegram if connected
        def safe_shutdown():
            try:
                # Stop system hooks before shutdown
                try:
                    from tce_system import stop_system_hooks
                    stop_system_hooks()
                    print("INFO: System hooks stopped")
                except Exception as e:
                    print(f"Warning: Error stopping system hooks: {e}")
                
                print("INFO: Application terminating now.")
                os._exit(0)
                
            except Exception as e:
                print(f"Critical error during shutdown: {e}")
                os._exit(1)
        
        # Start shutdown in a separate thread
        import threading
        shutdown_thread = threading.Thread(target=safe_shutdown, daemon=True)
        shutdown_thread.start()
    
    def on_close(self, event):
        """Handle close event using same method as GUI."""
        try:
            from shutdown_question import show_shutdown_dialog
            confirm_exit = self.settings.get('general', {}).get('confirm_exit', 'False').lower() in ['true', '1']
            
            if confirm_exit:
                result = show_shutdown_dialog()
                if result == wx.ID_OK:
                    self.shutdown_app()
                else:
                    print("INFO: Shutdown canceled by user.")
                    event.Veto()  # Cancel the close event
            else:
                self.shutdown_app()
        except Exception as e:
            print(f"Error in on_close: {e}")
            self.shutdown_app()


def start_klango_mode(version):
    """Start Klango Mode interface."""
    klango = KlangoMode(version)
    klango.run()


def start_klango_wx_mode(parent, version, settings, component_manager, gui_frame=None):
    """Start Klango Mode wxPython interface."""
    if not WX_AVAILABLE:
        raise ImportError("wxPython not available")
    
    frame = KlangoFrame(parent, _("Titan App Suite"), version, settings, component_manager, gui_frame)
    frame.Show()
    return frame