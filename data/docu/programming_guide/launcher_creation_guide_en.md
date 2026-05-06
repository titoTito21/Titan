# TCE Launcher Creation Guide

## Introduction

**Launchers** are alternative graphical interfaces for TCE. They completely replace the standard TCE GUI with a custom window built using **any Python GUI library** (wxPython, PyQt5, tkinter, pygame, kivy, ...). TCE keeps running in the background and exposes all services (applications, games, sound, settings, Titan IM, statusbar, components) through the `LauncherAPI` object passed to the launcher's `start()` function.

**Only one launcher can run at a time.**

### Running

From the command line:
```bash
python main.py --startup-mode launcher --launcher folder_name
```

Or in `settings.json`:
```ini
[general]
startup_mode = launcher
launcher = folder_name
```

## Architecture

```
data/launchers/my_launcher/
├── __launcher__.TCE     # Configuration (REQUIRED, .TCE in uppercase)
├── init.py              # Entry point with start(api) function (REQUIRED)
├── languages/           # Launcher-local translations (optional)
│   ├── pl/LC_MESSAGES/launcher.po/.mo
│   └── en/LC_MESSAGES/launcher.po/.mo
└── lib/                 # Bundled dependencies (optional)
```

`LauncherManager` scans `data/launchers/` at TCE startup, finds directories containing `__launcher__.TCE`, parses configuration, and launches the selected launcher.

## Configuration file `__launcher__.TCE`

INI format with two sections: `[launcher]` and `[features]`.

```ini
[launcher]
name = My Launcher
description = Short description
author = Your Name
version = 1.0
status = 0
libs = lib, vendor

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

### `[launcher]` fields

| Field | Required | Description |
|-------|----------|-------------|
| name | no | Display name (defaults to folder name) |
| description | no | Short description |
| author | no | Author |
| version | no | Version string (default `1.0`) |
| status | yes | **`0` = enabled, `1` = disabled** (same convention as components) |
| libs | no | Comma-separated list of bundled library subdirs (default: `lib`) |

### `[features]` fields

All values are `true` or `false`. Missing fields use their default.

| Feature | Default | What it unlocks |
|---------|---------|-----------------|
| applications | true | `api.get_applications()`, `api.open_application()` |
| games | true | `api.get_games()`, `api.open_game()` |
| titan_im | true | `api.titan_net_client`, `api.open_telegram()`, `api.open_messenger()`, ... |
| help | true | `api.show_help()` |
| components | true | `api.get_components()`, `api.get_component_menu_functions()` |
| system_hooks | true | OS-level hooks (Win key, lockscreen, ...) |
| notifications | true | `api.notifications` |
| sound | true | Full TCE sound system (always available regardless) |
| invisible_ui | false | `api.start_invisible_ui()` (tilde key overlay) |

## `init.py` implementation

The file MUST be named exactly `init.py` (or `init.pyc`).

A launcher MUST define:
- `start(api)` — entry point, called once at startup. **Must return quickly.**

A launcher MAY define:
- `shutdown()` — called when TCE shuts down.

### Skeleton

```python
# -*- coding: utf-8 -*-
def start(api):
    """Entry point. Must return quickly."""
    # wxPython: just create wx.Frame and return (wx.MainLoop is already running)
    # PyQt5/tkinter/pygame: start your own event loop in a daemon thread

def shutdown():
    """Optional: called when TCE is shutting down."""
    pass
