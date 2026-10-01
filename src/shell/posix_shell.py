"""The shell's Windows calls, answered on Linux (and, where it can, macOS).

`win_shell.py` is the taskbar's, the desktop's, the Start menu's and the
file browser's one door onto Windows: the window list, the appbar, the
shell hook, Explorer's file operations, the Apps folder. This module
answers the same names out of what a Linux desktop offers, and
`win_shell` installs them over its own at import time off Windows, so
none of the shell's windows know the difference.

What is honest here: a window list through `wmctrl` or, where the
compositor has no EWMH (WSLg's Weston), through AT-SPI; activating,
minimising and closing through `wmctrl`/`xdotool`; the appbar as a
strip at the screen's edge with `_NET_WM_STRUT_PARTIAL` asked for through
`xprop` (a compositor that ignores it simply lets windows under the
bar); the shell hook as a slow poll of the window list; the desktop
folder from `xdg-user-dir`; files through `shutil`, `gio trash` and
`xdg-open`; installed applications from the `.desktop` files; lock,
suspend and exit through `loginctl` and `systemctl`. Icons answer 0:
the taskbar then draws the first letter, which it already knew how to.
"""
import configparser
import glob
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time

IS_MACOS = sys.platform == 'darwin'


def _run(command, timeout=10):
    try:
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout)
        return done.returncode, done.stdout.decode('utf-8', errors='replace')
    except FileNotFoundError:
        return 127, ''
    except Exception:
        return 1, ''


def _has(tool):
    return shutil.which(tool) is not None


def available():
    """True when this machine can host the shell at all."""
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY') or IS_MACOS)


# --------------------------------------------------------------------------- #
# The screen
# --------------------------------------------------------------------------- #
def screen_size():
    try:
        import wx
        if wx.GetApp() is not None:
            size = wx.GetDisplaySize()
            return (int(size[0]), int(size[1]))
    except Exception:
        pass
    if _has('xdpyinfo'):
        code, out = _run(['xdpyinfo'])
        for line in out.splitlines():
            if 'dimensions:' in line:
                try:
                    dims = line.split()[1]
                    w, h = dims.split('x')
                    return (int(w), int(h))
                except Exception:
                    break
    return (1920, 1080)


def physical_screen_size():
    return screen_size()


def dpi_scale():
    return 1.0


# --------------------------------------------------------------------------- #
# Windows
# --------------------------------------------------------------------------- #
_window_cache = {}      # id -> title
_cache_lock = threading.Lock()


def _shell_window(hwnd, title, minimized=False, active=False):
    from .win_shell import ShellWindow
    return ShellWindow(hwnd, title=title, minimized=minimized, active=active)


def _wmctrl_windows():
    code, out = _run(['wmctrl', '-lp'])
    if code:
        return None
    _active = None
    if _has('xdotool'):
        c2, a = _run(['xdotool', 'getactivewindow'])
        if not c2:
            try:
                _active = int(a.strip())
            except ValueError:
                _active = None
    found = []
    own = os.getpid()
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            wid = int(parts[0], 16)
            pid = int(parts[2])
        except ValueError:
            continue
        title = parts[4].strip()
        if not title or pid == own:
            continue
        found.append(_shell_window(wid, title, active=(wid == _active)))
    return found


def _atspi_windows():
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
    except Exception:
        return []
    found = []
    own = os.getpid()
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            try:
                pid = int(app.get_process_id())
            except Exception:
                pid = 0
            if pid == own:
                continue
            for j in range(app.get_child_count()):
                window = app.get_child_at_index(j)
                if window is None:
                    continue
                states = window.get_state_set()
                if not states.contains(Atspi.StateType.SHOWING):
                    continue
                title = window.get_name() or ''
                if not title:
                    continue
                # A stable id: the process and the window's index in it.
                wid = pid * 64 + j
                found.append(_shell_window(wid, title,
                                           active=states.contains(Atspi.StateType.ACTIVE)))
    except Exception:
        return found
    return found


def list_windows(own_hwnds=()):
    """Every window that belongs on the taskbar."""
    windows = _wmctrl_windows()
    if windows is None:
        windows = _atspi_windows()
    windows = [w for w in windows if w.hwnd not in set(own_hwnds or ())]
    with _cache_lock:
        _window_cache.clear()
        for w in windows:
            _window_cache[w.hwnd] = w.title
    return windows


