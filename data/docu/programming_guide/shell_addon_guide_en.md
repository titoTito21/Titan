# TCE Shell Add-on Creation Guide

## Introduction

The **Titan shell** is the desktop, the taskbar, the notification area, the Start menu and the file browser that Titan puts up when *Settings -> Environment -> "Modify system interface"* and *Settings -> Titan shell -> "Replace the desktop, taskbar and Start menu"* are both on. All five are Titan's own code — and a **shell add-on** is how somebody else gets into them without changing Titan.

There are two kinds, and the difference decides everything about how you write one:

| Kind | What it does | How many apply |
|------|--------------|----------------|
| **Contributor** | Adds to what is already there: entries in the Start menu, a menu/toolbar button/column in the file browser, items on the desktop's and the taskbar's context menus, a control in the notification area | Any number, all at once |
| **Provider** | **Replaces** one part of the shell outright — `provides = start_menu` or `provides = explorer` | One, chosen by the user |

A provider replaces a **window**, not the shell: choose somebody else's Start menu and the desktop, the taskbar, the notification area and the file browser carry on exactly as they were.

Add-ons live in `data/shell addons/`. They are the tenth add-on kind, and they deliberately copy the conventions of the other nine — the same manifest style, the same `status = 0` meaning enabled, the same `init.py`, the same packaging.

## Architecture

```
data/shell addons/my_addon/
├── __shell_addon__.TCE   # Manifest (REQUIRED, .TCE in uppercase)
├── init.py               # The code (REQUIRED; init.pyc also accepted)
└── lib/                  # Bundled dependencies (optional)
```

Discovery goes through `platform_utils.discover_data_entries()`, so the same add-on may ship as a **directory** or as a single packaged **`.TCD`** file — see "Packaging" below. Both are found the same way, from the program's own `data/` and from the per-user overlay.

Loading is `src/shell/addons.py`:

1. Every `__shell_addon__.TCE` is read at startup (`ShellAddonManager.scan`).
2. An add-on with `status = 0` is **loaded on demand** — the first time a surface asks it for something, or when the shell starts.
3. `setup(api)` runs once, immediately after the module is imported.
4. Each surface then calls the hooks it cares about, if they exist.

**Nothing an add-on does may take the shell down.** Every call out goes through a guard: a hook that is missing, raises, or answers something that is not a list of entries contributes nothing, and the surface carries on. This matters more than it would anywhere else — with the appbar registered and the shell hook installed, Titan's process is what every other program's broadcasts pass through, so an exception escaping into a paint handler is not a broken add-on, it is a machine that has stopped answering.

## Manifest `__shell_addon__.TCE`

INI format, one section:

```ini
[shell addon]
name = My shell add-on
name_pl = Mój dodatek powłoki
description = What it adds, in one sentence.
description_pl = Co dodaje, jednym zdaniem.
author = Your Name
version = 1.0
status = 1
surfaces = start_menu, explorer
provides =
libs = lib
```

| Field | Required | Description |
|-------|----------|-------------|
| name | no | Display name (defaults to the folder name) |
| name_pl, name_en, ... | no | The name in that language; `name_<code>` wins over `name` |
| description | no | One sentence — shown under a provider's radio button in the properties sheet |
| description_pl, ... | no | The same, translated |
| author | no | Author |
| version | no | Version string (default `1.0`) |
| status | yes | **`0` = enabled, `1` = disabled** (the component convention) |
| surfaces | no | Comma-separated: `shell`, `start_menu`, `explorer`, `taskbar`, `desktop` |
| provides | no | `start_menu` or `explorer` — makes this add-on a **provider** |
| libs | no | Comma-separated subdirectories added to `sys.path` (default: `lib`) |

Notes:

- **`surfaces` is a help, not a gate.** An add-on that names none is asked about everything, because getting this wrong should mean a slightly slower menu rather than an add-on that silently does nothing. Name them anyway: it is what keeps the Start menu fast when twenty add-ons are installed.
- **Ship `status = 1`.** A shell add-on starts doing things the moment it is switched on, so the user switches it on — Settings -> Titan shell -> Shell add-ons. (This is the opposite of a settings interface, which ships `status = 0` because being installed only makes it one of the choices.)
- The name and the description are **your** words, not Titan's translatable strings, which is why `name_pl` / `description_pl` exist instead.

## `init.py`: every hook

