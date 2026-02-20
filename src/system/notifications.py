import platform
import subprocess
import ctypes
from datetime import datetime
import os
import glob
import re

from src.platform_utils import IS_WINDOWS, IS_LINUX, IS_MACOS

# Windows-specific imports
if IS_WINDOWS:
    from ctypes import wintypes

def get_current_time():
    now = datetime.now()
    return now.strftime("%H:%M:%S")

def get_battery_status():
    if IS_WINDOWS:
        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("Reserved1", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]

        SYSTEM_POWER_STATUS_P = ctypes.POINTER(SYSTEM_POWER_STATUS)
        GetSystemPowerStatus = ctypes.windll.kernel32.GetSystemPowerStatus
        GetSystemPowerStatus.argtypes = [SYSTEM_POWER_STATUS_P]
        GetSystemPowerStatus.restype = wintypes.BOOL

        status = SYSTEM_POWER_STATUS()
        if not GetSystemPowerStatus(ctypes.byref(status)):
            return "Unknown"

        return f"{status.BatteryLifePercent}%"
    elif IS_LINUX:
        try:
            # Try to find battery information in /sys/class/power_supply/
            battery_paths = glob.glob("/sys/class/power_supply/BAT*")
            if not battery_paths:
                return "No battery"
            
            # Use the first battery found
            battery_path = battery_paths[0]
            
            # Read capacity
            capacity_path = os.path.join(battery_path, "capacity")
            if os.path.exists(capacity_path):
                with open(capacity_path, 'r') as f:
                    capacity = int(f.read().strip())
                return f"{capacity}%"
            else:
                return "Unknown"
        except Exception as e:
            print(f"Error getting battery status on Linux: {e}")
            return "Unknown"
    elif IS_MACOS:  # macOS
        try:
            output = subprocess.check_output(["pmset", "-g", "batt"], text=True)
            # Parse battery percentage from pmset output
            match = re.search(r'(\d+)%', output)
            if match:
                return f"{match.group(1)}%"
            else:
                return "Unknown"
        except Exception as e:
            print(f"Error getting battery status on macOS: {e}")
            return "Unknown"
    else:
        return "Unknown"

def get_volume_level():
    if IS_WINDOWS:
        try:
            from pycaw.pycaw import AudioUtilities

            # Use modern pycaw API (20251023+) - EndpointVolume is a direct property
            devices = AudioUtilities.GetSpeakers()
            volume = devices.EndpointVolume

            current_volume = volume.GetMasterVolumeLevelScalar() * 100
            return f"{int(current_volume)}%"
        except Exception as e:
            print(f"Error getting volume level: {e}")
            return "Unknown"
    elif IS_LINUX:
        try:
            # Try PulseAudio first
            try:
                output = subprocess.check_output(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], 
                                                text=True, stderr=subprocess.DEVNULL)
                # Parse volume from pactl output (e.g., "Volume: front-left: 65536 /  100% / 0.00 dB")
                match = re.search(r'(\d+)%', output)
                if match:
                    return f"{match.group(1)}%"
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            # Try ALSA as fallback
            try:
                output = subprocess.check_output(["amixer", "get", "Master"], 
                                                text=True, stderr=subprocess.DEVNULL)
                # Parse volume from amixer output (e.g., "[75%]")
                match = re.search(r'\[(\d+)%\]', output)
                if match:
                    return f"{match.group(1)}%"
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            return "Unknown"
        except Exception as e:
            print(f"Error getting volume level on Linux: {e}")
            return "Unknown"
    elif IS_MACOS:  # macOS
        try:
            output = subprocess.check_output(["osascript", "-e", "output volume of (get volume settings)"], 
                                            text=True)
            volume = int(output.strip())
            return f"{volume}%"
        except Exception as e:
            print(f"Error getting volume level on macOS: {e}")
            return "Unknown"
    else:
        return "Unknown"

def get_network_status():
    if IS_WINDOWS:
        try:
            output = subprocess.check_output("netsh wlan show interfaces", shell=True).decode()
            if "There is no wireless interface" in output:
                return "nie połączono, nie ma dostępnych sieci WiFi"
            elif "State" in output:
                ssid = "Unknown"
                signal = "Unknown"
                lines = output.split("\n")
                for line in lines:
                    if "SSID" in line and "BSSID" not in line:
                        ssid = line.split(":")[1].strip()
                    if "Signal" in line:
                        signal = line.split(":")[1].strip()
                return f"Połączono z {ssid}, moc sygnału: {signal}"
        except subprocess.CalledProcessError:
            return "nie połączono, dostępne sieci WiFi"
    elif IS_LINUX:
        try:
            # Try NetworkManager first (nmcli)
            try:
                output = subprocess.check_output(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"], 
                                                text=True, stderr=subprocess.DEVNULL)
                lines = output.strip().split('\n')
                for line in lines:
                    parts = line.split(':')
                    if len(parts) >= 3 and parts[0] == 'yes':
                        ssid = parts[1] if parts[1] else "Hidden Network"
                        signal = parts[2] if parts[2] else "Unknown"
                        return f"Połączono z {ssid}, moc sygnału: {signal}%"
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            # Try iwconfig as fallback
            try:
                output = subprocess.check_output(["iwconfig"], text=True, stderr=subprocess.DEVNULL)
                lines = output.split('\n')
                for line in lines:
                    if "ESSID:" in line and "Access Point:" in line:
                        # Parse ESSID
                        essid_match = re.search(r'ESSID:"([^"]+)"', line)
                        if essid_match:
                            ssid = essid_match.group(1)
                            # Look for signal strength in next lines
                            signal = "Unknown"
                            return f"Połączono z {ssid}, moc sygnału: {signal}"
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass
            
            # Check if we have any network connection
            try:
                output = subprocess.check_output(["ip", "route", "show", "default"], 
                                                text=True, stderr=subprocess.DEVNULL)
                if output.strip():
                    return "Połączono z siecią (ethernet lub wifi)"
                else:
                    return "Nie połączono z siecią"
            except (subprocess.CalledProcessError, FileNotFoundError):
                return "Unknown"
        except Exception as e:
            print(f"Error getting network status on Linux: {e}")
            return "Unknown"
    elif IS_MACOS:  # macOS
        try:
            # Get current WiFi network
            output = subprocess.check_output(["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"], 
                                            text=True, stderr=subprocess.DEVNULL)
            ssid_match = re.search(r'\s+SSID: (.+)', output)
            if ssid_match:
                ssid = ssid_match.group(1)
                # Try to get signal strength
                signal_match = re.search(r'agrCtlRSSI: (-?\d+)', output)
                signal = signal_match.group(1) + " dBm" if signal_match else "Unknown"
                return f"Połączono z {ssid}, moc sygnału: {signal}"
            else:
                return "Nie połączono z WiFi"
        except Exception as e:
            print(f"Error getting network status on macOS: {e}")
            return "Unknown"
    else:
        return "Unknown"
