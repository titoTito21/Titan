"""
Macro Manager Component for TCE Launcher.
Supports .macro (built-in TCE format), .ahk (AutoHotKey), and .au3 (AutoIt) macros.
"""

import os
import re
import sys
import json
import shutil
import threading
import subprocess
import configparser
import gettext
import time as _time
import tempfile
import zipfile

# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------
KEYBOARD_AVAILABLE = False
try:
    if sys.platform != 'darwin':
        import keyboard
        KEYBOARD_AVAILABLE = True
except ImportError:
    pass

PYNPUT_AVAILABLE = False
try:
    from pynput.keyboard import Key, Controller as PynputController, Listener as PynputListener
    PYNPUT_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
COMPONENT_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_base_path():
    """Resolve the project root directory."""
    if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))


def _get_user_macros_dir():
    """Per-user writable macros dir under %APPDATA%/titosoft/Titan/data/macros/.

    Resolved via src.platform_utils when available, with a fallback that mirrors
    that module's logic so the macros component still works if Titan ever runs
    without it (or before it is importable).
    """
    try:
        from src.platform_utils import get_user_resource_path
        return get_user_resource_path(os.path.join('data', 'macros'))
    except Exception:
        if sys.platform == 'win32':
            base = os.getenv('APPDATA', os.path.expanduser('~'))
        elif sys.platform == 'darwin':
            base = os.path.expanduser('~/Library/Application Support')
        else:
            base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        return os.path.join(base, 'titosoft', 'Titan', 'data', 'macros')


MACROS_DIR = os.path.join(_get_base_path(), 'data', 'macros')      # bundled
USER_MACROS_DIR = _get_user_macros_dir()                            # per-user overlay
os.makedirs(MACROS_DIR, exist_ok=True)
try:
    os.makedirs(USER_MACROS_DIR, exist_ok=True)
except OSError:
    pass

# ---------------------------------------------------------------------------
# Translation setup
# ---------------------------------------------------------------------------
LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')

def _setup_translations():
    try:
        from src.titan_core.translation import language_code
        lang = language_code
    except ImportError:
        lang = 'pl'
    try:
        translation = gettext.translation('macros', LANGUAGES_DIR, languages=[lang], fallback=True)
        return translation.gettext
    except Exception:
        return lambda x: x

_ = _setup_translations()

# ---------------------------------------------------------------------------
# Sound helpers
# ---------------------------------------------------------------------------
def _play_sound(name, force=False):
    try:
        if not force and _get_macro_setting('announce_sound', 'True').lower() not in ['true', '1']:
            return
        from src.titan_core.sound import play_sound
        play_sound(name)
    except Exception:
        pass

def _play_focus():
    try:
        from src.titan_core.sound import play_focus_sound
        play_focus_sound()
    except Exception:
        pass

def _play_select():
    try:
        from src.titan_core.sound import play_select_sound
        play_select_sound()
    except Exception:
        pass

def _play_error():
    try:
        from src.titan_core.sound import play_error_sound
        play_error_sound()
    except Exception:
        pass

def _speak(text, force=False):
    if not force and _get_macro_setting('announce_speech', 'True').lower() not in ['true', '1']:
        return
    try:
        from src.titan_core.tce_speech import speak as tce_speak
        tce_speak(text)
    except Exception:
        try:
            from src.titan_core.sound import speaker
            speaker.speak(text)
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Windows SendInput for exact macro replay
# ---------------------------------------------------------------------------
_SENDINPUT_OK = False

if sys.platform == 'win32':
    try:
        import ctypes
        import ctypes.wintypes as _wt

        class _KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", _wt.WORD), ("wScan", _wt.WORD),
                ("dwFlags", _wt.DWORD), ("time", _wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class _MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", _wt.LONG), ("dy", _wt.LONG),
                ("mouseData", _wt.DWORD), ("dwFlags", _wt.DWORD),
                ("time", _wt.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class _INP_U(ctypes.Union):
            _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

        class _INPUT(ctypes.Structure):
            _fields_ = [("type", _wt.DWORD), ("u", _INP_U)]

        _SendInput = ctypes.windll.user32.SendInput
        _MapVK = ctypes.windll.user32.MapVirtualKeyW
        _INPUT_sz = ctypes.sizeof(_INPUT)
        _SENDINPUT_OK = True
    except Exception:
        pass


def _send_input_win32(vk=0, scan_code=0, is_extended=False, is_press=True):
    """Send a single key event via Windows SendInput API.
    Uses VK code for system shortcuts, falls back to scan code."""
    if not _SENDINPUT_OK:
        return False
    try:
        flags = 0
        w_vk = vk & 0xFFFF if vk else 0
        w_sc = scan_code & 0xFF if scan_code else 0

        if is_extended:
            flags |= 0x0001  # KEYEVENTF_EXTENDEDKEY
        if not w_vk and w_sc:
            flags |= 0x0008  # KEYEVENTF_SCANCODE
        if not is_press:
            flags |= 0x0002  # KEYEVENTF_KEYUP

        inp = _INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.u.ki.wVk = w_vk
        inp.u.ki.wScan = w_sc
        inp.u.ki.dwFlags = flags
        inp.u.ki.time = 0
        inp.u.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        return _SendInput(1, ctypes.byref(inp), _INPUT_sz) == 1
    except Exception:
        return False


def _derive_vk(scan_code, is_extended=False):
    """Derive VK code from scan code using Windows MapVirtualKeyW."""
    if not _SENDINPUT_OK:
        return 0
    try:
        if scan_code < 0:
            return -scan_code
        sc = scan_code
        if sc <= 0xFF and is_extended:
            sc |= 0xE000
        return _MapVK(sc, 3)  # MAPVK_VSC_TO_VK_EX
    except Exception:
        return 0


# Names of keys that are always extended (E0 prefix) on Windows
_ALWAYS_EXTENDED_NAMES = frozenset({
    'left windows', 'right windows',
    'right ctrl', 'right alt',
    'apps', 'print screen',
})
# Navigation/arrow keys are extended when NOT from numpad
_NAV_KEY_NAMES = frozenset({
    'up', 'down', 'left', 'right',
    'home', 'end', 'page up', 'page down',
    'insert', 'delete',
})


def _infer_extended(event):
    """Infer whether a key is extended from keyboard library event.
    The library captures is_extended from Windows hook but does NOT store it
    on the KeyboardEvent. We reconstruct it from name + is_keypad."""
    name = (event.name or '').lower()
    is_keypad = getattr(event, 'is_keypad', False)

    # Numpad keys are never extended
    if is_keypad:
        return False

    if name in _ALWAYS_EXTENDED_NAMES:
        return True

    # Arrow/navigation keys are extended when not from numpad
    if name in _NAV_KEY_NAMES:
        return True

    return False


# ---------------------------------------------------------------------------
# Interpreter constants
# ---------------------------------------------------------------------------
# AutoHotKey executables (v1: AutoHotkey.exe, v2: AutoHotkey64.exe / AutoHotkey32.exe)
AHK_EXECUTABLES = [
    'AutoHotkey.exe', 'AutoHotkey64.exe', 'AutoHotkey32.exe',
    'AutoHotkeyU64.exe', 'AutoHotkeyU32.exe', 'AutoHotkeyA32.exe',
    'v2/AutoHotkey64.exe', 'v2/AutoHotkey32.exe', 'v2/AutoHotkey.exe',
]
# AutoIt executables
AU3_EXECUTABLES = [
    'AutoIt3.exe', 'AutoIt3_x64.exe',
]

AHK_LICENSE_URL = 'https://raw.githubusercontent.com/AutoHotkey/AutoHotkey/master/license.txt'
AU3_LICENSE_URL = 'https://www.autoitscript.com/autoit3/docs/license.htm'

AHK_INSTALLER_URL = 'https://www.autohotkey.com/download/ahk-install.exe'
AU3_INSTALLER_URL = 'https://www.autoitscript.com/files/autoit3/autoit-v3-setup.exe'

# Common install paths to check as fallback
_AHK_COMMON_PATHS = [
    os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'AutoHotkey'),
    os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'AutoHotkey'),
    os.path.join(os.environ.get('ProgramW6432', r'C:\Program Files'), 'AutoHotkey'),
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'AutoHotkey'),
]
_AU3_COMMON_PATHS = [
    os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'AutoIt3'),
    os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'AutoIt3'),
    os.path.join(os.environ.get('ProgramW6432', r'C:\Program Files'), 'AutoIt3'),
]


def _find_autohotkey():
    """Find AutoHotKey interpreter. Returns path or None."""
    # 1. Check PATH for all known executable names
    for exe in AHK_EXECUTABLES:
        base = os.path.basename(exe)
        found = shutil.which(base)
        if found:
            return found

    if sys.platform != 'win32':
        return None

    try:
        import winreg
    except ImportError:
        return None

    # 2. Check Windows registry
    reg_keys = [
        r'SOFTWARE\AutoHotkey',
        r'SOFTWARE\WOW6432Node\AutoHotkey',
    ]
    for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        for key_path in reg_keys:
            try:
                with winreg.OpenKey(hive, key_path) as k:
                    install_dir, _ = winreg.QueryValueEx(k, 'InstallDir')
                    if install_dir:
                        for exe in AHK_EXECUTABLES:
                            candidate = os.path.join(install_dir, exe)
                            if os.path.isfile(candidate):
                                return candidate
            except Exception:
                pass

    # 3. Check .ahk file association in registry
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'AutoHotkeyScript\Shell\Open\Command') as k:
            cmd, _ = winreg.QueryValueEx(k, '')
            if cmd:
                # Command is like: "C:\...\AutoHotkey.exe" "%1"
                path = cmd.split('"')[1] if '"' in cmd else cmd.split()[0]
                if os.path.isfile(path):
                    return path
    except Exception:
        pass

    # 4. Check common install directories
    for base_dir in _AHK_COMMON_PATHS:
        if os.path.isdir(base_dir):
            for exe in AHK_EXECUTABLES:
                candidate = os.path.join(base_dir, exe)
                if os.path.isfile(candidate):
                    return candidate

    return None


def _find_autoit():
    """Find AutoIt interpreter. Returns path or None."""
    # 1. Check PATH
    for exe in AU3_EXECUTABLES:
        found = shutil.which(exe)
        if found:
            return found

    if sys.platform != 'win32':
        return None

    try:
        import winreg
    except ImportError:
        return None

    # 2. Check Windows registry
    reg_keys = [
        r'SOFTWARE\AutoIt v3\AutoIt',
        r'SOFTWARE\WOW6432Node\AutoIt v3\AutoIt',
    ]
    for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
        for key_path in reg_keys:
            try:
                with winreg.OpenKey(hive, key_path) as k:
                    install_dir, _ = winreg.QueryValueEx(k, 'InstallDir')
                    if install_dir:
                        for exe in AU3_EXECUTABLES:
                            candidate = os.path.join(install_dir, exe)
                            if os.path.isfile(candidate):
                                return candidate
            except Exception:
                pass

    # 3. Check .au3 file association in registry
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'AutoIt3Script\Shell\Run\Command') as k:
            cmd, _ = winreg.QueryValueEx(k, '')
            if cmd:
                path = cmd.split('"')[1] if '"' in cmd else cmd.split()[0]
                if os.path.isfile(path):
                    return path
    except Exception:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'AutoIt3ScriptFile\Shell\Run\Command') as k:
            cmd, _ = winreg.QueryValueEx(k, '')
            if cmd:
                path = cmd.split('"')[1] if '"' in cmd else cmd.split()[0]
                if os.path.isfile(path):
                    return path
    except Exception:
        pass

    # 4. Check common install directories
    for base_dir in _AU3_COMMON_PATHS:
        if os.path.isdir(base_dir):
            for exe in AU3_EXECUTABLES:
                candidate = os.path.join(base_dir, exe)
                if os.path.isfile(candidate):
                    return candidate

    return None