Each hook is optional. Titan asks for what is there and skips what is not — an add-on that only wants one entry on the desktop's menu writes `desktop_menu_items` and nothing else.

Every hook is handed `api` first (a `ShellAddonAPI`), then whatever the surface is about.

| Surface | Hook | Signature | Answers |
|---------|------|-----------|---------|
| shell | `setup` | `(api)` | — (called once, at load) |
| shell | `teardown` | `(api)` | — (called when switched off) |
| shell | `on_shell_start` | `(api, shell)` | — (**worker thread**) |
| shell | `on_shell_stop` | `(api, shell)` | — (**worker thread**) |
| start_menu | `start_menu_items` | `(api, menu)` | list of entries |
| explorer | `explorer_menu_items` | `(api, browser)` | list of entries (the Tools menu) |
| explorer | `explorer_toolbar_items` | `(api, browser)` | list of entries (the band) |
| explorer | `explorer_context_items` | `(api, browser, where, selection)` | list of entries |
| explorer | `explorer_columns` | `(api, browser, location)` | list of column entries |
| taskbar | `taskbar_bands` | `(api, taskbar)` | list of control entries |
| taskbar | `taskbar_menu_items` | `(api, taskbar)` | list of entries |
| desktop | `desktop_menu_items` | `(api, desktop, where, entry)` | list of entries |
| provider | `open_start_menu` | `(api, parent)` | a window |
| provider | `open_explorer` | `(api, location, parent, new_window)` | a window |

Every hook except the two providers and the four lifecycle ones runs on the **GUI thread**, because menus, toolbars and lists live there. Anything slow belongs on a thread of your own.

## The entry

A contribution is a plain dict — the same shape `src/ui/program_menu.py` established for "a thing a menu can offer":

```python
{'id': 'copy_path', 'label': "Copy the full path", 'action': copy_path}
```

| Key | Meaning |
|-----|---------|
| `id` | Yours, unique inside your add-on (one is generated if you leave it out) |
| `label` | What it says. **Required** — a menu item with no words is one a screen reader cannot read |
| `action` | A callable taking no arguments, run on the GUI thread |
| `children` | A list of entries — makes a Start menu branch instead of a line |
| `control` | A callable `(parent) -> wx.Window` — a taskbar band |
| `value` | A callable `(entry) -> str` — a file browser column |
| `help` | Tooltip / status bar text (toolbar items) |
| `art` | A `wx.ART_*` id for a toolbar item's picture |
| `width` | Pixels (a taskbar band, a browser column) |

An entry is real if it has something to **do** (`action`), something to **show** (`control`, `value`) or something to **open** (`children`). Anything else is dropped and the reason is printed to the console — a menu item with nothing behind it is a lie.

Titan adds `addon` and `addon_name` to every entry it accepts, which is how the Start menu can say where an entry came from.

## The API object

```python
def start_menu_items(api, menu):
    api.log("asked for my Start menu entries")
    ...
```

| Method | What it gives you |
|--------|-------------------|
| `api.id`, `api.path` | Your add-on's id and folder |
| `api.file(*parts)` | A path inside your own folder — use it for icons, sounds, data |
| `api.shell()` | The running `TitanShell`, or `None` when the shell is not up |
| `api.window(name)` | `'desktop'`, `'taskbar'` or `'start_menu'` |
| `api.run_action(addon, action, **params)` | **Any Titan action** — see the Action API guide |
| `api.setting(key, default)` | A setting of your own (section `shell_addon_<id>`) |
| `api.set_setting(key, value)` | The same, written |
| `api.speak(text)` | Titan's own speech |
| `api.sound(name)` | One of the shell's own sounds |
| `api.log(message)` | A line on the console, prefixed with your id |

`api.run_action` is the important one: it is how an add-on reaches the rest of Titan without this object growing a method per subsystem. `api.run_action('titan', 'open_settings')`, `api.run_action('tedit', 'open_file', path=...)`, `api.run_action('shell', 'list_windows')` — the same calls the AI, a macro and the Action Bus make. Reach for it before you reach for Titan's internals.

## The five surfaces

### 1. The shell itself

