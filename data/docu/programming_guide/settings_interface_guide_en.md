# TCE Settings Interface Creation Guide

## Introduction

Titan has one settings window, written in wxPython. A **settings interface** replaces it — with a web page, a Qt window, a console, a wizard that asks six questions, a voice dialogue, anything you can write in Python.

It is deliberately shaped like `data/launchers/`, because it is the same idea one level down: a launcher replaces Titan's main window, a settings interface replaces its settings window. One is chosen at a time, in **Settings -> Interface -> "Settings interface"**, where Titan's own window is called **Classic**.

**The thing that makes it possible: your interface never learns what a setting is.**

`src/settings/ui_model.py` reads the description out of Titan's own settings window — its categories are the categories, its controls are the settings, their labels are the labels, already translated. So:

- **A setting is added to Titan once.** A new checkbox in `settingsgui.py` appears in every installed interface, in the user's language, with none of them changed.
- **Component categories are there too** — the screen reader's forty settings, the macro manager's, the AI's — because a component registers its category by being handed the window, and that is the window being read. Measured on a normal installation: 14 categories, about 147 settings.
- **The values are live.** The voices, skins, sound themes and TTS engines are lists Titan fills in at run time; reading the model is reading what the user would see.
- **Saving is Titan's own save**, with everything that hangs off it: the SAPI registration, the system monitor restarting, the shell re-hooking, the menu bar rebuilding. An interface that wrote the ini file itself would set the value and change nothing.

There is deliberately **no second table of settings** anywhere. If you find yourself writing one, you have misunderstood the design.

## Architecture

```
data/settings interfaces/my_interface/
├── __settings_ui__.TCE   # Manifest (REQUIRED, .TCE in uppercase)
├── init.py               # open_settings(api) (REQUIRED; init.pyc accepted)
└── lib/                  # Bundled dependencies (optional)
```

Discovery is `platform_utils.discover_data_entries()`, so an interface may also ship as a single packaged **`.TCD`** file. Everything is in `src/settings/interfaces.py`.

**Every way into the settings in the whole program goes through `interfaces.open_settings()`** — the menu bar, the Invisible UI, both Klango classes, both Start menus, the desktop's menu, the shell, and the `titan.open_settings` action. That is what makes choosing one mean anything.

## Manifest `__settings_ui__.TCE`

```ini
[settings interface]
name = Settings as a web page
name_pl = Ustawienia jako strona internetowa
description = Every Titan setting as one HTML page in a Titan window.
description_pl = Wszystkie ustawienia Titana jako jedna strona HTML.
author = Your Name
version = 1.0
status = 0
libs = lib
```

| Field | Required | Description |
|-------|----------|-------------|
| name | no | Display name (defaults to the folder name) |
| name_pl, name_en, ... | no | The name in that language; `name_<code>` wins over `name` |
| description | no | One sentence, shown beside the name in the chooser |
| description_pl, ... | no | The same, translated |
| author | no | Author |
| version | no | Version string (default `1.0`) |
| status | yes | **`0` = offered, `1` = not offered** |
| libs | no | Comma-separated subdirectories added to `sys.path` (default: `lib`) |

**Ship `status = 0`.** Unlike a shell add-on, a settings interface changes nothing by being installed — it is one of the choices in Settings -> Interface until somebody picks it.

## `init.py`

One function:

```python
def open_settings(api):
    """Open the settings.  Answer the window, or True, or None."""
```

| Answer | Meaning |
|--------|---------|
| a window | Titan shows and raises it (`wx.Frame`, `wx.Dialog`, or anything with `Show`/`Raise`) |
| `True` | You opened something that is not a window — a console, a browser, a voice dialogue |
| `None` / an exception | Failed: **Titan's own settings window opens instead**, and says so |

That last row is a rule, not a fallback: settings are where a user goes to fix things, up to and including "turn this interface off", so they can never be the thing an add-on takes away. An interface that is uninstalled, switched off, has no `open_settings`, raises, or opens nothing means Titan's own window, plainly said.