# ============================================================================
# MacroManager - Core data layer
# ============================================================================
class MacroManager:
    """Handles loading, saving, running, creating, importing, and deleting macros.

    Macros are loaded from BOTH the bundled `data/macros/` directory and the
    per-user overlay under `%APPDATA%/titosoft/Titan/data/macros/`. User-overlay
    macros override bundled macros with the same folder name.

    All writes (new macros, imports, hotkey changes, deletions) target the
    user-overlay dir. Editing a bundled macro transparently shadow-copies its
    folder to the user dir before persisting changes, so the installation
    directory stays untouched.
    """

    def __init__(self, macros_dir, user_macros_dir=None):
        self.macros_dir = macros_dir
        self.user_macros_dir = user_macros_dir or USER_MACROS_DIR
        try:
            os.makedirs(self.user_macros_dir, exist_ok=True)
        except OSError:
            pass
        self.macros = []
        # Map folder_name -> source root the macro was loaded from. Used to
        # decide whether a write needs to shadow-copy the folder to the user
        # dir first.
        self._macro_roots = {}
        self.load_macros()

    def _iter_macro_roots(self):
        """Yield (root_dir, is_user) tuples in priority order (user wins).
        Bundled root is yielded first so the user dict overwrites it."""
        if self.macros_dir and os.path.isdir(self.macros_dir):
            yield self.macros_dir, False
        if (self.user_macros_dir and os.path.isdir(self.user_macros_dir)
                and os.path.abspath(self.user_macros_dir) != os.path.abspath(self.macros_dir or '')):
            yield self.user_macros_dir, True

    def _ensure_user_copy(self, folder_name):
        """Return the writable user-dir path for a macro, copying it from the
        bundled root on first write if needed."""
        try:
            os.makedirs(self.user_macros_dir, exist_ok=True)
        except OSError:
            pass
        user_path = os.path.join(self.user_macros_dir, folder_name)
        if not os.path.isdir(user_path):
            bundled_path = os.path.join(self.macros_dir, folder_name) if self.macros_dir else ''
            if bundled_path and os.path.isdir(bundled_path):
                try:
                    shutil.copytree(bundled_path, user_path)
                except Exception as e:
                    print(f"[macros] Could not shadow-copy '{folder_name}' to user dir: {e}")
                    return bundled_path
        self._macro_roots[folder_name] = self.user_macros_dir
        return user_path

    def load_macros(self):
        """Scan data/macros/ (bundled + user overlay) and parse each
        __macro__.TCE. User-overlay macros win on folder-name collision."""
        self.macros = []
        self._macro_roots = {}

        try:
            from src.titan_core.translation import language_code
            lang = language_code
        except Exception:
            lang = 'pl'

        # Build name->(folder_path, root_dir) so the user dir overwrites
        # bundled entries with the same folder name.
        collected = {}
        for root, _is_user in self._iter_macro_roots():
            try:
                for folder_name in sorted(os.listdir(root)):
                    folder_path = os.path.join(root, folder_name)
                    if not os.path.isdir(folder_path):
                        continue
                    config_path = os.path.join(folder_path, '__macro__.TCE')
                    if not os.path.exists(config_path):
                        continue
                    collected[folder_name] = (folder_path, root)
            except OSError:
                continue

        for folder_name in sorted(collected.keys()):
            folder_path, root = collected[folder_name]
            config_path = os.path.join(folder_path, '__macro__.TCE')
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')

            name = config.get('macro', 'name_{}'.format(lang),
                              fallback=config.get('macro', 'name_en', fallback=folder_name))
            openfile = config.get('macro', 'openfile', fallback='')
            hotkey = config.get('macrocfg', 'hotkey', fallback='')

            ext = os.path.splitext(openfile)[1].lower() if openfile else ''
            self._macro_roots[folder_name] = root
            self.macros.append({
                'name': name,
                'folder_path': folder_path,
                'folder_name': folder_name,
                'openfile': openfile,
                'script_path': os.path.join(folder_path, openfile) if openfile else '',
                'hotkey': hotkey,
                'type': ext,
            })

    def get_macro_names(self):
        return [m['name'] for m in self.macros]

    def get_macro(self, index):
        if 0 <= index < len(self.macros):
            return self.macros[index]
        return None

    def find_by_name(self, name):
        for m in self.macros:
            if m['name'] == name:
                return m
        return None

    def set_hotkey(self, folder_name, hotkey_str):
        """Persist hotkey change to __macro__.TCE. If the macro lives in the
        bundled dir it is shadow-copied to the user dir before the write."""
        folder_path = self._ensure_user_copy(folder_name)
        config_path = os.path.join(folder_path, '__macro__.TCE')
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        if 'macrocfg' not in config:
            config['macrocfg'] = {}
        config['macrocfg']['hotkey'] = hotkey_str
        with open(config_path, 'w', encoding='utf-8') as f:
            config.write(f)
        self.load_macros()

    def create_macro_folder(self, folder_name, name_en, name_pl, openfile, hotkey=''):
        """Create folder + __macro__.TCE for a new macro in the user dir."""
        try:
            os.makedirs(self.user_macros_dir, exist_ok=True)
        except OSError:
            pass
        folder_path = os.path.join(self.user_macros_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        config = configparser.ConfigParser()
        config['macro'] = {
            'name_pl': name_pl,
            'name_en': name_en,
            'openfile': openfile,
        }
        config['macrocfg'] = {'hotkey': hotkey}
        with open(os.path.join(folder_path, '__macro__.TCE'), 'w', encoding='utf-8') as f:
            config.write(f)
        self.load_macros()
        return folder_path

    def import_macro_from_zip(self, zip_path, name_en, name_pl, openfile):
        """Import from ZIP, extract to the user macros dir, create config."""
        try:
            os.makedirs(self.user_macros_dir, exist_ok=True)
        except OSError:
            pass
        folder_name = name_en.lower().replace(' ', '_')
        folder_path = os.path.join(self.user_macros_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(folder_path)
        # Create/overwrite config
        config = configparser.ConfigParser()
        config['macro'] = {
            'name_pl': name_pl,
            'name_en': name_en,
            'openfile': openfile,
        }
        config['macrocfg'] = {'hotkey': ''}
        with open(os.path.join(folder_path, '__macro__.TCE'), 'w', encoding='utf-8') as f:
            config.write(f)
        self.load_macros()
        return folder_path

    def import_macro_from_folder(self, src_folder, name_en, name_pl, openfile):
        """Import from a folder, copy to the user macros dir, create config."""
        try:
            os.makedirs(self.user_macros_dir, exist_ok=True)
        except OSError:
            pass
        folder_name = name_en.lower().replace(' ', '_')
        folder_path = os.path.join(self.user_macros_dir, folder_name)
        if os.path.abspath(src_folder) != os.path.abspath(folder_path):
            shutil.copytree(src_folder, folder_path, dirs_exist_ok=True)
        config = configparser.ConfigParser()
        config['macro'] = {
            'name_pl': name_pl,
            'name_en': name_en,
            'openfile': openfile,
        }
        config['macrocfg'] = {'hotkey': ''}
        with open(os.path.join(folder_path, '__macro__.TCE'), 'w', encoding='utf-8') as f:
            config.write(f)
        self.load_macros()
        return folder_path

    def delete_macro(self, folder_name):
        """Delete a macro folder entirely.

        Bundled macros cannot be deleted (the installation dir is treated as
        read-only); the user copy, if any, is removed and the bundled version
        will reappear on next scan.
        """
        user_path = os.path.join(self.user_macros_dir, folder_name)
        if os.path.exists(user_path):
            shutil.rmtree(user_path, ignore_errors=True)
        else:
            # Legacy code path: dev mode, no user shadow yet.
            bundled_path = os.path.join(self.macros_dir, folder_name) if self.macros_dir else ''
            if bundled_path and os.path.exists(bundled_path):
                shutil.rmtree(bundled_path, ignore_errors=True)
        self.load_macros()


# ============================================================================
# .macro runner
# ============================================================================
def run_tce_macro(script_path):
    """Execute a .macro JSON file by simulating key events.
    Uses scan codes for exact hardware-level replay when available,
    falls back to key names."""
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print("[MacroManager] Error reading .macro file: {}".format(e))
        _speak(_("Error running macro: {}").format(str(e)))
        return

    actions = data.get('actions', [])
    if not actions:
        _speak(_("Macro is empty"))
        return

    def _run():
        _play_sound('macro/macro_start.ogg')
        last_time = 0
        pynput_ctrl = PynputController() if PYNPUT_AVAILABLE else None

        for action in actions:
            action_time = action.get('time_ms', 0)
            delay = (action_time - last_time) / 1000.0
            if delay > 0:
                _time.sleep(delay)
            last_time = action_time

            atype = action.get('type', '')
            key = action.get('key', '')
            scan_code = action.get('scan_code', None)
            vk = action.get('vk', None)

            if atype == 'delay':
                continue

            sent = False

            # On Windows, use SendInput with VK codes for exact replay
            if sys.platform == 'win32':
                is_ext = action.get('is_extended', False)
                a_vk = action.get('vk', 0)
                sc = scan_code or 0

                if not a_vk:
                    if sc > 0:
                        if sc > 0xFF:
                            is_ext = True
                        a_vk = _derive_vk(sc, is_ext)
                    elif sc < 0:
                        a_vk = -sc

                a_sc = (sc & 0xFF) if sc > 0 else 0

                if a_vk or a_sc:
                    sent = _send_input_win32(
                        vk=a_vk, scan_code=a_sc,
                        is_extended=is_ext,
                        is_press=(atype == 'key_press'))

            if not sent and KEYBOARD_AVAILABLE and sys.platform != 'darwin':
                try:
                    if scan_code is not None:
                        if atype == 'key_press':
                            keyboard.press(scan_code)
                        elif atype == 'key_release':
                            keyboard.release(scan_code)
                    else:
                        if atype == 'key_press':
                            keyboard.press(key)
                        elif atype == 'key_release':
                            keyboard.release(key)
                except Exception as e:
                    print("[MacroManager] keyboard error for key '{}': {}".format(
                        key, e))
            elif not sent and pynput_ctrl:
                try:
                    pynput_key = _pynput_key_from_str(key, vk)
                    if atype == 'key_press':
                        pynput_ctrl.press(pynput_key)
                    elif atype == 'key_release':
                        pynput_ctrl.release(pynput_key)
                except Exception as e:
                    print("[MacroManager] pynput error for key '{}': {}".format(
                        key, e))

        _play_sound('macro/macro_end.ogg')

    threading.Thread(target=_run, daemon=True).start()


def _pynput_key_from_str(key_str, vk=None):
    """Convert a string key name to pynput Key enum or character.
    If vk code is provided, use it for exact key matching."""
    # If we have a vk code, use KeyCode.from_vk for exact match
    if vk is not None and PYNPUT_AVAILABLE:
        try:
            from pynput.keyboard import KeyCode
            return KeyCode.from_vk(vk)
        except Exception:
            pass

    key_map = {
        'ctrl': Key.ctrl, 'ctrl_l': Key.ctrl_l, 'ctrl_r': Key.ctrl_r,
        'alt': Key.alt, 'alt_l': Key.alt_l, 'alt_r': Key.alt_r,
        'alt_gr': Key.alt_gr,
        'shift': Key.shift, 'shift_l': Key.shift_l, 'shift_r': Key.shift_r,
        'enter': Key.enter, 'return': Key.enter,
        'tab': Key.tab, 'space': Key.space,
        'backspace': Key.backspace, 'delete': Key.delete,
        'escape': Key.esc, 'esc': Key.esc,
        'up': Key.up, 'down': Key.down, 'left': Key.left, 'right': Key.right,
        'home': Key.home, 'end': Key.end,
        'page_up': Key.page_up, 'page_down': Key.page_down,
        'insert': Key.insert,
        'print_screen': Key.print_screen, 'scroll_lock': Key.scroll_lock,
        'pause': Key.pause,
        'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
        'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
        'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
        'f13': Key.f13, 'f14': Key.f14, 'f15': Key.f15, 'f16': Key.f16,
        'f17': Key.f17, 'f18': Key.f18, 'f19': Key.f19, 'f20': Key.f20,
        'caps_lock': Key.caps_lock, 'num_lock': Key.num_lock,
        'cmd': Key.cmd, 'cmd_l': Key.cmd_l, 'cmd_r': Key.cmd_r,
        'menu': Key.menu,
        'media_play_pause': Key.media_play_pause,
        'media_volume_mute': Key.media_volume_mute,
        'media_volume_down': Key.media_volume_down,
        'media_volume_up': Key.media_volume_up,
        'media_next': Key.media_next, 'media_previous': Key.media_previous,
    }
    lower = key_str.lower()
    if lower in key_map:
        return key_map[lower]
    # Handle vk_NNN format from recorder
    if lower.startswith('vk_') and PYNPUT_AVAILABLE:
        try:
            from pynput.keyboard import KeyCode
            return KeyCode.from_vk(int(lower[3:]))
        except Exception:
            pass
    if len(key_str) == 1:
        return key_str
    return key_str


# ============================================================================
# Macro execution dispatcher
# ============================================================================
def run_macro(macro_info, parent_frame=None):
    """Dispatch macro by type. Show install dialog if interpreter missing."""
    ext = macro_info.get('type', '')
    script_path = macro_info.get('script_path', '')

    if not script_path or not os.path.exists(script_path):
        _speak(_("Macro file not found"))
        _play_error()
        return

    if ext == '.macro':
        run_tce_macro(script_path)
        return

    if ext == TCS_EXT:
        run_tcs(script_path)
        return

    if ext == '.exe':
        _play_select()
        try:
            if sys.platform == 'win32':
                subprocess.Popen([script_path])
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', script_path])
            else:
                subprocess.Popen(['xdg-open', script_path])
        except Exception as e:
            _speak(_("Error running macro: {}").format(str(e)))
            _play_error()
        return

    if ext == '.ahk':
        interp = _find_autohotkey()
        if not interp:
            if sys.platform != 'win32':
                _speak(_("AutoHotKey is only available on Windows"))
                _play_error()
                return
            try:
                import wx
                wx.CallAfter(_show_interpreter_install_dialog, parent_frame,
                             "AutoHotKey", AHK_LICENSE_URL, AHK_INSTALLER_URL,
                             macro_info)
            except Exception:
                _speak(_("This macro requires AutoHotKey interpreter"))
            return
        _play_select()
        subprocess.Popen([interp, script_path])
        return

    if ext == '.au3':
        interp = _find_autoit()
        if not interp:
            if sys.platform != 'win32':
                _speak(_("AutoIt is only available on Windows"))
                _play_error()
                return
            try:
                import wx
                wx.CallAfter(_show_interpreter_install_dialog, parent_frame,
                             "AutoIt", AU3_LICENSE_URL, AU3_INSTALLER_URL,
                             macro_info)
            except Exception:
                _speak(_("This macro requires AutoIt interpreter"))
            return
        _play_select()
        subprocess.Popen([interp, script_path])
        return


# ============================================================================
# Open in TEdit
# ============================================================================
def _open_in_tedit(file_path):
    """Open a file in the TEdit application."""
    try:
        from src.titan_core.app_manager import find_application_by_shortname, open_application
        app_info = find_application_by_shortname('tedit')
        if app_info:
            open_application(app_info, file_path)
        else:
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', file_path])
            else:
                subprocess.Popen(['xdg-open', file_path])
    except Exception as e:
        print("[MacroManager] Error opening in TEdit: {}".format(e))


# ============================================================================
# wxPython GUI classes (lazy import wx)
# ============================================================================
_gui_app_ref = None
_macro_manager = None
_macro_listbox = None
_macro_hotkey_manager = None


def _get_wx():
    import wx
    return wx


# ============================================================================
# InterpreterInstallDialog
# ============================================================================
def _show_interpreter_install_dialog(parent, name, license_url, installer_url,
                                     macro_info):
    wx = _get_wx()
    from src.titan_core.sound import play_dialog_sound, play_dialogclose_sound

    play_dialog_sound()

    dlg = InterpreterInstallDialog(parent, name, license_url, installer_url,
                                   lambda: run_macro(macro_info, parent))
    dlg.ShowModal()
    play_dialogclose_sound()
    dlg.Destroy()


class InterpreterInstallDialog:
    """Dialog shown when AHK/AutoIt interpreter is missing."""

    def __new__(cls, parent, interpreter_name, license_url, installer_url,
                on_installed_callback):
        wx = _get_wx()

        class _Dialog(wx.Dialog):
            def __init__(self, parent, interpreter_name, license_url,
                         installer_url, on_installed_callback):
                super().__init__(parent,
                                 title=_("Install {}").format(interpreter_name),
                                 style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
                self.installer_url = installer_url
                self.on_installed_callback = on_installed_callback
                self._init_ui(interpreter_name)
                self._bind_events()
                threading.Thread(target=self._fetch_license,
                                 args=(license_url,), daemon=True).start()

            def _init_ui(self, interpreter_name):
                sizer = wx.BoxSizer(wx.VERTICAL)

                msg = _("This macro requires {} interpreter").format(interpreter_name)
                question = _("Do you want to download and install {}?").format(interpreter_name)
                sizer.Add(wx.StaticText(self, label=msg), 0, wx.ALL, 10)
                sizer.Add(wx.StaticText(self, label=question), 0, wx.LEFT | wx.RIGHT, 10)

                sizer.Add(wx.StaticText(self, label=_("License:")), 0,
                          wx.LEFT | wx.RIGHT | wx.TOP, 10)
                self.license_ctrl = wx.TextCtrl(self,
                                                style=wx.TE_MULTILINE | wx.TE_READONLY)
                self.license_ctrl.SetMinSize((500, 200))
                self.license_ctrl.SetValue(_("Loading license..."))
                sizer.Add(self.license_ctrl, 1, wx.ALL | wx.EXPAND, 10)

                btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
                self.yes_btn = wx.Button(self, wx.ID_OK, _("Install"))
                self.no_btn = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
                btn_sizer.Add(self.yes_btn, 0, wx.RIGHT, 5)
                btn_sizer.Add(self.no_btn)
                sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_CENTER, 10)

                self.SetSizer(sizer)
                self.Fit()
                self.CenterOnParent()

            def _bind_events(self):
                self.yes_btn.Bind(wx.EVT_SET_FOCUS,
                                  lambda e: (_play_focus(), e.Skip()))
                self.no_btn.Bind(wx.EVT_SET_FOCUS,
                                 lambda e: (_play_focus(), e.Skip()))
                self.license_ctrl.Bind(wx.EVT_SET_FOCUS,
                                       lambda e: (_play_focus(), e.Skip()))
                self.yes_btn.Bind(wx.EVT_BUTTON, self._on_install)
                self.no_btn.Bind(wx.EVT_BUTTON,
                                 lambda e: self.EndModal(wx.ID_CANCEL))

            def _fetch_license(self, url):
                try:
                    import requests
                    r = requests.get(url, timeout=15)
                    text = r.text
                    # Strip HTML tags if present (for AutoIt license page)
                    if '<html' in text.lower():
                        import re
                        text = re.sub(r'<[^>]+>', '', text)
                        text = text.strip()
                except Exception as e:
                    text = _("Could not fetch license: {}").format(str(e))
                wx.CallAfter(self.license_ctrl.SetValue, text)

            def _on_install(self, event):
                self.yes_btn.Disable()
                self.no_btn.Disable()
                threading.Thread(target=self._download_and_install,
                                 daemon=True).start()

            def _download_and_install(self):
                try:
                    import requests
                    wx.CallAfter(self.yes_btn.SetLabel, _("Downloading..."))
                    r = requests.get(self.installer_url, stream=True, timeout=120)
                    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
                    for chunk in r.iter_content(chunk_size=8192):
                        tmp.write(chunk)
                    tmp.close()

                    wx.CallAfter(self.yes_btn.SetLabel, _("Installing..."))
                    if sys.platform == 'win32':
                        subprocess.run([tmp.name, '/S'], check=True, timeout=120)
                    os.unlink(tmp.name)
                    wx.CallAfter(self._install_done)
                except Exception as e:
                    wx.CallAfter(wx.MessageBox,
                                 _("Installation failed: {}").format(str(e)),
                                 _("Error"), wx.OK | wx.ICON_ERROR)
                    wx.CallAfter(self.EndModal, wx.ID_CANCEL)

            def _install_done(self):
                self.EndModal(wx.ID_OK)
                if callable(self.on_installed_callback):
                    self.on_installed_callback()

        return _Dialog(parent, interpreter_name, license_url, installer_url,
                       on_installed_callback)


# ============================================================================
# HotkeyCaptureCtrl
# ============================================================================
class HotkeyCaptureCtrl:
    """A TextCtrl that captures a key combination when focused.
    Tab/Shift+Tab navigate the dialog normally (accessible for screen readers).
    Escape closes the dialog normally. Only real hotkey combos are captured."""

    def __new__(cls, parent, value=''):
        wx = _get_wx()

        # Key name mapping table
        _KEYCODE_NAMES = {
            wx.WXK_F1: 'f1', wx.WXK_F2: 'f2', wx.WXK_F3: 'f3',
            wx.WXK_F4: 'f4', wx.WXK_F5: 'f5', wx.WXK_F6: 'f6',
            wx.WXK_F7: 'f7', wx.WXK_F8: 'f8', wx.WXK_F9: 'f9',
            wx.WXK_F10: 'f10', wx.WXK_F11: 'f11', wx.WXK_F12: 'f12',
            wx.WXK_SPACE: 'space',
            wx.WXK_RETURN: 'enter', wx.WXK_NUMPAD_ENTER: 'enter',
            wx.WXK_BACK: 'backspace', wx.WXK_DELETE: 'delete',
            wx.WXK_INSERT: 'insert',
            wx.WXK_HOME: 'home', wx.WXK_END: 'end',
            wx.WXK_PAGEUP: 'page_up', wx.WXK_PAGEDOWN: 'page_down',
            wx.WXK_UP: 'up', wx.WXK_DOWN: 'down',
            wx.WXK_LEFT: 'left', wx.WXK_RIGHT: 'right',
            wx.WXK_NUMPAD0: 'numpad0', wx.WXK_NUMPAD1: 'numpad1',
            wx.WXK_NUMPAD2: 'numpad2', wx.WXK_NUMPAD3: 'numpad3',
            wx.WXK_NUMPAD4: 'numpad4', wx.WXK_NUMPAD5: 'numpad5',
            wx.WXK_NUMPAD6: 'numpad6', wx.WXK_NUMPAD7: 'numpad7',
            wx.WXK_NUMPAD8: 'numpad8', wx.WXK_NUMPAD9: 'numpad9',
            wx.WXK_NUMPAD_ADD: 'numpad_add',
            wx.WXK_NUMPAD_SUBTRACT: 'numpad_subtract',
            wx.WXK_NUMPAD_MULTIPLY: 'numpad_multiply',
            wx.WXK_NUMPAD_DIVIDE: 'numpad_divide',
            wx.WXK_NUMPAD_DECIMAL: 'numpad_decimal',
        }

        _MODIFIER_KEYCODES = {
            wx.WXK_SHIFT, wx.WXK_ALT, wx.WXK_CONTROL,
            wx.WXK_WINDOWS_LEFT, wx.WXK_WINDOWS_RIGHT,
            wx.WXK_RAW_CONTROL,
        }

        # Keys that should NOT be captured - let them navigate normally
        _NAVIGATION_KEYS = {
            wx.WXK_TAB,     # Tab / Shift+Tab = navigate dialog
            wx.WXK_ESCAPE,  # Escape = close dialog
        }

        class _Ctrl(wx.TextCtrl):
            def __init__(self, parent, value=''):
                super().__init__(parent, value=value,
                                 style=wx.TE_READONLY | wx.TE_PROCESS_ENTER)
                self._hotkey = value
                self._capturing = False
                self.SetName(_("Hotkey"))
                # EVT_CHAR_HOOK fires before the event reaches any control
                self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
                self.Bind(wx.EVT_SET_FOCUS, self._on_focus)
                self.Bind(wx.EVT_KILL_FOCUS, self._on_blur)

            def _on_focus(self, event):
                _play_focus()
                self._capturing = True
                # Announce current value for screen readers
                if self._hotkey:
                    _speak(_("Hotkey: {}").format(self._hotkey))
                else:
                    _speak(_("Hotkey: not set. Press a key combination."))
                event.Skip()

            def _on_blur(self, event):
                self._capturing = False
                event.Skip()

            def _on_char_hook(self, event):
                if not self._capturing:
                    event.Skip()
                    return

                keycode = event.GetKeyCode()

                # Modifier-only - let through
                if keycode in _MODIFIER_KEYCODES:
                    event.Skip()
                    return

                # Tab / Shift+Tab / Escape - let through for navigation
                if keycode in _NAVIGATION_KEYS:
                    event.Skip()
                    return

                # Build the hotkey string
                parts = []
                if event.ControlDown() or event.RawControlDown():
                    parts.append('ctrl')
                if event.AltDown():
                    parts.append('alt')
                if event.ShiftDown():
                    parts.append('shift')

                # Get key name
                key_name = _KEYCODE_NAMES.get(keycode, None)
                if key_name is None:
                    if 32 < keycode < 127:
                        key_name = chr(keycode).lower()
                    elif keycode < 256:
                        try:
                            ch = chr(keycode)
                            if ch.strip():
                                key_name = ch.lower()
                        except (ValueError, OverflowError):
                            pass

                if key_name:
                    parts.append(key_name)

                if parts and not all(p in ('ctrl', 'alt', 'shift') for p in parts):
                    self._hotkey = '+'.join(parts)
                    self.SetValue(self._hotkey)
                    _play_select()
                    # Announce for screen readers
                    _speak(self._hotkey)
                    # Consume the event
                    return

                event.Skip()

            def get_hotkey(self):
                return self._hotkey

            def SetValue(self, value):
                self._hotkey = value
                super().SetValue(value)

        return _Ctrl(parent, value)


# ============================================================================
# MacroRecorder
# ============================================================================
class MacroRecorder:
    """Records ALL key press/release events with timestamps to a .macro file.
    Captures raw scan codes and key names for perfect 1:1 replay.
    Shift+Escape stops recording."""

    def __init__(self, output_path):
        self.output_path = output_path
        self.actions = []
        self._start_time = None
        self._stop_event = threading.Event()
        self._shift_held = False
        self._held_keys = set()  # Track held keys to suppress auto-repeat
        self._hook = None
        self._pynput_listener = None

    def start(self):
        """Start recording keystrokes in a background thread."""
        self.actions = []
        self._start_time = _time.time()
        self._shift_held = False
        self._held_keys = set()
        self._stop_event.clear()

        _play_sound('macro/recording_begin.ogg')
        _speak(_("Recording... Press Shift+Escape to stop"))

        if KEYBOARD_AVAILABLE and sys.platform != 'darwin':
            self._start_keyboard()
        elif PYNPUT_AVAILABLE:
            self._start_pynput()
        else:
            _speak(_("No keyboard recording library available"))
            return

    def _start_keyboard(self):
        """Record using the keyboard library (Windows/Linux).
        keyboard.hook() uses WH_KEYBOARD_LL - captures every single key
        including modifiers, numpad, media, Print Screen, etc."""
        def on_event(event):
            if self._stop_event.is_set():
                return

            elapsed = int((_time.time() - self._start_time) * 1000)

            # Track shift state
            if event.name in ('shift', 'left shift', 'right shift'):
                if event.event_type == 'down':
                    self._shift_held = True
                else:
                    self._shift_held = False

            # Shift+Escape stops recording
            if event.name == 'esc' and event.event_type == 'down' and self._shift_held:
                # Remove the last shift press and any shift events after it
                # (the ones belonging to the stop combo) so shift doesn't
                # appear "held down" during playback
                last_shift_idx = -1
                for i in range(len(self.actions) - 1, -1, -1):
                    a = self.actions[i]
                    if (a.get('key') in ('shift', 'left shift', 'right shift')
                            and a.get('type') == 'key_press'):
                        last_shift_idx = i
                        break
                if last_shift_idx >= 0:
                    # Remove from last_shift_idx to end (all trailing shift events)
                    del self.actions[last_shift_idx:]
                self._stop_event.set()
                keyboard.unhook(self._hook)
                self.save()
                _play_sound('macro/recording_end.ogg')
                _speak(_("Macro created"))
                return

            # Record EVERY key event including modifiers, everything
            action_type = 'key_press' if event.event_type == 'down' else 'key_release'

            # Suppress auto-repeat: skip duplicate key_down for already-held keys
            key_id = event.scan_code if hasattr(event, 'scan_code') and event.scan_code else event.name
            if action_type == 'key_press':
                if key_id in self._held_keys:
                    return  # Skip auto-repeat event
                self._held_keys.add(key_id)
            elif action_type == 'key_release':
                self._held_keys.discard(key_id)

            action = {
                'type': action_type,
                'key': event.name,
                'time_ms': elapsed,
            }
            # Store scan code for exact hardware-level replay
            if hasattr(event, 'scan_code') and event.scan_code:
                action['scan_code'] = event.scan_code

            # Infer extended flag from key name + is_keypad
            # (keyboard library knows is_extended but doesn't store it on event)
            is_ext = _infer_extended(event)
            action['is_extended'] = is_ext

            # Derive and store VK code for reliable Windows replay
            if sys.platform == 'win32':
                sc = action.get('scan_code', 0)
                if sc and sc > 0:
                    derived_vk = _derive_vk(sc, is_ext)
                    if derived_vk:
                        action['vk'] = derived_vk
                elif sc and sc < 0:
                    # Negative scan_code = VK code (keyboard library convention)
                    action['vk'] = -sc

            self.actions.append(action)

        self._hook = keyboard.hook(on_event, suppress=False)

    def _start_pynput(self):
        """Record using pynput (macOS/Linux fallback).
        pynput.Listener also captures all keys at OS level."""
        def on_press(key):
            if self._stop_event.is_set():
                return False

            elapsed = int((_time.time() - self._start_time) * 1000)
            key_name = self._pynput_key_to_str(key)

            # Track shift state
            if key_name in ('shift', 'shift_l', 'shift_r'):
                self._shift_held = True

            # Shift+Escape stops recording
            if key_name == 'esc' and self._shift_held:
                # Remove the last shift press and any events after it
                # so shift doesn't appear "held down" during playback
                last_shift_idx = -1
                for i in range(len(self.actions) - 1, -1, -1):
                    a = self.actions[i]
                    if (a.get('key') in ('shift', 'shift_l', 'shift_r')
                            and a.get('type') == 'key_press'):
                        last_shift_idx = i
                        break
                if last_shift_idx >= 0:
                    del self.actions[last_shift_idx:]
                self._stop_event.set()
                self.save()
                _play_sound('macro/recording_end.ogg')
                _speak(_("Macro created"))
                return False

            # Suppress auto-repeat: skip duplicate key_down for already-held keys
            if key_name in self._held_keys:
                return True  # Skip auto-repeat event
            self._held_keys.add(key_name)

            # Record everything - modifiers, special keys, chars
            action = {
                'type': 'key_press',
                'key': key_name,
                'time_ms': elapsed,
            }
            # Store vk code from pynput if available
            if hasattr(key, 'vk') and key.vk is not None:
                action['vk'] = key.vk

            self.actions.append(action)
            return True

        def on_release(key):
            if self._stop_event.is_set():
                return False

            elapsed = int((_time.time() - self._start_time) * 1000)
            key_name = self._pynput_key_to_str(key)

            # Track shift state
            if key_name in ('shift', 'shift_l', 'shift_r'):
                self._shift_held = False

            self._held_keys.discard(key_name)

            action = {
                'type': 'key_release',
                'key': key_name,
                'time_ms': elapsed,
            }
            if hasattr(key, 'vk') and key.vk is not None:
                action['vk'] = key.vk

            self.actions.append(action)
            return True

        self._pynput_listener = PynputListener(on_press=on_press,
                                                on_release=on_release)
        self._pynput_listener.daemon = True
        self._pynput_listener.start()

    @staticmethod
    def _pynput_key_to_str(key):
        """Convert a pynput key to a string name."""
        if hasattr(key, 'name') and key.name:
            return key.name
        if hasattr(key, 'char') and key.char:
            return key.char
        # Fallback: vk code as string
        if hasattr(key, 'vk') and key.vk is not None:
            return 'vk_{}'.format(key.vk)
        return str(key)

    def save(self):
        """Write recorded actions to the .macro file."""
        data = {
            'version': 2,
            'actions': self.actions,
        }
        try:
            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("[MacroManager] Saved {} actions to {}".format(
                len(self.actions), self.output_path))
        except Exception as e:
            print("[MacroManager] Error saving macro: {}".format(e))

    def stop(self):
        """Force stop recording."""
        self._stop_event.set()
        if self._hook and KEYBOARD_AVAILABLE:
            try:
                keyboard.unhook(self._hook)
            except Exception:
                pass
        if self._pynput_listener:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass


# ============================================================================
# MacroHotkeyManager - Global system hotkeys for macros
# ============================================================================
class MacroHotkeyManager:
    """Manages global system hotkeys for all configured macros."""

    def __init__(self, macro_manager):
        self.macro_manager = macro_manager
        self._registered_hotkeys = []
        self._running = False
        self._pynput_listener = None

    def start(self):
        """Register all configured macro hotkeys."""
        self._running = True
        self._register_all()

    def stop(self):
        """Unregister all hotkeys."""
        self._running = False
        self._unregister_all()

    def reload(self):
        """Re-load macros and re-register hotkeys."""
        self._unregister_all()
        self.macro_manager.load_macros()
        if self._running:
            self._register_all()

    def _register_all(self):
        for macro in self.macro_manager.macros:
            hotkey = macro.get('hotkey', '')
            if not hotkey:
                continue
            self._register_hotkey(hotkey, macro)

    def _register_hotkey(self, hotkey_str, macro_info):
        if KEYBOARD_AVAILABLE and sys.platform != 'darwin':
            try:
                hook = keyboard.add_hotkey(hotkey_str,
                                           lambda m=macro_info: run_macro(m),
                                           suppress=False)
                self._registered_hotkeys.append(('keyboard', hotkey_str, hook))
            except Exception as e:
                print("[MacroManager] Failed to register hotkey '{}': {}".format(
                    hotkey_str, e))
        elif PYNPUT_AVAILABLE:
            # pynput global hotkeys use angle-bracket format
            pynput_key = '<' + '>+<'.join(hotkey_str.split('+')) + '>'
            try:
                from pynput.keyboard import GlobalHotKeys
                listener = GlobalHotKeys({pynput_key: lambda m=macro_info: run_macro(m)})
                listener.daemon = True
                listener.start()
                self._registered_hotkeys.append(('pynput', hotkey_str, listener))
            except Exception as e:
                print("[MacroManager] Failed to register pynput hotkey '{}': {}".format(
                    hotkey_str, e))

    def _unregister_all(self):
        for entry in self._registered_hotkeys:
            kind = entry[0]
            if kind == 'keyboard' and KEYBOARD_AVAILABLE:
                try:
                    keyboard.remove_hotkey(entry[2])
                except Exception:
                    pass
            elif kind == 'pynput':
                try:
                    entry[2].stop()
                except Exception:
                    pass
        self._registered_hotkeys.clear()


# ============================================================================
# ConfigureDialog
# ============================================================================
def _show_configure_dialog(parent, macro_manager, selected_macro=None):
    """Show the Configure dialog."""
    wx = _get_wx()
    from src.titan_core.sound import play_dialog_sound, play_dialogclose_sound

    play_dialog_sound()

    class ConfigureDialog(wx.Dialog):
        def __init__(self, parent, macro_manager, selected_macro):
            super().__init__(parent, title=_("Macro Manager"),
                             style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            self.macro_manager = macro_manager
            self.selected_macro = selected_macro
            self._import_path = None
            self._init_ui()

        def _init_ui(self):
            sizer = wx.BoxSizer(wx.VERTICAL)
            notebook = wx.Notebook(self)

            # --- Tab 1: Hotkey ---
            hotkey_panel = wx.Panel(notebook)
            hk_sizer = wx.BoxSizer(wx.VERTICAL)

            if self.selected_macro:
                hk_sizer.Add(wx.StaticText(hotkey_panel,
                             label=_("Hotkey for: {}").format(
                                 self.selected_macro['name'])),
                             0, wx.ALL, 5)
                current_hotkey = self.selected_macro.get('hotkey', '')
            else:
                hk_sizer.Add(wx.StaticText(hotkey_panel,
                             label=_("Select a macro first to set hotkey")),
                             0, wx.ALL, 5)
                current_hotkey = ''

            hk_sizer.Add(wx.StaticText(hotkey_panel,
                         label=_("Press desired key combination:")),
                         0, wx.LEFT | wx.RIGHT, 5)
            self.hotkey_ctrl = HotkeyCaptureCtrl(hotkey_panel, value=current_hotkey)
            hk_sizer.Add(self.hotkey_ctrl, 0, wx.ALL | wx.EXPAND, 5)

            save_hk_btn = wx.Button(hotkey_panel, label=_("Save Hotkey"))
            save_hk_btn.Bind(wx.EVT_BUTTON, self._on_save_hotkey)
            save_hk_btn.Bind(wx.EVT_SET_FOCUS, lambda e: (_play_focus(), e.Skip()))
            hk_sizer.Add(save_hk_btn, 0, wx.ALL, 5)

            clear_hk_btn = wx.Button(hotkey_panel, label=_("Clear Hotkey"))
            clear_hk_btn.Bind(wx.EVT_BUTTON, self._on_clear_hotkey)
            clear_hk_btn.Bind(wx.EVT_SET_FOCUS, lambda e: (_play_focus(), e.Skip()))
            hk_sizer.Add(clear_hk_btn, 0, wx.ALL, 5)

            hotkey_panel.SetSizer(hk_sizer)
            notebook.AddPage(hotkey_panel, _("Hotkey"))

            # --- Tab 2: Import Macro ---
            import_panel = wx.Panel(notebook)
            imp_sizer = wx.BoxSizer(wx.VERTICAL)

            imp_sizer.Add(wx.StaticText(import_panel,
                          label=_("Import a macro from a folder or ZIP file")),
                          0, wx.ALL, 5)

            imp_sizer.Add(wx.StaticText(import_panel,
                          label=_("Name (English):")), 0, wx.LEFT | wx.TOP, 5)
            self.import_name_en = wx.TextCtrl(import_panel)
            self.import_name_en.Bind(wx.EVT_SET_FOCUS,
                                     lambda e: (_play_focus(), e.Skip()))
            imp_sizer.Add(self.import_name_en, 0, wx.ALL | wx.EXPAND, 3)

            imp_sizer.Add(wx.StaticText(import_panel,
                          label=_("Name (Polish):")), 0, wx.LEFT | wx.TOP, 5)
            self.import_name_pl = wx.TextCtrl(import_panel)
            self.import_name_pl.Bind(wx.EVT_SET_FOCUS,
                                     lambda e: (_play_focus(), e.Skip()))
            imp_sizer.Add(self.import_name_pl, 0, wx.ALL | wx.EXPAND, 3)

            browse_btn = wx.Button(import_panel, label=_("Browse..."))
            browse_btn.Bind(wx.EVT_BUTTON, self._on_import_browse)
            browse_btn.Bind(wx.EVT_SET_FOCUS, lambda e: (_play_focus(), e.Skip()))
            imp_sizer.Add(browse_btn, 0, wx.ALL, 5)

            imp_sizer.Add(wx.StaticText(import_panel,
                          label=_("Script file:")), 0, wx.LEFT | wx.TOP, 5)
            self.import_file_choice = wx.Choice(import_panel)
            self.import_file_choice.Bind(wx.EVT_SET_FOCUS,
                                         lambda e: (_play_focus(), e.Skip()))
            imp_sizer.Add(self.import_file_choice, 0, wx.ALL | wx.EXPAND, 3)

            import_btn = wx.Button(import_panel, label=_("Import"))
            import_btn.Bind(wx.EVT_BUTTON, self._on_import_confirm)
            import_btn.Bind(wx.EVT_SET_FOCUS, lambda e: (_play_focus(), e.Skip()))
            imp_sizer.Add(import_btn, 0, wx.ALL, 5)

            import_panel.SetSizer(imp_sizer)
            notebook.AddPage(import_panel, _("Import Macro"))

            # --- Tab 3: New Macro ---
            new_panel = wx.Panel(notebook)
            new_sizer = wx.BoxSizer(wx.VERTICAL)

            new_sizer.Add(wx.StaticText(new_panel,
                          label=_("Macro type:")), 0, wx.ALL, 5)
            type_choices = [_("TCE Macro (.macro)"),
                            _("Titan Script (.tcs)")]
            if _find_autohotkey():
                type_choices.append(_("AutoHotKey Script (.ahk)"))
            if _find_autoit():
                type_choices.append(_("AutoIt Script (.au3)"))
            self.type_choice = wx.Choice(new_panel, choices=type_choices)
            self.type_choice.SetSelection(0)
            self.type_choice.Bind(wx.EVT_SET_FOCUS,
                                  lambda e: (_play_focus(), e.Skip()))
            new_sizer.Add(self.type_choice, 0, wx.ALL | wx.EXPAND, 3)

            new_sizer.Add(wx.StaticText(new_panel,
                          label=_("Name (English):")), 0, wx.LEFT | wx.TOP, 5)
            self.new_name_en = wx.TextCtrl(new_panel)
            self.new_name_en.Bind(wx.EVT_SET_FOCUS,
                                  lambda e: (_play_focus(), e.Skip()))
            new_sizer.Add(self.new_name_en, 0, wx.ALL | wx.EXPAND, 3)

            new_sizer.Add(wx.StaticText(new_panel,
                          label=_("Name (Polish):")), 0, wx.LEFT | wx.TOP, 5)
            self.new_name_pl = wx.TextCtrl(new_panel)
            self.new_name_pl.Bind(wx.EVT_SET_FOCUS,
                                  lambda e: (_play_focus(), e.Skip()))
            new_sizer.Add(self.new_name_pl, 0, wx.ALL | wx.EXPAND, 3)

            new_sizer.Add(wx.StaticText(new_panel,
                          label=_("Script filename:")), 0, wx.LEFT | wx.TOP, 5)
            self.new_filename = wx.TextCtrl(new_panel)
            self.new_filename.Bind(wx.EVT_SET_FOCUS,
                                   lambda e: (_play_focus(), e.Skip()))
            new_sizer.Add(self.new_filename, 0, wx.ALL | wx.EXPAND, 3)

            create_btn = wx.Button(new_panel, label=_("Create"))
            create_btn.Bind(wx.EVT_BUTTON, self._on_create_macro)
            create_btn.Bind(wx.EVT_SET_FOCUS, lambda e: (_play_focus(), e.Skip()))
            new_sizer.Add(create_btn, 0, wx.ALL, 5)

            new_panel.SetSizer(new_sizer)
            notebook.AddPage(new_panel, _("New Macro"))

            sizer.Add(notebook, 1, wx.ALL | wx.EXPAND, 5)

            close_btn = wx.Button(self, wx.ID_CANCEL, _("Close"))
            close_btn.Bind(wx.EVT_SET_FOCUS, lambda e: (_play_focus(), e.Skip()))
            sizer.Add(close_btn, 0, wx.ALL | wx.ALIGN_RIGHT, 5)

            self.SetSizer(sizer)
            self.SetSize((500, 420))
            self.CenterOnParent()

        def _on_save_hotkey(self, event):
            if not self.selected_macro:
                wx.MessageBox(_("No macro selected"), _("Error"),
                              wx.OK | wx.ICON_ERROR)
                _play_error()
                return
            _play_select()
            hk = self.hotkey_ctrl.get_hotkey()
            self.macro_manager.set_hotkey(self.selected_macro['folder_name'], hk)
            if _macro_hotkey_manager:
                _macro_hotkey_manager.reload()
            _speak(_("Hotkey set to {}").format(hk))

        def _on_clear_hotkey(self, event):
            if not self.selected_macro:
                wx.MessageBox(_("No macro selected"), _("Error"),
                              wx.OK | wx.ICON_ERROR)
                _play_error()
                return
            _play_select()
            self.hotkey_ctrl.SetValue('')
            self.hotkey_ctrl._hotkey = ''
            self.macro_manager.set_hotkey(self.selected_macro['folder_name'], '')
            if _macro_hotkey_manager:
                _macro_hotkey_manager.reload()
            _speak(_("Hotkey cleared"))

        def _on_import_browse(self, event):
            wildcard = _("Macro files") + " (*.zip)|*.zip|" + _("All files") + "|*.*"
            dlg = wx.FileDialog(self, _("Import Macro"), wildcard=wildcard)
            if dlg.ShowModal() == wx.ID_OK:
                self._import_path = dlg.GetPath()
                _play_select()
                # List script files inside ZIP
                try:
                    if zipfile.is_zipfile(self._import_path):
                        with zipfile.ZipFile(self._import_path) as zf:
                            names = [n for n in zf.namelist()
                                     if os.path.splitext(n)[1].lower()
                                     in ('.ahk', '.au3', '.macro', '.exe')]
                            self.import_file_choice.Set(names)
                            if names:
                                self.import_file_choice.SetSelection(0)
                except Exception as e:
                    print("[MacroManager] Error reading ZIP: {}".format(e))
            dlg.Destroy()

        def _on_import_confirm(self, event):
            name_en = self.import_name_en.GetValue().strip()
            name_pl = self.import_name_pl.GetValue().strip() or name_en
            if not name_en:
                wx.MessageBox(_("Please enter a macro name"), _("Error"),
                              wx.OK | wx.ICON_ERROR)
                _play_error()
                return
            if not self._import_path:
                wx.MessageBox(_("Please browse for a file first"), _("Error"),
                              wx.OK | wx.ICON_ERROR)
                _play_error()
                return
            sel = self.import_file_choice.GetSelection()
            if sel == wx.NOT_FOUND:
                wx.MessageBox(_("Please select the script file"), _("Error"),
                              wx.OK | wx.ICON_ERROR)
                _play_error()
                return
            openfile = os.path.basename(
                self.import_file_choice.GetString(sel))
            _play_select()
            self.macro_manager.import_macro_from_zip(
                self._import_path, name_en, name_pl, openfile)
            if _macro_hotkey_manager:
                _macro_hotkey_manager.reload()
            _refresh_macro_list()
            _speak(_("Macro imported successfully"))

        def _on_create_macro(self, event):
            name_en = self.new_name_en.GetValue().strip()
            name_pl = self.new_name_pl.GetValue().strip() or name_en
            filename = self.new_filename.GetValue().strip()
            if not name_en or not filename:
                wx.MessageBox(_("Please fill in all fields"), _("Error"),
                              wx.OK | wx.ICON_ERROR)
                _play_error()
                return

            type_idx = self.type_choice.GetSelection()
            type_str = self.type_choice.GetString(type_idx)
            folder_name = name_en.lower().replace(' ', '_')

            _play_select()

            if '.macro' in type_str:
                script_name = filename if filename.endswith('.macro') \
                    else filename + '.macro'
                folder_path = self.macro_manager.create_macro_folder(
                    folder_name, name_en, name_pl, script_name)
                # Write empty .macro template
                template = {"version": 1, "actions": []}
                script_full = os.path.join(folder_path, script_name)
                with open(script_full, 'w', encoding='utf-8') as f:
                    json.dump(template, f, indent=2)
                # Close dialog and start recording
                self.EndModal(wx.ID_OK)
                _refresh_macro_list()
                wx.CallAfter(_start_macro_recording, script_full)
                return

            elif TCS_EXT in type_str:
                script_name = filename if filename.endswith(TCS_EXT) \
                    else filename + TCS_EXT
                folder_path = self.macro_manager.create_macro_folder(
                    folder_name, name_en, name_pl, script_name)
                script_full = os.path.join(folder_path, script_name)
                with open(script_full, 'w', encoding='utf-8') as f:
                    f.write(TCS_TEMPLATE)
                _open_in_tedit(script_full)
                self.EndModal(wx.ID_OK)
                _refresh_macro_list()
                return

            elif '.ahk' in type_str:
                script_name = filename if filename.endswith('.ahk') \
                    else filename + '.ahk'
                folder_path = self.macro_manager.create_macro_folder(
                    folder_name, name_en, name_pl, script_name)
                script_full = os.path.join(folder_path, script_name)
                with open(script_full, 'w', encoding='utf-8') as f:
                    f.write('; AutoHotKey Script\n')
                _open_in_tedit(script_full)
                self.EndModal(wx.ID_OK)
                _refresh_macro_list()
                return

            elif '.au3' in type_str:
                script_name = filename if filename.endswith('.au3') \
                    else filename + '.au3'
                folder_path = self.macro_manager.create_macro_folder(
                    folder_name, name_en, name_pl, script_name)
                script_full = os.path.join(folder_path, script_name)
                with open(script_full, 'w', encoding='utf-8') as f:
                    f.write('; AutoIt Script\n')
                _open_in_tedit(script_full)
                self.EndModal(wx.ID_OK)
                _refresh_macro_list()
                return

            if _macro_hotkey_manager:
                _macro_hotkey_manager.reload()

    dlg = ConfigureDialog(parent, macro_manager, selected_macro)
    dlg.ShowModal()
    play_dialogclose_sound()
    dlg.Destroy()


def _start_macro_recording(output_path):
    """Start the macro recorder."""
    recorder = MacroRecorder(output_path)
    recorder.start()


# ============================================================================
# GUI refresh helper
# ============================================================================
def _refresh_macro_list():
    """Refresh the macro list in the GUI and IUI."""
    global _macro_manager, _macro_listbox
    if _macro_manager:
        _macro_manager.load_macros()
    if _macro_listbox:
        try:
            wx = _get_wx()
            _macro_listbox.Clear()
            if _macro_manager:
                names = _macro_manager.get_macro_names()
                if names:
                    for name in names:
                        _macro_listbox.Append(name)
                else:
                    _macro_listbox.Append(_("No macros found"))
        except Exception:
            pass
    # Also refresh IUI macro list
    _iui_refresh_macro_list()


# ============================================================================
# Component hook functions
# ============================================================================
def add_menu(component_manager):
    """Register menu item in Components menu."""
    component_manager.register_menu_function(_("Macro Manager"), _on_menu_action)


def _on_menu_action(event):
    """Open the configure dialog from the Components menu."""
    global _macro_manager
    if not _macro_manager:
        _macro_manager = MacroManager(MACROS_DIR)
    _show_configure_dialog(_gui_app_ref, _macro_manager)


def get_gui_hooks():
    return {'on_gui_init': _on_gui_init}


def _on_gui_init(gui_app):
    """Register macro list view in the main GUI panel."""
    global _gui_app_ref, _macro_manager, _macro_listbox
    wx = _get_wx()

    _gui_app_ref = gui_app

    if not _macro_manager:
        _macro_manager = MacroManager(MACROS_DIR)

    _macro_listbox = wx.ListBox(gui_app.main_panel)

    # Populate
    names = _macro_manager.get_macro_names()
    if names:
        for name in names:
            _macro_listbox.Append(name)
    else:
        _macro_listbox.Append(_("No macros found"))

    # Bind events
    _macro_listbox.Bind(wx.EVT_CONTEXT_MENU, _on_macro_context_menu)
    _macro_listbox.Bind(wx.EVT_LISTBOX, _on_macro_selection)

    # Register view
    gui_app.component_manager.register_view(
        view_id='macros',
        label=_("Macros:"),
        control=_macro_listbox,
        on_show=_on_macros_view_show,
        on_activate=_on_macro_activate,
        position='after_network'
    )


def _on_macros_view_show():
    """Called when the macros view becomes visible."""
    _refresh_macro_list()


def _on_macro_selection(event):
    """Play focus sound on selection change."""
    _play_focus()


def _on_macro_activate(event):
    """Handle Enter key on macro list - show context menu."""
    _on_macro_context_menu(event)


def _on_macro_context_menu(event):
    """Show context menu for the selected macro."""
    global _macro_manager, _macro_listbox, _gui_app_ref
    wx = _get_wx()

    if not _macro_listbox:
        return

    selection = _macro_listbox.GetSelection()
    if selection == wx.NOT_FOUND:
        return

    macro_name = _macro_listbox.GetString(selection)
    if macro_name == _("No macros found"):
        # Still show configure for import/new macro
        _show_configure_dialog(_gui_app_ref, _macro_manager)
        return

    macro_info = _macro_manager.find_by_name(macro_name) if _macro_manager else None
    if not macro_info:
        return

    _play_sound('ui/contextmenu.ogg')

    menu = wx.Menu()

    # Run
    run_item = menu.Append(wx.ID_ANY, _("Run"))
    _gui_app_ref.Bind(wx.EVT_MENU,
                       lambda evt, m=macro_info: wx.CallAfter(
                           run_macro, m, _gui_app_ref),
                       run_item)

    # Edit
    edit_item = menu.Append(wx.ID_ANY, _("Edit"))
    _gui_app_ref.Bind(wx.EVT_MENU,
                       lambda evt, m=macro_info: wx.CallAfter(
                           _edit_macro, m),
                       edit_item)

    # Configure
    cfg_item = menu.Append(wx.ID_ANY, _("Configure"))
    _gui_app_ref.Bind(wx.EVT_MENU,
                       lambda evt, m=macro_info: wx.CallAfter(
                           _show_configure_dialog,
                           _gui_app_ref, _macro_manager, m),
                       cfg_item)

    # Delete
    del_item = menu.Append(wx.ID_ANY, _("Delete"))
    _gui_app_ref.Bind(wx.EVT_MENU,
                       lambda evt, m=macro_info: wx.CallAfter(
                           _delete_macro_confirm, m),
                       del_item)

    _macro_listbox.PopupMenu(menu)
    _play_sound('ui/contextmenuclose.ogg')
    menu.Destroy()


def _edit_macro(macro_info):
    """Edit a macro - open in TEdit or re-record for .macro."""
    ext = macro_info.get('type', '')
    script_path = macro_info.get('script_path', '')

    if ext == '.macro':
        _play_select()
        _start_macro_recording(script_path)
    elif ext in ('.ahk', '.au3', TCS_EXT):
        # A Titan Script is plain text, so it is edited like any other script.
        _play_select()
        _open_in_tedit(script_path)
    elif ext == '.exe':
        _speak(_("Cannot edit executable macros"))
        _play_error()
    else:
        _play_select()
        _open_in_tedit(script_path)


def _delete_macro_confirm(macro_info):
    """Show confirmation dialog before deleting a macro."""
    global _macro_manager
    wx = _get_wx()
    from src.titan_core.sound import play_dialog_sound, play_dialogclose_sound

    play_dialog_sound()
    dlg = wx.MessageDialog(
        _gui_app_ref,
        _("Are you sure you want to delete '{}'?").format(macro_info['name']),
        _("Delete Macro"),
        wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
    )
    result = dlg.ShowModal()
    play_dialogclose_sound()
    dlg.Destroy()

    if result == wx.ID_YES:
        _play_select()
        _macro_manager.delete_macro(macro_info['folder_name'])
        if _macro_hotkey_manager:
            _macro_hotkey_manager.reload()
        _refresh_macro_list()
        _speak(_("Macro deleted"))


# ============================================================================
# IUI hooks
# ============================================================================
_iui_ref = None
_iui_macro_backup = None
_iui_selected_macro = None

def get_iui_hooks():
    return {'on_iui_init': _on_iui_init}


def _on_iui_init(iui):
    """Add Macros category to the Invisible UI."""
    global _macro_manager, _iui_ref
    _iui_ref = iui
    if not _macro_manager:
        _macro_manager = MacroManager(MACROS_DIR)

    macro_names = _macro_manager.get_macro_names()
    if not macro_names:
        macro_names = [_("No macros found")]

    # Insert before the last categories (Menu, Components)
    insert_idx = len(iui.categories) - 1
    if insert_idx < 0:
        insert_idx = 0

    iui.categories.insert(insert_idx, {
        "name": _("Macros"),
        "sound": "core/focus.ogg",
        "elements": macro_names,
        "action": _iui_macro_action,
    })


def _iui_macro_action(macro_name):
    """Handle macro activation in IUI - show context menu."""
    global _macro_manager, _iui_ref, _iui_macro_backup, _iui_selected_macro

    if macro_name == _("No macros found"):
        _speak(_("No macros found"))
        return

    if not _iui_ref:
        return

    macro_info = _macro_manager.find_by_name(macro_name) if _macro_manager else None
    if not macro_info:
        return

    _iui_selected_macro = macro_info

    try:
        from src.titan_core.sound import play_sound
        play_sound("ui/focus_expanded.ogg")
    except Exception:
        pass

    # Find Macros category index
    macros_idx = None
    for i, cat in enumerate(_iui_ref.categories):
        if cat.get('name') == _("Macros"):
            macros_idx = i
            _iui_macro_backup = cat.copy()
            break

    if macros_idx is None:
        return

    # Build context menu elements
    menu_elements = [
        _("Back"),
        _("Run"),
        _("Edit"),
        _("Configure"),
        _("Delete"),
    ]

    _iui_ref.categories[macros_idx] = {
        "name": macro_name,
        "sound": "core/focus.ogg",
        "elements": menu_elements,
        "action": _iui_macro_context_action,
        "is_macro_context": True,
    }

    _iui_ref.current_element_index = 0
    _speak(_("Back"))


def _iui_macro_context_action(action_name):
    """Handle context menu action for a macro in IUI."""
    global _iui_selected_macro, _macro_manager, _iui_ref

    if not _iui_selected_macro:
        return

    if action_name == _("Back"):
        _iui_collapse_macro_context()
        return

    # Save reference before collapsing (collapse sets _iui_selected_macro to None)
    selected = _iui_selected_macro

    if action_name == _("Run"):
        _iui_collapse_macro_context()
        run_macro(selected)
        return

    if action_name == _("Edit"):
        _iui_collapse_macro_context()
        _edit_macro(selected)
        return

    if action_name == _("Configure"):
        _iui_collapse_macro_context()
        parent = _iui_ref.main_frame if _iui_ref else None
        if parent:
            wx = _get_wx()
            wx.CallAfter(_show_configure_dialog, parent, _macro_manager, selected)
        return

    if action_name == _("Delete"):
        _iui_collapse_macro_context()
        parent = _iui_ref.main_frame if _iui_ref else None
        if parent:
            wx = _get_wx()
            wx.CallAfter(_iui_delete_macro, selected, parent)
        return


def _iui_delete_macro(macro_info, parent):
    """Delete a macro from IUI with confirmation."""
    global _macro_manager, _macro_hotkey_manager
    wx = _get_wx()
    from src.titan_core.sound import play_dialog_sound, play_dialogclose_sound

    play_dialog_sound()
    dlg = wx.MessageDialog(
        parent,
        _("Are you sure you want to delete '{}'?").format(macro_info['name']),
        _("Delete Macro"),
        wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
    )
    result = dlg.ShowModal()
    play_dialogclose_sound()
    dlg.Destroy()

    if result == wx.ID_YES:
        _play_select()
        _macro_manager.delete_macro(macro_info['folder_name'])
        if _macro_hotkey_manager:
            _macro_hotkey_manager.reload()
        _iui_refresh_macro_list()
        _speak(_("Macro deleted"))


def _iui_collapse_macro_context():
    """Collapse the macro context menu back to the macro list."""
    global _iui_ref, _iui_macro_backup, _iui_selected_macro

    if not _iui_ref:
        return

    try:
        from src.titan_core.sound import play_sound
        play_sound("ui/focus_collabsed.ogg")
    except Exception:
        pass

    # Find and restore Macros category
    macros_idx = None
    for i, cat in enumerate(_iui_ref.categories):
        if cat.get('is_macro_context'):
            macros_idx = i
            break

    if macros_idx is not None and _iui_macro_backup is not None:
        # Refresh macro list before restoring
        macro_names = _macro_manager.get_macro_names() if _macro_manager else []
        if not macro_names:
            macro_names = [_("No macros found")]
        _iui_macro_backup['elements'] = macro_names
        _iui_ref.categories[macros_idx] = _iui_macro_backup

    _iui_macro_backup = None
    _iui_selected_macro = None
    _iui_ref.current_element_index = 0
    _speak(_("Macros"))


def _iui_refresh_macro_list():
    """Refresh the macro list in IUI after changes."""
    global _iui_ref, _macro_manager
    if not _iui_ref or not _macro_manager:
        return

    _macro_manager.load_macros()
    macro_names = _macro_manager.get_macro_names()
    if not macro_names:
        macro_names = [_("No macros found")]

    for cat in _iui_ref.categories:
        if cat.get('name') == _("Macros"):
            cat['elements'] = macro_names
            break


# ============================================================================
# Klango hooks
# ============================================================================
def get_klango_hooks():
    return {'on_klango_init': _on_klango_init}


def _on_klango_init(klango_mode):
    """Add Macros submenu to Klango mode."""
    global _macro_manager
    if not _macro_manager:
        _macro_manager = MacroManager(MACROS_DIR)

    macro_items = []
    for macro in _macro_manager.macros:
        macro_items.append({
            "name": macro['name'],
            "type": "action",
            "action": lambda m=macro: run_macro(m),
        })

    if not macro_items:
        macro_items = [{
            "name": _("No macros found"),
            "type": "action",
            "action": lambda: _speak(_("No macros found")),
        }]

    # Insert Macros submenu before Components (index 5)
    macros_menu = {
        "name": _("Macros"),
        "type": "submenu",
        "items": macro_items,
        "expanded": False,
    }

    # Try to insert before Components submenu
    if len(klango_mode.main_menu) > 5:
        klango_mode.main_menu.insert(5, macros_menu)
    else:
        klango_mode.main_menu.append(macros_menu)


# ============================================================================
# Initialize / Shutdown
# ============================================================================
def initialize(app):
    """Called after main event loop is running. Start global hotkey manager."""
    global _macro_manager, _macro_hotkey_manager, _tcs_scheduler

    if not _macro_manager:
        _macro_manager = MacroManager(MACROS_DIR)

    _macro_hotkey_manager = MacroHotkeyManager(_macro_manager)
    _macro_hotkey_manager.start()

    # A Titan Script can ask to run by itself ('when startup', 'when time = ...').
    # The watcher only exists if some macro actually says so - a user with no
    # triggered macros pays nothing for the feature.
    try:
        if any(m.get('type') == TCS_EXT for m in _macro_manager.macros):
            _tcs_scheduler = TCSScheduler(_macro_manager)
            _tcs_scheduler.start()
    except Exception as e:
        print(f"[tcs] could not start the trigger watcher: {e}")


def shutdown():
    """Called on app exit. Stop hotkey manager."""
    global _macro_hotkey_manager, _tcs_scheduler
    if _macro_hotkey_manager:
        _macro_hotkey_manager.stop()
        _macro_hotkey_manager = None
    if _tcs_scheduler:
        _tcs_scheduler.stop()
        _tcs_scheduler = None


# ---------------------------------------------------------------------------
# Settings category
# ---------------------------------------------------------------------------
import platform as _platform

def _get_macro_config_path():
    """Get path to macro manager settings file."""
    if _platform.system() == 'Windows':
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        config_dir = os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings')
    elif _platform.system() == 'Darwin':
        config_dir = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings')
    else:
        config_dir = os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan', 'appsettings')
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, 'macros.ini')


def _get_macro_setting(key, default='True'):
    """Read a single macro setting from the config file."""
    config = configparser.ConfigParser()
    path = _get_macro_config_path()
    if os.path.exists(path):
        config.read(path, encoding='utf-8')
    return config.get('Settings', key, fallback=default)


def add_settings_category(component_manager):
    """Register Macro Manager settings category in the main settings window."""
    import wx as _wx

    def create_macro_settings_panel(parent):
        panel = _wx.Panel(parent)
        vbox = _wx.BoxSizer(_wx.VERTICAL)

        panel.sound_announce_cb = _wx.CheckBox(panel, label=_("Announce macro actions with sound"))
        panel.sound_announce_cb.Bind(_wx.EVT_SET_FOCUS, lambda evt: evt.Skip())
        vbox.Add(panel.sound_announce_cb, flag=_wx.LEFT | _wx.TOP, border=10)

        panel.speech_announce_cb = _wx.CheckBox(panel, label=_("Announce macro actions with speech"))
        panel.speech_announce_cb.Bind(_wx.EVT_SET_FOCUS, lambda evt: evt.Skip())
        vbox.Add(panel.speech_announce_cb, flag=_wx.LEFT | _wx.TOP, border=10)

        panel.SetSizer(vbox)
        panel.Layout()
        return panel

    def save_macro_settings(panel):
        config = configparser.ConfigParser()
        path = _get_macro_config_path()
        if os.path.exists(path):
            config.read(path, encoding='utf-8')
        if 'Settings' not in config:
            config['Settings'] = {}
        config['Settings']['announce_sound'] = str(panel.sound_announce_cb.GetValue())
        config['Settings']['announce_speech'] = str(panel.speech_announce_cb.GetValue())
        with open(path, 'w', encoding='utf-8') as f:
            config.write(f)

    def load_macro_settings(panel):
        config = configparser.ConfigParser()
        path = _get_macro_config_path()
        if os.path.exists(path):
            config.read(path, encoding='utf-8')
        panel.sound_announce_cb.SetValue(
            config.get('Settings', 'announce_sound', fallback='True').lower() in ['true', '1'])
        panel.speech_announce_cb.SetValue(
            config.get('Settings', 'announce_speech', fallback='True').lower() in ['true', '1'])

    component_manager.register_settings_category(
        _("Macro Manager"), create_macro_settings_panel, save_macro_settings, load_macro_settings)


# ===========================================================================
# Titan actions - what Titan, its AI and other add-ons can ask this component
# ===========================================================================
# Running a macro by name is the whole point: a macro is already the user's own
# named piece of automation, so exposing it here turns every macro they have
# written into something the AI and other add-ons can trigger, without this
# component knowing anything about either.

try:
    from src.titan_core.actions import fails, needs
except Exception:                       # Titan not importable - actions unused
    def fails(reason):
        return reason

    def needs(name, prompt, options=None, kind='string', default=''):
        return prompt


# ===========================================================================
# Titan Script (.tcs) - a mini scripting language made of Titan actions
# ===========================================================================
# A .macro replays keystrokes, which is all it can do: it knows nothing about
# Titan. But everything Titan and its add-ons can do is already declared, typed
# and callable through the Action API - so a macro that *names* those actions
# can do anything Titan can, and say why when it cannot.
#
#     when time = "11:45"
#
#     titan.tts.speak "Time to eat"
#     titan.play.locally "Nirvana"
#     wait 2s
#     set state = zegarynka.get_settings
#     if state contains "on"
#         say "The chime is on"
#     end
#
# Nothing here calls a model: the language is Titan actions and conditions, so
# a macro written this way runs with the AI switched off. What the AI is for is
# *writing* one - the whole point of the name - and that is gated where every
# other AI feature is, by the AI being on at all.
#
# The file is plain text, so Edit opens it in tEdit like any other script.

TCS_EXT = '.tcs'

# The natural spellings of actions whose declared name reads differently.
# Deliberately short: the general rules below resolve almost everything, and a
# long alias table would be a second, private vocabulary to keep in step.
_AI_ALIASES = {
    'titan.tts.speak': ('titan', 'speak'),
    'titan.speak.text': ('titan', 'speak'),
    'titan.play.locally': ('titan', 'play_media'),
    'titan.play.local': ('titan', 'play_media'),
    'titan.play.radio': ('titan', 'play_radio'),
    'titan.play.audiobook': ('titan', 'play_audiobook'),
    'titan.mail.send': ('titannet', 'send_mail'),
    'titan.reminder.create': ('titan', 'create_reminder'),
}

_AI_TIME_UNITS = {'s': 1, 'sec': 1, 'secs': 1, 'second': 1, 'seconds': 1,
                  'm': 60, 'min': 60, 'mins': 60, 'minute': 60, 'minutes': 60,
                  'h': 3600, 'hour': 3600, 'hours': 3600}


class TCSError(Exception):
    """A line that cannot be understood or resolved. Carries the line number."""

    def __init__(self, line_no, message, hint=''):
        super().__init__(message)
        self.line_no = line_no
        self.message = message
        self.hint = hint

    def describe(self):
        return (f"line {self.line_no}: {self.message}"
                + (f" {self.hint}" if self.hint else ''))


# --------------------------------------------------------------------------- #
# Resolving a dotted name onto a real action
# --------------------------------------------------------------------------- #
def _ai_registry():
    from src.titan_core import actions
    return actions.get_registry()


def _ai_resolve(path):
    """('addon', 'action', spec) for a dotted name, or raise ValueError.

    A macro is written by a person (or by the AI on their behalf), so the
    spelling is theirs, not the registry's: 'titan.tts.speak' and 'titan.speak'
    must both reach the same action. What is never done is guessing between
    several candidates - an ambiguous name is an error naming them, because a
    macro that quietly ran the wrong action would be worse than one that
    refused.
    """
    raw = str(path or '').strip()
    lowered = raw.lower()
    registry = _ai_registry()

    def look(addon_id, action_name):
        addon = registry.by_id(addon_id)
        if addon is None:
            return None
        spec = addon.get(action_name)
        return (addon.addon_id, spec.name, spec) if spec is not None else None

    if lowered in _AI_ALIASES:
        found = look(*_AI_ALIASES[lowered])
        if found:
            return found

    parts = [p for p in lowered.split('.') if p]
    if len(parts) < 2:
        raise ValueError(f"'{raw}' is not an action - write it as "
                         f"add-on.action, for example titan.speak")

    head, rest = parts[0], parts[1:]
    for candidate in ('_'.join(rest), rest[-1], '_'.join(reversed(rest))):
        found = look(head, candidate)
        if found:
            return found

    addon = registry.by_id(head)
    if addon is not None:
        # The add-on is real, so the action is what is wrong. Offer the ones
        # that start the way this one does before offering everything.
        stem = rest[0]
        near = [a.name for a in addon.actions if a.name.startswith(stem)]
        if len(near) == 1:
            spec = addon.get(near[0])
            return addon.addon_id, spec.name, spec
        options = near or [a.name for a in addon.actions]
        raise ValueError(f"'{addon.addon_id}' has no action '{'.'.join(rest)}'."
                         f" Did you mean: "
                         + ", ".join(f"{addon.addon_id}.{n}" for n in options[:8])
                         + "?")

    # No such add-on. The action name alone may still be unique across Titan.
    wanted = rest[-1]
    matches = [(a.addon_id, act.name, act) for a in registry.addons
               for act in a.actions if act.name == wanted]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"'{raw}' is ambiguous - "
                         + ", ".join(f"{aid}.{n}" for aid, n, _s in matches[:8])
                         + " all match. Write the add-on's id in full.")
    raise ValueError(f"Titan has no add-on called '{head}'. Run "
                     f"macros.list_actions to see what can be scripted.")


# --------------------------------------------------------------------------- #
# Reading one line
# --------------------------------------------------------------------------- #
def _ai_split_args(text):
    """Split an argument list on commas and spaces, respecting quotes."""
    items = []
    current = ''
    quote = ''
    for char in text:
        if quote:
            if char == quote:
                quote = ''
            current += char
            continue
        if char in '"\'':
            quote = char
            current += char
            continue
        if char == ',' or char.isspace():
            if current.strip():
                items.append(current.strip())
            current = ''
            continue
        current += char
    if current.strip():
        items.append(current.strip())
    return items


def _ai_literal(token):
    """A written value as a Python value. Bare words stay strings."""
    text = str(token).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in '"\'':
        return text[1:-1]
    lowered = text.lower()
    if lowered in ('true', 'yes', 'on'):
        return True
    if lowered in ('false', 'no', 'off'):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


# --------------------------------------------------------------------------- #
# Expressions - what can be done to a variable
# --------------------------------------------------------------------------- #
# A macro that can only pass values straight through cannot count, join a name
# onto a greeting, or ask whether a number is big enough. This is a real but
# deliberately small expression language: arithmetic, joining text, a handful of
# functions. It is parsed, never eval'd - a macro is a file on disk, and a file
# on disk must not be able to run arbitrary Python.

_AI_FUNCTIONS = {
    'upper': lambda a: str(a).upper(),
    'lower': lambda a: str(a).lower(),
    'trim': lambda a: str(a).strip(),
    'length': lambda a: len(str(a)),
    'text': lambda a: str(a),
    'number': lambda a: _ai_number(a),
    'round': lambda a, digits=0: round(float(_ai_number(a)), int(digits)),
    'replace': lambda a, old, new: str(a).replace(str(old), str(new)),
    'now': lambda fmt='%H:%M': _time.strftime(str(fmt)),
    'today': lambda fmt='%Y-%m-%d': _time.strftime(str(fmt)),
}

_AI_TOKEN = None


def _ai_number(value):
    """A value as a number, or 0 - a macro should not die on 'two'."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return 0


def _ai_tokenise(text):
    global _AI_TOKEN
    if _AI_TOKEN is None:
        _AI_TOKEN = re.compile(
            r'\s*(?:(\d+\.\d+|\d+)'                 # number
            r'|("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')'   # string
            r'|(\{\{[a-zA-Z_][a-zA-Z_0-9]*\}\})'    # {{name}}
            r'|([a-zA-Z_][a-zA-Z_0-9]*)'            # name
            r'|(\*\*|[-+*/(),]))')                  # operator
    tokens = []
    position = 0
    while position < len(text):
        match = _AI_TOKEN.match(text, position)
        if not match:
            if text[position:].strip():
                raise ValueError(f"cannot read '{text[position:].strip()}'")
            break
        position = match.end()
        number, string, braced, name, operator = match.groups()
        if number is not None:
            tokens.append(('num', float(number) if '.' in number else int(number)))
        elif string is not None:
            tokens.append(('str', string[1:-1]))
        elif braced is not None:
            tokens.append(('name', braced[2:-2]))
        elif name is not None:
            tokens.append(('name', name))
        else:
            tokens.append(('op', operator))
    return tokens


class _AIExpr:
    """A parsed expression, evaluated later against the macro's variables."""

    def __init__(self, tokens, source):
        self.tokens = tokens
        self.source = source

    def evaluate(self, variables):
        self._position = 0
        self._variables = variables
        value = self._sum()
        if self._position < len(self.tokens):
            raise ValueError(f"'{self.source}' has more in it than an "
                             f"expression")
        return value

    # -- recursive descent -------------------------------------------------- #
    def _peek(self):
        return (self.tokens[self._position]
                if self._position < len(self.tokens) else (None, None))

    def _take(self):
        token = self._peek()
        self._position += 1
        return token

    def _sum(self):
        value = self._product()
        while self._peek() == ('op', '+') or self._peek() == ('op', '-'):
            _kind, operator = self._take()
            right = self._product()
            if operator == '+':
                # Numbers add; anything with text in it joins. That is what a
                # person writing "Hello " + name means.
                if isinstance(value, (int, float)) and not isinstance(value, bool) \
                        and isinstance(right, (int, float)) and not isinstance(right, bool):
                    value = value + right
                else:
                    value = f"{value}{right}"
            else:
                value = _ai_number(value) - _ai_number(right)
        return value

    def _product(self):
        value = self._unary()
        while self._peek() in (('op', '*'), ('op', '/')):
            _kind, operator = self._take()
            right = self._unary()
            if operator == '*':
                value = _ai_number(value) * _ai_number(right)
            else:
                divisor = _ai_number(right)
                if not divisor:
                    raise ValueError("cannot divide by zero")
                value = _ai_number(value) / divisor
        return value

    def _unary(self):
        if self._peek() == ('op', '-'):
            self._take()
            return -_ai_number(self._unary())
        return self._primary()

    def _primary(self):
        kind, value = self._take()
        if kind == 'num' or kind == 'str':
            return value
        if kind == 'op' and value == '(':
            inner = self._sum()
            if self._take() != ('op', ')'):
                raise ValueError("a bracket is not closed")
            return inner
        if kind == 'name':
            lowered = str(value).lower()
            if self._peek() == ('op', '('):
                self._take()
                arguments = []
                if self._peek() != ('op', ')'):
                    arguments.append(self._sum())
                    while self._peek() == ('op', ','):
                        self._take()
                        arguments.append(self._sum())
                if self._take() != ('op', ')'):
                    raise ValueError(f"{value}( is not closed")
                function = _AI_FUNCTIONS.get(lowered)
                if function is None:
                    raise ValueError(f"there is no function called '{value}' - "
                                     f"there is "
                                     + ", ".join(sorted(_AI_FUNCTIONS)))
                try:
                    return function(*arguments)
                except TypeError:
                    raise ValueError(f"'{value}' was given the wrong number of "
                                     f"values")
            if lowered in ('true', 'yes', 'on'):
                return True
            if lowered in ('false', 'no', 'off'):
                return False
            return self._variables.get(lowered, '')
        raise ValueError(f"'{self.source}' is not an expression")


def _ai_looks_like_expression(text):
    """Whether a right-hand side is worth parsing as an expression.

    A bare `"hello"` or `42` needs no machinery, and neither does a value the
    author clearly meant literally. An operator or a function call does.
    """
    stripped = str(text).strip()
    if not stripped:
        return False
    try:
        tokens = _ai_tokenise(stripped)
    except ValueError:
        return False
    if not tokens:
        return False
    if len(tokens) == 1:
        return tokens[0][0] == 'name'
    return True


def _ai_looks_like_call(line):
    """Whether a line names an action, rather than describing one in words.

    The test is deliberately narrow: a dotted identifier at the very start,
    with nothing but name characters in it. 'titan.speak "hi"' is a call;
    'remind me on Tuesday about the dentist' is not, and neither is
    'open the file C:\\notes.txt' - which contains a dot but is prose.

    Each part must also begin like a name rather than a digit, or the number
    0.8 is read as the action 'eight' of an add-on called '0'.
    """
    head = str(line).strip().split(' ')[0].split('(')[0]
    if '.' not in head:
        return False
    parts = head.split('.')
    if len(parts) < 2 or not all(parts):
        return False
    return all(part.replace('_', '').isalnum() and not part[0].isdigit()
               for part in parts)


def _ai_parse_call(line_no, text):
    """{'kind': 'call', ...} for `addon.action arg="v"` / `addon.action("v")`."""
    body = text.strip()
    name, _sep, remainder = body.partition(' ')
    if '(' in body and (body.index('(') < len(name) or not _sep):
        name = body[:body.index('(')].strip()
        remainder = body[body.index('('):].strip()
    remainder = remainder.strip()
    if remainder.startswith('(') and remainder.endswith(')'):
        remainder = remainder[1:-1]
    named = {}
    positional = []
    for item in _ai_split_args(remainder):
        key, sep, value = item.partition('=')
        if sep and key.strip().replace('_', '').isalnum() and not key.strip()[0].isdigit():
            named[key.strip().lower()] = _ai_literal(value)
        else:
            positional.append(_ai_literal(item))
    return {'kind': 'call', 'line': line_no, 'path': name.strip(),
            'named': named, 'positional': positional}


def _ai_parse(text):
    """(program, errors). A program is {'triggers': [...], 'body': [...]}.

    Parsing never stops at the first bad line: a macro with three mistakes
    should report three, not send its author round the loop three times.
    """
    triggers = []
    errors = []
    root = []
    stack = [root]          # innermost block last
    openers = []            # the statement each open block belongs to

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#') or line.startswith(';'):
            continue
        lowered = line.lower()
        block = stack[-1]

        try:
            if lowered.startswith('when '):
                if stack[-1] is not root:
                    raise TCSError(number, "'when' belongs at the top of "
                                               "the macro, not inside a block")
                triggers.append(_ai_parse_trigger(number, line[5:]))
                continue

            if lowered in ('end', 'end if', 'end repeat'):
                if len(stack) == 1:
                    raise TCSError(number, "'end' with nothing open")
                stack.pop()
                openers.pop()
                continue

            if lowered == 'else':
                if len(stack) == 1 or openers[-1]['kind'] != 'if':
                    raise TCSError(number, "'else' outside an 'if'")
                openers[-1]['else'] = []
                stack[-1] = openers[-1]['else']
                continue

            if lowered.startswith('if '):
                statement = _ai_parse_if(number, line[3:])
                block.append(statement)
                stack.append(statement['then'])
                openers.append(statement)
                continue

            if lowered.startswith('repeat '):
                count = _ai_literal(line[7:].strip())
                if not isinstance(count, int) or count < 1:
                    raise TCSError(number, "'repeat' wants a whole number "
                                               "of times, e.g. 'repeat 3'")
                statement = {'kind': 'repeat', 'line': number,
                             'count': min(count, 1000), 'body': []}
                block.append(statement)
                stack.append(statement['body'])
                openers.append(statement)
                continue

            if lowered.startswith('wait '):
                block.append({'kind': 'wait', 'line': number,
                              'seconds': _ai_seconds(number, line[5:])})
                continue

            if lowered.startswith(('say ', 'speak ')):
                _word, _sep, rest = line.partition(' ')
                values, named = _ai_arg_tail(number, rest)
                unknown = [k for k in named if k not in ('wait', 'interrupt')]
                if unknown:
                    raise TCSError(number, "'say' does not know "
                                   + ", ".join(unknown),
                                   "It takes wait and interrupt.")
                if not values:
                    raise TCSError(number, "'say' wants something to say")
                block.append({'kind': 'say', 'line': number,
                              'text': values[0],
                              'wait': named.get('wait'),
                              'interrupt': named.get('interrupt')})
                continue

            if lowered.startswith('return '):
                block.append({'kind': 'return', 'line': number,
                              'value': _ai_rvalue(number, line[7:])})
                continue

            if lowered == 'return':
                block.append({'kind': 'return', 'line': number, 'value': None})
                continue

            if lowered.startswith('play '):
                values, named = _ai_arg_tail(number, line[5:])
                if not values and 'file' not in named:
                    raise TCSError(number, "'play' wants a sound file, e.g. "
                                           'play "ding.ogg"')
                block.append({'kind': 'play', 'line': number,
                              'file': values[0] if values else named['file'],
                              'position': named.get('position'),
                              'wait': named.get('wait')})
                continue

            if lowered == 'stop':
                block.append({'kind': 'stop', 'line': number})
                continue

            if lowered == 'voice reset':
                block.append({'kind': 'voice', 'line': number, 'reset': True})
                continue

            if lowered.startswith('voice '):
                _values, named = _ai_arg_tail(number, line[6:])
                known = ('engine', 'name', 'rate', 'pitch', 'volume')
                unknown = [k for k in named if k not in known]
                if unknown:
                    raise TCSError(number, "'voice' does not know "
                                   + ", ".join(unknown),
                                   "It takes engine, name, rate, pitch and "
                                   "volume.")
                if not named:
                    raise TCSError(number, "'voice' wants something to change, "
                                           'e.g. voice engine="supertonic"')
                statement = {'kind': 'voice', 'line': number, 'reset': False}
                statement.update({k: named.get(k) for k in known})
                block.append(statement)
                continue

            if lowered.startswith('run '):
                values, named = _ai_arg_tail(number, line[4:])
                if not values and 'script' not in named:
                    raise TCSError(number, "'run' wants another script, e.g. "
                                           'run "helper.tcs"')
                block.append({'kind': 'run', 'line': number,
                              'script': values[0] if values else named['script']})
                continue

            if lowered.startswith('set '):
                name, sep, value = line[4:].partition('=')
                if not sep:
                    raise TCSError(number, "'set' wants a name and a "
                                               "value, e.g. set x = titan.speak")
                block.append({'kind': 'set', 'line': number,
                              'name': name.strip().lower(),
                              'value': _ai_rvalue(number, value.strip())})
                continue

            if lowered.startswith(('message ', 'warn ', 'error ', 'inform ')):
                word, _sep, rest = line.partition(' ')
                values, named = _ai_arg_tail(number, rest)
                level = {'warn': 'warning', 'error': 'error'}.get(
                    word.lower(), 'info')
                block.append({'kind': 'message', 'line': number,
                              'text': values[0] if values else {'kind': 'value',
                                                                'value': ''},
                              'title': named.get('title'),
                              'level': level})
                continue

            if lowered.startswith(('ask ', 'confirm ', 'choose ')):
                block.append(_ai_parse_prompt(number, line))
                continue

            if lowered.startswith('dialog'):
                statement = {'kind': 'dialog', 'line': number,
                             'title': _ai_literal(line[6:].strip() or '""'),
                             'fields': []}
                block.append(statement)
                stack.append(statement['fields'])
                openers.append(statement)
                continue

            if lowered.startswith(('field ', 'multiline ', 'choice ',
                                   'check ')):
                if not openers or openers[-1]['kind'] != 'dialog':
                    raise TCSError(number, f"'{lowered.split(' ')[0]}' "
                                               f"belongs inside a 'dialog'")
                block.append(_ai_parse_field(number, line))
                continue

            if lowered.startswith('do '):
                block.append({'kind': 'prose', 'line': number,
                              'text': _ai_literal(line[3:].strip())})
                continue

            # A line that does not name an action is not necessarily a
            # mistake: with AI features on it is pseudocode, and the AI works
            # out which actions it means. Deciding that here rather than at run
            # time is what lets `check` tell the author which lines will need
            # the AI - and which will simply never work without it.
            if not _ai_looks_like_call(line):
                block.append({'kind': 'prose', 'line': number, 'text': line})
                continue

            block.append(_ai_parse_call(number, line))
        except TCSError as e:
            errors.append(e)
        except Exception as e:                       # noqa: BLE001 - reported
            errors.append(TCSError(number, str(e)))

    if len(stack) > 1:
        errors.append(TCSError(openers[-1]['line'],
                                   "this block is never closed - add 'end'"))
    return {'triggers': triggers, 'body': root}, errors


def _ai_seconds(line_no, text):
    text = str(text).strip().lower().rstrip('.')
    number = ''
    for char in text:
        if char.isdigit() or char == '.':
            number += char
        else:
            break
    unit = text[len(number):].strip() or 's'
    if not number:
        raise TCSError(line_no, "'wait' wants a time, e.g. 'wait 2s'")
    if unit not in _AI_TIME_UNITS:
        raise TCSError(line_no, f"'{unit}' is not a time unit - use s, m "
                                    f"or h")
    return min(float(number) * _AI_TIME_UNITS[unit], 3600)


def _ai_rvalue(line_no, text):
    """A call, an expression or a literal - the right-hand side of set / if."""
    stripped = str(text).strip()
    if not stripped:
        raise TCSError(line_no, "something is missing here")
    if _ai_looks_like_call(stripped):
        return _ai_parse_call(line_no, stripped)
    if _ai_looks_like_expression(stripped):
        try:
            tokens = _ai_tokenise(stripped)
        except ValueError as e:
            raise TCSError(line_no, str(e))
        return {'kind': 'expr', 'line': line_no,
                'expr': _AIExpr(tokens, stripped)}
    return {'kind': 'value', 'line': line_no, 'value': _ai_literal(stripped)}


_AI_COMPARISONS = ('is not empty', 'is empty', 'is not', 'does not contain',
                   'contains', 'is at least', 'is at most',
                   'is more than', 'is less than', 'is', '>=', '<=', '!=',
                   '==', '>', '<', '=')


def _ai_parse_if(line_no, text):
    body = text.strip()
    lowered = body.lower()
    for operator in _AI_COMPARISONS:
        marker = f" {operator} "
        position = lowered.find(marker)
        if operator in ('is empty', 'is not empty') and lowered.endswith(
                f" {operator}"):
            return {'kind': 'if', 'line': line_no,
                    'left': _ai_rvalue(line_no, body[:len(body) - len(operator) - 1]),
                    'op': operator, 'right': {'kind': 'value', 'value': ''},
                    'then': [], 'else': None}
        if position > 0:
            return {'kind': 'if', 'line': line_no,
                    'left': _ai_rvalue(line_no, body[:position]),
                    'op': operator,
                    'right': _ai_rvalue(line_no, body[position + len(marker):]),
                    'then': [], 'else': None}
    raise TCSError(line_no, "an 'if' needs a comparison",
                       "use contains, does not contain, is, is not, is empty "
                       "or is not empty")


def _ai_arg_tail(line_no, text):
    """([value node, ...], {name: value node}) for the tail of a statement."""
    values = []
    named = {}
    for item in _ai_split_args(str(text).strip()):
        key, sep, value = item.partition('=')
        if sep and key.strip().replace('_', '').isalnum() \
                and not key.strip()[0].isdigit():
            named[key.strip().lower()] = _ai_rvalue(line_no, value)
        else:
            values.append(_ai_rvalue(line_no, item))
    return values, named


def _ai_parse_prompt(line_no, line):
    """ask / confirm / choose - a question, answered into a variable."""
    word, _sep, rest = line.partition(' ')
    word = word.lower()
    name, sep, tail = rest.partition('=')
    if not sep:
        raise TCSError(line_no, f"'{word}' wants a name to put the answer "
                                    f"in, e.g. {word} answer = \"...\"")
    variable = name.strip().lower()
    if not variable.replace('_', '').isalnum():
        raise TCSError(line_no, f"'{name.strip()}' is not a name a value "
                                    f"can be kept under")
    # 'options' is a list, so it is taken out before the rest is split as
    # ordinary arguments - otherwise its commas would look like separators.
    options = []
    lowered = tail.lower()
    marker = lowered.find(' options ')
    if marker >= 0:
        options = [_ai_rvalue(line_no, item)
                   for item in _ai_split_args(tail[marker + 9:])]
        tail = tail[:marker]
    values, named = _ai_arg_tail(line_no, tail)
    if not values and 'prompt' not in named:
        raise TCSError(line_no, f"'{word}' wants something to ask")
    if word == 'choose' and not options:
        raise TCSError(line_no, "'choose' wants options, e.g. "
                                    'choose x = "Which?" options "a", "b"')
    return {'kind': 'prompt', 'line': line_no, 'word': word, 'name': variable,
            'prompt': values[0] if values else named['prompt'],
            'title': named.get('title'), 'default': named.get('default'),
            'options': options}


def _ai_parse_field(line_no, line):
    """One control inside a `dialog` block."""
    word, _sep, rest = line.partition(' ')
    word = word.lower()
    name, sep, tail = rest.partition('=')
    if not sep:
        raise TCSError(line_no, f"'{word}' wants a name and a label, e.g. "
                                    f'{word} title = "Title"')
    variable = name.strip().lower()
    if not variable.replace('_', '').isalnum():
        raise TCSError(line_no, f"'{name.strip()}' is not a name a value "
                                    f"can be kept under")
    options = []
    lowered = tail.lower()
    marker = lowered.find(' options ')
    if marker >= 0:
        options = [_ai_rvalue(line_no, item)
                   for item in _ai_split_args(tail[marker + 9:])]
        tail = tail[:marker]
    values, named = _ai_arg_tail(line_no, tail)
    control = {'field': 'text', 'multiline': 'multiline',
               'choice': 'choice', 'check': 'check'}[word]
    if control == 'choice' and not options:
        raise TCSError(line_no, "'choice' wants options, e.g. "
                                    'choice kind = "Kind" options "a", "b"')
    return {'kind': 'field', 'line': line_no, 'control': control,
            'name': variable,
            'label': values[0] if values else named.get('label'),
            'default': named.get('default'), 'options': options}


def _ai_parse_trigger(line_no, text):
    body = text.strip()
    lowered = body.lower()
    if lowered in ('startup', 'start', 'titan starts'):
        return {'kind': 'startup', 'line': line_no}
    name, sep, value = body.partition('=')
    key = name.strip().lower()
    value = _ai_literal(value.strip()) if sep else ''
    if key == 'time' and sep:
        moment = str(value).strip()
        parts = moment.split(':')
        try:
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except (ValueError, IndexError):
            raise TCSError(line_no, f"'{moment}' is not a time of day - "
                                        f"write it as \"14:30\"")
        return {'kind': 'time', 'line': line_no, 'hour': hour, 'minute': minute}
    if key == 'every' and sep:
        return {'kind': 'every', 'line': line_no,
                'seconds': max(30.0, _ai_seconds(line_no, str(value)))}
    raise TCSError(line_no, f"'{body}' is not a trigger Titan knows",
                       'use when startup, when time = "14:30" or '
                       'when every = "15m"')


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #
class _AIStop(Exception):
    """The script said 'stop', or 'return' with something to hand back."""

    def __init__(self, value=None):
        super().__init__()
        self.value = value


def _ai_fill(value, variables):
    """Put {{name}} values into a string."""
    if not isinstance(value, str) or '{{' not in value:
        return value
    out = value
    for name, held in variables.items():
        out = out.replace('{{' + name + '}}', str(held))
    return out


def _ai_arguments(statement, spec, variables):
    """The keyword arguments for one call, positional ones mapped onto the
    action's declared parameters in the order it declared them."""
    args = {name: _ai_fill(value, variables)
            for name, value in statement['named'].items()}
    remaining = [p for p in spec.params.keys() if p not in args]
    for index, value in enumerate(statement['positional']):
        if index >= len(remaining):
            raise TCSError(statement['line'],
                               f"{statement['path']} takes "
                               f"{len(spec.params)} values, and got "
                               f"{len(statement['positional'])}")
        args[remaining[index]] = _ai_fill(value, variables)
    unknown = [name for name in args if name not in spec.params]
    if unknown and spec.params:
        raise TCSError(statement['line'],
                           f"{statement['path']} has no "
                           f"{'values' if len(unknown) > 1 else 'value'} called "
                           + ", ".join(unknown)
                           + ". It takes: " + ", ".join(spec.params) + ".")
    return args


def _ai_call(statement, variables, transcript):
    from src.titan_core import actions

    try:
        addon_id, action_name, spec = _ai_resolve(statement['path'])
    except ValueError as e:
        raise TCSError(statement['line'], str(e))
    args = _ai_arguments(statement, spec, variables)
    result = actions.run(addon_id, action_name, **args)
    text = str(result.text or '')
    transcript.append(f"{addon_id}.{action_name}: {text}"
                      if text else f"{addon_id}.{action_name}: done")
    if not result.ok:
        raise TCSError(statement['line'],
                           f"{addon_id}.{action_name} could not run", text)
    return text


# --------------------------------------------------------------------------- #
# Windows: message boxes, prompts, and whole dialogs
# --------------------------------------------------------------------------- #
# A macro that can only act *at* the user is half a macro. These put a real wx
# window on screen - the same accessible controls as anywhere else in Titan -
# and put what the user typed into ordinary variables.
#
# Every one of them runs on the GUI thread and blocks the macro's own thread
# until the user answers: wx is not thread-safe, and a macro that carried on
# past a question it had asked would be asking nothing.

class _AICancelled(Exception):
    """The user closed a dialog the macro was waiting on."""


def _tcs_say(text, wait=False, interrupt=False):
    """Speak, through whatever Titan itself is actually speaking with.

    `say` must be the same thing as `titan.speak`, not a second voice with its
    own idea of the settings: Titan TTS when the user has it on - the *live*
    engine, with their engine, voice, rate and pitch - and the screen reader
    otherwise. The action is asked first precisely so there is one answer to
    "what does Titan sound like".

    ``wait`` matters because a script is a sequence: without it, three lines of
    speech and a sound all start at once. Titan's engine already has a
    synchronous ``speak`` and an asynchronous one, so waiting is real waiting,
    not a guess at how long a sentence takes.
    """
    message = str(text)
    if interrupt:
        try:
            from src.titan_core.stereo_speech import get_stereo_speech
            speech = get_stereo_speech()
            if speech is not None:
                speech.stop()
        except Exception:
            pass
    if wait:
        try:
            from src.titan_core.stereo_speech import get_stereo_speech
            speech = get_stereo_speech()
            if speech is not None:
                speech.speak(message)          # blocks until it has finished
                return
        except Exception:
            pass
    try:
        from src.titan_core import actions
        result = actions.run('titan', 'speak', text=message,
                             interrupt=bool(interrupt))
        if result.ok:
            return
    except Exception:
        pass
    _speak(message)


def _tcs_parent():
    """The window a script's dialog belongs to.

    A dialog with no parent outlives Titan: it stays on screen after the main
    window has gone, and Alt+Tab treats it as a program of its own. Parenting it
    to Titan means Windows closes it when Titan closes.
    """
    wx = _get_wx()
    if wx is None:
        return None
    try:
        app = wx.GetApp()
        if app is None:
            return None
        top = app.GetTopWindow()
        if top is not None and top:
            return top
        windows = [w for w in wx.GetTopLevelWindows() if w]
        return windows[0] if windows else None
    except Exception:
        return None


def _ai_on_gui(function, timeout=600):
    """Run something on the wx main thread and wait for it."""
    wx = _get_wx()
    if wx is None:
        raise ValueError("this needs Titan's windows, which are not running")
    if wx.IsMainThread():
        return function()
    box = {}
    done = threading.Event()

    def call():
        try:
            box['value'] = function()
        except Exception as e:                       # noqa: BLE001 - relayed
            box['error'] = e
        finally:
            done.set()

    wx.CallAfter(call)
    if not done.wait(timeout):
        raise ValueError("the window was left open too long")
    if 'error' in box:
        raise box['error']
    return box.get('value')


def _ai_message(text, title='', level='info'):
    wx = _get_wx()
    icons = {'info': wx.ICON_INFORMATION, 'warning': wx.ICON_WARNING,
             'error': wx.ICON_ERROR, 'question': wx.ICON_QUESTION}

    def show():
        dialog = wx.MessageDialog(_tcs_parent(), str(text),
                                  str(title or _("Macro")),
                                  wx.OK | icons.get(level, wx.ICON_INFORMATION))
        dialog.ShowModal()
        dialog.Destroy()
        return ''
    return _ai_on_gui(show)


def _ai_confirm(question, title=''):
    wx = _get_wx()

    def show():
        dialog = wx.MessageDialog(_tcs_parent(), str(question),
                                  str(title or _("Macro")),
                                  wx.YES_NO | wx.ICON_QUESTION)
        answer = dialog.ShowModal()
        dialog.Destroy()
        return answer == wx.ID_YES
    return _ai_on_gui(show)


def _ai_ask(prompt, title='', default=''):
    wx = _get_wx()

    def show():
        dialog = wx.TextEntryDialog(_tcs_parent(), str(prompt),
                                    str(title or _("Macro")),
                                    str(default or ''))
        answer = dialog.ShowModal()
        value = dialog.GetValue()
        dialog.Destroy()
        if answer != wx.ID_OK:
            raise _AICancelled()
        return value
    return _ai_on_gui(show)


def _ai_choose(prompt, options, title=''):
    wx = _get_wx()
    choices = [str(o) for o in options if str(o).strip()]
    if not choices:
        raise ValueError("a choice needs something to choose from")

    def show():
        dialog = wx.SingleChoiceDialog(_tcs_parent(), str(prompt),
                                       str(title or _("Macro")), choices)
        answer = dialog.ShowModal()
        value = dialog.GetStringSelection()
        dialog.Destroy()
        if answer != wx.ID_OK:
            raise _AICancelled()
        return value
    return _ai_on_gui(show)


def _ai_form(title, fields):
    """A whole dialog: several controls at once, answered into variables.

    Built by hand rather than from a layout file because a macro's form is
    described in the macro, and the controls are the ordinary wx ones so the
    screen reader treats them like every other Titan dialog.
    """
    wx = _get_wx()

    def show():
        dialog = wx.Dialog(_tcs_parent(), title=str(title or _("Macro")))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)
        controls = []
        for field in fields:
            label = str(field.get('label') or field['name'])
            kind = field.get('control', 'text')
            if kind == 'check':
                control = wx.CheckBox(panel, label=label)
                control.SetValue(bool(field.get('default')))
                sizer.Add(control, 0, wx.ALL, 6)
            elif kind == 'choice':
                sizer.Add(wx.StaticText(panel, label=label), 0,
                          wx.LEFT | wx.TOP, 6)
                control = wx.Choice(panel, choices=[str(o) for o in
                                                    field.get('options', [])])
                if control.GetCount():
                    control.SetSelection(0)
                sizer.Add(control, 0, wx.ALL | wx.EXPAND, 6)
            else:
                sizer.Add(wx.StaticText(panel, label=label), 0,
                          wx.LEFT | wx.TOP, 6)
                style = wx.TE_MULTILINE if kind == 'multiline' else 0
                control = wx.TextCtrl(panel, value=str(field.get('default', '')),
                                      style=style)
                sizer.Add(control, 1 if style else 0, wx.ALL | wx.EXPAND, 6)
            control.Bind(wx.EVT_SET_FOCUS, lambda e: (_play_focus(), e.Skip()))
            controls.append((field, control))

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        # The buttons belong to the DIALOG, so they go in the dialog's sizer.
        # Adding them to the panel's sizer instead is what wx refuses: a sizer
        # can only position windows whose parent is the window it manages.
        buttons = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
        if buttons:
            outer.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        dialog.SetSizer(outer)
        dialog.SetSize((460, min(520, 160 + 70 * len(fields))))
        dialog.Layout()
        dialog.CenterOnScreen()
        if controls:
            controls[0][1].SetFocus()
        answer = dialog.ShowModal()
        values = {}
        for field, control in controls:
            kind = field.get('control', 'text')
            if kind == 'check':
                values[field['name']] = control.GetValue()
            elif kind == 'choice':
                values[field['name']] = control.GetStringSelection()
            else:
                values[field['name']] = control.GetValue()
        dialog.Destroy()
        if answer != wx.ID_OK:
            raise _AICancelled()
        return values
    return _ai_on_gui(show)


