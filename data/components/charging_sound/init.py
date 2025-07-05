# -*- coding: utf-8 -*-
import os
import sys
import threading
import time
import platform
import subprocess
import accessible_output3.outputs.auto
from sound import resource_path, play_sound, initialize_sound

speaker = accessible_output3.outputs.auto.Auto()

# Attempt to import psutil
try:
    import psutil
except ImportError:
    psutil = None
    print("psutil not found, battery monitoring will be disabled.")

# Initialize sound
initialize_sound()
pygame = None
# Initialize pygame mixer for interruptible sound on Windows
if platform.system() == 'Windows':
    try:
        import pygame
        pygame.mixer.init()
    except (ImportError, pygame.error) as e:
        print(f"Pygame not found or failed to initialize, sound interruption for volume change will not be available: {e}")
        pygame = None


def initialize(app=None):
    # Start ChargerMonitor only if psutil is available and battery is present
    if psutil and hasattr(psutil, 'sensors_battery') and psutil.sensors_battery() is not None:
        charger_monitor = ChargerMonitor()
        charger_monitor.start()
    else:
        print("psutil not available or no battery found. ChargerMonitor will not start.")

    # These monitors are not yet fully implemented, starting them is currently a no-op.
    # usb_monitor = USBMonitor()
    # usb_monitor.start()

    audio_monitor = AudioMonitor()
    audio_monitor.start()

class ChargerMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True
        self.charged_notification_sent = False
        battery = psutil.sensors_battery()
        if battery:
            self.previous_status = battery.power_plugged
            self.previous_percentage = battery.percent
        else:
            self.previous_status = None
            self.previous_percentage = None

    def run(self):
        while self.running:
            try:
                battery = psutil.sensors_battery()
                if battery:
                    current_status = battery.power_plugged
                    current_percentage = battery.percent

                    if self.previous_status is not None and current_status != self.previous_status:
                        if current_status:
                            self.on_charger_connect(current_percentage)
                        else:
                            self.on_charger_disconnect(current_percentage)
                        self.previous_status = current_status

                    if current_status and current_percentage != self.previous_percentage and current_percentage % 10 == 0:
                        self.on_battery_charging(current_percentage)

                    if current_status and current_percentage == 100 and not self.charged_notification_sent:
                        self.on_battery_charged()
                        self.charged_notification_sent = True
                    elif not current_status:
                        self.charged_notification_sent = False

                    self.previous_percentage = current_percentage
                else:
                    # No battery detected, stop the thread
                    self.running = False
            except Exception as e:
                print(f"Error in ChargerMonitor: {e}")
                self.running = False # Stop thread on error
            time.sleep(1)

    def on_charger_connect(self, percentage):
        play_sound('charger_connect.ogg')
        speaker.speak(f"Podłączono do zasilacza, poziom baterii wynosi {percentage}%")

    def on_charger_disconnect(self, percentage):
        self.charged_notification_sent = False
        play_sound('charger_disconnect.ogg')
        speaker.speak(f"Odłączono zasilacz, poziom baterii wynosi {percentage}%")

    def on_battery_charging(self, percentage):
        speaker.speak(f"Ładowanie baterii, poziom baterii {percentage}%")

    def on_battery_charged(self):
        speaker.speak("Bateria jest naładowana")

    def stop(self):
        self.running = False

class USBMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True

    def run(self):
        # This is a placeholder and does not have a real implementation yet.
        pass

    def stop(self):
        self.running = False

class AudioMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.running = True
        self.previous_volume = self.get_volume_percentage()

    def run(self):
        if platform.system() == 'Windows':
            try:
                import comtypes
                comtypes.CoInitialize()
            except (ImportError, OSError):
                print("Failed to initialize COM library.")
                return # Cannot run without COM

        try:
            while self.running:
                current_volume = self.get_volume_percentage()
                if current_volume != -1 and current_volume != self.previous_volume:
                    play_sound('volume.ogg')
                    speaker.speak(f"Głośność: {current_volume}%", interrupt=True)
                    
                    self.previous_volume = current_volume
                time.sleep(0.05)
        finally:
            if platform.system() == 'Windows' and 'comtypes' in sys.modules:
                sys.modules['comtypes'].CoUninitialize()

    def get_volume_percentage(self):
        try:
            if platform.system() == 'Windows':
                return self.get_volume_windows()
            elif platform.system() == 'Darwin':
                return self.get_volume_mac()
            else:
                return self.get_volume_linux()
        except Exception as e:
            # print(f"Error getting volume: {e}")
            return -1

    def get_volume_windows(self):
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            level = volume.GetMasterVolumeLevelScalar()
            return int(level * 100)
        except (ImportError, OSError, Exception) as e:
            # print(f"Could not get volume on Windows: {e}")
            return -1

    def get_volume_mac(self):
        try:
            result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                    capture_output=True, text=True, check=True)
            return int(result.stdout.strip())
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as e:
            # print(f"Could not get volume on macOS: {e}")
            return -1

    def get_volume_linux(self):
        try:
            import alsaaudio
            mixer = alsaaudio.Mixer()
            return mixer.getvolume()[0]
        except (ImportError, alsaaudio.ALSAAudioError) as e:
            # print(f"Could not get volume on Linux: {e}")
            return -1

    def stop(self):
        self.running = False