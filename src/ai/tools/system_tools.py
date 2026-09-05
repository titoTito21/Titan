"""The computer's own settings, not Titan's.

"Turn the volume down", "put it on the headphones", "connect to the Wi-Fi",
"switch to dark mode" are all things a user asks their desktop, and a launcher
that *is* the desktop for its users has to be able to do them.

The scope is deliberate: read anything, change the ordinary things. Volume,
audio device, brightness, power plan, Wi-Fi, light/dark theme and whether Titan
starts with Windows are all here. The registry at large, services, policies and
uninstalling software are not - a model misreading a request should not be able
to damage the installation. Anything outside that scope is handled by opening
the right page of Windows Settings and handing over to the user.

Every change is ``confirm``-tier, and everything degrades to a clear sentence
when a library or a device is missing rather than raising.
"""

import os
import subprocess
import sys


def _run(command, timeout=20):
    """Run a system command without flashing a console window."""
    kwargs = {}
    if sys.platform == 'win32':
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = info
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=timeout,
                                   **kwargs)
        # Console tools answer in the OEM code page, not UTF-8. Decoding them
        # as UTF-8 turns every accented character into a replacement character,
        # which then breaks whatever prints the result.
        raw = completed.stdout
        for encoding in ('oem', 'utf-8'):
            try:
                return completed.returncode, raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return completed.returncode, raw.decode('utf-8', errors='replace')
    except subprocess.TimeoutExpired:
        return 1, 'the command timed out'
    except Exception as e:
        return 1, str(e)


# --------------------------------------------------------------------------- #
# Volume and audio devices
# --------------------------------------------------------------------------- #
def _endpoint_volume():
    """The volume control of the default playback device.

    pycaw changed shape: ``GetSpeakers()`` used to hand back a raw IMMDevice to
    Activate an interface on, and now hands back an AudioDevice that exposes
    ``EndpointVolume`` directly. Both are supported so Titan does not care
    which version is installed.
    """
    from pycaw.pycaw import AudioUtilities
    speakers = AudioUtilities.GetSpeakers()
    endpoint = getattr(speakers, 'EndpointVolume', None)
    if endpoint is not None:
        return endpoint
    from ctypes import POINTER, cast
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume
    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def system_get_volume(**_):
    """The system volume and whether it is muted."""
    try:
        volume = _endpoint_volume()
        level = round(volume.GetMasterVolumeLevelScalar() * 100)
        muted = bool(volume.GetMute())
    except Exception as e:
        return f"Could not read the system volume: {e}"
    return (f"System volume is {level}%"
            + (", muted." if muted else "."))


def system_set_volume(percent, **_):
    """Set the system volume."""
    try:
        value = max(0, min(100, int(float(percent))))
    except (TypeError, ValueError):
        return "Give the volume as a number from 0 to 100."
    try:
        _endpoint_volume().SetMasterVolumeLevelScalar(value / 100.0, None)
    except Exception as e:
        return f"Could not set the system volume: {e}"
    return f"System volume set to {value}%."


def system_set_mute(muted=True, **_):
    """Mute or unmute the system."""
    want = str(muted).strip().lower() not in ('0', 'false', 'no', 'off')
    try:
        _endpoint_volume().SetMute(1 if want else 0, None)
    except Exception as e:
        return f"Could not change mute: {e}"
    return "Sound muted." if want else "Sound unmuted."


def _playback_devices():
    """The active *playback* devices only.

    ``GetAllDevices()`` also returns microphones, and offering the user a
    microphone as somewhere to send the sound is worse than useless - so the
    endpoints are enumerated with the render-only flow instead.
    """
    from pycaw.pycaw import AudioUtilities
    from pycaw.constants import DEVICE_STATE, EDataFlow
    enumerator = AudioUtilities.GetDeviceEnumerator()
    collection = enumerator.EnumAudioEndpoints(EDataFlow.eRender.value,
                                               DEVICE_STATE.ACTIVE.value)
    devices = []
    for index in range(collection.GetCount()):
        try:
            devices.append(AudioUtilities.CreateDevice(collection.Item(index)))
        except Exception:
            continue
    return devices


def _active_playback_id():
    from pycaw.pycaw import AudioUtilities
    active = AudioUtilities.GetSpeakers()
    # Old pycaw hands back an IMMDevice (GetId()), new pycaw an AudioDevice.
    return (getattr(active, 'id', None)
            or (active.GetId() if hasattr(active, 'GetId') else ''))