# --------------------------------------------------------------------------- #
# Pseudocode: a line of plain language, turned into actions by the AI
# --------------------------------------------------------------------------- #
# The language above is the whole macro when AI features are off - it is Titan
# actions and conditions, and needs nothing else. With them on, a line may also
# just say what it wants in words, and the AI turns it into the same action
# calls the author could have written by hand.
#
# It is a *translation*, not an agent: the model is asked for a list of steps
# and those steps are run through the ordinary sequence runner, so a
# pseudocode line can do exactly what a written line can do and nothing more.
# The translation is cached for the run, so a line inside 'repeat 10' costs one
# request, not ten.

_AI_PROSE_SYSTEM = (
    "You translate one line of a user's Titan macro into the Titan actions "
    "that carry it out. Titan is an accessible desktop environment; the "
    "actions its add-ons offer are listed below.\n\n"
    "Answer with a JSON array of steps and nothing else. Each step is "
    '{\"addon\": \"<id>\", \"action\": \"<name>\", \"args\": {...}}. Use '
    "{{1}}, {{2}} in a later step's string argument to mean what step 1 or 2 "
    "returned. Use only actions from the list, with the argument names they "
    "declare. If the line cannot be done with these actions, answer with an "
    "empty array [].")


def _ai_features_on():
    try:
        from src.settings.settings import get_setting
        return str(get_setting('enabled', '0', section='ai')).strip() == '1'
    except Exception:
        return False


