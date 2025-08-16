import platform
import subprocess
import psutil
from typing import List, Dict, Optional

try:
    import pywinctl as pwc
    PYWINCTL_AVAILABLE = True
except ImportError:
    PYWINCTL_AVAILABLE = False
    print("Warning: pywinctl not available. Install with: pip install pywinctl")

if platform.system() == "Windows":
    try:
        import win32gui
        import win32process
        import win32con
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
        print("Warning: win32gui not available. Install with: pip install pywin32")
else:
    WIN32_AVAILABLE = False

class WindowInfo:
    def __init__(self, handle, title, pid, process_name, is_active=False):
        self.handle = handle
        self.title = title
        self.pid = pid
        self.process_name = process_name
        self.is_active = is_active
        self.position = None
        self.size = None

class CrossPlatformWindowManager:
    def __init__(self):
        self.system = platform.system()
        
    def get_all_windows(self) -> List[WindowInfo]:
        """Get all visible application windows"""
        if PYWINCTL_AVAILABLE:
            return self._get_windows_pywinctl()
        elif self.system == "Windows" and WIN32_AVAILABLE:
            return self._get_windows_win32()
        elif self.system == "Linux":
            return self._get_windows_linux()
        else:
            return []
    
    def _get_windows_pywinctl(self) -> List[WindowInfo]:
        """Get windows using pywinctl (cross-platform)"""
        windows = []
        try:
            all_windows = pwc.getAllWindows()
            for window in all_windows:
                if window.title and window.title.strip():
                    try:
                        # Get PID using different methods depending on pywinctl version
                        pid = None
                        if hasattr(window, 'pid'):
                            pid = window.pid
                        elif hasattr(window, '_pid'):
                            pid = window._pid
                        elif hasattr(window, 'getProcessID'):
                            pid = window.getProcessID()
                        else:
                            # Try to get PID from handle on Windows
                            if platform.system() == "Windows":
                                try:
                                    import win32process
                                    _, pid = win32process.GetWindowThreadProcessId(window.getHandle())
                                except ImportError:
                                    continue
                            else:
                                continue
                        
                        if pid:
                            process = psutil.Process(pid)
                            is_active = False
                            if hasattr(window, 'isActive'):
                                is_active = window.isActive
                            elif hasattr(window, 'isActiveWindow'):
                                is_active = window.isActiveWindow()
                            
                            windows.append(WindowInfo(
                                handle=window.getHandle(),
                                title=window.title,
                                pid=pid,
                                process_name=process.name(),
                                is_active=is_active
                            ))
                    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                        continue
        except Exception as e:
            print(f"Error getting windows with pywinctl: {e}")
        return windows
    
    def _get_windows_win32(self) -> List[WindowInfo]:
        """Get windows using win32gui (Windows only)"""
        windows = []
        
        def callback(hwnd, windows_list):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title and title.strip():
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    try:
                        process = psutil.Process(pid)
                        is_active = win32gui.GetForegroundWindow() == hwnd
                        windows_list.append(WindowInfo(
                            handle=hwnd,
                            title=title,
                            pid=pid,
                            process_name=process.name(),
                            is_active=is_active
                        ))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            return True
        
        try:
            win32gui.EnumWindows(callback, windows)
        except Exception as e:
            print(f"Error getting windows with win32gui: {e}")
        return windows
    
    def _get_windows_linux(self) -> List[WindowInfo]:
        """Get windows using X11 tools (Linux only)"""
        windows = []
        try:
            # Using xdotool to get window list
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '.'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                window_ids = result.stdout.strip().split('\n')
                for window_id in window_ids:
                    if window_id:
                        try:
                            title_result = subprocess.run(['xdotool', 'getwindowname', window_id],
                                                        capture_output=True, text=True)
                            pid_result = subprocess.run(['xdotool', 'getwindowpid', window_id],
                                                      capture_output=True, text=True)
                            
                            if title_result.returncode == 0 and pid_result.returncode == 0:
                                title = title_result.stdout.strip()
                                pid = int(pid_result.stdout.strip())
                                
                                if title:
                                    process = psutil.Process(pid)
                                    
                                    # Check if window is active
                                    active_result = subprocess.run(['xdotool', 'getactivewindow'],
                                                                 capture_output=True, text=True)
                                    is_active = (active_result.returncode == 0 and 
                                               active_result.stdout.strip() == window_id)
                                    
                                    windows.append(WindowInfo(
                                        handle=window_id,
                                        title=title,
                                        pid=pid,
                                        process_name=process.name(),
                                        is_active=is_active
                                    ))
                        except (subprocess.CalledProcessError, psutil.NoSuchProcess, ValueError):
                            continue
        except Exception as e:
            print(f"Error getting windows on Linux: {e}")
        return windows
    
    def get_active_window(self) -> Optional[WindowInfo]:
        """Get currently active window"""
        if PYWINCTL_AVAILABLE:
            try:
                window = pwc.getActiveWindow()
                if window:
                    process = psutil.Process(window.pid)
                    return WindowInfo(
                        handle=window.getHandle(),
                        title=window.title,
                        pid=window.pid,
                        process_name=process.name(),
                        is_active=True
                    )
            except Exception:
                pass
        
        # Fallback: find active window from all windows
        for window in self.get_all_windows():
            if window.is_active:
                return window
        return None
    
    def activate_window(self, window_info: WindowInfo) -> bool:
        """Bring window to foreground"""
        try:
            if PYWINCTL_AVAILABLE:
                # Try different methods to get window by handle
                window = None
                try:
                    # Method 1: Try getWindowsWithHandle if available
                    if hasattr(pwc, 'getWindowsWithHandle'):
                        windows = pwc.getWindowsWithHandle(window_info.handle)
                        if windows:
                            window = windows[0]
                    # Method 2: Search through all windows
                    else:
                        all_windows = pwc.getAllWindows()
                        for w in all_windows:
                            if w.getHandle() == window_info.handle:
                                window = w
                                break
                except AttributeError:
                    # Method 3: Search by title and PID
                    all_windows = pwc.getAllWindows()
                    for w in all_windows:
                        if (w.title == window_info.title and 
                            w.getHandle() == window_info.handle):
                            window = w
                            break
                
                if window:
                    window.activate()
                    return True
            
            # Fallback methods
            if self.system == "Windows" and WIN32_AVAILABLE:
                win32gui.SetForegroundWindow(window_info.handle)
                return True
            elif self.system == "Linux":
                subprocess.run(['xdotool', 'windowactivate', str(window_info.handle)])
                return True
        except Exception as e:
            print(f"Error activating window: {e}")
        return False
    
    def close_window(self, window_info: WindowInfo) -> bool:
        """Close window"""
        try:
            if PYWINCTL_AVAILABLE:
                # Try different methods to get window by handle
                window = None
                try:
                    # Method 1: Try getWindowsWithHandle if available
                    if hasattr(pwc, 'getWindowsWithHandle'):
                        windows = pwc.getWindowsWithHandle(window_info.handle)
                        if windows:
                            window = windows[0]
                    # Method 2: Search through all windows
                    else:
                        all_windows = pwc.getAllWindows()
                        for w in all_windows:
                            if w.getHandle() == window_info.handle:
                                window = w
                                break
                except AttributeError:
                    # Method 3: Search by title and PID
                    all_windows = pwc.getAllWindows()
                    for w in all_windows:
                        if (w.title == window_info.title and 
                            w.getHandle() == window_info.handle):
                            window = w
                            break
                
                if window:
                    window.close()
                    return True
            
            # Fallback methods
            if self.system == "Windows" and WIN32_AVAILABLE:
                win32gui.PostMessage(window_info.handle, win32con.WM_CLOSE, 0, 0)
                return True
            elif self.system == "Linux":
                subprocess.run(['xdotool', 'windowclose', str(window_info.handle)])
                return True
        except Exception as e:
            print(f"Error closing window: {e}")
        return False
    
    def minimize_window(self, window_info: WindowInfo) -> bool:
        """Minimize window"""
        try:
            if PYWINCTL_AVAILABLE:
                # Try different methods to get window by handle
                window = None
                try:
                    # Method 1: Try getWindowsWithHandle if available
                    if hasattr(pwc, 'getWindowsWithHandle'):
                        windows = pwc.getWindowsWithHandle(window_info.handle)
                        if windows:
                            window = windows[0]
                    # Method 2: Search through all windows
                    else:
                        all_windows = pwc.getAllWindows()
                        for w in all_windows:
                            if w.getHandle() == window_info.handle:
                                window = w
                                break
                except AttributeError:
                    # Method 3: Search by title and PID
                    all_windows = pwc.getAllWindows()
                    for w in all_windows:
                        if (w.title == window_info.title and 
                            w.getHandle() == window_info.handle):
                            window = w
                            break
                
                if window:
                    window.minimize()
                    return True
            
            # Fallback methods
            if self.system == "Windows" and WIN32_AVAILABLE:
                win32gui.ShowWindow(window_info.handle, win32con.SW_MINIMIZE)
                return True
            elif self.system == "Linux":
                subprocess.run(['xdotool', 'windowminimize', str(window_info.handle)])
                return True
        except Exception as e:
            print(f"Error minimizing window: {e}")
        return False