## The API object

`api` is a `SettingsUIAPI`. The settings half:

| Method | Answers |
|--------|---------|
| `api.categories()` | `[{'name': str, 'items': [item, ...]}, ...]` — everything, JSON-safe |
| `api.items()` | Every setting flattened, for an interface with no categories |
| `api.find(text)` | The settings whose label or category matches |
| `api.get(item_id)` | One value |
| `api.set(item_id, value)` | Change one — nothing is written until `save` |
| `api.press(item_id)` | Press a setting that is a button (a dialog, a wizard) |
| `api.refresh()` | Read the window again, after a save or a category appearing |
| `api.save()` | **Titan's own save**, with all its side effects |
| `api.cancel()` | Put the settings window away without saving |

The window half:

| Method | What it gives you |
|--------|-------------------|
| `api.call(function, *args)` | Run something **on the GUI thread** and wait for its answer |
| `api.parent()` | The window to parent yours to |
| `api.file(*parts)` | A path inside your own folder |
| `api.translate(text)`, `api.language()` | Titan's own gettext and the current language code |
| `api.speak(text)` | Titan's speech |
| `api.open_builtin()` | Titan's own settings window — the way back, always there |
| `api.log(message)` | A console line prefixed with your id |

## The data an interface renders

`api.categories()`:

```python
[{'name': "General",
  'items': [
      {'id': 'quick_start_cb', 'category': "General",
       'label': "Quick start", 'kind': 'bool', 'value': True,
       'options': [], 'minimum': None, 'maximum': None,
       'enabled': True, 'description': ''},
      ...]},
 ...]
```

| Field | Meaning |
|-------|---------|
| `id` | The handle you pass back to `get` / `set` / `press` |
| `category` | Which category it is on |
| `label` | Its name in the user's language |
| `kind` | What the control **is** — the table below |
| `value` | What it is set to now |
| `options` | The choices (`choice`, `list`, `multi`) |
| `minimum`, `maximum` | The range (`number`) |
| `enabled` | Whether Titan currently allows it to be changed |

### The kinds

| Kind | The control in Titan | Render it as | `set` takes |
|------|---------------------|--------------|-------------|
| `bool` | `wx.CheckBox` | a tick box | `True` / `False` (or `"yes"`, `"1"`, `"tak"`) |
| `choice` | `wx.Choice`, `wx.ComboBox`, `wx.RadioBox` | a drop-down or radio group | one of `options` |
| `number` | `wx.Slider`, `wx.SpinCtrl` | a slider or number field, honouring `minimum`/`maximum` | an int |
| `text` | `wx.TextCtrl` | a text field | a string |
| `secret` | `wx.TextCtrl` with `TE_PASSWORD` | a password field — **never show the value** | a string |
| `list` | `wx.ListBox` | a single-selection list | one of `options` |
| `multi` | a tick list | **tick boxes**, one per option | a list of strings |
| `command` | `wx.Button` | a button; `api.press(id)` | — |
| `info` | read-only `wx.TextCtrl` | text the user reads, not a setting | — |

`kind` is what the **control** is, not what the key is called, so an interface renders what Titan renders instead of guessing from a name.

Two things follow from how the model is built and are worth knowing:

- **A control nobody named is not offered.** A `wx.Choice` is labelled by the static text in front of it — that is how every wx program is built — and a control with no caption is left out rather than shown as a nameless box. It is still reachable in Titan's own window.
- **Setting a value fires the control's own event**, because that is where Titan applies things live (the speech rate, the sound theme, the switch that makes the Titan shell category appear). Setting it silently would leave the window and the program disagreeing.

## Threading

The settings are wx controls. Reading or writing them off the GUI thread is undefined behaviour rather than an error you would see.