def _ai_action_catalogue():
    from src.titan_core import actions
    lines = []
    for addon in actions.get_registry().addons:
        for action in addon.actions:
            lines.append(action.describe())
    return "\n".join(lines)


def _ai_prose_steps(text, cache):
    """[step, ...] for a line of pseudocode. Raises TCSError when it cannot."""
    key = text.strip().lower()
    if key in cache:
        return cache[key]
    from src.ai import ai_provider
    system = _AI_PROSE_SYSTEM + "\n\nActions available:\n" + _ai_action_catalogue()
    answer = ai_provider.generate(system, f"Macro line: {text}", max_tokens=1200)
    try:
        steps = json.loads(str(answer).strip())
    except Exception:
        raise ValueError(f"the AI did not answer with steps ({str(answer)[:120]})")
    if not isinstance(steps, list):
        raise ValueError("the AI did not answer with a list of steps")
    cleaned = []
    for step in steps:
        if not isinstance(step, dict) or not step.get('addon') or not step.get('action'):
            continue
        args = step.get('args')
        cleaned.append({'addon': str(step['addon']), 'action': str(step['action']),
                        'args': args if isinstance(args, dict) else {}})
    cache[key] = cleaned
    return cleaned


def _ai_run_prose(statement, variables, transcript, cache):
    from src.titan_core import actions

    text = _ai_fill(statement['text'], variables)
    if not _ai_features_on():
        raise TCSError(statement['line'],
                           f"'{text}' is written in words, not as an action",
                           "Pseudocode lines need AI features switched on "
                           "(Settings, AI features). Write it as "
                           "add-on.action instead to run it without them.")
    try:
        steps = _ai_prose_steps(text, cache)
    except Exception as e:                           # noqa: BLE001 - reported
        raise TCSError(statement['line'], f"'{text}' could not be worked "
                                              f"out: {e}")
    if not steps:
        raise TCSError(statement['line'],
                           f"'{text}' does not match anything Titan can do")
    outcome = actions.run_sequence(steps)
    transcript.append(f"do {text}: " + str(outcome.text or '').replace('\n', ' / '))
    if outcome.pending:
        raise TCSError(statement['line'],
                           f"'{text}' needs an answer, and a macro cannot ask",
                           str(outcome.question.as_text()
                               if outcome.question else ''))
    if not outcome.ok:
        raise TCSError(statement['line'], f"'{text}' did not finish",
                           str(outcome.text or ''))
    return str(outcome.text or '')


