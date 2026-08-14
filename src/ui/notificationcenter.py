import os
import platform
import threading
import time
from src.titan_core.sound import play_sound
from src.platform_utils import IS_WINDOWS, IS_LINUX, IS_MACOS, get_user_data_dir

if IS_WINDOWS:
    try:
        import wmi
    except ImportError:
        wmi = None
else:
    wmi = None

# Inicjalizacja mówienia
# The one speaker Titan shares, built the first time something speaks -
# see `src/accessibility/lazy_speaker.py`.
from src.accessibility.lazy_speaker import LazySpeaker
speaker = LazySpeaker()

def get_notifications_path():
    return os.path.join(get_user_data_dir(), 'bg5notifications.tno')

NOTIFICATIONS_FILE_PATH = get_notifications_path()

def create_notifications_file():
    os.makedirs(os.path.dirname(NOTIFICATIONS_FILE_PATH), exist_ok=True)
    with open(NOTIFICATIONS_FILE_PATH, 'w', encoding='utf-8') as file:
        file.write('')

def add_notification(date, time, appname, content):
    with open(NOTIFICATIONS_FILE_PATH, 'a', encoding='utf-8') as file:
        file.write(f'notification\n')
        file.write(f'date={date}\n')
        file.write(f'time={time}\n')
        file.write(f'appname={appname}\n')
        file.write(f'content={content}\n\n')

def show_notification(title, message):
    """Odtwarza dźwięk powiadomienia i odczytuje jego treść."""
    play_sound('ui/notify.ogg')
    speaker.speak(f"{title}, {message}")
    # Feed the Titan Buffer System (Titan category -> Notifications buffer).
    try:
        from src.buffers import buffer_bus
        from src.titan_core.translation import set_language
        from src.settings.settings import get_setting
        _ = set_language(get_setting('language', 'pl'))
        buffer_bus.push('titan', 'notifications', message, author=title,
                        kind='notification', category_name=_("Titan"),
                        buffer_name=_("Notifications"))
    except Exception as e:
        print(f"[Notifications] buffer feed error: {e}")

def _monitor_network_events():
    """Network monitoring using WMI (Windows only)."""
    if not IS_WINDOWS:
        return
    import pythoncom
    pythoncom.CoInitialize()
    try:
        c = wmi.WMI()
        # Watch for network connection events
        connect_watcher = c.watch_for(
            notification_type="Creation",
            wmi_class="__InstanceCreationEvent",
            delay_secs=2,
            within="2",
            where="TargetInstance ISA 'Win32_NetworkAdapterConfiguration' AND IPEnabled=True"
        )
        # Watch for network disconnection events
        disconnect_watcher = c.watch_for(
            notification_type="Deletion",
            wmi_class="__InstanceDeletionEvent",
            delay_secs=2,
            within="2",
            where="TargetInstance ISA 'Win32_NetworkAdapterConfiguration'"
        )

        while True:
            try:
                # Wait for a connection or disconnection event
                connect_event = connect_watcher(timeout_ms=50)
                if connect_event:
                    show_notification("System", "Connected to network")

                disconnect_event = disconnect_watcher(timeout_ms=50)
                if disconnect_event:
                    show_notification("System", "Disconnected from network")

                time.sleep(0.1) # Small sleep to prevent high CPU usage

            except wmi.x_wmi_timed_out:
                continue
            except Exception as e:
                print(f"Error in network monitoring: {e}")
                time.sleep(10)
    finally:
        pythoncom.CoUninitialize()

def _monitor_network_events_crossplatform():
    """Cross-platform network monitoring using psutil polling."""
    try:
        import psutil
    except ImportError:
        print("psutil not available, network monitoring disabled")
        return

    def _get_active_connections():
        """Get set of active network interface addresses."""
        addrs = {}
        try:
            stats = psutil.net_if_stats()
            for iface, stat in stats.items():
                if stat.isup and iface != 'lo':
                    addrs[iface] = stat.isup
        except Exception:
            pass
        return addrs

    last_state = _get_active_connections()

    while True:
        try:
            time.sleep(5)
            current_state = _get_active_connections()

            # Detect new connections
            for iface in current_state:
                if iface not in last_state:
                    show_notification("System", "Connected to network")
                    break

            # Detect disconnections
            for iface in last_state:
                if iface not in current_state:
                    show_notification("System", "Disconnected from network")
                    break

            last_state = current_state
        except Exception as e:
            print(f"Error in network monitoring: {e}")
            time.sleep(10)

