import os
import platform
import threading
import time
import accessible_output3.outputs.auto
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
speaker = accessible_output3.outputs.auto.Auto()

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
