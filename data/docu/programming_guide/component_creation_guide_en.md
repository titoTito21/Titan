# Titan Component Creation Guide

## Introduction

Titan components are system extensions that run in the background and can add functionality to the main application. Components can be enabled/disabled by users, integrate with the system menu, add custom views to the main interface, and extend the invisible UI and Klango mode.

## Component System Architecture

### Component Location
All components are located in the `data/components/` directory. Each component is a separate directory containing:
- `init.py` - main file with component code (NOT `__init__.py`!)
- `__component__.TCE` - component configuration file (INI format)

### Component Lifecycle

1. **Loading** - components are loaded at Titan startup
2. **Initialization** - `initialize(app)` method is called
3. **Operation** - component runs in the background
4. **Shutdown** - `shutdown()` method is called

## Configuration File Structure

### __component__.TCE
INI file with `[component]` section:

```ini
[component]
name = Component Name
status = 1

```

**Parameters:**
- `name` - name displayed in component manager
- **`status = 1` means DISABLED, `status = 0` means ENABLED** (inverted!)
- `libs` (optional) - comma-separated dirs under the component folder added
  to `sys.path` before loading (default `lib`), so the component can vendor
  its own third-party dependencies (native DLLs, bundled Python packages)
- **IMPORTANT**: File name is `__component__.TCE` (uppercase .TCE)
- **IMPORTANT**: Main file is `init.py` (lowercase, NOT `__init__.py`)
- **IMPORTANT**: Add blank line at end of file

## Component Implementation

### Basic init.py structure

```python
# -*- coding: utf-8 -*-
"""
Component name - description
"""

import os
import sys
import wx
import gettext

# Add the component directory to the path
COMPONENT_DIR = os.path.dirname(__file__)
if COMPONENT_DIR not in sys.path:
    sys.path.insert(0, COMPONENT_DIR)

# Add the TCE root directory to the path
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# Import TCE modules
try:
    from src.titan_core.sound import play_sound
    SOUND_AVAILABLE = True
except ImportError as e:
    SOUND_AVAILABLE = False
    print(f"[component_id] Warning: sound module not available: {e}")

try:
    from src.settings.settings import get_setting
    SETTINGS_AVAILABLE = True
except ImportError as e:
    SETTINGS_AVAILABLE = False
    print(f"[component_id] Warning: settings module not available: {e}")
    def get_setting(key, default='', section='general'):
        return default

# Translation support
LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')

try:
    if SETTINGS_AVAILABLE:
        lang = get_setting('language', 'pl')
    else:
        lang = 'pl'

    translation = gettext.translation('component_id', localedir=LANGUAGES_DIR, languages=[lang], fallback=True)
    translation.install()
    _ = translation.gettext
except Exception as e:
    print(f"[component_id] Translation loading failed: {e}")
    def _(text):
        return text


class MyComponent:
    """Main component class"""

    def __init__(self):
        """Initialize the component"""
        self._ = _
        print(f"[component_id] Component initialized")

    def enable(self):
        """Enable component functionality"""
        try:
            # Add component logic here
            if SOUND_AVAILABLE:
                play_sound('ui/dialog.ogg')
            print(f"[component_id] Component enabled")
            return True
        except Exception as e:
            print(f"[component_id] Error enabling component: {e}")
            return False

    def disable(self):
        """Disable component functionality"""
        try:
            # Add cleanup logic here
            if SOUND_AVAILABLE:
                play_sound('ui/dialogclose.ogg')
            print(f"[component_id] Component disabled")
        except Exception as e:
            print(f"[component_id] Error disabling component: {e}")


# Global component instance
_component_instance = None


def get_component():
    """Get the global component instance"""
    global _component_instance
    if _component_instance is None:
        _component_instance = MyComponent()
    return _component_instance


def initialize(app=None):
    """Component initialization - called by ComponentManager"""
    try:
        print(f"[component_id] Initializing component...")
        component = get_component()
        # Add initialization logic here
        print(f"[component_id] Component initialized successfully")
    except Exception as e:
        print(f"[component_id] Error during initialization: {e}")
        import traceback
        traceback.print_exc()


def shutdown():
    """Component shutdown - called by ComponentManager"""
    global _component_instance
    try:
        print(f"[component_id] Shutting down component...")
        if _component_instance:
            _component_instance.disable()
            _component_instance = None
        print(f"[component_id] Component shutdown complete")
    except Exception as e:
        print(f"[component_id] Error during shutdown: {e}")
        import traceback
        traceback.print_exc()
```

## Component Interface

