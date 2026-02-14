import threading
import time
import platform
import accessible_output3.outputs.auto
from src.titan_core.sound import play_sound
from src.titan_core.translation import _
from src.settings.settings import get_setting
import queue
import sys
import subprocess
from src.titan_core.stereo_speech import get_stereo_speech

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

# Windows-specific imports
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32con
    import win32gui
    import win32ts
    import keyboard

# Session change constants (Windows-specific)
WM_WTSSESSION_CHANGE = 0x2B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

class ThreadSafeEventMonitor:
    """Thread-safe event-driven session monitor (Windows primary, stubs for other platforms)"""

    def __init__(self):
        self.is_locked = False
        self.monitoring = False
        self.monitor_thread = None
        self.speaker = accessible_output3.outputs.auto.Auto()
        self.stereo_speech = get_stereo_speech()
        self.lock_overlay_active = False
        self.keyboard_hook = None

        # Thread-safe event queue for communicating between threads
        self.event_queue = queue.Queue()
        self.event_thread = None
        self.window_handle = None

        # Thread synchronization
        self.state_lock = threading.RLock()  # Reentrant lock for state changes
        self.cleanup_event = threading.Event()

        # Platform check
        self.platform_supported = IS_WINDOWS
        
    def __del__(self):
        """Safe cleanup on destruction"""
        self.stop_monitoring()
    
    def _create_message_window(self):
        """Create invisible window to receive session change messages (Windows only)"""
        if not IS_WINDOWS:
            return False

        try:
            # Define window class
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._window_proc
            wc.lpszClassName = 'LockScreenMonitor'
            wc.hInstance = win32api.GetModuleHandle(None)

            # Register window class
            class_atom = win32gui.RegisterClass(wc)

            # Create window
            self.window_handle = win32gui.CreateWindow(
                class_atom, 'LockScreenMonitor', 0, 0, 0, 0, 0,
                win32con.HWND_MESSAGE, None, wc.hInstance, None
            )

            if self.window_handle:
                # Register for session change notifications
                win32ts.WTSRegisterSessionNotification(
                    self.window_handle,
                    win32ts.NOTIFY_FOR_THIS_SESSION
                )
                return True
            return False

        except Exception as e:
            print(f"Error creating message window: {e}")
            return False
    
    def _window_proc(self, hwnd, msg, wparam, lparam):
        """Window procedure to handle session change messages"""
        if msg == WM_WTSSESSION_CHANGE:
            try:
                # Queue the event for processing in monitor thread
                self.event_queue.put((wparam, time.time()), timeout=0.1)
            except queue.Full:
                print("Event queue full, dropping session change event")
        
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
    
    def is_workstation_locked_fast(self):
        """Improved Windows lock screen detection with multiple methods"""
        try:
            # Method 1: Check for LogonUI.exe process (most reliable)
            try:
                output = subprocess.check_output('tasklist /fi "imagename eq LogonUI.exe"', shell=True, text=True)
                if 'LogonUI.exe' in output:
                    return True
            except:
                pass
            
            # Method 2: Check WTS session state
            try:
                session_id = win32ts.WTSGetActiveConsoleSessionId()
                if session_id != 0xFFFFFFFF:  # Valid session
                    session_info = win32ts.WTSQuerySessionInformation(win32ts.WTS_CURRENT_SERVER_HANDLE, session_id, win32ts.WTSSessionState)
                    if session_info == win32ts.WTSLocked:
                        return True
            except:
                pass
            
            # Method 3: Check for lock screen windows
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd != 0:
                class_name = ctypes.create_unicode_buffer(256)
                if ctypes.windll.user32.GetClassNameW(hwnd, class_name, 256):
                    if class_name.value in ['Windows.UI.Core.CoreWindow', 'LockApp', 'LogonUI Logon Window']:
                        return True
            
            # Method 4: Check if taskbar is visible (fallback)
            shell = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
            if shell == 0 or not ctypes.windll.user32.IsWindowVisible(shell):
                return True
            
            return False
            
        except Exception as e:
            print(f"Error in lock detection: {e}")
            return False
    
    def play_lock_sound(self):
        """Play lock screen sound safely"""
        # Check if screen lock announcement is enabled
        announce_enabled = get_setting('announce_screen_lock', 'True', 'environment').lower() in ['true', '1']
        if not announce_enabled:
            return
        
        try:
            play_sound('system/lock_screen.ogg')
        except:
            try:
                play_sound('system/onlock_screen.ogg')
            except:
                pass
    
    def play_unlock_sound(self):
        """Play unlock screen sound safely"""
        # Check if screen lock announcement is enabled
        announce_enabled = get_setting('announce_screen_lock', 'True', 'environment').lower() in ['true', '1']
        if not announce_enabled:
            return
        
        try:
            play_sound('system/unlock_screen.ogg')
        except:
            try:
                play_sound('system/onlock_screen.ogg')
            except:
                pass
    
    def announce_lock_status(self, locked):
        """Thread-safe lock status announcement with stereo speech support"""
        try:
            # Check if screen lock announcement is enabled
            announce_enabled = get_setting('announce_screen_lock', 'True', 'environment').lower() in ['true', '1']
            if not announce_enabled:
                return
            
            if locked:
                message = _("Screen locked")
                if not message or message == "Screen locked":
                    message = "Screen locked"
                position = -0.5  # Center-left for lock
                pitch_offset = -2  # Lower pitch for lock
            else:
                message = _("Screen unlocked") 
                if not message or message == "Screen unlocked":
                    message = "Screen unlocked"
                position = 0.5   # Center-right for unlock
                pitch_offset = 2   # Higher pitch for unlock
            
            # Check if stereo speech is enabled in settings
            stereo_enabled = get_setting('stereo_speech', 'False', 'invisible_interface').lower() in ['true', '1']
            
            if stereo_enabled and self.stereo_speech:
                # Use stereo speech with positioning and pitch
                # Stereo speech already has fallback to accessible_output3 built-in
                try:
                    self.stereo_speech.speak_async(message, position=position, pitch_offset=pitch_offset, use_fallback=True)
                except Exception as stereo_e:
                    print(f"Stereo speech failed: {stereo_e}")
                    # Fallback to regular accessible_output3
                    try:
                        self.speaker.speak(message)
                    except Exception as ao3_e:
                        print(f"All TTS methods failed: stereo={stereo_e}, ao3={ao3_e}")
            else:
                # Use regular accessible_output3 if stereo is disabled
                try:
                    self.speaker.speak(message)
                except Exception as ao3_e:
                    print(f"accessible_output3 TTS failed: {ao3_e}")
                    # Fallback to stereo_speech which has additional fallback mechanisms
                    if self.stereo_speech:
                        try:
                            self.stereo_speech.speak_async(message, position=position, pitch_offset=pitch_offset, use_fallback=True)
                        except Exception as stereo_e:
                            print(f"All TTS methods failed: ao3={ao3_e}, stereo={stereo_e}")
                    else:
                        print(f"No alternative TTS available")
                    
        except Exception as e:
            print(f"Error announcing lock status: {e}")
    
    def on_key_press(self, event):
        """Handle key press during lock overlay"""
        if self.lock_overlay_active and self.is_locked:
            # Check if screen is still locked
            if not self.is_workstation_locked_fast():
                # Queue unlock event
                try:
                    self.event_queue.put((WTS_SESSION_UNLOCK, time.time()), timeout=0.1)
                except queue.Full:
                    pass
            return True
    
    def start_lock_overlay(self):
        """Start keyboard monitoring during lock"""
        with self.state_lock:
            if not self.lock_overlay_active:
                self.lock_overlay_active = True
                try:
                    self.keyboard_hook = keyboard.on_press(self.on_key_press, suppress=False)
                except Exception as e:
                    print(f"Failed to start keyboard hook: {e}")
    
    def stop_lock_overlay(self):
        """Stop keyboard monitoring"""
        with self.state_lock:
            if self.lock_overlay_active:
                self.lock_overlay_active = False
                try:
                    if self.keyboard_hook:
                        keyboard.unhook(self.keyboard_hook)
                        self.keyboard_hook = None
                except Exception as e:
                    print(f"Failed to stop keyboard hook: {e}")
    
    def _process_events(self):
        """Process session change events from queue"""
        while self.monitoring and not self.cleanup_event.is_set():
            try:
                # Wait for event with timeout
                event_data = self.event_queue.get(timeout=1.0)
                event_type, timestamp = event_data
                
                with self.state_lock:
                    if event_type == WTS_SESSION_LOCK:
                        if not self.is_locked:
                            print("Session locked event received")
                            self.is_locked = True
                            self.play_lock_sound()
                            self.announce_lock_status(True)
                            self.start_lock_overlay()
                    
                    elif event_type == WTS_SESSION_UNLOCK:
                        if self.is_locked:
                            # Verify unlock with quick check
                            if not self.is_workstation_locked_fast():
                                print("Session unlocked event received")
                                self.is_locked = False
                                self.stop_lock_overlay()
                                self.play_unlock_sound()
                                self.announce_lock_status(False)
                            else:
                                print("Unlock event received but screen still locked")
                
                self.event_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error processing event: {e}")
                time.sleep(1)
    
    def _message_pump(self):
        """Message pump for the invisible window"""
        try:
            while self.monitoring and not self.cleanup_event.is_set():
                try:
                    # Use GetMessage instead of PeekMessage to avoid argument errors
                    bRet = win32gui.GetMessage(None, 0, 0)
                    if bRet == 0:  # WM_QUIT
                        break
                    elif bRet == -1:  # Error
                        print("GetMessage error")
                        break
                    else:
                        # Process the message
                        msg = bRet
                        win32gui.TranslateMessage(msg)
                        win32gui.DispatchMessage(msg)
                        
                except Exception as e:
                    if self.cleanup_event.is_set():
                        break
                    print(f"Message pump error: {e}")
                    time.sleep(0.1)
        except Exception as e:
            print(f"Message pump thread error: {e}")
        finally:
            print("Message pump thread exiting")
    
    def start_monitoring(self):
        """Start lock screen monitoring (use reliable polling)"""
        with self.state_lock:
            if self.monitoring:
                return
            
            print("Starting reliable polling lock screen monitoring")
            self.monitoring = True
            
            # Use polling approach - more reliable than Windows messages
            self._start_polling_fallback()
    
    def _start_polling_fallback(self):
        """Fallback to polling if event-driven approach fails"""
        print("Starting polling fallback")
        self.monitor_thread = threading.Thread(
            target=self._polling_monitor, 
            daemon=True, 
            name="LockPollingMonitor"
        )
        self.monitor_thread.start()
    
    def _polling_monitor(self):
        """Fallback polling monitor with improved reliability"""
        stable_locked_count = 0
        stable_unlocked_count = 0
        required_stable_checks = 3
        debug_counter = 0
        
        while self.monitoring and not self.cleanup_event.is_set():
            try:
                current_locked = self.is_workstation_locked_fast()
                debug_counter += 1
                
                # Debug output every 40 checks (20 seconds with 0.5s sleep)
                if debug_counter % 40 == 0:
                    print(f"Polling monitor: locked={current_locked}, state={self.is_locked}")
                
                with self.state_lock:
                    if current_locked:
                        stable_locked_count += 1
                        stable_unlocked_count = 0
                    else:
                        stable_unlocked_count += 1
                        stable_locked_count = 0
                    
                    # State transitions
                    if not self.is_locked and stable_locked_count >= required_stable_checks:
                        print("Screen locked (polling)")
                        self.is_locked = True
                        self.play_lock_sound()
                        self.announce_lock_status(True)
                        self.start_lock_overlay()
                        stable_locked_count = 0
                        
                    elif self.is_locked and stable_unlocked_count >= required_stable_checks:
                        print("Screen unlocked (polling)")
                        self.is_locked = False
                        self.stop_lock_overlay()
                        self.play_unlock_sound()
                        self.announce_lock_status(False)
                        stable_unlocked_count = 0
                
                # Use event for interruptible sleep
                if self.cleanup_event.wait(0.5):  # 500ms sleep with interrupt
                    break
                    
            except Exception as e:
                print(f"Error in polling monitor: {e}")
                if not self.cleanup_event.wait(2):  # 2s sleep on error
                    break
    
    def stop_monitoring(self):
        """Stop monitoring with proper cleanup"""
        with self.state_lock:
            if not self.monitoring:
                return
            
            print("Stopping lock screen monitoring")
            self.monitoring = False
            self.cleanup_event.set()
            
            # Stop overlay first
            self.stop_lock_overlay()
            
            # Clean up window (if any was created)
            if self.window_handle:
                try:
                    win32ts.WTSUnRegisterSessionNotification(self.window_handle)
                    win32gui.DestroyWindow(self.window_handle)
                    self.window_handle = None
                except Exception as e:
                    print(f"Error cleaning up window: {e}")
            
            # Join threads with timeout
            threads_to_join = []
            if self.monitor_thread and self.monitor_thread.is_alive():
                threads_to_join.append(("Monitor", self.monitor_thread))
            if self.event_thread and self.event_thread.is_alive():
                threads_to_join.append(("Event", self.event_thread))
            
            for name, thread in threads_to_join:
                try:
                    thread.join(timeout=3)
                    if thread.is_alive():
                        print(f"Warning: {name} thread did not shut down cleanly")
                except Exception as e:
                    print(f"Error joining {name} thread: {e}")
            
            # Final cleanup
            self.cleanup_event.clear()

