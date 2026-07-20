# Titan IM Module Creation Guide

## Introduction

Titan IM modules are external communicator plugins for the Titan IM system in TCE Launcher. Modules live in the `data/titanIM_modules/` directory and can add custom communicators, RSS readers, social tools, and much more.

## Titan IM Module Architecture

### Module Location
All modules are located in the `data/titanIM_modules/` directory. Each module is a separate directory containing:
- `init.py` - the main file with the module's code (NOT `__init__.py`!)
- `__im.TCE` - the module's configuration file (INI format)

### Module Lifecycle

1. **Loading** - modules are loaded at Titan IM startup
2. **Opening** - `open(parent_frame)` is called when the user selects the module
3. **Status** - the optional `get_status_text()` returns status text

## Configuration File Structure

### __im.TCE

INI file with an `[im_module]` section:

```ini
[im_module]
name = Module Name
status = 0
description = Module description

```

**Parameters:**
- `name` - name displayed in the Titan IM list
- **`status = 0` means ENABLED, any other value means DISABLED**
- `description` - module description (optional)
- `libs` (optional) - comma-separated dirs under the module folder added
  to `sys.path` before loading (default `lib`), so the module can vendor
  its own dependencies
- **IMPORTANT**: File name is `__im.TCE` (uppercase .TCE)
- **IMPORTANT**: Main file is `init.py` (lowercase, NOT `__init__.py`)
- **IMPORTANT**: Add a blank line at end of file

## Module Implementation

### Basic init.py structure

```python
# -*- coding: utf-8 -*-
"""
Module Name - Titan IM external module for TCE Launcher
Module description
"""

import os
import sys

# Add the TCE root directory to the path
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# The Sound API and the _() function are automatically injected by the module manager:
# - _module.sounds: unified TitanNet/Titan IM sounds (Telegram, EltenLink, Titan-Net)
# - _: gettext from {module_path}/languages/ (domain = module id, language from TCE settings)
_module = sys.modules[__name__]


def open(parent_frame):
    """Open the communicator window.

    Called when the user selects this module from the Titan IM list.
    parent_frame: wx.Frame or None - parent window reference
    """
    try:
        import wx
        sounds = _module.sounds

        # Play the welcome sound (unified across all Titan IM integrations)
        sounds.welcome()

        # TODO: Implement your communicator window here
        # Example:
        # frame = MyIMFrame(parent_frame)
        # frame.Show()

        sounds.dialog_open()
        wx.MessageBox("Module opened!", "Module Name", wx.OK | wx.ICON_INFORMATION, parent_frame)
    except Exception as e:
        print(f"[module_id] Error opening: {e}")


def get_status_text():
    """Return the connection status suffix shown after the module name in the Titan IM list.

    Return an empty string if not connected / no status to show.
    Examples: "- connected as jan", "- 3 unread"
    """
    return ""
```

## Required Functions

### open(parent_frame)
**Required function** called when the user opens the module:
```python
def open(parent_frame):
    """
    parent_frame: wx.Frame or None for console mode
    """
    sounds = _module.sounds  # Access the Sound API
    sounds.welcome()  # Play the welcome sound

    # Create and show your communicator window
    # ...
```

## Optional Functions

### get_status_text()
Returns the status text shown after the module name:
```python
def get_status_text():
    """
    Returns:
        str: Status suffix, e.g. "- connected as username" or ""
    """
    if connected and username:
        return f"- connected as {username}"
    return ""
```

## Config API (Automatically Injected)

Every module also receives a `config` object via `_module.config` — a
namespaced load/save helper backed by the shared, encrypted `titan.IM`
file. Each module's data is stored under a key matching its folder name, so
other modules' data (Telegram, EltenLink...) is never disturbed:

```python
data = _module.config.load()                  # this module's dict ({} if none)
_module.config.save({"username": "jan"})       # replaces the whole module dict
value = _module.config.get("username", "")     # single key, with a default
_module.config.set("username", "jan")          # single key
_module.config.update(username="jan", token="...")  # merge multiple keys at once
```

Use this instead of writing your own settings file if the module needs to
remember login state, tokens, or preferences between sessions.

## Translations (Automatically Injected)

If the module folder contains a `languages/` directory, the loader sets
`mod._` in the module's namespace **before** `init.py` runs — since that
IS the module's namespace, a plain `_("text")` call works directly in the
module's code, with no `import` or manual `gettext.translation()` setup.
The gettext domain is **the module's folder name** (not a fixed domain
like TTS engines use). If `languages/` is missing or fails to load, it
falls back to an identity function.