def window_title(hwnd):
    with _cache_lock:
        return _window_cache.get(int(hwnd or 0), '')


def is_taskbar_window(hwnd, own_hwnds=()):
    return int(hwnd or 0) in _window_cache and hwnd not in set(own_hwnds or ())


def _wid(hwnd):
    return '0x%08x' % int(hwnd)


def activate_window(hwnd):
    if _has('wmctrl') and not _run(['wmctrl', '-ia', _wid(hwnd)])[0]:
        return True
    if _has('xdotool') and not _run(['xdotool', 'windowactivate', str(int(hwnd))])[0]:
        return True
    return False


def take_foreground(hwnd):
    return activate_window(hwnd)


def minimize_window(hwnd):
    return _has('xdotool') and not _run(['xdotool', 'windowminimize', str(int(hwnd))])[0]


def maximize_window(hwnd):
    return _has('wmctrl') and not _run(['wmctrl', '-ir', _wid(hwnd), '-b',
                                        'add,maximized_vert,maximized_horz'])[0]


def restore_window(hwnd):
    if _has('wmctrl'):
        _run(['wmctrl', '-ir', _wid(hwnd), '-b', 'remove,maximized_vert,maximized_horz'])
    return activate_window(hwnd)


def close_window(hwnd):
    return _has('wmctrl') and not _run(['wmctrl', '-ic', _wid(hwnd)])[0]


def minimize_all(own_hwnds=()):
    if _has('wmctrl') and not _run(['wmctrl', '-k', 'on'])[0]:
        return [w.hwnd for w in list_windows(own_hwnds)]
    return []


def restore_all(hwnds):
    if _has('wmctrl'):
        return not _run(['wmctrl', '-k', 'off'])[0]
    return False


def cascade_windows(own_hwnds=()):
    return False


def tile_windows_horizontally(own_hwnds=()):
    return False


def tile_windows_vertically(own_hwnds=()):
    return False


def hide_from_alt_tab(hwnd):
    if _has('wmctrl'):
        _run(['wmctrl', '-ir', _wid(hwnd), '-b', 'add,skip_taskbar,skip_pager'])
    return True


def window_icon_handle(hwnd):
    return 0


def shell_icon_handle(index, size=32):
    return None


def send_message_timeout(hwnd, message, wparam=0, lparam=0, timeout=200):
    return None


def windows_desktop_hwnd():
    return 0


def focus_windows_desktop():
    return False


def open_task_manager():
    for command in (['gnome-system-monitor'], ['ksysguard'], ['xfce4-taskmanager'],
                    ['x-terminal-emulator', '-e', 'top']):
        if _has(command[0]):
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


def set_explorer_taskbar_visible(visible):
    return True


# --------------------------------------------------------------------------- #
# The appbar and the shell hook
# --------------------------------------------------------------------------- #
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3


class AppBar:
    """A strip at one edge of the screen.

    The reservation is asked for with `_NET_WM_STRUT_PARTIAL` through
    `xprop`, which every EWMH window manager honours; one that does not
    (Weston) still shows the bar, only under a maximised window.
    """

    def __init__(self, hwnd, edge=ABE_BOTTOM, height=30):
        self.hwnd = int(hwnd or 0)
        self.edge = edge
        self.height = int(height)
        self.registered = False

    def register(self):
        self.registered = True
        self.reposition()
        return True

    def reposition(self, height=None):
        if height is not None:
            self.height = int(height)
        width, screen_height = screen_size()
        t = max(1, self.height)
        if self.edge == ABE_BOTTOM:
            rect = (0, screen_height - t, width, screen_height)
            strut = f"0, 0, 0, {t}, 0, 0, 0, 0, 0, 0, 0, {width}"
        elif self.edge == ABE_TOP:
            rect = (0, 0, width, t)
            strut = f"0, 0, {t}, 0, 0, 0, 0, 0, 0, {width}, 0, 0"
        elif self.edge == ABE_LEFT:
            rect = (0, 0, t, screen_height)
            strut = f"{t}, 0, 0, 0, 0, {screen_height}, 0, 0, 0, 0, 0, 0"
        else:
            rect = (width - t, 0, width, screen_height)
            strut = f"0, {t}, 0, 0, 0, 0, 0, {screen_height}, 0, 0, 0, 0"
        if self.hwnd and _has('xprop'):
            _run(['xprop', '-id', str(self.hwnd), '-f', '_NET_WM_STRUT_PARTIAL', '32c',
                  '-set', '_NET_WM_STRUT_PARTIAL', strut])
            _run(['xprop', '-id', str(self.hwnd), '-f', '_NET_WM_WINDOW_TYPE', '32a',
                  '-set', '_NET_WM_WINDOW_TYPE', '_NET_WM_WINDOW_TYPE_DOCK'])
        return rect

    def unregister(self):
        if self.registered and self.hwnd and _has('xprop'):
            _run(['xprop', '-id', str(self.hwnd), '-remove', '_NET_WM_STRUT_PARTIAL'])
        self.registered = False
        return True