```

**IMPORTANT:**
- For **wxPython**, just create a `wx.Frame` and return — `wx.MainLoop()` is already running in `main.py`.
- For **other libraries** (tkinter, PyQt5, pygame) you MUST run your event loop in a daemon thread, otherwise you block TCE.
- **Never** create a new `wx.App()` — use `api.wx_app` if you need wx dialogs.

## LauncherAPI

The `api` object passed to `start(api)` is the gateway to all TCE services.

### Always available (regardless of `[features]`)

#### Settings
```python
api.get_setting(key, default='', section='general')
api.set_setting(key, value, section='general')
api.load_settings()           # returns full settings dict
api.save_settings()
```

#### Translation
```python
_ = api._                              # TCE's built-in translation function
api.language_code                      # current language code, e.g. 'pl'
_ = api.load_translations()            # load own languages/ dir (domain='launcher')
_ = api.load_translations('my_name')   # custom domain
api.set_language(lang_code)
api.get_available_languages()
```

#### Sound (full TCE sound system)
```python
api.play_sound('ui/dialog.ogg')        # any sfx file from current theme
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
api.resource_path('sfx/sound.ogg')     # absolute path to TCE resource
api.get_sfx_directory()                # current sfx theme directory
```

#### Speaker (TTS)
```python
api.speaker.speak("Hello")
api.speaker.speak(text, interrupt=True)
# api.speaker is a ready-to-use accessible_output3 Auto()
```

#### Stereo speech (panning + pitch)
```python
api.speak_stereo(text, position=0.0, interrupt=True, pitch_offset=0)
api.stop_stereo_speech()
api.get_stereo_speech()                # StereoSpeech instance or None
```

#### Controller vibrations
```python
api.vibrate_cursor_move()
api.vibrate_selection()
api.vibrate_focus_change()
api.vibrate_error()
api.vibrate_notification()
api.vibrate_startup()
api.set_vibration_enabled(True)
api.set_vibration_strength(0.7)
```

#### Statusbar
```python
api.statusbar_applet_manager.get_statusbar_items()    # all texts as [str]
api.statusbar_applet_manager.get_builtin_items()      # built-in only (Clock, Battery, ...)
api.statusbar_applet_manager.get_applet_names()       # loaded applet names
api.statusbar_applet_manager.get_all_applet_texts()   # applet texts only
api.statusbar_applet_manager.activate_applet(name)    # open applet detail dialog
api.statusbar_applet_manager.start_auto_update()
api.statusbar_applet_manager.stop_auto_update()
```

#### IM modules (communicators)
```python
for mod in api.im_module_manager.modules:
    print(mod['id'], mod['name'])
    status = api.im_module_manager.get_status_text(mod['id'])
    api.im_module_manager.open_module(mod['id'], parent_window)
```

#### Launcher control
```python
api.show_settings()                        # open TCE Settings window
api.request_exit()                         # graceful wx loop exit
api.force_exit()                           # hard shutdown + os._exit(0)
api.register_shutdown_callback(callback)   # called when shutting down
api.has_feature('applications')            # whether feature is enabled (bool)
api.check_for_updates()                    # check for TCE updates

# Minimize to tray:
api.register_minimize_handler(callback)    # callback hides your window
api.register_restore_handler(callback)     # callback shows your window
api.minimize_launcher()                    # hides window + shows tray icon → bool
api.restore_launcher()                     # shows window + hides tray icon → bool
api.is_minimized                           # bool
api.supports_minimize                      # bool

# Invisible UI (tilde key overlay):
api.start_invisible_ui()                   # requires invisible_ui=true in config
api.stop_invisible_ui()
```

#### Window switcher
```python
api.show_window_switcher(parent=None)
api.register_window(window, name)
api.unregister_window(window)
```

#### Metadata
```python
api.version           # TCE version, e.g. "2.1.0"
api.launcher_path     # absolute path to launcher's directory
api.wx_app            # wx.App instance (for wx dialogs from non-wx launchers)
```

### Conditional (based on `[features]`)

#### Applications (`features.applications = true`)
```python
apps = api.get_applications()             # [{'name': str, 'name_en': str, 'shortname': str, ...}]
api.open_application(app_dict)            # launch an application
api.find_application_by_shortname('tedit')
```

#### Games (`features.games = true`)
```python
games = api.get_games()                   # [{'name': str, 'platform': str, ...}]
api.get_games_by_platform('Titan')
api.open_game(game_dict)
```

#### Titan IM (`features.titan_im = true`)
```python
api.titan_net_client                      # TitanNetClient or None
api.open_telegram()                       # Telegram login dialog
api.open_messenger()                      # Facebook Messenger
api.open_whatsapp()                       # WhatsApp
api.open_titannet()                       # Titan-Net (login + main window on success)
api.open_eltenlink()                      # EltenLink
api.open_im_module('name_or_id')          # opens IM module by name/id
```

#### Help (`features.help = true`)
```python
api.show_help()
```

#### Components (`features.components = true`)
```python
api.get_components()
api.get_component_menu_functions()        # [(label, callback), ...]
```

#### Notifications (`features.notifications = true`)
```python
api.notifications                         # notifications manager
```

#### Invisible UI (`features.invisible_ui = true`)
```python
api.invisible_ui                          # InvisibleUI instance
```

## Component hooks for launchers

Components can react to launcher startup by defining `get_launcher_hooks()` in their `init.py`:

```python
# In a component's init.py:
def get_launcher_hooks():
    def on_launcher_init(launcher_manager, launcher_name):
        print(f"Launcher '{launcher_name}' started, customize here")
    return {'on_launcher_init': on_launcher_init}
