# Create Component Wizard

Interactive wizard to create a new component for TCE Launcher.

## Process:

1. **Ask for Component Details:**
   - Component name (display name in English)
   - Component ID (lowercase, no spaces, for directory name)
   - Component description
   - Component type (service, integration, feature, view)
   - Whether the component needs a view (tab) in the left panel
   - Required dependencies (if any)

2. **Create Component Structure:**
   - Create directory: `data/components/{component_id}/`
   - Create main file: `data/components/{component_id}/init.py` (NOT `__init__.py`!)
   - Create config file: `data/components/{component_id}/__component__.TCE`

3. **Generate Component Template (`init.py`):**
   ```python
   # -*- coding: utf-8 -*-
   """
   {Component Name} Component for TCE Launcher
   {Component Description}
   """

   import os
   import sys
   import wx
   import gettext

   # Add component directory to path
   COMPONENT_DIR = os.path.dirname(__file__)
   if COMPONENT_DIR not in sys.path:
       sys.path.insert(0, COMPONENT_DIR)

   # Add TCE root directory to path for proper imports
   TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
   if TCE_ROOT not in sys.path:
       sys.path.insert(0, TCE_ROOT)

   # Import TCE modules
   try:
       from src.titan_core.sound import play_sound
       SOUND_AVAILABLE = True
   except ImportError as e:
       SOUND_AVAILABLE = False
       print(f"[{component_id}] Warning: sound module not available: {e}")

   try:
       from src.settings.settings import get_setting
       SETTINGS_AVAILABLE = True
   except ImportError as e:
       SETTINGS_AVAILABLE = False
       print(f"[{component_id}] Warning: settings module not available: {e}")
       def get_setting(key, default='', section='general'):
           return default

   # Translation support
   LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')

   try:
       if SETTINGS_AVAILABLE:
           lang = get_setting('language', 'pl')
       else:
           lang = 'pl'

       translation = gettext.translation('{component_id}', localedir=LANGUAGES_DIR, languages=[lang], fallback=True)
       translation.install()
       _ = translation.gettext
   except Exception as e:
       print(f"[{component_id}] Translation loading failed: {e}")
       def _(text):
           return text


   class {ComponentName}:
       """Main component class"""

       def __init__(self):
           """Initialize component"""
           self._ = _
           print(f"[{component_id}] Component initialized")

       def enable(self):
           """Enable component functionality"""
           try:
               # Add your component logic here
               if SOUND_AVAILABLE:
                   play_sound('ui/dialog.ogg')
               print(f"[{component_id}] Component enabled")
               return True
           except Exception as e:
               print(f"[{component_id}] Error enabling component: {e}")
               return False

       def disable(self):
           """Disable component functionality"""
           try:
               # Add cleanup logic here
               if SOUND_AVAILABLE:
                   play_sound('ui/dialogclose.ogg')
               print(f"[{component_id}] Component disabled")
           except Exception as e:
               print(f"[{component_id}] Error disabling component: {e}")


   # Global component instance
   _component_instance = None


   def get_component():
       """Get the global component instance"""
       global _component_instance
       if _component_instance is None:
           _component_instance = {ComponentName}()
       return _component_instance


   def on_menu_action(event):
       """Menu action handler"""
       component = get_component()
       # Add your menu action logic here
       print(f"[{component_id}] Menu action triggered")


   def add_menu(component_manager):
       """Register menu item (optional)"""
       try:
           component_manager.register_menu_function(_("{Component Name}..."), on_menu_action)
           print(f"[{component_id}] Menu registered")
       except Exception as e:
           print(f"[{component_id}] Error registering menu: {e}")


   def add_settings(settings_frame):
       """Add settings panel — legacy hook, prefer add_settings_category (optional)"""
       pass


   def add_settings_category(component_manager):
       """Register a settings category via the modular settings system (optional)"""
       # Example:
       # def build_panel(parent):
       #     panel = wx.Panel(parent)
       #     # ... add controls ...
       #     return panel
       # component_manager.register_settings_category(_("{Component Name}"), build_panel)
       pass


   def get_gui_hooks():
       """Return GUI hooks dict (optional).

       Supported hooks:
           'on_gui_init': called with gui_app (TitanApp wx.Frame) when GUI is initialized
       """
       return {}


   def get_klango_hooks():
       """Return Klango mode hooks dict (optional).

       Supported hooks:
           'on_klango_init': called with klango_mode (KlangoMode) when Klango mode starts
       """
       return {}


   def get_iui_hooks():
       """Return Invisible UI hooks dict (optional).

       Supported hooks:
           'on_iui_init': called with iui (InvisibleUI) after build_structure() completes

       Example — add a custom category:
           def on_iui_init(iui):
               iui.categories.append({
                   "name": "My Component",
                   "sound": "core/focus.ogg",
                   "elements": ["Option 1", "Option 2"],
                   "action": lambda name: my_action(name)
               })
       """
       return {}


   def initialize(app=None):
       """Initialize component — called by ComponentManager on load"""
       try:
           print(f"[{component_id}] Initializing component...")
           component = get_component()
           # Add initialization logic here
           print(f"[{component_id}] Component initialized successfully")
       except Exception as e:
           print(f"[{component_id}] Error during initialization: {e}")
           import traceback
           traceback.print_exc()


   def shutdown():
       """Shutdown component — called by ComponentManager on unload"""
       global _component_instance
       try:
           print(f"[{component_id}] Shutting down component...")
           if _component_instance:
               _component_instance.disable()
               _component_instance = None
           print(f"[{component_id}] Component shutdown complete")
       except Exception as e:
           print(f"[{component_id}] Error during shutdown: {e}")
           import traceback
           traceback.print_exc()


   if __name__ == '__main__':
       print("="*60)
       print("Testing {Component Name} Component")
       print("="*60)
       initialize()
       print("Component test completed!")
   ```

