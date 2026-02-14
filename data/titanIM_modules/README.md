# Titan IM External Modules

Place communicator module directories here. Each module needs:

```
ModuleName/
├── __im.TCE     - module config (INI format)
└── init.py      - module code
```

## __im.TCE format

```ini
[im_module]
name = Display Name
status = 0
description = Optional description
```

`status = 0` means enabled. Any other value disables the module.

## init.py interface

Required:
```python
def open(parent_frame):
    """Open the communicator window."""
    pass
```

Optional:
```python
def get_status_text():
    """Return status suffix, e.g. '- logged in as user'. Return empty string if none."""
    return ""
```

## Sound API (sounds)

Every module automatically receives a `sounds` object injected by the module manager.
This ensures all external communicators use unified TitanNet/Titan IM sounds,
matching the built-in integrations (Telegram, EltenLink, Titan-Net).

Access it via the module's global `sounds` variable:

```python
# sounds is automatically available as a module-level variable
import sys
_module = sys.modules[__name__]

def open(parent_frame):
    sounds = _module.sounds

    # Play welcome sound when opening
    sounds.welcome()

    # ... create your window ...

    # Play goodbye sound when closing
    sounds.goodbye()
```

### Message sounds

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.new_message()` | titannet/new_message.ogg | New message received |
| `sounds.message_sent()` | titannet/message_send.ogg | Message sent successfully |
| `sounds.chat_message()` | titannet/chat_message.ogg | Chat message event (in active chat) |
| `sounds.typing()` | titannet/typing.ogg | User is typing indicator |

### Chat/Room sounds

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.new_chat()` | titannet/new_chat.ogg | New chat or room opened |
| `sounds.new_replies()` | titannet/newreplies.ogg | New replies available (forum, thread) |

### User presence sounds

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.user_online()` | titannet/online.ogg | User came online |
| `sounds.user_offline()` | titannet/offline.ogg | User went offline |
| `sounds.status_changed()` | titannet/new_status.ogg | User status changed |
| `sounds.account_created()` | titannet/account_created.ogg | New account created |

### Call / Voice sounds

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.call_connected()` | titannet/callsuccess.ogg | Voice call connected |
| `sounds.ring_incoming()` | titannet/ring_in.ogg | Incoming call ringing |
| `sounds.ring_outgoing()` | titannet/ring_out.ogg | Outgoing call ringing |
| `sounds.walkie_talkie_start()` | titannet/walkietalkie.ogg | Push-to-talk activated |
| `sounds.walkie_talkie_end()` | titannet/walkietalkieend.ogg | Push-to-talk deactivated |
| `sounds.recording_start()` | ai/ui1.ogg | Voice recording started |
| `sounds.recording_stop()` | ai/ui2.ogg | Voice recording stopped |

### File sounds

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.file_received()` | titannet/new_file.ogg | New file received |
| `sounds.file_success()` | titannet/file_success.ogg | File operation succeeded |
| `sounds.file_error()` | titannet/file_error.ogg | File operation failed |

### General notification sounds

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.notification()` | titannet/titannet-notification.ogg | General notification |
| `sounds.success()` | titannet/titannet_success.ogg | Success notification |
| `sounds.error()` | core/error.ogg | Error notification |
| `sounds.welcome()` | titannet/welcome to IM.ogg | Module opened |
| `sounds.goodbye()` | titannet/bye.ogg | Module closed / disconnected |
| `sounds.birthday()` | titannet/birthday.ogg | Birthday notification |
| `sounds.new_feed_post()` | titannet/new_feedpost.ogg | New feed post |
| `sounds.announcement()` | titannet/ogloszenie.ogg | Announcement start |
| `sounds.announcement_ended()` | titannet/ogloszenie_ended.ogg | Announcement ended |
| `sounds.announcement_status_changed()` | titannet/ogloszenie_changestatus.ogg | Announcement status changed |
| `sounds.moderation()` | titannet/moderation.ogg | Moderation alert / broadcast |
| `sounds.motd()` | titannet/motd.ogg | Message of the day |
| `sounds.iui()` | titannet/iui.ogg | IUI related notification |
| `sounds.app_update()` | apprepo/appupdate.ogg | App/package update |

