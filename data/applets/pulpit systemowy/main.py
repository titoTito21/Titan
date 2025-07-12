import os
import subprocess
from invisibleui import BaseWidget
import gettext
import sys
import glob

# Inicjalizacja gettext dla tego apletu
try:
    applet_name = "pulpit_systemowy"
    localedir = os.path.join(os.path.dirname(__file__), 'languages')
    
    # Poprawne wczytanie globalnego ustawienia języka
    from settings import get_setting
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
            desktop_path = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
            public_desktop_path = os.path.join(os.path.join(os.environ['PUBLIC']), 'Desktop')
            
            for lnk_path in glob.glob(os.path.join(desktop_path, '*.lnk')) + glob.glob(os.path.join(public_desktop_path, '*.lnk')):
                name = os.path.splitext(os.path.basename(lnk_path))[0]
                shortcuts.append({"name": name, "path": lnk_path})

        elif sys.platform == "darwin": # macOS
            apps_path = "/Applications"
            for app_path in glob.glob(os.path.join(apps_path, '*.app')):
                name = os.path.splitext(os.path.basename(app_path))[0]
                shortcuts.append({"name": name, "path": app_path})
        
        # Można dodać obsługę Linuksa w przyszłości
        # elif sys.platform.startswith('linux'):
        #     ...

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
                    # Dla macOS otwieramy aplikacje za pomocą 'open'
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", shortcut["path"]])
                    else: # Dla Windows i innych
                        os.startfile(shortcut["path"])
                    self.speak(f"Uruchamiam {shortcut['name']}")
                except Exception as e:
                    self.speak(f"Błąd podczas uruchamiania {shortcut['name']}: {e}")
            else:
                self.speak("Ten skrót jest pusty.")
        else:
            self.speak("Puste miejsce.")

def get_widget_instance(speak_func):
    return DesktopWidget(speak_func)

def get_widget_info():
    return {
        "name": _("Pulpit systemowy"),
        "type": "grid"
    }
