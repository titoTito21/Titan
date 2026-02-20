import os
import sys
import threading
import time
import subprocess
import platform
import wx
from src.settings.settings import get_setting
from src.titan_core.app_manager import find_application_by_shortname, open_application
from src.titan_core.translation import _

from src.platform_utils import IS_WINDOWS, IS_LINUX, IS_MACOS

# Windows-specific imports
if IS_WINDOWS:
    import win32gui
    import win32con
    import win32api
    import keyboard

class SystemHooksManager:
    """Manages system-level hooks and modifications for TCE environment"""
    
    def __init__(self):
        self.windows_e_hook_active = False
        self.hooks_thread = None
        self.monitoring = False
        self.cleanup_event = threading.Event()
        
    def start_system_hooks(self):
        """Start system hooks based on settings"""
        if self.monitoring:
            return
            
        self.monitoring = True
        self.cleanup_event.clear()
        
        # Check if system interface modification is enabled
        system_interface_enabled = get_setting('windows_e_hook', 'False', 'environment').lower() in ['true', '1']
        
        if system_interface_enabled:
            self.start_system_interface_hooks()
    
    def stop_system_hooks(self):
        """Stop all system hooks"""
        if not self.monitoring:
            return
            
        self.monitoring = False
        self.cleanup_event.set()
        
        if self.windows_e_hook_active:
            self.stop_system_interface_hooks()
    
    def start_system_interface_hooks(self):
        """Start system interface hooks - Windows key, Escape key, Windows+E, and Windows+B"""
        if not IS_WINDOWS:
            print("INFO: System interface hooks are only available on Windows")
            return
        if self.windows_e_hook_active:
            return

        try:
            # Hook Windows key (left) to open Classic Start Menu
            keyboard.add_hotkey('left windows', self.on_windows_key_pressed, suppress=True)

            # Hook Windows key (right) to open Classic Start Menu
            keyboard.add_hotkey('right windows', self.on_windows_key_pressed, suppress=True)

            # Hook Windows+E combination
            keyboard.add_hotkey('win+e', self.on_windows_e_pressed, suppress=True)

            # Hook Windows+B combination (System Tray)
            keyboard.add_hotkey('win+b', self.on_windows_b_pressed, suppress=True)

            # Hook Escape key to open Start Menu
            keyboard.add_hotkey('escape', self.on_escape_key_pressed, suppress=True)

            self.windows_e_hook_active = True
            print("INFO: System interface hooks activated - Windows key -> Classic Start Menu, Escape key -> Classic Start Menu, Windows+E -> TFM, Windows+B -> System Tray")
        except Exception as e:
            print(f"ERROR: Failed to start system interface hooks: {e}")
    
    def stop_system_interface_hooks(self):
        """Stop system interface hooks"""
        if not self.windows_e_hook_active:
            return

        try:
            keyboard.remove_hotkey('left windows')
            keyboard.remove_hotkey('right windows')
            keyboard.remove_hotkey('win+e')
            keyboard.remove_hotkey('win+b')
            keyboard.remove_hotkey('escape')
            self.windows_e_hook_active = False
            print("INFO: System interface hooks deactivated")
        except Exception as e:
            print(f"ERROR: Failed to stop system interface hooks: {e}")

    def on_windows_key_pressed(self):
        """Handler for Windows key press - opens Classic Start Menu"""
        try:
            print("INFO: Windows key pressed - opening Classic Start Menu")
            threading.Thread(
                target=self._open_classic_start_menu,
                daemon=True
            ).start()
        except Exception as e:
            print(f"ERROR: Failed to handle Windows key: {e}")

    def on_escape_key_pressed(self):
        """Handler for Escape key press - opens Classic Start Menu"""
        try:
            print("INFO: Escape key pressed - opening Classic Start Menu")
            threading.Thread(
                target=self._open_classic_start_menu,
                daemon=True
            ).start()
        except Exception as e:
            print(f"ERROR: Failed to handle Escape key: {e}")
    
    def _get_main_frame(self):
        """Get the main TitanApp frame"""
        try:
            # Find the main frame from wx app
            app = wx.GetApp()
            if app:
                for window in wx.GetTopLevelWindows():
                    if hasattr(window, 'start_menu'):  # TitanApp has start_menu attribute
                        return window
            return None
        except Exception as e:
            print(f"ERROR: Failed to get main frame: {e}")
            return None

    def _open_classic_start_menu(self):
        """Open Classic Start Menu"""
        try:
            main_frame = self._get_main_frame()
            if main_frame and hasattr(main_frame, 'start_menu') and main_frame.start_menu:
                # Use existing start menu from main frame
                wx.CallAfter(main_frame.start_menu.toggle_menu)
                print("INFO: Classic Start Menu toggled")
            else:
                print("WARNING: Main frame or start menu not found")
        except Exception as e:
            print(f"ERROR: Failed to open Classic Start Menu: {e}")
    
    
    def on_windows_e_pressed(self):
        """Handler for Windows+E keypress - opens TCE File Manager"""
        try:
            print("INFO: Windows+E pressed - opening TCE File Manager")
            
            # Find TFM application
            tfm_app = find_application_by_shortname('tfm')
            if tfm_app:
                threading.Thread(
                    target=self._open_tfm_app, 
                    args=(tfm_app,),
                    daemon=True
                ).start()
            else:
                print("ERROR: TFM application not found")
                # Don't open anything if TFM not available
                
        except Exception as e:
            print(f"ERROR: Failed to handle Windows+E: {e}")
            # Don't open anything on error
    
    def _open_tfm_app(self, tfm_app):
        """Open TFM application using app_manager"""
        try:
            # Use app_manager's open_application function like other apps
            from src.titan_core.app_manager import open_application
            open_application(tfm_app)
            print("INFO: TFM application launched")

        except Exception as e:
            print(f"ERROR: Failed to open TFM: {e}")
            # Don't fallback to explorer - just log the error
            print("TFM failed to open, no fallback to Windows Explorer")

    def on_windows_b_pressed(self):
        """Handler for Windows+B keypress - opens System Tray list"""
        try:
            print("INFO: Windows+B pressed - opening System Tray list")
            threading.Thread(
                target=self._open_system_tray_list,
                daemon=True
            ).start()
        except Exception as e:
            print(f"ERROR: Failed to handle Windows+B: {e}")

    def _open_system_tray_list(self):
        """Open System Tray icon list"""
        try:
            main_frame = self._get_main_frame()
            if main_frame:
                from system_tray_list import show_system_tray_list
                wx.CallAfter(show_system_tray_list, main_frame)
                print("INFO: System Tray list opened")
            else:
                print("WARNING: Main frame not found for System Tray list")
        except Exception as e:
            print(f"ERROR: Failed to open System Tray list: {e}")
    

# Global system hooks manager
_system_hooks_manager = None
_manager_lock = threading.Lock()

def get_system_hooks_manager():
    """Get the global system hooks manager instance (thread-safe)"""
    global _system_hooks_manager
    with _manager_lock:
        if _system_hooks_manager is None:
            _system_hooks_manager = SystemHooksManager()
        return _system_hooks_manager

def start_system_hooks():
    """Start system hooks (Windows only - uses keyboard hooks)"""
    if not IS_WINDOWS:
        print("System hooks are only available on Windows")
        return

    manager = get_system_hooks_manager()
    manager.start_system_hooks()

def stop_system_hooks():
    """Stop system hooks"""
    if not IS_WINDOWS:
        return

    global _system_hooks_manager
    with _manager_lock:
        if _system_hooks_manager:
            _system_hooks_manager.stop_system_hooks()
            _system_hooks_manager = None

if __name__ == "__main__":
    # Test the system hooks
    print("Testing system hooks manager...")
    manager = SystemHooksManager()
    
    try:
        manager.start_system_hooks()
        print("System hooks started. Press Windows+E to test, Ctrl+C to stop.")
        
        # Keep main thread alive
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        manager.stop_system_hooks()
        print("System hooks stopped.")