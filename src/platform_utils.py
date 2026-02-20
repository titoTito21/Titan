# -*- coding: utf-8 -*-
"""
Centralized platform utilities for TCE Launcher.
Single source of truth for all platform detection, path resolution,
and cross-platform abstractions.
"""

import os
import sys
import platform
import shutil
import subprocess
import webbrowser

# Platform constants
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'


def is_frozen():
    """Check if running as a compiled executable (PyInstaller/Nuitka)."""
    return hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False)


def is_app_bundle():
    """Check if running inside a macOS .app bundle."""
    if not IS_MACOS:
        return False
    return '.app/Contents/MacOS/' in sys.executable


def get_base_path():
    """
    Get the project root / installation base path.

    - Frozen (PyInstaller/Nuitka): directory containing the executable
    - macOS .app bundle: Contents/MacOS/ directory
    - Development: project root (directory containing main.py)

    This is the primary path used to locate bundled resources and data.
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    else:
        # Development mode - project root
        # This file is at src/platform_utils.py, so go up one level
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def get_user_data_dir():
    """
    Get the platform-specific user data directory for writable config/data.

    - Windows: %APPDATA%/titosoft/Titan
    - Linux: ~/.config/titosoft/Titan
    - macOS: ~/Library/Application Support/titosoft/Titan
    """
    if IS_WINDOWS:
        base = os.getenv('APPDATA', os.path.expanduser('~'))
    elif IS_MACOS:
        base = os.path.expanduser('~/Library/Application Support')
    else:  # Linux and others
        base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))

    return os.path.join(base, 'titosoft', 'Titan')


def get_resource_path(relative_path=''):
    """
    Get the full path to a bundled/read-only resource.

    On all platforms in dev mode or Windows frozen: uses get_base_path().
    On macOS .app bundle: resources are in Contents/Resources/.
    On Linux installed: could be /usr/share/tce-launcher/ (future).

    Args:
        relative_path: Path relative to the resource root (e.g., 'sfx/default')

    Returns:
        Absolute path to the resource.
    """
    if is_app_bundle():
        # macOS .app bundle: resources in Contents/Resources/
        bundle_dir = os.path.dirname(os.path.dirname(sys.executable))  # Contents/
        resource_root = os.path.join(bundle_dir, 'Resources')
    else:
        resource_root = get_base_path()

    if relative_path:
        return os.path.join(resource_root, relative_path)
    return resource_root


def get_data_path(relative_path=''):
    """
    Get path to writable data directories (applications, components, games, etc.).

    In development mode and Windows frozen: same as get_base_path()/data/...
    In macOS .app bundle: ~/Library/Application Support/titosoft/Titan/data/...
    In Linux installed mode (future): ~/.local/share/titosoft/Titan/data/...

    Args:
        relative_path: Path relative to data root (e.g., 'applications')

    Returns:
        Absolute path to the writable data location.
    """
    if is_app_bundle():
        # macOS .app bundle: writable data in user directory
        data_root = os.path.join(get_user_data_dir(), 'data')
    else:
        # Windows/Linux dev/frozen: data is alongside the executable/project
        data_root = os.path.join(get_base_path(), 'data')

    if relative_path:
        return os.path.join(data_root, relative_path)
    return data_root


def ensure_data_directory():
    """
    Ensure writable data directory exists.
    On macOS .app bundle: copies bundled data/ to user directory on first run.
    On other platforms: creates directory if needed.
    """
    data_dir = get_data_path()

    if is_app_bundle():
        if not os.path.exists(data_dir):
            # First run on macOS - copy bundled data to user directory
            bundled_data = get_resource_path('data')
            if os.path.exists(bundled_data):
                print(f"[platform_utils] First run: copying data from bundle to {data_dir}")
                os.makedirs(os.path.dirname(data_dir), exist_ok=True)
                shutil.copytree(bundled_data, data_dir)
            else:
                os.makedirs(data_dir, exist_ok=True)
    else:
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)


def open_file_manager(path):
    """
    Open the platform's file manager at the given path.
    Cross-platform replacement for os.startfile().

    Args:
        path: File or directory path to open/reveal.
    """
    try:
        if IS_WINDOWS:
            os.startfile(path)
        elif IS_MACOS:
            subprocess.Popen(['open', path])
        else:  # Linux
            subprocess.Popen(['xdg-open', path])
    except Exception as e:
        print(f"[platform_utils] Error opening file manager: {e}")


def open_url(url):
    """
    Open a URL in the default browser. Cross-platform.

    Args:
        url: URL to open.
    """
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"[platform_utils] Error opening URL: {e}")


def get_python_executable_name():
    """
    Get the appropriate Python executable name for the current platform.

    Returns:
        Tuple of (gui_name, console_name) - preferred GUI and console Python names.
    """
    if IS_WINDOWS:
        return ('pythonw.exe', 'python.exe')
    else:
        return ('python3', 'python3')


def get_subprocess_kwargs():
    """
    Get platform-specific subprocess keyword arguments for hiding console windows.

    Returns:
        Dict of kwargs to pass to subprocess.Popen/run.
    """
    kwargs = {}
    if IS_WINDOWS:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = startupinfo
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return kwargs


def get_system_shutdown_command():
    """Get the platform-specific shutdown command."""
    if IS_WINDOWS:
        return ['shutdown', '/s', '/t', '0']
    elif IS_MACOS:
        return ['osascript', '-e', 'tell app "System Events" to shut down']
    else:  # Linux
        return ['systemctl', 'poweroff']


def get_system_restart_command():
    """Get the platform-specific restart command."""
    if IS_WINDOWS:
        return ['shutdown', '/r', '/t', '0']
    elif IS_MACOS:
        return ['osascript', '-e', 'tell app "System Events" to restart']
    else:  # Linux
        return ['systemctl', 'reboot']


def get_system_lock_command():
    """Get the platform-specific lock screen command."""
    if IS_WINDOWS:
        return ['rundll32.exe', 'user32.dll,LockWorkStation']
    elif IS_MACOS:
        return ['pmset', 'displaysleepnow']
    else:  # Linux
        return ['loginctl', 'lock-session']


def macos_is_accessibility_trusted():
    """
    Return True if the process has macOS Accessibility permission.
    Always returns True on non-macOS platforms.
    """
    if not IS_MACOS:
        return True
    try:
        import ctypes
        ax = ctypes.CDLL(
            '/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices'
        )
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(ax.AXIsProcessTrusted())
    except Exception:
        return True  # If we can't check, assume it's fine


def macos_request_accessibility_permission():
    """
    On macOS: if Accessibility permission is not yet granted, open System
    Preferences to the correct page so the user can grant it.
    Starting the pynput listener will additionally trigger the system
    permission dialog automatically.

    Returns True if already trusted, False if permission was just requested.
    """
    if not IS_MACOS:
        return True
    if macos_is_accessibility_trusted():
        return True
    # Open System Preferences -> Privacy & Security -> Accessibility
    try:
        subprocess.Popen([
            'open',
            'x-apple.systempreferences:'
            'com.apple.preference.security?Privacy_Accessibility'
        ])
    except Exception as e:
        print(f"[platform_utils] Could not open System Preferences: {e}")
    return False