All of the functions below are optional — the component manager checks
with `hasattr()` before calling any of them, `initialize` included, so a
component missing one simply skips that step rather than failing to load.

#### initialize(app=None)
Called at Titan startup, if defined:
- `app` - wxPython main application instance (may be None)
- Use for initializing resources, starting threads

#### shutdown()
Called at Titan shutdown:
- Stop threads, free resources
- Save component state if needed

#### add_menu(component_manager)
Adds items to component menu:
- `component_manager.register_menu_function(name, function)`
- Menu available in invisible UI and GUI menu

#### add_settings_category(component_manager)
**Recommended**: Registers settings category in modular settings system:
```python
def add_settings_category(component_manager):
    def build_panel(parent):
        panel = wx.Panel(parent)
        # ... add controls ...
        return panel

    component_manager.register_settings_category(
        "My Component",
        build_panel,
        save_callback,
        load_callback
    )
```

## Hooks System

### GUI Hooks (get_gui_hooks)

Component can register hooks to main GUI:

```python
def get_gui_hooks():
    """Return GUI hooks dict (optional)

    Available hooks:
        'on_gui_init': called with gui_app (TitanApp wx.Frame) when GUI is initialized
    """
    return {
        'on_gui_init': on_gui_init
    }

def on_gui_init(gui_app):
    """Hook called when GUI is initialized"""
    # Here you can register a view in the main panel
    pass
```

### Invisible UI Hooks (get_iui_hooks)

Component can add custom categories to invisible UI:

```python
def get_iui_hooks():
    """Return Invisible UI hooks dict (optional)

    Available hooks:
        'on_iui_init': called with iui (InvisibleUI) after build_structure()
    """
    return {
        'on_iui_init': on_iui_init
    }

def on_iui_init(iui):
    """Hook called when Invisible UI is initialized"""
    iui.categories.append({
        "name": "My Component",
        "sound": "core/focus.ogg",
        "elements": ["Action 1", "Action 2"],
        "action": lambda name: handle_action(name)
    })
```

### Klango Mode Hooks (get_klango_hooks)

Component can integrate with Klango mode:

```python
def get_klango_hooks():
    """Return Klango mode hooks dict (optional)

    Available hooks:
        'on_klango_init': called with klango_mode (KlangoMode) when Klango mode starts
    """
    return {
        'on_klango_init': on_klango_init
    }
```

### Launcher Hooks (get_launcher_hooks)

Component can hook into alternative-launcher startup:

```python
def get_launcher_hooks():
    """Return launcher hooks dict (optional)

    Available hooks:
        'on_launcher_init': called with (launcher_manager, launcher_name)
        when an alternative launcher starts
    """
    return {
        'on_launcher_init': on_launcher_init
    }

def on_launcher_init(launcher_manager, launcher_name):
    """Hook called when an alternative launcher (see the Launcher Creation
    Guide) starts up"""
    pass
```

## Buffer System API (Automatically Injected)

The component manager injects a module-level `buffers` object (bound to
your component name) into your `init.py`'s namespace before it runs. It
feeds the Titan Buffer System — the shared, audio-game-style review of
recent messages/notifications navigated identically from the GUI, Klango
mode, and the tilde Titan UI overlay. Use it if your component produces a
stream of items the user might want to review (feed posts, alerts,
incoming events, etc.):

```python
# `buffers` is injected as a module global. For standalone testing (running
# init.py directly) fall back to creating one:
try:
    buffers
except NameError:
    from src.buffers import buffer_bus
    buffers = buffer_bus.make_module_api("mycomponent")

buffers.register_category("My Component")            # optional nice name
buffers.ensure_buffer("events", "Events", kind="notification")

# Push each new item as it arrives (thread-safe, never raises):
buffers.push("events", text, author=source_name)
```

`kind` is a hint (`'message'` | `'private'` | `'notification'`). `push()`
returns `True` when the item landed in the buffer the user is currently
reviewing (Titan plays a quiet ping); background buffers stay silent. Skip
this entirely if your component does not produce reviewable items.

Note: this injection is reliable in the frozen `.pyc`-via-importlib load
path and in development mode. One frozen-build path (a component shipped
as a raw `.py` with no compiled `.pyc` next to it) loads via `exec()` and
does NOT get `buffers` injected — always use the `except NameError`
fallback shown above rather than assuming the module global exists.

## Component View Registration API

Components can add custom tabs/views to the main GUI left panel. Registered views appear in the virtual tab bar (first row of the list) and Ctrl+Tab cycle alongside built-in views (Application List, Game List, Titan IM).