## Sound API (Automatically Injected)

Every module receives a `sounds` object via `_module.sounds` with unified TitanNet/Titan IM sounds.

### Main Sound Categories

#### Messages
```python
sounds.new_message()        # New message received
sounds.message_sent()       # Message sent
sounds.chat_message()       # Chat message (in the active chat)
sounds.typing()             # Typing indicator
```

#### User Presence
```python
sounds.user_online()        # User logged in
sounds.user_offline()       # User logged out
sounds.status_changed()     # User status changed
sounds.account_created()    # New account created
```

#### Chats/Rooms
```python
sounds.new_chat()           # New chat or room opened
sounds.new_replies()        # New replies (forum, thread)
```

#### Voice Calls
```python
sounds.call_connected()     # Voice call connected
sounds.ring_incoming()      # Incoming ring
sounds.ring_outgoing()      # Outgoing ring
sounds.walkie_talkie_start()    # Push-to-talk activated
sounds.walkie_talkie_end()      # Push-to-talk deactivated
sounds.recording_start()    # Voice recording started
sounds.recording_stop()     # Voice recording stopped
```

#### Files
```python
sounds.file_received()      # New file received
sounds.file_success()       # File operation succeeded
sounds.file_error()         # File operation failed
```

#### General Notifications
```python
sounds.notification()       # General notification
sounds.success()            # Success notification
sounds.error()               # Error notification
sounds.welcome()            # Module opened
sounds.goodbye()            # Module closed / disconnected
sounds.birthday()           # Birthday notification
sounds.new_feed_post()      # New feed post
sounds.moderation()         # Moderation alert / broadcast
sounds.motd()               # Message of the day
sounds.app_update()         # Application/package update
```

#### UI Sounds - Core
```python
sounds.focus(pan=0.5)       # Focus change (stereo pan 0.0-1.0)
sounds.select()             # Selection / action confirmed
sounds.click()               # Simple click
```

#### UI Sounds - Dialogs
```python
sounds.dialog_open()        # Dialog opened
sounds.dialog_close()       # Dialog closed
sounds.window_open()        # Window opened
sounds.window_close()       # Window closed
sounds.popup()               # Popup opened
sounds.popup_close()        # Popup closed
sounds.msg_box()            # Message box opened
sounds.msg_box_close()      # Message box closed
```

#### UI Sounds - Context Menus
```python
sounds.context_menu()       # Context menu opened
sounds.context_menu_close() # Context menu closed
```

#### UI Sounds - Lists and Navigation
```python
sounds.end_of_list()        # End of list reached
sounds.section_change()     # Section/tab changed
sounds.switch_category()    # Category switched
sounds.switch_list()        # List switched
sounds.focus_collapsed()    # Tree node collapsed
sounds.focus_expanded()     # Tree node expanded
```

#### UI Sounds - Notifications and Window State
```python
sounds.notify_sound()       # Notification sound (no TTS)
sounds.tip()                 # Tip / hint
sounds.minimize()           # Window minimized
sounds.restore()            # Window restored
```

#### System Sounds
```python
sounds.connecting()         # Connecting in progress
```

### TTS (Text-to-Speech) Notifications

```python
# Simple TTS with stereo positioning
sounds.speak("Connected!", position=0.0, pitch_offset=0)

# Notification with an automatic sound effect + TTS (respects TCE settings)
# Types: 'error', 'success', 'info', 'warning', 'banned'
sounds.notify("Login successful", 'success')
sounds.notify("Connection failed", 'error')
sounds.notify("New update available", 'info')
sounds.notify("Rate limit exceeded", 'warning')

# TTS-only notification (no sound effect)
sounds.notify("Reply posted", 'success', play_sound_effect=False)
```

### Direct Sound Access

```python
# Play any sound file from the sfx/ directory
sounds.play('titannet/new_message.ogg')
sounds.play('core/FOCUS.ogg', pan=0.3)  # pan: 0.0 (left) to 1.0 (right)
```

Full API documentation: `data/titanIM_modules/README.md`

## Complete Code Examples

### Example 1: Simple Chat Client

A complete IM module opening a chat window with a contact list, message display, message input, and full Sound API integration.

