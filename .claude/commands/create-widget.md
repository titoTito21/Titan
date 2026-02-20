# Create Widget Wizard

Interactive wizard to create a new widget (applet) for TCE Launcher's invisible UI.

## What are Widgets?

Widgets (applets) are mini-applications located in `data/applets/` that provide quick access to system functions. They are used in invisible UI mode (keyboard shortcuts) and other accessible interface modes. Examples: quick settings, taskbar, desktop shortcuts.

## Process:

1. **Ask for Widget Details:**
   - Widget name in English (display name)
   - Widget name in Polish (for bilingual `applet.json`)
   - Widget ID (unique identifier, lowercase, for directory name)
   - Description (Polish and English)
   - Widget type (list, grid, button, custom)

2. **Widget Structure:**
   - Widgets are located in `data/applets/{widget_id}/`
   - Main file must be named `main.py`
   - Metadata file: `applet.json`
   - All widgets inherit from `BaseWidget` (defined locally in main.py)
   - Widgets define `get_widget_instance()` and `get_widget_info()` functions

3. **Create `applet.json`:**
   ```json
   {
       "name_pl": "{Polish name}",
       "name_en": "{English name}",
       "description_pl": "{Polish description}",
       "description_en": "{English description}",
       "version": "1.0.0",
       "author": "TCE Launcher",
       "type": "{list|grid|button|custom}"
   }
   ```

4. **Generate Widget Template (`main.py`):**
   ```python
   import os
   import sys
   import gettext

   # Add TCE root to path
   APPLET_DIR = os.path.dirname(__file__)
   TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
   if TCE_ROOT not in sys.path:
       sys.path.insert(0, TCE_ROOT)

   from src.settings.settings import get_setting, set_setting
   from src.titan_core.sound import play_sound

   # BaseWidget definition — defined locally to avoid circular imports
   class BaseWidget:
       def __init__(self, speak_func):
           self.speak = speak_func
           self.view = None
           try:
               from src.titan_core.translation import set_language
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
           """Speak with stereo positioning (-1.0 left to 1.0 right) and pitch offset"""
           self.speak(text, position=position, pitch_offset=pitch_offset)

       def get_current_element(self):
           raise NotImplementedError

       def navigate(self, direction):
           raise NotImplementedError


   # Translation setup
   try:
       applet_name = "{widget_id}"
       localedir = os.path.join(APPLET_DIR, 'languages')
       language_code = get_setting('language', 'pl')
       print(f"[{widget_id}] Loading language: '{language_code}' from '{localedir}'")

       translation = gettext.translation(applet_name, localedir, languages=[language_code], fallback=True)
       _ = translation.gettext
       print(f"[{widget_id}] Translation loaded successfully")
   except Exception as e:
       print(f"Error loading translation for {widget_id}: {e}")
       _ = gettext.gettext


   class {WidgetName}Widget(BaseWidget):
       """Main widget class"""

       def __init__(self, speak_func):
           super().__init__(speak_func)

           # Widget state
           self.current_index = 0
           self.items = []

           # Initialize widget
           self.load_items()

           # Announce widget activation
           if self.items:
               self.speak(self.get_current_element())

       def load_items(self):
           """Load widget items"""
           # Add your items here
           self.items = [
               _("Item 1"),
               _("Item 2"),
               _("Item 3")
           ]

       def get_current_element(self):
           """Get current element text with control type"""
           try:
               if not self.items or self.current_index >= len(self.items):
                   return _("Empty")

               item = self.items[self.current_index]
               control_type = self._control_types.get('list item', 'item')
               return f"{item}, {control_type}"
           except Exception as e:
               print(f"Error in get_current_element: {e}")
               return _("Error")

       def navigate(self, direction):
           """
           Navigate through widget items.

           Returns:
               tuple: (changed: bool, position: int, total: int)
               For grid widgets: (changed, current_col, grid_width)
           """
           if not self.items:
               return False, 0, 1

           old_index = self.current_index

           if direction == 'up':
               self.current_index = max(0, self.current_index - 1)
           elif direction == 'down':
               self.current_index = min(len(self.items) - 1, self.current_index + 1)
           elif direction == 'left':
               self.current_index = max(0, self.current_index - 1)
           elif direction == 'right':
               self.current_index = min(len(self.items) - 1, self.current_index + 1)

           changed = (self.current_index != old_index)
           return changed, self.current_index, len(self.items)

       def activate_current_element(self):
           """Activate/select current element"""
           try:
               if not self.items or self.current_index >= len(self.items):
                   return

               selected = self.items[self.current_index]
               play_sound('core/SELECT.ogg')
               self.speak(_("Selected: {}").format(selected))

               # Add your selection logic here

           except Exception as e:
               print(f"Error activating element: {e}")
               self.speak(_("Activation failed"))


   def get_widget_instance(speak_func):
       """
       Create and return widget instance.

       Args:
           speak_func: Function to speak text with TTS (supports position and pitch_offset kwargs)

       Returns:
           Widget instance or None on error
       """
       try:
           return {WidgetName}Widget(speak_func)
       except Exception as e:
           print(f"Error creating {widget_id} widget: {e}")
           return None


   def get_widget_info():
       """
       Get widget metadata.

       Returns:
           dict: Widget information (name, type)
       """
       return {
           "name": _("{Widget Name}"),
           "type": "list"  # Options: list, grid, button, custom
       }
   ```