```

## Launcher translations

```bash
# 1. Create languages/ directory inside the launcher folder
mkdir data/launchers/my_launcher/languages

# 2. Extract translatable strings from init.py
pybabel extract -o languages/launcher.pot --no-default-keywords --keyword=_ \
    data/launchers/my_launcher/init.py

# 3. Initialize languages
pybabel init -l pl -d data/launchers/my_launcher/languages \
    -i data/launchers/my_launcher/languages/launcher.pot -D launcher
pybabel init -l en -d data/launchers/my_launcher/languages \
    -i data/launchers/my_launcher/languages/launcher.pot -D launcher

# 4. Compile
pybabel compile -d data/launchers/my_launcher/languages
```

In `init.py`:
```python
def start(api):
    _ = api.load_translations()           # loads launcher.mo from languages/
    print(_("Hello"))
```

## Multiplatform requirements

Every launcher MUST work on **Windows, macOS, and Linux**.

### Choosing a GUI library

| Library | Extra deps | Event loop |
|---------|-----------|------------|
| **wxPython** | None (already required by TCE) | Shared — just create wx.Frame and return from `start()` |
| **tkinter** | None (Python stdlib) | Own — `root.mainloop()` in daemon thread |
| **PyQt5** | `pip install PyQt5` | Own — `app.exec_()` in daemon thread |
| **pygame** | `pip install pygame` | Own — game loop in daemon thread |

### Opening files/URLs (cross-platform)
```python
import sys, subprocess, os
if sys.platform == 'win32':
    os.startfile(path)
elif sys.platform == 'darwin':
    subprocess.Popen(['open', path])
else:
    subprocess.Popen(['xdg-open', path])

# URLs: always webbrowser.open(url)
```

### `keyboard` library — guard on macOS
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
- Creating a new `wx.App()` — **don't**, use `api.wx_app`.
- Blocking in `start()` — own event loops MUST run in a daemon thread (except wxPython).
- `os.environ['APPDATA']` → `os.getenv('APPDATA') or os.path.expanduser('~')`.
- `os.startfile(path)` → Windows only, use the platform check above.
- `os.sys.platform` → **AttributeError!** Correct: `sys.platform` (after `import sys`).

## Example 1: wxPython launcher

A complete wxPython launcher with application/game lists, Titan IM, statusbar, sound feedback, and tray support. Uses the shared wx event loop — no daemon thread.

**File: `data/launchers/simple_wx/__launcher__.TCE`**
```ini
[launcher]
name = Simple WX Launcher
description = A minimal accessible wxPython launcher for TCE
author = TCE Team
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
import wx

_api = None
_frame = None


def start(api):
    """Entry point — creates the frame and returns immediately."""
    global _api, _frame
    _api = api

    frame = SimpleLauncherFrame(None, api)
    _frame = frame

    api.register_minimize_handler(lambda: wx.CallAfter(frame.Hide))
    api.register_restore_handler(lambda: (wx.CallAfter(frame.Show),
                                           wx.CallAfter(frame.Raise)))

    wx.CallAfter(frame.Show)
    wx.CallAfter(api.play_startup_sound)
    api.start_invisible_ui()


