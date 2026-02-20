import os
import subprocess
import gettext
import sys
import glob

# Add TCE root to path
APPLET_DIR = os.path.dirname(__file__)
TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

from src.ui.invisibleui import BaseWidget

# Inicjalizacja gettext dla tego apletu
try:
    applet_name = "pulpit_systemowy"
    localedir = os.path.join(os.path.dirname(__file__), 'languages')

    # Poprawne wczytanie globalnego ustawienia języka
    from src.settings.settings import get_setting
    language_code = get_setting('language', 'pl')
    print(f"[Pulpit systemowy] Trying to load language: '{language_code}' from '{localedir}'")
    
    translation = gettext.translation(applet_name, localedir, languages=[language_code], fallback=True)
    _ = translation.gettext
    print(f"[Pulpit systemowy] Translation loaded successfully.")
except Exception as e:
    print(f"Error loading translation for pulpit_systemowy: {e}")
    # Fallback, jeśli tłumaczenie nie powiedzie się
    _ = gettext.gettext

class DesktopWidget(BaseWidget):
    def __init__(self, speak_func):
        super().__init__(speak_func)
        self.shortcuts = self._find_shortcuts()
        self.current_row = 0
        self.current_col = 0
        # Przykładowa siatka 4xN
        self.grid_width = 4

    def _find_shortcuts(self):
        shortcuts = []
        if sys.platform == "win32":
            home = os.path.expanduser('~')
            desktop_path = os.path.join(home, 'Desktop')
            public = os.environ.get('PUBLIC', '')
            public_desktop_path = os.path.join(public, 'Desktop') if public else ''

            paths = glob.glob(os.path.join(desktop_path, '*.lnk'))
            if public_desktop_path:
                paths += glob.glob(os.path.join(public_desktop_path, '*.lnk'))
            for lnk_path in paths:
                name = os.path.splitext(os.path.basename(lnk_path))[0]
                shortcuts.append({"name": name, "path": lnk_path})

        elif sys.platform == "darwin":  # macOS
            apps_path = "/Applications"
            for app_path in glob.glob(os.path.join(apps_path, '*.app')):
                name = os.path.splitext(os.path.basename(app_path))[0]
                shortcuts.append({"name": name, "path": app_path})

        elif sys.platform.startswith('linux'):
            desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')
            if os.path.isdir(desktop_path):
                for entry in os.listdir(desktop_path):
                    full = os.path.join(desktop_path, entry)
                    if os.path.isfile(full):
                        name = os.path.splitext(entry)[0]
                        shortcuts.append({"name": name, "path": full})

        return shortcuts

    def get_current_element(self):
        index = self.current_row * self.grid_width + self.current_col
        if 0 <= index < len(self.shortcuts):
            return self.shortcuts[index]["name"]
        return _("Puste miejsce")

    def navigate(self, direction):
        num_shortcuts = len(self.shortcuts)
        if num_shortcuts == 0:
            return False, 0, 1

        num_rows = (num_shortcuts + self.grid_width - 1) // self.grid_width
        old_row, old_col = self.current_row, self.current_col

        if direction == 'up':
            self.current_row = max(0, self.current_row - 1)
        elif direction == 'down':
            self.current_row = min(num_rows - 1, self.current_row + 1)
        elif direction == 'left':
            self.current_col = max(0, self.current_col - 1)
        elif direction == 'right':
            self.current_col = min(self.grid_width - 1, self.current_col + 1)
        
        new_index = self.current_row * self.grid_width + self.current_col
        if new_index >= num_shortcuts:
            self.current_row, self.current_col = old_row, old_col
            return False, old_col, self.grid_width

        if (self.current_row, self.current_col) != (old_row, old_col):
            return True, self.current_col, self.grid_width
        return False, old_col, self.grid_width

    def activate_current_element(self):
        index = self.current_row * self.grid_width + self.current_col
        if 0 <= index < len(self.shortcuts):
            shortcut = self.shortcuts[index]
            if shortcut["path"]:
                try:
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", shortcut["path"]])
                    elif sys.platform == "win32":
                        os.startfile(shortcut["path"])
                    else:
                        subprocess.Popen(["xdg-open", shortcut["path"]])
                    
                    # Użyj pozycjonowania stereo dla widget activation
                    position = (self.current_col / (self.grid_width - 1) * 2.0) - 1.0 if self.grid_width > 1 else 0.0
                    self.speak_with_position(_("Launching {}").format(shortcut['name']), position=position)
                except Exception as e:
                    position = (self.current_col / (self.grid_width - 1) * 2.0) - 1.0 if self.grid_width > 1 else 0.0
                    self.speak_with_position(_("Error launching {}: {}").format(shortcut['name'], e), position=position)
            else:
                position = (self.current_col / (self.grid_width - 1) * 2.0) - 1.0 if self.grid_width > 1 else 0.0
                self.speak_with_position(_("This shortcut is empty."), position=position)

def get_widget_instance(speak_func):
    return DesktopWidget(speak_func)

def get_widget_info():
    return {
        "name": _("Pulpit systemowy"),
        "type": "grid"
    }