5. **Optional Translation Setup:**
   - Create `languages/` directory for translations
   - `pybabel extract -o languages/{widget_id}.pot --no-default-keywords --keyword=_ data/applets/{widget_id}/main.py`
   - `pybabel init -l pl -d languages -i languages/{widget_id}.pot -D {widget_id}`
   - `pybabel compile -d data/applets/{widget_id}/languages`

6. **Widget Types:**

   - **list**: Simple list navigation (up/down)
     - Returns: `(changed, position, total)`
     - Example: Task switcher, application list

   - **grid**: 2D grid navigation (up/down/left/right)
     - Returns: `(changed, column, grid_width)`
     - Example: Quick settings (2-column), desktop shortcuts (4-column)
     - Stereo position: `(col / (cols-1) * 2.0) - 1.0`

   - **button**: Single interactive element
     - Activates immediately without entering widget mode
     - Example: Simple launcher button

   - **custom**: Custom navigation logic
     - Returns: Custom tuple based on needs

7. **Integration with InvisibleUI:**

   Widget auto-loads from `data/applets/{widget_id}/` if it has both `main.py` and `applet.json`. No registration needed.

   Loading priority:
   1. Modern format: `applet.json` + `main.py` (preferred)
   2. Legacy format: `init.py` only

8. **Test Widget:**
   - Restart TCE Launcher
   - Activate widget through invisible UI
   - Test navigation (up/down/left/right)
   - Test selection (enter)
   - Test exit (escape)
   - Verify TTS announcements
   - Verify sound effects

## Widget Best Practices:

1. **Always provide audio feedback** - Clear announcements for all actions
2. **Use stereo positioning** for grid widgets - left/right based on column
3. **Cache items and settings** - Prevent I/O hangs during navigation
4. **Handle empty state** - Return "Empty" gracefully
5. **Thread-safe operations** - Use proper locking for shared resources
6. **Translation support** - Use gettext for all user-facing strings

## Reference Examples:

- **quick_settings** (`data/applets/quick_settings/main.py`): Settings grid
  - 2-column grid navigation
  - Boolean toggles and choice cycling
  - Settings cache to prevent I/O hangs
  - Full translation support

- **taskbar** (`data/applets/taskbar/main.py`): Application taskbar
  - List-based window enumeration
  - Context menu for Activate/Close/Minimize
  - `CrossPlatformWindowManager` integration

- **pulpit systemowy** (`data/applets/pulpit systemowy/main.py`): Desktop shortcuts
  - 4-column grid scanning Windows Desktop .lnk files
  - Launches shortcuts on activation

## Required Functions:

Widgets MUST define:
- `get_widget_instance(speak_func)` - Create widget instance (required)
- `get_widget_info()` - Return widget metadata with `name` and `type` (required)

Widget class MUST implement:
- `__init__(self, speak_func)` - Initialize widget
- `get_current_element(self)` - Get current element text
- `navigate(self, direction)` - Handle navigation, return `(changed, pos, total)`
- `activate_current_element(self)` - Handle selection (optional)

## Complete Code Examples

### Example 1: Quick Launcher Widget (List Type)

A widget that shows a configurable list of quick-launch applications. Users navigate with Up/Down arrows, press Enter to launch.

**File: `data/applets/quick_launcher/applet.json`**
```json
{
    "name_pl": "Szybki launcher",
    "name_en": "Quick Launcher",
    "description_pl": "Szybkie uruchamianie ulubionych aplikacji",
    "description_en": "Quick launch your favorite applications",
    "version": "1.0.0",
    "author": "TCE Launcher",
    "type": "list"
}
```

