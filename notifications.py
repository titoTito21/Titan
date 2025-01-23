import platform
import subprocess
import ctypes
from ctypes import wintypes
from datetime import datetime

def get_current_time():
    now = datetime.now()
    return now.strftime("%H:%M:%S")

def get_battery_status():
    if platform.system() == "Windows":
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
    else:
        return "Unknown"

def get_volume_level():
    if platform.system() == "Windows":
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))

        current_volume = volume.GetMasterVolumeLevelScalar() * 100
        return f"{int(current_volume)}%"
    else:
        return "Unknown"

def get_network_status():
    if platform.system() == "Windows":
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
    else:
        return "Unknown"