HSHELL_WINDOWCREATED = 1
HSHELL_WINDOWDESTROYED = 2
HSHELL_WINDOWACTIVATED = 4
HSHELL_REDRAW = 6
HSHELL_RUDEAPPACTIVATED = 0x8004
HSHELL_FLASH = 0x8006
ABN_STATECHANGE = 0
ABN_POSCHANGED = 1
ABN_FULLSCREENAPP = 2


class ShellHook:
    """Window-list changes, by polling: Linux has no shell hook message.

    A poll every `INTERVAL` seconds, and `on_shell_event` is called with
    the same codes the Windows hook delivers, so the taskbar's handler is
    unchanged. Off the GUI thread; the taskbar marshals it itself.
    """

    INTERVAL = 1.5

    def __init__(self, hwnd, on_shell_event=None, on_appbar_event=None):
        self.hwnd = int(hwnd or 0)
        self.on_shell_event = on_shell_event
        self.on_appbar_event = on_appbar_event
        self.message = 0
        self._stop = threading.Event()
        self._thread = None
        self._last = {}

    def install(self):
        if self._thread is not None:
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='TitanShellPoll', daemon=True)
        self._thread.start()
        return True

    def uninstall(self):
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(2.0)

    def _loop(self):
        while not self._stop.wait(self.INTERVAL):
            try:
                now = {w.hwnd: (w.title, w.active) for w in list_windows()}
            except Exception:
                continue
            before = self._last
            self._last = now
            if self.on_shell_event is None:
                continue
            for wid in now:
                if wid not in before:
                    self._fire(HSHELL_WINDOWCREATED, wid)
            for wid in before:
                if wid not in now:
                    self._fire(HSHELL_WINDOWDESTROYED, wid)
            active_now = [w for w, (_t, a) in now.items() if a]
            active_before = [w for w, (_t, a) in before.items() if a]
            if active_now != active_before and active_now:
                self._fire(HSHELL_WINDOWACTIVATED, active_now[0])
            elif any(now[w][0] != before[w][0] for w in now if w in before):
                self._fire(HSHELL_REDRAW, 0)

    def _fire(self, code, hwnd):
        try:
            self.on_shell_event(code, hwnd)
        except Exception as e:
            print(f"[TitanShell] shell poll handler error: {e}")


# --------------------------------------------------------------------------- #
# The desktop and its files
# --------------------------------------------------------------------------- #
def _xdg_dir(name, default):
    if _has('xdg-user-dir'):
        code, out = _run(['xdg-user-dir', name])
        if not code and out.strip():
            return out.strip()
    return default


def desktop_folders():
    """The folders whose contents make up the desktop."""
    folders = [_xdg_dir('DESKTOP', os.path.expanduser('~/Desktop'))]
    return [path for path in folders if path and os.path.isdir(path)]


def wallpaper_path():
    if _has('gsettings'):
        code, out = _run(['gsettings', 'get', 'org.gnome.desktop.background', 'picture-uri'])
        if not code:
            uri = out.strip().strip("'")
            if uri.startswith('file://'):
                path = uri[7:]
                return path if os.path.isfile(path) else None
    return None


def user_display_name():
    try:
        import pwd
        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(',')[0].strip()
        if gecos:
            return gecos
    except Exception:
        pass
    return os.environ.get('USER') or 'User'


def file_icon_handle(path, large=True):
    return 0


def file_display_name(path):
    if path.lower().endswith('.desktop'):
        name = _desktop_entry(path).get('Name')
        if name:
            return name
    base = os.path.basename(path.rstrip('/'))
    return base if os.path.isdir(path) else os.path.splitext(base)[0]


