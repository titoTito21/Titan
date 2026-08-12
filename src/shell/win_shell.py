# -*- coding: utf-8 -*-
"""
The Windows side of the Titan shell.

Everything in here is what a shell has to do that a normal application never
does: reserve its strip of the screen so maximised windows stop above it
(the appbar), be told when a window appears, disappears, is activated or
flashes (the shell hook) instead of polling for it, list the windows that
belong on a taskbar, drive them, find the desktop folders and the wallpaper,
and - when Titan really is the shell - do the couple of jobs Explorer would
otherwise do.

Nothing here draws anything; the modules that draw call in here.
"""

import ctypes
import os
import sys
import threading
from ctypes import wintypes

from src.platform_utils import IS_WINDOWS

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    try:
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        dwmapi = None
else:  # pragma: no cover - the shell is a Windows feature
    user32 = shell32 = kernel32 = dwmapi = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ABM_NEW = 0x00000000
ABM_REMOVE = 0x00000001
ABM_QUERYPOS = 0x00000002
ABM_SETPOS = 0x00000003
ABM_GETSTATE = 0x00000004
ABM_ACTIVATE = 0x00000006
ABM_WINDOWPOSCHANGED = 0x00000009

ABE_LEFT = 0
ABE_TOP = 1
ABE_RIGHT = 2
ABE_BOTTOM = 3

ABN_STATECHANGE = 0x0000
ABN_POSCHANGED = 0x0001
ABN_FULLSCREENAPP = 0x0002

# Shell hook notifications.
HSHELL_WINDOWCREATED = 1
HSHELL_WINDOWDESTROYED = 2
HSHELL_ACTIVATESHELLWINDOW = 3
HSHELL_WINDOWACTIVATED = 4
HSHELL_GETMINRECT = 5
HSHELL_REDRAW = 6
HSHELL_TASKMAN = 7
HSHELL_LANGUAGE = 8
HSHELL_FLASH = 0x8006
HSHELL_RUDEAPPACTIVATED = 0x8004

GWL_STYLE = -16
GWL_EXSTYLE = -20
GWL_WNDPROC = -4

WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
SW_SHOWNA = 8

WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
SC_MINIMIZE = 0xF020
SC_MAXIMIZE = 0xF030
SC_RESTORE = 0xF120
WM_SYSCOMMAND = 0x0112

SPI_GETDESKWALLPAPER = 0x0073
SPI_GETWORKAREA = 0x0030

DWMWA_CLOAKED = 14

WM_SHELL_APPBAR = 0x0400 + 2317   # our own appbar callback message


class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uCallbackMessage', wintypes.UINT),
        ('uEdge', wintypes.UINT),
        ('rc', wintypes.RECT),
        ('lParam', ctypes.c_long),
    ]


def available():
    """True when this machine can host the shell at all."""
    return bool(IS_WINDOWS and user32)


# ---------------------------------------------------------------------------
# The screen
# ---------------------------------------------------------------------------


def screen_size():
    if not available():
        return (1920, 1080)
    return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def physical_screen_size():
    """The screen in real pixels, whatever this process is told it is.

    Titan runs DPI-unaware, so wx and GetSystemMetrics both report the
    virtualised size (1024x640 on a 1280x800 screen at 125%).  The appbar
    messages, however, are answered in *real* pixels - which is why a bar
    docked with the virtualised rectangle reserves a strip several times too
    tall.  This is the one place that has to know the difference.
    """
    if not available():
        return screen_size()
    try:
        hdc = user32.GetDC(0)
        try:
            # DESKTOPHORZRES / DESKTOPVERTRES ignore the DPI virtualisation.
            width = ctypes.windll.gdi32.GetDeviceCaps(hdc, 118)
            height = ctypes.windll.gdi32.GetDeviceCaps(hdc, 117)
        finally:
            user32.ReleaseDC(0, hdc)
        if width > 0 and height > 0:
            return (width, height)
    except Exception:
        pass
    return screen_size()


def dpi_scale():
    """How many real pixels one of this process's pixels is."""
    logical = screen_size()
    physical = physical_screen_size()
    if not logical[0] or not logical[1]:
        return 1.0
    return max(physical[0] / float(logical[0]),
               physical[1] / float(logical[1]))


def work_area():
    """The desktop rectangle minus everything already docked."""
    if not available():
        return (0, 0) + screen_size()
    rect = wintypes.RECT()
    if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return (rect.left, rect.top, rect.right - rect.left,
                rect.bottom - rect.top)
    return (0, 0) + screen_size()


# ---------------------------------------------------------------------------
# AppBar - reserving the strip
# ---------------------------------------------------------------------------


