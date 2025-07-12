import os
import gettext
from invisibleui import BaseWidget
from settings import get_setting, set_setting, load_settings
from sound import set_theme
import os

# Inicjalizacja gettext dla tego apletu
try:
    applet_name = "quick_settings"
    localedir = os.path.join(os.path.dirname(__file__), 'languages')
    
    # Poprawne wczytanie globalnego ustawienia języka
    from settings import get_setting
    language_code = get_setting('language', 'pl')
    print(f"[Quick Settings] Trying to load language: '{language_code}' from '{localedir}'")
    
    translation = gettext.translation(applet_name, localedir, languages=[language_code], fallback=True)
    _ = translation.gettext
    print(f"[Quick Settings] Translation loaded successfully.")
except Exception as e:
    print(f"Error loading translation for quick_settings: {e}")
    # Fallback, jeśli tłumaczenie nie powiedzie się
    _ = gettext.gettext

class QuickSettingsWidget(BaseWidget):
    def __init__(self, speak_func):
        super().__init__(speak_func)
        self.settings_items = []
        self.current_row = 0
        self.current_col = 0
        self.grid_width = 2  # Ustawiamy siatkę na 2 kolumny
        self.load_settings()

    def get_available_languages(self):
        lang_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'languages'))
        try:
            return sorted([d for d in os.listdir(lang_dir) if os.path.isdir(os.path.join(lang_dir, d))])
        except FileNotFoundError:
            return ['en', 'pl']

    def get_available_skins(self):
        skins_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'skins'))
        try:
            return [_("Default")] + sorted([d for d in os.listdir(skins_dir) if os.path.isdir(os.path.join(skins_dir, d))])
        except FileNotFoundError:
            return [_("Default")]

    def get_sfx_themes(self):
        try:
            # Poprawna ścieżka do głównego katalogu sfx
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
            sfx_dir = os.path.join(base_dir, 'sfx')
            themes = [d for d in os.listdir(sfx_dir) if os.path.isdir(os.path.join(sfx_dir, d))]
            print(f"[Quick Settings] Found sound themes: {themes} in {sfx_dir}")
            return themes
        except FileNotFoundError:
            print(f"[Quick Settings] Error: sfx directory not found at {sfx_dir}")
            return ['default']

    def load_settings(self):
        self.settings_items = [
            # General
            {'name': _("Quick start"), 'section': 'general', 'key': 'quick_start', 'type': 'bool'},
            {'name': _("Confirm exit"), 'section': 'general', 'key': 'confirm_exit', 'type': 'bool'},
            {'name': _("Language"), 'section': 'general', 'key': 'language', 'type': 'choice', 'choices': self.get_available_languages()},
            # Sound
            {'name': _("Sound theme"), 'section': 'sound', 'key': 'theme', 'type': 'choice', 'choices': self.get_sfx_themes()},
            {'name': _("Stereo sounds"), 'section': 'sound', 'key': 'stereo_sound', 'type': 'bool'},
            # Interface
            {'name': _("Skin"), 'section': 'interface', 'key': 'skin', 'type': 'choice', 'choices': self.get_available_skins()},
            # Invisible Interface
            {'name': _("Announce item index"), 'section': 'invisible_interface', 'key': 'announce_index', 'type': 'bool'},
            {'name': _("Announce widget type"), 'section': 'invisible_interface', 'key': 'announce_widget_type', 'type': 'bool'},
            {'name': _("Enable TitanUI support"), 'section': 'invisible_interface', 'key': 'enable_titan_ui', 'type': 'bool'},
            {'name': _("Announce first item in category"), 'section': 'invisible_interface', 'key': 'announce_first_item', 'type': 'bool'}
        ]

    def get_current_element(self):
        index = self.current_row * self.grid_width + self.current_col
        if not (0 <= index < len(self.settings_items)):
            return _("Empty space")
        
        item = self.settings_items[index]
        value = get_setting(item['key'], section=item['section'])
        
        display_name = item['name']
        if item['key'] == 'language':
            display_name += f" {_('(requires restart)')}"

        if item['type'] == 'bool':
            value_str = _('On') if str(value).lower() == 'true' else _('Off')
        else:
            value_str = str(value)
            
        return f"{display_name}: {value_str}"

    def navigate(self, direction):
        num_items = len(self.settings_items)
        if num_items == 0:
            return False, 0, 1

        num_rows = (num_items + self.grid_width - 1) // self.grid_width
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
        if new_index >= num_items:
            self.current_row, self.current_col = old_row, old_col
            return False, old_col, self.grid_width

        if (self.current_row, self.current_col) != (old_row, old_col):
            return True, self.current_col, self.grid_width
        return False, old_col, self.grid_width

    def activate_current_element(self):
        index = self.current_row * self.grid_width + self.current_col
        if not (0 <= index < len(self.settings_items)):
            return

        item = self.settings_items[index]
        from sound import play_sound
        
        if item['type'] == 'bool':
            current_value = get_setting(item['key'], section=item['section'], default='false').lower() == 'true'
            new_value = str(not current_value)
            set_setting(item['key'], new_value, section=item['section'])
            play_sound('select.ogg')
            self.speak(f"{item['name']}: { _('On') if new_value.lower() == 'true' else _('Off')}")
        
        elif item['type'] == 'choice':
            current_value = get_setting(item['key'], section=item['section'])
            choices = item['choices']
            if not choices: return
            try:
                current_choice_index = choices.index(current_value)
            except ValueError:
                current_choice_index = -1
            
            new_choice_index = (current_choice_index + 1) % len(choices)
            new_value = choices[new_choice_index]
            set_setting(item['key'], new_value, section=item['section'])
            
            if item['key'] == 'theme':
                set_theme(new_value)
                # Dźwięk zostanie odtworzony z nowego motywu
                play_sound('select.ogg')
            else:
                play_sound('select.ogg')

            self.speak(f"{item['name']}: {new_value}")

def get_widget_instance(speak_func):
    return QuickSettingsWidget(speak_func)

def get_widget_info():
    return {
        "name": _("Quick Settings"),
        "type": "grid"
    }