### UI sounds - Core

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.focus(pan)` | core/FOCUS.ogg | Focus change (pan: 0.0-1.0) |
| `sounds.select()` | core/SELECT.ogg | Selection / action confirmed |
| `sounds.click()` | core/click.ogg | Simple click |

### UI sounds - Dialogs & Windows

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.dialog_open()` | ui/dialog.ogg | Dialog opened |
| `sounds.dialog_close()` | ui/dialogclose.ogg | Dialog closed |
| `sounds.window_open()` | ui/uiopen.ogg | Window opened |
| `sounds.window_close()` | ui/uiclose.ogg | Window closed |
| `sounds.popup()` | ui/popup.ogg | Popup opened |
| `sounds.popup_close()` | ui/popupclose.ogg | Popup closed |
| `sounds.msg_box()` | ui/msg.ogg | Message box opened |
| `sounds.msg_box_close()` | ui/msgclose.ogg | Message box closed |

### UI sounds - Context Menu

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.context_menu()` | ui/contextmenu.ogg | Context menu opened |
| `sounds.context_menu_close()` | ui/contextmenuclose.ogg | Context menu closed |

### UI sounds - Lists & Navigation

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.end_of_list()` | ui/endoflist.ogg | End of list reached |
| `sounds.section_change()` | ui/sectionchange.ogg | Section/tab changed |
| `sounds.switch_category()` | ui/switch_category.ogg | Category switched |
| `sounds.switch_list()` | ui/switch_list.ogg | List switched |
| `sounds.focus_collapsed()` | ui/focus_collabsed.ogg | Tree node collapsed |
| `sounds.focus_expanded()` | ui/focus_expanded.ogg | Tree node expanded |

### UI sounds - Notifications & Window State

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.notify_sound()` | ui/notify.ogg | Notification sound (no TTS) |
| `sounds.tip()` | ui/tip.ogg | Tooltip / hint |
| `sounds.minimize()` | ui/minimalize.ogg | Window minimized |
| `sounds.restore()` | ui/normalize.ogg | Window restored |

### System sounds

| Method | Sound | When to use |
|--------|-------|-------------|
| `sounds.connecting()` | system/connecting.ogg | Connection in progress |

### TTS (Text-to-Speech) notifications

```python
# Simple TTS with stereo positioning
sounds.speak("Connected!", position=0.0, pitch_offset=0)

# Notification with automatic sound + TTS (respects TCE settings)
# Types: 'error', 'success', 'info', 'warning', 'banned'
sounds.notify("Login successful", 'success')
sounds.notify("Connection failed", 'error')
sounds.notify("New update available", 'info')
sounds.notify("Rate limit exceeded", 'warning')

# Notification with TTS only (no sound effect)
sounds.notify("Reply posted", 'success', play_sound_effect=False)
```

### Direct sound access

```python
# Play any sound file from sfx/ directory
sounds.play('titannet/new_message.ogg')
sounds.play('core/FOCUS.ogg', pan=0.3)  # pan: 0.0 (left) to 1.0 (right)
```

## Example usage in a module

```python
"""My Custom IM module."""
import sys
import wx

_module = sys.modules[__name__]

class MyIMWindow(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent, title="My IM", size=(600, 400))
        self.sounds = _module.sounds

        # Play welcome sound (same as Telegram, EltenLink, Titan-Net)
        self.sounds.welcome()
        self.sounds.notify("Welcome to My IM!", 'success')

        # ... build UI ...

        self.Bind(wx.EVT_CLOSE, self.on_close)

    def on_message_received(self, sender, text):
        self.sounds.new_message()
        self.sounds.speak(f"New message from {sender}")

    def on_message_sent(self):
        self.sounds.message_sent()

    def on_user_online(self, username):
        self.sounds.user_online()

    def on_user_offline(self, username):
        self.sounds.user_offline()

    def on_context_menu(self):
        self.sounds.context_menu()
        # ... show menu ...
        self.sounds.context_menu_close()

    def on_close(self, event):
        self.sounds.goodbye()
        self.Destroy()

def open(parent_frame):
    window = MyIMWindow(parent_frame)
    window.Show()

def get_status_text():
    return ""
```