class AppBar:
    """Registers a window as a docked appbar on one edge of the screen.

    This is the difference between a blue strip lying on top of the desktop
    and a taskbar: without it a maximised window covers the shell, and the
    user's windows have no idea the bottom 30 pixels are taken.
    """

    def __init__(self, hwnd, edge=ABE_BOTTOM, height=30):
        self.hwnd = int(hwnd)
        self.edge = edge
        self.height = int(height)
        self.registered = False

    def _data(self):
        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        data.hWnd = self.hwnd
        data.uCallbackMessage = WM_SHELL_APPBAR
        data.uEdge = self.edge
        return data

    def register(self):
        if not available() or self.registered:
            return self.registered
        try:
            data = self._data()
            if shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(data)):
                self.registered = True
                self.reposition()
        except Exception as error:
            print(f"[TitanShell] appbar registration failed: {error}")
        return self.registered

    def reposition(self, height=None):
        """Ask Windows where we may sit, then take it.

        The two-step (QUERYPOS then SETPOS) is required: Windows adjusts the
        rectangle for anything already docked, and only the rectangle it
        hands back may be claimed.
        """
        if not available() or not self.registered:
            return None
        if height is not None:
            self.height = int(height)

        # The rectangle handed to Windows is in real pixels; the one handed
        # back to the caller is in this process's own, because that is what
        # it will pass to wx.
        scale = dpi_scale()
        width, screen_height = physical_screen_size()
        thickness = max(1, int(round(self.height * scale)))
        data = self._data()
        if self.edge == ABE_BOTTOM:
            data.rc.left, data.rc.right = 0, width
            data.rc.top = screen_height - thickness
            data.rc.bottom = screen_height
        elif self.edge == ABE_TOP:
            data.rc.left, data.rc.right = 0, width
            data.rc.top, data.rc.bottom = 0, thickness
        elif self.edge == ABE_LEFT:
            data.rc.top, data.rc.bottom = 0, screen_height
            data.rc.left, data.rc.right = 0, thickness
        else:
            data.rc.top, data.rc.bottom = 0, screen_height
            data.rc.left = width - thickness
            data.rc.right = width

        try:
            shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(data))
            # QUERYPOS moves the edge; put the thickness back on the side we
            # actually asked for, or the bar collapses to nothing.
            if self.edge == ABE_BOTTOM:
                data.rc.top = data.rc.bottom - thickness
            elif self.edge == ABE_TOP:
                data.rc.bottom = data.rc.top + thickness
            elif self.edge == ABE_LEFT:
                data.rc.right = data.rc.left + thickness
            else:
                data.rc.left = data.rc.right - thickness
            shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(data))

            # Back into this process's own pixels. The edge is then anchored
            # rather than divided: rounding a scaled coordinate can land a
            # pixel short, and a taskbar with a one pixel gap under it is a
            # taskbar the mouse can fall through.
            logical_width, logical_height = screen_size()
            left = int(round(data.rc.left / scale))
            top = int(round(data.rc.top / scale))
            width = int(round((data.rc.right - data.rc.left) / scale))
            height = int(round((data.rc.bottom - data.rc.top) / scale))
            if self.edge == ABE_BOTTOM:
                top = logical_height - height
            elif self.edge == ABE_TOP:
                top = 0
            elif self.edge == ABE_LEFT:
                left = 0
            else:
                left = logical_width - width
            return (left, top, width, height)
        except Exception as error:
            print(f"[TitanShell] appbar reposition failed: {error}")
            return None

    def notify_position_changed(self):
        if not available() or not self.registered:
            return
        try:
            data = self._data()
            shell32.SHAppBarMessage(ABM_WINDOWPOSCHANGED, ctypes.byref(data))
        except Exception:
            pass

    def activate(self):
        if not available() or not self.registered:
            return
        try:
            data = self._data()
            shell32.SHAppBarMessage(ABM_ACTIVATE, ctypes.byref(data))
        except Exception:
            pass

    def unregister(self):
        if not available() or not self.registered:
            return
        try:
            data = self._data()
            shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(data))
        except Exception as error:
            print(f"[TitanShell] appbar removal failed: {error}")
        finally:
            self.registered = False


# ---------------------------------------------------------------------------
# The window list
# ---------------------------------------------------------------------------


class ShellWindow:
    """One entry of the taskbar."""

    __slots__ = ('hwnd', 'title', 'minimized', 'active', 'flashing')

    def __init__(self, hwnd, title='', minimized=False, active=False,
                 flashing=False):
        self.hwnd = int(hwnd)
        self.title = title
        self.minimized = minimized
        self.active = active
        self.flashing = flashing

    def __eq__(self, other):
        return isinstance(other, ShellWindow) and other.hwnd == self.hwnd

    def __hash__(self):
        return hash(self.hwnd)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<ShellWindow {self.hwnd} {self.title!r}>"


def _is_cloaked(hwnd):
    """UWP keeps invisible ghost windows around; they are cloaked, not hidden."""
    if dwmapi is None:
        return False
    try:
        value = ctypes.c_int(0)
        dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                                     ctypes.byref(value), ctypes.sizeof(value))
        return bool(value.value)
    except Exception:
        return False


def window_title(hwnd):
    if not available():
        return ''
    try:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ''
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception:
        return ''


def is_taskbar_window(hwnd, own_hwnds=()):
    """The Alt+Tab rule, which is also the taskbar rule.

    A window belongs on the taskbar when it is visible, top level, not a tool
    window, not one of ours, and either unowned or explicitly an app window.
    """
    if not available() or not hwnd:
        return False
    try:
        if hwnd in own_hwnds:
            return False
        if not user32.IsWindowVisible(hwnd):
            return False
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        if style & WS_CHILD:
            return False
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if ex_style & WS_EX_TOOLWINDOW and not (ex_style & WS_EX_APPWINDOW):
            return False
        owner = user32.GetWindow(hwnd, 4)  # GW_OWNER
        if owner and not (ex_style & WS_EX_APPWINDOW):
            return False
        if _is_cloaked(hwnd):
            return False
        return bool(window_title(hwnd).strip())
    except Exception:
        return False


