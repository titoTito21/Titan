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
    - Subprocess in compiled distribution (_internal/python.exe): parent of _internal/
    - Development: project root (directory containing main.py)

    This is the primary path used to locate bundled resources and data.
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    else:
        # Check if running as subprocess inside a compiled distribution
        # (e.g. apps/games launched via _internal/pythonw.exe)
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.path.basename(exe_dir) == '_internal':
            return os.path.dirname(exe_dir)
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


# ---------------------------------------------------------------------------
# User-data overlay (%APPDATA%/titosoft/Titan/...)
# ---------------------------------------------------------------------------
# Titan supports a per-user overlay so that users (and the configuration wizard)
# can drop their own applications, components, games, launchers, Titan IM
# modules, statusbar applets, widgets, macros, TTS engines, skins, sfx themes
# and language packs into the user data directory without modifying the
# installation directory.
#
# Layout under get_user_data_dir():
#   data/applications/
#   data/components/
#   data/games/
#   data/launchers/
#   data/titanIM_modules/
#   data/statusbar_applets/
#   data/applets/
#   data/macros/
#   data/titantts engines/
#   skins/
#   sfx/<theme>/
#   languages/<lang>/LC_MESSAGES/<domain>.mo
#
# Rules:
# - When a folder/file exists with the same name in BOTH the bundled location
#   and the user location, the USER copy wins (overrides). This lets users
#   shadow bundled items.
# - Writes that would mutate per-item configuration (e.g. enabling/disabling a
#   component or persisting an applet config) go to the directory the item was
#   loaded from. Writes that create brand-new items default to the user dir.

def get_user_resource_path(relative_path=''):
    """
    Get the per-user overlay path for any resource (data/, sfx/, skins/,
    languages/, etc.).

    On macOS .app bundle this is identical to get_data_path()'s root (because
    bundled resources are already copied to the user dir on first launch). On
    Windows/Linux it points at %APPDATA%/titosoft/Titan/ (or the XDG / macOS
    equivalent).
    """
    base = get_user_data_dir()
    if relative_path:
        return os.path.join(base, relative_path)
    return base


def iter_resource_paths(relative_path, prefer_user=True):
    """
    Yield candidate locations for a bundled/user-overlay resource, in priority
    order.

    Each candidate is an absolute path; existence is NOT checked. Callers
    typically use:

        for candidate in iter_resource_paths('sfx/default/ui/click.ogg'):
            if os.path.exists(candidate):
                ...
                break

    With prefer_user=True (default) the user overlay wins. The bundled path is
    always also yielded so users can drop a partial overlay (e.g. only one .mo
    file or one sound file).
    """
    user_path = get_user_resource_path(relative_path)
    bundled_path = get_resource_path(relative_path) if relative_path else get_resource_path()

    if prefer_user:
        yield user_path
        if bundled_path != user_path:
            yield bundled_path
    else:
        yield bundled_path
        if user_path != bundled_path:
            yield user_path


def find_resource(relative_path, prefer_user=True):
    """
    Return the first existing candidate for a resource, or None.

    Resolution order with prefer_user=True: user overlay -> bundled.
    """
    for candidate in iter_resource_paths(relative_path, prefer_user=prefer_user):
        if os.path.exists(candidate):
            return candidate
    return None


def iter_data_roots(subdir):
    """
    Yield existing root directories that may contain entries for the given
    `data/...` subdirectory (e.g. 'applications', 'components', 'games').

    Order is bundled first then user, so callers that want user-wins should
    build a name->path dict, overriding when the user entry appears (see
    discover_data_entries).
    """
    bundled = os.path.join(get_data_path(), subdir) if subdir else get_data_path()
    user = os.path.join(get_user_resource_path('data'), subdir) if subdir \
        else get_user_resource_path('data')

    if os.path.isdir(bundled):
        yield bundled
    if os.path.isdir(user) and os.path.abspath(user) != os.path.abspath(bundled):
        yield user


