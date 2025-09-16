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
            
        def write(self, text):
            if any(pattern in text.lower() for pattern in [
                "failed to load any com objects",
                "freedomsci.jawsapi",
                "jfwapi",
                "gwspeak.speak",
                "com objects. tried",
                "exception ignored in"
            ]):
                return
            self.original_stderr.write(text)
            
        def flush(self):
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
        import win32gui
        import win32process
        import win32api
        import win32con
        import comtypes
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from ctypes import POINTER, cast
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
    from com_fix import suppress_com_errors, init_com_safe
    suppress_com_errors()
    init_com_safe()
except ImportError:
    pass
except Exception as e:
    pass
from gui import TitanApp
from sound import play_startup_sound, initialize_sound, set_theme, play_sound
from settings import get_setting, set_setting, load_settings, save_settings, SETTINGS_FILE_PATH
from translation import set_language
from notificationcenter import create_notifications_file, NOTIFICATIONS_FILE_PATH, start_monitoring
from shutdown_question import show_shutdown_dialog
from app_manager import find_application_by_shortname, open_application
from game_manager import *
from component_manager import ComponentManager
from menu import MenuBar
from lockscreen_monitor_improved import start_lock_monitoring
from tce_system import start_system_hooks
from system_monitor import initialize_system_monitor
from updater import check_for_updates_on_startup

# Initialize translation system
_ = set_language(get_setting('language', 'pl'))