def list_windows(own_hwnds=()):
    """Every window that belongs on the taskbar, in z-order."""
    if not available():
        return []
    windows = []
    foreground = user32.GetForegroundWindow()

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)

    def callback(hwnd, _lparam):
        try:
            if is_taskbar_window(hwnd, own_hwnds):
                windows.append(ShellWindow(
                    hwnd,
                    title=window_title(hwnd),
                    minimized=bool(user32.IsIconic(hwnd)),
                    active=(hwnd == foreground)))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception as error:
        print(f"[TitanShell] window enumeration failed: {error}")
    return windows


def hide_from_alt_tab(hwnd):
    """Make a window furniture: no Alt+Tab entry, no taskbar button.

    The shell's own windows are the system interface, not applications -
    a desktop, a taskbar and a Start menu that answer Alt+Tab are three
    extra "programs" the user has to tab past to reach their own.
    `WS_EX_TOOLWINDOW` is the documented way to say so, and it has to be
    set on the window rather than asked for at construction because
    wxWidgets only offers it on frames that also draw a small caption.
    """
    if not available() or not hwnd:
        return False
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        return True
    except Exception as error:
        print(f"[TitanShell] could not hide a shell window: {error}")
        return False


def take_foreground(hwnd):
    """Give a window the keyboard, even though it is not the foreground one.

    `SetFocus` on a control only moves the focus *within* the window that is
    already active, so the shell's own bar could set the focus onto a task
    button all it liked and the keystrokes still went to the application the
    user was in - which is exactly why Tab did nothing on the taskbar.  A
    window has to be made the foreground one first, and Windows refuses that
    to any process that does not already own the foreground; attaching to the
    foreground thread's input queue is what lifts the refusal.
    """
    if not available() or not hwnd:
        return False
    try:
        foreground = user32.GetForegroundWindow()
        if foreground == hwnd:
            return True
        own_thread = kernel32.GetCurrentThreadId()
        threads = []
        if foreground:
            threads.append(user32.GetWindowThreadProcessId(foreground, None))
        threads.append(user32.GetWindowThreadProcessId(hwnd, None))
        attached = [thread for thread in threads
                    if thread and thread != own_thread
                    and user32.AttachThreadInput(thread, own_thread, True)]
        try:
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            for thread in attached:
                user32.AttachThreadInput(thread, own_thread, False)
        return bool(user32.GetForegroundWindow() == hwnd)
    except Exception as error:
        print(f"[TitanShell] could not take the foreground: {error}")
        return False


def activate_window(hwnd):
    """Bring a window forward the way a taskbar button does.

    A minimised window is restored first, and the foreground is asked for
    through the input-queue attachment, because Windows refuses
    SetForegroundWindow to a process that does not already own it - which is
    always the case for the shell.
    """
    if not available() or not hwnd:
        return False
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
        take_foreground(hwnd)
        user32.BringWindowToTop(hwnd)
        return True
    except Exception as error:
        print(f"[TitanShell] could not activate window: {error}")
        return False


def minimize_window(hwnd):
    if not available() or not hwnd:
        return False
    try:
        user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_MINIMIZE, 0)
        return True
    except Exception:
        return False


def maximize_window(hwnd):
    if not available() or not hwnd:
        return False
    try:
        user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_MAXIMIZE, 0)
        return True
    except Exception:
        return False


def restore_window(hwnd):
    if not available() or not hwnd:
        return False
    try:
        user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
        return True
    except Exception:
        return False


def close_window(hwnd):
    if not available() or not hwnd:
        return False
    try:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return True
    except Exception:
        return False


def is_minimized(hwnd):
    if not available() or not hwnd:
        return False
    try:
        return bool(user32.IsIconic(hwnd))
    except Exception:
        return False


def minimize_all(own_hwnds=()):
    """Show the desktop: minimise everything that is not ours."""
    minimized = []
    for window in list_windows(own_hwnds):
        if not window.minimized:
            if minimize_window(window.hwnd):
                minimized.append(window.hwnd)
    return minimized


def restore_all(hwnds):
    for hwnd in hwnds or ():
        restore_window(hwnd)


# Window arrangement.  Windows does this itself - CascadeWindows and
# TileWindows are the same calls Explorer's taskbar menu makes - so the shell
# asks for it rather than working out geometry of its own.
MDITILE_VERTICAL = 0x0000
MDITILE_HORIZONTAL = 0x0001


def _arrange(function, flags, own_hwnds=()):
    if not available():
        return False
    windows = [w for w in list_windows(own_hwnds) if not w.minimized]
    if not windows:
        return False
    try:
        count = len(windows)
        array = (wintypes.HWND * count)(*[w.hwnd for w in windows])
        function(None, flags, None, count, array)
        return True
    except Exception as error:
        print(f"[TitanShell] window arrangement failed: {error}")
        return False


def cascade_windows(own_hwnds=()):
    return _arrange(user32.CascadeWindows, 0, own_hwnds) if available() else False


def tile_windows_horizontally(own_hwnds=()):
    return _arrange(user32.TileWindows, MDITILE_HORIZONTAL, own_hwnds) \
        if available() else False


def tile_windows_vertically(own_hwnds=()):
    return _arrange(user32.TileWindows, MDITILE_VERTICAL, own_hwnds) \
        if available() else False


