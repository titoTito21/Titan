"""
Titan shell layer - system level hooks for the "Modify system interface" mode.

While the mode is enabled Titan owns the Windows key: a bare tap opens the
Titan Menu instead of the Windows Start menu, and a configurable set of
Windows+<key> shortcuts is routed to Titan features.

With "Replace the desktop, taskbar and Start menu" turned on as well, the
mode goes the whole way: `src/shell/` puts up Titan's own desktop, taskbar,
notification area and Start menu in the shape of Windows XP, Explorer's own
bar is hidden while Titan owns the screen, and the shortcuts below drive
those instead of standing in for them.  With it off, the mode is exactly
what it always was - the keyboard, and nothing on the screen.

Combinations Titan deliberately does not claim keep working:

  * Windows+L still locks the workstation (handled natively, because the
    Windows key itself never reaches the system while the mode is on).
  * Anything pressed together with Control (Windows+Ctrl+D and friends) is
    handed back to Windows by re-injecting the Windows key.

Every binding can be turned off individually under Settings -> Titan shell.
"""

import os
import sys
import threading
import time
import subprocess
import platform
import ctypes
import wx
from src.settings.settings import get_setting
from src.titan_core.app_manager import find_application_by_shortname, open_application
from src.titan_core.translation import _

from src.platform_utils import IS_WINDOWS, IS_LINUX, IS_MACOS

# Windows-specific imports
if IS_WINDOWS:
    import win32gui
    import win32con
    import win32api
    import keyboard

# Settings section holding the per-binding switches of the shell layer.
SHELL_SECTION = 'titan_shell'

# Windows key names as understood by the keyboard module.
_WIN_KEYS = ('left windows', 'right windows')

# Shortcut table.  Each entry is (binding id, keys, shortcut label, default).
# "keys" is the list of keys that trigger the binding while the Windows key is
# held; the start menu binding uses no key because it fires on a bare tap.
SHELL_BINDINGS = (
    ('start_menu', (), 'Windows', True),
    ('file_manager', ('e',), 'Windows+E', True),
    ('system_tray', ('b',), 'Windows+B', True),
    ('show_desktop', ('d',), 'Windows+D', True),
    ('run_dialog', ('r',), 'Windows+R', True),
    ('window_switcher', ('w', 'f2'), 'Windows+W / Windows+F2', True),
    ('notifications', ('n',), 'Windows+N', True),
    ('taskbar', ('t',), 'Windows+T', True),
    ('minimize_all', ('m',), 'Windows+M', True),
    ('find', ('f',), 'Windows+F', True),
    ('system_properties', ('pause',), 'Windows+Pause', True),
)

# Shortcuts that are not Windows+<key> at all.  Ctrl+Escape has opened the
# Start menu since Windows 95 and is the only way to reach it on a keyboard
# with no Windows key, so with Titan's shell up it must open Titan's menu.
EXTRA_SHELL_BINDINGS = (
    ('start_menu_ctrl_esc', 'ctrl+esc', 'Ctrl+Escape', True),
)


def get_binding_descriptions():
    """Return {binding id: translated description} for the settings UI."""
    return {
        'start_menu': _("Open the Start menu"),
        'file_manager': _("Open the Titan file manager"),
        'system_tray': _("Open the system tray list"),
        'show_desktop': _("Show or hide the Titan window"),
        'run_dialog': _("Open the Run dialog"),
        'notifications': _("Open the notification center"),
        'window_switcher': _("Open the window switcher"),
        'taskbar': _("Move to the taskbar"),
        'minimize_all': _("Minimise every window"),
        'find': _("Search for files"),
        'system_properties': _("Open the system properties"),
        'start_menu_ctrl_esc': _("Open the Start menu"),
    }


def is_shell_mode_enabled():
    """True when the "Modify system interface" setting is turned on."""
    value = get_setting('windows_e_hook', 'False', 'environment')
    return str(value).lower() in ('true', '1')


def is_desktop_shell_enabled():
    """True when the mode should also replace the desktop and the taskbar."""
    if not is_shell_mode_enabled():
        return False
    value = get_setting('desktop_shell', 'False', SHELL_SECTION)
    return str(value).lower() in ('true', '1')


