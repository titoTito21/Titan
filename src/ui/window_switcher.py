# -*- coding: utf-8 -*-
"""
Window Switcher - "Switch To" dialog for TCE Launcher.

Maintains a registry of open windows (main TCE, apps, messengers, components)
and auto-discovers TCE app windows running as separate processes.

F2 opens the switcher globally (via InvisibleUI global hotkey).
Escape or F2 closes it.

Usage from TCE apps (optional - auto-discovery handles most cases):
    try:
        from src.titan_core.tce_window_switcher import register_window, unregister_window
    except ImportError:
        register_window = None

    if register_window:
        register_window("My App", my_wx_frame)
        # ... on close:
        unregister_window("My App")
"""

import wx
import os
import threading
try:
    import accessible_output3.outputs.auto
    _ao3_available = True
except Exception:
    _ao3_available = False

from src.titan_core.sound import play_focus_sound, play_select_sound, play_endoflist_sound, play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.controller.controller_vibrations import (
    vibrate_cursor_move, vibrate_selection, vibrate_menu_open, vibrate_menu_close
)
from src.platform_utils import IS_WINDOWS, IS_MACOS, IS_LINUX

_ = set_language(get_setting('language', 'pl'))


class _SilentSpeaker:
    def speak(self, text, **kwargs):
        pass
    def braille(self, text, **kwargs):
        pass


try:
    if _ao3_available:
        speaker = accessible_output3.outputs.auto.Auto()
    else:
        speaker = _SilentSpeaker()
except Exception:
    speaker = _SilentSpeaker()


# ---------------------------------------------------------------------------
# Global window registry (explicit registrations)
# ---------------------------------------------------------------------------
_registry_lock = threading.Lock()
_registered_windows = []  # List of dicts: {name, window, callback, category, handle}


def register_window(name, window=None, callback=None, category='app', handle=None):
    """
    Register a window in the switcher.

    Auto-unregisters when the wx.Window is closed/destroyed.

    Args:
        name: Display name for the window.
        window: wx.Window/wx.Frame to bring to front (optional, in-process only).
        callback: Callable to invoke when switching to this window (optional).
        category: 'main', 'app', 'messenger', 'component' - for ordering.
        handle: OS window handle (HWND on Windows) for cross-process switching.
    """
    with _registry_lock:
        for entry in _registered_windows:
            if entry['name'] == name:
                entry['window'] = window
                entry['callback'] = callback
                entry['category'] = category
                entry['handle'] = handle
                return
        _registered_windows.append({
            'name': name,
            'window': window,
            'callback': callback,
            'category': category,
            'handle': handle,
        })

    # Auto-unregister when the wx window is destroyed
    if window and isinstance(window, wx.Window):
        try:
            window.Bind(wx.EVT_WINDOW_DESTROY, lambda evt, n=name, w=window: _on_window_destroy(evt, n, w))
        except Exception:
            pass


def _on_window_destroy(event, name, expected_window):
    """Handler for EVT_WINDOW_DESTROY — unregister the window."""
    # EVT_WINDOW_DESTROY fires for child windows too; only act on the registered one
    if event.GetEventObject() is expected_window:
        unregister_window(name)
    event.Skip()


def unregister_window(name):
    """Remove a window from the switcher registry."""
    with _registry_lock:
        _registered_windows[:] = [w for w in _registered_windows if w['name'] != name]


def _is_window_alive(entry):
    """Check if a registered window is still alive and valid."""
    window = entry.get('window')
    if window is None:
        # No wx window — might be handle-only (cross-process), keep it
        return entry.get('handle') is not None
    if not isinstance(window, wx.Window):
        return False
    try:
        # wx C++ object deleted — raises RuntimeError
        window.GetId()
        return True
    except RuntimeError:
        return False


def get_registered_windows():
    """Return a sorted copy of registered windows, filtering out dead ones."""
    order = {'main': 0, 'app': 1, 'messenger': 2, 'component': 3}
    with _registry_lock:
        # Remove dead windows from registry
        _registered_windows[:] = [w for w in _registered_windows if _is_window_alive(w)]
        windows = list(_registered_windows)
    windows.sort(key=lambda w: (order.get(w['category'], 99), w['name']))
    return windows


def clear_all():
    """Clear all registered windows."""
    with _registry_lock:
        _registered_windows.clear()