# Global monitor instance with thread safety
_lock_monitor = None
_monitor_lock = threading.Lock()

def get_lock_monitor():
    """Get the global lock monitor instance (thread-safe)"""
    global _lock_monitor
    with _monitor_lock:
        if _lock_monitor is None:
            _lock_monitor = ThreadSafeEventMonitor()
        return _lock_monitor

def start_lock_monitoring():
    """Start lock screen monitoring (Windows only)"""
    if not IS_WINDOWS:
        print("Lock screen monitoring is only available on Windows")
        return

    monitor = get_lock_monitor()
    monitor.start_monitoring()

def stop_lock_monitoring():
    """Stop lock screen monitoring"""
    if not IS_WINDOWS:
        return

    global _lock_monitor
    with _monitor_lock:
        if _lock_monitor:
            _lock_monitor.stop_monitoring()
            _lock_monitor = None

def test_lock_detection():
    """Test lock detection - simplified for thread safety"""
    monitor = ThreadSafeEventMonitor()
    result = monitor.is_workstation_locked_fast()
    print(f"Lock detection result: {'LOCKED' if result else 'UNLOCKED'}")
    return result

if __name__ == "__main__":
    # Test the improved monitor
    print("Testing improved lock screen monitor...")
    monitor = ThreadSafeEventMonitor()
    
    try:
        monitor.start_monitoring()
        print("Monitor started. Press Ctrl+C to stop.")
        
        # Keep main thread alive
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        monitor.stop_monitoring()
        print("Monitor stopped.")