**File: `data/titanIM_modules/SimpleChat/__im.TCE`**
```ini
[im_module]
name = Simple Chat
status = 0
description = A simple chat client with contacts, messages, and sound notifications

```

**File: `data/titanIM_modules/SimpleChat/init.py`**

```python
# -*- coding: utf-8 -*-
"""
Simple Chat - Titan IM external module for TCE Launcher
A simple chat client demonstrating contacts, messages, and the Sound API.
"""

import os
import sys
import threading
import time

# Add the TCE root directory to the path
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# The Sound API and the _() function are automatically injected by the module manager
# (_: gettext from {module_path}/languages/, sounds: unified Sound API)
_module = sys.modules[__name__]

# Connection state for the status text
_state = {
    "connected": False,
    "username": "",
    "unread": 0
}


# ---------------------------------------------------------------------------
# Chat window
# ---------------------------------------------------------------------------

class SimpleChatFrame:
    """Main chat window with a contact list, message display, and input field."""

    def __init__(self, parent_frame, sounds):
        import wx

        self.sounds = sounds
        self.frame = wx.Frame(parent_frame, title="Simple Chat", size=(700, 500))
        self.frame.Bind(wx.EVT_CLOSE, self._on_close)

        # --- Demo data ---
        self.contacts = ["Alice", "Bob", "Charlie", "Diana", "Eve"]
        self.online = {"Alice", "Charlie", "Eve"}
        self.messages = {name: [] for name in self.contacts}
        self.current_contact = None

        # --- Layout ---
        main_panel = wx.Panel(self.frame)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Left: contact list
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(wx.StaticText(main_panel, label="Contacts"), 0, wx.ALL, 5)

        self.contact_list = wx.ListBox(main_panel, style=wx.LB_SINGLE)
        self._refresh_contacts()
        self.contact_list.Bind(wx.EVT_LISTBOX, self._on_contact_select)
        self.contact_list.Bind(wx.EVT_RIGHT_DOWN, self._on_contact_right_click)
        left_sizer.Add(self.contact_list, 1, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(left_sizer, 1, wx.EXPAND)

        # Right: messages + input
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer.Add(wx.StaticText(main_panel, label="Messages"), 0, wx.ALL, 5)

        self.message_display = wx.TextCtrl(
            main_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        right_sizer.Add(self.message_display, 1, wx.EXPAND | wx.ALL, 5)

        # Input row
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.message_input = wx.TextCtrl(main_panel, style=wx.TE_PROCESS_ENTER)
        self.message_input.Bind(wx.EVT_TEXT_ENTER, self._on_send)
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 5)

        send_btn = wx.Button(main_panel, label="Send")
        send_btn.Bind(wx.EVT_BUTTON, self._on_send)
        input_sizer.Add(send_btn, 0, wx.ALL, 5)

        right_sizer.Add(input_sizer, 0, wx.EXPAND)
        main_sizer.Add(right_sizer, 2, wx.EXPAND)

        main_panel.SetSizer(main_sizer)

        # Simulate connecting
        self._connect()

    # --- Connection ---

    def _connect(self):
        """Simulate connecting to a chat server."""
        self.sounds.connecting()
        _state["connected"] = True
        _state["username"] = "You"
        self.sounds.notify("Connected as You", 'success')

        # Simulate incoming messages in the background
        self._sim_thread = threading.Thread(target=self._simulate_incoming, daemon=True)
        self._sim_thread.start()

    def _simulate_incoming(self):
        """Simulate receiving messages from contacts after a delay."""
        import wx
        time.sleep(3)
        greetings = [
            ("Alice", "Hey! How are you?"),
            ("Charlie", "Did you see the latest update?"),
        ]
        for sender, text in greetings:
            self.messages[sender].append(f"{sender}: {text}")
            _state["unread"] += 1
            wx.CallAfter(self._on_incoming_message, sender)
            time.sleep(2)

    def _on_incoming_message(self, sender):
        """Handle a newly received message on the GUI thread."""
        self.sounds.new_message()
        self._refresh_contacts()
        if self.current_contact == sender:
            self._show_messages(sender)

    # --- Contact list ---

    def _refresh_contacts(self):
        self.contact_list.Clear()
        for name in self.contacts:
            status = " (online)" if name in self.online else ""
            unread = len([m for m in self.messages[name] if m.startswith(name)])
            tag = f" [{unread} new]" if unread else ""
            self.contact_list.Append(f"{name}{status}{tag}")

    def _on_contact_select(self, event):
        idx = self.contact_list.GetSelection()
        if idx == -1:
            return
        self.current_contact = self.contacts[idx]
        self.sounds.select()
        self._show_messages(self.current_contact)

    def _on_contact_right_click(self, event):
        import wx
        idx = self.contact_list.HitTest(event.GetPosition())
        if idx == -1:
            return
        self.contact_list.SetSelection(idx)
        self.current_contact = self.contacts[idx]

        menu = wx.Menu()
        item_info = menu.Append(wx.ID_ANY, "View Info")
        item_clear = menu.Append(wx.ID_ANY, "Clear History")

        self.frame.Bind(wx.EVT_MENU, self._on_view_info, item_info)
        self.frame.Bind(wx.EVT_MENU, self._on_clear_history, item_clear)

        self.sounds.context_menu()
        self.frame.PopupMenu(menu)
        menu.Destroy()
        self.sounds.context_menu_close()

    def _on_view_info(self, event):
        import wx
        name = self.current_contact
        if not name:
            return
        status = "Online" if name in self.online else "Offline"
        self.sounds.dialog_open()
        wx.MessageBox(f"Contact: {name}\nStatus: {status}", "Contact Info",
                      wx.OK | wx.ICON_INFORMATION, self.frame)
        self.sounds.dialog_close()

    def _on_clear_history(self, event):
        if self.current_contact:
            self.messages[self.current_contact].clear()
            self._show_messages(self.current_contact)
            self.sounds.notify("History cleared", 'info')

    # --- Messaging ---

    def _show_messages(self, contact):
        self.message_display.SetValue("\n".join(self.messages[contact]))

    def _on_send(self, event):
        text = self.message_input.GetValue().strip()
        if not text or not self.current_contact:
            self.sounds.error()
            return
        self.messages[self.current_contact].append(f"You: {text}")
        self.message_input.SetValue("")
        self._show_messages(self.current_contact)
        self.sounds.message_sent()

    # --- Close ---

    def _on_close(self, event):
        _state["connected"] = False
        _state["username"] = ""
        _state["unread"] = 0
        self.sounds.goodbye()
        self.frame.Destroy()

    def show(self):
        self.frame.Show()


# ---------------------------------------------------------------------------
# Module interface
# ---------------------------------------------------------------------------

def open(parent_frame):
    """Open the chat window.

    Called when the user selects this module from the Titan IM list.
    parent_frame: wx.Frame or None - parent window reference
    """
    try:
        sounds = _module.sounds
        sounds.welcome()
        chat = SimpleChatFrame(parent_frame, sounds)
        chat.show()
        sounds.window_open()
    except Exception as e:
        print(f"[SimpleChat] Error opening: {e}")
        try:
            _module.sounds.notify(f"Failed to open: {e}", 'error')
        except Exception:
            pass


def get_status_text():
    """Return the connection status suffix shown after the module name in the Titan IM list.

    Examples: "- connected as You", "- 2 unread"
    """
    if _state["connected"] and _state["username"]:
        parts = [f"- connected as {_state['username']}"]
        if _state["unread"] > 0:
            parts.append(f", {_state['unread']} unread")
        return "".join(parts)
    return ""
```