def _ai_value_of(node, variables, transcript):
    kind = node.get('kind')
    if kind == 'call':
        return _ai_call(node, variables, transcript)
    if kind == 'expr':
        try:
            return node['expr'].evaluate(variables)
        except ValueError as e:
            raise TCSError(node.get('line', 0), str(e))
    return _ai_fill(node.get('value', ''), variables)


# --------------------------------------------------------------------------- #
# The voice a script speaks in
# --------------------------------------------------------------------------- #
# By default a script speaks in the user's own voice - Titan's live engine with
# the engine, voice, rate and pitch they configured. A script may borrow a
# different one, and "borrow" is the whole point: it is applied to the live
# engine and NEVER written to the settings file, and it is put back when the
# script ends however it ends - finished, stopped, cancelled or broken. A macro
# that could leave the user's screen reader in some other voice would be a
# macro nobody could afford to run.

def _tcs_speech():
    from src.titan_core.stereo_speech import get_stereo_speech
    return get_stereo_speech()


def _tcs_voice_remember(budget):
    """Capture the voice Titan is speaking in, once per run."""
    if 'voice_saved' in budget:
        return
    saved = {}
    try:
        speech = _tcs_speech()
        if speech is not None:
            saved['engine'] = speech.get_engine()
            saved['voice'] = getattr(speech, 'voice', None)
    except Exception:
        pass
    # rate/pitch/volume are held on the engine in its own units, so they are
    # put back from the user's settings rather than guessed at.
    try:
        from src.settings.settings import get_setting
        for key in ('rate', 'pitch', 'volume'):
            saved[key] = get_setting(key, '', section='stereo_speech')
    except Exception:
        pass
    budget['voice_saved'] = saved


