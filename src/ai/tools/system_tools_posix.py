"""The computer's own settings on Linux and macOS.

The Windows half (``system_tools.py``) reaches the registry, WMI and the
audio endpoint COM interfaces; none of those exist elsewhere. This is the
same surface - the same function names, the same sentences back - made of
what each desktop really offers on its command line: PulseAudio/PipeWire's
``pactl`` (or ALSA's ``amixer``), ``brightnessctl`` or the backlight class
in sysfs, GNOME's ``gsettings`` and ``powerprofilesctl``, NetworkManager's
``nmcli``, and on macOS ``osascript``, ``networksetup`` and ``open``.

A tool that is not installed answers with a sentence saying which one,
never with an exception: the caller is a model or a macro, and "install
pulseaudio-utils" is something a person can act on.
"""
import os
import plistlib
import shutil
import subprocess
import sys

IS_MACOS = sys.platform == 'darwin'


def _run(command, timeout=20, input_text=None):
    """(returncode, output). Never raises."""
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=timeout,
                                   input=input_text.encode() if input_text else None)
        return completed.returncode, completed.stdout.decode('utf-8', errors='replace')
    except FileNotFoundError:
        return 127, f"{command[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 1, 'the command timed out'
    except Exception as e:
        return 1, str(e)


def _has(tool):
    return shutil.which(tool) is not None


def _percent(value, what):
    try:
        return max(0, min(100, int(float(value)))), ''
    except (TypeError, ValueError):
        return None, f"Give the {what} as a number from 0 to 100."


def _truthy(value):
    return str(value).strip().lower() not in ('0', 'false', 'no', 'off')


# --------------------------------------------------------------------------- #
# Volume and audio devices
# --------------------------------------------------------------------------- #
def _osascript(script):
    return _run(['osascript', '-e', script])