def is_binding_enabled(binding_id, default=True):
    """True when a single shell shortcut is enabled in the settings."""
    value = get_setting(binding_id, None, SHELL_SECTION)
    if value is None:
        return default
    return str(value).lower() in ('true', '1')


class SystemHooksManager:
    """Manages system-level hooks and modifications for TCE environment"""

    def __init__(self):
        self.windows_e_hook_active = False
        self.hooks_thread = None
        self.monitoring = False
        self.cleanup_event = threading.Event()

        # Handles returned by keyboard.hook_key, removed one by one on stop.
        self._hook_handles = []
        # Handles returned by keyboard.add_hotkey for whole combinations.
        self._hotkey_handles = []
        # Windows key state tracked by the low level hooks.
        self._win_down = False
        self._win_consumed = False
        self._win_passthrough = False
        self._win_injected = False
        self._injecting = False
        # Titan Menu owned by this manager when the host frame has none
        # (Klango mode, launcher mode, invisible interface).
        self._own_menu = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_system_hooks(self):
        """Start system hooks based on settings"""
        if self.monitoring:
            return

        self.monitoring = True
        self.cleanup_event.clear()

        if is_shell_mode_enabled():
            self.start_system_interface_hooks()
            self.start_desktop_shell()

    def start_desktop_shell(self):
        """Bring up the Titan desktop, taskbar and Start menu."""
        if not IS_WINDOWS or not is_desktop_shell_enabled():
            return False
        try:
            from src.shell.shell_manager import start_shell
            return bool(wx.CallAfter(start_shell,
                                     self._get_main_frame()) or True)
        except Exception as e:
            print(f"ERROR: Failed to start the Titan shell: {e}")
            return False

    def stop_desktop_shell(self):
        """Take the shell down and give the screen back to Windows."""
        try:
            from src.shell.shell_manager import stop_shell, is_shell_running
            if is_shell_running():
                return bool(stop_shell())
        except Exception as e:
            print(f"ERROR: Failed to stop the Titan shell: {e}")
        return False

    def stop_system_hooks(self):
        """Stop all system hooks"""
        self.monitoring = False
        self.cleanup_event.set()
        self.stop_desktop_shell()

        # Always attempt to release the keyboard hooks, even when start was
        # never called - a half finished registration must not leave the
        # Windows key suppressed for the rest of the session.
        self.stop_system_interface_hooks()
        self._destroy_own_menu()

    def refresh_from_settings(self):
        """Apply the current settings without restarting the application."""
        if is_shell_mode_enabled():
            if not self.windows_e_hook_active:
                self.monitoring = True
                self.start_system_interface_hooks()
        else:
            self.stop_system_interface_hooks()

        # The desktop half of the mode follows the same settings, so turning
        # it on shows the desktop at once rather than on the next start.
        try:
            from src.shell.shell_manager import apply_shell_settings
            wx.CallAfter(apply_shell_settings, self._get_main_frame())
        except Exception as e:
            print(f"WARNING: Could not apply the Titan shell settings: {e}")

    def start_system_interface_hooks(self):
        """Install the low level keyboard hooks of the Titan shell layer."""
        if not IS_WINDOWS:
            print("INFO: System interface hooks are only available on Windows")
            return
        if self.windows_e_hook_active:
            return

        # Mark active before registering so a failure half way through still
        # lets stop_system_interface_hooks() unwind what was installed.
        self.windows_e_hook_active = True
        try:
            for win_key in _WIN_KEYS:
                self._add_hook(win_key, self._on_win_key)

            # Control taken while the Windows key is held gives the Windows
            # key back to the system (Windows+Ctrl+D and similar).
            for ctrl_key in ('left ctrl', 'right ctrl'):
                self._add_hook(ctrl_key, self._on_ctrl_key)

            # Windows+L must keep locking the workstation.
            self._add_hook('l', self._on_lock_key)

            for binding_id, keys, _label, default in SHELL_BINDINGS:
                if not keys:
                    continue
                if not is_binding_enabled(binding_id, default):
                    continue
                for key in keys:
                    self._add_hook(key, self._make_binding_hook(binding_id))

            # Combinations that do not involve the Windows key at all.
            for binding_id, combo, _label, default in EXTRA_SHELL_BINDINGS:
                if is_binding_enabled(binding_id, default):
                    self._add_combination(binding_id, combo)

            print("INFO: Titan shell hooks activated - Windows key owned by Titan")
        except Exception as e:
            print(f"ERROR: Failed to start system interface hooks: {e}")
            self.stop_system_interface_hooks()

    def stop_system_interface_hooks(self):
        """Remove every keyboard hook installed by the shell layer."""
        if not IS_WINDOWS:
            return
        if not self._hook_handles and not self.windows_e_hook_active:
            return

        hotkeys, self._hotkey_handles = self._hotkey_handles, []
        for handle in hotkeys:
            try:
                keyboard.remove_hotkey(handle)
            except Exception as e:
                print(f"WARNING: Failed to release a shell combination: {e}")

        handles, self._hook_handles = self._hook_handles, []
        for key, callback, handle in handles:
            # Remove each hook on its own - one failure must not leave the
            # remaining hooks (and the Windows key) installed.
            try:
                keyboard.unhook(handle)
            except Exception as e:
                print(f"WARNING: Failed to remove the {key} hook: {e}")
                self._force_unhook(key, callback)

        self.windows_e_hook_active = False
        self._win_down = False
        self._win_consumed = False
        self._win_passthrough = False
        self._win_injected = False
        print("INFO: Titan shell hooks deactivated")

    def _add_hook(self, key, callback):
        """
        Install one suppressing key hook and remember how to remove it.

        keyboard.hook_key indexes its bookkeeping by the callback object, and
        its removal helper deletes that entry before it detaches the hook.
        Registering one bound method for two keys therefore makes the second
        removal raise - and leaves the key suppressed for the rest of the
        session.  Wrapping every hook in its own function keeps the entries
        distinct.
        """
        def hook(event, _callback=callback):
            return _callback(event)

        handle = keyboard.hook_key(key, hook, suppress=True)
        self._hook_handles.append((key, hook, handle))
        return handle

    def _add_combination(self, binding_id, combination):
        """Claim a whole combination (Ctrl+Escape), not a single key.

        `keyboard.add_hotkey` is used rather than a suppressing key hook
        because Control and Escape both have to keep working on their own;
        only the pair belongs to Titan.
        """
        try:
            handler = getattr(self, f'_handle_{binding_id}', None)
            if handler is None:
                return
            handle = keyboard.add_hotkey(
                combination, lambda: wx.CallAfter(handler),
                suppress=True, trigger_on_release=False)
            self._hotkey_handles.append(handle)
        except Exception as e:
            print(f"WARNING: Could not claim {combination}: {e}")

    def _force_unhook(self, key, callback):
        """Detach a hook straight from the keyboard listener tables.

        Last resort for when keyboard.unhook fails: a suppressing hook that
        stays installed would swallow that key system wide.
        """
        try:
            store = keyboard._listener.blocking_keys
            for scan_code in keyboard.key_to_scan_codes(key):
                while callback in store[scan_code]:
                    store[scan_code].remove(callback)
            print(f"INFO: Force-removed the {key} hook")
        except Exception as e:
            print(f"ERROR: Could not force-remove the {key} hook: {e}")

    # ------------------------------------------------------------------
    # Low level key handling
    #
    # A suppressing hook lets the event through when the callback returns a
    # truthy value and swallows it otherwise, so every handler below returns
    # True on any unexpected error (fail open - never trap the user's
    # keyboard).
    # ------------------------------------------------------------------

    def _on_win_key(self, event):
        """Windows key: swallow it and act on a bare tap."""
        try:
            if self._injecting:
                return True

            if event.event_type == keyboard.KEY_DOWN:
                if not self._win_down:
                    self._win_down = True
                    self._win_consumed = False
                    self._win_injected = False
                    # Control already held means the user is going for a
                    # system shortcut - stay out of the way entirely.
                    self._win_passthrough = keyboard.is_pressed('ctrl')
                return self._win_passthrough

            # Key up.
            if not self._win_down:
                # A release without a press we tracked - most likely the one we
                # injected ourselves for a passthrough combination. Injected
                # events can outlive the replay flag, so never treat this as a
                # tap on the Windows key.
                return True

            consumed = self._win_consumed
            passthrough = self._win_passthrough
            injected = self._win_injected
            self._win_down = False
            self._win_consumed = False
            self._win_passthrough = False
            self._win_injected = False

            if passthrough:
                # Only undo a press we made ourselves; when the real press went
                # through, the real release does the job.
                if injected:
                    self._inject(keyboard.release, 'left windows')
                return True

            if not consumed and is_binding_enabled('start_menu'):
                wx.CallAfter(self._toggle_start_menu)
            return False
        except Exception as e:
            print(f"ERROR: Windows key handler failed: {e}")
            return True

    def _on_ctrl_key(self, event):
        """Control pressed after the Windows key: hand the combo to Windows."""
        try:
            if self._injecting or event.event_type != keyboard.KEY_DOWN:
                return True
            if self._win_down and not self._win_passthrough:
                self._win_passthrough = True
                self._win_consumed = True
                self._win_injected = True
                self._inject(keyboard.press, 'left windows')
        except Exception as e:
            print(f"ERROR: Control passthrough failed: {e}")
        return True

    def _on_lock_key(self, event):
        """Windows+L: lock the workstation ourselves."""
        try:
            if self._injecting or event.event_type != keyboard.KEY_DOWN:
                return True
            if not self._win_down or self._win_passthrough:
                return True
            self._win_consumed = True
            threading.Thread(target=self._lock_workstation, daemon=True).start()
            return False
        except Exception as e:
            print(f"ERROR: Lock shortcut failed: {e}")
            return True

    def _make_binding_hook(self, binding_id):
        """Build the suppressing hook for one Windows+<key> shortcut."""
        def hook(event):
            try:
                if self._injecting or event.event_type != keyboard.KEY_DOWN:
                    return True
                if not self._win_down or self._win_passthrough:
                    return True
                self._win_consumed = True
                handler = getattr(self, f'_handle_{binding_id}', None)
                if handler is None:
                    return True
                wx.CallAfter(handler)
                return False
            except Exception as e:
                print(f"ERROR: Shell binding {binding_id} failed: {e}")
                return True
        return hook

    def _inject(self, func, *args):
        """Send a synthetic key event without re-entering our own hooks."""
        self._injecting = True
        try:
            func(*args)
        except Exception as e:
            print(f"WARNING: Key injection failed: {e}")
        finally:
            self._injecting = False

    def _lock_workstation(self):
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception as e:
            print(f"ERROR: Failed to lock the workstation: {e}")

    # ------------------------------------------------------------------
    # Host lookup - the shell layer runs in every Titan front end
    # ------------------------------------------------------------------

    def _get_main_frame(self):
        """Return the main Titan frame, or None. Must run on the wx thread."""
        try:
            windows = wx.GetTopLevelWindows()
            # The graphical interface owns a start menu; prefer it.
            for window in windows:
                if hasattr(window, 'start_menu'):
                    return window
            # Klango mode and launcher mode have no start menu, so fall back
            # to the application's top window and then to any visible frame.
            app = wx.GetApp()
            if app:
                top = app.GetTopWindow()
                if top and top is not self._own_menu:
                    return top
            for window in windows:
                if isinstance(window, wx.Frame) and window is not self._own_menu:
                    return window
            return None
        except Exception as e:
            print(f"ERROR: Failed to get main frame: {e}")
            return None

    def _get_menu(self):
        """
        Return the Titan Menu to drive.

        Uses the main frame's menu when there is one, otherwise creates and
        keeps a private instance so the Windows key also works in Klango
        mode, launcher mode and the invisible interface.
        """
        main_frame = self._get_main_frame()
        if main_frame is not None and getattr(main_frame, 'start_menu', None):
            return main_frame.start_menu

        if self._own_menu is not None:
            try:
                if self._own_menu.IsBeingDeleted():
                    self._own_menu = None
            except RuntimeError:
                self._own_menu = None

        if self._own_menu is None:
            try:
                from src.ui.classic_start_menu import create_classic_start_menu
                self._own_menu = create_classic_start_menu(main_frame)
            except Exception as e:
                print(f"ERROR: Failed to create Titan Menu: {e}")
                return None
        return self._own_menu

    def _destroy_own_menu(self):
        menu, self._own_menu = self._own_menu, None
        if menu is None:
            return
        try:
            wx.CallAfter(menu.Destroy)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Shortcut handlers - all of these run on the wx main thread
    # ------------------------------------------------------------------

    def _toggle_start_menu(self):
        """Open or close the Start menu.

        With the desktop shell running that is the XP one on its own
        taskbar; otherwise it is the classic Titan Menu, exactly as before.
        """
        try:
            from src.shell.shell_manager import toggle_start_menu
            if toggle_start_menu():
                return
        except Exception as e:
            print(f"WARNING: The shell Start menu is unavailable: {e}")

        try:
            menu = self._get_menu()
            if menu is None:
                print("WARNING: Titan Menu not available")
                return
            menu.toggle_menu()
        except Exception as e:
            print(f"ERROR: Failed to toggle the Titan Menu: {e}")

    def _handle_file_manager(self):
        """Windows+E - open the TCE file manager."""
        try:
            tfm_app = find_application_by_shortname('tfm')
            if not tfm_app:
                print("ERROR: TFM application not found")
                return
            threading.Thread(
                target=self._open_tfm_app,
                args=(tfm_app,),
                daemon=True
            ).start()
        except Exception as e:
            print(f"ERROR: Failed to handle Windows+E: {e}")

    def _open_tfm_app(self, tfm_app):
        """Open TFM application using app_manager"""
        try:
            open_application(tfm_app)
            print("INFO: TFM application launched")
        except Exception as e:
            print(f"ERROR: Failed to open TFM: {e}")

    def _handle_system_tray(self):
        """Windows+B - the notification area.

        With the shell running this is Windows' own meaning of the shortcut:
        the keyboard goes to the notification area of the taskbar.
        """
        try:
            from src.shell.shell_manager import focus_tray
            if focus_tray():
                return
        except Exception as e:
            print(f"WARNING: Could not focus the notification area: {e}")

        try:
            from src.system.system_tray_list import show_system_tray_list
            show_system_tray_list(self._get_main_frame())
        except Exception as e:
            print(f"ERROR: Failed to open System Tray list: {e}")

    def _handle_show_desktop(self):
        """Windows+D - show the desktop, or toggle the Titan window.

        With the system interface replaced this means what it means on
        Windows: everything goes down and the keyboard lands on the
        desktop - the Titan window included, and whether or not it was
        open, since "show the desktop" is not "show Titan".
        """
        try:
            from src.shell.shell_manager import show_desktop
            if show_desktop():
                return
        except Exception as e:
            print(f"WARNING: Could not show the desktop: {e}")

        if is_shell_mode_enabled():
            # The shell's own windows are not up (the desktop half of the
            # mode is off), but the mode is - so the shortcut still means
            # the desktop rather than the Titan window.
            self._handle_minimize_all()
            return

        try:
            frame = self._get_main_frame()
            if frame is None:
                print("WARNING: No Titan window to toggle")
                return
            if frame.IsShown() and not frame.IsIconized():
                frame.Iconize(True)
            else:
                frame.Iconize(False)
                frame.Show()
                frame.Raise()
                force_foreground(frame)
        except Exception as e:
            print(f"ERROR: Failed to toggle the Titan window: {e}")

    def _handle_run_dialog(self):
        """Windows+R - the Titan Run dialog."""
        try:
            menu = self._get_menu()
            if menu is None:
                return
            menu.show_run_dialog()
        except Exception as e:
            print(f"ERROR: Failed to open the Run dialog: {e}")

    def _handle_window_switcher(self):
        """Windows+W / Windows+F2 - the Titan window switcher."""
        try:
            from src.ui.window_switcher import show_window_switcher
            show_window_switcher(self._get_main_frame())
        except Exception as e:
            print(f"ERROR: Failed to open the window switcher: {e}")

    def _handle_start_menu_ctrl_esc(self):
        """Ctrl+Escape - the Start menu, as on every Windows since 95."""
        self._toggle_start_menu()

    def _handle_minimize_all(self):
        """Windows+M - minimise everything, Titan's own windows included.

        As on Windows, the keyboard ends up on the desktop: there is nothing
        else left on the screen for it to be in.  That is true whether or
        not Titan is the one drawing the desktop, so the landing is the
        shell manager's fallback rather than the shell's own window.
        """
        try:
            from src.shell.shell_manager import focus_desktop, get_shell
            from src.shell import win_shell
            shell = get_shell()
            own = shell.own_hwnds() if shell and shell.is_running() else ()
            win_shell.minimize_all(own)
            # The windows are asked to minimise, not made to, so the
            # keyboard follows a moment later.
            wx.CallLater(150, focus_desktop)
        except Exception as e:
            print(f"ERROR: Windows+M failed: {e}")

    def _handle_find(self):
        """Windows+F - search, through the Titan Menu's own Find dialog."""
        try:
            menu = self._get_menu()
            if menu is not None:
                menu.show_find_dialog()
        except Exception as e:
            print(f"ERROR: Windows+F failed: {e}")

    def _handle_system_properties(self):
        """Windows+Pause - the system properties, as Windows opens them."""
        try:
            subprocess.Popen(['control', 'system'], shell=True)
        except Exception as e:
            print(f"ERROR: Windows+Pause failed: {e}")

    def _handle_taskbar(self):
        """Windows+T - put the keyboard on the taskbar's window buttons."""
        try:
            from src.shell.shell_manager import get_shell
            shell = get_shell()
            if shell is not None and shell.is_running():
                shell.focus_taskbar()
                return
        except Exception as e:
            print(f"WARNING: Could not focus the taskbar: {e}")

        # Without the shell there is no Titan taskbar, so the nearest thing
        # Titan has to "the list of my windows" is the switcher.
        self._handle_window_switcher()

    def _handle_notifications(self):
        """Windows+N - the notification center."""
        try:
            from src.ui.notificationcenter import show_notification_center
            show_notification_center(self._get_main_frame())
        except Exception as e:
            print(f"ERROR: Failed to open the notification center: {e}")