### register_view() Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `view_id` | str | Yes | Unique identifier, e.g. `'my_notes'` |
| `label` | str | Yes | Header text shown above control, e.g. `'My Notes:'` |
| `control` | wx.Window | Yes | Any wx control (ListBox, TreeCtrl, etc.), parent: `gui_app.main_panel` |
| `on_show` | callable | No | Called every time view becomes visible (refresh data) |
| `on_activate` | callable | No | Called when user presses Enter on control |
| `position` | str/int | No | Position in cycle: `'after_apps'`, `'after_games'`, `'after_network'` (default), or integer index |
| `short_name` | str | No | Short label used for the tab bar row and toolbar button (defaults to `label` with trailing colon stripped) |

### How it works

- Registered control is added to the left panel sizer (hidden by default).
- The first row of the list (item 0) is a **virtual tab bar** auto-injected by `register_view()`. Text: `"ViewName, N of M"`. Left/Right arrows on item 0 cycle through views.
- User presses Ctrl+Tab to cycle views: Apps → Games → [your view] → Titan IM → ...
- Tab/Shift+Tab navigates between view control and status bar.
- Enter on view control calls `on_activate` (if provided).
- TTS announces view label and position, e.g. "My Notes, 3 of 4".
- Each registered view also gets a toolbar button (label = `short_name`).

### Tab bar auto-sync

Components often call `control.Clear()` / `tree.DeleteAllItems()` to repopulate their lists. Clearing wipes out the injected tab bar row too. `register_view()` handles this automatically through:

- **`EVT_SET_FOCUS`** — re-injects the tab bar row whenever focus enters the view.
- **`EVT_LISTBOX`** (only `wx.ListBox`) — re-injects on selection change.

If you repopulate from somewhere else and need an immediate refresh, call **`component_manager.sync_view_tab_bar(view_id_or_control)`** or **`gui_app.sync_view_tab_bar(view_id_or_control)`**:

```python
def refresh_my_data(self):
    self._listbox.Clear()
    for item in self._items:
        self._listbox.Append(item)
    # Force immediate tab bar row re-injection
    self.component_manager.sync_view_tab_bar('my_view_id')
```

## Complete Examples

### Example 1: Simple List View (Bookmarks Manager)

Component adding a "Bookmarks" tab to left panel with saved bookmarks list.

**File: `data/components/bookmarks/init.py`**
```python
# -*- coding: utf-8 -*-
"""Bookmarks component - adds bookmarks list to main panel."""

import os
import sys
import wx
import json

COMPONENT_DIR = os.path.dirname(__file__)
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

try:
    from src.titan_core.sound import play_sound
except ImportError:
    def play_sound(name): pass

try:
    from src.settings.settings import get_setting
except ImportError:
    def get_setting(key, default='', section='general'): return default

def _(text):
    return text

# --- Bookmark Data ---
BOOKMARKS_FILE = os.path.join(COMPONENT_DIR, 'bookmarks.json')
_bookmarks = []
_listbox = None


def load_bookmarks():
    """Load bookmarks from JSON file."""
    global _bookmarks
    try:
        if os.path.exists(BOOKMARKS_FILE):
            with open(BOOKMARKS_FILE, 'r', encoding='utf-8') as f:
                _bookmarks = json.load(f)
        else:
            _bookmarks = [
                {"name": "Google", "url": "https://google.com"},
                {"name": "YouTube", "url": "https://youtube.com"},
            ]
            save_bookmarks()
    except Exception as e:
        print(f"[bookmarks] Error loading bookmarks: {e}")
        _bookmarks = []


def save_bookmarks():
    """Save bookmarks to JSON file."""
    try:
        with open(BOOKMARKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(_bookmarks, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[bookmarks] Error saving bookmarks: {e}")


def refresh_list():
    """Refresh listbox with current bookmarks (called by on_show)."""
    if _listbox is None:
        return
    _listbox.Clear()
    for bm in _bookmarks:
        _listbox.Append(bm['name'])
    if _listbox.GetCount() > 0:
        _listbox.SetSelection(0)


def on_bookmark_activate(event):
    """Open selected bookmark in browser (called by Enter key)."""
    if _listbox is None:
        return
    sel = _listbox.GetSelection()
    if sel == wx.NOT_FOUND or sel >= len(_bookmarks):
        return
    url = _bookmarks[sel]['url']
    play_sound('ui/dialog.ogg')
    import webbrowser
    webbrowser.open(url)


def on_gui_init(gui_app):
    """Register bookmarks view in main left panel."""
    global _listbox
    _listbox = wx.ListBox(gui_app.main_panel)

    gui_app.register_view(
        view_id='bookmarks',
        label="Bookmarks:",
        control=_listbox,
        on_show=refresh_list,
        on_activate=on_bookmark_activate,
        position='after_network'
    )
    print("[bookmarks] View registered in main panel")


# --- Component Interface ---

def get_gui_hooks():
    return {'on_gui_init': on_gui_init}


def add_menu(component_manager):
    def add_bookmark(event):
        dlg = wx.TextEntryDialog(None, "Enter bookmark name:", "Add Bookmark")
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                url_dlg = wx.TextEntryDialog(None, "Enter URL:", "Add Bookmark", "https://")
                if url_dlg.ShowModal() == wx.ID_OK:
                    url = url_dlg.GetValue().strip()
                    if url:
                        _bookmarks.append({"name": name, "url": url})
                        save_bookmarks()
                        refresh_list()
                        play_sound('ui/dialog.ogg')
                url_dlg.Destroy()
        dlg.Destroy()

    component_manager.register_menu_function("Add Bookmark...", add_bookmark)


def initialize(app=None):
    load_bookmarks()
    print("[bookmarks] Component initialized")


def shutdown():
    save_bookmarks()
    print("[bookmarks] Component shutdown")
```

