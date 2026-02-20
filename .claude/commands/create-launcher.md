# Create Launcher Wizard

Interactive wizard to create a new alternative launcher interface for TCE Launcher.

## What are Launchers?

Launchers are alternative GUI interfaces for TCE, located in `data/launchers/`. They completely replace the standard TCE GUI with a custom UI using **any Python GUI library** (wxPython, PyQt5, tkinter, pygame, etc.). TCE continues running in the background, providing all services (applications, games, sound, settings, Titan IM, etc.) through the `LauncherAPI` object passed to your `start()` function.

**Only one launcher can run at a time.**

Run a launcher:
```bash
python main.py --startup-mode launcher --launcher {folder_name}
```

Or configure in settings (`[general]` section):
```
startup_mode = launcher
launcher = {folder_name}
```

## Process:

1. **Ask for Launcher Details:**
   - Launcher name (display name in English)
   - Folder name (lowercase, no spaces, for directory under `data/launchers/`)
   - Description
   - GUI library to use (wxPython, tkinter, PyQt5, other)
   - Which features to enable (applications, games, titan_im, invisible_ui, etc.)
   - Whether to support minimize-to-tray

2. **Create Launcher Structure:**
   - Create directory: `data/launchers/{folder_name}/`
   - Create main file: `data/launchers/{folder_name}/init.py`
   - Create config file: `data/launchers/{folder_name}/__launcher__.TCE`

3. **Create Config File (`__launcher__.TCE`):**

   ```ini
   [launcher]
   name = {Launcher Name}
   description = {Description}
   author = {Author}
   version = 1.0
   status = 0

   [features]
   applications = true
   games = true
   titan_im = true
   help = true
   components = true
   system_hooks = true
   notifications = true
   sound = true
   invisible_ui = false
   ```

   **IMPORTANT**:
   - Use INI format with `[launcher]` and `[features]` sections
   - **`status = 0` means ENABLED, `status = 1` means DISABLED** (same convention as components)
   - Set features to `false` to disable capabilities you don't need
   - `invisible_ui = true` enables the tilde-key Invisible UI overlay inside the launcher
   - File must be named `__launcher__.TCE` (UPPERCASE .TCE)
   - Main file MUST be named `init.py`

4. **Launcher Interface (`init.py`):**

   A launcher MUST define:
   - `start(api)` — Entry point. Called once at startup. **Must return quickly.** For non-wx GUI libraries (tkinter, PyQt5, pygame), start your event loop in a daemon thread and return. For wxPython, just create a wx.Frame and return — wx.MainLoop is already running.

   A launcher CAN define:
   - `shutdown()` — Called when TCE shuts down. Use to clean up your UI.

   ```python
   def start(api):
       """Start the launcher. Must return quickly — do not block."""
       # For wx: just create and show a frame, wx.MainLoop already runs
       # For tkinter/PyQt5: start a daemon thread with your event loop

   def shutdown():
       """Optional: called when TCE is shutting down."""
       pass
   ```

## LauncherAPI — Always Available

These are always available regardless of `[features]` config:

### Settings
```python
api.get_setting(key, default='', section='general')
api.set_setting(key, value, section='general')
api.load_settings()    # returns full settings dict
api.save_settings()
```

### Translation
```python
_ = api._                              # TCE's built-in translation function
api.language_code                      # current language code, e.g. 'pl'
_ = api.load_translations()            # load own languages/ dir (domain='launcher')
_ = api.load_translations('my_name')  # custom domain from launcher's languages/
api.set_language(lang_code)
api.get_available_languages()
```

### Sound (full TCE sound system)
```python
api.play_sound('ui/dialog.ogg')        # play any sfx file from current theme
api.play_startup_sound()
api.play_focus_sound()                 # list focus changed
api.play_select_sound()                # item selected/activated
api.play_applist_sound()               # entered app/game list
api.play_endoflist_sound()             # reached end of list
api.play_error_sound()
api.play_dialog_sound()                # dialog opened
api.play_dialogclose_sound()           # dialog closed
api.play_statusbar_sound()             # statusbar item focused
api.play_loop_sound()                  # start looping background sound
api.stop_loop_sound()
api.play_ai_tts(text)                  # AI text-to-speech
api.stop_ai_tts()
api.is_ai_tts_playing()                # bool
api.resource_path('sfx/sound.ogg')    # absolute path to TCE resource
api.get_sfx_directory()               # path to current sfx theme directory
```