def _tcs_voice_restore(budget):
    """Put the user's own voice back."""
    saved = budget.pop('voice_saved', None)
    if not saved:
        return
    try:
        speech = _tcs_speech()
        if speech is None:
            return
        if saved.get('engine'):
            speech.set_engine(saved['engine'])
        for key, setter in (('rate', 'set_rate'), ('pitch', 'set_pitch'),
                            ('volume', 'set_volume')):
            value = saved.get(key)
            if value not in (None, ''):
                try:
                    getattr(speech, setter)(int(value))
                except (TypeError, ValueError, AttributeError):
                    pass
        name = saved.get('voice')
        if name:
            _tcs_set_voice_by_name(speech, name)
    except Exception as e:
        print(f"[tcs] could not put the voice back: {e}")


def _tcs_set_voice_by_name(speech, name):
    """Select a voice on the live engine by its name. True when it matched."""
    wanted = str(name or '').strip().lower()
    if not wanted:
        return False
    try:
        voices = speech.get_available_voices() or []
    except Exception:
        return False
    for index, voice in enumerate(voices):
        label = (voice.get('display_name') or voice.get('name')
                 or voice.get('id') or '') if isinstance(voice, dict) else str(voice)
        identifier = (voice.get('id') or '') if isinstance(voice, dict) else str(voice)
        if wanted in (str(label).lower(), str(identifier).lower()):
            speech.set_voice(index)
            return True
    for index, voice in enumerate(voices):
        label = (voice.get('display_name') or voice.get('name')
                 or voice.get('id') or '') if isinstance(voice, dict) else str(voice)
        if wanted in str(label).lower():
            speech.set_voice(index)
            return True
    return False


