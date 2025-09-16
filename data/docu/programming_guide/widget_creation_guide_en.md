# Titan Widget Creation Guide

## Introduction

Titan widgets are interactive components available in the invisible interface that allow programmers to create custom functionality. The system supports two types of widgets: **button** (simple action) and **grid** (navigable interface).

## Widget System Architecture

### Widget Location
All widgets are located in the `data/applets/` directory. Each widget is a separate directory containing:
- `main.py` or `init.py` - main file with widget code
- `applet.json` (optional) - widget metadata in the new system

### BaseWidget Class

Titan provides a base class `BaseWidget` in `invisibleui.py`:

```python
class BaseWidget:
    def __init__(self, speak_func):
        self.speak = speak_func
        self.view = None
    
    def speak_with_position(self, text, position=0.0, pitch_offset=0):
        """Speaks text with stereo positioning"""
        self.speak(text, position=position, pitch_offset=pitch_offset)
    
    def set_border(self):
        """Sets widget border (for GUI)"""
        pass
    
    def get_current_element(self):
        """Returns description of current element - REQUIRED"""
        raise NotImplementedError
    
    def navigate(self, direction):
        """Navigation within widget - REQUIRED for 'grid' type"""
        raise NotImplementedError
    
    def activate_current_element(self):
        """Activates current element - REQUIRED"""
        raise NotImplementedError
```

## Widget Types

### 1. "button" Type Widget

Simple single-use widget that performs an action when activated.

**Implementation example:**
```python
class WidgetButton:
    def __init__(self, speak_func, view=None):
        self.speak = speak_func
        self.view = view

    def activate_current_element(self):
        """Activates the widget"""
        self.speak("Example button activated!")
        # Perform action
        
    def get_current_element(self):
        """Returns button name"""
        return "Example Button"

def get_widget_info():
    return {
        "name": "My Button",
        "type": "button",
    }

def get_widget_instance(speak_func, view=None):
    return WidgetButton(speak_func, view)
```

### 2. "grid" Type Widget

Interactive widget allowing navigation in multiple directions.

**Implementation example:**
```python
from invisibleui import BaseWidget

class WidgetGrid(BaseWidget):
    def __init__(self, speak_func, view=None):
        super().__init__(speak_func)
        self.view = view
        self.grid = [
            ["Top-Left", "Top-Right"],
            ["Bottom-Left", "Bottom-Right"]
        ]
        self.current_pos = [0, 0]  # [row, column]

    def navigate(self, direction):
        """Grid navigation"""
        rows = len(self.grid)
        cols = len(self.grid[0]) if self.grid else 1
        old_pos = self.current_pos[:]
        
        if direction == 'up' and self.current_pos[0] > 0:
            self.current_pos[0] -= 1
        elif direction == 'down' and self.current_pos[0] < rows - 1:
            self.current_pos[0] += 1
        elif direction == 'left' and self.current_pos[1] > 0:
            self.current_pos[1] -= 1
        elif direction == 'right' and self.current_pos[1] < cols - 1:
            self.current_pos[1] += 1
        else:
            return False, self.current_pos[1], cols  # Edge reached
        
        # Return success and position for stereo positioning
        return True, self.current_pos[1], cols

    def activate_current_element(self):
        """Activates current element"""
        element = self.get_current_element()
        
        # Use stereo positioning
        cols = len(self.grid[0]) if self.grid else 1
        position = (self.current_pos[1] / (cols - 1) * 2.0) - 1.0 if cols > 1 else 0.0
        
        self.speak_with_position(f"Activated: {element}", position=position)
        
    def get_current_element(self):
        """Returns current element"""
        return self.grid[self.current_pos[0]][self.current_pos[1]]

def get_widget_info():
    return {
        "name": "Example Grid",
        "type": "grid",
    }

def get_widget_instance(speak_func, view=None):
    return WidgetGrid(speak_func, view)
```

## Widget Metadata (applet.json)

The new system allows defining metadata in `applet.json`:

```json
{
    "name_pl": "Mój widget",
    "name_en": "My Widget", 
    "description_pl": "Opis widgetu po polsku",
    "description_en": "Widget description in English",
    "version": "1.0.0",
    "author": "Your Name",
    "type": "grid"
}
```

## Stereo Positioning Features

### speak_with_position()
By inheriting from `BaseWidget`, you get access to the `speak_with_position()` method:

```python
self.speak_with_position(text, position=0.0, pitch_offset=0)
```

**Parameters:**
- `text` - text to speak
- `position` - stereo position: -1.0 (left) to 1.0 (right), 0.0 = center  
- `pitch_offset` - pitch change: -10 to +10

### Automatic Positioning

The system automatically positions speech based on values returned from `navigate()`:
- Left/right navigation uses stereo positioning
- Up/down navigation uses pitch change

## Required Methods