**File: `data/applets/quick_launcher/main.py`**
```python
import os
import sys
import subprocess
import gettext

# Add TCE root to path
APPLET_DIR = os.path.dirname(__file__)
TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

from src.settings.settings import get_setting, set_setting
from src.titan_core.sound import play_sound

# BaseWidget definition — defined locally to avoid circular imports
class BaseWidget:
    def __init__(self, speak_func):
        self.speak = speak_func
        self.view = None
        try:
            from src.titan_core.translation import set_language
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
        """Speak with stereo positioning (-1.0 left to 1.0 right) and pitch offset"""
        self.speak(text, position=position, pitch_offset=pitch_offset)

    def get_current_element(self):
        raise NotImplementedError

    def navigate(self, direction):
        raise NotImplementedError


# Translation setup
try:
    applet_name = "quick_launcher"
    localedir = os.path.join(APPLET_DIR, 'languages')
    language_code = get_setting('language', 'pl')
    print(f"[quick_launcher] Loading language: '{language_code}' from '{localedir}'")

    translation = gettext.translation(applet_name, localedir, languages=[language_code], fallback=True)
    _ = translation.gettext
    print(f"[quick_launcher] Translation loaded successfully")
except Exception as e:
    print(f"Error loading translation for quick_launcher: {e}")
    _ = gettext.gettext


# Application definitions: (display_name, launch_target)
# launch_target can be an executable name, full path, or shell command
DEFAULT_APPS = [
    (_("Notepad"), "notepad.exe"),
    (_("Calculator"), "calc.exe"),
    (_("Web Browser"), "https://www.google.com"),
    (_("File Explorer"), "explorer.exe"),
    (_("Command Prompt"), "cmd.exe"),
    (_("Task Manager"), "taskmgr.exe"),
]


class QuickLauncherWidget(BaseWidget):
    """A list widget for quickly launching applications."""

    def __init__(self, speak_func):
        super().__init__(speak_func)

        self.current_index = 0
        self.items = []

        # Load items
        self.load_items()

        # Announce first item on activation
        if self.items:
            self.speak(self.get_current_element())

    def load_items(self):
        """Load the list of launchable applications."""
        self.items = []
        for display_name, target in DEFAULT_APPS:
            self.items.append({
                'name': display_name,
                'target': target
            })

    def get_current_element(self):
        """Get current element text with control type annotation."""
        try:
            if not self.items or self.current_index >= len(self.items):
                return _("Empty")

            item = self.items[self.current_index]
            control_type = self._control_types.get('list item', 'item')
            return f"{item['name']}, {control_type}"
        except Exception as e:
            print(f"Error in get_current_element: {e}")
            return _("Error")

    def navigate(self, direction):
        """
        Navigate through the application list.

        Args:
            direction: 'up', 'down', 'left', or 'right'

        Returns:
            tuple: (changed: bool, position: int, total: int)
        """
        if not self.items:
            return False, 0, 1

        old_index = self.current_index

        if direction in ('up', 'left'):
            self.current_index = max(0, self.current_index - 1)
        elif direction in ('down', 'right'):
            self.current_index = min(len(self.items) - 1, self.current_index + 1)

        changed = (self.current_index != old_index)
        if changed:
            play_sound('core/SELECT.ogg')
        return changed, self.current_index, len(self.items)

    def activate_current_element(self):
        """Launch the currently selected application."""
        try:
            if not self.items or self.current_index >= len(self.items):
                return

            item = self.items[self.current_index]
            target = item['target']

            play_sound('core/SELECT.ogg')
            self.speak(_("Launching: {}").format(item['name']))

            # Determine how to launch the target
            if target.startswith("http://") or target.startswith("https://"):
                # Open URL in default browser
                os.startfile(target)
            elif os.path.isabs(target) and os.path.exists(target):
                # Launch by absolute path
                subprocess.Popen([target], shell=False)
            else:
                # Launch by executable name (relies on PATH)
                try:
                    os.startfile(target)
                except OSError:
                    subprocess.Popen(target, shell=True)

        except Exception as e:
            print(f"Error launching application: {e}")
            self.speak(_("Failed to launch application"))


def get_widget_instance(speak_func):
    """
    Create and return widget instance.

    Args:
        speak_func: Function to speak text with TTS (supports position and pitch_offset kwargs)

    Returns:
        Widget instance or None on error
    """
    try:
        return QuickLauncherWidget(speak_func)
    except Exception as e:
        print(f"Error creating quick_launcher widget: {e}")
        return None


def get_widget_info():
    """
    Get widget metadata.

    Returns:
        dict: Widget information (name, type)
    """
    return {
        "name": _("Quick Launcher"),
        "type": "list"
    }
```