### Speaker (TTS)
```python
api.speaker.speak("Hello")
api.speaker.speak(text, interrupt=True)
# api.speaker is accessible_output3 Auto() — already initialized safely
```

### Metadata & References
```python
api.version           # version string, e.g. "2.1.0"
api.launcher_path     # absolute path to this launcher's directory
api.wx_app            # wx.App instance (use for wx dialogs from non-wx launchers)
```

### Statusbar Applet Manager
```python
api.statusbar_applet_manager.get_statusbar_items()       # all items as [str] (built-in + applets)
api.statusbar_applet_manager.get_builtin_items()         # built-in items only (Clock, Battery, Volume, Network)
api.statusbar_applet_manager.get_applet_names()          # names of loaded applets
api.statusbar_applet_manager.get_all_applet_texts()      # applet text strings only
api.statusbar_applet_manager.activate_applet(name)       # open applet detail dialog
api.statusbar_applet_manager.start_auto_update()
api.statusbar_applet_manager.stop_auto_update()
```

### IM Module Manager
```python
api.im_module_manager.modules                             # [{'id': str, 'name': str, ...}]
api.im_module_manager.get_status_text(module_id)         # status suffix, e.g. "- connected as jan"
api.im_module_manager.open_module(module_id, parent)     # open the IM module window
```

### Control Methods
```python
api.show_settings()                        # open TCE Settings window (wx dialog)
api.request_exit()                         # graceful wx event loop exit
api.force_exit()                           # hard shutdown: stops services + os._exit(0)
api.register_shutdown_callback(callback)   # called when TCE is shutting down
api.has_feature('applications')            # check if feature is enabled (bool)

# Minimize/tray support:
api.register_minimize_handler(callback)    # callback: hides your window
api.register_restore_handler(callback)     # callback: shows your window
api.minimize_launcher()                    # hides window + shows TCE tray icon → bool
api.restore_launcher()                     # shows window + hides tray icon → bool
api.is_minimized                           # bool
api.supports_minimize                      # bool (True if handlers registered)

# Invisible UI:
api.start_invisible_ui()                   # start tilde-key overlay (requires invisible_ui=true)
api.stop_invisible_ui()                    # stop tilde-key overlay
```

## LauncherAPI — Conditional (based on `[features]`)

```python
# Applications (features.applications = true):
apps = api.get_applications()              # [{'name': str, 'name_en': str, 'shortname': str, ...}]
api.open_application(app_dict)             # launch an application
api.find_application_by_shortname('tedit')

# Games (features.games = true):
games = api.get_games()                    # [{'name': str, 'platform': str, ...}]
api.get_games_by_platform('Titan')
api.open_game(game_dict)

# Titan IM (features.titan_im = true):
api.titan_net_client                       # TitanNetClient or None
api.open_telegram()                        # open Telegram login dialog
api.open_messenger()                       # open Facebook Messenger
api.open_whatsapp()                        # open WhatsApp
api.open_titannet()                        # open Titan-Net login
api.open_eltenlink()                       # open EltenLink login

# IM modules via im_module_manager (always available):
for mod in api.im_module_manager.modules:
    status = api.im_module_manager.get_status_text(mod['id'])
    api.im_module_manager.open_module(mod['id'], parent_frame)

# Help (features.help = true):
api.show_help()

# Components (features.components = true):
api.get_components()
api.get_component_menu_functions()         # [(label, callback), ...]

# Notifications (features.notifications = true):
api.notifications                           # notifications manager object

# Invisible UI (features.invisible_ui = true):
api.invisible_ui                            # InvisibleUI instance
```

## Component Hooks for Launchers

Components can hook into launcher startup via `get_launcher_hooks()` in their `init.py`:

```python
# In a component's init.py:
def get_launcher_hooks():
    def on_launcher_init(launcher_manager, launcher_name):
        print(f"Launcher '{launcher_name}' started, can customize here")
    return {'on_launcher_init': on_launcher_init}
```

## Translation Setup (Optional)

```bash
# 1. Create languages directory inside the launcher folder
mkdir data/launchers/{folder_name}/languages

# 2. Extract translatable strings from init.py
pybabel extract -o languages/{folder_name}.pot --no-default-keywords --keyword=_ data/launchers/{folder_name}/init.py

# 3. Initialize language
pybabel init -l pl -d languages -i languages/{folder_name}.pot -D {folder_name}
pybabel init -l en -d languages -i languages/{folder_name}.pot -D {folder_name}

# 4. Compile
pybabel compile -d data/launchers/{folder_name}/languages
```