### get_widget_info()
**Required function** at module level:
```python
def get_widget_info():
    return {
        "name": "Widget Name",
        "type": "button" # or "grid"
    }
```

### get_widget_instance()
**Required function** at module level:
```python
def get_widget_instance(speak_func, view=None):
    return MyWidget(speak_func, view)
```

### get_current_element()
**Required method** of widget class - returns description of current element.

### activate_current_element()
**Required method** of widget class - performs activation action.

### navigate() (only for "grid" type)
**Required method** for "grid" type widgets:
```python
def navigate(self, direction):
    # direction: 'up', 'down', 'left', 'right'
    # Return: (success, horizontal_index, total_horizontal_items)
    return True, current_column, total_columns
```

## Directory Structure

### Legacy system (init.py)
```
data/applets/my_widget/
├── init.py              # Main widget file
```

### New system (main.py + applet.json)
```
data/applets/my_widget/
├── main.py              # Main widget file
├── applet.json          # Widget metadata
├── babel.cfg            # Translation config (optional)
└── languages/           # Translations (optional)
    ├── messages.pot
    ├── pl/
    └── en/
```

## Internationalization

### Adding Translations

1. Create `babel.cfg`:
```ini
[python: **.py]
```

2. Use `_()` function in code:
```python
import gettext
import os

# Setup translations
domain = 'my_widget'
localedir = os.path.join(os.path.dirname(__file__), 'languages')
try:
    translation = gettext.translation(domain, localedir, fallback=True)
    _ = translation.gettext
except Exception:
    _ = lambda x: x

# In code
self.speak(_("Text to translate"))
```

3. Extract texts for translation:
```bash
pybabel extract -o messages.pot --input-dirs=.
```

4. Create translation files:
```bash
pybabel init -l pl -d languages -i messages.pot
pybabel init -l en -d languages -i messages.pot
```

5. Compile translations:
```bash
pybabel compile -d languages
```

## Practical Examples

### Example 1: Clock Widget
```python
import datetime
from invisibleui import BaseWidget

class ClockWidget(BaseWidget):
    def __init__(self, speak_func, view=None):
        super().__init__(speak_func)
        self.view = view
        
    def get_current_element(self):
        now = datetime.datetime.now()
        return f"Current time: {now.strftime('%H:%M:%S')}"
        
    def activate_current_element(self):
        self.speak(self.get_current_element())

def get_widget_info():
    return {"name": "Clock", "type": "button"}

def get_widget_instance(speak_func, view=None):
    return ClockWidget(speak_func, view)
```

### Example 2: Simple Calculator Widget
```python
from invisibleui import BaseWidget

class SimpleCalculator(BaseWidget):
    def __init__(self, speak_func, view=None):
        super().__init__(speak_func)
        self.view = view
        self.operations = [
            ["1 + 1 = 2", "2 + 2 = 4", "3 + 3 = 6"],
            ["5 * 5 = 25", "10 / 2 = 5", "2^3 = 8"]
        ]
        self.current_pos = [0, 0]
        
    def navigate(self, direction):
        rows = len(self.operations)
        cols = len(self.operations[0])
        
        if direction == 'up' and self.current_pos[0] > 0:
            self.current_pos[0] -= 1
        elif direction == 'down' and self.current_pos[0] < rows - 1:
            self.current_pos[0] += 1
        elif direction == 'left' and self.current_pos[1] > 0:
            self.current_pos[1] -= 1
        elif direction == 'right' and self.current_pos[1] < cols - 1:
            self.current_pos[1] += 1
        else:
            return False, self.current_pos[1], cols
        
        return True, self.current_pos[1], cols
        
    def get_current_element(self):
        return self.operations[self.current_pos[0]][self.current_pos[1]]
        
    def activate_current_element(self):
        element = self.get_current_element()
        self.speak(f"Selected example: {element}")

def get_widget_info():
    return {"name": "Simple Calculator", "type": "grid"}

def get_widget_instance(speak_func, view=None):
    return SimpleCalculator(speak_func, view)
```

## Testing Widgets

1. Place widget in `data/applets/widget_name/` directory
2. Start Titan
3. Enter invisible interface (Ctrl+Shift+arrows)
4. Navigate to "Widgets" category
5. Select your widget and test functionality

## Important Guidelines

1. **DO NOT** use `self.speak()` in the `navigate()` method - the system automatically handles speech with positioning
2. Use `speak_with_position()` in `activate_current_element()` for better experience
3. Always implement all required methods
4. Test navigation in all directions
5. Add error handling for invalid data
6. Use internationalization for better accessibility

## Available Tools

- `self.speak()` - basic TTS speech
- `self.speak_with_position()` - speech with stereo positioning
- `play_sound()` - play sounds (import from `sound`)
- Settings system (import from `settings`)
- Access to main application frame through `self.view`

Titan provides a rich API for creating custom, accessible widgets with full support for screen reader users.