def system_list_audio_devices(**_):
    """List the playback devices and say which one is in use."""
    try:
        devices = _playback_devices()
        active_id = _active_playback_id()
    except Exception as e:
        return f"Could not list the audio devices: {e}"
    lines = ["Playback devices:"]
    for device in devices:
        try:
            mark = " [in use]" if device.id == active_id else ""
            lines.append(f"- {device.FriendlyName}{mark}")
        except Exception:
            continue
    return "\n".join(lines) if len(lines) > 1 else "No active playback devices."


def _policy_config():
    """The undocumented interface Windows itself uses to change the default
    playback device. There is no supported API for this, and every tool that
    does it (including Windows' own Sound page) goes through here."""
    import comtypes
    from ctypes import HRESULT, POINTER, c_int, c_void_p
    from ctypes.wintypes import LPCWSTR
    from comtypes import COMMETHOD, GUID, IUnknown

    class IPolicyConfig(IUnknown):
        _iid_ = GUID('{f8679f50-850a-41cf-9c72-430f290290c8}')
        _methods_ = (
            COMMETHOD([], HRESULT, 'GetMixFormat'),
            COMMETHOD([], HRESULT, 'GetDeviceFormat'),
            COMMETHOD([], HRESULT, 'ResetDeviceFormat'),
            COMMETHOD([], HRESULT, 'SetDeviceFormat'),
            COMMETHOD([], HRESULT, 'GetProcessingPeriod'),
            COMMETHOD([], HRESULT, 'SetProcessingPeriod'),
            COMMETHOD([], HRESULT, 'GetShareMode'),
            COMMETHOD([], HRESULT, 'SetShareMode'),
            COMMETHOD([], HRESULT, 'GetPropertyValue'),
            COMMETHOD([], HRESULT, 'SetPropertyValue'),
            COMMETHOD([], HRESULT, 'SetDefaultEndpoint',
                      (['in'], LPCWSTR, 'device_id'),
                      (['in'], c_int, 'role')),
            COMMETHOD([], HRESULT, 'SetEndpointVisibility'),
        )

    class CPolicyConfigClient(comtypes.CoClass):
        _reg_clsid_ = GUID('{870af99c-171d-4f9e-af0d-e63df40c2bc9}')
        _idlflags_ = []
        _com_interfaces_ = [IPolicyConfig]

    return comtypes.CoCreateInstance(
        CPolicyConfigClient._reg_clsid_, interface=IPolicyConfig)


def system_set_audio_device(name, **_):
    """Send the sound to a different playback device."""
    wanted = str(name or '').strip().lower()
    if not wanted:
        return "Say which device, e.g. 'headphones'."
    try:
        devices = _playback_devices()
    except Exception as e:
        return f"Could not list the audio devices: {e}"
    match = None
    for device in devices:
        try:
            if wanted in str(device.FriendlyName).lower():
                match = device
                break
        except Exception:
            continue
    if match is None:
        return (f"No playback device matches '{name}'. "
                f"Use system_list_audio_devices to see them.")
    try:
        config = _policy_config()
        for role in (0, 1, 2):          # console, multimedia, communications
            config.SetDefaultEndpoint(match.id, role)
    except Exception as e:
        _run(['cmd', '/c', 'start', '', 'ms-settings:sound'])
        return (f"Windows would not let Titan switch the device ({e}). The "
                f"Sound settings page is now open so it can be done there.")
    return f"Sound now goes to {match.FriendlyName}."


# --------------------------------------------------------------------------- #
# Screen, power, appearance
# --------------------------------------------------------------------------- #
def system_set_brightness(percent, **_):
    """Set the built-in screen's brightness (laptops and tablets)."""
    try:
        value = max(0, min(100, int(float(percent))))
    except (TypeError, ValueError):
        return "Give the brightness as a number from 0 to 100."
    try:
        import wmi
        methods = wmi.WMI(namespace='wmi').WmiMonitorBrightnessMethods()
        if not methods:
            return ("This screen does not support software brightness "
                    "(that is normal for a desktop monitor).")
        methods[0].WmiSetBrightness(value, 0)
    except Exception as e:
        return f"Could not set the brightness: {e}"
    return f"Screen brightness set to {value}%."