def file_type_name(path):
    if os.path.isdir(path):
        return 'Folder'
    if path.lower().endswith('.desktop'):
        return 'Shortcut'
    import mimetypes
    kind, _ = mimetypes.guess_type(path)
    if kind:
        return kind.split('/')[-1].replace('-', ' ').title()
    ext = os.path.splitext(path)[1].lstrip('.').upper()
    return f"{ext} File" if ext else 'File'


def recycle(paths, confirm=True):
    """Move to the trash."""
    ok = True
    for path in paths:
        if _has('gio') and not _run(['gio', 'trash', path])[0]:
            continue
        try:
            trash = os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
                                 'Trash', 'files')
            os.makedirs(trash, exist_ok=True)
            shutil.move(path, os.path.join(trash, os.path.basename(path)))
        except Exception:
            ok = False
    return ok


def file_operation(paths, destination, move=False):
    ok = True
    for path in paths:
        try:
            target = os.path.join(destination, os.path.basename(path))
            if move:
                shutil.move(path, target)
            elif os.path.isdir(path):
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
        except Exception as e:
            print(f"[TitanShell] file operation failed for {path}: {e}")
            ok = False
    return ok


def show_properties(path, owner=0):
    """There is no system property sheet; open the folder's view instead."""
    return open_path(os.path.dirname(path) if os.path.isfile(path) else path)


def _desktop_entry(path):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding='utf-8')
        if parser.has_section('Desktop Entry'):
            return dict(parser.items('Desktop Entry'))
    except Exception:
        pass
    return {}


def shortcut_target(path):
    if not path.lower().endswith('.desktop'):
        return ''
    entry = _desktop_entry(path)
    return entry.get('exec', '').split(' %')[0].strip() or entry.get('url', '')


def create_shortcut(target, folder=None, name=None):
    folder = folder or (desktop_folders() or [os.path.expanduser('~')])[0]
    name = name or os.path.basename(target.rstrip('/'))
    path = os.path.join(folder, f"{name}.desktop")
    try:
        kind = 'Link' if target.startswith(('http:', 'https:')) else 'Application'
        with open(path, 'w', encoding='utf-8') as f:
            f.write("[Desktop Entry]\nType=%s\nName=%s\n" % (kind, name))
            if kind == 'Link':
                f.write(f"URL={target}\n")
            elif os.path.isdir(target):
                f.write(f"Exec=xdg-open {shlex.quote(target)}\nIcon=folder\n")
            else:
                f.write(f"Exec={shlex.quote(target)}\n")
        os.chmod(path, 0o755)
        return path
    except Exception:
        return ''