---

### Example 2: RSS Feed Reader

A simpler IM module that fetches and displays RSS feed items, opening them in the default browser.

**File: `data/titanIM_modules/RSSReader/__im.TCE`**
```ini
[im_module]
name = RSS Feed Reader
status = 0
description = RSS feed reader with browser integration and sound notifications

```

**File: `data/titanIM_modules/RSSReader/init.py`**

```python
# -*- coding: utf-8 -*-
"""
RSS Feed Reader - Titan IM external module for TCE Launcher
Fetches RSS feeds and displays items in an accessible list.
"""

import os
import sys
import threading
import webbrowser

# Add the TCE root directory to the path
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# The Sound API and the _() function are automatically injected by the module manager
# (_: gettext from {module_path}/languages/, sounds: unified Sound API)
_module = sys.modules[__name__]

# State for the status text
_state = {
    "unread": 0
}

# Default feed URL (can be changed in the reader window)
DEFAULT_FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"


# ---------------------------------------------------------------------------
# RSS parsing helpers
# ---------------------------------------------------------------------------

def _fetch_feed(url):
    """Fetch and parse an RSS feed. Returns a list of dicts with title, link, description."""
    import urllib.request
    import xml.etree.ElementTree as ET

    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TCE-RSSReader/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        root = ET.fromstring(data)

        # Support both RSS 2.0 (<channel><item>) and Atom (<entry>)
        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "No title")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")
            items.append({"title": title, "link": link, "description": desc})

        # Atom fallback
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", "No title", ns)
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                desc = entry.findtext("atom:summary", "", ns)
                items.append({"title": title, "link": link, "description": desc})
    except Exception as e:
        raise RuntimeError(f"Failed to fetch feed: {e}")

    return items


# ---------------------------------------------------------------------------
# Reader window
# ---------------------------------------------------------------------------

class RSSReaderFrame:
    """RSS feed reader window with a feed list and browser integration."""

    def __init__(self, parent_frame, sounds):
        import wx

        self.sounds = sounds
        self.items = []
        self.feed_url = DEFAULT_FEED_URL

        self.frame = wx.Frame(parent_frame, title="RSS Feed Reader", size=(600, 450))
        self.frame.Bind(wx.EVT_CLOSE, self._on_close)

        panel = wx.Panel(self.frame)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Feed URL input
        url_sizer = wx.BoxSizer(wx.HORIZONTAL)
        url_sizer.Add(wx.StaticText(panel, label="Feed URL:"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.url_input = wx.TextCtrl(panel, value=self.feed_url)
        url_sizer.Add(self.url_input, 1, wx.EXPAND | wx.ALL, 5)
        refresh_btn = wx.Button(panel, label="Refresh")
        refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh)
        url_sizer.Add(refresh_btn, 0, wx.ALL, 5)
        sizer.Add(url_sizer, 0, wx.EXPAND)

        # Status label
        self.status_label = wx.StaticText(panel, label="Press Refresh to load the feed.")
        sizer.Add(self.status_label, 0, wx.ALL, 5)

        # Feed items list
        self.item_list = wx.ListBox(panel)
        self.item_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_item_activate)
        self.item_list.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        sizer.Add(self.item_list, 1, wx.EXPAND | wx.ALL, 5)

        # Description display
        self.desc_display = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2
        )
        sizer.Add(self.desc_display, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Show description on selection
        self.item_list.Bind(wx.EVT_LISTBOX, self._on_item_select)

        panel.SetSizer(sizer)

        # Auto-load the feed
        self._on_refresh(None)

    # --- Feed loading ---

    def _on_refresh(self, event):
        """Load the feed in a background thread."""
        import wx
        self.feed_url = self.url_input.GetValue().strip()
        if not self.feed_url:
            self.sounds.error()
            return
        self.status_label.SetLabel("Loading...")
        self.sounds.connecting()
        threading.Thread(target=self._load_feed, daemon=True).start()

    def _load_feed(self):
        """Background thread: fetch the feed and update the UI."""
        import wx
        try:
            items = _fetch_feed(self.feed_url)
            wx.CallAfter(self._on_feed_loaded, items)
        except Exception as e:
            wx.CallAfter(self._on_feed_error, str(e))

    def _on_feed_loaded(self, items):
        self.items = items
        _state["unread"] = len(items)

        self.item_list.Clear()
        for item in items:
            self.item_list.Append(item["title"])

        self.status_label.SetLabel(f"Loaded {len(items)} items.")
        self.desc_display.SetValue("")

        if items:
            self.sounds.new_feed_post()
            self.sounds.notify(f"{len(items)} feed items loaded", 'success')
        else:
            self.sounds.notify("Feed is empty", 'info')

    def _on_feed_error(self, error_msg):
        self.status_label.SetLabel(f"Error: {error_msg}")
        self.sounds.notify(f"Feed error: {error_msg}", 'error')

    # --- Item interaction ---

    def _on_item_select(self, event):
        idx = self.item_list.GetSelection()
        if idx == -1 or idx >= len(self.items):
            return
        self.sounds.select()
        desc = self.items[idx].get("description", "No description available.")
        self.desc_display.SetValue(desc)

    def _on_item_activate(self, event):
        """Open the selected feed item in the default browser."""
        self._open_selected_item()

    def _on_key_down(self, event):
        if event.GetKeyCode() == 13:  # Enter
            self._open_selected_item()
        else:
            event.Skip()

    def _open_selected_item(self):
        idx = self.item_list.GetSelection()
        if idx == -1 or idx >= len(self.items):
            self.sounds.error()
            return
        link = self.items[idx].get("link", "")
        if link:
            webbrowser.open(link)
            self.sounds.notify("Opened in browser", 'info')
            if _state["unread"] > 0:
                _state["unread"] -= 1
        else:
            self.sounds.notify("No link available for this item", 'warning')

    # --- Close ---

    def _on_close(self, event):
        _state["unread"] = 0
        self.sounds.goodbye()
        self.frame.Destroy()

    def show(self):
        self.frame.Show()


# ---------------------------------------------------------------------------
# Module interface
# ---------------------------------------------------------------------------

def open(parent_frame):
    """Open the RSS feed reader window.

    Called when the user selects this module from the Titan IM list.
    parent_frame: wx.Frame or None - parent window reference
    """
    try:
        sounds = _module.sounds
        sounds.welcome()
        reader = RSSReaderFrame(parent_frame, sounds)
        reader.show()
        sounds.window_open()
    except Exception as e:
        print(f"[RSSReader] Error opening: {e}")
        try:
            _module.sounds.notify(f"Failed to open: {e}", 'error')
        except Exception:
            pass


def get_status_text():
    """Return the status suffix shown after the module name in the Titan IM list.

    Example: "- 5 unread"
    """
    if _state["unread"] > 0:
        return f"- {_state['unread']} unread"
    return ""
```