Usage in `init.py`:
```python
def start(api):
    _ = api.load_translations('my_launcher')  # loads from launcher's languages/
    print(_("Hello"))
```

## Verify Installation

- Run: `python main.py --startup-mode launcher --launcher {folder_name}`
- Check console output for `[LauncherManager] Starting launcher: {name}`
- Verify your window appears and shows apps/games
- Test Escape key minimizes (if minimize handlers registered)
- Test Exit button calls `api.force_exit()`
- Test sound feedback (focus, select, startup)

---

## Multiplatform Requirements

All TCE launchers MUST work on **Windows, macOS, and Linux**.

### Choosing a GUI library

| Library | Extra deps | Event loop |
|---------|-----------|------------|
| **wxPython** | None (already required by TCE) | Shared — just create wx.Frame and return from `start()` |
| **tkinter** | None (Python stdlib) | Own — run `root.mainloop()` in daemon thread |
| **PyQt5** | `pip install PyQt5` | Own — run `app.exec_()` in daemon thread |
| **pygame** | `pip install pygame` | Own — run game loop in daemon thread |

### wxPython pattern (shared wx event loop)
```python
def start(api):
    import wx
    frame = MyFrame(None, api)
    frame.Show()
    api.play_startup_sound()
    # wx.MainLoop() already running in main.py — start() returns, frame stays alive
```

### Non-wx pattern (daemon thread with own event loop)
```python
import threading

def start(api):
    t = threading.Thread(target=_run_ui, args=(api,), daemon=True)
    t.start()
    # Returns immediately — UI runs in background

def _run_ui(api):
    import tkinter as tk
    root = tk.Tk()
    # ... build UI ...
    root.mainloop()
```

### Opening files/URLs (cross-platform)
```python
import sys, subprocess, os
if sys.platform == 'win32':
    os.startfile(path)           # Windows only
elif sys.platform == 'darwin':
    subprocess.Popen(['open', path])
else:
    subprocess.Popen(['xdg-open', path])
# URLs: always use webbrowser.open(url)
```

### accessible_output3 — always try/except
```python
# api.speaker is already a safe ao3 speaker — use it directly.
# If you need your own speaker instance:
try:
    import accessible_output3.outputs.auto as _ao3
    my_speaker = _ao3.Auto()
except Exception:
    my_speaker = None
```

### keyboard library — guard on macOS
```python
import sys
KEYBOARD_AVAILABLE = False
if sys.platform != 'darwin':
    try:
        import keyboard
        KEYBOARD_AVAILABLE = True
    except ImportError:
        pass
```

### Common mistakes
- Creating a new `wx.App()` in the launcher — **do not**, use `api.wx_app` for wx dialogs
- Blocking in `start()` — own GUI event loops MUST run in a daemon thread (except wxPython)
- `os.environ['APPDATA']` → use `os.getenv('APPDATA') or os.path.expanduser('~')`
- `os.startfile(path)` → Windows only, use platform check above
- `os.sys.platform` → **AttributeError!** Use `sys.platform` (after `import sys`)

---

## Complete Code Examples

### Example 1: wxPython Launcher

A full-featured wxPython launcher with application list, game list, statusbar section, Titan IM communicators, minimize-to-tray support, and full sound feedback. Uses the shared wx event loop — no daemon thread needed.

**File: `data/launchers/simple_wx/__launcher__.TCE`**
```ini
[launcher]
name = Simple WX Launcher
description = A minimal accessible wxPython launcher for TCE
author = TCE Launcher
version = 1.0
status = 0

[features]
applications = true
games = true
titan_im = true
help = true
components = false
system_hooks = true
notifications = true
sound = true
invisible_ui = false
```