**File: `data/components/bookmarks/__component__.TCE`**
```ini
[component]
name = Bookmarks
status = 0

```

### Example 2: TreeCtrl View (File Browser)

Component adding a tree view showing files from a directory.

**File: `data/components/filebrowser/init.py`**
```python
# -*- coding: utf-8 -*-
"""File Browser component - adds file tree to main panel."""

import os
import sys
import wx

COMPONENT_DIR = os.path.dirname(__file__)
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

try:
    from src.titan_core.sound import play_sound
except ImportError:
    def play_sound(name): pass

def _(text):
    return text

_tree = None
_browse_path = os.path.expanduser("~\\Documents")


def populate_tree():
    """Populate tree with files from browse_path (called by on_show)."""
    if _tree is None:
        return

    _tree.DeleteAllItems()
    root = _tree.AddRoot(_browse_path)

    try:
        for item_name in sorted(os.listdir(_browse_path)):
            full_path = os.path.join(_browse_path, item_name)
            if os.path.isdir(full_path):
                _tree.AppendItem(root, f"[DIR] {item_name}")
            else:
                _tree.AppendItem(root, item_name)
    except PermissionError:
        _tree.AppendItem(root, "Access denied")
    except Exception as e:
        _tree.AppendItem(root, f"Error: {e}")

    _tree.Expand(root)

    # Select first child
    child, cookie = _tree.GetFirstChild(root)
    if child.IsOk():
        _tree.SelectItem(child)


def on_file_activate(event):
    """Open selected file (called by Enter key)."""
    if _tree is None:
        return
    item = _tree.GetSelection()
    if not item.IsOk():
        return
    text = _tree.GetItemText(item)
    if text.startswith("[DIR] "):
        # Enter directory
        global _browse_path
        dir_name = text[6:]  # Remove "[DIR] " prefix
        _browse_path = os.path.join(_browse_path, dir_name)
        populate_tree()
        play_sound('core/focus.ogg')
    elif text == "Access denied":
        return
    else:
        # Open file
        file_path = os.path.join(_browse_path, text)
        if os.path.exists(file_path):
            os.startfile(file_path)
            play_sound('ui/dialog.ogg')


def on_gui_init(gui_app):
    """Register file browser view."""
    global _tree
    _tree = wx.TreeCtrl(
        gui_app.main_panel,
        style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE
    )

    gui_app.register_view(
        view_id='filebrowser',
        label="File Browser:",
        control=_tree,
        on_show=populate_tree,
        on_activate=on_file_activate,
        position='after_games'  # Between Games and Titan IM
    )
    print("[filebrowser] View registered in main panel")


# --- Component Interface ---

def get_gui_hooks():
    return {'on_gui_init': on_gui_init}


def initialize(app=None):
    print("[filebrowser] Component initialized")


def shutdown():
    print("[filebrowser] Component shutdown")
```

**File: `data/components/filebrowser/__component__.TCE`**
```ini
[component]
name = File Browser
status = 0

```

## System Integration

### Accessing the main application
```python
def initialize(app=None):
    if app:
        # Access the main window
        main_frame = app.GetTopWindow()
        # Access the menu
        menubar = main_frame.GetMenuBar()
        # Access the status bar
        statusbar = main_frame.GetStatusBar()
```

### Thread-safe calls
```python
# Use wx.CallAfter for GUI operations from threads
wx.CallAfter(self._update_ui, data)

def _update_ui(self, data):
    # GUI-modifying code
    pass
```

