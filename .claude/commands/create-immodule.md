# Create IM Module Wizard

Interactive wizard to create a new external IM module for Titan IM in TCE Launcher.

## Process:

1. **Ask for Module Details:**
   - Module name (display name in English)
   - Module ID (PascalCase, no spaces, for directory name)
   - Module description
   - Whether to include status text support (connection status)

2. **Create Module Structure:**
   - Create directory: `data/titanIM_modules/{module_id}/`
   - Create main file: `data/titanIM_modules/{module_id}/init.py`
   - Create config file: `data/titanIM_modules/{module_id}/__im.TCE`

3. **Generate Module Template (`init.py`):**
   ```python
   # -*- coding: utf-8 -*-
   """
   {Module Name} - Titan IM external module for TCE Launcher
   {Module Description}
   """

   import os
   import sys

   # Add TCE root directory to path for proper imports
   _MODULE_DIR = os.path.dirname(__file__)
   _TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
   if _TCE_ROOT not in sys.path:
       sys.path.insert(0, _TCE_ROOT)

   # Sound API - automatically injected by the module manager
   # Provides unified TitanNet/Titan IM sounds (same as Telegram, EltenLink, Titan-Net)
   _module = sys.modules[__name__]


   # Connection state (optional - for status text support)
   _state = {
       "connected": False,
       "username": ""
   }


   def open(parent_frame):
       """Open the communicator window.

       Called when the user selects this module from Titan IM list.
       parent_frame: wx.Frame or None - parent window reference
       """
       try:
           import wx
           sounds = _module.sounds

           # Play welcome sound (unified with all Titan IM integrations)
           sounds.welcome()

           # TODO: Implement your communicator window here
           # Example:
           # frame = MyIMFrame(parent_frame)
           # frame.Show()

           # Use sounds for consistent audio experience:
           # sounds.new_message()           # New message received
           # sounds.message_sent()          # Message sent
           # sounds.chat_message()          # Chat message in active chat
           # sounds.user_online()           # User came online
           # sounds.user_offline()          # User went offline
           # sounds.new_chat()              # New chat/room opened
           # sounds.new_replies()           # New replies (forum/thread)
           # sounds.call_connected()        # Voice call connected
           # sounds.ring_incoming()         # Incoming call
           # sounds.ring_outgoing()         # Outgoing call
           # sounds.recording_start()       # Voice recording started
           # sounds.recording_stop()        # Voice recording stopped
           # sounds.file_received()         # File received
           # sounds.file_success()          # File operation OK
           # sounds.file_error()            # File operation failed
           # sounds.notification()          # General notification
           # sounds.success()               # Success sound
           # sounds.error()                 # Error sound
           # sounds.moderation()            # Moderation alert
           # sounds.birthday()              # Birthday notification
           # sounds.new_feed_post()         # New feed post
           # sounds.app_update()            # App/package update
           # sounds.goodbye()               # Disconnect/close

           # UI sounds:
           # sounds.dialog_open()           # Dialog opened
           # sounds.dialog_close()          # Dialog closed
           # sounds.window_open()           # Window opened
           # sounds.window_close()          # Window closed
           # sounds.popup()                 # Popup opened
           # sounds.popup_close()           # Popup closed
           # sounds.context_menu()          # Context menu opened
           # sounds.context_menu_close()    # Context menu closed
           # sounds.focus(pan=0.5)          # Focus change (stereo pan)
           # sounds.select()                # Selection/action confirmed
           # sounds.click()                 # Simple click
           # sounds.end_of_list()           # End of list reached
           # sounds.section_change()        # Section/tab changed
           # sounds.switch_category()       # Category switched
           # sounds.switch_list()           # List switched
           # sounds.focus_collapsed()       # Tree node collapsed
           # sounds.focus_expanded()        # Tree node expanded
           # sounds.notify_sound()          # Notification sound (no TTS)
           # sounds.tip()                   # Tooltip/hint
           # sounds.minimize()              # Window minimized
           # sounds.restore()               # Window restored
           # sounds.connecting()            # Connection in progress
           # sounds.msg_box()               # Message box opened
           # sounds.msg_box_close()         # Message box closed

           # TTS notifications (respects TCE settings - stereo, pitch):
           # sounds.notify("Login successful", 'success')
           # sounds.notify("Connection failed", 'error')
           # sounds.notify("New update", 'info')
           # sounds.notify("Rate limit", 'warning')
           # sounds.notify("Posted", 'success', play_sound_effect=False)  # TTS only
           # sounds.speak("Custom text", position=0.0, pitch_offset=0)

           # Direct sound access:
           # sounds.play('titannet/new_message.ogg')
           # sounds.play('core/FOCUS.ogg', pan=0.3)

           sounds.dialog_open()
           wx.MessageBox("{Module Name} opened!", "{Module Name}", wx.OK | wx.ICON_INFORMATION, parent_frame)
       except Exception as e:
           print(f"[{module_id}] Error opening: {e}")


   def get_status_text():
       """Return connection status suffix shown after module name in Titan IM list.

       Return empty string if not connected / no status to show.
       Examples: "- connected as jan", "- 3 unread"
       """
       if _state["connected"] and _state["username"]:
           return f"- connected as {_state['username']}"
       return ""
   ```

   **Without status text** (simpler variant -- omit `_state` and `get_status_text()`):
   ```python
   # -*- coding: utf-8 -*-
   """
   {Module Name} - Titan IM external module for TCE Launcher
   {Module Description}
   """

   import os
   import sys

   _MODULE_DIR = os.path.dirname(__file__)
   _TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
   if _TCE_ROOT not in sys.path:
       sys.path.insert(0, _TCE_ROOT)

   # Sound API - automatically injected by the module manager
   _module = sys.modules[__name__]


   def open(parent_frame):
       """Open the communicator window."""
       try:
           import wx
           sounds = _module.sounds

           sounds.welcome()

           # TODO: Implement your communicator window here
           sounds.dialog_open()
           wx.MessageBox("{Module Name} opened!", "{Module Name}", wx.OK | wx.ICON_INFORMATION, parent_frame)
       except Exception as e:
           print(f"[{module_id}] Error opening: {e}")
   ```