**File: `data/launchers/simple_wx/init.py`**
```python
# -*- coding: utf-8 -*-
"""
Simple WX Launcher — minimal wxPython launcher for TCE.

wxPython shares the event loop with TCE, so start() just creates a
wx.Frame and returns. No daemon thread needed.

Escape minimizes to tray, window close / Exit button quits TCE entirely.
"""

import wx

_api = None
_frame = None


def start(api):
    """Entry point — creates the launcher frame and returns immediately."""
    global _api, _frame
    _api = api

    frame = SimpleLauncherFrame(None, api)
    _frame = frame

    # Register minimize/restore for tray icon support
    def do_minimize():
        wx.CallAfter(frame.Hide)

    def do_restore():
        wx.CallAfter(frame.Show)
        wx.CallAfter(frame.Raise)

    api.register_minimize_handler(do_minimize)
    api.register_restore_handler(do_restore)

    # Show frame and play startup sound after event loop starts
    wx.CallAfter(frame.Show)
    wx.CallAfter(api.play_startup_sound)

    # Start Invisible UI overlay (requires invisible_ui=true in config)
    api.start_invisible_ui()


class SimpleLauncherFrame(wx.Frame):
    """Main launcher window."""

    def __init__(self, parent, api):
        _ = api._
        super().__init__(
            parent,
            title=f"TCE {api.version}",
            size=(720, 620),
        )
        self.api = api
        self._apps = []
        self._games = []
        self._im_items = []   # list of (display_name, im_type, im_id)
        self._sb_builtin_count = 0

        self._build_ui()
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _build_ui(self):
        api = self.api
        _ = api._
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Applications ---
        if api.get_applications:
            self._apps = api.get_applications() or []
            if self._apps:
                sizer.Add(wx.StaticText(panel, label=_("Applications")), 0, wx.LEFT | wx.TOP, 8)
                self.app_list = wx.ListBox(panel)
                for app in self._apps:
                    self.app_list.Append(app.get('name', app.get('name_en', '?')))
                self.app_list.Bind(wx.EVT_LISTBOX, lambda e: api.play_focus_sound())
                self.app_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_app_activate)
                sizer.Add(self.app_list, 2, wx.EXPAND | wx.ALL, 5)

        # --- Games ---
        if api.get_games:
            self._games = api.get_games() or []
            if self._games:
                sizer.Add(wx.StaticText(panel, label=_("Games")), 0, wx.LEFT | wx.TOP, 8)
                self.game_list = wx.ListBox(panel)
                for g in self._games:
                    name = g.get('name', '?')
                    plat = g.get('platform', '')
                    self.game_list.Append(f"{name} ({plat})" if plat else name)
                self.game_list.Bind(wx.EVT_LISTBOX, lambda e: api.play_focus_sound())
                self.game_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_game_activate)
                sizer.Add(self.game_list, 2, wx.EXPAND | wx.ALL, 5)

        # --- Titan IM ---
        if api.has_feature('titan_im'):
            sizer.Add(wx.StaticText(panel, label=_("Titan IM")), 0, wx.LEFT | wx.TOP, 8)
            self.im_list = wx.ListBox(panel)

            if api.titan_net_client:
                self._im_items.append((_("Titan-Net"), 'titannet', None))
                self.im_list.Append(_("Titan-Net"))
            for label, im_type in [
                (_("Telegram"), 'telegram'),
                (_("Facebook Messenger"), 'messenger'),
                (_("WhatsApp"), 'whatsapp'),
                (_("EltenLink"), 'eltenlink'),
            ]:
                self._im_items.append((label, im_type, None))
                self.im_list.Append(label)
            if api.im_module_manager:
                for mod in api.im_module_manager.modules:
                    status = api.im_module_manager.get_status_text(mod['id'])
                    display = f"{mod['name']} {status}" if status else mod['name']
                    self._im_items.append((display, 'im_module', mod['id']))
                    self.im_list.Append(display)

            if self._im_items:
                self.im_list.Bind(wx.EVT_LISTBOX, lambda e: api.play_focus_sound())
                self.im_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_im_activate)
                sizer.Add(self.im_list, 1, wx.EXPAND | wx.ALL, 5)

        # --- Statusbar ---
        if api.statusbar_applet_manager:
            sizer.Add(wx.StaticText(panel, label=_("Status Bar")), 0, wx.LEFT | wx.TOP, 8)
            self.sb_list = wx.ListBox(panel)
            self._refresh_statusbar()
            self.sb_list.Bind(wx.EVT_LISTBOX, lambda e: api.play_statusbar_sound())
            self.sb_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_sb_activate)
            sizer.Add(self.sb_list, 1, wx.EXPAND | wx.ALL, 5)

            self._sb_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_sb_timer, self._sb_timer)
            self._sb_timer.Start(2000)

        # --- Buttons ---
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        if api.show_help:
            h = wx.Button(panel, label=_("Help"))
            h.Bind(wx.EVT_BUTTON, lambda e: (api.play_dialog_sound(), api.show_help()))
            btn_sizer.Add(h, 0, wx.ALL, 5)
        s = wx.Button(panel, label=_("Settings"))
        s.Bind(wx.EVT_BUTTON, lambda e: (api.play_dialog_sound(), api.show_settings()))
        btn_sizer.Add(s, 0, wx.ALL, 5)
        x = wx.Button(panel, label=_("Exit"))
        x.Bind(wx.EVT_BUTTON, self._on_close)
        btn_sizer.Add(x, 0, wx.ALL, 5)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        panel.SetSizer(sizer)

        # Focus first available list
        for attr in ('app_list', 'game_list', 'im_list'):
            ctrl = getattr(self, attr, None)
            if ctrl and ctrl.GetCount() > 0:
                ctrl.SetFocus()
                ctrl.SetSelection(0)
                break

    def _refresh_statusbar(self):
        items = self.api.statusbar_applet_manager.get_statusbar_items()
        builtin = self.api.statusbar_applet_manager.get_builtin_items()
        self._sb_builtin_count = len(builtin)
        self.sb_list.Clear()
        for text in items:
            self.sb_list.Append(text)

    def _on_app_activate(self, event):
        idx = self.app_list.GetSelection()
        if 0 <= idx < len(self._apps):
            self.api.play_select_sound()
            self.api.open_application(self._apps[idx])

    def _on_game_activate(self, event):
        idx = self.game_list.GetSelection()
        if 0 <= idx < len(self._games):
            self.api.play_select_sound()
            self.api.open_game(self._games[idx])

    def _on_im_activate(self, event):
        idx = self.im_list.GetSelection()
        if not (0 <= idx < len(self._im_items)):
            return
        _, im_type, im_id = self._im_items[idx]
        self.api.play_select_sound()
        dispatch = {
            'titannet':  self.api.open_titannet,
            'telegram':  self.api.open_telegram,
            'messenger': self.api.open_messenger,
            'whatsapp':  self.api.open_whatsapp,
            'eltenlink': self.api.open_eltenlink,
        }
        if im_type in dispatch:
            dispatch[im_type]()
        elif im_type == 'im_module' and self.api.im_module_manager:
            self.api.im_module_manager.open_module(im_id, None)

    def _on_sb_activate(self, event):
        idx = self.sb_list.GetSelection()
        applet_idx = idx - self._sb_builtin_count
        names = self.api.statusbar_applet_manager.get_applet_names()
        if 0 <= applet_idx < len(names):
            self.api.play_select_sound()
            self.api.statusbar_applet_manager.activate_applet(names[applet_idx])

    def _on_sb_timer(self, event):
        items = self.api.statusbar_applet_manager.get_statusbar_items()
        for i, text in enumerate(items):
            if i < self.sb_list.GetCount():
                self.sb_list.SetString(i, text)

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.api.minimize_launcher()
        else:
            event.Skip()

    def _on_close(self, event=None):
        self.api.play_dialogclose_sound()
        self.api.force_exit()


def shutdown():
    """Called when TCE is shutting down."""
    global _frame
    try:
        if _api:
            _api.stop_invisible_ui()
    except Exception:
        pass
    try:
        if _frame:
            wx.CallAfter(_frame.Destroy)
    except Exception:
        pass
    _frame = None
```