- An interface that **is a window** (wx, and anything Titan opens on the GUI thread) can call the API directly.
- An interface with a **loop of its own** — a console asking questions, a web server answering requests, a voice dialogue — runs it on a thread of its own and reaches the settings through `api.call(...)`, which marshals onto the GUI thread and waits (20 s timeout). Called *from* the GUI thread it simply calls, so you never have to ask which thread you are on.

```python
categories = api.call(api.categories)
api.call(api.set, 'quick_start_cb', True)
api.call(api.save)
```

## Accessibility

Titan's users read this window with a screen reader, and the settings are the last place that may be unreadable.

- **Use real controls.** A native `wx.CheckBox`, `wx.Choice`, `wx.Slider` and `wx.TextCtrl` are read by every screen reader with no help from you. Anything you paint yourself is a blank rectangle.
- **A `multi` is tick boxes, and they must be tick boxes to the platform.** Do not use `wx.CheckListBox`: it is owner-drawn on Windows, its rows report role "list item" with no checked state, and a reader says the name of the entry and nothing about whether it is on. Use `src.ui.check_list.CheckList` — a report-mode list with `EnableCheckBoxes()`, whose rows report role "check box", the CHECKED state and a UIA toggle pattern.
- **Name your lists for MSAA.** `wx.Window.SetName` never reaches a screen reader on a native list or tree; `src.shell.a11y.name_control(control, "Categories")` is what does.
- **Put a caption in front of every field**, as Titan's own window does — that is where a screen reader (and `ui_model`) looks for a control's name.
- **Do not build a voice of your own.** If you want to say something, `api.speak`; if a reader is running it is already reading your controls, and a second copy of everything is worse than silence.

## Turning it on, and driving it