4. **Create Config File (`__im.TCE` format):**
   ```ini
   [im_module]
   name = {Module Name}
   status = 0
   description = {Module Description}
   ```

   **IMPORTANT**:
   - Use INI format with `[im_module]` section
   - **`status = 0` means ENABLED, any other value means DISABLED**
   - File must be named `__im.TCE` (UPPERCASE .TCE)
   - Main file MUST be named `init.py` (lowercase, NOT `__init__.py`)
   - Include blank line at end of file

5. **Verify Installation:**
   - Restart TCE Launcher
   - Open Titan IM (in GUI, IUI, or Klango mode)
   - Check if module appears in the communicators list
   - Click/select module -- should call `open(parent_frame)`
   - If `get_status_text()` is implemented, check it shows after module name

## Module Interface:

Modules MUST define:
- `open(parent_frame)` -- Called when user opens the module (required)

Modules CAN define (optional):
- `get_status_text()` -- Returns suffix string for status display, e.g. `"- connected as jan"`. Return `""` if no status.

## Sound API (automatically injected):

Every module receives a `sounds` object via `_module.sounds` with unified TitanNet/Titan IM audio. Key methods:

**Messages:** `new_message()`, `message_sent()`, `chat_message()`, `typing()`
**Presence:** `user_online()`, `user_offline()`, `status_changed()`, `account_created()`
**Chat:** `new_chat()`, `new_replies()`
**Calls:** `call_connected()`, `ring_incoming()`, `ring_outgoing()`, `walkie_talkie_start()`, `walkie_talkie_end()`, `recording_start()`, `recording_stop()`
**Files:** `file_received()`, `file_success()`, `file_error()`
**Notifications:** `notification()`, `success()`, `error()`, `welcome()`, `goodbye()`, `birthday()`, `new_feed_post()`, `moderation()`, `motd()`, `app_update()`, `announcement()`, `announcement_ended()`, `announcement_status_changed()`, `iui()`
**UI Core:** `focus(pan)`, `select()`, `click()`
**UI Dialogs:** `dialog_open()`, `dialog_close()`, `window_open()`, `window_close()`, `popup()`, `popup_close()`, `msg_box()`, `msg_box_close()`
**UI Menu:** `context_menu()`, `context_menu_close()`
**UI Navigation:** `end_of_list()`, `section_change()`, `switch_category()`, `switch_list()`, `focus_collapsed()`, `focus_expanded()`
**UI Other:** `notify_sound()`, `tip()`, `minimize()`, `restore()`, `connecting()`
**TTS:** `speak(text, position, pitch_offset)`, `notify(text, type, play_sound_effect)`
**Direct:** `play(sound_file, pan)`