---

### Example 2: Volume Control Widget (Grid Type)

A 2-column grid widget for audio settings. Navigate rows with Up/Down, change values with Left/Right or Enter. Settings persist via `get_setting`/`set_setting`.

**File: `data/applets/volume_control/applet.json`**
```json
{
    "name_pl": "Kontrola dzwieku",
    "name_en": "Volume Control",
    "description_pl": "Ustawienia glosnosci i dzwieku",
    "description_en": "Volume and audio settings",
    "version": "1.0.0",
    "author": "TCE Launcher",
    "type": "grid"
}
```

**File: `data/applets/volume_control/main.py`**
```python
import os
import sys
import gettext

# Add TCE root to path
APPLET_DIR = os.path.dirname(__file__)
TCE_ROOT = os.path.abspath(os.path.join(APPLET_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

from src.settings.settings import get_setting, set_setting
from src.titan_core.sound import play_sound

# BaseWidget definition — defined locally to avoid circular imports
class BaseWidget:
    def __init__(self, speak_func):
        self.speak = speak_func
        self.view = None
        try:
            from src.titan_core.translation import set_language
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
        """Speak with stereo positioning (-1.0 left to 1.0 right) and pitch offset"""
        self.speak(text, position=position, pitch_offset=pitch_offset)

    def get_current_element(self):
        raise NotImplementedError

    def navigate(self, direction):
        raise NotImplementedError


# Translation setup
try:
    applet_name = "volume_control"
    localedir = os.path.join(APPLET_DIR, 'languages')
    language_code = get_setting('language', 'pl')
    print(f"[volume_control] Loading language: '{language_code}' from '{localedir}'")

    translation = gettext.translation(applet_name, localedir, languages=[language_code], fallback=True)
    _ = translation.gettext
    print(f"[volume_control] Translation loaded successfully")
except Exception as e:
    print(f"Error loading translation for volume_control: {e}")
    _ = gettext.gettext


# Volume step size for slider adjustments
VOLUME_STEP = 5


class VolumeControlWidget(BaseWidget):
    """A grid widget for controlling audio settings."""

    def __init__(self, speak_func):
        super().__init__(speak_func)

        self.current_row = 0
        self.current_col = 0
        self.grid_width = 2  # 2 columns: label | value

        self._settings_cache = {}
        self._build_rows()

        # Announce first item on activation
        self.speak(self.get_current_element())

    def _build_rows(self):
        """Define the grid rows. Each row is a setting with name, key, type, and options."""
        self.rows = [
            {
                'name': _("Master Volume"),
                'section': 'sound',
                'key': 'master_volume',
                'type': 'slider',
                'min': 0,
                'max': 100,
                'step': VOLUME_STEP,
                'default': '100',
                'unit': '%'
            },
            {
                'name': _("TTS Volume"),
                'section': 'sound',
                'key': 'tts_volume',
                'type': 'slider',
                'min': 0,
                'max': 100,
                'step': VOLUME_STEP,
                'default': '100',
                'unit': '%'
            },
            {
                'name': _("Sound Effects"),
                'section': 'sound',
                'key': 'sound_effects_enabled',
                'type': 'bool',
                'default': 'true'
            },
            {
                'name': _("TTS Speed"),
                'section': 'sound',
                'key': 'tts_speed',
                'type': 'choice',
                'choices': [_("Slow"), _("Normal"), _("Fast")],
                'values': ['slow', 'normal', 'fast'],
                'default': 'normal'
            },
        ]

    def _get_cached_setting(self, key, section='sound', default=None):
        """Get setting with caching to prevent I/O hangs during navigation."""
        import time
        cache_key = f"{section}.{key}"
        if cache_key not in self._settings_cache:
            try:
                self._settings_cache[cache_key] = get_setting(key, default=default, section=section)
            except Exception:
                self._settings_cache[cache_key] = default
        return self._settings_cache[cache_key]

    def _invalidate_cache(self, key, section='sound'):
        """Remove a specific key from the cache after changing it."""
        cache_key = f"{section}.{key}"
        if cache_key in self._settings_cache:
            del self._settings_cache[cache_key]

    def _get_display_value(self, row):
        """Get the human-readable display value for a row."""
        raw = self._get_cached_setting(row['key'], section=row['section'], default=row['default'])

        if row['type'] == 'slider':
            try:
                val = int(raw)
            except (TypeError, ValueError):
                val = int(row['default'])
            return f"{val}{row.get('unit', '')}"

        elif row['type'] == 'bool':
            return _("On") if str(raw).lower() == 'true' else _("Off")

        elif row['type'] == 'choice':
            values = row.get('values', [])
            choices = row.get('choices', [])
            raw_str = str(raw)
            if raw_str in values:
                idx = values.index(raw_str)
                return choices[idx] if idx < len(choices) else raw_str
            return raw_str

        return str(raw)

    def _get_control_type_label(self, row):
        """Get the accessibility control type label for a row."""
        if row['type'] == 'slider':
            return self._control_types.get('slider', 'slider')
        elif row['type'] == 'bool':
            return self._control_types.get('checkbox', 'checkbox')
        elif row['type'] == 'choice':
            return self._control_types.get('list item', 'list item')
        return ''

    def get_current_element(self):
        """Get current element text with control type and value."""
        try:
            if self.current_row >= len(self.rows):
                return _("Empty")

            row = self.rows[self.current_row]
            value_str = self._get_display_value(row)
            control_type = self._get_control_type_label(row)

            if self.current_col == 0:
                # Label column
                return f"{row['name']}: {value_str}, {control_type}"
            else:
                # Value column
                return f"{value_str}, {control_type}"
        except Exception as e:
            print(f"Error in get_current_element: {e}")
            return _("Error")

    def navigate(self, direction):
        """
        Navigate the 2-column grid.
        Up/Down moves between rows. Left/Right moves between columns
        and adjusts slider/choice values when on the value column.

        Returns:
            tuple: (changed: bool, current_col: int, grid_width: int)
        """
        if not self.rows:
            return False, 0, self.grid_width

        old_row, old_col = self.current_row, self.current_col

        if direction == 'up':
            self.current_row = max(0, self.current_row - 1)
        elif direction == 'down':
            self.current_row = min(len(self.rows) - 1, self.current_row + 1)
        elif direction == 'left':
            if self.current_col > 0:
                self.current_col -= 1
            else:
                # On left column, try adjusting the value downward
                self._adjust_value(-1)
        elif direction == 'right':
            if self.current_col < self.grid_width - 1:
                self.current_col += 1
            else:
                # On right column, try adjusting the value upward
                self._adjust_value(1)

        changed = (self.current_row != old_row) or (self.current_col != old_col)
        if changed:
            play_sound('core/SELECT.ogg')

        # Stereo position based on column: col 0 = left (-1.0), col 1 = right (1.0)
        if self.grid_width > 1:
            stereo = (self.current_col / (self.grid_width - 1) * 2.0) - 1.0
        else:
            stereo = 0.0

        return changed, self.current_col, self.grid_width

    def _adjust_value(self, step_direction):
        """
        Adjust the value of the current row's setting.

        Args:
            step_direction: +1 to increase / next, -1 to decrease / previous
        """
        if self.current_row >= len(self.rows):
            return

        row = self.rows[self.current_row]

        if row['type'] == 'slider':
            raw = self._get_cached_setting(row['key'], section=row['section'], default=row['default'])
            try:
                current_val = int(raw)
            except (TypeError, ValueError):
                current_val = int(row['default'])

            new_val = current_val + (row['step'] * step_direction)
            new_val = max(row['min'], min(row['max'], new_val))

            if new_val != current_val:
                set_setting(row['key'], str(new_val), section=row['section'])
                self._invalidate_cache(row['key'], section=row['section'])
                play_sound('core/SELECT.ogg')
                self.speak(f"{row['name']}: {new_val}{row.get('unit', '')}")

        elif row['type'] == 'bool':
            raw = self._get_cached_setting(row['key'], section=row['section'], default=row['default'])
            current_bool = str(raw).lower() == 'true'
            new_bool = not current_bool
            set_setting(row['key'], str(new_bool).lower(), section=row['section'])
            self._invalidate_cache(row['key'], section=row['section'])
            play_sound('core/SELECT.ogg')
            value_text = _("On") if new_bool else _("Off")
            self.speak(f"{row['name']}: {value_text}")

        elif row['type'] == 'choice':
            raw = self._get_cached_setting(row['key'], section=row['section'], default=row['default'])
            values = row.get('values', [])
            choices = row.get('choices', [])
            if not values:
                return

            try:
                current_idx = values.index(str(raw))
            except ValueError:
                current_idx = 0

            new_idx = (current_idx + step_direction) % len(values)
            new_value = values[new_idx]
            set_setting(row['key'], new_value, section=row['section'])
            self._invalidate_cache(row['key'], section=row['section'])
            play_sound('core/SELECT.ogg')
            display = choices[new_idx] if new_idx < len(choices) else new_value
            self.speak(f"{row['name']}: {display}")

    def activate_current_element(self):
        """Toggle or cycle the current setting when Enter is pressed."""
        try:
            if self.current_row >= len(self.rows):
                return

            row = self.rows[self.current_row]

            if row['type'] == 'bool':
                self._adjust_value(1)  # Toggle
            elif row['type'] == 'choice':
                self._adjust_value(1)  # Cycle to next
            elif row['type'] == 'slider':
                # Announce current value on Enter
                value_str = self._get_display_value(row)
                self.speak(f"{row['name']}: {value_str}")
        except Exception as e:
            print(f"Error in activate_current_element: {e}")
            self.speak(_("Activation failed"))


def get_widget_instance(speak_func):
    """
    Create and return widget instance.

    Args:
        speak_func: Function to speak text with TTS (supports position and pitch_offset kwargs)

    Returns:
        Widget instance or None on error
    """
    try:
        return VolumeControlWidget(speak_func)
    except Exception as e:
        print(f"Error creating volume_control widget: {e}")
        return None


def get_widget_info():
    """
    Get widget metadata.

    Returns:
        dict: Widget information (name, type)
    """
    return {
        "name": _("Volume Control"),
        "type": "grid"
    }
```