def system_get_power_plan(**_):
    """Which Windows power plan is active."""
    code, output = _run(['powercfg', '/getactivescheme'])
    if code:
        return f"Could not read the power plan: {output.strip()}"
    return output.strip() or "Windows did not report a power plan."


def system_set_power_plan(name, **_):
    """Switch the Windows power plan."""
    wanted = str(name or '').strip().lower()
    known = {'balanced': '381b4222-f694-41f0-9685-ff5bb260df2e',
             'power saver': 'a1841308-3541-4fab-bc81-f71556f20b4a',
             'saver': 'a1841308-3541-4fab-bc81-f71556f20b4a',
             'high performance': '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c',
             'performance': '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'}
    guid = known.get(wanted)
    if guid is None:
        code, output = _run(['powercfg', '/list'])
        for line in output.splitlines():
            if wanted and wanted in line.lower() and ':' in line:
                parts = line.split(':', 1)[1].strip().split()
                if parts:
                    guid = parts[0]
                    break
    if guid is None:
        return (f"No power plan matches '{name}'. Try 'balanced', "
                f"'power saver' or 'high performance'.")
    code, output = _run(['powercfg', '/setactive', guid])
    if code:
        return f"Could not switch the power plan: {output.strip()}"
    return f"Power plan switched to {name}."


def system_set_theme(mode, **_):
    """Switch Windows between the light and dark theme."""
    wanted = str(mode or '').strip().lower()
    if wanted not in ('dark', 'light'):
        return "Say 'dark' or 'light'."
    value = 0 if wanted == 'dark' else 1
    try:
        import winreg
        path = (r'Software\Microsoft\Windows\CurrentVersion\Themes'
                r'\Personalize')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, 'AppsUseLightTheme', 0, winreg.REG_DWORD,
                              value)
            winreg.SetValueEx(key, 'SystemUsesLightTheme', 0, winreg.REG_DWORD,
                              value)
    except Exception as e:
        return f"Could not change the Windows theme: {e}"
    return f"Windows switched to the {wanted} theme."


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
def system_network_status(**_):
    """Which network the computer is on."""
    code, output = _run(['netsh', 'wlan', 'show', 'interfaces'])
    wifi = ''
    if not code:
        state = ssid = signal = ''
        for line in output.splitlines():
            lowered = line.lower()
            if 'state' in lowered and ':' in line and not state:
                state = line.split(':', 1)[1].strip()
            elif lowered.strip().startswith('ssid') and 'bssid' not in lowered:
                ssid = ssid or line.split(':', 1)[1].strip()
            elif 'signal' in lowered and ':' in line:
                signal = line.split(':', 1)[1].strip()
        if ssid:
            wifi = f"Wi-Fi: connected to {ssid} ({signal} signal)."
        elif state:
            wifi = f"Wi-Fi: {state}."
    try:
        import psutil
        counters = psutil.net_if_stats()
        up = [name for name, stats in counters.items() if stats.isup]
        wired = ", ".join(n for n in up if 'wi-fi' not in n.lower()
                          and 'loopback' not in n.lower())
    except Exception:
        wired = ''
    parts = [p for p in (wifi, f"Interfaces up: {wired}." if wired else '') if p]
    return "\n".join(parts) or "Could not determine the network state."


def system_list_wifi(**_):
    """List the Wi-Fi networks in range."""
    code, output = _run(['netsh', 'wlan', 'show', 'networks', 'mode=bssid'])
    if code:
        return f"Could not scan for Wi-Fi networks: {output.strip()}"
    names = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith('ssid ') and ':' in stripped:
            name = stripped.split(':', 1)[1].strip()
            if name and name not in names:
                names.append(name)
    if not names:
        return "No Wi-Fi networks are in range (or Wi-Fi is switched off)."
    return "Wi-Fi networks in range:\n" + "\n".join(f"- {n}" for n in names)


