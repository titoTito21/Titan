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

VERSION = "0.2"
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

def main():
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
            if len(sys.argv) > 1:
                shortname = sys.argv[1]
                app_info = find_application_by_shortname(shortname)
                if app_info:
                    file_path = sys.argv[2] if len(sys.argv) > 2 else None
                    open_application(app_info, file_path)
                    return True # Zwróć informację, że aplikacja została uruchomiona w trybie specjalnym
        except Exception as e:
            print(f"Error processing command line arguments: {e}")
                
        return False
        
    except Exception as e:
        print(f"Critical error in main(): {e}")
        return False

if __name__ == "__main__":
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
    if main():
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

    # Check startup mode setting safely
    try:
        startup_mode = settings.get('general', {}).get('startup_mode', 'normal')
        start_minimized = startup_mode == 'minimized'
    except Exception:
        start_minimized = False
    
    try:
        frame = TitanApp(None, title=_("Titan App Suite"), version=VERSION, settings=settings, component_manager=component_manager, start_minimized=start_minimized)
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
    
    # Initialize system monitor in a separate thread after all other components are loaded
    def init_system_monitor_delayed():
        import time
        time.sleep(2)  # Wait 2 seconds for full app initialization
        try:
            initialize_system_monitor()
            print("System monitor initialized successfully")
        except Exception as e:
            print(f"Warning: System monitor initialization failed: {e}")
    
    monitor_thread = threading.Thread(target=init_system_monitor_delayed, daemon=True)
    monitor_thread.start()
    
    if start_minimized:
        # Start in minimized/invisible interface mode without showing GUI
        frame.minimize_to_tray()
    else:
        # Show normally
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
