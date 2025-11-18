import os
import gettext
from settings import get_setting, set_setting, load_settings
from sound import set_theme

# BaseWidget definition to avoid circular import
class BaseWidget:
    def __init__(self, speak_func):
        self.speak = speak_func
        self.view = None
        # Control type strings for translation  
        try:
            from translation import set_language
            _ = set_language(get_setting('language', 'pl'))
            self._control_types = {
                'slider': _("slider"),
                'button': _("button"), 
                'checkbox': _("checkbox"),
                'list item': _("list item")
            }
        except:
            self._control_types = {
                'slider': "slider",
                'button': "button", 
                'checkbox': "checkbox",
                'list item': "list item"
            }
    
    def speak_with_position(self, text, position=0.0, pitch_offset=0):
        self.speak(text, position=position, pitch_offset=pitch_offset)

    def set_border(self):
        if self.view:
            try:
                self.view.setStyleSheet("border: 1px solid black;")
            except AttributeError:
                pass

    def get_current_element(self):
        raise NotImplementedError

    def navigate(self, direction):
        raise NotImplementedError

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
        self._settings_cache = {}  # Cache to prevent I/O hangs
        self._cache_timestamp = 0
        self.load_settings()

    def get_available_languages(self):
        """Get available languages with safe error handling"""
        try:
            lang_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'languages'))
            if not os.path.exists(lang_dir):
                return ['en', 'pl']
            
            # Use timeout and limit directory scanning
            languages = []
            for item in os.listdir(lang_dir)[:20]:  # Limit to prevent hangs
                item_path = os.path.join(lang_dir, item)
                if os.path.isdir(item_path) and len(item) <= 5:  # Basic validation
                    languages.append(item)
            return sorted(languages) if languages else ['en', 'pl']
        except (OSError, PermissionError, Exception):
            return ['en', 'pl']

    def get_available_skins(self):
        """Get available skins with safe error handling"""
        try:
            skins_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'skins'))
            if not os.path.exists(skins_dir):
                return [_("Default")]
            
            skins = [_("Default")]
            for item in os.listdir(skins_dir)[:20]:  # Limit to prevent hangs
                item_path = os.path.join(skins_dir, item)
                if os.path.isdir(item_path):
                    skins.append(item)
            return skins
        except (OSError, PermissionError, Exception):
            return [_("Default")]

    def get_sfx_themes(self):
        """Get sound themes with safe error handling"""
        try:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
            sfx_dir = os.path.join(base_dir, 'sfx')
            
            if not os.path.exists(sfx_dir):
                return ['default']
            
            themes = []
            for item in os.listdir(sfx_dir)[:20]:  # Limit to prevent hangs
                item_path = os.path.join(sfx_dir, item)
                if os.path.isdir(item_path):
                    themes.append(item)
            
            return themes if themes else ['default']
        except (OSError, PermissionError, Exception):
            return ['default']

    def _get_cached_setting(self, key, section='general', default=None):
        """Get setting with caching to prevent I/O hangs"""
        import time
        current_time = time.time()
        
        # Refresh cache every 5 seconds
        if current_time - self._cache_timestamp > 5:
            self._settings_cache.clear()
            self._cache_timestamp = current_time
        
        cache_key = f"{section}.{key}"
        if cache_key not in self._settings_cache:
            try:
                self._settings_cache[cache_key] = get_setting(key, default=default, section=section)
            except Exception:
                self._settings_cache[cache_key] = default
        
        return self._settings_cache[cache_key]

    def load_settings(self):
        """Load settings with safe error handling"""
        try:
            # Pre-cache directory contents to avoid hangs during navigation
            available_languages = self.get_available_languages()
            available_themes = self.get_sfx_themes()
            available_skins = self.get_available_skins()
            
            self.settings_items = [
                # General
                {'name': _("Quick start"), 'section': 'general', 'key': 'quick_start', 'type': 'bool'},
                {'name': _("Confirm exit"), 'section': 'general', 'key': 'confirm_exit', 'type': 'bool'},
                {'name': _("Language"), 'section': 'general', 'key': 'language', 'type': 'choice', 'choices': available_languages},
                # Sound
                {'name': _("Sound theme"), 'section': 'sound', 'key': 'theme', 'type': 'choice', 'choices': available_themes},
                {'name': _("Stereo sounds"), 'section': 'sound', 'key': 'stereo_sound', 'type': 'bool'},
                # Interface
                {'name': _("Skin"), 'section': 'interface', 'key': 'skin', 'type': 'choice', 'choices': available_skins},
                # Invisible Interface
                {'name': _("Announce item index"), 'section': 'invisible_interface', 'key': 'announce_index', 'type': 'bool'},
                {'name': _("Announce widget type"), 'section': 'invisible_interface', 'key': 'announce_widget_type', 'type': 'bool'},
                {'name': _("Enable TitanUI support"), 'section': 'invisible_interface', 'key': 'enable_titan_ui', 'type': 'bool'},
                {'name': _("Announce first item in category"), 'section': 'invisible_interface', 'key': 'announce_first_item', 'type': 'bool'}
            ]
        except Exception as e:
            print(f"Error loading settings items: {e}")
            # Minimal fallback settings to prevent hang
            self.settings_items = [
                {'name': _("Quick start"), 'section': 'general', 'key': 'quick_start', 'type': 'bool'},
                {'name': _("Confirm exit"), 'section': 'general', 'key': 'confirm_exit', 'type': 'bool'}
            ]

    def get_current_element(self):
        """Get current element with caching to prevent hangs"""
        try:
            index = self.current_row * self.grid_width + self.current_col
            if not (0 <= index < len(self.settings_items)):
                return _("Empty space")
            
            item = self.settings_items[index]
            
            # Use cached setting to prevent I/O hangs
            value = self._get_cached_setting(item['key'], section=item['section'], default='false')
            
            display_name = item['name']
            if item['key'] == 'language':
                display_name += f" {_('(requires restart)')}"

            if item['type'] == 'bool':
                value_str = _('On') if str(value).lower() == 'true' else _('Off')
            else:
                value_str = str(value) if value else "Unknown"
                
            return f"{display_name}: {value_str}"
        except Exception as e:
            print(f"Error in get_current_element: {e}")
            return _("Settings item")

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
        """Activate element with comprehensive error handling"""
        try:
            index = self.current_row * self.grid_width + self.current_col
            if not (0 <= index < len(self.settings_items)):
                return

            item = self.settings_items[index]
            
            try:
                from sound import play_sound
            except ImportError:
                play_sound = lambda x: None  # Fallback
            
            if item['type'] == 'bool':
                try:
                    current_value = self._get_cached_setting(item['key'], section=item['section'], default='false').lower() == 'true'
                    new_value = str(not current_value).lower()
                    set_setting(item['key'], new_value, section=item['section'])
                    
                    # Clear cache for this setting
                    cache_key = f"{item['section']}.{item['key']}"
                    if cache_key in self._settings_cache:
                        del self._settings_cache[cache_key]

                    play_sound('core/SELECT.ogg')
                    value_text = _('On') if new_value == 'true' else _('Off')
                    self.speak(f"{item['name']}: {value_text}")
                except Exception as e:
                    print(f"Error toggling boolean setting: {e}")
                    self.speak(_("Setting change failed"))
            
            elif item['type'] == 'choice':
                try:
                    current_value = self._get_cached_setting(item['key'], section=item['section'], default='')
                    choices = item.get('choices', [])
                    if not choices:
                        self.speak(_("No choices available"))
                        return
                        
                    try:
                        current_choice_index = choices.index(current_value)
                    except ValueError:
                        current_choice_index = -1
                    
                    new_choice_index = (current_choice_index + 1) % len(choices)
                    new_value = choices[new_choice_index]
                    set_setting(item['key'], new_value, section=item['section'])
                    
                    # Clear cache for this setting
                    cache_key = f"{item['section']}.{item['key']}"
                    if cache_key in self._settings_cache:
                        del self._settings_cache[cache_key]
                    
                    if item['key'] == 'theme':
                        try:
                            set_theme(new_value)
                        except Exception as e:
                            print(f"Error setting theme: {e}")

                    play_sound('core/SELECT.ogg')
                    self.speak(f"{item['name']}: {new_value}")
                    
                except Exception as e:
                    print(f"Error changing choice setting: {e}")
                    self.speak(_("Setting change failed"))
                    
        except Exception as e:
            print(f"Critical error in activate_current_element: {e}")
            self.speak(_("Activation failed"))

def get_widget_instance(speak_func):
    """Create widget instance with timeout protection"""
    try:
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Widget initialization timeout")
        
        # Set a 10-second timeout for widget initialization
        if hasattr(signal, 'SIGALRM'):  # Unix systems
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(10)
            try:
                widget = QuickSettingsWidget(speak_func)
                signal.alarm(0)  # Cancel the alarm
                return widget
            except TimeoutError:
                print("Quick Settings widget initialization timed out")
                signal.alarm(0)
                return None
        else:
            # Windows - no timeout available, but initialization should be faster now
            return QuickSettingsWidget(speak_func)
            
    except Exception as e:
        print(f"Error creating Quick Settings widget: {e}")
        return None

def get_widget_info():
    return {
        "name": _("Quick Settings"),
        "type": "grid"
    }

