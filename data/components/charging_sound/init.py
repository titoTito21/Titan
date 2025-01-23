# -*- coding: utf-8 -*-
import os
import sys
import threading
import time
import platform
import subprocess
import psutil
from sound import resource_path, play_sound, initialize_sound
from bg5reader import bg5reader

# Initialize sound
initialize_sound()

def initialize(app=None):
    # Start ChargerMonitor only if battery information is available
    if psutil.sensors_battery() is not None:
        charger_monitor = ChargerMonitor()
        charger_monitor.start()
    else:
        print("Battery information not available. ChargerMonitor will not start.")

    usb_monitor = USBMonitor()
    usb_monitor.start()

    audio_monitor = AudioMonitor()
    audio_monitor.start()

class ChargerMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True
        battery = psutil.sensors_battery()
        if battery:
            self.previous_status = battery.power_plugged
            self.previous_percentage = battery.percent
        else:
            self.previous_status = None
            self.previous_percentage = None

    def run(self):
        while self.running:
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

                if not current_status and current_percentage == 100:
                    self.on_battery_charged()

                self.previous_percentage = current_percentage
            else:
                print("Battery information not available.")
                self.running = False  # Stop the thread if battery info is unavailable
            time.sleep(1)

    def on_charger_connect(self, percentage):
        threading.Thread(target=play_sound, args=('charger_connect.ogg',)).start()
        bg5reader.interrupt_and_speak(f"Podłączono do zasilacza, poziom baterii wynosi {percentage}%")

    def on_charger_disconnect(self, percentage):
        threading.Thread(target=play_sound, args=('charger_disconnect.ogg',)).start()
        bg5reader.interrupt_and_speak(f"Odłączono zasilacz, poziom baterii wynosi {percentage}%")

    def on_battery_charging(self, percentage):
        bg5reader.interrupt_and_speak(f"Ładowanie baterii, poziom baterii {percentage}%")

    def on_battery_charged(self):
        bg5reader.interrupt_and_speak("Bateria jest naładowana")

    def stop(self):
        self.running = False

class USBMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        if platform.system() == 'Windows':
            self.monitor_usb_windows()
        elif platform.system() == 'Darwin':
            self.monitor_usb_mac()
        else:
            self.monitor_usb_linux()

    def monitor_usb_windows(self):
        # Placeholder for Windows USB monitoring code
        pass

    def monitor_usb_mac(self):
        # Placeholder for macOS USB monitoring code
        pass

    def monitor_usb_linux(self):
        # Placeholder for Linux USB monitoring code
        pass

    def stop(self):
        self.running = False

class AudioMonitor(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True
        self.previous_volume = self.get_volume_percentage()

    def run(self):
        # Initialize COM library for this thread (Windows only)
        if platform.system() == 'Windows':
            import comtypes
            comtypes.CoInitialize()

        try:
            while self.running:
                current_volume = self.get_volume_percentage()
                if current_volume != self.previous_volume:
                    threading.Thread(target=play_sound, args=('volume.ogg',)).start()
                    bg5reader.interrupt_and_speak(f"Głośność: {current_volume}%")
                    self.previous_volume = current_volume

                time.sleep(1)
        finally:
            # Uninitialize COM library
            if platform.system() == 'Windows':
                comtypes.CoUninitialize()

    def get_volume_percentage(self):
        if platform.system() == 'Windows':
            return self.get_volume_windows()
        elif platform.system() == 'Darwin':
            return self.get_volume_mac()
        else:  # Assume Linux
            return self.get_volume_linux()

    def get_volume_windows(self):
        import comtypes
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        level = volume.GetMasterVolumeLevelScalar()
        return int(level * 100)

    def get_volume_mac(self):
        result = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"],
                                capture_output=True, text=True)
        return int(result.stdout.strip())

    def get_volume_linux(self):
        import alsaaudio
        mixer = alsaaudio.Mixer()
        return mixer.getvolume()[0]

    def stop(self):
        self.running = False

def add_menu(menubar):
    pass  # No menu items needed for this component