def system_get_volume(**_):
    """The system volume and whether it is muted."""
    if IS_MACOS:
        code, output = _osascript('output volume of (get volume settings)')
        if code:
            return f"Could not read the system volume: {output.strip()}"
        _code, muted = _osascript('output muted of (get volume settings)')
        level = output.strip()
        return (f"System volume is {level}%"
                + (", muted." if muted.strip() == 'true' else "."))
    if _has('pactl'):
        code, output = _run(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'])
        if code:
            return f"Could not read the system volume: {output.strip()}"
        level = _first_percent(output)
        _code, mute = _run(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'])
        muted = 'yes' in mute.lower()
        if level is None:
            return "PulseAudio did not report a volume."
        return f"System volume is {level}%" + (", muted." if muted else ".")
    if _has('amixer'):
        code, output = _run(['amixer', 'sget', 'Master'])
        if code:
            return f"Could not read the system volume: {output.strip()}"
        level = _first_percent(output)
        muted = '[off]' in output
        if level is None:
            return "ALSA did not report a volume."
        return f"System volume is {level}%" + (", muted." if muted else ".")
    return "No volume tool found (install pulseaudio-utils or alsa-utils)."


def _first_percent(text):
    import re
    match = re.search(r'(\d+)%', text)
    return int(match.group(1)) if match else None


def system_set_volume(percent, **_):
    """Set the system volume."""
    value, problem = _percent(percent, 'volume')
    if problem:
        return problem
    if IS_MACOS:
        code, output = _osascript(f'set volume output volume {value}')
    elif _has('pactl'):
        code, output = _run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{value}%'])
    elif _has('amixer'):
        code, output = _run(['amixer', 'sset', 'Master', f'{value}%'])
    else:
        return "No volume tool found (install pulseaudio-utils or alsa-utils)."
    if code:
        return f"Could not set the system volume: {output.strip()}"
    return f"System volume set to {value}%."


def system_set_mute(muted=True, **_):
    """Mute or unmute the system."""
    want = _truthy(muted)
    if IS_MACOS:
        code, output = _osascript(f'set volume output muted {"true" if want else "false"}')
    elif _has('pactl'):
        code, output = _run(['pactl', 'set-sink-mute', '@DEFAULT_SINK@', '1' if want else '0'])
    elif _has('amixer'):
        code, output = _run(['amixer', 'sset', 'Master', 'mute' if want else 'unmute'])
    else:
        return "No volume tool found (install pulseaudio-utils or alsa-utils)."
    if code:
        return f"Could not change mute: {output.strip()}"
    return "Sound muted." if want else "Sound unmuted."


def _pactl_sinks():
    """[(name, description)] and the default sink's name."""
    code, output = _run(['pactl', 'list', 'short', 'sinks'])
    if code:
        return [], None
    sinks = []
    for line in output.splitlines():
        parts = line.split('\t')
        if len(parts) >= 2:
            sinks.append((parts[1], parts[1]))
    _code, default = _run(['pactl', 'get-default-sink'])
    default = default.strip() if not _code else None
    # Descriptions, which are what a person calls the device.
    code, output = _run(['pactl', 'list', 'sinks'])
    if not code:
        name = None
        described = {}
        for line in output.splitlines():
            line = line.strip()
            if line.startswith('Name:'):
                name = line[5:].strip()
            elif line.startswith('Description:') and name:
                described[name] = line[12:].strip()
        sinks = [(n, described.get(n, d)) for n, d in sinks]
    return sinks, default


def system_list_audio_devices(**_):
    """The playback devices and which is in use."""
    if IS_MACOS:
        if _has('SwitchAudioSource'):
            code, output = _run(['SwitchAudioSource', '-a', '-t', 'output'])
            _code, current = _run(['SwitchAudioSource', '-c'])
            if not code:
                names = [n.strip() for n in output.splitlines() if n.strip()]
                current = current.strip()
                return "Playback devices: " + ", ".join(
                    f"{n} (in use)" if n == current else n for n in names)
        return ("The playback devices are chosen in System Settings > Sound "
                "(install switchaudio-osx to change them from here).")
    if not _has('pactl'):
        return "No PulseAudio or PipeWire found (install pulseaudio-utils)."
    sinks, default = _pactl_sinks()
    if not sinks:
        return "No playback device was found."
    return "Playback devices: " + ", ".join(
        f"{desc} (in use)" if name == default else desc for name, desc in sinks)


def system_set_audio_device(name, **_):
    """Send the sound to a different playback device."""
    wanted = str(name or '').strip().lower()
    if not wanted:
        return "Say part of the device's name."
    if IS_MACOS:
        if not _has('SwitchAudioSource'):
            return ("Changing the output device needs switchaudio-osx "
                    "(brew install switchaudio-osx).")
        code, output = _run(['SwitchAudioSource', '-a', '-t', 'output'])
        names = [n.strip() for n in output.splitlines() if n.strip()]
        match = [n for n in names if wanted in n.lower()]
        if not match:
            return f"No playback device matches '{name}'."
        code, output = _run(['SwitchAudioSource', '-t', 'output', '-s', match[0]])
        return f"Sound now goes to {match[0]}." if not code else f"Could not switch: {output.strip()}"
    if not _has('pactl'):
        return "No PulseAudio or PipeWire found (install pulseaudio-utils)."
    sinks, _default = _pactl_sinks()
    match = [(n, d) for n, d in sinks if wanted in d.lower() or wanted in n.lower()]
    if not match:
        return f"No playback device matches '{name}'."
    code, output = _run(['pactl', 'set-default-sink', match[0][0]])
    if code:
        return f"Could not switch: {output.strip()}"
    return f"Sound now goes to {match[0][1]}."


# --------------------------------------------------------------------------- #
# Brightness
# --------------------------------------------------------------------------- #
def _backlight():
    base = '/sys/class/backlight'
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    return os.path.join(base, names[0]) if names else None


def system_get_brightness(**_):
    """How bright the screen is now."""
    if IS_MACOS:
        if _has('brightness'):
            code, output = _run(['brightness', '-l'])
            for line in output.splitlines():
                if 'brightness' in line:
                    try:
                        return f"Screen brightness is {round(float(line.split()[-1]) * 100)}%."
                    except ValueError:
                        pass
        return "The brightness is in System Settings > Displays (install the 'brightness' tool to read it here)."
    if _has('brightnessctl'):
        code, output = _run(['brightnessctl', '-m'])
        if not code and output.strip():
            fields = output.strip().split(',')
            if len(fields) >= 4:
                return f"Screen brightness is {fields[3].strip()}."
    path = _backlight()
    if path is None:
        return "This screen does not support software brightness (that is normal for a desktop monitor)."
    try:
        with open(os.path.join(path, 'brightness')) as f:
            now = int(f.read().strip())
        with open(os.path.join(path, 'max_brightness')) as f:
            top = int(f.read().strip())
        return f"Screen brightness is {round(now * 100 / max(top, 1))}%."
    except OSError as e:
        return f"Could not read the brightness: {e}"


def system_set_brightness(percent, **_):
    """Set the built-in screen's brightness."""
    value, problem = _percent(percent, 'brightness')
    if problem:
        return problem
    if IS_MACOS:
        if not _has('brightness'):
            return "Setting the brightness needs the 'brightness' tool (brew install brightness)."
        code, output = _run(['brightness', str(value / 100.0)])
        return f"Screen brightness set to {value}%." if not code else f"Could not set the brightness: {output.strip()}"
    if _has('brightnessctl'):
        code, output = _run(['brightnessctl', 'set', f'{value}%'])
        if not code:
            return f"Screen brightness set to {value}%."
        return f"Could not set the brightness: {output.strip()}"
    path = _backlight()
    if path is None:
        return "This screen does not support software brightness (that is normal for a desktop monitor)."
    try:
        with open(os.path.join(path, 'max_brightness')) as f:
            top = int(f.read().strip())
        with open(os.path.join(path, 'brightness'), 'w') as f:
            f.write(str(round(top * value / 100)))
    except OSError as e:
        return f"Could not set the brightness ({e}); brightnessctl would do it without root."
    return f"Screen brightness set to {value}%."


# --------------------------------------------------------------------------- #
# Power
# --------------------------------------------------------------------------- #
def system_get_power_plan(**_):
    """Which power profile is active."""
    if IS_MACOS:
        code, output = _run(['pmset', '-g'])
        if code:
            return f"Could not read the power settings: {output.strip()}"
        for line in output.splitlines():
            if 'lowpowermode' in line:
                return "Low power mode is " + ("on." if line.strip().endswith('1') else "off.")
        return "macOS has no power plans; Low Power Mode is in System Settings > Battery."
    if _has('powerprofilesctl'):
        code, output = _run(['powerprofilesctl', 'get'])
        if not code:
            return f"The active power profile is {output.strip()}."
        return f"Could not read the power profile: {output.strip()}"
    return "No power profiles daemon found (install power-profiles-daemon)."


def system_list_power_plans(**_):
    """The power profiles this computer has, the active one marked."""
    if IS_MACOS:
        return "macOS has no power plans; Low Power Mode is the one switch, in System Settings > Battery."
    if not _has('powerprofilesctl'):
        return "No power profiles daemon found (install power-profiles-daemon)."
    code, output = _run(['powerprofilesctl', 'list'])
    if code:
        return f"Could not list the power profiles: {output.strip()}"
    names = []
    for line in output.splitlines():
        line = line.rstrip()
        if line and not line.startswith(' ') and line.endswith(':'):
            names.append(line.replace('*', '').strip(': ').strip()
                         + (' (active)' if line.startswith('*') else ''))
    return "Power profiles: " + ", ".join(names) if names else output.strip()


def system_set_power_plan(name, **_):
    """Switch the power profile."""
    wanted = str(name or '').strip().lower()
    if IS_MACOS:
        if 'low' in wanted or 'saver' in wanted:
            code, output = _run(['pmset', '-a', 'lowpowermode', '1'])
        elif wanted:
            code, output = _run(['pmset', '-a', 'lowpowermode', '0'])
        else:
            return "Say 'low power' or 'normal'."
        return "Done." if not code else f"Could not change it (this needs an administrator): {output.strip()}"
    if not _has('powerprofilesctl'):
        return "No power profiles daemon found (install power-profiles-daemon)."
    aliases = {'balanced': 'balanced', 'power saver': 'power-saver', 'saver': 'power-saver',
               'power-saver': 'power-saver', 'high performance': 'performance',
               'performance': 'performance'}
    profile = aliases.get(wanted)
    if profile is None:
        return "Say 'balanced', 'power saver' or 'performance'."
    code, output = _run(['powerprofilesctl', 'set', profile])
    if code:
        return f"Could not switch the power profile: {output.strip()}"
    return f"Power profile set to {profile}."


# --------------------------------------------------------------------------- #
# Theme
# --------------------------------------------------------------------------- #
def system_set_theme(mode, **_):
    """Switch the desktop between the light and the dark theme."""
    wanted = str(mode or '').strip().lower()
    if wanted not in ('dark', 'light'):
        return "Say 'dark' or 'light'."
    if IS_MACOS:
        code, output = _osascript(
            'tell application "System Events" to tell appearance preferences '
            f'to set dark mode to {"true" if wanted == "dark" else "false"}')
        return f"macOS switched to the {wanted} theme." if not code else f"Could not change the theme: {output.strip()}"
    if not _has('gsettings'):
        return "No gsettings found; the theme is set in the desktop's own settings."
    scheme = 'prefer-dark' if wanted == 'dark' else 'default'
    code, output = _run(['gsettings', 'set', 'org.gnome.desktop.interface', 'color-scheme', scheme])
    if code:
        return f"Could not change the theme: {output.strip()}"
    return f"The desktop switched to the {wanted} theme."


# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
def _airport_device():
    code, output = _run(['networksetup', '-listallhardwareports'])
    device = None
    for line in output.splitlines():
        if 'Wi-Fi' in line or 'AirPort' in line:
            device = 'next'
        elif device == 'next' and line.startswith('Device:'):
            return line.split(':', 1)[1].strip()
    return 'en0'


def system_network_status(**_):
    """Which network the computer is on."""
    if IS_MACOS:
        code, output = _run(['networksetup', '-getairportnetwork', _airport_device()])
        return output.strip() if not code else f"Could not read the network: {output.strip()}"
    if _has('nmcli'):
        code, output = _run(['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL', 'dev', 'wifi'])
        if not code:
            for line in output.splitlines():
                parts = line.split(':')
                if parts and parts[0] == 'yes':
                    return f"Connected to {parts[1] or 'a hidden network'}, signal {parts[2]}%."
        code, output = _run(['nmcli', '-t', '-f', 'NAME,TYPE,DEVICE', 'connection', 'show', '--active'])
        if not code and output.strip():
            names = [l.split(':')[0] for l in output.splitlines() if l.strip()]
            return "Connected: " + ", ".join(names)
        return "Not connected to any network."
    from src.system.notifications import get_network_status
    return get_network_status()


def system_list_wifi(**_):
    """The Wi-Fi networks in range."""
    if IS_MACOS:
        airport = '/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport'
        code, output = _run([airport, '-s'])
        if code:
            return "Scanning needs the Wi-Fi menu on this macOS (the airport tool is gone)."
        names = [l.split()[0] for l in output.splitlines()[1:] if l.strip()]
        return "Networks in range: " + ", ".join(dict.fromkeys(names)) if names else "No networks in range."
    if not _has('nmcli'):
        return "No NetworkManager found (install network-manager)."
    code, output = _run(['nmcli', '-t', '-f', 'SSID,SIGNAL', 'dev', 'wifi', 'list'])
    if code:
        return f"Could not scan: {output.strip()}"
    seen = {}
    for line in output.splitlines():
        ssid, _, signal = line.rpartition(':')
        if ssid and ssid not in seen:
            seen[ssid] = signal
    if not seen:
        return "No networks in range."
    return "Networks in range: " + ", ".join(f"{s} ({v}%)" for s, v in seen.items())


def system_connect_wifi(name, password="", **_):
    """Connect to a Wi-Fi network."""
    ssid = str(name or '').strip()
    if not ssid:
        return "Say the network's name."
    if IS_MACOS:
        command = ['networksetup', '-setairportnetwork', _airport_device(), ssid]
        if password:
            command.append(str(password))
        code, output = _run(command)
        return f"Connected to {ssid}." if not code and 'Error' not in output else f"Could not connect: {output.strip()}"
    if not _has('nmcli'):
        return "No NetworkManager found (install network-manager)."
    command = ['nmcli', 'dev', 'wifi', 'connect', ssid]
    if password:
        command += ['password', str(password)]
    code, output = _run(command, timeout=60)
    if code:
        return f"Could not connect to {ssid}: {output.strip()}"
    return f"Connected to {ssid}."


# --------------------------------------------------------------------------- #
# Autostart
# --------------------------------------------------------------------------- #
def _launch_command():
    from src.platform_utils import is_frozen
    if is_frozen():
        return [sys.executable]
    return [sys.executable, os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else 'main.py')]


def _autostart_path():
    if IS_MACOS:
        return os.path.expanduser('~/Library/LaunchAgents/com.titosoft.titan.plist')
    return os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')),
                        'autostart', 'titan.desktop')