def start_monitoring():
    """Uruchamia monitorowanie zdarzeń systemowych w tle."""
    if IS_WINDOWS:
        network_thread = threading.Thread(target=_monitor_network_events, daemon=True)
        network_thread.start()
    else:
        network_thread = threading.Thread(target=_monitor_network_events_crossplatform, daemon=True)
        network_thread.start()


def read_notifications():
    """
    Read the stored notifications, newest first.

    Returns a list of dicts with date, time, appname and content keys.
    """
    if not os.path.exists(NOTIFICATIONS_FILE_PATH):
        return []

    entries = []
    current = None
    try:
        with open(NOTIFICATIONS_FILE_PATH, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.rstrip('\n')
                if line.strip() == 'notification':
                    current = {'date': '', 'time': '', 'appname': '', 'content': ''}
                    entries.append(current)
                elif current is not None and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    if key in current:
                        current[key] = value
    except Exception as e:
        print(f"[NotificationCenter] Error reading notifications: {e}")
        return []

    entries.reverse()
    return entries


def clear_notifications():
    """Remove every stored notification."""
    try:
        create_notifications_file()
        return True
    except Exception as e:
        print(f"[NotificationCenter] Error clearing notifications: {e}")
        return False


def show_notification_center(parent=None):
    """
    Open the notification center - an accessible list of past notifications.

    Reachable from the Titan shell layer (Windows+N) while the system
    interface modification is active.
    """
    import wx
    from src.titan_core.translation import _
    from src.titan_core.skin_manager import apply_skin_to_window

    class NotificationCenterDialog(wx.Dialog):
        def __init__(self, parent):
            super().__init__(
                parent,
                title=_("Notification center"),
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
                size=wx.Size(560, 380),
            )

            panel = wx.Panel(self)
            sizer = wx.BoxSizer(wx.VERTICAL)

            sizer.Add(wx.StaticText(panel, label=_("Notifications:")),
                      0, wx.ALL | wx.EXPAND, 5)

            self.listbox = wx.ListBox(panel)
            sizer.Add(self.listbox, 1, wx.ALL | wx.EXPAND, 5)

            buttons = wx.BoxSizer(wx.HORIZONTAL)
            self.clear_button = wx.Button(panel, label=_("Clear all"))
            self.close_button = wx.Button(panel, wx.ID_CANCEL, label=_("Close"))
            buttons.Add(self.clear_button, 0, wx.ALL, 5)
            buttons.Add(self.close_button, 0, wx.ALL, 5)
            sizer.Add(buttons, 0, wx.ALIGN_RIGHT)

            panel.SetSizer(sizer)

            self.clear_button.Bind(wx.EVT_BUTTON, self._on_clear)
            self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_read)
            self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

            self._reload()
            self.listbox.SetFocus()

            try:
                apply_skin_to_window(self)
            except Exception:
                pass

        def _reload(self):
            self.entries = read_notifications()
            self.listbox.Clear()
            for entry in self.entries:
                self.listbox.Append("{} {} - {}: {}".format(
                    entry['date'], entry['time'],
                    entry['appname'], entry['content']).strip())
            if self.listbox.GetCount():
                self.listbox.SetSelection(0)
                speaker.speak(_("Notification center, {} items").format(
                    self.listbox.GetCount()))
            else:
                speaker.speak(_("Notification center, no notifications"))

        def _on_read(self, event):
            index = self.listbox.GetSelection()
            if index != wx.NOT_FOUND:
                speaker.speak(self.listbox.GetString(index))

        def _on_clear(self, event):
            if clear_notifications():
                self._reload()
            self.listbox.SetFocus()

        def _on_char_hook(self, event):
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                self.EndModal(wx.ID_CANCEL)
            elif event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self._on_read(event)
            else:
                event.Skip()

    dialog = NotificationCenterDialog(parent)
    try:
        # Opened from a global shortcut the dialog has to ask Windows for the
        # foreground explicitly, like the Titan Menu does.
        from src.titan_core.tce_system import force_foreground
        wx.CallAfter(force_foreground, dialog)
    except Exception:
        pass
    dialog.ShowModal()
    dialog.Destroy()