# ---------------------------------------------------------------------------
# Dynamic window discovery for TCE apps (separate processes)
# ---------------------------------------------------------------------------

def _discover_tce_app_windows():
    """
    Discover windows belonging to TCE app processes.
    Returns list of dicts compatible with the registry format.
    """
    discovered = []

    if IS_WINDOWS:
        discovered = _discover_windows_win32()
    elif IS_MACOS or IS_LINUX:
        discovered = _discover_windows_pywinctl()

    return discovered


def _discover_windows_win32():
    """Discover TCE app windows on Windows using win32gui."""
    discovered = []
    try:
        import win32gui
        import win32process
        import psutil
    except ImportError:
        return _discover_windows_pywinctl()

    # Get PID of current process (main TCE) and its child processes
    main_pid = os.getpid()
    tce_pids = {main_pid}
    try:
        main_proc = psutil.Process(main_pid)
        for child in main_proc.children(recursive=True):
            tce_pids.add(child.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    # Get names of explicitly registered windows to avoid duplicates
    registered_names = set()
    registered_handles = set()
    with _registry_lock:
        for entry in _registered_windows:
            registered_names.add(entry['name'])
            if entry.get('handle'):
                registered_handles.add(entry['handle'])
            if entry.get('window') and hasattr(entry['window'], 'GetHandle'):
                try:
                    registered_handles.add(entry['window'].GetHandle())
                except Exception:
                    pass

    def enum_callback(hwnd, results):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title or not title.strip():
            return
        if hwnd in registered_handles:
            return
        if title in registered_names:
            return

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in tce_pids and pid != main_pid:
                results.append({
                    'name': title,
                    'window': None,
                    'callback': None,
                    'category': 'app',
                    'handle': hwnd,
                })
        except Exception:
            pass

    results = []
    try:
        win32gui.EnumWindows(enum_callback, results)
    except Exception as e:
        print(f"[WindowSwitcher] Error enumerating windows: {e}")

    return results


def _discover_windows_pywinctl():
    """Discover TCE app windows using pywinctl (cross-platform fallback)."""
    discovered = []
    try:
        import pywinctl as pwc
        import psutil
    except ImportError:
        return discovered

    main_pid = os.getpid()
    tce_pids = {main_pid}
    try:
        main_proc = psutil.Process(main_pid)
        for child in main_proc.children(recursive=True):
            tce_pids.add(child.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    registered_names = set()
    with _registry_lock:
        for entry in _registered_windows:
            registered_names.add(entry['name'])

    try:
        for window in pwc.getAllWindows():
            if not window.title or not window.title.strip():
                continue
            if window.title in registered_names:
                continue

            pid = None
            if hasattr(window, 'pid'):
                pid = window.pid
            elif hasattr(window, '_pid'):
                pid = window._pid
            elif hasattr(window, 'getProcessID'):
                pid = window.getProcessID()

            if pid and pid in tce_pids and pid != main_pid:
                handle = None
                try:
                    handle = window.getHandle()
                except Exception:
                    pass
                discovered.append({
                    'name': window.title,
                    'window': None,
                    'callback': None,
                    'category': 'app',
                    'handle': handle,
                })
    except Exception as e:
        print(f"[WindowSwitcher] Error discovering windows with pywinctl: {e}")

    return discovered


def _get_all_windows():
    """Get all windows: explicitly registered + dynamically discovered."""
    registered = get_registered_windows()
    discovered = _discover_tce_app_windows()

    # Merge - registered first, then discovered (avoid duplicates by name)
    seen_names = {w['name'] for w in registered}
    merged = list(registered)
    for d in discovered:
        if d['name'] not in seen_names:
            merged.append(d)
            seen_names.add(d['name'])

    return merged


# ---------------------------------------------------------------------------
# OS-level window activation (for cross-process windows)
# ---------------------------------------------------------------------------

def _activate_os_window(handle):
    """Bring an OS window to front by its handle."""
    if not handle:
        return False

    if IS_WINDOWS:
        try:
            import win32gui
            import win32con
            # Restore if minimized
            if win32gui.IsIconic(handle):
                win32gui.ShowWindow(handle, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(handle)
            return True
        except Exception as e:
            print(f"[WindowSwitcher] Error activating window handle {handle}: {e}")
            return False
    else:
        try:
            import pywinctl as pwc
            for w in pwc.getAllWindows():
                try:
                    if w.getHandle() == handle:
                        w.activate()
                        return True
                except Exception:
                    continue
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Switch To dialog
# ---------------------------------------------------------------------------

class WindowSwitcherDialog(wx.Dialog):
    """Switch To dialog - shows list of registered + discovered windows."""

    def __init__(self, parent=None):
        super().__init__(
            parent,
            title=_("Switch To"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
            size=wx.Size(400, 300),
        )

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label=_("Switch To:"))
        sizer.Add(label, 0, wx.ALL | wx.EXPAND, 5)

        self.listbox = wx.ListBox(panel)
        sizer.Add(self.listbox, 1, wx.ALL | wx.EXPAND, 5)

        panel.SetSizer(sizer)

        # Populate with all windows
        self._windows = _get_all_windows()
        for w in self._windows:
            self.listbox.Append(w['name'])

        if self.listbox.GetCount() > 0:
            self.listbox.SetSelection(0)

        # Bindings
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self._on_activate)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        # Focus and announce
        self.listbox.SetFocus()
        play_sound('ui/contextmenu.ogg')
        vibrate_menu_open()
        count = self.listbox.GetCount()
        if count > 0:
            speaker.speak(_("Switch To, {} items").format(count))
        else:
            speaker.speak(_("Switch To, no windows"))

        # Force foreground on Windows — multiple attempts at different timings
        # because Windows may not grant foreground rights until the dialog
        # is fully rendered and the event loop is pumping.
        if IS_WINDOWS:
            wx.CallAfter(self._force_to_foreground)
            wx.CallLater(50, self._force_to_foreground)
            wx.CallLater(150, self._force_to_foreground)

    def _force_to_foreground(self):
        """Force this dialog to the foreground on Windows.

        Uses multiple Win32 API tricks to bypass Windows' foreground lock.
        Called multiple times at different timings to ensure it works.
        """
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = self.GetHandle()
            if not hwnd:
                return

            # Already foreground? Just ensure listbox focus.
            if user32.GetForegroundWindow() == hwnd:
                self.listbox.SetFocus()
                return

            # 1. Temporarily disable the foreground lock timeout
            SPI_GETFOREGROUNDLOCKTIMEOUT = 0x2000
            SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
            old_timeout = ctypes.wintypes.DWORD(0)
            user32.SystemParametersInfoW(
                SPI_GETFOREGROUNDLOCKTIMEOUT, 0,
                ctypes.byref(old_timeout), 0
            )
            user32.SystemParametersInfoW(
                SPI_SETFOREGROUNDLOCKTIMEOUT, 0, None, 0
            )

            # 2. Attach our thread to the foreground window's input thread
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_tid = user32.GetWindowThreadProcessId(
                foreground_hwnd, None
            )
            current_tid = user32.GetCurrentThreadId()
            attached = False
            if foreground_tid and foreground_tid != current_tid:
                attached = bool(user32.AttachThreadInput(
                    foreground_tid, current_tid, True
                ))

            # 3. Simulate an Alt key press+release — this is the most
            #    reliable way to gain foreground activation rights.
            ALT_KEY = 0x12
            KEYEVENTF_EXTENDEDKEY = 0x0001
            KEYEVENTF_KEYUP = 0x0002
            user32.keybd_event(ALT_KEY, 0, KEYEVENTF_EXTENDEDKEY, 0)
            user32.keybd_event(ALT_KEY, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

            # 4. Force the window to front
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)

            # 5. SetWindowPos with HWND_TOPMOST for z-order
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
            )

            # Detach
            if attached:
                user32.AttachThreadInput(foreground_tid, current_tid, False)

            # Restore the old timeout
            user32.SystemParametersInfoW(
                SPI_SETFOREGROUNDLOCKTIMEOUT, 0,
                ctypes.c_void_p(old_timeout.value), 0
            )
        except Exception as e:
            print(f"[WindowSwitcher] Error forcing foreground: {e}")

        # Also set wx-level focus on the listbox
        try:
            self.Raise()
            self.listbox.SetFocus()
        except Exception:
            pass

    def _on_char_hook(self, event):
        keycode = event.GetKeyCode()
        count = self.listbox.GetCount()
        current = self.listbox.GetSelection()

        # Escape closes the dialog
        if keycode == wx.WXK_ESCAPE:
            play_sound('ui/contextmenuclose.ogg')
            vibrate_menu_close()
            self.EndModal(wx.ID_CANCEL)
            return

        # Enter activates selected item
        if keycode == wx.WXK_RETURN:
            self._on_activate(event)
            return

        if keycode in (wx.WXK_UP, wx.WXK_LEFT):
            if current > 0:
                new_sel = current - 1
                self.listbox.SetSelection(new_sel)
                vibrate_cursor_move()
                pan = new_sel / max(count - 1, 1)
                play_focus_sound(pan=pan)
            else:
                play_endoflist_sound()
            return

        if keycode in (wx.WXK_DOWN, wx.WXK_RIGHT):
            if current < count - 1:
                new_sel = current + 1
                self.listbox.SetSelection(new_sel)
                vibrate_cursor_move()
                pan = new_sel / max(count - 1, 1)
                play_focus_sound(pan=pan)
            else:
                play_endoflist_sound()
            return

        if keycode == wx.WXK_HOME:
            if count > 0:
                self.listbox.SetSelection(0)
                vibrate_cursor_move()
                play_focus_sound(pan=0)
            return

        if keycode == wx.WXK_END:
            if count > 0:
                self.listbox.SetSelection(count - 1)
                vibrate_cursor_move()
                play_focus_sound(pan=1.0)
            return

        event.Skip()

    def _on_activate(self, event):
        sel = self.listbox.GetSelection()
        if sel == wx.NOT_FOUND or sel >= len(self._windows):
            play_endoflist_sound()
            return

        play_select_sound()
        vibrate_selection()
        entry = self._windows[sel]
        self.EndModal(wx.ID_OK)

        # Switch to the selected window
        _switch_to_window(entry)


def _find_focusable_child(window):
    """Find the first visible, focusable child control in a window.

    Prefers ListBox, TreeCtrl, ListCtrl, then TextCtrl, then any control.
    """
    preferred_types = (wx.ListBox, wx.TreeCtrl, wx.ListCtrl)
    secondary_types = (wx.TextCtrl,)
    preferred = None
    secondary = None
    fallback = None

    def _scan(win):
        nonlocal preferred, secondary, fallback
        for child in win.GetChildren():
            if not child.IsShown():
                continue
            if isinstance(child, preferred_types) and not preferred:
                preferred = child
            elif isinstance(child, secondary_types) and not secondary:
                secondary = child
            elif child.AcceptsFocus() and not fallback:
                if not isinstance(child, (wx.Panel, wx.StaticText, wx.StaticBitmap)):
                    fallback = child
            # Recurse into panels
            if isinstance(child, wx.Panel):
                _scan(child)

    _scan(window)
    return preferred or secondary or fallback


def _switch_to_window(entry):
    """Bring a registered window to front."""
    has_callback = entry.get('callback') and callable(entry['callback'])

    # Try wx.Window (in-process) - show and raise first
    window = entry.get('window')
    if window and isinstance(window, wx.Window):
        try:
            if isinstance(window, wx.Frame) and window.IsIconized():
                window.Iconize(False)
            window.Show()
            window.Raise()
        except Exception as e:
            print(f"[WindowSwitcher] Error raising window '{entry['name']}': {e}")

    # Run callback after window is visible (so it can focus child controls)
    if has_callback:
        try:
            entry['callback']()
        except Exception as e:
            print(f"[WindowSwitcher] Error in callback for '{entry['name']}': {e}")
        return

    # No callback — find and focus the best child control instead of the frame
    if window and isinstance(window, wx.Window):
        try:
            child = _find_focusable_child(window)
            if child:
                child.SetFocus()
            else:
                window.SetFocus()
        except Exception:
            try:
                window.SetFocus()
            except Exception:
                pass
        return

    # Try OS handle (cross-process)
    handle = entry.get('handle')
    if handle:
        _activate_os_window(handle)


_switcher_open = False


def show_window_switcher(parent=None):
    """Show the Switch To dialog. Returns True if a window was selected."""
    global _switcher_open
    if _switcher_open:
        return False
    _switcher_open = True
    try:
        dlg = WindowSwitcherDialog(parent)
        try:
            result = dlg.ShowModal()
            return result == wx.ID_OK
        finally:
            dlg.Destroy()
    finally:
        _switcher_open = False