---

### Example 2: tkinter Launcher

A cross-platform tkinter launcher with no extra dependencies (tkinter is part of the Python standard library). Runs in a daemon thread with its own `mainloop()`. Shows applications, a combined statusbar line, and settings/exit buttons.

**File: `data/launchers/simple_tk/__launcher__.TCE`**
```ini
[launcher]
name = Simple Tkinter Launcher
description = A lightweight tkinter launcher for TCE with no extra dependencies
author = TCE Launcher
version = 1.0
status = 0

[features]
applications = true
games = false
titan_im = false
help = true
components = false
system_hooks = true
notifications = false
sound = true
invisible_ui = false
```

**File: `data/launchers/simple_tk/init.py`**
```python
# -*- coding: utf-8 -*-
"""
Simple tkinter Launcher — cross-platform, no extra dependencies.

tkinter has its own event loop so it runs in a daemon thread.
start() launches that thread and returns immediately.

Escape minimizes (hides window), window close / Exit exits TCE entirely.
"""

import sys
import threading

_api = None
_root = None


def start(api):
    """Launch tkinter UI in a daemon thread and return immediately."""
    global _api
    _api = api
    t = threading.Thread(target=_run_ui, args=(api,), daemon=True)
    t.start()


def _run_ui(api):
    """Build and run the tkinter UI. Runs in a daemon thread."""
    global _root
    import tkinter as tk
    from tkinter import font as tkfont

    _ = api._

    root = tk.Tk()
    _root = root
    root.title(f"TCE {api.version}")
    root.geometry("640x520")
    root.resizable(True, True)

    bold_font = tkfont.Font(weight="bold", size=11)

    # --- Applications ---
    apps = []
    if api.get_applications:
        apps = api.get_applications() or []

    if apps:
        tk.Label(root, text=_("Applications"), font=bold_font).pack(
            anchor="w", padx=10, pady=(10, 0)
        )

        frame_list = tk.Frame(root)
        frame_list.pack(fill="both", expand=True, padx=10, pady=5)

        scrollbar = tk.Scrollbar(frame_list, orient="vertical")
        app_listbox = tk.Listbox(
            frame_list,
            yscrollcommand=scrollbar.set,
            activestyle="dotbox",
            height=14,
        )
        scrollbar.config(command=app_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        app_listbox.pack(side="left", fill="both", expand=True)

        for app in apps:
            name = app.get('name', app.get('name_en', '?'))
            app_listbox.insert(tk.END, name)

        def _on_app_select(event):
            api.play_focus_sound()

        def _on_app_activate(event):
            sel = app_listbox.curselection()
            if sel and 0 <= sel[0] < len(apps):
                api.play_select_sound()
                api.open_application(apps[sel[0]])

        app_listbox.bind("<<ListboxSelect>>", _on_app_select)
        app_listbox.bind("<Return>", _on_app_activate)
        app_listbox.bind("<Double-Button-1>", _on_app_activate)

        if apps:
            app_listbox.selection_set(0)
            app_listbox.focus_set()

    # --- Statusbar (single line showing all items joined) ---
    sb_text_var = tk.StringVar(value="")
    if api.statusbar_applet_manager:
        tk.Label(root, text=_("Status"), font=bold_font).pack(
            anchor="w", padx=10, pady=(6, 0)
        )
        tk.Label(
            root,
            textvariable=sb_text_var,
            anchor="w",
            wraplength=600,
            justify="left",
        ).pack(fill="x", padx=10, pady=2)

        def _refresh_statusbar():
            try:
                items = api.statusbar_applet_manager.get_statusbar_items()
                sb_text_var.set("  |  ".join(items))
            except Exception:
                pass
            root.after(2000, _refresh_statusbar)

        root.after(200, _refresh_statusbar)

    # --- Buttons ---
    btn_frame = tk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=10)

    if api.show_help:
        def _on_help():
            api.play_dialog_sound()
            api.show_help()
        tk.Button(btn_frame, text=_("Help"), command=_on_help, width=12).pack(
            side="left", padx=5
        )

    def _on_settings():
        api.play_dialog_sound()
        api.show_settings()

    tk.Button(btn_frame, text=_("Settings"), command=_on_settings, width=12).pack(
        side="left", padx=5
    )

    def _on_exit():
        api.play_dialogclose_sound()
        api.force_exit()

    tk.Button(btn_frame, text=_("Exit"), command=_on_exit, width=12).pack(
        side="right", padx=5
    )

    # --- Minimize/restore (hide/show window) ---
    # Note: root.after() is used so callbacks run on the tkinter thread
    def do_minimize():
        root.after(0, root.withdraw)

    def do_restore():
        root.after(0, root.deiconify)
        root.after(10, root.lift)

    api.register_minimize_handler(do_minimize)
    api.register_restore_handler(do_restore)

    root.bind('<Escape>', lambda e: api.minimize_launcher())
    root.protocol("WM_DELETE_WINDOW", _on_exit)

    # Start Invisible UI overlay if enabled in config
    api.start_invisible_ui()

    # Play startup sound (pygame-based, thread-safe)
    api.play_startup_sound()

    root.mainloop()


def shutdown():
    """Called when TCE is shutting down."""
    global _root
    try:
        if _api:
            _api.stop_invisible_ui()
    except Exception:
        pass
    try:
        if _root:
            _root.after(0, _root.destroy)
    except Exception:
        pass
    _root = None
```

---

## Action:

Ask the user for launcher details and create a complete, working launcher in `data/launchers/` following the TCE Launcher standard, with full LauncherAPI integration, sound feedback, minimize support, and multiplatform compatibility.