def open_path(path):
    try:
        if path.lower().endswith('.desktop') and os.path.isfile(path):
            if _has('gtk-launch'):
                subprocess.Popen(['gtk-launch', os.path.basename(path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            command = shortcut_target(path)
            if command:
                subprocess.Popen(shlex.split(command), stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return True
        opener = 'open' if IS_MACOS else 'xdg-open'
        subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def shell_execute(command, working_directory=None):
    command = (command or '').strip()
    if not command:
        return False
    if os.path.exists(command):
        return open_path(command)
    try:
        subprocess.Popen(shlex.split(command), cwd=working_directory or None,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        try:
            subprocess.Popen(command, shell=True, cwd=working_directory or None)
            return True
        except Exception:
            return False


def reveal_in_explorer(path):
    return open_path(os.path.dirname(path) if os.path.isfile(path) else path)


DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = 2, 3, 4, 5, 6


def list_drives():
    """My Computer's contents: the root, the home, and every mounted volume."""
    drives = []
    seen = set()

    def add(root, label, kind):
        if root in seen or not os.path.isdir(root):
            return
        seen.add(root)
        try:
            stat = os.statvfs(root)
            total = stat.f_frsize * stat.f_blocks
            free = stat.f_frsize * stat.f_bavail
        except Exception:
            total = free = 0
        drives.append({'root': root, 'letter': '', 'label': label, 'type': kind,
                       'total': total, 'free': free, 'name': label})

    add('/', 'Computer', DRIVE_FIXED)
    add(os.path.expanduser('~'), 'Home', DRIVE_FIXED)
    try:
        with open('/proc/mounts', encoding='utf-8') as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device, mount, fstype = parts[0], parts[1].replace('\\040', ' '), parts[2]
                if mount.startswith(('/media/', '/mnt/', '/run/media/')):
                    kind = DRIVE_REMOTE if fstype in ('nfs', 'cifs', 'smb3', 'sshfs') else \
                        DRIVE_CDROM if fstype in ('iso9660', 'udf') else DRIVE_REMOVABLE
                    add(mount, os.path.basename(mount) or device, kind)
    except OSError:
        pass
    return drives


def make_directory(parent, name):
    candidate = os.path.join(parent, name)
    try:
        os.makedirs(candidate, exist_ok=False)
        return candidate
    except Exception:
        return ''


def run_startup_items():
    return []


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #
_APPS = None
_APPS_LOCK = threading.Lock()


def _application_dirs():
    dirs = [os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')),
                         'applications')]
    for base in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':'):
        dirs.append(os.path.join(base, 'applications'))
    dirs.append('/var/lib/flatpak/exports/share/applications')
    dirs.append('/var/lib/snapd/desktop/applications')
    return [d for d in dirs if os.path.isdir(d)]


def _read_desktop_apps():
    apps = {}
    for folder in _application_dirs():
        for path in glob.glob(os.path.join(folder, '*.desktop')):
            entry = _desktop_entry(path)
            if not entry or entry.get('type', 'Application') != 'Application':
                continue
            if entry.get('nodisplay', '').lower() == 'true' or entry.get('hidden', '').lower() == 'true':
                continue
            app_id = os.path.basename(path)
            if app_id in apps:
                continue
            name = entry.get('name') or app_id[:-8]
            apps[app_id] = (name, app_id)
    return sorted(apps.values(), key=lambda pair: pair[0].lower())


def installed_apps(refresh=False, packaged_only=False, wait=True):
    """Every application the desktop lists: [(name, id)], id = the .desktop file."""
    global _APPS
    with _APPS_LOCK:
        if _APPS is None or refresh:
            if not wait and _APPS is None:
                read_installed_apps_async()
                return []
            _APPS = _read_desktop_apps()
        return [] if packaged_only else list(_APPS)


def read_installed_apps_async(then=None):
    def work():
        global _APPS
        apps = _read_desktop_apps()
        with _APPS_LOCK:
            _APPS = apps
        if then is not None:
            try:
                then()
            except Exception:
                pass
    threading.Thread(target=work, name='TitanShellApps', daemon=True).start()
    return True


def is_packaged_app(app_id):
    return False


def launch_app_id(app_id):
    if not app_id:
        return False
    if _has('gtk-launch'):
        try:
            subprocess.Popen(['gtk-launch', app_id], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    for folder in _application_dirs():
        path = os.path.join(folder, app_id)
        if os.path.isfile(path):
            return open_path(path)
    return False


# --------------------------------------------------------------------------- #
# Power
# --------------------------------------------------------------------------- #
def power_states_allowed():
    return (_has('systemctl'), _has('systemctl'))


def suspend(hibernate=False):
    if IS_MACOS:
        return not _run(['pmset', 'sleepnow'])[0]
    return _has('systemctl') and not _run(['systemctl', 'hibernate' if hibernate else 'suspend'])[0]


def exit_windows(mode='shutdown'):
    mode = (mode or 'shutdown').lower()
    if IS_MACOS:
        verb = {'logoff': 'log out', 'restart': 'restart'}.get(mode, 'shut down')
        return not _run(['osascript', '-e', f'tell application "System Events" to {verb}'])[0]
    if mode == 'logoff':
        for command in (['gnome-session-quit', '--logout', '--no-prompt'],
                        ['loginctl', 'terminate-session', os.environ.get('XDG_SESSION_ID', '')]):
            if _has(command[0]) and not _run(command)[0]:
                return True
        return False
    verb = 'reboot' if mode == 'restart' else 'poweroff'
    return _has('systemctl') and not _run(['systemctl', verb])[0]


def lock_workstation():
    for command in (['loginctl', 'lock-session'], ['xdg-screensaver', 'lock'],
                    ['gnome-screensaver-command', '-l']):
        if _has(command[0]) and not _run(command)[0]:
            return True
    if IS_MACOS:
        return not _run(['pmset', 'displaysleepnow'])[0]
    return False


def quiet_media_errors():
    import contextlib
    return contextlib.nullcontext()


def install_into(namespace):
    """Put this module's answers over `win_shell`'s, name for name."""
    for name, value in globals().items():
        if name.startswith('_') or name in ('install_into', 'IS_MACOS'):
            continue
        namespace[name] = value