def force_foreground(window):
    """
    Bring a wx window to the foreground from a global hotkey.

    Windows refuses SetForegroundWindow to a process that does not own the
    current foreground window, which is exactly the situation after a global
    shortcut.  Attaching to the foreground thread's input queue lifts the
    restriction; without this the Titan Menu opens behind the active
    application and is hidden again by its own focus watchdog.
    """
    if not IS_WINDOWS or window is None:
        return
    try:
        import win32process
        hwnd = window.GetHandle()
        foreground = win32gui.GetForegroundWindow()
        if foreground == hwnd:
            return
        target_thread = win32process.GetWindowThreadProcessId(foreground)[0]
        own_thread = win32api.GetCurrentThreadId()
        attached = False
        if target_thread and target_thread != own_thread:
            attached = bool(ctypes.windll.user32.AttachThreadInput(
                target_thread, own_thread, True))
        try:
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                ctypes.windll.user32.AttachThreadInput(
                    target_thread, own_thread, False)
    except Exception as e:
        print(f"WARNING: Could not bring window to the foreground: {e}")


# Global system hooks manager
_system_hooks_manager = None
_manager_lock = threading.Lock()

def get_system_hooks_manager():
    """Get the global system hooks manager instance (thread-safe)"""
    global _system_hooks_manager
    with _manager_lock:
        if _system_hooks_manager is None:
            _system_hooks_manager = SystemHooksManager()
        return _system_hooks_manager

