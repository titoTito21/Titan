import platform
import threading
from typing import Set, Callable, Optional

class KeyBlocker:
    """Cross-platform key blocker for Titan UI mode"""
    
    def __init__(self):
        self.system = platform.system()
        self.blocking = False
        self.blocked_keys = set()
        self.hook = None
        self.thread = None
        
    def start_blocking(self, keys_to_block: Set[str]):
        """Start blocking specified keys"""
        if self.blocking:
            return
            
        self.blocked_keys = keys_to_block
        self.blocking = True
        
        # Try Windows low-level hooks first
        if self.system == "Windows":
            success = self._start_windows_blocking()
            if not success:
                print("Windows hook failed, trying fallback method...")
                self._start_fallback_blocking()
        else:
            # For non-Windows systems, use fallback method
            self._start_fallback_blocking()
    
    def stop_blocking(self):
        """Stop blocking keys"""
        if not self.blocking:
            return
            
        self.blocking = False
        
        # Stop Windows hooks if active
        if self.system == "Windows" and self.hook:
            self._stop_windows_blocking()
        
        # Stop keyboard library hooks
        try:
            import keyboard as kb
            kb.unhook_all()
        except (ImportError, Exception):
            pass
        
        self.blocked_keys.clear()
    
    def _start_windows_blocking(self):
        """Start Windows low-level keyboard blocking"""
        try:
            import ctypes
            from ctypes import wintypes
            
            # Windows constants
            WH_KEYBOARD_LL = 13
            
            # Virtual key codes we want to block
            VK_CODES = {
                'up': 0x26,      # VK_UP
                'down': 0x28,    # VK_DOWN  
                'left': 0x25,    # VK_LEFT
                'right': 0x27,   # VK_RIGHT
                'enter': 0x0D,   # VK_RETURN
                'space': 0x20,   # VK_SPACE
                'escape': 0x1B,  # VK_ESCAPE
                'backspace': 0x08, # VK_BACK
            }
            
            def low_level_keyboard_proc(nCode, wParam, lParam):
                try:
                    if nCode >= 0 and self.blocking:
                        # Get the virtual key code from lParam
                        # lParam points to a KBDLLHOOKSTRUCT
                        vk_code = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_ulong)).contents.value & 0xFFFFFFFF
                        
                        # Check if this key should be blocked
                        for key_name, key_code in VK_CODES.items():
                            if vk_code == key_code and key_name in self.blocked_keys:
                                # Block the key by returning 1 (don't pass to next hook)
                                return 1
                except Exception as e:
                    print(f"Error in keyboard hook: {e}")
                
                # Pass the key to the next hook
                try:
                    return ctypes.windll.user32.CallNextHookExW(self.hook, nCode, wParam, lParam)
                except:
                    return 0
            
            # Define the hook procedure type
            HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            self.hook_proc = HOOKPROC(low_level_keyboard_proc)
            
            # Get current module handle
            try:
                kernel32 = ctypes.windll.kernel32
                hmod = kernel32.GetModuleHandleW(None)
                if not hmod:
                    print("Could not get module handle")
                    return False
            except Exception as e:
                print(f"Error getting module handle: {e}")
                return False
            
            # Install the hook
            try:
                self.hook = ctypes.windll.user32.SetWindowsHookExW(
                    WH_KEYBOARD_LL,
                    self.hook_proc,
                    hmod,
                    0
                )
                
                if not self.hook:
                    error_code = ctypes.windll.kernel32.GetLastError()
                    print(f"Failed to install keyboard hook, error code: {error_code}")
                    return False
                    
                print("Keyboard hook installed successfully")
                return True
                
            except Exception as e:
                print(f"Error installing hook: {e}")
                return False
                
        except ImportError as e:
            print(f"Import error for Windows key blocking: {e}")
            return False
        except Exception as e:
            print(f"Error starting Windows key blocking: {e}")
            return False
    
    def _stop_windows_blocking(self):
        """Stop Windows keyboard blocking"""
        try:
            if self.hook:
                ctypes.windll.user32.UnhookWindowsHookExW(self.hook)
                self.hook = None
                
            # Signal message loop to stop
            if self.thread and self.thread.is_alive():
                ctypes.windll.user32.PostQuitMessage(0)
                self.thread.join(timeout=1.0)
                
        except Exception as e:
            print(f"Error stopping Windows key blocking: {e}")
    
    def _start_fallback_blocking(self):
        """Fallback method using keyboard library for aggressive key consumption"""
        try:
            import keyboard as kb
            
            def on_key_event(event):
                if self.blocking and event.event_type == kb.KEY_DOWN:
                    # Check if this key should be consumed
                    key_name = event.name.lower()
                    if key_name in self.blocked_keys:
                        # Try to suppress the key by immediately consuming it
                        try:
                            kb.press_and_release('ctrl+z')  # Send a harmless key combo to "consume" the event
                            return False  # Suppress the original key
                        except:
                            pass
                return True  # Allow other keys through
            
            # Register the hook
            kb.hook(on_key_event, suppress=True)
            print("Fallback key blocking active (using keyboard library)")
            return True
            
        except ImportError:
            print("Fallback key blocking requires 'keyboard' library: pip install keyboard")
            return False
        except Exception as e:
            print(f"Error starting fallback key blocking: {e}")
            return False


# Global key blocker instance
_key_blocker = None

def get_key_blocker() -> KeyBlocker:
    """Get the global key blocker instance"""
    global _key_blocker
    if _key_blocker is None:
        _key_blocker = KeyBlocker()
    return _key_blocker

def start_key_blocking(keys_to_block: Set[str]) -> bool:
    """Start blocking specified keys globally"""
    blocker = get_key_blocker()
    blocker.start_blocking(keys_to_block)
    return blocker.blocking

def stop_key_blocking():
    """Stop blocking keys globally"""
    blocker = get_key_blocker()
    blocker.stop_blocking()

def is_key_blocking_active() -> bool:
    """Check if key blocking is currently active"""
    blocker = get_key_blocker()
    return blocker.blocking