```python
def setup(api):
    """Once, when the add-on is loaded."""
    api.log("loaded")


def on_shell_start(api, shell):
    """The desktop, the bar and the Start menu now exist.

    Called on a WORKER thread - `start_shell()` costs about 200 ms and this
    process owns the appbar and the shell hook, so add-ons are loaded and
    told off the GUI thread.  Anything touching a window goes through
    `wx.CallAfter`.
    """
    import wx
    wx.CallAfter(lambda: api.log(str(api.window('taskbar'))))


def on_shell_stop(api, shell):
    """Take down anything of yours that is left."""
```

### 2. The Start menu

One hook feeds **both** built-in menus — the XP two-pane one and the classic one — **and the search box**, because both are built from `src/ui/start_menu_content.py`. Write it once.

```python
def start_menu_items(api, menu):
    def open_home():
        from src.shell import explorer
        explorer.open_explorer(os.path.expanduser('~'))

    return [
        {'id': 'home', 'label': _("My home folder"), 'action': open_home},
        {'id': 'more', 'label': _("My add-on"), 'children': [
            {'id': 'hello', 'label': _("Say hello"),
             'action': lambda: api.speak(_("Hello"))},
        ]},
    ]
```

An entry with `children` becomes a **branch** that opens where it stands (the left column is a tree, not a chain of flyouts a keyboard cannot follow). Do not write the word "submenu" into the label: the tree control reports "collapsed" / "expanded" itself and a screen reader would then say it twice.

### 3. The file browser

Four hooks, and they are Explorer's own extension points rebuilt.

```python
def explorer_menu_items(api, browser):
    """The browser's Tools menu - it exists only when something is in it."""
    return [{'id': 'where', 'label': _("Where am I?"),
             'action': lambda: wx.MessageBox(str(browser.location))}]


def explorer_toolbar_items(api, browser):
    return [{'id': 'up_twice', 'label': _("Up twice"),
             'help': _("Go up two folders at once"),
             'art': wx.ART_GO_DIR_UP,
             'action': lambda: (browser.go_up(), browser.go_up())}]


def explorer_context_items(api, browser, where, selection):
    """`where` is 'item' or 'background'; `selection` is what the menu is
    about - so a command can be about THIS file."""
    if where != 'item' or not selection:
        return []
    path = selection[0].get('path') or ''

    def copy_path():
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(path))
            finally:
                wx.TheClipboard.Close()

    return [{'id': 'copy', 'label': _("Copy the full path"),
             'action': copy_path}]


def explorer_columns(api, browser, location):
    """A column of your own in the details view."""
    def extension(entry):
        if entry.get('directory'):
            return ''
        return os.path.splitext(entry.get('name') or '')[1].lstrip('.').upper()

    return [{'id': 'extension', 'label': _("Extension"), 'width': 90,
             'value': extension}]
```

**The column rule is the one to remember.** `explorer_columns` is asked **once per folder**, and `value` is then called per row out of the entry already in hand. The view is a virtual list — that is what opens a folder of three thousand files in about 30 ms instead of six seconds — so a `value` that asks Windows something per row (a shell call, a file read, a network lookup) undoes it. Everything you need is usually already in the entry: `name`, `path`, `directory`, `size`, `modified`.

### 4. The taskbar

```python
def taskbar_bands(api, taskbar):
    """A control of your own on the bar - Windows calls this a deskband."""
    def make(parent):
        from src.shell.controls import TextControl
        return TextControl(parent, _("Example"))

    return [{'id': 'band', 'label': _("Example band"), 'width': 70,
             'control': make}]


def taskbar_menu_items(api, taskbar):
    return [{'id': 'refresh', 'label': _("Refresh the bar"),
             'action': taskbar.refresh_windows}]
```

A band is built **in the notification area**, so it is a real child window of the bar: reachable with Tab and the arrows like everything else there, and named, so a screen reader says what it is. It is built **once with the bar** and never on a tray refresh — the notification area is re-read every thirty seconds, and rebuilding somebody's control that often would throw the keyboard out of it.

A band that is not a `wx.Window` is dropped, with a line on the console.

### 5. The desktop

```python
def desktop_menu_items(api, desktop, where, entry):
    """`where` is 'item' (an icon was right-clicked) or 'background'."""
    if where == 'background':
        return [{'id': 'count', 'label': _("How many icons?"),
                 'action': lambda: api.speak(str(len(desktop.entries)))}]
    name = (entry or {}).get('name') or ''
    return [{'id': 'say', 'label': _("Say the name"),
             'action': lambda: api.speak(name)}] if name else []
```

## Providers: replacing a part of the shell

### A Start menu of your own