def _tcs_voice(statement, variables, transcript, budget):
    """`voice engine="supertonic" name="Nova" rate=2` - for this script only."""
    speech = _tcs_speech()
    if speech is None:
        raise TCSError(statement['line'],
                       "Titan's speech engine is not running")
    if statement.get('reset'):
        _tcs_voice_restore(budget)
        transcript.append("voice: back to the user's own")
        return ''
    _tcs_voice_remember(budget)
    changed = []
    engine = statement.get('engine')
    if engine is not None:
        wanted = str(_ai_value_of(engine, variables, transcript)).strip()
        try:
            speech.set_engine(wanted)
        except Exception as e:
            raise TCSError(statement['line'],
                           f"could not speak with '{wanted}': {e}")
        if str(speech.get_engine()).lower() != wanted.lower():
            raise TCSError(statement['line'],
                           f"'{wanted}' is not an engine Titan can speak with "
                           f"here", "Run titan.list_tts_engines to see them.")
        changed.append(f"engine {wanted}")
    name = statement.get('name')
    if name is not None:
        wanted = str(_ai_value_of(name, variables, transcript)).strip()
        if not _tcs_set_voice_by_name(speech, wanted):
            raise TCSError(statement['line'],
                           f"this engine has no voice called '{wanted}'")
        changed.append(f"voice {wanted}")
    for key, setter in (('rate', 'set_rate'), ('pitch', 'set_pitch'),
                        ('volume', 'set_volume')):
        node = statement.get(key)
        if node is None:
            continue
        value = _ai_number(_ai_value_of(node, variables, transcript))
        try:
            getattr(speech, setter)(int(value))
        except Exception as e:
            raise TCSError(statement['line'], f"could not set the {key}: {e}")
        changed.append(f"{key} {int(value)}")
    transcript.append("voice: " + (", ".join(changed) or "nothing changed")
                      + " (for this script only)")
    return ''


def _tcs_beside(budget, name):
    """A file named by a script, found next to that script.

    A macro is a folder, and the sounds and helper scripts an author ships with
    it live in that folder. Writing an absolute path would mean the macro only
    worked on the machine it was written on - so a bare name is looked for
    beside the script first, and only then taken as a path in its own right.
    """
    target = str(name or '').strip().strip('"')
    if not target:
        return ''
    expanded = os.path.expandvars(os.path.expanduser(target))
    base = budget.get('dir') or ''
    if base and not os.path.isabs(expanded):
        beside = os.path.join(base, expanded)
        if os.path.isfile(beside):
            return os.path.abspath(beside)
    return os.path.abspath(expanded)


def _tcs_play(statement, variables, transcript, budget):
    """`play "ding.ogg"` - a sound the script ships with itself."""
    from src.titan_core import actions

    name = _ai_value_of(statement['file'], variables, transcript)
    path = _tcs_beside(budget, name)
    if not path or not os.path.isfile(path):
        raise TCSError(statement['line'],
                       f"there is no sound file called '{name}'",
                       "A bare name is looked for next to the script itself.")
    args = {'path': path}
    if statement.get('position') is not None:
        args['position'] = _ai_value_of(statement['position'], variables,
                                        transcript)
    if statement.get('wait') is not None:
        args['wait'] = _ai_value_of(statement['wait'], variables, transcript)
    result = actions.run('titan', 'play_sound', **args)
    transcript.append(f"play {os.path.basename(path)}: {result.text}")
    if not result.ok:
        raise TCSError(statement['line'], str(result.text))
    return str(result.text or '')


def _tcs_run_script(statement, variables, transcript, budget):
    """`run "helper.tcs"` - another script, normally one beside this one.

    The called script gets its own variables: a script is a piece of behaviour,
    not a shared pile of state, and two scripts that happened to use `x` for
    different things should not corrupt each other. What comes back is its last
    value, so the caller can use it.
    """
    name = _ai_value_of(statement['script'], variables, transcript)
    path = _tcs_beside(budget, name)
    if not path.lower().endswith(TCS_EXT):
        path += TCS_EXT
    if not os.path.isfile(path):
        raise TCSError(statement['line'],
                       f"there is no script called '{name}'",
                       "A bare name is looked for next to the script itself.")
    key = os.path.normcase(path)
    chain = budget.setdefault('chain', [])
    if key in chain:
        raise TCSError(statement['line'],
                       f"'{os.path.basename(path)}' is already running - a "
                       f"script cannot call itself round in a circle")
    if len(chain) >= 8:
        raise TCSError(statement['line'],
                       "scripts are calling each other too many levels deep")
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            text = handle.read()
    except OSError as e:
        raise TCSError(statement['line'],
                       f"could not read {os.path.basename(path)}: {e}")
    transcript.append(f"run {os.path.basename(path)}")
    inner = dict(budget)
    inner['dir'] = os.path.dirname(path)
    inner['chain'] = chain + [key]
    program, errors = _ai_parse(text)
    if errors:
        raise TCSError(statement['line'],
                       f"{os.path.basename(path)} would not run",
                       "; ".join(e.describe() for e in errors[:4]))
    scope = {}
    returned = None
    try:
        try:
            _ai_execute(program['body'], scope, transcript, inner)
        except _AIStop as stop:
            # 'return x' says what the helper hands back; 'stop' says nothing,
            # and then the caller reads its last result as before.
            returned = stop.value
    finally:
        # A called script's borrowed voice ends with the called script - it has
        # its own copy of the run state, so the caller's finally cannot see it.
        _tcs_voice_restore(inner)
        # The step budget is shared, so a called script cannot buy its caller
        # more room by starting over.
        budget['steps'] = inner['steps']
    return str(returned if returned is not None else scope.get('last', ''))


def _ai_prompt(statement, variables, transcript):
    """ask / confirm / choose, answered into a variable."""
    prompt = _ai_value_of(statement['prompt'], variables, transcript)
    title = (_ai_value_of(statement['title'], variables, transcript)
             if statement.get('title') else '')
    word = statement['word']
    try:
        if word == 'confirm':
            answer = _ai_confirm(prompt, title)
        elif word == 'choose':
            options = [_ai_value_of(o, variables, transcript)
                       for o in statement['options']]
            answer = _ai_choose(prompt, options, title)
        else:
            default = (_ai_value_of(statement['default'], variables, transcript)
                       if statement.get('default') else '')
            answer = _ai_ask(prompt, title, default)
    except _AICancelled:
        # Closing the question ends the macro. Carrying on with an empty answer
        # would be doing something the user just declined to authorise.
        raise _AIStop()
    except ValueError as e:
        raise TCSError(statement['line'], str(e))
    transcript.append(f"{word} {statement['name']}: {answer}")
    return answer


def _ai_dialog(statement, variables, transcript):
    """A whole form, answered into one variable per control."""
    title = _ai_fill(statement.get('title', ''), variables)
    fields = []
    for field in statement['fields']:
        if field.get('kind') != 'field':
            continue
        fields.append({
            'name': field['name'],
            'control': field['control'],
            'label': (_ai_value_of(field['label'], variables, transcript)
                      if field.get('label') else field['name']),
            'default': (_ai_value_of(field['default'], variables, transcript)
                        if field.get('default') else ''),
            'options': [_ai_value_of(o, variables, transcript)
                        for o in field.get('options', [])],
        })
    if not fields:
        raise TCSError(statement['line'],
                           "this dialog has no controls in it")
    try:
        values = _ai_form(title, fields)
    except _AICancelled:
        raise _AIStop()
    except ValueError as e:
        raise TCSError(statement['line'], str(e))
    transcript.append("dialog: " + ", ".join(f"{k}={v}"
                                             for k, v in values.items()))
    return values


_AI_NUMERIC_OPS = {
    'is more than': lambda a, b: a > b, '>': lambda a, b: a > b,
    'is less than': lambda a, b: a < b, '<': lambda a, b: a < b,
    'is at least': lambda a, b: a >= b, '>=': lambda a, b: a >= b,
    'is at most': lambda a, b: a <= b, '<=': lambda a, b: a <= b,
}


def _ai_compare(left, operator, right):
    if operator in _AI_NUMERIC_OPS:
        return _AI_NUMERIC_OPS[operator](_ai_number(left), _ai_number(right))
    a, b = str(left if left is not None else ''), str(right if right is not None else '')
    if operator == 'is empty':
        return not a.strip()
    if operator == 'is not empty':
        return bool(a.strip())
    if operator == 'contains':
        return b.lower() in a.lower()
    if operator == 'does not contain':
        return b.lower() not in a.lower()
    if operator in ('is not', '!='):
        return a.strip().lower() != b.strip().lower()
    # 'is', '=', '==' - equality. Numbers compare as numbers, so 3 and "3.0"
    # are the same thing, which is what somebody writing a macro expects.
    if _ai_is_numeric(a) and _ai_is_numeric(b):
        return _ai_number(a) == _ai_number(b)
    return a.strip().lower() == b.strip().lower()


def _ai_truth(value):
    """Whether a script value means yes. Booleans, words and numbers alike."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on', 'tak')


def _ai_is_numeric(text):
    try:
        float(str(text).strip())
        return True
    except ValueError:
        return False


def _ai_execute(body, variables, transcript, budget):
    for statement in body:
        if budget['steps'] <= 0:
            raise TCSError(statement.get('line', 0),
                               "this macro ran too many steps and was stopped")
        budget['steps'] -= 1
        kind = statement['kind']
        if kind == 'call':
            variables['last'] = _ai_call(statement, variables, transcript)
        elif kind == 'prose':
            variables['last'] = _ai_run_prose(statement, variables, transcript,
                                              budget['prose'])
        elif kind == 'set':
            variables[statement['name']] = _ai_value_of(
                statement['value'], variables, transcript)
        elif kind == 'say':
            spoken = _ai_value_of(statement['text'], variables, transcript)
            wait = (_ai_truth(_ai_value_of(statement['wait'], variables,
                                           transcript))
                    if statement.get('wait') is not None else False)
            interrupt = (_ai_truth(_ai_value_of(statement['interrupt'],
                                                variables, transcript))
                         if statement.get('interrupt') is not None else False)
            _tcs_say(str(spoken), wait=wait, interrupt=interrupt)
            transcript.append(f"say: {spoken}")
        elif kind == 'return':
            raise _AIStop(_ai_value_of(statement['value'], variables,
                                       transcript)
                          if statement.get('value') else
                          variables.get('last', ''))
        elif kind == 'message':
            text = _ai_value_of(statement['text'], variables, transcript)
            title = (_ai_value_of(statement['title'], variables, transcript)
                     if statement.get('title') else '')
            _ai_message(text, title, statement['level'])
            transcript.append(f"message: {text}")
        elif kind == 'prompt':
            variables[statement['name']] = _ai_prompt(statement, variables,
                                                      transcript)
        elif kind == 'dialog':
            for name, value in _ai_dialog(statement, variables,
                                          transcript).items():
                variables[name] = value
        elif kind == 'wait':
            _time.sleep(statement['seconds'])
        elif kind == 'play':
            variables['last'] = _tcs_play(statement, variables, transcript,
                                          budget)
        elif kind == 'run':
            variables['last'] = _tcs_run_script(statement, variables,
                                                transcript, budget)
        elif kind == 'voice':
            _tcs_voice(statement, variables, transcript, budget)
        elif kind == 'stop':
            raise _AIStop()
        elif kind == 'repeat':
            for _index in range(statement['count']):
                _ai_execute(statement['body'], variables, transcript, budget)
        elif kind == 'if':
            left = _ai_value_of(statement['left'], variables, transcript)
            right = _ai_value_of(statement['right'], variables, transcript)
            if _ai_compare(left, statement['op'], right):
                _ai_execute(statement['then'], variables, transcript, budget)
            elif statement.get('else'):
                _ai_execute(statement['else'], variables, transcript, budget)


def check_tcs(text, base_dir=''):
    """[problem, ...] - everything wrong with a script, without running it.

    Resolution is checked here too, so 'titan.plya.locally' is caught when the
    script is written rather than halfway through it at a quarter to twelve.
    Given ``base_dir``, the sounds and helper scripts it names are checked as
    well.
    """
    program, errors = _ai_parse(text)
    problems = [e.describe() for e in errors]
    ai_on = _ai_features_on()

    def walk(body):
        for statement in body:
            if statement['kind'] == 'call':
                try:
                    _addon, _name, spec = _ai_resolve(statement['path'])
                except ValueError as e:
                    problems.append(f"line {statement['line']}: {e}")
                    continue
                except Exception:
                    continue
                # The values, too: an action given a name it does not take, or
                # three values when it takes one, is a mistake worth catching
                # now rather than at a quarter to twelve.
                try:
                    _ai_arguments(statement, spec, {})
                except TCSError as e:
                    problems.append(e.describe())
                missing = [name for name, param in spec.params.items()
                           if param.get('required')
                           and name not in statement['named']
                           and list(spec.params).index(name) >= len(statement['positional'])]
                if missing:
                    problems.append(f"line {statement['line']}: "
                                    f"{statement['path']} needs "
                                    + ", ".join(missing))
            elif statement['kind'] == 'prose' and not ai_on:
                problems.append(
                    f"line {statement['line']}: '{statement['text']}' is "
                    f"written in words, and pseudocode needs AI features "
                    f"switched on. Write it as add-on.action to run it "
                    f"without them.")
            elif statement['kind'] == 'set':
                walk([statement['value']])
            elif statement['kind'] == 'repeat':
                walk(statement['body'])
            elif statement['kind'] == 'if':
                walk([statement['left'], statement['right']])
                walk(statement['then'])
                walk(statement.get('else') or [])
            elif statement['kind'] == 'dialog':
                walk(statement['fields'])
            elif statement['kind'] == 'prompt':
                walk([statement['prompt']] + list(statement.get('options') or []))
            elif statement['kind'] in ('message', 'say'):
                walk([statement['text']])
            elif statement['kind'] == 'return' and statement.get('value'):
                walk([statement['value']])
            elif statement['kind'] == 'voice':
                walk([node for key, node in statement.items()
                      if isinstance(node, dict) and node.get('kind')])
            elif statement['kind'] in ('play', 'run'):
                node = statement.get('file') or statement.get('script')
                walk([node])
                # A file named literally can be checked now; one built from a
                # variable can only be checked when it is known.
                if node.get('kind') == 'value' and base_dir:
                    name = str(node.get('value', ''))
                    target = _tcs_beside({'dir': base_dir}, name)
                    if statement['kind'] == 'run' and not target.lower().endswith(TCS_EXT):
                        target += TCS_EXT
                    if name and not os.path.isfile(target):
                        problems.append(
                            f"line {statement['line']}: there is no "
                            f"{'script' if statement['kind'] == 'run' else 'sound file'}"
                            f" called '{name}' next to this one")
    try:
        walk(program['body'])
    except Exception as e:
        problems.append(str(e))
    return problems


def run_tcs_text(text, announce=True, base_dir=''):
    """(ok, transcript). Runs a script that is already in memory.

    ``base_dir`` is the folder the script came from: the sounds and helper
    scripts it names by bare filename are looked for there.
    """
    program, errors = _ai_parse(text)
    if errors:
        return False, [e.describe() for e in errors]
    transcript = []
    variables = {}
    # 'prose' is the per-run translation cache: a pseudocode line inside a
    # repeat costs one request, not one per turn of the loop. 'chain' is the
    # scripts already running, so they cannot call each other in a circle.
    budget = {'steps': 2000, 'prose': {}, 'dir': base_dir, 'chain': []}
    try:
        try:
            _ai_execute(program['body'], variables, transcript, budget)
        except _AIStop:
            transcript.append("stopped")
        except TCSError as e:
            transcript.append(e.describe())
            if announce:
                _speak(_("Macro problem: {}").format(e.message))
                _play_error()
            return False, transcript
        except Exception as e:                       # noqa: BLE001 - reported
            transcript.append(f"{type(e).__name__}: {e}")
            if announce:
                _speak(_("Error running macro: {}").format(str(e)))
                _play_error()
            return False, transcript
        return True, transcript
    finally:
        # Whatever happened - finished, stopped, cancelled, crashed - the
        # user's own voice comes back. A borrowed engine that outlived the
        # script would leave them listening to somebody else's choice.
        _tcs_voice_restore(budget)


def run_tcs(script_path):
    """Run a .tcs file on its own thread, as the other kinds do."""
    try:
        with open(script_path, 'r', encoding='utf-8') as handle:
            text = handle.read()
    except Exception as e:
        _speak(_("Error running macro: {}").format(str(e)))
        _play_error()
        return

    def _run():
        _play_sound('macro/macro_start.ogg')
        ok, transcript = run_tcs_text(
            text, base_dir=os.path.dirname(os.path.abspath(script_path)))
        for line in transcript:
            print(f"[tcs] {line}")
        if ok:
            _play_sound('macro/macro_end.ogg')

    threading.Thread(target=_run, daemon=True).start()


TCS_TEMPLATE = """# A Titan Script (.TCS): a script made of Titan's own actions.
#
# Every action any add-on offers can be called here by name. Run
# macros.macro_actions (or ask the assistant) to see what is available.
#
#   titan.speak "hello"             an action, with one value
#   titan.play_media title="..."    the same, naming the value
#   set x = zegarynka.get_settings  keep what it answered
#   set greeting = "Hello, " + name upper(), lower(), now(), + - * /
#   if x contains "on"              contains, is, is more than, is empty...
#       say "The chime is on"
#   end
#   repeat 3
#       wait 2s
#   end
#
# It can ask, and show windows:
#   ask who = "What is your name?"
#   confirm sure = "Go ahead?"
#   choose kind = "Which?" options "one", "two"
#   message "Done, {{who}}."
#   dialog "Add a note"
#       field title = "Title"
#       multiline body = "Text"
#       check urgent = "Urgent?"
#   end
#
# Uncomment a trigger to have Titan run this by itself:
# when startup
# when time = "11:45"
# when every = "15m"

titan.speak "This script works."
"""


# --------------------------------------------------------------------------- #
# Triggers
# --------------------------------------------------------------------------- #
class TCSScheduler(threading.Thread):
    """Fires the macros that asked to run by themselves.

    One thread for every trigger of every macro, checked on a slow tick: a
    macro that wants to run at 11:45 does not need a timer accurate to the
    second, and a thread per macro would be a thread per macro.
    """

    TICK = 20.0

    def __init__(self, macro_manager):
        super().__init__(daemon=True)
        self.macro_manager = macro_manager
        self._running = False
        self._fired_today = set()       # (folder, 'HH:MM') fired on _day
        self._day = None
        self._last_every = {}           # folder -> monotonic seconds
        self._started_at = 0.0

    def stop(self):
        self._running = False

    def _macros(self):
        for macro in list(self.macro_manager.macros):
            if macro.get('type') != TCS_EXT:
                continue
            path = macro.get('script_path', '')
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    text = handle.read()
            except OSError:
                continue
            program, errors = _ai_parse(text)
            if errors or not program['triggers']:
                continue
            yield macro, text, program['triggers']

    def _fire(self, macro, text):
        print(f"[tcs] trigger fired: {macro.get('name')}")
        run_tcs_text(text, base_dir=macro.get('folder_path', ''))

    def run(self):
        self._running = True
        self._started_at = _time.monotonic()
        startup_done = False
        while self._running:
            try:
                now = _time.localtime()
                today = (now.tm_year, now.tm_yday)
                if today != self._day:
                    self._day = today
                    self._fired_today.clear()
                elapsed = _time.monotonic()
                for macro, text, triggers in self._macros():
                    folder = macro.get('folder_name', '')
                    for trigger in triggers:
                        if trigger['kind'] == 'startup':
                            if not startup_done:
                                self._fire(macro, text)
                        elif trigger['kind'] == 'time':
                            key = (folder, trigger['hour'], trigger['minute'])
                            if (now.tm_hour == trigger['hour']
                                    and now.tm_min == trigger['minute']
                                    and key not in self._fired_today):
                                self._fired_today.add(key)
                                self._fire(macro, text)
                        elif trigger['kind'] == 'every':
                            last = self._last_every.get(folder, self._started_at)
                            if elapsed - last >= trigger['seconds']:
                                self._last_every[folder] = elapsed
                                self._fire(macro, text)
                startup_done = True
            except Exception as e:                   # noqa: BLE001 - logged
                print(f"[tcs] scheduler: {e}")
            for _tick in range(int(self.TICK)):
                if not self._running:
                    return
                _time.sleep(1)


_tcs_scheduler = None


def _action_manager():
    """A MacroManager with the current macros loaded."""
    manager = MacroManager(MACROS_DIR, USER_MACROS_DIR)
    manager.load_macros()
    return manager


def action_list_macros():
    """List the macros the user has."""
    manager = _action_manager()
    if not manager.macros:
        return "There are no macros yet."
    lines = []
    for macro in manager.macros:
        hotkey = macro.get('hotkey') or ''
        lines.append(f"- {macro.get('name', '?')}"
                     + (f" ({hotkey})" if hotkey else '')
                     + f" [{macro.get('type', '?')}]")
    return f"{len(manager.macros)} macros:\n" + "\n".join(lines)


def action_run_macro(name):
    """Run one of the user's macros by name."""
    manager = _action_manager()
    if not manager.macros:
        return fails("There are no macros to run.")
    macro = manager.find_by_name(name)
    if macro is None:
        wanted = str(name or '').strip().lower()
        matches = [m for m in manager.macros
                   if wanted and wanted in str(m.get('name', '')).lower()]
        if len(matches) == 1:
            macro = matches[0]
        elif len(matches) > 1:
            return needs('name', f"'{name}' matches {len(matches)} macros. "
                         f"Which one should run?",
                         options=[m.get('name', '?') for m in matches[:8]])
        else:
            return needs('name', f"There is no macro called '{name}'. Which "
                         f"macro should run?",
                         options=[m.get('name', '?')
                                  for m in manager.macros[:12]])
    run_macro(macro)
    return f"Running the macro '{macro.get('name')}'."