## Multiplatform Requirements

All TCE widgets MUST work on **Windows, macOS, and Linux**. Follow these rules:

### accessible_output3 — always try/except
```python
try:
    import accessible_output3.outputs.auto as _ao3
    _ao3_speaker = _ao3.Auto()
except Exception:
    _ao3_speaker = None
```

### TTS fallback (when no screen reader is running)
```python
import platform, subprocess

def speak(text):
    if _ao3_speaker:
        try:
            _ao3_speaker.speak(text, interrupt=True)
            return
        except Exception:
            pass
    p = platform.system()
    try:
        if p == 'Windows':
            import win32com.client
            win32com.client.Dispatch("SAPI.SpVoice").Speak(text)
        elif p == 'Darwin':
            subprocess.Popen(['say', text])
        else:
            subprocess.Popen(['spd-say', text])
    except Exception:
        pass
```

### Opening files/URLs (cross-platform)
```python
import sys, subprocess
if sys.platform == 'win32':
    os.startfile(path)           # Windows only
elif sys.platform == 'darwin':
    subprocess.Popen(['open', path])
else:
    subprocess.Popen(['xdg-open', path])
```

### Config/data directory (cross-platform)
```python
import platform, os

def get_config_dir(app_name):
    p = platform.system()
    if p == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
    elif p == 'Darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'Titosoft', 'Titan', app_name)
```

### Platform-specific paths
```python
import sys, os
# Desktop shortcuts: Windows=.lnk, macOS=.app, Linux=any file
if sys.platform == 'win32':
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    public_desktop = os.environ.get('PUBLIC', '')
    if public_desktop:
        public_desktop = os.path.join(public_desktop, 'Desktop')
elif sys.platform == 'darwin':
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
else:
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
```

### Common mistakes to avoid
- `os.environ['APPDATA']` → use `os.getenv('APPDATA') or os.path.expanduser('~')` (KeyError on Linux/macOS)
- `os.environ['USERPROFILE']` → use `os.path.expanduser('~')` (works on all platforms)
- `os.environ['PUBLIC']` → use `os.environ.get('PUBLIC', '')` (only exists on Windows)
- `os.sys.platform` → **AttributeError!** Use `sys.platform` (after `import sys`)
- `os.system(cmd)` → use `subprocess.Popen(...)` (safer, cross-platform)
- `os.startfile(path)` → Windows only, always use the platform check above
- `os.path.expanduser("~\\Documents")` → use `os.path.join(os.path.expanduser('~'), 'Documents')` (cross-platform)

## Action:

Ask the user for widget details and create a complete, working widget following the current TCE standard.