```ini
provides = start_menu
surfaces = start_menu
```

```python
def open_start_menu(api, parent):
    """Answer a window.  That is the whole contract."""
    return MyStartMenu(api, parent)
```

The window must have `Show`, `Hide` and `IsShown`. Everything else — where it appears, what is on it, how it is navigated — is yours. `data/shell addons/simple_start_menu/` is a complete working one in about 200 lines: a search box, a list, and every command reached through `api.run_action`.

**Being installed does not take the Windows key.** Titan asks for an add-on Start menu only when the user has chosen yours, in either of the two places that ask:

- the taskbar's own **Properties -> Start menu**, where every installed provider is a radio button beside Titan's two, with your manifest's description as the line under it;
- **Settings -> Titan shell -> Start menu**, the same list as a drop-down.

Both write `start_menu_style = addon` and `provider_start_menu = <your id>` in the `titan_shell` section. An add-on chosen and since uninstalled or switched off means **Titan's own menu**, never a different add-on silently promoted.

### A file browser of your own

```ini
provides = explorer
surfaces = explorer
```

```python
def open_explorer(api, location, parent, new_window):
    """`location` is the folder to show (or a virtual name like My Computer),
    `new_window` says whether the user asked for a second window."""
    return MyBrowser(api, location, parent)
```

Everything that opens a folder in Titan comes here: the desktop, the Start menu's File manager, My Computer, Windows+E while the shell is on.

## Accessibility: the rules that are not optional

The shell replaces the system interface, so its users are reading it with a screen reader. Four rules, all of them learned the hard way:

1. **Never speak what the reader already says.** The shell itself says nothing through TTS: it is the system interface, and a Titan announcement on top of the reader's would say every button twice. `api.speak` exists because an add-on is a program the user installed, not the system interface — but ask yourself first whether the reader has not said this already.
2. **Every control you build must be a real, focusable, named window.** A painted rectangle is nothing to a screen reader. Use the shell's own controls (`src/shell/controls.py` — they answer MSAA with a name, a role and a state through `a11y.AccessibleMixin`), or name a native control the hard way:

   ```python
   from src.shell.a11y import name_control
   name_control(self.list, _("Start menu"))
   ```

   `wx.Window.SetName` alone never reaches MSAA on a native control (a list view answers with its own IAccessible, whose name comes from window text these controls do not have). That is what `name_control` is for.
3. **A tick list must be tick boxes to the platform.** `wx.CheckListBox` is owner-drawn on Windows: its rows report role "list item" with no checked state, so a reader says the name and nothing about whether it is on. Use `src.ui.check_list.CheckList`, which is a report-mode list with `EnableCheckBoxes()` — its rows report role "check box" with the CHECKED state and a UIA toggle pattern.
4. **No character ever stands in for a picture or a word.** A list item's text *is* its accessible name, so an arrow after a folder's name is read out as the arrow. Say "submenu" in words, or better, use a control that reports the state itself.

## Settings of your own

```python
value = api.setting('greeting', 'Hello')
api.set_setting('greeting', "Good morning")
```

They go into the `shell_addon_<your id>` section of Titan's own settings file. `get_setting` is cached against the file's timestamp, so reading one in a paint handler is cheap (about a microsecond) — writing one is not, so do not write in a loop.

## Translations

```python
try:
    from src.titan_core.translation import _
except Exception:
    def _(text):
        return text
```

Titan's own catalogues are already loaded, so anything Titan says, you get in the user's language for free. For words Titan does not have, ship a `.mo` beside your add-on and load it yourself with `gettext`. Your add-on's **name and description** are not translatable strings at all — they are `name_pl` / `description_pl` in the manifest.

## Turning it on, and driving it

- **Settings -> Titan shell -> Shell add-ons** is a tick list of everything installed. Ticking one writes `status` into that add-on's own manifest at once, exactly as the component manager does — a shell add-on is switched on to try it.
- The **Action API** has the same thing for a macro, the AI, or another add-on:

| Action | What it does |
|--------|--------------|
| `shell.list_addons` | Everything installed, with `enabled`, `provides` and `surfaces` |
| `<addon id>.status` | Is it on? |
| `<addon id>.enable` / `<addon id>.disable` | Switch it |

## Letting the AI write one