4. **Create Config File (`__component__.TCE` format):**
   ```ini
   [component]
   name = {component_name}
   status = 1

   ```

   **IMPORTANT**:
   - Use INI format with `[component]` section
   - **`status = 1` means DISABLED, `status = 0` means ENABLED** (inverted!)
   - File must be named `__component__.TCE` (UPPERCASE .TCE)
   - Main file MUST be named `init.py` (lowercase, NOT `__init__.py`)
   - Include blank line at end of file

5. **Optional Translation Setup:**
   - Create `languages/` directory for translations
   - `pybabel extract -o languages/{component_id}.pot --no-default-keywords --keyword=_ data/components/{component_id}/init.py`
   - `pybabel init -l pl -d languages -i languages/{component_id}.pot -D {component_id}`
   - `pybabel compile -d languages`

6. **Optional Data Directory:**
   - Create `data/` subdirectory for component-specific data
   - See `data/components/tDict/data/` for example

7. **Verify Installation:**
   - Restart TCE Launcher
   - Open Component Manager (from main menu)
   - Check if component appears in list
   - Enable component and verify it loads correctly
   - Check for any error messages in console

## Component Interface (from component_manager.py):

Components MUST define:
- `initialize(app=None)` — Called when component is loaded (required)

Components CAN define (all optional):
- `add_menu(component_manager)` — Register menu items
- `add_settings(settings_frame)` — Legacy settings UI hook
- `add_settings_category(component_manager)` — Modular settings (preferred)
- `get_gui_hooks()` — Return `{'on_gui_init': func}` for GUI customization
  - In `on_gui_init(gui_app)`, can call `gui_app.register_view()` to add a tab/view to the left panel (Ctrl+Tab cycle)
- `get_klango_hooks()` — Return `{'on_klango_init': func}` for Klango mode
- `get_iui_hooks()` — Return `{'on_iui_init': func}` for Invisible UI
- `shutdown()` — Cleanup when component is unloaded

## View Registration API:

Components can add views (tabs) to the main GUI's left panel. Registered views appear in the Ctrl+Tab cycle alongside built-in views (Application List, Game List, Titan IM).

### register_view() Parameters:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `view_id` | str | Yes | Unique identifier, e.g. `'my_notes'` |
| `label` | str | Yes | Header text shown above the control, e.g. `'My Notes:'` |
| `control` | wx.Window | Yes | Any wx control (ListBox, TreeCtrl, etc.), parented to `gui_app.main_panel` |
| `on_show` | callable | No | Called every time the view becomes visible (use to refresh data) |
| `on_activate` | callable | No | Called when user presses Enter on the control |
| `position` | str/int | No | Where in cycle: `'after_apps'`, `'after_games'`, `'after_network'` (default), or integer index |