def open_task_manager():
    """Ctrl+Shift+Escape's target, for the taskbar menu that offers it."""
    if not IS_WINDOWS:
        return False
    try:
        import subprocess
        subprocess.Popen(['taskmgr.exe'], shell=True)
        return True
    except Exception as error:
        print(f"[TitanShell] could not start the task manager: {error}")
        return False


# ---------------------------------------------------------------------------
# The shell hook - being told instead of asking
# ---------------------------------------------------------------------------


class ShellHook:
    """Subclasses a window so it receives shell and appbar notifications.

    Polling for the window list is what makes third-party taskbars feel a
    second behind the system; `RegisterShellHookWindow` makes Windows post
    the change as it happens.  The window procedure is chained, never
    replaced, so wx keeps working underneath.
    """

    def __init__(self, hwnd, on_shell_event=None, on_appbar_event=None):
        self.hwnd = int(hwnd)
        self.on_shell_event = on_shell_event
        self.on_appbar_event = on_appbar_event
        self.message = 0
        self._old_proc = None
        self._new_proc = None
        self._registered = False

    def install(self):
        if not available():
            return False
        try:
            self.message = user32.RegisterWindowMessageW('SHELLHOOK')
            self._registered = bool(user32.RegisterShellHookWindow(self.hwnd))

            # LRESULT and the old procedure's address are pointer sized. Left
            # to ctypes' default of a C int, the 64-bit address of the window
            # procedure we are chaining to overflows on every single message -
            # which does not crash anything, it just silently turns the chain
            # into an exception per message and the window stops working.
            WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                         ctypes.c_uint, wintypes.WPARAM,
                                         wintypes.LPARAM)
            user32.CallWindowProcW.restype = ctypes.c_ssize_t
            user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                               ctypes.c_uint, wintypes.WPARAM,
                                               wintypes.LPARAM]

            def proc(hwnd, message, wparam, lparam):
                try:
                    if message == self.message and self.on_shell_event:
                        self.on_shell_event(int(wparam), int(lparam))
                    elif message == WM_SHELL_APPBAR and self.on_appbar_event:
                        self.on_appbar_event(int(wparam), int(lparam))
                except Exception as error:
                    print(f"[TitanShell] shell hook handler failed: {error}")
                return user32.CallWindowProcW(self._old_proc, hwnd, message,
                                              wparam, lparam)

            self._new_proc = WNDPROC(proc)
            set_long = getattr(user32, 'SetWindowLongPtrW', None) or \
                user32.SetWindowLongW
            set_long.restype = ctypes.c_void_p
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            self._old_proc = set_long(
                self.hwnd, GWL_WNDPROC,
                ctypes.cast(self._new_proc, ctypes.c_void_p))
            return bool(self._old_proc)
        except Exception as error:
            print(f"[TitanShell] could not install the shell hook: {error}")
            return False

    def uninstall(self):
        if not available():
            return
        try:
            if self._registered:
                user32.DeregisterShellHookWindow(self.hwnd)
                self._registered = False
            if self._old_proc:
                set_long = getattr(user32, 'SetWindowLongPtrW', None) or \
                    user32.SetWindowLongW
                set_long.restype = ctypes.c_void_p
                set_long.argtypes = [wintypes.HWND, ctypes.c_int,
                                     ctypes.c_void_p]
                set_long(self.hwnd, GWL_WNDPROC, self._old_proc)
                self._old_proc = None
        except Exception as error:
            print(f"[TitanShell] could not remove the shell hook: {error}")


# ---------------------------------------------------------------------------
# Explorer, and standing in for it
# ---------------------------------------------------------------------------


def explorer_taskbar_hwnd():
    if not available():
        return 0
    try:
        return user32.FindWindowW('Shell_TrayWnd', None) or 0
    except Exception:
        return 0


_APPS_CACHE = []
_APPS_CACHE_AT = 0.0
# Reading the Apps folder is over a second, and what is installed does not
# change while a menu is open.
APPS_CACHE_SECONDS = 300


def installed_apps(refresh=False):
    """Every application Windows itself lists, UWP ones included.

    `shell:AppsFolder` is what the Windows Start menu is made of: Store and
    packaged apps beside desktop programs.  It is the only place a UWP app
    can be found at all - there is no shortcut on disk, only an Application
    User Model ID - and it is also the only handle you can launch one by.

    Returns [(name, app id)], cached, because the walk costs over a second.
    """
    global _APPS_CACHE, _APPS_CACHE_AT
    import time
    if not IS_WINDOWS:
        return []
    if not refresh and _APPS_CACHE and             (time.time() - _APPS_CACHE_AT) < APPS_CACHE_SECONDS:
        return list(_APPS_CACHE)
    apps = []
    try:
        import pythoncom
        import win32com.client
        # A worker thread has no apartment of its own; the Shell objects
        # need one, and this is where the walk is done from.
        initialised = False
        try:
            pythoncom.CoInitialize()
            initialised = True
        except Exception:
            pass
        try:
            shell = win32com.client.Dispatch('Shell.Application')
            folder = shell.NameSpace('shell:AppsFolder')
            if folder is not None:
                for item in folder.Items():
                    try:
                        name = item.Name
                        app_id = item.Path
                    except Exception:
                        continue
                    if name and app_id:
                        apps.append((str(name), str(app_id)))
        finally:
            if initialised:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
    except Exception as error:
        print(f"[TitanShell] could not read the app list: {error}")
        return list(_APPS_CACHE)
    apps.sort(key=lambda pair: pair[0].lower())
    _APPS_CACHE, _APPS_CACHE_AT = apps, time.time()
    return list(apps)


