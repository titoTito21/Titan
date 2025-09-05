import os
import sys
import threading
import time
import subprocess
import win32gui
import win32con
import win32api
import keyboard
from settings import get_setting
from app_manager import find_application_by_shortname, open_application
from translation import _

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
        """Start system interface hooks - Windows key and Windows+E"""
        if self.windows_e_hook_active:
            return
            
        try:
            # Hook Windows+E combination
            keyboard.add_hotkey('win+e', self.on_windows_e_pressed, suppress=True)
            
            # Hook Windows key (left and right)
            keyboard.add_hotkey('win', self.on_windows_key_pressed, suppress=True)
            
            self.windows_e_hook_active = True
            print("INFO: System interface hooks activated - Windows key -> Classic Start Menu, Windows+E -> TFM")
        except Exception as e:
            print(f"ERROR: Failed to start system interface hooks: {e}")
    
    def stop_system_interface_hooks(self):
        """Stop system interface hooks"""
        if not self.windows_e_hook_active:
            return
            
        try:
            keyboard.remove_hotkey('win+e')
            keyboard.remove_hotkey('win')
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
    
    def _open_classic_start_menu(self):
        """Open Classic Start Menu"""
        try:
            from classic_start_menu import create_classic_start_menu
            create_classic_start_menu()
            print("INFO: Classic Start Menu opened")
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
            from app_manager import open_application
            open_application(tfm_app)
            print("INFO: TFM application launched")
            
        except Exception as e:
            print(f"ERROR: Failed to open TFM: {e}")
            # Don't fallback to explorer - just log the error
            print("TFM failed to open, no fallback to Windows Explorer")
    

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
    """Start system hooks"""
    manager = get_system_hooks_manager()
    manager.start_system_hooks()

def stop_system_hooks():
    """Stop system hooks"""
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