# Titan Component Creation Guide

## Introduction

Titan components are system extensions that run in the background and can add functionality to the main application. Components can be enabled/disabled by users and integrate with the system menu.

## Component System Architecture

### Component Location
All components are located in the `data/components/` directory. Each component is a separate directory containing:
- `init.py` - main file with component code
- `__component__.TCE` - component configuration file

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
status = 0
```

**Parameters:**
- `name` - name displayed in component manager
- `status` - `0` = enabled, `1` = disabled

## Component Implementation

### Basic init.py structure

```python
# -*- coding: utf-8 -*-
import wx
import threading
import time

class MyComponent:
    def __init__(self):
        self.running = False
        self.thread = None
    
    def start(self):
        """Starts the component"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
    
    def stop(self):
        """Stops the component"""
        self.running = False
    
    def _run(self):
        """Main component loop"""
        while self.running:
            # Component logic here
            time.sleep(1)

# Global component instance
component_instance = None

def initialize(app=None):
    """
    Called during Titan initialization.
    app - main application instance (optional)
    """
    global component_instance
    component_instance = MyComponent()
    component_instance.start()
    print("Component initialized")

def shutdown():
    """Called during Titan shutdown"""
    global component_instance
    if component_instance:
        component_instance.stop()
    print("Component shutdown")

def add_menu(component_manager):
    """
    Adds items to component menu.
    component_manager - ComponentManager instance
    """
    component_manager.register_menu_function("Component Option", my_menu_function)

def add_settings(settings_frame):
    """
    Adds settings to configuration window.
    settings_frame - Titan settings frame
    """
    # Here you can add controls to settings
    pass

def my_menu_function():
    """Function called from component menu"""
    wx.MessageBox("Component action executed!", "Component", wx.OK | wx.ICON_INFORMATION)
```

## Required Functions

### initialize(app=None)
**Required function** called at Titan startup:
- `app` - main wxPython application instance (may be None)
- Use to initialize resources, start threads

### shutdown() (optional)
Called during Titan shutdown:
- Stop threads, release resources
- Save component state if needed

### add_menu(component_manager) (optional)
Adds items to component menu:
- `component_manager.register_menu_function(name, function)`
- Menu available in invisible interface

### add_settings(settings_frame) (optional)
Adds controls to settings window:
- `settings_frame` - main settings window
- Add panels, checkboxes, sliders, etc.

## Component Examples

### Example 1: System Monitor
```python
# -*- coding: utf-8 -*-
import psutil
import threading
import time
import wx

class SystemMonitor:
    def __init__(self):
        self.running = False
        self.thread = None
        self.cpu_threshold = 80.0
    
    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
    
    def _monitor(self):
        while self.running:
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > self.cpu_threshold:
                wx.CallAfter(self._show_warning, cpu_percent)
            time.sleep(5)
    
    def _show_warning(self, cpu_percent):
        message = f"High CPU usage: {cpu_percent:.1f}%"
        wx.MessageBox(message, "System Warning", wx.OK | wx.ICON_WARNING)

monitor_instance = None

def initialize(app=None):
    global monitor_instance
    monitor_instance = SystemMonitor()
    monitor_instance.start()

def shutdown():
    global monitor_instance
    if monitor_instance:
        monitor_instance.stop()

def add_menu(component_manager):
    component_manager.register_menu_function("Show System Info", show_system_info)

def show_system_info():
    cpu = psutil.cpu_percent()
    memory = psutil.virtual_memory().percent
    message = f"CPU: {cpu}%\nMemory: {memory}%"
    wx.MessageBox(message, "System Information", wx.OK | wx.ICON_INFORMATION)
```

### Example 2: Time Notifications
```python
# -*- coding: utf-8 -*-
import wx
import threading
import time
from datetime import datetime, timedelta

class TimeNotifier:
    def __init__(self):
        self.running = False
        self.thread = None
        self.notifications = []  # List of (time, message)
    
    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._check_notifications, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
    
    def add_notification(self, minutes_from_now, message):
        """Adds notification in X minutes"""
        notification_time = datetime.now() + timedelta(minutes=minutes_from_now)
        self.notifications.append((notification_time, message))
    
    def _check_notifications(self):
        while self.running:
            now = datetime.now()
            # Check notifications to show
            to_show = [msg for time, msg in self.notifications if time <= now]
            # Remove shown notifications
            self.notifications = [(t, m) for t, m in self.notifications if t > now]
            
            for message in to_show:
                wx.CallAfter(self._show_notification, message)
            
            time.sleep(10)  # Check every 10 seconds
    
    def _show_notification(self, message):
        wx.MessageBox(message, "Notification", wx.OK | wx.ICON_INFORMATION)

notifier_instance = None

def initialize(app=None):
    global notifier_instance
    notifier_instance = TimeNotifier()
    notifier_instance.start()
    # Example notification in 1 minute
    notifier_instance.add_notification(1, "This is a test notification!")

def shutdown():
    global notifier_instance
    if notifier_instance:
        notifier_instance.stop()

def add_menu(component_manager):
    component_manager.register_menu_function("Add Notification", add_notification_dialog)

def add_notification_dialog():
    dlg = wx.TextEntryDialog(None, "Enter notification message:", "New Notification")
    if dlg.ShowModal() == wx.ID_OK:
        message = dlg.GetValue()
        if notifier_instance and message:
            notifier_instance.add_notification(5, message)  # In 5 minutes
            wx.MessageBox("Notification will be shown in 5 minutes", "Added", wx.OK)
    dlg.Destroy()
```

## System Integration

### Access to Main Application
```python
def initialize(app=None):
    if app:
        # Access to main window
        main_frame = app.GetTopWindow()
        # Access to menu
        menubar = main_frame.GetMenuBar()
        # Access to statusbar
        statusbar = main_frame.GetStatusBar()
```

### Thread-Safe Calls
```python
# Use wx.CallAfter for GUI operations from threads
wx.CallAfter(self._update_ui, data)

def _update_ui(self, data):
    # GUI modification code
    pass
```

### Using System Sounds
```python
from sound import play_sound, play_error_sound, play_dialog_sound

def my_function():
    play_sound("focus.ogg")  # Play sound from theme
    play_error_sound()       # Error sound
```

### Access to Settings
```python
from settings import get_setting, set_setting

def initialize(app=None):
    # Read setting
    enabled = get_setting('my_component_enabled', 'True', section='components')
    
    # Save setting
    set_setting('my_component_value', '42', section='components')
```

## Component State Management

### Enable/Disable
Users can enable/disable components through:
1. Component manager in GUI
2. Invisible interface → Menu → Components

### State Persistence
Enabled/disabled state is saved in `__component__.TCE`:
```ini
[component]
name = My Component
status = 0  # 0 = enabled, 1 = disabled
```

## Directory Structure

```
data/components/my_component/
├── init.py              # Main component file
├── __component__.TCE    # Component configuration
├── resources/           # Resources (optional)
│   ├── sounds/
│   └── images/
└── config/              # Configuration files (optional)
    └── settings.ini
```

## Testing Components

1. Place component in `data/components/component_name/`
2. Start Titan
3. Check in component manager if component is loaded
4. Test functionality through component menu

## Important Guidelines

1. **Always use daemon threads** - `threading.Thread(daemon=True)`
2. **Handle shutdown()** - stop all threads
3. **Use wx.CallAfter** for GUI operations from threads
4. **Test enable/disable** functionality
5. **Add error handling** - components shouldn't crash Titan
6. **Save resources** - don't perform heavy operations too often
7. **Document menu functions** - explain what they do

## Debugging

### Component Logs
```python
import logging

# Configure logger
logger = logging.getLogger(__name__)

def initialize(app=None):
    logger.info("Component initializing")
    
def shutdown():
    logger.info("Component shutting down")
```

### Error Handling
```python
def initialize(app=None):
    try:
        # Initialization code
        pass
    except Exception as e:
        print(f"Component initialization error: {e}")
        # Optionally show error dialog
        wx.MessageBox(f"Component error: {e}", "Error", wx.OK | wx.ICON_ERROR)
```

Titan components enable extending system functionality in a modular and safe way. With the simple API, you can easily add new capabilities without modifying the main application code.