def launch_app_id(app_id):
    """Start something out of the Apps folder, UWP or not.

    A packaged app has no executable to run: Explorer is asked for it by its
    Application User Model ID, which is what Windows' own Start menu does.
    """
    if not app_id:
        return False
    try:
        if os.path.exists(str(app_id)):
            return open_path(app_id)
        return shell_execute(
            r'explorer.exe shell:appsFolder\{}'.format(app_id))
    except Exception as error:
        print(f"[TitanShell] could not start {app_id}: {error}")
        return False


def windows_desktop_hwnd():
    """Windows' own desktop - the icon list, not the wallpaper behind it.

    It lives either under `Progman` or, once a slideshow wallpaper has run,
    under one of the `WorkerW` windows Explorer creates beside it, which is
    why both are looked in.  What comes back is the `SysListView32` itself,
    because that is the window that takes the keyboard and that a screen
    reader reads; its parents are containers with nothing in them.
    """
    if not available():
        return 0

    # A window handle is a pointer, and ctypes' default return type is a
    # 32-bit int: without this the handle of a real desktop comes back
    # truncated and every call made with it silently does nothing.
    try:
        user32.FindWindowW.restype = wintypes.HWND
        user32.FindWindowExW.restype = wintypes.HWND
        user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                         wintypes.LPCWSTR, wintypes.LPCWSTR]
    except Exception:
        pass

    def defview_list(parent):
        if not parent:
            return 0
        try:
            view = user32.FindWindowExW(parent, None, 'SHELLDLL_DefView',
                                        None)
            if not view:
                return 0
            return user32.FindWindowExW(view, None, 'SysListView32', None) or 0
        except Exception:
            return 0

    try:
        found = defview_list(user32.FindWindowW('Progman', None))
        if found:
            return found
        # Walk the WorkerW windows: the desktop moves into one of them when
        # Explorer is showing a wallpaper it animates.
        result = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                         wintypes.LPARAM)

        def callback(hwnd, _lparam):
            buffer = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, buffer, 64)
            if buffer.value == 'WorkerW':
                child = defview_list(hwnd)
                if child:
                    result.append(child)
                    return False
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return result[0] if result else 0
    except Exception:
        return 0


def focus_windows_desktop():
    """Put the keyboard on Windows' own desktop.

    What Windows+D and Windows+M mean when Titan is not drawing the desktop
    itself: the icons are still there, they are still a list view, and the
    shortcut has to land on them rather than doing nothing at all.
    """
    hwnd = windows_desktop_hwnd()
    if not hwnd:
        return False
    return take_foreground(hwnd)


def is_explorer_shell_running():
    """True while Explorer is still the shell (Titan is running beside it)."""
    return bool(explorer_taskbar_hwnd())


ABM_SETSTATE = 0x0000000A
ABS_AUTOHIDE = 0x0000001
ABS_ALWAYSONTOP = 0x0000002


def set_explorer_taskbar_reserved(reserved):
    """Give back (or take back) the strip Explorer's taskbar has reserved.

    Hiding Explorer's taskbar with ShowWindow makes it invisible but leaves
    its appbar registration standing, so every maximised window still stops
    short of a bar that is not there.  Putting it into auto-hide is what
    actually releases the work area, and it is exactly reversible.
    """
    hwnd = explorer_taskbar_hwnd()
    if not available() or not hwnd:
        return False
    try:
        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        data.hWnd = hwnd
        data.lParam = ABS_ALWAYSONTOP if reserved else ABS_AUTOHIDE
        shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(data))
        return True
    except Exception as error:
        print(f"[TitanShell] could not change Explorer's appbar state: {error}")
        return False


def set_explorer_taskbar_visible(visible):
    """Hide or show Explorer's own taskbar.

    Replacing the system interface with Explorer still running means two
    taskbars, and a maximised window sized around the wrong one.  Both are
    undone when the shell stops.
    """
    hwnd = explorer_taskbar_hwnd()
    if not hwnd:
        return False
    set_explorer_taskbar_reserved(visible)
    try:
        user32.ShowWindow(hwnd, SW_SHOW if visible else SW_HIDE)
        start = user32.FindWindowW('Button', None)
        if start:
            user32.ShowWindow(start, SW_SHOW if visible else SW_HIDE)
        # The secondary-monitor bars are separate windows of their own class.
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                         wintypes.LPARAM)

        def callback(child, _lparam):
            try:
                buffer = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(child, buffer, 64)
                if buffer.value == 'Shell_SecondaryTrayWnd':
                    user32.ShowWindow(child, SW_SHOW if visible else SW_HIDE)
            except Exception:
                pass
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return True
    except Exception as error:
        print(f"[TitanShell] could not change Explorer's taskbar: {error}")
        return False


def desktop_folders():
    """The two folders whose contents make up the desktop."""
    folders = []
    try:
        user_desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
        if IS_WINDOWS:
            buffer = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY = 0x10, CSIDL_COMMON_DESKTOPDIRECTORY 0x19
            if shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) == 0:
                user_desktop = buffer.value
            folders.append(user_desktop)
            buffer = ctypes.create_unicode_buffer(260)
            if shell32.SHGetFolderPathW(None, 0x19, None, 0, buffer) == 0 \
                    and buffer.value:
                folders.append(buffer.value)
        else:
            folders.append(user_desktop)
    except Exception:
        folders = [os.path.join(os.path.expanduser('~'), 'Desktop')]
    return [path for path in folders if path and os.path.isdir(path)]