## Directory Structure

```
data/titanIM_modules/ModuleName/
├── init.py              # Main module file (NOT __init__.py!)
└── __im.TCE             # Module configuration
```

## Packaging as `.TCD` (Optional)

Instead of shipping a directory, a Titan IM module can be distributed as a
single `.tcd` file. Purely optional and additive.

```bash
python src/scripts/pack_addon.py data/titanIM_modules/MyModule --kind im_module -o MyModule.tcd
```

- `.tcd` is a custom compressed container (magic header + LZMA payload),
  deliberately not a real zip/7z — 7-Zip and Windows Explorer refuse to
  open it as an archive.
- No code changes needed: the payload is byte-identical to the directory,
  so `init.py` and `__im.TCE` still resolve the same way once extracted.
- Drop the `.tcd` into `data/titanIM_modules/` (bundled or per-user
  overlay) and it's discovered/loaded identically to a directory-based
  module.

See `src/titan_core/titan_package.py` for the format implementation.

## Testing Modules

1. Place the module in `data/titanIM_modules/ModuleName/`
2. Make sure the file is `init.py`, not `__init__.py`
3. Check the `__im.TCE` format (INI, uppercase .TCE)
4. Start Titan
5. Open Titan IM (in GUI, IUI, or Klango mode)
6. Check whether the module appears in the communicators list
7. Click/select the module — it should call `open(parent_frame)`
8. If `get_status_text()` is implemented, check that it shows after the module name