**Programmer -> AI -> Create Shell Add-on...** generates one from a
description. It is given this guide and the reference add-on in full, and
what it writes is then checked against Titan itself before it is saved: the
hooks it defined must be hooks Titan really calls (with the right number of
arguments), the manifest keys and surfaces must be ones Titan reads, an
add-on that says `provides = start_menu` must define `open_start_menu`, and
every `api.something` must exist on the real `ShellAddonAPI`. A problem is
reported by name and the model is asked to correct it, so the failure this
prevents is the one that is otherwise invisible: an add-on that loads, is
listed, can be ticked - and contributes nothing, because its functions are
called something Titan never asks for.

The check is `ai_creation_kit.check_shell_addon`, and it reads
`shell.addons.HOOKS`, `HOOK_SIGNATURES`, `SURFACES`, `PROVIDABLE`,
`MANIFEST_KEYS` and the API class itself - never a copy - so it cannot
describe a Titan that does not exist.

## Packaging

Any add-on directory can become one compressed file:

```bash
python src/scripts/pack_addon.py "data/shell addons/my_addon" --kind shell_addon -o my_addon.tcd
python src/scripts/pack_addon.py --unpack my_addon.tcd -o /tmp/inspect
```

- Shell add-ons pack as **`.TCD`** (`.TCA` is applications and games).
- The packaged file is found and used exactly like the directory — no separate manifest, no conversion, nothing to install by hand. Double-clicking it in Explorer installs it into the per-user `data/shell addons/`.
- It can be uploaded to and downloaded from the Titan-Net application repository like any other add-on.

## Debugging

- Run Titan from source (`python main.py`) and watch the console: everything the add-on layer refuses says why — `[ShellAddons] my_addon.start_menu_items failed: ...`, `contributed an entry with no label or nothing behind it`, `answered str, which is not a list of entries`.
- `api.log(...)` prefixes your own lines the same way.
- The shell's own tests are `tests/test_shell_addons.py` (26 tests) and `tests/test_shell.py`; run them directly (`python tests/test_shell_addons.py`) — `tests/` has no `__init__.py`. If you add a surface, add a test there.
- A frozen (compiled) Titan loads `init.py` by reading and executing it, so an add-on works the same in a build as it does from source. Anything you import that is not in Titan already must be inside your `lib/`.

## A complete minimal add-on

`data/shell addons/hello_shell/__shell_addon__.TCE`:

```ini
[shell addon]
name = Hello shell
name_pl = Witaj powłoko
description = One entry on the Start menu and one on the desktop's menu.
description_pl = Jedna pozycja w menu Start i jedna w menu pulpitu.
author = Me
version = 1.0
status = 1
surfaces = start_menu, desktop
```

`data/shell addons/hello_shell/init.py`:

```python
# -*- coding: utf-8 -*-
try:
    from src.titan_core.translation import _
except Exception:
    def _(text):
        return text


def setup(api):
    api.log("hello")


def start_menu_items(api, menu):
    return [{'id': 'hello', 'label': _("Say hello"),
             'action': lambda: api.speak(_("Hello from my add-on"))}]


def desktop_menu_items(api, desktop, where, entry):
    if where != 'background':
        return []
    return [{'id': 'count', 'label': _("How many icons?"),
             'action': lambda: api.speak(str(len(desktop.entries)))}]
```

Then: Settings -> Titan shell -> Shell add-ons -> tick it, and press the Windows key.

## Checklist

- [ ] `__shell_addon__.TCE` with `[shell addon]`, `status = 1`, and the `surfaces` you actually touch
- [ ] `name_pl` / `description_pl` if your users are Polish
- [ ] Only the hooks you need — every one of them optional
- [ ] Every entry has a `label` and something behind it
- [ ] Nothing slow on the GUI thread; `explorer_columns` values read the entry, not Windows
- [ ] Every control you build is focusable and named (`name_control`, or the shell's own controls)
- [ ] Nothing spoken that the screen reader already says
- [ ] Reached the rest of Titan through `api.run_action`, not through Titan's internals
- [ ] Tried it switched off as well as on — the shell must not notice your absence
- [ ] Packed as `.TCD` for distribution

## See also

- `data/shell addons/example_shell_addon/` — one function per surface, the reference
- `data/shell addons/simple_start_menu/` — a Start menu provider, complete
- `action_api_guide_en.md` — everything `api.run_action` can reach
- `settings_interface_guide_en.md` — the same idea for the settings window
- `component_creation_guide_en.md` — for anything that is not part of the shell
