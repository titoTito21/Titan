# Titan Application Creation Guide

## Introduction

Titan applications are standalone programs launched from the launcher. They can be Python applications, compiled executables (.exe), or other types of executable files. Applications are displayed in the "Applications" category in the invisible interface.

## Application System Architecture

### Application Location
All applications are located in the `data/applications/` directory. Each application is a separate directory containing:
- `__app.tce` - application configuration file (required)
- `main.py` - main application file (or other file specified in openfile)
- additional application files and resources

### Application Launch Process

1. **Compilation** - .py files are automatically compiled to .pyc
2. **Environment** - PYTHONPATH and environment variables are set
3. **Launch** - application runs in separate process
4. **Isolation** - each application runs in its working directory

## Configuration File Structure

### __app.tce
File in key=value format:

```
name_pl=Nazwa aplikacji po polsku
name_en=Application name in English
openfile=main.py
shortname=myapp
hidden=false
```

**Required parameters:**
- `openfile` - name of file to execute

**Optional parameters:**
- `name_pl` - name in Polish
- `name_en` - name in English  
- `name` - default name (if no translations)
- `shortname` - short name for programmatic calls
- `hidden` - whether to hide application in list (true/false)

## Python Application Implementation

### Basic main.py structure

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import wx
import sys
import os

class MyAppFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="My Application")
        self.InitUI()
        self.Center()
        
    def InitUI(self):
        """Initialize user interface"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Add controls
        self.text_ctrl = wx.TextCtrl(panel, style=wx.TE_MULTILINE)
        vbox.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        # Button
        btn = wx.Button(panel, label="Click me")
        btn.Bind(wx.EVT_BUTTON, self.OnButtonClick)
        vbox.Add(btn, 0, wx.ALL | wx.CENTER, 5)
        
        panel.SetSizer(vbox)
        
    def OnButtonClick(self, event):
        """Handle button click"""
        self.text_ctrl.AppendText("Button was clicked!\n")

class MyApp(wx.App):
    def OnInit(self):
        frame = MyAppFrame()
        frame.Show()
        return True

if __name__ == '__main__':
    app = MyApp()
    app.MainLoop()
```

### Access to Titan Modules

Applications have automatic access to Titan modules:

```python
# Import Titan modules
from sound import play_sound, play_error_sound
from settings import get_setting, set_setting
from translation import get_available_languages

# Use in application
def on_action(self):
    play_sound("focus.ogg")
    
    # Save application setting
    set_setting('my_app_setting', 'value', section='my_app')
    
    # Read setting
    value = get_setting('my_app_setting', 'default', section='my_app')
```

## Command Line Arguments Handling

Applications can receive arguments during launch:

```python
import sys

def main():
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        print(f"Received file path: {file_path}")
        # Open file in application
        open_file(file_path)
    else:
        # Run normally without arguments
        start_normal_mode()

if __name__ == '__main__':
    main()
```

## Application Internationalization

### babel.cfg Configuration
```ini
[python: **.py]
```

### Translation Structure
```
data/applications/my_application/
├── main.py
├── __app.tce
├── babel.cfg
├── languages/
│   ├── messages.pot
│   ├── pl/
│   │   └── LC_MESSAGES/
│   │       ├── messages.po
│   │       └── messages.mo
│   └── en/
│       └── LC_MESSAGES/
│           ├── messages.po
│           └── messages.mo
└── translation.py
```

### translation.py File
```python
import gettext
import os

def setup_translation():
    """Configure translations for the application"""
    # Get language from environment variable set by Titan
    lang = os.environ.get('LANG', 'en')
    
    domain = 'messages'
    localedir = os.path.join(os.path.dirname(__file__), 'languages')
    
    try:
        translation = gettext.translation(domain, localedir, languages=[lang], fallback=True)
        translation.install()
        return translation.gettext
    except Exception as e:
        print(f"Translation configuration error: {e}")
        return lambda x: x

# Use in application
_ = setup_translation()

# In application code
title = _("My Application")
message = _("Hello, world!")
```

### Babel Commands
```bash
# Extract texts for translation
pybabel extract -o languages/messages.pot --input-dirs=.

# Create translation files
pybabel init -l pl -d languages -i languages/messages.pot
pybabel init -l en -d languages -i languages/messages.pot

# Update existing translations
pybabel update -l pl -d languages -i languages/messages.pot
pybabel update -l en -d languages -i languages/messages.pot

# Compile translations
pybabel compile -d languages
```

## Application Examples

### Example 1: Simple Text Editor
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import wx
import os

class TextEditorFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Text Editor", size=(600, 400))
        self.current_file = None
        self.InitUI()
        self.Center()
        
    def InitUI(self):
        # Menu
        menubar = wx.MenuBar()
        
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_NEW, "&New\tCtrl+N")
        file_menu.Append(wx.ID_OPEN, "&Open\tCtrl+O")
        file_menu.Append(wx.ID_SAVE, "&Save\tCtrl+S")
        file_menu.AppendSeparator()
        file_menu.Append(wx.ID_EXIT, "E&xit\tCtrl+Q")
        
        menubar.Append(file_menu, "&File")
        self.SetMenuBar(menubar)
        
        # Text area
        self.text_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        
        # Status bar
        self.statusbar = self.CreateStatusBar()
        self.statusbar.SetStatusText("Ready")
        
        # Events
        self.Bind(wx.EVT_MENU, self.OnNew, id=wx.ID_NEW)
        self.Bind(wx.EVT_MENU, self.OnOpen, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.OnSave, id=wx.ID_SAVE)
        self.Bind(wx.EVT_MENU, self.OnExit, id=wx.ID_EXIT)
        
    def OnNew(self, event):
        self.text_ctrl.Clear()
        self.current_file = None
        self.SetTitle("Text Editor - New Document")
        
    def OnOpen(self, event):
        dlg = wx.FileDialog(self, "Open file", wildcard="Text files (*.txt)|*.txt")
        if dlg.ShowModal() == wx.ID_OK:
            self.current_file = dlg.GetPath()
            with open(self.current_file, 'r', encoding='utf-8') as f:
                self.text_ctrl.SetValue(f.read())
            self.SetTitle(f"Text Editor - {os.path.basename(self.current_file)}")
        dlg.Destroy()
        
    def OnSave(self, event):
        if self.current_file:
            with open(self.current_file, 'w', encoding='utf-8') as f:
                f.write(self.text_ctrl.GetValue())
            self.statusbar.SetStatusText("File saved")
        else:
            self.OnSaveAs(event)
            
    def OnSaveAs(self, event):
        dlg = wx.FileDialog(self, "Save file", wildcard="Text files (*.txt)|*.txt", 
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            self.current_file = dlg.GetPath()
            self.OnSave(event)
        dlg.Destroy()
        
    def OnExit(self, event):
        self.Close()

class TextEditorApp(wx.App):
    def OnInit(self):
        frame = TextEditorFrame()
        frame.Show()
        
        # Check if file was passed to open
        if len(sys.argv) > 1:
            file_path = sys.argv[1]
            if os.path.exists(file_path):
                frame.current_file = file_path
                with open(file_path, 'r', encoding='utf-8') as f:
                    frame.text_ctrl.SetValue(f.read())
                frame.SetTitle(f"Text Editor - {os.path.basename(file_path)}")
        
        return True

if __name__ == '__main__':
    app = TextEditorApp()
    app.MainLoop()
```

### Example 2: Calculator
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import wx
import math

class CalculatorFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Calculator", style=wx.DEFAULT_FRAME_STYLE & ~wx.RESIZE_BORDER)
        self.InitUI()
        self.Center()
        self.current_value = "0"
        self.previous_value = None
        self.operation = None
        
    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Display
        self.display = wx.TextCtrl(panel, value="0", style=wx.TE_RIGHT | wx.TE_READONLY)
        self.display.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        vbox.Add(self.display, 0, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        button_data = [
            ['C', 'CE', '←', '/'],
            ['7', '8', '9', '*'],
            ['4', '5', '6', '-'],
            ['1', '2', '3', '+'],
            ['±', '0', '.', '=']
        ]
        
        for row in button_data:
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            for label in row:
                btn = wx.Button(panel, label=label, size=(50, 40))
                btn.Bind(wx.EVT_BUTTON, self.OnButtonClick)
                hbox.Add(btn, 0, wx.ALL, 2)
            vbox.Add(hbox, 0, wx.CENTER)
            
        panel.SetSizer(vbox)
        self.Fit()
        
    def OnButtonClick(self, event):
        label = event.GetEventObject().GetLabel()
        
        if label.isdigit():
            self.OnNumber(label)
        elif label == '.':
            self.OnDecimal()
        elif label in ['+', '-', '*', '/']:
            self.OnOperation(label)
        elif label == '=':
            self.OnEquals()
        elif label == 'C':
            self.OnClear()
        elif label == 'CE':
            self.OnClearEntry()
        elif label == '←':
            self.OnBackspace()
        elif label == '±':
            self.OnPlusMinus()
            
    def OnNumber(self, digit):
        if self.current_value == "0":
            self.current_value = digit
        else:
            self.current_value += digit
        self.UpdateDisplay()
        
    def OnDecimal(self):
        if '.' not in self.current_value:
            self.current_value += '.'
        self.UpdateDisplay()
        
    def OnOperation(self, op):
        if self.operation and self.previous_value:
            self.OnEquals()
        self.previous_value = float(self.current_value)
        self.operation = op
        self.current_value = "0"
        
    def OnEquals(self):
        if self.operation and self.previous_value is not None:
            current = float(self.current_value)
            try:
                if self.operation == '+':
                    result = self.previous_value + current
                elif self.operation == '-':
                    result = self.previous_value - current
                elif self.operation == '*':
                    result = self.previous_value * current
                elif self.operation == '/':
                    if current != 0:
                        result = self.previous_value / current
                    else:
                        wx.MessageBox("Cannot divide by zero!", "Error", wx.OK | wx.ICON_ERROR)
                        return
                        
                self.current_value = str(result)
                self.UpdateDisplay()
                self.operation = None
                self.previous_value = None
            except Exception as e:
                wx.MessageBox(f"Calculation error: {e}", "Error", wx.OK | wx.ICON_ERROR)
                
    def OnClear(self):
        self.current_value = "0"
        self.previous_value = None
        self.operation = None
        self.UpdateDisplay()
        
    def OnClearEntry(self):
        self.current_value = "0"
        self.UpdateDisplay()
        
    def OnBackspace(self):
        if len(self.current_value) > 1:
            self.current_value = self.current_value[:-1]
        else:
            self.current_value = "0"
        self.UpdateDisplay()
        
    def OnPlusMinus(self):
        if self.current_value != "0":
            if self.current_value.startswith("-"):
                self.current_value = self.current_value[1:]
            else:
                self.current_value = "-" + self.current_value
        self.UpdateDisplay()
        
    def UpdateDisplay(self):
        # Format number display
        try:
            val = float(self.current_value)
            if val.is_integer():
                display_text = str(int(val))
            else:
                display_text = self.current_value
        except:
            display_text = self.current_value
            
        self.display.SetValue(display_text)

class CalculatorApp(wx.App):
    def OnInit(self):
        frame = CalculatorFrame()
        frame.Show()
        return True

if __name__ == '__main__':
    app = CalculatorApp()
    app.MainLoop()
```

## Console Applications

You can also create console applications:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

def main():
    print("=== My Console Application ===")
    
    if len(sys.argv) > 1:
        print(f"Received arguments: {sys.argv[1:]}")
    
    while True:
        command = input("Enter command (help/exit): ").strip().lower()
        
        if command == "exit":
            break
        elif command == "help":
            print("Available commands:")
            print("- help: shows this help")
            print("- exit: ends program")
        else:
            print(f"Unknown command: {command}")
    
    print("Program ended")

if __name__ == '__main__':
    main()
```

## Executable Applications (.exe)

You can also use compiled applications:

**__app.tce:**
```
name_pl=Moja aplikacja
name_en=My Application
openfile=myapp.exe
```

## Testing Applications

1. Create directory in `data/applications/application_name/`
2. Add `__app.tce` and main application file
3. Start Titan
4. Check if application appears in "Applications" category
5. Test launch and functionality

## Important Guidelines

1. **Always add __app.tce file** - without it application won't be visible
2. **Test with arguments** - applications can receive files to open
3. **Use translations** - add multilingual support for better accessibility
4. **Handle errors** - add try/catch for stability
5. **Optimize size** - remove unnecessary files from application directory
6. **Document settings** - if using settings, describe options
7. **Test compilation** - .py files are automatically compiled to .pyc

## Directory Structure

```
data/applications/my_application/
├── __app.tce           # Application configuration (required)
├── main.py             # Main application file
├── babel.cfg           # Translation configuration (optional)
├── languages/          # Translations (optional)
│   ├── messages.pot
│   ├── pl/
│   └── en/
├── resources/          # Resources (optional)
│   ├── images/
│   ├── sounds/
│   └── data/
├── modules/            # Additional modules (optional)
│   └── helpers.py
└── translation.py      # Translation handling (optional)
```

Titan applications provide a simple platform for creating independent programs with access to launcher functionality and full internationalization support.