- **Settings -> Interface -> "Settings interface"** lists Classic (Titan's own) and every installed interface by its manifest name.
- The Action API has the same:

| Action | What it does |
|--------|--------------|
| `settings.settings_interfaces` | What is installed and which is in use |
| `settings.use_settings_interface` | Choose one (empty = Classic) |
| `<interface id>.status` / `<interface id>.use` | The same, per interface |

## The two examples

Both ship with Titan, both are installed, and neither is in use until it is chosen.

- **`data/settings interfaces/html_settings/`** — the whole settings as one HTML page in a `wx.html2` window, with a search box and a link to each category. The page talks back by setting `location.href` to a `titan:` URL, which Python vetoes in `EVT_WEBVIEW_NAVIGATING` and handles — the oldest trick there is, and the one that works on every WebView backend with no bridge and no local server.
- **`data/settings interfaces/console_settings/`** — `AllocConsole`, a numbered list of categories, a numbered list of settings, one question at a time. It is also the interface that still works when the graphical one cannot be used at all.

## A complete minimal interface

`data/settings interfaces/quick_settings/__settings_ui__.TCE`:

```ini
[settings interface]
name = Quick settings
name_pl = Szybkie ustawienia
description = One category at a time, in a plain Titan dialog.
description_pl = Jedna kategoria naraz, w zwykłym oknie Titana.
author = Me
version = 1.0
status = 0
```

`data/settings interfaces/quick_settings/init.py`:

```python
# -*- coding: utf-8 -*-
import wx

try:
    from src.titan_core.translation import _
except Exception:
    def _(text):
        return text


class QuickSettings(wx.Frame):
    def __init__(self, api, parent=None):
        super().__init__(parent, title=_("Settings"), size=(640, 520))
        self.api = api
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.categories = api.categories()
        sizer.Add(wx.StaticText(panel, label=_("Category:")), 0, wx.ALL, 6)
        self.choice = wx.Choice(
            panel, choices=[c['name'] for c in self.categories])
        self.choice.SetSelection(0)
        self.choice.Bind(wx.EVT_CHOICE, lambda event: self.fill())
        sizer.Add(self.choice, 0, wx.EXPAND | wx.ALL, 6)

        self.box = wx.BoxSizer(wx.VERTICAL)
        self.host = wx.ScrolledWindow(panel)
        self.host.SetScrollRate(0, 10)
        self.host.SetSizer(self.box)
        sizer.Add(self.host, 1, wx.EXPAND | wx.ALL, 6)

        save = wx.Button(panel, wx.ID_SAVE, _("&Save"))
        save.Bind(wx.EVT_BUTTON, self.on_save)
        sizer.Add(save, 0, wx.ALL, 6)
        panel.SetSizer(sizer)
        self.fill()

    def fill(self):
        """Only the tick boxes, to keep the example short."""
        self.box.Clear(True)
        self.controls = {}
        category = self.categories[self.choice.GetSelection()]
        for item in category['items']:
            if item['kind'] != 'bool':
                continue
            check = wx.CheckBox(self.host, label=item['label'])
            check.SetValue(bool(item['value']))
            check.Enable(item['enabled'])
            self.box.Add(check, 0, wx.ALL, 4)
            self.controls[item['id']] = check
        self.host.Layout()
        self.host.FitInside()

    def on_save(self, event):
        for item_id, check in self.controls.items():
            self.api.set(item_id, check.GetValue())
        self.api.save()
        self.Close()


def open_settings(api):
    frame = QuickSettings(api, api.parent())
    frame.Show()
    frame.Raise()
    return frame
```

Then: Settings -> Interface -> Settings interface -> Quick settings. Every way into the settings now opens it.

## Letting the AI write one

**Programmer -> AI -> Create Settings Interface...** generates one from a
description, with this guide in the prompt. What it writes is checked against
Titan before it is saved: `open_settings(api)` must be there and take one
argument, the manifest keys must be ones Titan reads, every `api.something`
must exist on the real `SettingsUIAPI`, and an interface that imports
`set_setting` / `save_settings` to write the ini file itself is refused with
the reason - that sets the value and changes nothing.

The check is `ai_creation_kit.check_settings_interface`, and it reads
`interfaces.ENTRY_POINT`, `interfaces.MANIFEST_KEYS` and the API class
itself, so it always describes the Titan you have.

## Debugging

- Run Titan from source and watch the console: `[SettingsInterfaces] ...` says why an interface was not used, and `api.log` prefixes your own lines.
- `python tests/test_settings_interfaces.py` (36 tests) is the model's own test suite — run it directly, `tests/` has no `__init__.py`. It builds a fake settings window with known contents, so it is also the fastest way to see what `ui_model` makes of a control.
- To see the data without any interface at all:

  ```python
  from src.settings import interfaces
  model = interfaces.build_model()
  for category in model.categories():
      print(category['name'], len(category['items']))
  ```

- A frozen (compiled) Titan executes `init.py` by reading it, so an interface behaves the same in a build as from source. Anything you import beyond what Titan already ships must be in your `lib/`.

## Packaging

```bash
python src/scripts/pack_addon.py "data/settings interfaces/my_interface" --kind settings_interface -o my_interface.tcd
```

`.TCD`, found and used exactly like the directory, installable by double-click, and uploadable to the Titan-Net repository.

## Checklist

- [ ] `__settings_ui__.TCE` with `[settings interface]` and `status = 0`
- [ ] `open_settings(api)` answering a window, or `True`, and never raising
- [ ] Renders from `api.categories()` — no table of settings of your own
- [ ] Every `kind` handled, or deliberately skipped (and `secret` never shown)
- [ ] Saves with `api.save()`, never by writing the ini file
- [ ] Any loop of your own on its own thread, reaching the settings through `api.call`
- [ ] Real, named, focusable controls; `CheckList` for a `multi`
- [ ] A way back: `api.open_builtin()` on a menu or a button
- [ ] Tried with the AI, the screen reader and the macro manager installed — their categories must appear too

## See also

- `data/settings interfaces/html_settings/`, `console_settings/` — the two working examples
- `shell_addon_guide_en.md` — the same idea for the desktop, taskbar and Start menu
- `action_api_guide_en.md` — `settings.*` actions and everything else Titan exposes
- `launcher_creation_guide_en.md` — replacing Titan's main window instead
