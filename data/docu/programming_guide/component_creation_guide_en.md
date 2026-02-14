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
- **IMPORTANT**: File name is `__component__.TCE` (uppercase .TCE)
- **IMPORTANT**: Main file is `init.py` (lowercase, NOT `__init__.py`)
- **IMPORTANT**: Add blank line at end of file

## Component Interface

### Required Functions

#### initialize(app=None)
**Required function** called at Titan startup:
- `app` - wxPython main application instance (may be None)
- Use for initializing resources, starting threads

### Optional Functions

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

## Component View Registration API

**NEW!** Components can add custom tabs/views to the main GUI left panel. Registered views appear in Ctrl+Tab cycle alongside built-in views (Application List, Game List, Titan IM).

### register_view() Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `view_id` | str | Yes | Unique identifier, e.g. `'my_notes'` |
| `label` | str | Yes | Header text shown above control, e.g. `'My Notes:'` |
| `control` | wx.Window | Yes | Any wx control (ListBox, TreeCtrl, etc.), parent: `gui_app.main_panel` |
| `on_show` | callable | No | Called every time view becomes visible (refresh data) |
| `on_activate` | callable | No | Called when user presses Enter on control |
| `position` | str/int | No | Position in cycle: `'after_apps'`, `'after_games'`, `'after_network'` (default), or integer index |

### How it works

- Registered control is added to left panel sizer (hidden by default)
- User presses Ctrl+Tab to cycle views: Apps → Games → [your view] → Titan IM → ...
- Tab/Shift+Tab navigates between view control and status bar
- Enter on view control calls `on_activate` (if provided)
- TTS announces view label and position, e.g. "My Notes, 3 of 4"

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

## Testing Components

1. Place component in `data/components/component_name/`
2. Ensure file is `init.py` not `__init__.py`
3. Check `__component__.TCE` format (INI, uppercase .TCE)
4. Start Titan
5. Check component manager if component is loaded
6. Test functionality through component menu
7. If component registers view, test Ctrl+Tab cycle

Components enable extending Titan functionality in a modular and safe way. With the simple API, you can easily add new capabilities without modifying the main application code.