VERSION = "0.2.1"
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
                # Odtwarzanie dźwięku w osobnym wątku
                sound_thread = threading.Thread(target=play_startup_sound, daemon=True)
                sound_thread.start()
                time.sleep(1)  # Poczekaj 1 sekundę
                
                # Mówienie tekstu w osobnym wątku
                speech_thread = threading.Thread(
                    target=lambda: speaker.speak(_("Welcome to Titan: Version {}").format(VERSION)), 
                    daemon=True
                )
                speech_thread.start()
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
                # Create wx.App for Klango mode
                klango_app = wx.App(False)
                
                # Initialize all TCE systems like in GUI mode
                try:
                    from settingsgui import SettingsFrame
                    settings_frame = SettingsFrame(None, title=_("Settings"))
                    print("Settings frame initialized for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to create settings frame for Klango: {e}")
                    settings_frame = None
                
                # Initialize component manager with settings frame
                try:
                    component_manager = ComponentManager(settings_frame)
                    component_manager.initialize_components(klango_app)
                    print("Component manager fully initialized for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to initialize component manager for Klango: {e}")
                    component_manager = None
                
                # Start all system services like in GUI mode
                try:
                    start_lock_monitoring()
                    print("Lock screen monitoring started for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to start lock monitoring for Klango: {e}")
                
                try:
                    start_system_hooks()
                    print("System hooks started for Klango mode")
                except Exception as e:
                    print(f"Warning: Failed to start system hooks for Klango: {e}")
                
                # Initialize system monitor in background thread like GUI
                def init_system_services_delayed():
                    import time
                    time.sleep(2)  # Wait 2 seconds for full app initialization
                    try:
                        initialize_system_monitor()
                        print("System monitor initialized for Klango mode")
                    except Exception as e:
                        print(f"Warning: System monitor initialization failed for Klango: {e}")

                    # Initialize TCE sounds if enabled in environment settings
                    try:
                        environment_settings = settings.get('environment', {})
                        enable_tce_sounds = str(environment_settings.get('enable_tce_sounds', 'False')).lower() in ['true', '1']

                        if enable_tce_sounds:
                            import tsounds
                            tce_sound_feedback = tsounds.initialize()
                            print("TCE sounds initialized successfully for Klango mode")
                    except Exception as e:
                        print(f"Warning: TCE sounds initialization failed for Klango: {e}")

                services_thread = threading.Thread(target=init_system_services_delayed, daemon=True)
                services_thread.start()
                
                # Start Klango frame with full initialization
                from klangomode import start_klango_wx_mode
                klango_frame = start_klango_wx_mode(settings_frame, VERSION, settings, component_manager)
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

    # Check for updates before starting the main application
    # Create minimal wx.App for update dialog only
    update_app = wx.App(False)
    
    try:
        # Check for updates - this will show dialog if update available
        update_result = check_for_updates_on_startup()
        
        # If update was applied, the application will exit automatically
        # If no update or user cancelled, continue normally
        
    except Exception as e:
        print(f"Error checking for updates: {e}")
    finally:
            # Clean up the temporary app safely
        try:
            update_app.Destroy()
            del update_app
        except Exception as e:
            print(f"Error destroying update app: {e}")

    # Inicjalizacja aplikacji wxPython w głównym zakresie
    try:
        app = wx.App(False)
    except Exception as e:
        print(f"Failed to create main wx.App: {e}")
        sys.exit(1)
    settings = load_settings()
    
    # Language warning dialog removed per user request

    try:
        from settingsgui import SettingsFrame
        settings_frame = SettingsFrame(None, title=_("Settings"))
    except Exception as e:
        print(f"Failed to create settings frame: {e}")
        sys.exit(1)

    try:
        component_manager = ComponentManager(settings_frame)
        component_manager.initialize_components(app)
    except Exception as e:
        print(f"Failed to initialize component manager: {e}")
        # Continue without components rather than crash

    
    try:
        # Check if we should start minimized
        should_start_minimized = settings.get('general', {}).get('startup_mode', 'normal') == 'minimized'
        frame = TitanApp(None, title=_("Titan App Suite"), version=VERSION, settings=settings, component_manager=component_manager, start_minimized=should_start_minimized)
    except Exception as e:
        print(f"Failed to create main application frame: {e}")
        sys.exit(1)
    
    # Bind the close event to the appropriate handler
    if settings.get('general', {}).get('confirm_exit', 'False').lower() in ['true', '1']:
        frame.Bind(wx.EVT_CLOSE, frame.on_close)
    else:
        frame.Bind(wx.EVT_CLOSE, frame.on_close_unconfirmed)
    
    frame.component_manager = component_manager
    menubar = MenuBar(frame)
    frame.SetMenuBar(menubar)

    # Start lockscreen monitoring service
    start_lock_monitoring()
    
    # Start system hooks
    start_system_hooks()
    
    # Initialize system services in a separate thread after all other components are loaded
    def init_system_services_delayed():
        import time
        time.sleep(2)  # Wait 2 seconds for full app initialization
        try:
            initialize_system_monitor()
            print("System monitor initialized successfully")
        except Exception as e:
            print(f"Warning: System monitor initialization failed: {e}")

        # Initialize TCE sounds if enabled in environment settings
        try:
            environment_settings = settings.get('environment', {})
            enable_tce_sounds = str(environment_settings.get('enable_tce_sounds', 'False')).lower() in ['true', '1']

            if enable_tce_sounds:
                import tsounds
                tce_sound_feedback = tsounds.initialize()
                print("TCE sounds initialized successfully")
                # Store reference to prevent garbage collection
                if hasattr(frame, 'tce_sound_feedback'):
                    frame.tce_sound_feedback = tce_sound_feedback
        except Exception as e:
            print(f"Warning: TCE sounds initialization failed: {e}")

    services_thread = threading.Thread(target=init_system_services_delayed, daemon=True)
    services_thread.start()
    
    # Show the GUI normally (unless we should start minimized)
    if should_start_minimized:
        # Start minimized to tray with invisible UI active
        wx.CallAfter(frame.minimize_to_tray)
    else:
        frame.Show()
    
    try:
        app.MainLoop()
    except KeyboardInterrupt:
        print("Application interrupted by user")
    except SystemExit:
        print("Application exiting normally")
    except Exception as e:
        print(f"Fatal error in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Ensure proper cleanup
        print("Performing final cleanup...")
        
        # Cleanup frame
        if 'frame' in locals():
            try:
                if hasattr(frame, 'task_bar_icon') and frame.task_bar_icon:
                    frame.task_bar_icon.RemoveIcon()
                    frame.task_bar_icon.Destroy()
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
        
        # Additional cleanup for COM objects
        try:
            from com_fix import cleanup_com_on_exit
            cleanup_com_on_exit()
        except:
            pass
        
        print("Cleanup completed")
