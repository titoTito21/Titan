"""
Macro Manager Component for TCE Launcher.
Supports .macro (built-in TCE format), .ahk (AutoHotKey), and .au3 (AutoIt) macros.
"""

import os
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


MACROS_DIR = os.path.join(_get_base_path(), 'data', 'macros')
os.makedirs(MACROS_DIR, exist_ok=True)

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
    """Handles loading, saving, running, creating, importing, and deleting macros."""

    def __init__(self, macros_dir):
        self.macros_dir = macros_dir
        self.macros = []
        self.load_macros()

    def load_macros(self):
        """Scan data/macros/ and parse each __macro__.TCE."""
        self.macros = []
        if not os.path.exists(self.macros_dir):
            return
        for folder_name in sorted(os.listdir(self.macros_dir)):
            folder_path = os.path.join(self.macros_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            config_path = os.path.join(folder_path, '__macro__.TCE')
            if not os.path.exists(config_path):
                continue
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')

            try:
                from src.titan_core.translation import language_code
                lang = language_code
            except Exception:
                lang = 'pl'

            name = config.get('macro', 'name_{}'.format(lang),
                              fallback=config.get('macro', 'name_en', fallback=folder_name))
            openfile = config.get('macro', 'openfile', fallback='')
            hotkey = config.get('macrocfg', 'hotkey', fallback='')

            ext = os.path.splitext(openfile)[1].lower() if openfile else ''
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
        """Persist hotkey change to __macro__.TCE."""
        config_path = os.path.join(self.macros_dir, folder_name, '__macro__.TCE')
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        if 'macrocfg' not in config:
            config['macrocfg'] = {}
        config['macrocfg']['hotkey'] = hotkey_str
        with open(config_path, 'w', encoding='utf-8') as f:
            config.write(f)
        self.load_macros()

    def create_macro_folder(self, folder_name, name_en, name_pl, openfile, hotkey=''):
        """Create folder + __macro__.TCE for a new macro."""
        folder_path = os.path.join(self.macros_dir, folder_name)
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
        """Import from ZIP, extract to macros_dir, create config."""
        folder_name = name_en.lower().replace(' ', '_')
        folder_path = os.path.join(self.macros_dir, folder_name)
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
        """Import from a folder, copy to macros_dir, create config."""
        folder_name = name_en.lower().replace(' ', '_')
        folder_path = os.path.join(self.macros_dir, folder_name)
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
        """Delete a macro folder entirely."""
        folder_path = os.path.join(self.macros_dir, folder_name)
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path, ignore_errors=True)
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
            type_choices = [_("TCE Macro (.macro)")]
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
    elif ext in ('.ahk', '.au3'):
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
    global _macro_manager, _macro_hotkey_manager

    if not _macro_manager:
        _macro_manager = MacroManager(MACROS_DIR)

    _macro_hotkey_manager = MacroHotkeyManager(_macro_manager)
    _macro_hotkey_manager.start()


def shutdown():
    """Called on app exit. Stop hotkey manager."""
    global _macro_hotkey_manager
    if _macro_hotkey_manager:
        _macro_hotkey_manager.stop()
        _macro_hotkey_manager = None


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