def start_system_hooks():
    """Start system hooks (Windows only - uses keyboard hooks)"""
    if not IS_WINDOWS:
        print("System hooks are only available on Windows")
        return

    manager = get_system_hooks_manager()
    manager.start_system_hooks()

def stop_system_hooks():
    """Stop system hooks"""
    if not IS_WINDOWS:
        return

    global _system_hooks_manager
    with _manager_lock:
        if _system_hooks_manager:
            _system_hooks_manager.stop_system_hooks()
            _system_hooks_manager = None


def apply_shell_settings():
    """
    Re-read the shell settings and install or remove the hooks accordingly.

    Called after the settings dialog is saved so toggling the mode (or a
    single shortcut) takes effect immediately instead of on the next start.
    """
    if not IS_WINDOWS:
        return

    manager = get_system_hooks_manager()
    # Rebuild from scratch: the set of hooked keys depends on which
    # individual bindings are enabled.
    manager.stop_system_interface_hooks()
    manager.refresh_from_settings()

if __name__ == "__main__":
    # Test the system hooks
    print("Testing system hooks manager...")
    manager = SystemHooksManager()

    try:
        manager.start_system_hooks()
        print("System hooks started. Press Windows+E to test, Ctrl+C to stop.")

        # Keep main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        manager.stop_system_hooks()
        print("System hooks stopped.")
