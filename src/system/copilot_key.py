"""
Copilot key detection and remapping via copilothook.dll.

Detects the Microsoft Copilot key on 2024+ laptops and optionally
remaps it to a user-chosen key (Left Control, Context Menu, etc.)
using a low-level keyboard hook.
"""

import ctypes
import os
import sys

# Replacement key constants (VK codes)
VK_RCONTROL = 0xA3
VK_APPS = 0x5D  # Context menu key

REPLACEMENT_KEYS = [
    (VK_RCONTROL, "Right Control"),
    (VK_APPS, "Context menu"),
]

_dll = None
_loaded = False


def _get_dll_path():
    """Return path to copilothook.dll."""
    if getattr(sys, 'frozen', False):
        base = os.path.join(os.path.dirname(sys.executable), '_internal')
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.path.join(base, 'data', 'lib', 'copilothook.dll')


def _ensure_dll():
    """Load copilothook.dll (lazy, once)."""
    global _dll, _loaded
    if _loaded:
        return _dll
    _loaded = True
    if sys.platform != 'win32':
        return None
    path = _get_dll_path()
    if not os.path.isfile(path):
        print(f"[CopilotKey] DLL not found: {path}")
        return None
    try:
        _dll = ctypes.CDLL(path)
        _dll.DetectCopilotKey.restype = ctypes.c_bool
        _dll.InstallHook.argtypes = [ctypes.c_int]
        _dll.InstallHook.restype = ctypes.c_bool
        _dll.UninstallHook.restype = None
        _dll.SetReplacementKey.argtypes = [ctypes.c_int]
        _dll.SetReplacementKey.restype = None
        _dll.GetReplacementKey.restype = ctypes.c_int
        _dll.WasCopilotPressed.restype = ctypes.c_bool
        print("[CopilotKey] DLL loaded")
    except Exception as e:
        print(f"[CopilotKey] DLL load error: {e}")
        _dll = None
    return _dll


def is_available():
    """Return True if copilothook.dll is loaded and functional."""
    return _ensure_dll() is not None


def detect_copilot_key():
    """Heuristic: return True if this machine likely has a Copilot key."""
    dll = _ensure_dll()
    if dll is None:
        return False
    try:
        return dll.DetectCopilotKey()
    except Exception:
        return False


def install_hook(replacement_vk=VK_RCONTROL):
    """Install the low-level keyboard hook. Returns True on success."""
    dll = _ensure_dll()
    if dll is None:
        return False
    try:
        return dll.InstallHook(replacement_vk)
    except Exception as e:
        print(f"[CopilotKey] InstallHook error: {e}")
        return False


def uninstall_hook():
    """Remove the keyboard hook."""
    dll = _ensure_dll()
    if dll is None:
        return
    try:
        dll.UninstallHook()
    except Exception:
        pass


def set_replacement_key(vk):
    """Change the replacement VK code at runtime."""
    dll = _ensure_dll()
    if dll is None:
        return
    try:
        dll.SetReplacementKey(vk)
    except Exception:
        pass


def get_replacement_key():
    """Return the current replacement VK code."""
    dll = _ensure_dll()
    if dll is None:
        return VK_RCONTROL
    try:
        return dll.GetReplacementKey()
    except Exception:
        return VK_RCONTROL