def system_get_autostart(**_):
    """Whether Titan starts with the session."""
    path = _autostart_path()
    if os.path.exists(path):
        return f"Titan starts with the session ({path})."
    return "Titan does not start with the session."


def system_set_autostart(enabled=True, **_):
    """Make Titan start with the session, or stop it doing so."""
    want = _truthy(enabled)
    path = _autostart_path()
    try:
        if not want:
            if os.path.exists(path):
                os.remove(path)
            return "Titan will not start with the session."
        os.makedirs(os.path.dirname(path), exist_ok=True)
        command = _launch_command()
        if IS_MACOS:
            with open(path, 'wb') as f:
                plistlib.dump({'Label': 'com.titosoft.titan', 'ProgramArguments': command,
                               'RunAtLoad': True}, f)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("[Desktop Entry]\nType=Application\nName=Titan\n"
                        f"Exec={' '.join(command)}\nX-GNOME-Autostart-enabled=true\n")
    except OSError as e:
        return f"Could not change the startup entry: {e}"
    return "Titan will start with the session."


# --------------------------------------------------------------------------- #
# The settings application
# --------------------------------------------------------------------------- #
_GNOME_PANELS = {
    'sound': 'sound', 'display': 'display', 'network': 'network', 'wifi': 'wifi',
    'bluetooth': 'bluetooth', 'power': 'power', 'battery': 'power',
    'accessibility': 'universal-access', 'apps': 'applications',
    'startup': 'applications', 'update': 'info-overview', 'privacy': 'privacy',
    'language': 'region', 'time': 'datetime', 'printers': 'printers',
    'mouse': 'mouse', 'keyboard': 'keyboard', 'personalisation': 'background',
    'personalization': 'background', 'defaultapps': 'default-apps',
}
_MAC_PANES = {
    'sound': 'com.apple.Sound-Settings.extension', 'display': 'com.apple.Displays-Settings.extension',
    'network': 'com.apple.Network-Settings.extension', 'wifi': 'com.apple.wifi-settings-extension',
    'bluetooth': 'com.apple.BluetoothSettings', 'power': 'com.apple.Battery-Settings.extension',
    'battery': 'com.apple.Battery-Settings.extension',
    'accessibility': 'com.apple.Accessibility-Settings.extension',
    'apps': 'com.apple.LoginItems-Settings.extension', 'startup': 'com.apple.LoginItems-Settings.extension',
    'update': 'com.apple.Software-Update-Settings.extension',
    'privacy': 'com.apple.settings.PrivacySecurity.extension',
    'language': 'com.apple.Localization-Settings.extension', 'time': 'com.apple.Date-Time-Settings.extension',
    'printers': 'com.apple.Print-Scan-Settings.extension', 'mouse': 'com.apple.Mouse-Settings.extension',
    'keyboard': 'com.apple.Keyboard-Settings.extension',
    'personalisation': 'com.apple.Appearance-Settings.extension',
    'personalization': 'com.apple.Appearance-Settings.extension',
    'defaultapps': 'com.apple.Desktop-Settings.extension',
}


def system_open_settings_page(page, **_):
    """Open a page of the desktop's settings and let the user finish there."""
    key = str(page or '').strip().lower().replace(' ', '')
    if IS_MACOS:
        pane = _MAC_PANES.get(key)
        if pane is None:
            return "Unknown settings page. Known pages: " + ", ".join(sorted(_MAC_PANES))
        code, output = _run(['open', f'x-apple.systempreferences:{pane}'])
        return f"Opened the {key} settings." if not code else f"Could not open System Settings: {output.strip()}"
    panel = _GNOME_PANELS.get(key)
    if panel is None:
        return "Unknown settings page. Known pages: " + ", ".join(sorted(_GNOME_PANELS))
    for command in (['gnome-control-center', panel], ['systemsettings', panel],
                    ['xfce4-settings-manager']):
        if _has(command[0]):
            try:
                subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                return f"Could not open the settings: {e}"
            return f"Opened the {key} settings."
    return "No settings application was found (gnome-control-center or systemsettings)."
