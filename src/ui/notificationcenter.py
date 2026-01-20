import os
import platform
import threading
import time
import wmi
import accessible_output3.outputs.auto
from src.titan_core.sound import play_sound

# Inicjalizacja mówienia
speaker = accessible_output3.outputs.auto.Auto()

def get_notifications_path():
    if platform.system() == 'Windows':
        return os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan', 'bg5notifications.tno')
    elif platform.system() == 'Linux':
        return os.path.expanduser('~/.config/titosoft/Titan/bg5notifications.tno')
    elif platform.system() == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/titosoft/Titan/bg5notifications.tno')
    else:
        raise NotImplementedError('Unsupported platform')

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
    """Wątek monitorujący zmiany w połączeniach sieciowych."""
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
                    adapter = connect_event.TargetInstance
                    # It's not straightforward to get the NetConnectionID from here,
                    # so we'll use a more generic message.
                    show_notification("Windows", "Połączono z siecią")

                disconnect_event = disconnect_watcher(timeout_ms=50)
                if disconnect_event:
                    show_notification("Windows", "Rozłączono z siecią")
                
                time.sleep(0.1) # Small sleep to prevent high CPU usage

            except wmi.x_wmi_timed_out:
                continue
            except Exception as e:
                print(f"Błąd w monitorowaniu sieci: {e}")
                time.sleep(10)
    finally:
        pythoncom.CoUninitialize()

def start_monitoring():
    """Uruchamia monitorowanie zdarzeń systemowych w tle."""
    if platform.system() == 'Windows':
        # Monitorowanie sieci
        network_thread = threading.Thread(target=_monitor_network_events, daemon=True)
        network_thread.start()