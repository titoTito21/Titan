# Create Application Wizard

Interactive wizard to create a new application for TCE Launcher.

## Process:

1. **Ask for Application Details:**
   - Application name (Polish)
   - Application name (English)
   - Short name (lowercase, no spaces, for directory and command line)
   - Description (optional, can be empty)
   - Main file name (default: {shortname}.py)
   - Hidden (default: false — hidden apps don't appear in the main list)

2. **Create Application Structure:**
   - Create directory: `data/applications/{shortname}/`
   - Create main Python file: `data/applications/{shortname}/{mainfile}`
   - Create config file: `data/applications/{shortname}/__app.TCE`

3. **Generate Application Template:**
   ```python
   import wx
   import os
   import sys

   # Add TCE root to path for imports
   APP_DIR = os.path.dirname(os.path.abspath(__file__))
   TCE_ROOT = os.path.abspath(os.path.join(APP_DIR, '..', '..', '..'))
   if TCE_ROOT not in sys.path:
       sys.path.insert(0, TCE_ROOT)

   # Optional: Translation support
   # from src.titan_core.translation import set_language
   # from src.settings.settings import get_setting
   # _ = set_language(get_setting('language', 'pl'))

   class {AppName}Frame(wx.Frame):
       def __init__(self, *args, **kwargs):
           super({AppName}Frame, self).__init__(*args, **kwargs)
           self.InitUI()

       def InitUI(self):
           panel = wx.Panel(self)
           vbox = wx.BoxSizer(wx.VERTICAL)

           # Add your UI elements here

           panel.SetSizer(vbox)
           self.SetSize((800, 600))
           self.SetTitle("{App Name}")
           self.Centre()

           self.Bind(wx.EVT_KEY_DOWN, self.on_key_press)

       def on_key_press(self, event):
           key = event.GetKeyCode()
           if key == wx.WXK_ESCAPE:
               self.Close()
           event.Skip()

   if __name__ == "__main__":
       app = wx.App(False)
       frame = {AppName}Frame(None)
       frame.Show()
       app.MainLoop()
   ```

4. **Create Config File (`__app.TCE` format):**
   ```
   name_pl="{Polish name}"
   name_en="{English name}"
   description="{Description or empty}"
   openfile="{mainfile}"
   shortname="{shortname}"
   hidden="false"
   ```

   **IMPORTANT**:
   - Use double quotes around values
   - One key=value pair per line
   - File can be named `__app.TCE` (uppercase) or `__app.tce` (lowercase) — both are supported
   - `hidden="true"` hides the app from the main applications list (but still launchable by shortname)
   - Values are read with `strip().strip('"')` so quotes are optional but preferred

5. **Optional Translation Setup:**
   - Create `languages/` directory inside the app folder
   - Use `src/titan_core/translation.set_language()` for translations
   - See `data/applications/tEdit/` for a reference with full translation support

6. **Verify Installation:**
   - Restart TCE Launcher or refresh app list
   - Check if app appears in applications list
   - Test launching the application
   - Verify proper cleanup on exit

## Reference Example:

See `data/applications/tEdit/` for a complete application example with:
- Main file: `tedit.py` (wx.Frame-based text editor)
- Config: `__app.TCE` with all required fields
- Translation support: `translation.py`, `languages/`, `babel.cfg`

## Key Notes from app_manager.py:
- Apps are launched via `subprocess` using the system Python interpreter
- In frozen (compiled) mode, uses `pythonw.exe` from `_internal/` directory
- Supports `.py`, `.pyc`, `.pyd`/`.so` (Cython), and `.exe` files
- Language is passed via `LANG` environment variable

## Complete Code Examples

These are three complete, runnable application examples you can copy directly into a new app directory.

---

### Example 1: Calculator

A simple accessible calculator with keyboard support.

**File: `data/applications/tcalc/__app.TCE`**
```
name_pl="Kalkulator"
name_en="Calculator"
description=""
openfile="calculator.py"
shortname="tcalc"
```

**File: `data/applications/tcalc/calculator.py`**
```python
import wx
import os
import sys

# Add TCE root to path for imports
APP_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(APP_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# Translation support
try:
    from src.titan_core.translation import set_language
    from src.settings.settings import get_setting
    _ = set_language(get_setting('language', 'pl'))
except Exception:
    def _(s): return s


class CalculatorFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(CalculatorFrame, self).__init__(*args, **kwargs)
        self.expression = ""
        self.InitUI()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Display field (read-only)
        self.display = wx.TextCtrl(
            panel, style=wx.TE_RIGHT | wx.TE_READONLY,
            size=(-1, 50)
        )
        font = self.display.GetFont()
        font.SetPointSize(18)
        self.display.SetFont(font)
        self.display.SetValue("0")
        vbox.Add(self.display, 0, wx.EXPAND | wx.ALL, 10)

        # Button grid
        button_labels = [
            ['7', '8', '9', '/'],
            ['4', '5', '6', '*'],
            ['1', '2', '3', '-'],
            ['0', '.', '=', '+'],
        ]

        for row in button_labels:
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            for label in row:
                btn = wx.Button(panel, label=label, size=(80, 60))
                btn.Bind(wx.EVT_BUTTON, self.on_button_click)
                hbox.Add(btn, 1, wx.EXPAND | wx.ALL, 2)
            vbox.Add(hbox, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Clear button
        clear_btn = wx.Button(panel, label=_("Clear (C)"), size=(-1, 50))
        clear_btn.Bind(wx.EVT_BUTTON, self.on_clear)
        vbox.Add(clear_btn, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(vbox)
        self.SetSize((380, 450))
        self.SetTitle(_("Calculator"))
        self.Centre()

        # Keyboard events on the panel
        panel.Bind(wx.EVT_KEY_DOWN, self.on_key_press)
        panel.SetFocus()

    def on_button_click(self, event):
        label = event.GetEventObject().GetLabel()
        if label == '=':
            self.calculate()
        else:
            self.append_to_expression(label)

    def append_to_expression(self, char):
        self.expression += char
        self.display.SetValue(self.expression)

    def calculate(self):
        try:
            result = str(eval(self.expression))
            self.display.SetValue(result)
            self.expression = result
        except Exception:
            self.display.SetValue(_("Error"))
            self.expression = ""

    def on_clear(self, event=None):
        self.expression = ""
        self.display.SetValue("0")

    def on_key_press(self, event):
        key = event.GetKeyCode()
        char = chr(key) if 32 <= key < 127 else ''

        if key == wx.WXK_ESCAPE:
            self.Close()
        elif char in '0123456789':
            self.append_to_expression(char)
        elif char in '+-*/.':
            self.append_to_expression(char)
        elif key == wx.WXK_RETURN or key == wx.WXK_NUMPAD_ENTER:
            self.calculate()
        elif char.upper() == 'C':
            self.on_clear()
        elif key == wx.WXK_BACK:
            if self.expression:
                self.expression = self.expression[:-1]
                self.display.SetValue(self.expression if self.expression else "0")
        else:
            event.Skip()


if __name__ == "__main__":
    app = wx.App(False)
    frame = CalculatorFrame(None)
    frame.Show()
    app.MainLoop()
```

---

### Example 2: Countdown Timer

A countdown timer with sound alerts and keyboard shortcuts.

**File: `data/applications/ttimer/__app.TCE`**
```
name_pl="Minutnik"
name_en="Countdown Timer"
description=""
openfile="timer.py"
shortname="ttimer"
```

**File: `data/applications/ttimer/timer.py`**
```python
import wx
import os
import sys

# Add TCE root to path for imports
APP_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(APP_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# Translation support
try:
    from src.titan_core.translation import set_language
    from src.settings.settings import get_setting
    _ = set_language(get_setting('language', 'pl'))
except Exception:
    def _(s): return s

# Sound support
try:
    from src.titan_core.sound import play_sound
    SOUND_AVAILABLE = True
except Exception:
    SOUND_AVAILABLE = False
    def play_sound(f, **kw): pass


class TimerFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(TimerFrame, self).__init__(*args, **kwargs)
        self.remaining_seconds = 0
        self.running = False
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_tick, self.timer)
        self.InitUI()

    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Time display
        self.time_label = wx.StaticText(panel, label="00:00")
        font = self.time_label.GetFont()
        font.SetPointSize(48)
        self.time_label.SetFont(font)
        vbox.Add(self.time_label, 0, wx.ALIGN_CENTER | wx.TOP, 20)

        # Status display
        self.status_label = wx.StaticText(panel, label=_("Stopped"))
        vbox.Add(self.status_label, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        # Minutes input
        hbox_input = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(panel, label=_("Minutes:"))
        hbox_input.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.minutes_input = wx.SpinCtrl(
            panel, value="5", min=1, max=999, size=(100, -1)
        )
        hbox_input.Add(self.minutes_input, 0, wx.ALIGN_CENTER_VERTICAL)
        vbox.Add(hbox_input, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        # Buttons
        hbox_btns = wx.BoxSizer(wx.HORIZONTAL)

        self.start_stop_btn = wx.Button(panel, label=_("Start"))
        self.start_stop_btn.Bind(wx.EVT_BUTTON, self.on_start_stop)
        hbox_btns.Add(self.start_stop_btn, 0, wx.ALL, 5)

        self.reset_btn = wx.Button(panel, label=_("Reset"))
        self.reset_btn.Bind(wx.EVT_BUTTON, self.on_reset)
        hbox_btns.Add(self.reset_btn, 0, wx.ALL, 5)

        vbox.Add(hbox_btns, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        # Keyboard shortcut help
        help_text = wx.StaticText(
            panel,
            label=_("Space = Start/Stop, R = Reset, Escape = Exit")
        )
        vbox.Add(help_text, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(vbox)
        self.SetSize((400, 350))
        self.SetTitle(_("Countdown Timer"))
        self.Centre()

        # Keyboard events
        panel.Bind(wx.EVT_KEY_DOWN, self.on_key_press)
        panel.SetFocus()

        # Cleanup on close
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def format_time(self, total_seconds):
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def on_start_stop(self, event=None):
        if self.running:
            # Stop
            self.timer.Stop()
            self.running = False
            self.start_stop_btn.SetLabel(_("Start"))
            self.status_label.SetLabel(_("Paused"))
        else:
            # Start
            if self.remaining_seconds == 0:
                self.remaining_seconds = self.minutes_input.GetValue() * 60
                self.time_label.SetLabel(self.format_time(self.remaining_seconds))
            self.timer.Start(1000)
            self.running = True
            self.start_stop_btn.SetLabel(_("Stop"))
            self.status_label.SetLabel(_("Running"))

    def on_reset(self, event=None):
        self.timer.Stop()
        self.running = False
        self.remaining_seconds = 0
        self.time_label.SetLabel("00:00")
        self.start_stop_btn.SetLabel(_("Start"))
        self.status_label.SetLabel(_("Stopped"))

    def on_tick(self, event):
        if self.remaining_seconds > 0:
            self.remaining_seconds -= 1
            self.time_label.SetLabel(self.format_time(self.remaining_seconds))
            if self.remaining_seconds == 0:
                self.timer.Stop()
                self.running = False
                self.start_stop_btn.SetLabel(_("Start"))
                self.status_label.SetLabel(_("Finished!"))
                self.on_timer_finished()

    def on_timer_finished(self):
        """Called when the countdown reaches zero."""
        try:
            play_sound('core/NOTIFICATION.ogg')
        except Exception:
            pass
        wx.MessageBox(
            _("Time is up!"),
            _("Countdown Timer"),
            wx.OK | wx.ICON_INFORMATION
        )

    def on_key_press(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.Close()
        elif key == wx.WXK_SPACE:
            self.on_start_stop()
        elif key == ord('R') or key == ord('r'):
            self.on_reset()
        else:
            event.Skip()

    def on_close(self, event):
        self.timer.Stop()
        self.Destroy()


if __name__ == "__main__":
    app = wx.App(False)
    frame = TimerFrame(None)
    frame.Show()
    app.MainLoop()
```

---

### Example 3: Text Notes (Simple Notepad)

A minimal text editor with file operations and keyboard shortcuts.

**File: `data/applications/tnotepad/__app.TCE`**
```
name_pl="Notatnik"
name_en="Notepad"
description=""
openfile="notepad.py"
shortname="tnotepad"
```

**File: `data/applications/tnotepad/notepad.py`**
```python
import wx
import os
import sys

# Add TCE root to path for imports
APP_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(APP_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# Translation support
try:
    from src.titan_core.translation import set_language
    from src.settings.settings import get_setting
    _ = set_language(get_setting('language', 'pl'))
except Exception:
    def _(s): return s


class NotepadFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(NotepadFrame, self).__init__(*args, **kwargs)
        self.current_file = None
        self.modified = False
        self.InitUI()

    def InitUI(self):
        # Menu bar
        menubar = wx.MenuBar()

        file_menu = wx.Menu()
        item_new = file_menu.Append(wx.ID_NEW, _("New") + "\tCtrl+N")
        item_open = file_menu.Append(wx.ID_OPEN, _("Open") + "\tCtrl+O")
        file_menu.AppendSeparator()
        item_save = file_menu.Append(wx.ID_SAVE, _("Save") + "\tCtrl+S")
        item_save_as = file_menu.Append(
            wx.ID_SAVEAS, _("Save As") + "\tCtrl+Shift+S"
        )
        file_menu.AppendSeparator()
        item_exit = file_menu.Append(wx.ID_EXIT, _("Exit") + "\tAlt+F4")

        menubar.Append(file_menu, _("File"))
        self.SetMenuBar(menubar)

        # Bind menu events
        self.Bind(wx.EVT_MENU, self.on_new, item_new)
        self.Bind(wx.EVT_MENU, self.on_open, item_open)
        self.Bind(wx.EVT_MENU, self.on_save, item_save)
        self.Bind(wx.EVT_MENU, self.on_save_as, item_save_as)
        self.Bind(wx.EVT_MENU, self.on_exit, item_exit)

        # Text area
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.text_ctrl = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_PROCESS_TAB | wx.HSCROLL
        )
        font = wx.Font(
            11, wx.FONTFAMILY_MODERN, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL
        )
        self.text_ctrl.SetFont(font)
        vbox.Add(self.text_ctrl, 1, wx.EXPAND)

        panel.SetSizer(vbox)

        # Track modifications
        self.text_ctrl.Bind(wx.EVT_TEXT, self.on_text_changed)

        # Keyboard shortcut for Escape
        self.text_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_key_press)

        # Handle close event
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.SetSize((800, 600))
        self.update_title()
        self.Centre()
        self.text_ctrl.SetFocus()

    def update_title(self):
        name = os.path.basename(self.current_file) if self.current_file else _("Untitled")
        modified_marker = " *" if self.modified else ""
        self.SetTitle(f"{name}{modified_marker} - {_('Notepad')}")

    def on_text_changed(self, event):
        if not self.modified:
            self.modified = True
            self.update_title()
        event.Skip()

    def check_save(self):
        """Ask user to save if there are unsaved changes. Returns True to proceed."""
        if not self.modified:
            return True
        dlg = wx.MessageDialog(
            self,
            _("Do you want to save changes?"),
            _("Unsaved Changes"),
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
        )
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == wx.ID_YES:
            return self.do_save()
        elif result == wx.ID_CANCEL:
            return False
        return True  # wx.ID_NO - discard changes

    def on_new(self, event=None):
        if not self.check_save():
            return
        self.text_ctrl.SetValue("")
        self.current_file = None
        self.modified = False
        self.update_title()

    def on_open(self, event=None):
        if not self.check_save():
            return
        wildcard = _("Text files") + " (*.txt)|*.txt|" + _("All files") + " (*.*)|*.*"
        dlg = wx.FileDialog(
            self, _("Open File"), wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.text_ctrl.SetValue(content)
                self.current_file = path
                self.modified = False
                self.update_title()
            except Exception as e:
                wx.MessageBox(
                    _("Failed to open file:") + f"\n{e}",
                    _("Error"),
                    wx.OK | wx.ICON_ERROR
                )
        dlg.Destroy()

    def on_save(self, event=None):
        self.do_save()

    def do_save(self):
        """Save the file. Returns True on success."""
        if self.current_file:
            return self.save_to_file(self.current_file)
        else:
            return self.do_save_as()

    def on_save_as(self, event=None):
        self.do_save_as()

    def do_save_as(self):
        """Save As dialog. Returns True on success."""
        wildcard = _("Text files") + " (*.txt)|*.txt|" + _("All files") + " (*.*)|*.*"
        dlg = wx.FileDialog(
            self, _("Save File As"), wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT
        )
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            dlg.Destroy()
            return self.save_to_file(path)
        dlg.Destroy()
        return False

    def save_to_file(self, path):
        """Write content to file. Returns True on success."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.text_ctrl.GetValue())
            self.current_file = path
            self.modified = False
            self.update_title()
            return True
        except Exception as e:
            wx.MessageBox(
                _("Failed to save file:") + f"\n{e}",
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )
            return False

    def on_exit(self, event=None):
        self.Close()

    def on_key_press(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def on_close(self, event):
        if self.check_save():
            self.Destroy()
        else:
            if event.CanVeto():
                event.Veto()


if __name__ == "__main__":
    app = wx.App(False)
    frame = NotepadFrame(None)
    frame.Show()
    app.MainLoop()
```

---

## Multiplatform Requirements

All TCE apps MUST work on **Windows, macOS, and Linux**. Follow these rules:

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

### keyboard library — guard on macOS (hangs without Accessibility permission)
```python
import sys
KEYBOARD_AVAILABLE = False
if sys.platform != 'darwin':
    try:
        import keyboard
        KEYBOARD_AVAILABLE = True
    except ImportError:
        pass
# Always check before use: if KEYBOARD_AVAILABLE: keyboard.press(...)
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

### Common mistakes to avoid
- `os.environ['APPDATA']` → use `os.getenv('APPDATA') or os.path.expanduser('~')` (KeyError on Linux/macOS)
- `os.environ['USERPROFILE']` → use `os.path.expanduser('~')` (works on all platforms)
- `os.environ['PUBLIC']` → use `os.environ.get('PUBLIC', '')` (only exists on Windows)
- `os.sys.platform` → **AttributeError!** Use `sys.platform` (after `import sys`)
- `os.system(cmd)` → use `subprocess.Popen(...)` (safer, cross-platform)
- `os.startfile(path)` → Windows only, always use the platform check above

## Action:

Ask the user for application details and create a complete, working application following TCE Launcher conventions.