class SimpleLauncherFrame(wx.Frame):
    def __init__(self, parent, api):
        _ = api._
        super().__init__(parent, title=f"TCE {api.version}", size=(720, 620))
        self.api = api
        self._apps = []
        self._games = []
        self._build_ui()
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _build_ui(self):
        api = self.api
        _ = api._
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

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

        btns = wx.BoxSizer(wx.HORIZONTAL)
        s = wx.Button(panel, label=_("Settings"))
        s.Bind(wx.EVT_BUTTON, lambda e: (api.play_dialog_sound(), api.show_settings()))
        btns.Add(s, 0, wx.ALL, 5)
        x = wx.Button(panel, label=_("Exit"))
        x.Bind(wx.EVT_BUTTON, self._on_close)
        btns.Add(x, 0, wx.ALL, 5)
        sizer.Add(btns, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        panel.SetSizer(sizer)

        for attr in ('app_list', 'game_list'):
            ctrl = getattr(self, attr, None)
            if ctrl and ctrl.GetCount() > 0:
                ctrl.SetFocus()
                ctrl.SetSelection(0)
                break

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

    def _on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.api.minimize_launcher()
        else:
            event.Skip()

    def _on_close(self, event=None):
        self.api.play_dialogclose_sound()
        self.api.force_exit()


def shutdown():
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

## Example 2: tkinter launcher

A cross-platform launcher with no extra dependencies (tkinter is in stdlib). Runs in a daemon thread with its own `mainloop()`.

**File: `data/launchers/simple_tk/__launcher__.TCE`**
```ini
[launcher]
name = Simple Tkinter Launcher
description = Lightweight tkinter launcher for TCE with no extra deps
author = TCE Team
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
import threading

_api = None
_root = None


def start(api):
    """Run tkinter UI in a daemon thread and return immediately."""
    global _api
    _api = api
    threading.Thread(target=_run_ui, args=(api,), daemon=True).start()


def _run_ui(api):
    global _root
    import tkinter as tk
    from tkinter import font as tkfont

    _ = api._
    root = tk.Tk()
    _root = root
    root.title(f"TCE {api.version}")
    root.geometry("640x520")

    bold_font = tkfont.Font(weight="bold", size=11)

    apps = api.get_applications() if api.get_applications else []

    if apps:
        tk.Label(root, text=_("Applications"), font=bold_font).pack(
            anchor="w", padx=10, pady=(10, 0))
        listbox = tk.Listbox(root, height=14)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        for app in apps:
            listbox.insert(tk.END, app.get('name', app.get('name_en', '?')))

        listbox.bind("<<ListboxSelect>>", lambda e: api.play_focus_sound())

        def on_activate(event):
            sel = listbox.curselection()
            if sel and 0 <= sel[0] < len(apps):
                api.play_select_sound()
                api.open_application(apps[sel[0]])

        listbox.bind("<Return>", on_activate)
        listbox.bind("<Double-Button-1>", on_activate)
        listbox.selection_set(0)
        listbox.focus_set()

    btn_frame = tk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=10)

    tk.Button(btn_frame, text=_("Settings"),
              command=lambda: (api.play_dialog_sound(), api.show_settings())
              ).pack(side="left", padx=5)

    def on_exit():
        api.play_dialogclose_sound()
        api.force_exit()

    tk.Button(btn_frame, text=_("Exit"), command=on_exit).pack(side="right", padx=5)

    api.register_minimize_handler(lambda: root.after(0, root.withdraw))
    api.register_restore_handler(lambda: (root.after(0, root.deiconify),
                                           root.after(10, root.lift)))
    root.bind('<Escape>', lambda e: api.minimize_launcher())
    root.protocol("WM_DELETE_WINDOW", on_exit)

    api.play_startup_sound()
    root.mainloop()


def shutdown():
    global _root
    try:
        if _root:
            _root.after(0, _root.destroy)
    except Exception:
        pass
    _root = None
```

## Example 3: PyQt5 launcher

The full launcher in `data/launchers/example_launcher/init.py` — application/game lists, Titan IM, statusbar with 2-second timer updates, tray support, Invisible UI, and full sound feedback.

**File: `data/launchers/example_launcher/__launcher__.TCE`** — see [example_launcher](../../launchers/example_launcher/__launcher__.TCE) in the repository.

**File: `data/launchers/example_launcher/init.py`** — full PyQt5 implementation (~340 lines) is in the repo. Key fragments:

```python
import sys
import threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QListWidget, QPushButton, QShortcut)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence

_api = None
_qt_app = None
_window = None


def start(api):
    """Run PyQt5 in a daemon thread — Qt has its own event loop."""
    global _api
    _api = api
    threading.Thread(target=_run_pyqt_ui, daemon=True).start()


def _run_pyqt_ui():
    global _window, _qt_app
    _ = _api._

    _qt_app = QApplication(sys.argv)
    _qt_app.setQuitOnLastWindowClosed(False)
    window = QMainWindow()
    _window = window
    window.setWindowTitle(f"TCE v{_api.version}")
    window.resize(700, 600)

    central = QWidget()
    layout = QVBoxLayout(central)
    window.setCentralWidget(central)

    apps = (_api.get_applications() or []) if _api.get_applications else []
    if apps:
        listw = QListWidget()
        for app in apps:
            listw.addItem(app.get('name', app.get('name_en', '?')))
        listw.currentItemChanged.connect(lambda *a: _api.play_focus_sound())
        listw.itemActivated.connect(
            lambda item: (_api.play_select_sound(),
                          _api.open_application(apps[listw.row(item)])))
        layout.addWidget(listw)

    # Statusbar with 2-second timer updates
    if _api.statusbar_applet_manager:
        sb = QListWidget()
        for text in _api.statusbar_applet_manager.get_statusbar_items():
            sb.addItem(text)
        layout.addWidget(sb)

        timer = QTimer(window)
        def update_sb():
            items = _api.statusbar_applet_manager.get_statusbar_items()
            for i, text in enumerate(items):
                if i < sb.count():
                    sb.item(i).setText(text)
        timer.timeout.connect(update_sb)
        timer.start(2000)

    # Minimize: Esc -> tray
    _api.register_minimize_handler(lambda: window.hide())
    _api.register_restore_handler(lambda: (window.show(), window.raise_()))
    QShortcut(QKeySequence(Qt.Key_Escape), window).activated.connect(
        _api.minimize_launcher)

    # Window close -> exit TCE
    def closeEvent(event):
        event.ignore()
        _api.play_dialogclose_sound()
        _qt_app.quit()
        _api.force_exit()
    window.closeEvent = closeEvent

    window.show()
    _api.start_invisible_ui()
    _api.play_startup_sound()
    _qt_app.exec_()


def shutdown():
    global _window, _qt_app
    try:
        if _qt_app:
            _qt_app.quit()
    except Exception:
        pass
    _window = None
    _qt_app = None
```

## Verifying the install

1. Run: `python main.py --startup-mode launcher --launcher folder_name`
2. Console should show: `[LauncherManager] Starting launcher: NAME`
3. Your window should appear, lists populated with applications/games.
4. Press Escape — should minimize to tray.
5. Click Exit / close window — TCE should fully shut down.
6. Verify sounds: focus, select, startup, dialog.
7. If `invisible_ui = true` — press tilde, the Invisible UI overlay should appear.

## Key tips

1. **Always set `status = 0`** — otherwise the launcher is disabled.
2. **`init.py` — exact filename**, not `main.py`, not `__init__.py`.
3. **`__launcher__.TCE` — uppercase `.TCE`**, the parser requires it.
4. **Never block `start(api)`** for libraries with their own event loop.
5. **Don't create a new `wx.App()`** — use `api.wx_app` if you need wx dialogs.
6. **Register minimize/restore handlers** — without them `api.minimize_launcher()` is a no-op.
7. **Call `api.force_exit()` on exit** — otherwise TCE leaves an orphan process.
8. **Use `api.has_feature(name)` before calling conditional APIs** — protects against `None`.
9. **Test on every platform** — Windows, macOS, Linux.
10. **Add sound feedback** — TCE is built for blind users, sound cues are essential.