### How it works:
- The registered control is added to the left panel sizer (hidden by default)
- User presses Ctrl+Tab to cycle through views: Apps -> Games -> [your view] -> Titan IM -> ...
- Tab/Shift+Tab navigates between the view control and the status bar
- Enter on the view control calls `on_activate` (if provided)
- TTS announces the view label and position, e.g. "My Notes, 3 of 4"

---

## Complete Code Examples

### Example 1: Simple List View (Bookmarks Manager)

A component that adds a "Bookmarks" tab to the left panel with a list of saved bookmarks.

**File: `data/components/bookmarks/init.py`**
```python
# -*- coding: utf-8 -*-
"""Bookmarks component - adds a bookmarks list to the main panel."""

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
    """Refresh the listbox with current bookmarks (called on_show)."""
    if _listbox is None:
        return
    _listbox.Clear()
    for bm in _bookmarks:
        _listbox.Append(bm['name'])
    if _listbox.GetCount() > 0:
        _listbox.SetSelection(0)


def on_bookmark_activate(event):
    """Open selected bookmark in browser (called on Enter key)."""
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
    """Register the bookmarks view in the main left panel."""
    global _listbox
    _listbox = wx.ListBox(gui_app.main_panel)

    gui_app.register_view(
        view_id='bookmarks',
        label=_("Bookmarks:"),
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
        dlg = wx.TextEntryDialog(None, _("Enter bookmark name:"), _("Add Bookmark"))
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                url_dlg = wx.TextEntryDialog(None, _("Enter URL:"), _("Add Bookmark"), "https://")
                if url_dlg.ShowModal() == wx.ID_OK:
                    url = url_dlg.GetValue().strip()
                    if url:
                        _bookmarks.append({"name": name, "url": url})
                        save_bookmarks()
                        refresh_list()
                        play_sound('ui/dialog.ogg')
                url_dlg.Destroy()
        dlg.Destroy()

    component_manager.register_menu_function(_("Add Bookmark..."), add_bookmark)


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

---

### Example 2: TreeCtrl View (File Browser)

A component that adds a tree view showing files from a directory.

**File: `data/components/filebrowser/init.py`**
```python
# -*- coding: utf-8 -*-
"""File Browser component - adds a file tree to the main panel."""

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
    """Populate tree with files from browse_path (called on_show)."""
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
        _tree.AppendItem(root, _("Access denied"))
    except Exception as e:
        _tree.AppendItem(root, f"Error: {e}")

    _tree.Expand(root)

    # Select first child
    child, cookie = _tree.GetFirstChild(root)
    if child.IsOk():
        _tree.SelectItem(child)


def on_file_activate(event):
    """Open selected file (called on Enter key)."""
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
    elif text == _("Access denied"):
        return
    else:
        # Open file
        file_path = os.path.join(_browse_path, text)
        if os.path.exists(file_path):
            os.startfile(file_path)
            play_sound('ui/dialog.ogg')