def wallpaper_path():
    """The picture Windows is currently using, if any."""
    if not available():
        return None
    try:
        buffer = ctypes.create_unicode_buffer(512)
        if user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 512, buffer, 0):
            path = buffer.value
            if path and os.path.isfile(path):
                return path
    except Exception:
        pass
    return None


def user_display_name():
    """The name to put at the top of the Start menu."""
    try:
        if IS_WINDOWS:
            size = wintypes.DWORD(256)
            buffer = ctypes.create_unicode_buffer(256)
            # NameDisplay = 3; falls back to the login name.
            if ctypes.windll.secur32.GetUserNameExW(3, buffer, ctypes.byref(size)):
                if buffer.value:
                    return buffer.value
    except Exception:
        pass
    return os.environ.get('USERNAME') or os.environ.get('USER') or 'User'


def run_startup_items():
    """Run what Explorer would have run at logon.

    Only done when Titan really is the shell; with Explorer running these
    have already been started and doing it again would double every one.
    """
    if not IS_WINDOWS or is_explorer_shell_running():
        return []
    started = []
    folders = []
    try:
        for csidl in (0x07, 0x18):  # CSIDL_STARTUP, CSIDL_COMMON_STARTUP
            buffer = ctypes.create_unicode_buffer(260)
            if shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) == 0:
                folders.append(buffer.value)
    except Exception:
        pass

    for folder in folders:
        if not folder or not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            path = os.path.join(folder, entry)
            if not os.path.isfile(path):
                continue
            try:
                os.startfile(path)
                started.append(path)
            except Exception as error:
                print(f"[TitanShell] startup item {entry} failed: {error}")
    return started


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ('hIcon', wintypes.HICON),
        ('iIcon', ctypes.c_int),
        ('dwAttributes', wintypes.DWORD),
        ('szDisplayName', ctypes.c_wchar * 260),
        ('szTypeName', ctypes.c_wchar * 80),
    ]


SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SMALLICON = 0x000000001
SHGFI_DISPLAYNAME = 0x000000200
SHGFI_TYPENAME = 0x000000400


def file_icon_handle(path, large=True):
    """The icon Windows itself would draw for this file.

    A desktop that shows a generic page for every shortcut is not the XP
    desktop; this is where the real icons come from, including the ones a
    `.lnk` points at.
    """
    if not available():
        return 0
    try:
        info = SHFILEINFOW()
        flags = SHGFI_ICON | (SHGFI_LARGEICON if large else SHGFI_SMALLICON)
        result = shell32.SHGetFileInfoW(str(path), 0, ctypes.byref(info),
                                        ctypes.sizeof(info), flags)
        return int(info.hIcon) if result else 0
    except Exception:
        return 0


def window_icon_handle(hwnd):
    """The icon a window would show on a taskbar button.

    Asked for the way the shell asks: the window's own small icon first,
    then the one its window class carries, which is what a program that
    never answered WM_GETICON was registered with.
    """
    if not available() or not hwnd:
        return 0
    WM_GETICON = 0x007F
    ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0, 1, 2
    GCLP_HICONSM, GCLP_HICON = -34, -14
    for which in (ICON_SMALL2, ICON_SMALL, ICON_BIG):
        try:
            handle = user32.SendMessageW(int(hwnd), WM_GETICON, which, 0)
        except Exception:
            handle = 0
        if handle:
            return int(handle)
    getter = getattr(user32, 'GetClassLongPtrW', None) or         getattr(user32, 'GetClassLongW', None)
    if getter is None:
        return 0
    for index in (GCLP_HICONSM, GCLP_HICON):
        try:
            handle = getter(int(hwnd), index)
        except Exception:
            handle = 0
        if handle:
            return int(handle)
    return 0


def file_display_name(path):
    """What Explorer shows as the name (a localised folder, a .lnk's label)."""
    if not available():
        return os.path.splitext(os.path.basename(path))[0]
    try:
        info = SHFILEINFOW()
        if shell32.SHGetFileInfoW(str(path), 0, ctypes.byref(info),
                                  ctypes.sizeof(info), SHGFI_DISPLAYNAME):
            name = info.szDisplayName
            if name:
                return os.path.splitext(name)[0] if name.lower().endswith(
                    ('.lnk', '.url')) else name
    except Exception:
        pass
    return os.path.splitext(os.path.basename(path))[0]


def file_type_name(path):
    """"Shortcut", "Folder", "Text Document" - the second thing XP shows."""
    if not available():
        return ''
    try:
        info = SHFILEINFOW()
        if shell32.SHGetFileInfoW(str(path), 0, ctypes.byref(info),
                                  ctypes.sizeof(info), SHGFI_TYPENAME):
            return info.szTypeName or ''
    except Exception:
        pass
    return ''


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('wFunc', wintypes.UINT),
        ('pFrom', wintypes.LPCWSTR),
        ('pTo', wintypes.LPCWSTR),
        ('fFlags', ctypes.c_uint16),
        ('fAnyOperationsAborted', wintypes.BOOL),
        ('hNameMappings', ctypes.c_void_p),
        ('lpszProgressTitle', wintypes.LPCWSTR),
    ]


FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010


