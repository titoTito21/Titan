# Python 3.14+ fix: Create asyncio event loop before any imports that use it
import asyncio
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import wx
import threading
import time
import os
import sys
import signal
import gc

# Suppress COM errors BEFORE any imports
try:
    import warnings
    warnings.filterwarnings("ignore", message=".*COM.*")
    warnings.filterwarnings("ignore", category=UserWarning, module="comtypes")
    
    class COMErrorSuppressor:
        def __init__(self):
            self.original_stderr = sys.stderr
            self.buffer = ""
            self.suppress_until_newline = 0

        def write(self, text):
            # Suppress single colons/punctuation (COM error fragments)
            if text.strip() in [':', '', ' ']:
                return

            # Simple aggressive suppression: if buffer + text contains error keywords, suppress everything
            self.buffer += text

            # Check for error patterns in buffer
            buffer_lower = self.buffer.lower()

            # Suppress if we see these keywords
            if any(keyword in buffer_lower for keyword in [
                "systemerror", "valueerror", "comtypes", "com method",
                "__del__", "unknwn", "iunknown", "traceback", "gwspeak", "jfwapi",
                "win32 exception", "releasing iunknown", "exception occurred"
            ]):
                self.suppress_until_newline = 100  # Suppress next 100 writes (increased)
                self.buffer = ""
                return

            # If suppressing, count down
            if self.suppress_until_newline > 0:
                self.suppress_until_newline -= 1
                self.buffer = ""
                return

            # If buffer gets too large without errors, flush it
            if len(self.buffer) > 200 or '\n' in self.buffer:
                self.original_stderr.write(self.buffer)
                self.buffer = ""

        def flush(self):
            # Only flush non-error content
            if self.suppress_until_newline == 0 and self.buffer:
                self.original_stderr.write(self.buffer)
                self.buffer = ""
            self.original_stderr.flush()
    
    sys.stderr = COMErrorSuppressor()
except Exception as e:
    pass

import accessible_output3.outputs.auto

# Import libraries used by components for compilation compatibility
try:
    import platform
    import subprocess
    import configparser
    import json
    import keyboard
    import speech_recognition as sr
    import pygame
    import random
    import psutil
    if platform.system() == 'Windows':
        import win32com.client
        import pythoncom  # For TitanScreenReader component
        import win32gui
        import win32process
        import win32api
        import win32con
        import comtypes
        from pycaw.pycaw import AudioUtilities
        from ctypes import wintypes  # For TitanScreenReader component
    elif platform.system() == 'Linux':
        import alsaaudio
    # Other potential libraries used by components
    import time
    import random
    import threading
    import os
    import sys
    from bg5reader import bg5reader
    
    # Import libraries used by widgets (applets) for compilation compatibility
    import gettext
    import glob
    if platform.system() == "Windows":
        # Additional Windows-specific imports for taskbar widget
        import win32con
    try:
        import pywinctl as pwc
    except ImportError:
        pass  # pywinctl is optional
    # Other widget dependencies
    import typing
    from typing import List, Dict, Optional
    
except ImportError as e:
    print(f"Warning: Could not import component/widget library: {e}")

# Fix COM errors early
try:
    from src.system.com_fix import suppress_com_errors, init_com_safe
    suppress_com_errors()
    init_com_safe()
except ImportError:
    pass
except Exception as e:
    pass
from src.ui.gui import TitanApp
from src.titan_core.sound import play_startup_sound, initialize_sound, set_theme, play_sound
from src.settings.settings import get_setting, set_setting, load_settings, save_settings, SETTINGS_FILE_PATH
from src.titan_core.translation import set_language
from src.controller.controller_vibrations import initialize_vibration, vibrate_startup
from src.controller.controller_ui import initialize_controller_system, shutdown_controller_system
from src.controller.controller_modes import initialize_controller_modes
from src.ui.notificationcenter import create_notifications_file, NOTIFICATIONS_FILE_PATH, start_monitoring
from src.ui.shutdown_question import show_shutdown_dialog
from src.titan_core.app_manager import find_application_by_shortname, open_application
from src.titan_core.game_manager import *
from src.titan_core.component_manager import ComponentManager
from src.ui.menu import MenuBar
from src.system.lockscreen_monitor_improved import start_lock_monitoring
from src.titan_core.tce_system import start_system_hooks
from src.system.system_monitor import initialize_system_monitor
from src.system.updater import check_for_updates_on_startup