def on_gui_init(gui_app):
    """Register the file browser view."""
    global _tree
    _tree = wx.TreeCtrl(
        gui_app.main_panel,
        style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE
    )

    gui_app.register_view(
        view_id='filebrowser',
        label=_("File Browser:"),
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

---

### Example 3: Menu-Only Component (No View)

A simple component that only adds menu items without a left panel view.

**File: `data/components/quicklaunch/init.py`**
```python
# -*- coding: utf-8 -*-
"""Quick Launch - adds frequently used tools to the menu."""

import os
import sys
import subprocess

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


def add_menu(component_manager):
    """Register menu items."""
    def open_notepad(event):
        play_sound('ui/dialog.ogg')
        subprocess.Popen(['notepad.exe'])

    def open_calculator(event):
        play_sound('ui/dialog.ogg')
        subprocess.Popen(['calc.exe'])

    def open_cmd(event):
        play_sound('ui/dialog.ogg')
        subprocess.Popen(['cmd.exe'])

    component_manager.register_menu_function(_("Notepad"), open_notepad)
    component_manager.register_menu_function(_("Calculator"), open_calculator)
    component_manager.register_menu_function(_("Command Prompt"), open_cmd)


def initialize(app=None):
    print("[quicklaunch] Component initialized")


def shutdown():
    print("[quicklaunch] Component shutdown")
```

---

### Example 4: View + Settings + Menu (Full Component)

A complete component with a left panel view, settings category, and menu item.

**File: `data/components/notes/init.py`**
```python
# -*- coding: utf-8 -*-
"""Notes component - quick notes accessible from the main panel."""

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

# --- Notes Data ---
NOTES_FILE = os.path.join(COMPONENT_DIR, 'notes.json')
_notes = []
_listbox = None
_gui_app = None


def load_notes():
    global _notes
    try:
        if os.path.exists(NOTES_FILE):
            with open(NOTES_FILE, 'r', encoding='utf-8') as f:
                _notes = json.load(f)
        else:
            _notes = []
    except Exception as e:
        print(f"[notes] Error loading: {e}")
        _notes = []


def save_notes():
    try:
        with open(NOTES_FILE, 'w', encoding='utf-8') as f:
            json.dump(_notes, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[notes] Error saving: {e}")


def refresh_list():
    """Refresh the listbox (called when view becomes visible via Ctrl+Tab)."""
    if _listbox is None:
        return
    _listbox.Clear()
    for note in _notes:
        # Show first line of note as title
        title = note.get('text', '').split('\n')[0][:50]
        if not title:
            title = _("(empty note)")
        _listbox.Append(title)
    if _listbox.GetCount() > 0:
        _listbox.SetSelection(0)


def on_note_activate(event):
    """Edit selected note on Enter key."""
    if _listbox is None:
        return
    sel = _listbox.GetSelection()
    if sel == wx.NOT_FOUND:
        return

    if sel < len(_notes):
        # Edit existing note
        current_text = _notes[sel].get('text', '')
        dlg = wx.TextEntryDialog(
            None,
            _("Edit note:"),
            _("Edit Note"),
            current_text,
            style=wx.OK | wx.CANCEL | wx.TE_MULTILINE
        )
        if dlg.ShowModal() == wx.ID_OK:
            _notes[sel]['text'] = dlg.GetValue()
            save_notes()
            refresh_list()
            play_sound('ui/dialog.ogg')
        dlg.Destroy()


def create_new_note(event=None):
    """Create a new note."""
    dlg = wx.TextEntryDialog(
        None,
        _("Enter note text:"),
        _("New Note"),
        style=wx.OK | wx.CANCEL | wx.TE_MULTILINE
    )
    if dlg.ShowModal() == wx.ID_OK:
        text = dlg.GetValue().strip()
        if text:
            _notes.append({'text': text})
            save_notes()
            refresh_list()
            play_sound('ui/dialog.ogg')
    dlg.Destroy()


def delete_current_note(event=None):
    """Delete the currently selected note."""
    if _listbox is None:
        return
    sel = _listbox.GetSelection()
    if sel == wx.NOT_FOUND or sel >= len(_notes):
        return
    confirm = wx.MessageDialog(
        None,
        _("Are you sure you want to delete this note?"),
        _("Delete Note"),
        wx.YES_NO | wx.ICON_QUESTION
    )
    if confirm.ShowModal() == wx.ID_YES:
        del _notes[sel]
        save_notes()
        refresh_list()
        play_sound('ui/dialogclose.ogg')
    confirm.Destroy()


# --- GUI Hook: Register Left Panel View ---

def on_gui_init(gui_app):
    """Register the notes view in the main left panel."""
    global _listbox, _gui_app
    _gui_app = gui_app

    _listbox = wx.ListBox(gui_app.main_panel)

    # Right-click context menu for list
    def on_context_menu(event):
        menu = wx.Menu()
        item_new = menu.Append(wx.ID_ANY, _("New Note"))
        item_edit = menu.Append(wx.ID_ANY, _("Edit Note"))
        item_delete = menu.Append(wx.ID_ANY, _("Delete Note"))

        gui_app.Bind(wx.EVT_MENU, lambda e: create_new_note(), item_new)
        gui_app.Bind(wx.EVT_MENU, lambda e: on_note_activate(e), item_edit)
        gui_app.Bind(wx.EVT_MENU, lambda e: delete_current_note(), item_delete)

        gui_app.PopupMenu(menu)
        menu.Destroy()

    _listbox.Bind(wx.EVT_CONTEXT_MENU, on_context_menu)

    gui_app.register_view(
        view_id='notes',
        label=_("Notes:"),
        control=_listbox,
        on_show=refresh_list,
        on_activate=on_note_activate,
        position='after_network'
    )
    print("[notes] View registered in main panel")


def get_gui_hooks():
    return {'on_gui_init': on_gui_init}


# --- Menu ---

def add_menu(component_manager):
    component_manager.register_menu_function(_("New Note..."), create_new_note)


# --- Settings ---

def add_settings_category(component_manager):
    """Register notes settings in the Settings window."""
    def build_panel(parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label=_("Notes Settings")), 0, wx.ALL, 10)

        panel.auto_save_cb = wx.CheckBox(panel, label=_("Auto-save notes on exit"))
        panel.auto_save_cb.SetValue(True)
        sizer.Add(panel.auto_save_cb, 0, wx.ALL, 5)

        panel.SetSizer(sizer)
        return panel

    def save_settings(panel):
        # Save settings logic here
        print(f"[notes] Settings saved: auto_save={panel.auto_save_cb.GetValue()}")

    def load_settings(panel):
        # Load settings logic here
        panel.auto_save_cb.SetValue(True)

    component_manager.register_settings_category(
        _("Notes"),
        build_panel,
        save_settings,
        load_settings
    )


# --- Lifecycle ---

def initialize(app=None):
    load_notes()
    print(f"[notes] Initialized with {len(_notes)} notes")


def shutdown():
    save_notes()
    print("[notes] Shutdown complete")
```

**File: `data/components/notes/__component__.TCE`**
```ini
[component]
name = Notes
status = 0

```

---

## Component Types:

- **Service**: Background services (e.g., screen reader integration, system monitoring)
- **Integration**: Third-party service integrations (e.g., dictionary, article viewer)
- **Feature**: Additional features (e.g., terminal, tips system, launchers)
- **View**: Components that add a tab/view to the main left panel (use `register_view()`)

## Key Points for View Components:

1. Create your wx control with `gui_app.main_panel` as parent
2. Call `gui_app.register_view()` inside `on_gui_init()` hook
3. The control is automatically hidden/shown during Ctrl+Tab cycling
4. Use `on_show` callback to refresh data when view becomes visible
5. Use `on_activate` callback for Enter key handling
6. Add right-click context menus with `control.Bind(wx.EVT_CONTEXT_MENU, ...)`
7. You can use `wx.ListBox`, `wx.TreeCtrl`, or any other wx control

## Available gui_app Attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `gui_app.main_panel` | wx.Panel | Parent panel for creating new controls |
| `gui_app.list_sizer` | wx.BoxSizer | The sizer containing all left panel controls |
| `gui_app.registered_views` | list | All registered views (built-in + component) |
| `gui_app.register_view()` | method | Register a new view for Ctrl+Tab cycling |
| `gui_app.component_manager` | ComponentManager | Reference to component manager |
| `gui_app.settings` | dict | Application settings |
| `gui_app.titan_client` | TitanNetClient | Titan-Net client instance |

## Reference Examples:

- **TitanScreenReader** (`data/components/TitanScreenReader/`): Complex screen reader
  - Service-type component with background monitoring
  - Multiple sub-modules (uia_handler, speech_manager, keyboard_handler)
  - Settings dialog with wxPython
  - Translation support

- **tips** (`data/components/tips/`): Tips system
  - Simple feature component
  - Background thread for periodic tips
  - Settings dialog

- **tDict** (`data/components/tDict/`): Dictionary component
  - Has `data/` subdirectory for dictionary files
  - Translation support

## Action:

Ask the user for component details and create a complete, working component following the current TCE standard. If the user wants a view in the left panel, use the View Registration API with `get_gui_hooks()` and `register_view()`.