# --------------------------------------------------------------------------- #
# Making a macro
# --------------------------------------------------------------------------- #
# "Write me a macro that does X" has to end with a macro *in the macro manager*
# - listed, editable, deletable, with a shortcut - not a script file dropped
# somewhere on the disk. So creating one goes through MacroManager exactly as
# the Configure dialog does, and the writing of the file is here rather than in
# the caller: nothing outside this component should have to know what a .macro
# file looks like.

# Special keys the user names, as Windows virtual-key codes. Ordinary
# characters are looked up with VkKeyScanW at build time, so a key that depends
# on the user's keyboard layout is still the right key.
_VK_NAMES = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'return': 0x0D,
    'shift': 0x10, 'ctrl': 0x11, 'control': 0x11, 'alt': 0x12,
    'pause': 0x13, 'caps_lock': 0x14, 'capslock': 0x14,
    'escape': 0x1B, 'esc': 0x1B, 'space': 0x20,
    'page_up': 0x21, 'pageup': 0x21, 'page_down': 0x22, 'pagedown': 0x22,
    'end': 0x23, 'home': 0x24,
    'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'print_screen': 0x2C, 'insert': 0x2D, 'delete': 0x2E, 'del': 0x2E,
    'win': 0x5B, 'cmd': 0x5B, 'menu': 0x5D, 'apps': 0x5D,
    'num_lock': 0x90, 'scroll_lock': 0x91,
    'ctrl_l': 0xA2, 'ctrl_r': 0xA3, 'shift_l': 0xA0, 'shift_r': 0xA1,
    'alt_l': 0xA4, 'alt_r': 0xA5, 'alt_gr': 0xA5,
    'media_volume_mute': 0xAD, 'media_volume_down': 0xAE,
    'media_volume_up': 0xAF, 'media_next': 0xB0, 'media_previous': 0xB1,
    'media_play_pause': 0xB3,
}
for _i in range(1, 25):
    _VK_NAMES['f{}'.format(_i)] = 0x6F + _i

# Keys that live on the grey island / numeric pad edge and must carry the
# extended flag, or Windows delivers a different key entirely.
_EXTENDED_NAMES = frozenset({
    'insert', 'delete', 'del', 'home', 'end', 'page_up', 'pageup',
    'page_down', 'pagedown', 'left', 'up', 'right', 'down',
    'num_lock', 'print_screen', 'win', 'cmd', 'menu', 'apps',
    'ctrl_r', 'alt_r', 'alt_gr',
})


def _vk_for(key_name):
    """The virtual-key code for a key the user named, or 0."""
    lower = str(key_name or '').strip().lower()
    if not lower:
        return 0
    if lower in _VK_NAMES:
        return _VK_NAMES[lower]
    if lower.startswith('vk_'):
        try:
            return int(lower[3:])
        except ValueError:
            return 0
    if len(lower) == 1:
        if lower.isdigit() or ('a' <= lower <= 'z'):
            return ord(lower.upper())
        if sys.platform == 'win32':
            try:
                import ctypes
                result = ctypes.windll.user32.VkKeyScanW(ord(lower))
                if result != -1:
                    return result & 0xFF
            except Exception:
                pass
    return 0


def _parse_key_steps(keys):
    """'ctrl+c, ctrl+v' -> [['ctrl', 'c'], ['ctrl', 'v']]."""
    steps = []
    for chunk in str(keys or '').replace(';', ',').split(','):
        parts = [p.strip().lower().replace(' ', '_')
                 for p in chunk.split('+') if p.strip()]
        if parts:
            steps.append(parts)
    return steps


def _macro_json_from_keys(keys, gap_ms=120):
    """(data, error). Turn named key combinations into a .macro document.

    Held modifiers are what makes this worth doing in code: a combination is
    press-in-order then release-in-reverse, and a model writing the JSON by
    hand gets that wrong in a way that leaves Ctrl stuck down.
    """
    steps = _parse_key_steps(keys)
    if not steps:
        return None, "No keys were given."
    actions = []
    time_ms = 0
    for step in steps:
        unknown = [name for name in step if not _vk_for(name)]
        if unknown:
            return None, ("These are not keys Titan recognises: "
                          + ", ".join(unknown)
                          + ". Use names like ctrl, alt, shift, enter, tab, "
                            "f5, left, or a single character.")
        for name in step:
            actions.append({'type': 'key_press', 'key': name,
                            'vk': _vk_for(name), 'time_ms': time_ms,
                            'is_extended': name in _EXTENDED_NAMES})
            time_ms += 20
        for name in reversed(step):
            actions.append({'type': 'key_release', 'key': name,
                            'vk': _vk_for(name), 'time_ms': time_ms,
                            'is_extended': name in _EXTENDED_NAMES})
            time_ms += 20
        time_ms += max(0, int(gap_ms))
    return {'actions': actions}, ''


_KINDS = {'keys': '.macro', 'macro': '.macro', 'ahk': '.ahk',
          'autohotkey': '.ahk', 'au3': '.au3', 'autoit': '.au3',
          'ai': TCS_EXT, 'tcs': TCS_EXT,
          'script': TCS_EXT, 'actions': TCS_EXT}


def _folder_name_for(manager, name):
    """A folder name that is safe on disk and not already taken."""
    base = re.sub(r'[^a-z0-9_]+', '_', str(name).strip().lower()).strip('_')
    base = base or 'macro'
    candidate = base
    counter = 2
    existing = {m.get('folder_name') for m in manager.macros}
    while candidate in existing or os.path.isdir(
            os.path.join(manager.user_macros_dir, candidate)):
        candidate = '{}_{}'.format(base, counter)
        counter += 1
    return candidate


def action_create_macro(name, keys='', script='', kind='', hotkey=''):
    """Create a macro the user can then see, run, edit and give a shortcut."""
    name = str(name or '').strip()
    if not name:
        return needs('name', "What should the macro be called?")
    keys = str(keys or '').strip()
    script = str(script or '').strip()
    if not keys and not script:
        return needs('keys', "What should the macro do? Give the keys to "
                             "press, like 'ctrl+c, ctrl+v', or pass a script "
                             "in 'script'.")
    wanted = str(kind or '').strip().lower()
    if not wanted:
        wanted = 'keys' if keys else 'ahk'
    extension = _KINDS.get(wanted)
    if extension is None:
        return fails("A macro is either 'keys' (Titan's own key replay), "
                     "'ahk' (AutoHotkey) or 'au3' (AutoIt).")

    manager = _action_manager()
    if manager.find_by_name(name) is not None:
        return fails(f"There is already a macro called '{name}'. Delete it "
                     f"first, or choose another name.")

    if extension == '.macro':
        if not keys:
            return needs('keys', "Which keys should the macro press? For "
                                 "example 'ctrl+c, ctrl+v'.")
        data, error = _macro_json_from_keys(keys)
        if error:
            return fails(error)
        body = json.dumps(data, indent=2)
    elif extension == TCS_EXT:
        if not script:
            return needs('script', "What should the macro do? Write it in the "
                                   "Titan Script language - run "
                                   "macros.macro_language to see it.")
        # Checked before it is written, not the first time it runs: a macro
        # that fires at a quarter to twelve must not be where its author finds
        # out an action name was wrong.
        problems = check_tcs(script)
        if problems:
            return fails("That macro would not run:\n"
                         + "\n".join(f"- {p}" for p in problems[:8]))
        body = script
    else:
        if not script:
            return needs('script', f"What should the {wanted} script contain?")
        body = script

    folder_name = _folder_name_for(manager, name)
    openfile = folder_name + extension
    try:
        folder_path = manager.create_macro_folder(
            folder_name, name_en=name, name_pl=name, openfile=openfile,
            hotkey=str(hotkey or '').strip())
        with open(os.path.join(folder_path, openfile), 'w',
                  encoding='utf-8') as handle:
            handle.write(body)
    except Exception as e:
        return fails(f"Could not create the macro '{name}': {e}")
    manager.load_macros()
    _refresh_macro_list()
    return (f"Created the macro '{name}'"
            + (f" with the shortcut {hotkey}" if hotkey else "")
            + f". It is in the macro manager and can be run by name.")


def _find_macro(manager, name, verb):
    """(macro, problem) - the macro the user meant."""
    macro = manager.find_by_name(name)
    if macro is not None:
        return macro, None
    wanted = str(name or '').strip().lower()
    matches = [m for m in manager.macros
               if wanted and wanted in str(m.get('name', '')).lower()]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return None, needs('name', f"'{name}' matches {len(matches)} macros. "
                           f"Which one should be {verb}?",
                           options=[m.get('name', '?') for m in matches[:8]])
    if not manager.macros:
        return None, fails("There are no macros yet.")
    return None, needs('name', f"There is no macro called '{name}'. Which "
                       f"macro should be {verb}?",
                       options=[m.get('name', '?') for m in manager.macros[:12]])


def action_read_macro(name):
    """Show what a macro actually does."""
    manager = _action_manager()
    macro, problem = _find_macro(manager, name, 'shown')
    if problem is not None:
        return problem
    path = macro.get('script_path', '')
    header = (f"{macro.get('name')} [{macro.get('type', '?')}]"
              + (f", shortcut {macro['hotkey']}" if macro.get('hotkey') else '')
              + f"\n{path}")
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            body = handle.read(4000)
    except Exception as e:
        return f"{header}\n(the file could not be read: {e})"
    return f"{header}\n\n{body}"


def action_delete_macro(name):
    """Delete one of the user's macros."""
    manager = _action_manager()
    macro, problem = _find_macro(manager, name, 'deleted')
    if problem is not None:
        return problem
    try:
        manager.delete_macro(macro.get('folder_name'))
    except Exception as e:
        return fails(f"Could not delete '{macro.get('name')}': {e}")
    _refresh_macro_list()
    return f"Deleted the macro '{macro.get('name')}'."


def action_set_macro_hotkey(name, hotkey):
    """Give a macro a keyboard shortcut, or take it away."""
    manager = _action_manager()
    macro, problem = _find_macro(manager, name, 'changed')
    if problem is not None:
        return problem
    hotkey = str(hotkey or '').strip()
    try:
        manager.set_hotkey(macro.get('folder_name'), hotkey)
    except Exception as e:
        return fails(f"Could not change the shortcut of "
                     f"'{macro.get('name')}': {e}")
    if _macro_hotkey_manager is not None:
        try:
            _macro_hotkey_manager.reload()
        except Exception:
            pass
    _refresh_macro_list()
    if not hotkey:
        return f"'{macro.get('name')}' no longer has a shortcut."
    return f"'{macro.get('name')}' now runs with {hotkey}."


_MACRO_LANGUAGE = """The Titan Scripting Language (.TCS) - a script made of Titan's
own actions. Plain text, edited in tEdit like any other script.

One statement per line. # starts a comment.

  ACTIONS - every action every Titan add-on offers, exactly the set the
  assistant has, called by name:
    titan.speak "hello"                 one value, positionally
    titan.play_media title="Nirvana"    the same value, named
    titan.tts.speak("hello")            brackets and extra dots both work
    macros.run_macro name="My macro"    including other macros
    tnotes.create_note title="x" text="y"
    system.set_volume percent=30
  The values an action takes are the ones it declares - run
  macros.macro_actions, or titan_list_actions, to see them.

  VARIABLES AND WHAT CAN BE DONE TO THEM
    set state = zegarynka.get_settings  keep what an action returned
    set total = 2 + 3 * 4               + - * / and brackets
    set greeting = "Hello, " + who      + joins text when either side is text
    set shout = upper(trim(who))
    titan.speak "it said {{state}}"     put a value into any text
    {{last}} is always the previous result.
    Functions: upper, lower, trim, length, text, number, round, replace,
    now("%H:%M"), today("%Y-%m-%d").

  CONDITIONS
    if state contains "on"              contains, does not contain,
        say "the chime is on"           is, is not, is empty, is not empty,
    else                                is more than, is less than,
        say "the chime is off"          is at least, is at most
    end                                 (>, <, >=, <=, ==, != also work)

  REPEATING AND WAITING
    repeat 3
        wait 2s                         s, m or h
    end

  ASKING, AND WINDOWS
    ask who = "What is your name?"      a text box; the answer goes in 'who'
    ask who = "Name?" default="Anna" title="Greeting"
    confirm sure = "Go ahead?"          yes/no, so 'sure' is true or false
    choose kind = "Which?" options "personal", "work"
    message "All done, {{who}}."        a message box; also warn and error
    message "Saved" title="My macro"
    dialog "Add a note"                 one window, several controls
        field title = "Title"
        multiline body = "Text"
        choice kind = "Kind" options "personal", "work"
        check urgent = "Urgent?"
    end
    Each control's name becomes a variable. Closing a question or a dialog
    ends the script - a macro must not carry on past something declined.

  SPEAKING, SOUNDS AND STOPPING
    say "anything"                      Titan's own voice, as titan.speak
    say "anything" wait=true            wait until it has finished speaking
    say "anything" interrupt=true       stop what is being said first
    speak "anything"                    the same word either way
    voice engine="supertonic" name="Nova" rate=2 pitch=-1
                                        a different voice FOR THIS SCRIPT ONLY
    voice reset                         back to the user's own, early
    play "ding.ogg"                     a sound shipped beside the script
    play "ding.ogg" position=-1 wait=true    -1 left to 1 right
    run "helper.tcs"                    another script in the same folder;
                                        {{last}} is what it returned
    return "whatever"                   ends this script, handing that back
    stop                                ends the script here

  A bare filename in 'play' and 'run' is looked for next to the script itself,
  so a macro folder carries its own sounds and helper scripts anywhere.

  A script speaks with whatever the user configured. 'voice' borrows a
  different one: it is applied to the live engine, never saved, and put back
  the moment the script ends - finished, stopped, cancelled or broken.

  TRIGGERS - put these at the top to have Titan run the macro by itself:
    when startup
    when time = "11:45"                 every day at that time
    when every = "15m"

  PSEUDOCODE - with AI features switched on, a line may instead just say what
  it wants in plain language, and the AI turns it into these same actions:
    do "put today's date in a note called diary"
  A line that does not name an action is treated as pseudocode. Without AI
  features on, such a line is an error and the macro says so - everything
  above runs with the AI switched off."""


def action_macro_language():
    """The Titan Scripting Language, for whoever is writing one."""
    return _MACRO_LANGUAGE


def action_macro_actions(addon=""):
    """Every action a Titan Script can call."""
    try:
        from src.titan_core import actions
        registry = actions.get_registry()
    except Exception as e:
        return fails(f"The action registry is not available: {e}")
    wanted = str(addon or '').strip().lower()
    lines = []
    for entry in registry.addons:
        if wanted and entry.addon_id != wanted:
            continue
        for action in entry.actions:
            lines.append(f"  {action.describe()}")
    if not lines:
        return fails(f"No add-on called '{addon}' offers actions.")
    return ("Actions a Titan Script can call, as add-on.action(values):\n"
            + "\n".join(lines))


def action_check_macro(script="", name=""):
    """Say whether a Titan Script would run, without running it."""
    text = str(script or '')
    folder = ''
    if not text.strip():
        if not str(name or '').strip():
            return needs('script', "Which macro should be checked? Pass the "
                                   "script, or the name of a saved one.")
        manager = _action_manager()
        macro, problem = _find_macro(manager, name, 'checked')
        if problem is not None:
            return problem
        if macro.get('type') != TCS_EXT:
            return fails(f"'{macro.get('name')}' is a "
                         f"{macro.get('type')} macro, not a Titan Script.")
        try:
            with open(macro.get('script_path', ''), 'r',
                      encoding='utf-8') as handle:
                text = handle.read()
        except Exception as e:
            return fails(f"Could not read '{macro.get('name')}': {e}")
        folder = macro.get('folder_path', '')
    problems = check_tcs(text, base_dir=folder)
    if not problems:
        return "The macro is fine - every line names something Titan can do."
    return ("The macro would not run:\n"
            + "\n".join(f"- {p}" for p in problems[:12]))


TITAN_ACTIONS = [
    {'name': 'list_macros',
     'summary': "List the macros the user has, with their shortcuts.",
     'run': action_list_macros},
    {'name': 'run_macro',
     'summary': "Run one of the user's macros by name.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The macro's name."}},
     'risk': 'confirm', 'promote': True, 'run': action_run_macro},
    {'name': 'create_macro',
     'summary': "Create a macro in the user's macro manager. Use this whenever "
                "the user asks for a macro - it appears in their macro list "
                "with a name and an optional shortcut, instead of a script "
                "file left somewhere.",
     'params': {
         'name': {'type': 'string', 'required': True,
                  'description': "What the macro is called."},
         'keys': {'type': 'string',
                  'description': "The keys to press, combinations separated by "
                                 "commas, e.g. 'ctrl+c, ctrl+v' or "
                                 "'alt+f4'. Titan works out the press and "
                                 "release order."},
         'script': {'type': 'string',
                    'description': "The script itself, instead of 'keys' - an "
                                   "Titan Script (kind 'tcs'), or an AutoHotkey "
                                   "or AutoIt script. A Titan Script is checked "
                                   "before it is saved and the problems come "
                                   "back to you."},
         'kind': {'type': 'string', 'enum': ['keys', 'tcs', 'ahk', 'au3'],
                  'description': "'keys' for Titan's own key replay (the "
                                 "default when 'keys' is given), 'tcs' for a "
                                 "Titan Script (.TCS) made of Titan actions (put "
                                 "it in 'script'; see macros.macro_language), "
                                 "'ahk' for AutoHotkey, 'au3' for AutoIt."},
         'hotkey': {'type': 'string',
                    'description': "A shortcut that runs it, e.g. "
                                   "'ctrl+alt+m' (optional)."}},
     'risk': 'confirm', 'promote': True, 'run': action_create_macro},
    {'name': 'read_macro',
     'summary': "Show what one of the user's macros does.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The macro's name."}},
     'run': action_read_macro},
    {'name': 'delete_macro',
     'summary': "Delete one of the user's macros.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The macro's name."}},
     'risk': 'always_confirm', 'run': action_delete_macro},
    {'name': 'set_macro_hotkey',
     'summary': "Give a macro a keyboard shortcut, or remove the one it has.",
     'params': {'name': {'type': 'string', 'required': True,
                         'description': "The macro's name."},
                'hotkey': {'type': 'string',
                           'description': "The shortcut, e.g. 'ctrl+alt+m'. "
                                          "Leave empty to remove it."}},
     'risk': 'confirm', 'run': action_set_macro_hotkey},
    {'name': 'macro_language',
     'summary': "The Titan Scripting Language (.TCS) - how to write a macro "
                "out of Titan's own actions, with variables, conditions, "
                "dialogs and triggers. Read this before writing one.",
     'run': action_macro_language},
    {'name': 'macro_actions',
     'summary': "Every action a Titan Script can call, with the values each "
                "one takes.",
     'params': {'addon': {'type': 'string',
                          'description': "One add-on's id, to list only its "
                                         "actions (optional)."}},
     'run': action_macro_actions},
    {'name': 'check_macro',
     'summary': "Say whether a Titan Script would run, without running it - "
                "every line that names something Titan cannot do is reported. "
                "Use this on a script you have written before saving it.",
     'params': {'script': {'type': 'string',
                           'description': "The script text to check."},
                'name': {'type': 'string',
                         'description': "Or the name of a saved macro to "
                                        "check instead."}},
     'run': action_check_macro},
]