## How Modules Appear in Each Interface

- **GUI** (`src/ui/gui.py`): Listed in the network listbox, status shown inline
- **Invisible UI** (`src/ui/invisibleui.py`): Listed among the Titan IM category elements
- **Klango Mode** (`src/system/klangomode.py`): Listed in the Titan IM submenu

## Reference Example

- **ExampleIM** (`data/titanIM_modules/ExampleIM/`): Demonstrates the Sound API with demo buttons
  - Disabled by default (`status = 1`)
  - Demonstrates `sounds.welcome()`, `sounds.notify()`, presence sounds, etc.

## Key Tips

1. **Always implement `open(parent_frame)`** — required
2. **Use `_module.sounds` for unified sounds** — the same ones Telegram and Titan-Net use
3. **Implement `get_status_text()` for connection info** — users like seeing status
4. **Handle `parent_frame=None` gracefully** — support console mode
5. **Test across every interface mode** — GUI, Invisible UI, and Klango
6. **Use wx.CallAfter for GUI updates from threads** — thread-safe
7. **Add sounds for a better UX** — `new_message()`, `message_sent()`, `user_online()`, etc.
8. **Handle closing gracefully** — call `sounds.goodbye()`, clear state

Titan IM modules let you add custom communicators, social feeds, and tools to TCE Launcher without modifying the core code. Thanks to the unified Sound API, every module gets a consistent audio experience, matching the built-in integrations (Telegram, EltenLink, Titan-Net).