def system_connect_wifi(name, password="", **_):
    """Connect to a Wi-Fi network.

    A network the computer already knows can be joined by name. A new one needs
    a profile, and building one from a password means writing the password into
    a temporary file - so that path is deliberately not taken here; Windows'
    own connection dialog is opened instead.
    """
    if not str(name).strip():
        return "Say which network to connect to."
    code, output = _run(['netsh', 'wlan', 'connect', f'name={name}'])
    if not code and 'completed successfully' in output.lower():
        return f"Connecting to {name}."
    if password:
        _run(['cmd', '/c', 'start', '', 'ms-availablenetworks:'])
        return (f"'{name}' is not a saved network, so Windows needs to take "
                f"the password itself. The network list is now open - choose "
                f"{name} there and enter the password.")
    return (f"Could not connect to '{name}': {output.strip() or 'unknown error'}. "
            f"If the computer has never joined it, it needs the password "
            f"entered in Windows once.")


# --------------------------------------------------------------------------- #
# Startup and the fallback
# --------------------------------------------------------------------------- #
_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def system_get_autostart(**_):
    """Whether Titan starts with Windows."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            try:
                value, _kind = winreg.QueryValueEx(key, 'Titan')
                return f"Titan starts with Windows ({value})."
            except FileNotFoundError:
                return "Titan does not start with Windows."
    except Exception as e:
        return f"Could not check the startup entry: {e}"


def system_set_autostart(enabled=True, **_):
    """Make Titan start with Windows, or stop it doing so."""
    want = str(enabled).strip().lower() not in ('0', 'false', 'no', 'off')
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if want:
                target = sys.executable
                if not getattr(sys, 'frozen', False):
                    script = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), '..', '..', '..',
                                     'main.py'))
                    target = f'"{sys.executable}" "{script}"'
                else:
                    target = f'"{target}"'
                winreg.SetValueEx(key, 'Titan', 0, winreg.REG_SZ, target)
            else:
                try:
                    winreg.DeleteValue(key, 'Titan')
                except FileNotFoundError:
                    return "Titan already does not start with Windows."
    except Exception as e:
        return f"Could not change the startup entry: {e}"
    return ("Titan will start with Windows." if want
            else "Titan will no longer start with Windows.")


_SETTINGS_PAGES = {
    'sound': 'ms-settings:sound', 'audio': 'ms-settings:sound',
    'display': 'ms-settings:display', 'screen': 'ms-settings:display',
    'network': 'ms-settings:network', 'wifi': 'ms-settings:network-wifi',
    'bluetooth': 'ms-settings:bluetooth',
    'power': 'ms-settings:powersleep', 'battery': 'ms-settings:batterysaver',
    'accessibility': 'ms-settings:easeofaccess',
    'narrator': 'ms-settings:easeofaccess-narrator',
    'apps': 'ms-settings:appsfeatures',
    'startup': 'ms-settings:startupapps',
    'update': 'ms-settings:windowsupdate',
    'privacy': 'ms-settings:privacy',
    'language': 'ms-settings:regionlanguage',
    'time': 'ms-settings:dateandtime', 'date': 'ms-settings:dateandtime',
    'printers': 'ms-settings:printers',
    'mouse': 'ms-settings:mousetouchpad', 'keyboard': 'ms-settings:keyboard',
    'personalisation': 'ms-settings:personalization',
    'personalization': 'ms-settings:personalization',
    'defaultapps': 'ms-settings:defaultapps',
}



def system_get_brightness(**_):
    """How bright the screen is now.

    Setting it was already here; reading it was not, and a panel that lets
    somebody change a value has to be able to say what the value IS.
    """
    try:
        import wmi
        monitors = wmi.WMI(namespace='wmi').WmiMonitorBrightness()
    except Exception as e:
        return f"Could not read the brightness: {e}"
    for monitor in monitors or []:
        try:
            return f"Screen brightness is {int(monitor.CurrentBrightness)}%."
        except Exception:
            continue
    return "This screen does not report its brightness."


def system_list_power_plans(**_):
    """The power plans this computer has, with the active one marked.

    `set_power_plan` already reads `powercfg /list` to find a plan's GUID;
    this is the same listing, answered rather than used and thrown away, so
    a caller can OFFER the plans instead of asking somebody to name one.
    """
    code, output = _run(['powercfg', '/list'])
    if code:
        return f"Could not list the power plans: {output.strip()}"
    active_code, active = _run(['powercfg', '/getactivescheme'])
    active_guid = ''
    if not active_code:
        for part in active.replace(':', ' ').split():
            if part.count('-') == 4:
                active_guid = part.strip()
                break
    plans = []
    for line in output.splitlines():
        if 'GUID' not in line:
            continue
        guid = ''
        for part in line.replace(':', ' ').split():
            if part.count('-') == 4:
                guid = part.strip()
                break
        name = line.split('(')[-1].rsplit(')', 1)[0].strip() if '(' in line else line.strip()
        if not name:
            continue
        plans.append(f"- {name}" + (" [in use]" if guid and guid == active_guid else ""))
    if not plans:
        return "Windows did not report any power plans."
    return "Power plans:\n" + "\n".join(plans)


def system_open_settings_page(page, **_):
    """Open a page of Windows Settings.

    The honest fallback for everything this module deliberately will not change
    itself: the user is put exactly where the setting lives.
    """
    key = str(page or '').strip().lower().replace(' ', '')
    uri = _SETTINGS_PAGES.get(key)
    if uri is None:
        return ("Unknown Windows settings page. Known pages: "
                + ", ".join(sorted(_SETTINGS_PAGES)))
    code, output = _run(['cmd', '/c', 'start', '', uri])
    if code:
        return f"Could not open Windows Settings: {output.strip()}"
    return f"Opened the Windows {key} settings."


def get_system_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    N = {'type': 'number'}
    B = {'type': 'boolean'}
    if sys.platform != 'win32':
        return []
    return [
        _tool('system_get_volume', "Read the computer's volume and mute state.",
              system_get_volume),
        _tool('system_set_volume', "Set the computer's volume.",
              system_set_volume, risk='confirm',
              properties={'percent': dict(N, description="0 to 100.")},
              required=['percent']),
        _tool('system_set_mute', "Mute or unmute the computer.",
              system_set_mute, risk='confirm',
              properties={'muted': dict(B, description="True to mute.")}),
        _tool('system_list_audio_devices',
              "List the computer's playback devices and which is in use.",
              system_list_audio_devices),
        _tool('system_set_audio_device',
              "Send the sound to a different playback device (headphones, "
              "speakers, a monitor).", system_set_audio_device, risk='confirm',
              properties={'name': dict(S, description="Part of the device name.")},
              required=['name']),
        _tool('system_set_brightness',
              "Set the built-in screen's brightness.", system_set_brightness,
              risk='confirm',
              properties={'percent': dict(N, description="0 to 100.")},
              required=['percent']),
        _tool('system_get_power_plan', "Which Windows power plan is active.",
              system_get_power_plan),
        _tool('system_set_power_plan',
              "Switch the Windows power plan (balanced, power saver, high "
              "performance).", system_set_power_plan, risk='confirm',
              properties={'name': dict(S, description="Plan name.")},
              required=['name']),
        _tool('system_set_theme',
              "Switch Windows between the light and the dark theme.",
              system_set_theme, risk='confirm',
              properties={'mode': dict(S, description="'dark' or 'light'.")},
              required=['mode']),
        _tool('system_network_status',
              "Which network the computer is on.", system_network_status),
        _tool('system_list_wifi', "List the Wi-Fi networks in range.",
              system_list_wifi),
        _tool('system_connect_wifi',
              "Connect to a Wi-Fi network the computer already knows.",
              system_connect_wifi, risk='confirm',
              properties={'name': dict(S, description="Network name (SSID)."),
                          'password': dict(S, description="Only if it is a new network.")},
              required=['name']),
        _tool('system_get_autostart', "Whether Titan starts with Windows.",
              system_get_autostart),
        _tool('system_set_autostart',
              "Make Titan start with Windows, or stop it doing so.",
              system_set_autostart, risk='confirm',
              properties={'enabled': dict(B, description="True to start with Windows.")}),
        _tool('system_get_brightness',
              "How bright the screen is now.", system_get_brightness),
        _tool('system_list_power_plans',
              "The power plans this computer has, with the active one "
              "marked.", system_list_power_plans),
        _tool('system_open_settings_page',
              "Open a page of Windows Settings and let the user finish there. "
              "Use this for anything Titan cannot change itself.",
              system_open_settings_page, risk='confirm',
              properties={'page': dict(S, description="sound, display, network, "
                                       "wifi, bluetooth, power, battery, "
                                       "accessibility, apps, startup, update, "
                                       "privacy, language, time, printers, "
                                       "mouse, keyboard, personalisation, "
                                       "defaultapps.")},
              required=['page']),
    ]