### Using system sounds
```python
from src.titan_core.sound import play_sound, play_error_sound, play_dialog_sound

def my_function():
    play_sound("focus.ogg")  # Play a sound from the current theme
    play_error_sound()       # Error sound
```

### Accessing settings
```python
from src.settings.settings import get_setting, set_setting

def initialize(app=None):
    # Read a setting
    enabled = get_setting('my_component_enabled', 'True', section='components')

    # Save a setting
    set_setting('my_component_value', '42', section='components')
```

## Component State Management

### Enabling/disabling
Users can enable/disable components through:
1. The Component Manager in the GUI
2. Invisible UI → Menu → Components

### State persistence
The enabled/disabled state is stored in `__component__.TCE`:
```ini
[component]
name = My Component
status = 0  # 0 = enabled, 1 = disabled
```

## Directory Structure

```
data/components/my_component/
├── init.py              # Main component file (NOT __init__.py!)
├── __component__.TCE    # Component configuration
├── bookmarks.json       # Component data (example)
├── resources/           # Resources (optional)
│   ├── sounds/
│   └── images/
├── data/                # Data files (optional)
└── languages/           # Translations (optional)
    ├── component_id.pot
    ├── pl/
    │   └── LC_MESSAGES/
    │       └── component_id.mo
    └── en/
        └── LC_MESSAGES/
            └── component_id.mo
```

## Component Types

- **Service**: Background services (e.g., screen reader integration, system monitoring)
- **Integration**: Third-party service integrations (e.g., dictionary, article viewer)
- **Feature**: Additional features (e.g., terminal, tips system, launchers)
- **View**: Components that add a tab/view to main left panel (use `register_view()`)

## Key Guidelines

1. **Always use daemon threads** - `threading.Thread(daemon=True)`
2. **Implement shutdown()** - stop all threads
3. **Use wx.CallAfter** for GUI operations from threads
4. **Test enable/disable** functionality
5. **Add error handling** - components shouldn't crash Titan
6. **Conserve resources** - don't run heavy operations too frequently
7. **Use get_gui_hooks()** for views instead of direct GUI modification
8. **Refresh data in on_show** when view becomes visible (Ctrl+Tab)
9. **Add context menus** for better UX (right-click on ListBox/TreeCtrl)

## Packaging as `.TCD` (Optional)

Instead of shipping a directory, a component can be distributed as a
single `.tcd` file — same content, including any bundled `lib/` native
dependencies. Purely optional and additive.

```bash
python src/scripts/pack_addon.py data/components/my_component --kind component -o my_component.tcd
```

- `.tcd` is a custom compressed container (magic header + LZMA payload),
  deliberately not a real zip/7z — 7-Zip and Windows Explorer refuse to
  open it as an archive.
- No code changes needed: the payload is byte-identical to the directory,
  so `init.py` and `__component__.TCE` still resolve the same way once
  extracted, and native `lib/` dependencies work unmodified since
  `sys.path` insertion is computed from the extracted path.
- Drop the `.tcd` into `data/components/` (bundled or per-user overlay) and
  it's discovered/loaded identically to a directory-based component.

See `src/titan_core/titan_package.py` for the format implementation.

## Testing Components

1. Place component in `data/components/component_name/`
2. Ensure file is `init.py` not `__init__.py`
3. Check `__component__.TCE` format (INI, uppercase .TCE)
4. Start Titan
5. Check component manager if component is loaded
6. Test functionality through component menu
7. If component registers view, test Ctrl+Tab cycle

## Debugging

### Component logs
```python
import logging

# Configure a logger
logger = logging.getLogger(__name__)

def initialize(app=None):
    logger.info("Component initializing")

def shutdown():
    logger.info("Component shutting down")
```

### Error handling
```python
def initialize(app=None):
    try:
        # Initialization code
        pass
    except Exception as e:
        print(f"Component initialization error: {e}")
        import traceback
        traceback.print_exc()
```

## Reference Examples

- **TitanScreenReader** (`data/components/TitanScreenReader/`): Complex screen reader
  - Service-type component with background monitoring
  - Multiple sub-modules (uia_handler, speech_manager, keyboard_handler)
  - Settings dialog with wxPython
  - Translation support

- **tips** (`data/components/tips/`): Tips system
  - Simple Feature-type component
  - Background thread for periodic tips
  - Settings dialog

- **tDict** (`data/components/tDict/`): Dictionary component
  - `data/` subdirectory for dictionary files
  - Translation support

Components enable extending Titan functionality in a modular and safe way. With the simple API, you can easily add new capabilities without modifying the main application code.