Full API docs: `data/titanIM_modules/README.md`

## How modules appear in each interface:

- **GUI** (`src/ui/gui.py`): Listed in network listbox, status shown inline
- **Invisible UI** (`src/ui/invisibleui.py`): Listed in Titan IM category elements
- **Klango Mode** (`src/system/klangomode.py`): Listed in Titan IM submenu

## Reference Examples:

- **ExampleIM** (`data/titanIM_modules/ExampleIM/`): Shows Sound API with demo buttons
  - Disabled by default (`status = 1`)
  - Demonstrates `sounds.welcome()`, `sounds.notify()`, presence sounds, etc.

## Complete Code Examples

### Example 1: Simple Chat Client

A complete IM module that opens a chat window with a contact list, message display, message input, and full Sound API integration.

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
A simple chat client demonstrating contacts, messaging, and the Sound API.
"""

import os
import sys
import threading
import time

# Add TCE root directory to path for proper imports
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# Sound API - automatically injected by the module manager
_module = sys.modules[__name__]

# Connection state for status text
_state = {
    "connected": False,
    "username": "",
    "unread": 0
}


# ---------------------------------------------------------------------------
# Chat window
# ---------------------------------------------------------------------------

class SimpleChatFrame:
    """Main chat window with contact list, message display, and input field."""

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

        # Simulate connection
        self._connect()

    # --- Connection ---

    def _connect(self):
        """Simulate connecting to a chat server."""
        self.sounds.connecting()
        _state["connected"] = True
        _state["username"] = "You"
        self.sounds.notify("Connected as You", 'success')

        # Simulate incoming messages in background
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
    """Return connection status suffix shown after module name in Titan IM list.

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

# Add TCE root directory to path for proper imports
_MODULE_DIR = os.path.dirname(__file__)
_TCE_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, '..', '..', '..'))
if _TCE_ROOT not in sys.path:
    sys.path.insert(0, _TCE_ROOT)

# Sound API - automatically injected by the module manager
_module = sys.modules[__name__]

# State for status text
_state = {
    "unread": 0
}

# Default feed URL (can be changed in the reader window)
DEFAULT_FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"


# ---------------------------------------------------------------------------
# RSS parsing helpers
# ---------------------------------------------------------------------------

def _fetch_feed(url):
    """Fetch and parse an RSS feed. Returns list of dicts with title, link, description."""
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
    """RSS feed reader window with feed list and browser integration."""

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
        self.status_label = wx.StaticText(panel, label="Press Refresh to load feed.")
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

        # Auto-load feed
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
        """Background thread: fetch feed and update UI."""
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
    """Return status suffix shown after module name in Titan IM list.

    Example: "- 5 unread"
    """
    if _state["unread"] > 0:
        return f"- {_state['unread']} unread"
    return ""
```

## Action:

Ask the user for IM module details and create a complete, working module in `data/titanIM_modules/` following the Titan IM module standard with full Sound API integration.