def recycle(paths, confirm=True):
    """Delete to the Recycle Bin, which is what Delete means on a desktop."""
    if not available() or not paths:
        return False
    try:
        buffer = '\0'.join(str(path) for path in paths) + '\0\0'
        operation = SHFILEOPSTRUCTW()
        operation.hwnd = None
        operation.wFunc = FO_DELETE
        operation.pFrom = buffer
        operation.pTo = None
        operation.fFlags = FOF_ALLOWUNDO | (0 if confirm else FOF_NOCONFIRMATION)
        result = shell32.SHFileOperationW(ctypes.byref(operation))
        return result == 0 and not operation.fAnyOperationsAborted
    except Exception as error:
        print(f"[TitanShell] delete failed: {error}")
        return False


FO_MOVE = 0x0001
FO_COPY = 0x0002


def file_operation(paths, destination, move=False):
    """Copy or move files the way Explorer does: with undo and its own
    progress box.  The double-NUL terminated list is the shell's own
    calling convention, and the same one `recycle` above uses."""
    if not available() or not paths or not destination:
        return False
    try:
        separator = chr(0)
        source = separator.join(str(p) for p in paths) + separator * 2
        operation = SHFILEOPSTRUCTW()
        operation.hwnd = None
        operation.wFunc = FO_MOVE if move else FO_COPY
        operation.pFrom = source
        operation.pTo = str(destination) + separator * 2
        operation.fFlags = FOF_ALLOWUNDO
        result = shell32.SHFileOperationW(ctypes.byref(operation))
        return result == 0 and not operation.fAnyOperationsAborted
    except Exception as error:
        print(f"[TitanShell] copy or move failed: {error}")
        return False


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('fMask', wintypes.ULONG),
        ('hwnd', wintypes.HWND),
        ('lpVerb', wintypes.LPCWSTR),
        ('lpFile', wintypes.LPCWSTR),
        ('lpParameters', wintypes.LPCWSTR),
        ('lpDirectory', wintypes.LPCWSTR),
        ('nShow', ctypes.c_int),
        ('hInstApp', wintypes.HINSTANCE),
        ('lpIDList', ctypes.c_void_p),
        ('lpClass', wintypes.LPCWSTR),
        ('hkeyClass', ctypes.c_void_p),
        ('dwHotKey', wintypes.DWORD),
        ('hIcon', ctypes.c_void_p),
        ('hProcess', wintypes.HANDLE),
    ]


SEE_MASK_INVOKEIDLIST = 0x0000000C
SEE_MASK_NOCLOSEPROCESS = 0x00000040


def show_properties(path, owner=0):
    """Windows' own properties sheet - it is accessible, so use it.

    This is the whole of "properties of a desktop shortcut": the sheet the
    shell puts up has the Shortcut tab with the target, the working folder,
    the shortcut key and the window state, and it is a real dialog that
    every screen reader reads.  `owner` is the window it belongs to - the
    desktop - without which the sheet can open behind the shell, which with
    Explorer's taskbar hidden means behind everything.
    """
    if not available():
        return False
    try:
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_INVOKEIDLIST
        info.hwnd = owner or None
        info.lpVerb = 'properties'
        info.lpFile = str(path)
        info.nShow = SW_SHOW
        return bool(shell32.ShellExecuteExW(ctypes.byref(info)))
    except Exception as error:
        print(f"[TitanShell] properties failed: {error}")
        return False


def shortcut_target(path):
    """What a .lnk points at, or '' for anything that is not one."""
    if not IS_WINDOWS or not str(path).lower().endswith('.lnk'):
        return ''
    try:
        import win32com.client
        shell = win32com.client.Dispatch('WScript.Shell')
        return shell.CreateShortCut(str(path)).Targetpath or ''
    except Exception as error:
        print(f"[TitanShell] could not read the shortcut: {error}")
        return ''


def reveal_in_explorer(path):
    """Open the folder something is in, with the thing itself selected.

    For a shortcut it is the *target's* folder that is wanted - "open file
    location" on a shortcut to a program is how somebody finds the program.
    """
    target = shortcut_target(path) or path
    if not target or not os.path.exists(target):
        target = path
    try:
        if IS_WINDOWS:
            shell32.ShellExecuteW(None, 'open', 'explorer.exe',
                                  '/select,"{}"'.format(target), None, SW_SHOW)
            return True
        return open_path(os.path.dirname(target))
    except Exception as error:
        print(f"[TitanShell] could not reveal {path}: {error}")
        return False


def create_shortcut(target, folder=None, name=None):
    """Make a .lnk to something, the way "Create shortcut" does."""
    if not IS_WINDOWS:
        return ''
    folder = folder or os.path.dirname(target)
    base = name or (os.path.splitext(os.path.basename(target))[0] + ' - '
                    + 'Shortcut')
    path = os.path.join(folder, base + '.lnk')
    index = 2
    while os.path.exists(path):
        path = os.path.join(folder, '{} ({}).lnk'.format(base, index))
        index += 1
    try:
        import win32com.client
        shell = win32com.client.Dispatch('WScript.Shell')
        link = shell.CreateShortCut(path)
        link.Targetpath = target
        link.WorkingDirectory = os.path.dirname(target) or ''
        link.save()
        return path
    except Exception as error:
        print(f"[TitanShell] could not create the shortcut: {error}")
        return ''


