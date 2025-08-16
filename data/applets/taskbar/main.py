import os
import sys
import gettext
import threading
import time
from typing import List, Optional

# Add current directory to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from window_manager import CrossPlatformWindowManager, WindowInfo
except ImportError:
    print("Error: Could not import window_manager")
    class WindowInfo:
        def __init__(self, handle, title, pid, process_name, is_active=False):
            self.handle = handle
            self.title = title
            self.pid = pid
            self.process_name = process_name
            self.is_active = is_active
    
    class CrossPlatformWindowManager:
        def get_all_windows(self):
            return []
        def activate_window(self, window_info):
            return False
        def close_window(self, window_info):
            return False

# Setup translations
domain = 'taskbar'
localedir = os.path.join(current_dir, 'languages')
try:
    translation = gettext.translation(domain, localedir, fallback=True)
    _ = translation.gettext
except Exception:
    _ = lambda x: x

class TaskbarWidget:
    def __init__(self, speak_func, view=None):
        self.speak = speak_func
        self.view = view
        self.window_manager = CrossPlatformWindowManager()
        self.windows = []
        self.current_index = 0
        self.refresh_interval = 2.0  # Refresh every 2 seconds
        self.last_refresh = 0
        self.context_menu_open = False
        self.context_menu_index = 0
        self.context_menu_actions = [
            _("Activate window"),
            _("Close window"),
            _("Minimize window"),
            _("Back")
        ]
        self.refresh_windows()

    def set_border(self):
        if self.view:
            try:
                pass  # Widget border implementation if needed
            except Exception as e:
                print(f"Could not set border on taskbar widget: {e}")

    def refresh_windows(self):
        """Refresh the list of windows"""
        current_time = time.time()
        if current_time - self.last_refresh < self.refresh_interval:
            return
        
        try:
            all_windows = self.window_manager.get_all_windows()
            # Filter out empty titles and system windows
            filtered_windows = []
            for window in all_windows:
                if (window.title and 
                    len(window.title.strip()) > 0 and
                    not self._is_system_window(window)):
                    filtered_windows.append(window)
            
            self.windows = filtered_windows
            self.last_refresh = current_time
            
            # Adjust current index if needed
            if self.current_index >= len(self.windows):
                self.current_index = max(0, len(self.windows) - 1)
                
        except Exception as e:
            print(f"Error refreshing windows: {e}")
            self.windows = []

    def _is_system_window(self, window: WindowInfo) -> bool:
        """Check if window should be filtered out (system windows, etc.)"""
        system_processes = [
            'dwm.exe', 'winlogon.exe', 'csrss.exe', 'explorer.exe',
            'taskeng.exe', 'svchost.exe', 'System', 'smss.exe'
        ]
        system_titles = [
            'Program Manager', 'Default IME', 'MSCTFIME UI',
            'GDI+ Window', 'Hidden Window'
        ]
        
        # Filter by process name
        if window.process_name.lower() in [p.lower() for p in system_processes]:
            return True
            
        # Filter by title
        if window.title in system_titles:
            return True
            
        # Filter very short titles (likely system windows)
        if len(window.title.strip()) < 3:
            return True
            
        return False

    def navigate(self, direction):
        """Navigate through windows or context menu"""
        self.refresh_windows()
        
        if self.context_menu_open:
            return self._navigate_context_menu(direction)
        else:
            return self._navigate_windows(direction)

    def _navigate_windows(self, direction):
        """Navigate through the window list"""
        if not self.windows:
            return (False, 0, 1)
        
        old_index = self.current_index
        
        if direction in ['left', 'up']:
            self.current_index = max(0, self.current_index - 1)
        elif direction in ['right', 'down']:
            self.current_index = min(len(self.windows) - 1, self.current_index + 1)
        
        success = self.current_index != old_index
        return (success, self.current_index, len(self.windows))

    def _navigate_context_menu(self, direction):
        """Navigate through context menu"""
        old_index = self.context_menu_index
        
        if direction in ['up', 'left']:
            self.context_menu_index = max(0, self.context_menu_index - 1)
        elif direction in ['down', 'right']:
            self.context_menu_index = min(len(self.context_menu_actions) - 1, 
                                        self.context_menu_index + 1)
        
        success = self.context_menu_index != old_index
        return (success, self.context_menu_index, len(self.context_menu_actions))

    def activate_current_element(self):
        """Activate current window or context menu action"""
        if self.context_menu_open:
            self._activate_context_menu_action()
        else:
            self._show_context_menu()

    def _show_context_menu(self):
        """Show context menu for current window"""
        if not self.windows or self.current_index >= len(self.windows):
            self.speak(_("No window selected"))
            return
        
        self.context_menu_open = True
        self.context_menu_index = 0
        
        # Play context menu open sound
        try:
            from sound import play_sound
            play_sound('contextmenu.ogg')
        except ImportError:
            pass
        
        window = self.windows[self.current_index]
        self.speak(_("Context menu for {}").format(window.title))

    def _activate_context_menu_action(self):
        """Execute selected context menu action"""
        if not self.windows or self.current_index >= len(self.windows):
            self._close_context_menu()
            return
        
        action = self.context_menu_actions[self.context_menu_index]
        window = self.windows[self.current_index]
        
        if action == _("Activate window"):
            success = self.window_manager.activate_window(window)
            if success:
                self.speak(_("Window activated: {}").format(window.title))
            else:
                self.speak(_("Failed to activate window"))
                
        elif action == _("Close window"):
            success = self.window_manager.close_window(window)
            if success:
                self.speak(_("Window closed: {}").format(window.title))
                # Remove from list and refresh
                self.refresh_windows()
            else:
                self.speak(_("Failed to close window"))
                
        elif action == _("Minimize window"):
            success = self.window_manager.minimize_window(window)
            if success:
                self.speak(_("Window minimized: {}").format(window.title))
            else:
                self.speak(_("Failed to minimize window"))
                
        elif action == _("Back"):
            pass  # Just close menu
        
        self._close_context_menu()

    def _close_context_menu(self):
        """Close context menu"""
        if self.context_menu_open:
            self.context_menu_open = False
            self.context_menu_index = 0
            
            # Play context menu close sound
            try:
                from sound import play_sound
                play_sound('contextmenuclose.ogg')
            except ImportError:
                pass
            
            # Speak current window again
            if self.windows and self.current_index < len(self.windows):
                window = self.windows[self.current_index]
                self.speak(window.title)

    def get_current_element(self):
        """Get current element description"""
        self.refresh_windows()
        
        if self.context_menu_open:
            if self.context_menu_index < len(self.context_menu_actions):
                return self.context_menu_actions[self.context_menu_index]
            return _("Context menu")
        
        if not self.windows:
            return _("No windows found")
        
        if self.current_index >= len(self.windows):
            self.current_index = max(0, len(self.windows) - 1)
        
        if self.current_index < len(self.windows):
            window = self.windows[self.current_index]
            active_indicator = _(" (active)") if window.is_active else ""
            return f"{window.title} - {window.process_name}{active_indicator}"
        
        return _("No window selected")

    def handle_titan_enter(self):
        """Handle Titan+Enter - directly activate window without context menu"""
        if not self.windows or self.current_index >= len(self.windows):
            self.speak(_("No window to activate"))
            return
        
        window = self.windows[self.current_index]
        success = self.window_manager.activate_window(window)
        if success:
            self.speak(_("Activated: {}").format(window.title))
        else:
            self.speak(_("Failed to activate window"))

def get_widget_info():
    """Return widget information"""
    return {
        "name": _("Taskbar"),
        "type": "grid",
        "description": _("Window switching taskbar widget")
    }

def get_widget_instance(speak_func, view=None):
    """Return widget instance"""
    return TaskbarWidget(speak_func, view)