def discover_data_entries(subdir, predicate=None):
    """
    Discover entries in `data/<subdir>/` across bundled + user roots.

    Returns an ordered dict mapping entry_name -> absolute_path. When the same
    name appears in both roots the user copy wins (user is enumerated last and
    overwrites bundled entries in the dict).

    Args:
        subdir: Subdirectory under data/ (e.g. 'applications').
        predicate: Optional callable(entry_name, full_path) -> bool. Only
            entries for which predicate returns True are included. The default
            keeps every directory that is not .DS_Store.

    Returns:
        dict[str, str] preserving discovery order (bundled first, user wins on
        name collision).
    """
    from collections import OrderedDict
    found = OrderedDict()

    def _default_predicate(name, full):
        return os.path.isdir(full) and name != '.DS_Store'

    pred = predicate or _default_predicate

    for root in iter_data_roots(subdir):
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            full = os.path.join(root, name)
            entry_name = name
            if not os.path.isdir(full):
                # Not a directory -- could be a packaged .TCA/.TCD add-on.
                # The package file itself stays exactly where it is (it is
                # never deleted or converted into a directory); it's
                # transparently extracted into a runtime cache and that
                # cache directory is used for the rest of this call, so
                # every existing caller/predicate keeps working unmodified.
                try:
                    from src.titan_core import titan_package
                    if titan_package.is_package_file(full):
                        entry_name = titan_package.read_header(full).id
                        full = titan_package.ensure_extracted(full)
                    else:
                        continue
                except Exception as e:
                    print(f"[platform_utils] Skipping unreadable package '{full}': {e}")
                    continue
            try:
                if pred(entry_name, full):
                    found[entry_name] = full
            except Exception:
                continue
    return found


def discover_resource_entries(relative_dir, predicate=None):
    """
    Like discover_data_entries() but for top-level resources outside data/
    (e.g. 'skins', 'sfx', 'languages').
    """
    from collections import OrderedDict
    found = OrderedDict()

    def _default_predicate(name, full):
        return os.path.isdir(full) and name != '.DS_Store'

    pred = predicate or _default_predicate

    bundled = get_resource_path(relative_dir) if relative_dir else get_resource_path()
    user = get_user_resource_path(relative_dir) if relative_dir else get_user_resource_path()

    for root in (bundled, user):
        if not root or not os.path.isdir(root):
            continue
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            full = os.path.join(root, name)
            try:
                if pred(name, full):
                    found[name] = full
            except Exception:
                continue
    return found


def ensure_user_data_subdir(*parts):
    """
    Build and create (mkdir -p) a directory under the user data root.

    Returns the absolute path. Safe to call repeatedly.
    """
    path = os.path.join(get_user_data_dir(), *parts)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        print(f"[platform_utils] Could not create user data subdir {path}: {e}")
    return path


# Layout under get_user_data_dir() that Titan expects to exist so users can
# drop their own apps/components/macros/skins/sfx/translations without having
# to mkdir anything by hand. Order is not significant; everything is mkdir -p.
USER_OVERLAY_SUBDIRS = (
    ('data', 'applications'),
    ('data', 'components'),
    ('data', 'games'),
    ('data', 'launchers'),
    ('data', 'titanIM_modules'),
    ('data', 'statusbar_applets'),
    ('data', 'applets'),
    ('data', 'macros'),
    ('data', 'titantts engines'),
    ('skins',),
    ('sfx',),
    ('languages',),
)


def ensure_user_overlay_layout():
    """
    Create every user-overlay subdirectory Titan can read from so the first
    launch on a fresh machine doesn't have to deal with "directory X not
    found" issues.

    Reads from missing overlay dirs were already safe (they're silently
    skipped), but creating them up front makes it obvious to the user where
    to drop their own content and ensures any code that writes new entries
    (the macros manager, the statusbar applet auto-create, the configuration
    wizard, ...) always has a parent dir ready.

    Safe to call repeatedly; only creates missing directories.
    """
    created = []
    for parts in USER_OVERLAY_SUBDIRS:
        path = ensure_user_data_subdir(*parts)
        created.append(path)
    return created


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