def open_path(path):
    """Open a file, folder or shortcut the way a double click would."""
    try:
        if IS_WINDOWS:
            os.startfile(path)
        else:
            import subprocess
            subprocess.Popen(['xdg-open' if sys.platform.startswith('linux')
                              else 'open', path])
        return True
    except Exception as error:
        print(f"[TitanShell] could not open {path}: {error}")
        return False


def split_command(command):
    """Split what was typed into the file to open and its arguments.

    The rule is the shell's own and not a general command-line one: a
    quoted first word is the file however many spaces are in it, and an
    unquoted one ends at the first space, so a quoted program path with
    a space in it keeps its arguments separate.
    `notepad readme.txt` comes out right too.
    """
    command = (command or '').strip()
    if not command:
        return '', ''
    if command.startswith('"'):
        closing = command.find('"', 1)
        if closing > 0:
            return command[1:closing], command[closing + 1:].strip()
        return command.strip('"'), ''
    parts = command.split(' ', 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else '')


def shell_execute(command, working_directory=None):
    """Run what the Run box says, the way the shell runs it.

    `os.startfile` cannot do this: it needs something that already exists on
    disk, so a bare `notepad`, anything with arguments, and a search the
    shell would have resolved through the App Paths key all fail.
    `ShellExecuteW` is what the Run dialog itself calls, and it takes a
    program name, a document, a folder and a web address alike.
    """
    if not IS_WINDOWS:
        return open_path(command)
    target, arguments = split_command(command)
    if not target:
        return False
    try:
        SW_SHOWNORMAL = 1
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        result = shell32.ShellExecuteW(None, 'open', target,
                                       arguments or None,
                                       working_directory, SW_SHOWNORMAL)
        # Anything up to and including 32 is one of ShellExecute's error
        # codes; above it is an instance handle, which means it started.
        return int(result or 0) > 32
    except Exception as error:
        print(f"[TitanShell] could not run {command}: {error}")
        return False


def shell_icon_handle(index, size=32):
    """One of shell32's own icons, by its index, as an HICON."""
    if not IS_WINDOWS:
        return None
    try:
        large = (ctypes.c_void_p * 1)()
        small = (ctypes.c_void_p * 1)()
        shell32.ExtractIconExW.restype = ctypes.c_uint
        count = shell32.ExtractIconExW('shell32.dll', int(index),
                                       large, small, 1)
        if not count:
            return None
        wanted, other = (large, small) if size >= 32 else (small, large)
        if other[0]:
            user32.DestroyIcon(other[0])
        return wanted[0] or None
    except Exception as error:
        print(f"[TitanShell] could not read a shell icon: {error}")
        return None


_shutdown_lock = threading.Lock()


def exit_windows(mode='shutdown'):
    """Log off, restart or shut down.

    Titan already knows the right command per platform; this only picks it
    and keeps the call off the GUI thread's hands.
    """
    from src.platform_utils import (get_system_shutdown_command,
                                    get_system_restart_command)
    import subprocess

    with _shutdown_lock:
        try:
            if mode == 'logoff':
                if IS_WINDOWS:
                    subprocess.Popen(['shutdown', '/l'], shell=True)
                    return True
                return False
            command = get_system_restart_command() if mode == 'restart' \
                else get_system_shutdown_command()
            subprocess.Popen(command, shell=IS_WINDOWS)
            return True
        except Exception as error:
            print(f"[TitanShell] {mode} failed: {error}")
            return False


def power_states_allowed():
    """Whether this machine will sleep and hibernate.

    The Shut Down dialog must not offer either where Windows would refuse
    it: `powrprof.dll` answers both questions, and a machine with hibernation
    turned off says so rather than the dialog finding out afterwards.
    """
    if not IS_WINDOWS:
        return False, False
    try:
        powrprof = ctypes.windll.powrprof
        # GetPwrCapabilities first.  `IsPwrSuspendAllowed` predates modern
        # standby and answers no on machines that sleep perfectly well, so
        # asking it alone hides Sleep on most laptops made this decade.
        # The capabilities structure begins with a run of one-byte flags:
        # 3..7 are S1 to S5, 8 is whether there is a hibernation file, and
        # 20 is AoAc - modern standby, which is how a machine made this
        # decade sleeps.  Without that last one every such laptop reports
        # S1, S2 and S3 as absent and Sleep would never be offered on the
        # hardware that sleeps best.
        buffer = (ctypes.c_ubyte * 128)()
        if powrprof.GetPwrCapabilities(ctypes.byref(buffer)):
            sleep = any(buffer[index] for index in (3, 4, 5, 20))
            hibernate = bool(buffer[6] and buffer[8])
            return sleep, hibernate
    except Exception:
        pass
    try:
        powrprof = ctypes.windll.powrprof
        return (bool(powrprof.IsPwrSuspendAllowed()),
                bool(powrprof.IsPwrHibernateAllowed()))
    except Exception:
        return False, False


def suspend(hibernate=False):
    """Sleep, or hibernate.  True if Windows took it."""
    if not IS_WINDOWS:
        return False
    try:
        # SetSuspendState(Hibernate, ForceCritical, DisableWakeEvent)
        return bool(ctypes.windll.powrprof.SetSuspendState(
            1 if hibernate else 0, 0, 0))
    except Exception as error:
        print(f"[TitanShell] could not suspend: {error}")
        return False


def lock_workstation():
    if not available():
        return False
    try:
        user32.LockWorkStation()
        return True
    except Exception:
        return False