# Initialize translation system
_ = set_language(get_setting('language', 'pl'))

VERSION = "0.3"
speaker = accessible_output3.outputs.auto.Auto()

# Global flag for graceful shutdown
_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle system signals for graceful shutdown"""
    global _shutdown_requested
    print(f"Signal {signum} received, initiating graceful shutdown...")
    _shutdown_requested = True
    
    # Force garbage collection
    gc.collect()
    
    try:
        # Try to close the main application if it exists
        if wx.GetApp():
            wx.CallAfter(wx.GetApp().ExitMainLoop)
    except:
        pass

def main(command_line_args=None):
    """Main initialization function with comprehensive error handling."""
    try:
        settings = load_settings()
        
        # Set the LANG environment variable for the entire application and subprocesses
        try:
            lang = get_setting('language', 'pl')
            os.environ['LANG'] = lang
            os.environ['LANGUAGE'] = lang
            
            # Initialize translation system with the correct language
            global _
            _ = set_language(lang)
        except Exception as e:
            print(f"Error setting up language: {e}")
            lang = 'pl'  # Fallback

        # Initialize sound system with error handling
        try:
            initialize_sound()
            theme = settings.get('sound', {}).get('theme', 'default')
            set_theme(theme)
        except Exception as e:
            print(f"Error initializing sound system: {e}")
        
        # Handle quick start setting safely
        try:
            quick_start = settings.get('general', {}).get('quick_start', 'False').lower() in ['true', '1']
        except Exception:
            quick_start = False
        
        if not quick_start:
            try:
                # Initialize controller vibration system
                initialize_vibration()

                # Controller modes system will be initialized when GUI starts
                try:
                    initialize_controller_modes()
                    print("Controller modes system initialized")
                except Exception as e:
                    print(f"Warning: Controller modes system failed to initialize: {e}")

                # Odtwarzanie dźwięku w osobnym wątku
                sound_thread = threading.Thread(target=play_startup_sound, daemon=True)
                sound_thread.start()

                # Strong vibration for startup sound (3 seconds)
                vibration_thread = threading.Thread(target=vibrate_startup, daemon=True)
                vibration_thread.start()

                # Mówienie tekstu w osobnym wątku po odczekaniu 1 sekundy (nie blokuje głównego wątku)
                def delayed_speech():
                    time.sleep(1)  # Odczekaj w tle
                    speaker.speak(_("Welcome to Titan: Version {}").format(VERSION))

                speech_thread = threading.Thread(target=delayed_speech, daemon=True)
                speech_thread.start()

                # Wait 2 seconds before loading the program (allows sounds/speech to play in background)
                time.sleep(2)
            except Exception as e:
                print(f"Error playing startup sounds/speech: {e}")
        
        # Dodajemy główny katalog do sys.path
        try:
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        except Exception as e:
            print(f"Error adding to sys.path: {e}")

        # Sprawdzenie argumentów wiersza poleceń
        try:
            if command_line_args and command_line_args.application:
                shortname = command_line_args.application
                app_info = find_application_by_shortname(shortname)
                if app_info:
                    file_path = command_line_args.file_path
                    open_application(app_info, file_path)
                    return True # Zwróć informację, że aplikacja została uruchomiona w trybie specjalnym
        except Exception as e:
            print(f"Error processing command line arguments: {e}")
        
        # Check startup mode setting safely - allow command line override
        try:
            if command_line_args and command_line_args.startup_mode:
                startup_mode = command_line_args.startup_mode
                print(f"Command line startup mode: {startup_mode}")
            else:
                startup_mode = settings.get('general', {}).get('startup_mode', 'normal')
                print(f"Settings startup mode: {startup_mode}")
            print(f"Final startup mode: {startup_mode}")
        except Exception:
            startup_mode = 'normal'
    
        # Handle different startup modes
        if startup_mode == 'klango':
            try:
                print("Starting Klango mode with full TCE initialization...")
                # Check if wx.App already exists (it shouldn't in Klango mode called from main())
                existing_app = wx.GetApp()
                if existing_app:
                    print("Warning: wx.App already exists, using existing instance for Klango")
                    klango_app = existing_app
                else:
                    # Create wx.App for Klango mode
                    klango_app = wx.App(False)

                # Create component manager first (without settings_frame initially)
                try:
                    component_manager = ComponentManager(settings_frame=None, gui_app=None)
                    print("Component manager created for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to create component manager for Klango: {e}")
                    import traceback
                    traceback.print_exc()
                    component_manager = None

                # Initialize all TCE systems like in GUI mode
                try:
                    from src.ui.settingsgui import SettingsFrame
                    settings_frame = SettingsFrame(None, title=_("Settings"), component_manager=component_manager)
                    print("Settings frame initialized for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to create settings frame for Klango: {e}")
                    import traceback
                    traceback.print_exc()
                    settings_frame = None

                # Set settings_frame reference in component manager and register component settings
                if component_manager:
                    component_manager.settings_frame = settings_frame
                    component_manager.register_component_settings()
                    settings_frame.rebuild_category_list()
                    settings_frame.load_component_settings()  # Load component settings after registration
                    print("Component settings categories registered for Klango mode")

                # Start all system services like in GUI mode
                try:
                    start_lock_monitoring()
                    print("Lock screen monitoring started for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to start lock monitoring for Klango: {e}")
                    import traceback
                    traceback.print_exc()

                try:
                    start_system_hooks()
                    print("System hooks started for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to start system hooks for Klango: {e}")
                    import traceback
                    traceback.print_exc()

                # Start Klango frame FIRST, then initialize components
                try:
                    from src.system.klangomode import start_klango_wx_mode
                    klango_frame = start_klango_wx_mode(settings_frame, VERSION, settings, component_manager)
                    print("Klango frame created successfully")
                except Exception as e:
                    print(f"Failed to create Klango frame: {e}")
                    import traceback
                    traceback.print_exc()
                    return False

                # Set gui_app reference for Klango mode
                if component_manager:
                    component_manager.gui_app = klango_frame

                # NOW initialize components after Klango frame is created
                if component_manager:
                    try:
                        component_manager.initialize_components(klango_app)
                        print("Components initialized successfully for Klango mode")
                        # Apply Klango hooks from components
                        component_manager.apply_klango_hooks(klango_frame)
                        print("Klango hooks applied successfully")
                    except Exception as e:
                        print(f"Warning: Failed to initialize components for Klango: {e}")
                        import traceback
                        traceback.print_exc()

                # Initialize system monitor in background thread like GUI
                def init_system_services_delayed():
                    import time
                    time.sleep(2)  # Wait 2 seconds for full app initialization
                    try:
                        initialize_system_monitor()
                        print("System monitor initialized for Klango mode")
                    except Exception as e:
                        print(f"Warning: System monitor initialization failed for Klango: {e}")
                        import traceback
                        traceback.print_exc()

                    # Initialize TCE sounds if enabled in environment settings
                    try:
                        environment_settings = settings.get('environment', {})
                        enable_tce_sounds = str(environment_settings.get('enable_tce_sounds', 'False')).lower() in ['true', '1']

                        if enable_tce_sounds:
                            from src.titan_core import tsounds
                            tce_sound_feedback = tsounds.initialize()
                            print("TCE sounds initialized successfully for Klango mode")
                    except Exception as e:
                        print(f"Warning: TCE sounds initialization failed for Klango: {e}")
                        import traceback
                        traceback.print_exc()

                services_thread = threading.Thread(target=init_system_services_delayed, daemon=True)
                services_thread.start()

                # Start main loop
                klango_app.MainLoop()
                return True
            except Exception as e:
                print(f"Failed to start Klango mode: {e}")
                import traceback
                traceback.print_exc()
                # Fallback to normal mode
                startup_mode = 'normal'
        
        elif startup_mode == 'minimized':
            # Start GUI in minimized mode (will minimize to tray automatically)
            print("Starting in minimized mode...")
            startup_mode = 'normal'  # Continue with normal GUI startup but will be minimized
                
        # If we get here, we're in normal GUI mode
        return False
        
    except Exception as e:
        print(f"Critical error in main(): {e}")
        return False

if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='Titan App Suite')
    parser.add_argument('application', nargs='?', default=None, 
                       help='Application shortname to launch directly')
    parser.add_argument('file_path', nargs='?', default=None,
                       help='File path to open with the application')
    parser.add_argument('--startup-mode', choices=['normal', 'minimized', 'klango'], 
                       default=None, help='Override startup mode setting')
    args = parser.parse_args()
    
    # Install signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Set default settings if the file doesn't exist
    if not os.path.exists(SETTINGS_FILE_PATH):
        set_setting('language', 'pl')
        set_setting('theme', 'default', section='sound')

    if not os.path.exists(NOTIFICATIONS_FILE_PATH):
        create_notifications_file()
    
    # Uruchom logikę przed-GUI. Jeśli zwróci True, zakończ program.
    if main(args):
        sys.exit()

    # Inicjalizacja aplikacji wxPython w głównym zakresie (TYLKO JEDNA instancja wx.App)
    try:
        # Check if wx.App already exists (shouldn't happen, but be safe)
        existing_app = wx.GetApp()
        if existing_app:
            print("Warning: wx.App already exists, using existing instance")
            app = existing_app
        else:
            app = wx.App(False)
            print("wx.App created successfully")
    except Exception as e:
        print(f"Failed to create main wx.App: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Reload settings to ensure we have latest configuration
    try:
        settings = load_settings()
    except Exception as e:
        print(f"Error loading settings: {e}")
        settings = {}

    # Check for updates using the main app instance
    try:
        # Check for updates - this will show dialog if update available
        update_result = check_for_updates_on_startup()

        # If update was applied, the application will exit automatically
        # If no update or user cancelled, continue normally

    except Exception as e:
        print(f"Error checking for updates: {e}")
        import traceback
        traceback.print_exc()

    # Check if we should start minimized
    should_start_minimized = settings.get('general', {}).get('startup_mode', 'normal') == 'minimized'

    # Language warning dialog removed per user request

    # Create component manager first (without settings_frame initially)
    try:
        component_manager = ComponentManager(settings_frame=None, gui_app=None)
        print("Component manager created (not yet initialized)")
    except Exception as e:
        print(f"Failed to create component manager: {e}")
        component_manager = None
        # Continue without components rather than crash

    # Now create settings frame with component_manager reference
    try:
        from src.ui.settingsgui import SettingsFrame
        settings_frame = SettingsFrame(None, title=_("Settings"), component_manager=component_manager)
    except Exception as e:
        print(f"Failed to create settings frame: {e}")
        sys.exit(1)

    # Set settings_frame reference in component manager and register component settings
    if component_manager:
        component_manager.settings_frame = settings_frame
        print("[MAIN] Registering component settings...")
        component_manager.register_component_settings()
        print("[MAIN] Calling rebuild_category_list...")
        settings_frame.rebuild_category_list()
        print("[MAIN] Loading component settings...")
        settings_frame.load_component_settings()  # Load component settings after registration
        print("[MAIN] Component settings categories registered")


    try:
        # Use should_start_minimized variable defined earlier
        frame = TitanApp(None, title=_("Titan App Suite"), version=VERSION, settings=settings, component_manager=component_manager, start_minimized=should_start_minimized)
        print("TitanApp frame created successfully")
    except Exception as e:
        print(f"Failed to create main application frame: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Set gui_app reference in component manager
    if component_manager:
        component_manager.gui_app = frame

    # NOW initialize components after TitanApp is fully created
    if component_manager:
        try:
            component_manager.initialize_components(app)
            print("Components initialized successfully")
            # Apply GUI hooks from components
            component_manager.apply_gui_hooks(frame)
            print("GUI hooks applied successfully")
        except Exception as e:
            print(f"Warning: Failed to initialize components: {e}")
            import traceback
            traceback.print_exc()
            # Continue without components rather than crash

    # Ensure frame has component_manager and settings_frame references before binding events
    frame.component_manager = component_manager
    frame.settings_frame = settings_frame

    # Bind the close event to the appropriate handler
    try:
        if settings.get('general', {}).get('confirm_exit', 'False').lower() in ['true', '1']:
            frame.Bind(wx.EVT_CLOSE, frame.on_close)
        else:
            frame.Bind(wx.EVT_CLOSE, frame.on_close_unconfirmed)
    except Exception as e:
        print(f"Warning: Failed to bind close event: {e}")

    # Create and set menu bar
    try:
        menubar = MenuBar(frame)
        frame.SetMenuBar(menubar)
        print("Menu bar created successfully")
    except Exception as e:
        print(f"Warning: Failed to create menu bar: {e}")

    # Initialize Titan-Net client with auto-connect - DISABLED
    # try:
    #     from src.network.titan_net import TitanNetClient
    #     from src.network.titan_net_gui import show_login_dialog

    #     # Get Titan-Net server configuration from settings
    #     titan_net_settings = settings.get('titan_net', {})
    #     server_host = titan_net_settings.get('server_host', 'localhost')
    #     server_port = int(titan_net_settings.get('server_port', 8001))

    #     print(f"Titan-Net configuration: host={server_host}, port={server_port}")

    #     # Create Titan-Net client
    #     titan_client = TitanNetClient(server_host=server_host, server_port=server_port)

    #     # Store client reference in frame
    #     frame.titan_client = titan_client

    #     print(f"Titan-Net client initialized with URL: ws://{server_host}:{server_port}")

    #     # Auto-connect: Check if server is available and show login dialog
    #     # IMPORTANT: Add delay to ensure frame is fully initialized first
    #     def auto_connect_titannet():
    #         try:
    #             # Wait for frame to be fully initialized
    #             import time
    #             time.sleep(1)

    #             # Verify frame still exists and is ready
    #             if not frame or not hasattr(frame, 'active_services'):
    #                 print("Frame not ready for Titan-Net auto-connect, skipping")
    #                 return

    #             # Check if auto-connect is enabled in settings
    #             auto_connect = titan_net_settings.get('auto_connect', True)

    #             if auto_connect:
    #                 print("Checking Titan-Net server availability...")

    #                 # Check server availability
    #                 if titan_client.check_server():
    #                     print("Titan-Net server available, showing login dialog...")

    #                     # Show login dialog on main thread with safety check
    #                     wx.CallAfter(lambda: _show_titannet_login_safe(frame, titan_client))
    #                 else:
    #                     print("Titan-Net server not available, skipping auto-connect")
    #             else:
    #                 print("Titan-Net auto-connect disabled in settings")

    #         except Exception as e:
    #             print(f"Error during Titan-Net auto-connect: {e}")
    #             import traceback
    #             traceback.print_exc()

    #     def _show_titannet_login_safe(frame, titan_client):
    #         """Show Titan-Net login dialog and handle result with safety checks"""
    #         try:
    #             # Safety check: ensure frame is still valid
    #             if not frame or not hasattr(frame, 'active_services'):
    #                 print("Frame not ready for Titan-Net login, skipping")
    #                 return

    #             logged_in, offline_mode = show_login_dialog(frame, titan_client)

    #             if logged_in:
    #                 print(f"Titan-Net login successful: {titan_client.username}")

    #                 # Store in active services with safety check
    #                 if hasattr(frame, 'active_services'):
    #                     frame.active_services["titannet"] = {
    #                         "client": titan_client,
    #                         "type": "titannet",
    #                         "name": "Titan-Net",
    #                         "online_users": [],
    #                         "unread_messages": {},
    #                         "user_data": {
    #                             "username": titan_client.username,
    #                             "titan_number": titan_client.titan_number
    #                         }
    #                     }

    #                     # Setup callbacks for real-time updates
    #                     titan_client.on_message_received = lambda msg: frame._on_titannet_message(msg)
    #                     titan_client.on_user_online = lambda username: frame._on_titannet_user_online(username)
    #                     titan_client.on_user_offline = lambda username: frame._on_titannet_user_offline(username)

    #                     print("Titan-Net callbacks registered")
    #             elif offline_mode:
    #                 print("User chose Titan-Net offline mode")
    #             else:
    #                 print("Titan-Net login cancelled")

    #         except Exception as e:
    #             print(f"Error showing Titan-Net login dialog: {e}")
    #             import traceback
    #             traceback.print_exc()

    #     # Start auto-connect in background thread
    #     connect_thread = threading.Thread(target=auto_connect_titannet, daemon=True)
    #     connect_thread.start()

    # except Exception as e:
    #     print(f"Warning: Failed to initialize Titan-Net client (optional): {e}")
    #     frame.titan_client = None

    # Set titan_client to None since Titan-Net is disabled
    frame.titan_client = None

    # Start lockscreen monitoring service with error handling
    try:
        start_lock_monitoring()
        print("Lock screen monitoring started")
    except Exception as e:
        print(f"Warning: Failed to start lock monitoring: {e}")

    # Start system hooks with error handling
    try:
        start_system_hooks()
        print("System hooks started")
    except Exception as e:
        print(f"Warning: Failed to start system hooks: {e}")

    # Initialize system services in a separate thread after all other components are loaded
    def init_system_services_delayed():
        import time
        time.sleep(2)  # Wait 2 seconds for full app initialization
        try:
            initialize_system_monitor()
            print("System monitor initialized successfully")
        except Exception as e:
            print(f"Warning: System monitor initialization failed: {e}")
            import traceback
            traceback.print_exc()

        # Initialize TCE sounds if enabled in environment settings
        try:
            environment_settings = settings.get('environment', {})
            enable_tce_sounds = str(environment_settings.get('enable_tce_sounds', 'False')).lower() in ['true', '1']

            if enable_tce_sounds:
                from src.titan_core import tsounds
                tce_sound_feedback = tsounds.initialize()
                print("TCE sounds initialized successfully")
                # Store reference to prevent garbage collection
                if hasattr(frame, 'tce_sound_feedback'):
                    frame.tce_sound_feedback = tce_sound_feedback
        except Exception as e:
            print(f"Warning: TCE sounds initialization failed: {e}")
            import traceback
            traceback.print_exc()

    services_thread = threading.Thread(target=init_system_services_delayed, daemon=True)
    services_thread.start()

    # AI is now managed by the AI component (data/components/AI)
    # Enable it through component settings if needed

    # Show the GUI normally (unless we should start minimized)
    try:
        if should_start_minimized:
            # Start minimized to tray with invisible UI active
            wx.CallAfter(frame.minimize_to_tray)
            print("Starting minimized to tray")
        else:
            frame.Show()
            print("Main frame shown")
    except Exception as e:
        print(f"Error showing frame: {e}")
        import traceback
        traceback.print_exc()

    # Start main event loop with comprehensive error handling
    print("Starting main event loop...")
    try:
        app.MainLoop()
    except KeyboardInterrupt:
        print("Application interrupted by user (Ctrl+C)")
    except SystemExit:
        print("Application exiting normally")
    except Exception as e:
        print(f"Fatal error in main loop: {e}")
        import traceback
        traceback.print_exc()

        # Try to show error dialog to user before crashing
        try:
            wx.MessageBox(
                f"Critical error occurred:\n\n{str(e)}\n\nPlease check console for details.",
                "Titan Error",
                wx.OK | wx.ICON_ERROR
            )
        except:
            pass  # If even the error dialog fails, just continue to cleanup
    finally:
        # Ensure proper cleanup
        print("Performing final cleanup...")

        # Stop all daemon threads gracefully by signaling them
        # All daemon threads should check their stop events and exit
        print("Signaling all daemon threads to stop...")

        # Unregister AI hotkey
        try:
            import keyboard
            keyboard.remove_hotkey('ctrl+shift+a')
            print("AI hotkey unregistered")
        except Exception as e:
            print(f"Warning: Error unregistering AI hotkey: {e}")

        # Cleanup frame and stop its threads
        if 'frame' in locals():
            try:
                # Stop frame's status update thread if it exists
                if hasattr(frame, 'status_thread_running'):
                    frame.status_thread_running = False
                if hasattr(frame, 'status_thread_stop_event'):
                    frame.status_thread_stop_event.set()

                # Stop invisible UI threads if they exist
                if hasattr(frame, 'invisible_ui') and frame.invisible_ui:
                    try:
                        # Signal invisible UI to cleanup its threads
                        if hasattr(frame.invisible_ui, 'cleanup'):
                            frame.invisible_ui.cleanup()
                    except Exception as e:
                        print(f"Error cleaning up invisible UI: {e}")

                # Remove taskbar icon
                if hasattr(frame, 'task_bar_icon') and frame.task_bar_icon:
                    frame.task_bar_icon.RemoveIcon()
                    frame.task_bar_icon.Destroy()

                # Destroy frame
                frame.Destroy()
            except Exception as e:
                print(f"Error destroying frame: {e}")

        # Cleanup app
        try:
            if app:
                app.Destroy()
        except Exception as e:
            print(f"Error destroying app: {e}")
        
        # Force garbage collection
        import gc
        gc.collect()
        
        # Cleanup controller system
        try:
            shutdown_controller_system()
            print("Controller system shutdown completed")
        except:
            pass

        # AI is now managed by the AI component
        # Shutdown happens automatically through component manager

        # Additional cleanup for COM objects
        try:
            from src.system.com_fix import cleanup_com_on_exit
            cleanup_com_on_exit()
        except:
            pass

        print("Cleanup completed")
