# -*- coding: utf-8 -*-
"""
What turns the pieces into a shell.

`start_shell()` brings up the desktop, the taskbar and the Start menu, hides
Explorer's own bar while Titan owns the screen, and puts everything back on
`stop_shell()` - including when Titan exits unexpectedly, because the appbar
is unregistered and the system taskbar restored from the same teardown path.

The mode is the existing "Modify system interface" setting: with it on,
Titan's shell layer already owned the Windows key, and this is what it now
opens onto.  Nothing here runs unless that setting is on.
"""

import threading

import wx

from src.platform_utils import IS_WINDOWS
from src.settings.settings import get_setting, set_setting
from src.shell import luna, win_shell
from src.shell.a11y import (SOUND_SHUTDOWN, SOUND_STARTUP,
                            shell_setting, shell_sound)
from src.titan_core.translation import _

_shell = None
# Re-entrant on purpose. Building the shell reads the skin, loading a skin
# tells the shell to repaint, and that asks for the shell again - all on the
# one thread. A plain lock deadlocks there, and the symptom is Titan freezing
# the moment the desktop shell is switched on.
_lock = threading.RLock()


def desktop_shell_enabled():
    """True when the shell should replace the desktop, not only the keys.

    Two switches, deliberately: "Modify system interface" is the master one
    the user already knows, and this is the part of it that takes over the
    screen - so somebody who only wants the Windows key routed to Titan can
    still have exactly that.
    """
    from src.titan_core.tce_system import is_shell_mode_enabled
    if not is_shell_mode_enabled():
        return False
    return bool(shell_setting('desktop_shell', False))


class TitanShell:
    """The desktop, the taskbar and the Start menu, as one thing."""

    def __init__(self, parent=None):
        self.parent = parent
        self.palette = luna.get_palette(refresh=True)
        self.desktop = None
        self.taskbar = None
        self.start_menu = None
        self._explorer_hidden = False
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self):
        if self._running:
            return True
        if not IS_WINDOWS:
            print("[TitanShell] the shell is a Windows feature")
            return False

        try:
            from src.shell.desktop import DesktopFrame
            from src.shell.taskbar import TaskbarFrame

            # Explorer's bar has to give the strip up before ours claims
            # it, or Windows places ours above the strip the other one still
            # owns.  That handover is `ABM_SETSTATE`, which measured 2.4
            # SECONDS on this machine - Explorer moves the work area and
            # every window in the session is told about it - so the two are
            # chained through this event, on workers, rather than the shell
            # sitting inside Windows waiting for either of them.
            hidden = threading.Event()

            # The bar before the desktop, and both before anything is read
            # into them.  Starting a shell is the moment Windows is least
            # able to wait: the appbar and the shell hook make this process
            # something every other program's broadcasts go through, so the
            # rule here is that nothing slow happens between registering
            # them and getting back to the message loop.  What is slow -
            # the desktop's icons, the notification area, the user's startup
            # programs - is read afterwards, off this thread.
            if shell_setting('show_taskbar', True):
                self.taskbar = TaskbarFrame(self, parent=self.parent)
                self.taskbar.dock(after=hidden)

            if shell_setting('show_desktop', True):
                self.desktop = DesktopFrame(self, parent=self.parent,
                                            defer=True)
                self.desktop.cover_screen()

            self._running = True
            print("[TitanShell] shell started")
            # The shell has the screen: say so with the one sound Windows
            # itself would make here.
            shell_sound(SOUND_STARTUP)

            # Explorer's bar goes away only now, with the shell's own
            # windows built and shown and this thread about to go back to
            # the message loop.  While Explorer is switching its bar to
            # auto-hide, ANY window this thread creates and any message it
            # sends across the session waits for it: measured, the same
            # taskbar took 76 ms to build before that change and 2.6
            # SECONDS during it.  The work-area change costs what it costs;
            # what matters is that the shell spends it answering Windows
            # instead of queueing behind it.
            self._claim_the_strip(hidden)

            # Only when Titan really is the shell: with Explorer running,
            # these programs were started at logon already.  On a thread,
            # and after the shell is up, because `ShellExecute` on a program
            # that puts a window up can take seconds - and every one of them
            # would have been seconds of a shell that had stopped answering
            # Windows.
            self._start_startup_items()
            # The Start menu is built the first time it is asked for, which
            # is about 150 ms - noticeable exactly when the user has just
            # pressed the Windows key.  So it is built for them a couple of
            # seconds later instead, while nobody is waiting, and its slow
            # lists (the packaged apps, the Windows Start Menu) are warmed
            # on a thread of their own by `prefetch`.
            wx.CallLater(2500, self._prebuild_start_menu)
            return True
        except Exception as error:
            print(f"[TitanShell] could not start: {error}")
            import traceback
            traceback.print_exc()
            self.stop()
            return False

    def _claim_the_strip(self, hidden):
        """Put Explorer's bar away, on a worker, and let ours dock after it.

        `hidden` is what the taskbar's own appbar worker is waiting on: our
        bar must not be registered until Explorer's has given the strip up,
        or Windows places ours above it.
        """
        if not shell_setting('hide_system_taskbar', True):
            hidden.set()
            return None

        def work():
            try:
                self._explorer_hidden = win_shell.set_explorer_taskbar_visible(
                    False)
            except Exception as error:
                print(f"[TitanShell] could not hide Explorer's bar: {error}")
            finally:
                hidden.set()

        thread = threading.Thread(target=work, daemon=True,
                                  name='TitanShellExplorerBar')
        thread.start()
        return thread

    def _prebuild_start_menu(self):
        """Have the menu ready before the Windows key is pressed."""
        if not self._running or self.start_menu is not None:
            return False
        menu = self.get_start_menu()
        if menu is None:
            return False
        try:
            menu.prefetch()
        except Exception:
            pass
        return True

    def _start_startup_items(self, delay=1.5):
        """Run the user's startup programs, out of the shell's way.

        Staggered on purpose: a logon that launches six programs at once
        gives the machine six cold starts to do together, and the shell is
        what the user is looking at while that happens.
        """
        def work():
            import time
            time.sleep(delay)
            try:
                started = win_shell.run_startup_items()
                if started:
                    print(f"[TitanShell] {len(started)} startup items")
            except Exception as error:
                print(f"[TitanShell] startup items failed: {error}")

        thread = threading.Thread(target=work, daemon=True,
                                  name='TitanShellStartup')
        thread.start()
        return thread

    def stop(self, quiet=False):
        """Put the screen back exactly as it was.

        `quiet` skips the goodbye sound - a quick start's quick exit, or an
        exit that has already said it.  Nothing here waits for that sound:
        it is something to hear on the way out, not something to hold the
        program up, and Titan's own shutdown takes long enough that most of
        it is heard anyway.
        """
        was_running = self._running
        self._running = False

        if was_running and not quiet:
            shell_sound(SOUND_SHUTDOWN)

        # Restored whenever the shell was ever going to hide it, not only
        # when the flag says it managed to: hiding it happens on a worker
        # now, and a stop that overtakes that worker must still give the
        # user their taskbar back.  Showing a bar that was never hidden
        # costs nothing.
        if self._explorer_hidden or shell_setting('hide_system_taskbar', True):
            win_shell.set_explorer_taskbar_visible(True)
            self._explorer_hidden = False

        for window in (self.start_menu, self.taskbar, self.desktop):
            if window is None:
                continue
            try:
                # The bar and the desktop refuse to close for anybody else -
                # Alt+F4 and the system menu mean "shut down" there - so the
                # shell says plainly that this one is its own teardown.
                if hasattr(window, 'allow_close'):
                    window.allow_close()
                if hasattr(window, 'undock'):
                    window.undock()
                window.Destroy()
            except Exception as error:
                print(f"[TitanShell] could not close a shell window: {error}")

        self.start_menu = self.taskbar = self.desktop = None
        print("[TitanShell] shell stopped")

    def is_running(self):
        return self._running

    def own_hwnds(self):
        """Our own windows, which never belong on our own taskbar."""
        handles = []
        for window in (self.desktop, self.taskbar, self.start_menu):
            try:
                if window is not None:
                    handles.append(window.GetHandle())
            except Exception:
                pass
        return tuple(handles)

    def taskbar_height(self):
        if self.taskbar is not None:
            try:
                return self.taskbar.GetSize().height
            except Exception:
                pass
        return self.palette.taskbar_height

    # ------------------------------------------------------------------
    # The Start menu
    # ------------------------------------------------------------------
    def get_start_menu(self, create=True):
        if self.start_menu is not None:
            try:
                if self.start_menu.IsBeingDeleted():
                    self.start_menu = None
            except RuntimeError:
                self.start_menu = None
        if self.start_menu is None and create:
            try:
                # Which of the two menus, the way the taskbar properties
                # dialog asks it: the two-pane one, or the classic one it is
                # built on top of.
                from src.shell.a11y import shell_setting
                classic = str(shell_setting('start_menu_style', 'xp')).lower()                     == 'classic'
                if classic:
                    from src.ui.classic_start_menu import ClassicStartMenu
                    self.start_menu = ClassicStartMenu(self.parent)
                else:
                    from src.shell.start_menu import create_xp_start_menu
                    self.start_menu = create_xp_start_menu(self.parent,
                                                           shell=self)
            except Exception as error:
                print(f"[TitanShell] could not build the Start menu: {error}")
                import traceback
                traceback.print_exc()
                return None
            # Whichever menu it is, it is part of the shell and not one more
            # window for the user to tab past.
            try:
                win_shell.hide_from_alt_tab(self.start_menu.GetHandle())
            except Exception:
                pass
        return self.start_menu

    def toggle_start_menu(self):
        menu = self.get_start_menu()
        if menu is None:
            return False
        try:
            if menu.IsShown():
                menu.Hide()
            else:
                menu.show_menu()
            return True
        except Exception as error:
            print(f"[TitanShell] could not open the Start menu: {error}")
            return False

    def close_start_menu(self):
        if self.start_menu is not None and self.start_menu.IsShown():
            self.start_menu.Hide()
            return True
        return False

    def set_start_button_pressed(self, pressed):
        if self.taskbar is not None:
            try:
                self.taskbar.start_button.set_menu_open(pressed)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Things the shell's own menus ask for
    # ------------------------------------------------------------------
    def show_titan_window(self, view=None):
        """Bring Titan's own window forward - it is an application here."""
        frame = self.parent
        if frame is None:
            app = wx.GetApp()
            frame = app.GetTopWindow() if app else None
        if frame is None:
            return False
        try:
            frame.Iconize(False)
            frame.Show()
            frame.Raise()
            from src.titan_core.tce_system import force_foreground
            force_foreground(frame)
            if view == 'apps' and hasattr(frame, 'show_app_list'):
                frame.show_app_list()
            elif view == 'games' and hasattr(frame, 'show_game_list'):
                frame.show_game_list()
            return True
        except Exception as error:
            print(f"[TitanShell] could not show the Titan window: {error}")
            return False

    def open_settings(self):
        """Settings, opened on the shell's own page."""
        try:
            frame = self.parent
            settings_frame = getattr(frame, 'settings_frame', None)
            if settings_frame is None:
                from src.ui.settingsgui import SettingsFrame
                settings_frame = SettingsFrame(None, title=_("Settings"))
            settings_frame.Show()
            settings_frame.Raise()
            return True
        except Exception as error:
            print(f"[TitanShell] could not open settings: {error}")
            return False

    def open_explorer(self, path=None, new_window=False):
        """The shell's own file browser - what My Computer opens into.

        It is a window of Titan's, not Explorer's: the desktop, the Start
        menu and Windows+E all come here, so a folder is always something
        the user can read with the keyboard and with a screen reader.
        """
        try:
            from src.shell.explorer import open_explorer as open_browser
            return open_browser(path, parent=self.parent,
                                new_window=new_window)
        except Exception as error:
            print(f"[TitanShell] could not open the file browser: {error}")
            import traceback
            traceback.print_exc()
            return None

    def open_programs_folder(self):
        import os
        path = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft',
                            'Windows', 'Start Menu', 'Programs')
        return win_shell.open_path(path)

    def show_window_switcher(self):
        try:
            from src.ui.window_switcher import show_window_switcher
            show_window_switcher(self.parent)
            return True
        except Exception as error:
            print(f"[TitanShell] window switcher failed: {error}")
            return False

    def focus_desktop(self):
        """Windows+D and Windows+M: the desktop is shown and read."""
        if self.desktop is not None:
            return self.desktop.bring_up()
        # No Titan desktop (the shell is off, or it was told not to draw
        # one) - the icons are still Windows' own, and the shortcut has to
        # land on them rather than doing nothing.
        return win_shell.focus_windows_desktop()

    def focus_taskbar(self):
        """Windows+T: the keyboard goes to the window buttons."""
        if self.taskbar is not None:
            return self.taskbar.focus_first_task()
        return False

    def focus_tray(self):
        """Windows+B: the keyboard goes to the notification area."""
        if self.taskbar is not None:
            return self.taskbar.focus_tray()
        return False

    def focus_taskbar_or_tray(self, tray=False):
        """Whichever of the two the bar can offer, if there is a bar."""
        if self.taskbar is None:
            return False
        return self.taskbar.focus_tray() if tray else             self.taskbar.focus_first_task()

    def focus_start_button(self):
        if self.taskbar is not None:
            return self.taskbar.focus_start_button()
        return False

    def return_focus_to_desktop(self):
        """Escape on the taskbar hands the keyboard back."""
        if self.taskbar is not None:
            return self.taskbar.hand_keyboard_back()
        return self.focus_desktop()

    def show_desktop(self):
        """Minimise everything (the Show desktop button, Windows+D).

        The keyboard follows the windows down: whether the bar did the work
        or not, what the user asked for is the desktop, so that is where
        they are put - after a moment, because the windows are asked to
        minimise rather than made to.
        """
        if self.taskbar is not None:
            self.taskbar.toggle_show_desktop()
            return True
        win_shell.minimize_all(self.own_hwnds())
        wx.CallLater(150, self.focus_desktop)
        return True

    # ------------------------------------------------------------------
    # Refreshing
    # ------------------------------------------------------------------
    def refresh(self, skin_changed=False):
        """Re-read the desktop, the windows and, if asked, the skin."""
        if skin_changed:
            self.palette = luna.get_palette(refresh=True)
        # The desktop off the GUI thread: a refresh re-reads every icon,
        # and F5 must not be a moment of a shell that has stopped answering
        # Windows.
        for window, method in ((self.desktop, 'refresh_async'),
                               (self.taskbar, 'refresh_windows')):
            if window is None:
                continue
            try:
                getattr(window, method)()
            except Exception:
                pass
        if self.taskbar is not None:
            try:
                self.taskbar.refresh_tray()
            except Exception:
                pass
        if skin_changed:
            for window in (self.desktop, self.taskbar):
                if window is None:
                    continue
                try:
                    window.apply_palette(self.palette)
                except Exception:
                    pass
            if self.start_menu is not None:
                try:
                    self.start_menu.apply_skin_settings()
                except Exception:
                    pass
        return True


# ---------------------------------------------------------------------------
# Module level API - what the rest of Titan calls
# ---------------------------------------------------------------------------


def get_shell(create=False, parent=None):
    global _shell
    with _lock:
        if _shell is None and create:
            _shell = TitanShell(parent=parent)
        return _shell


def is_shell_running():
    shell = get_shell()
    return bool(shell and shell.is_running())


def start_shell(parent=None, force=False):
    """Start the shell if the settings ask for it (or `force`)."""
    if not force and not desktop_shell_enabled():
        return False
    shell = get_shell(create=True, parent=parent)
    if shell.parent is None and parent is not None:
        shell.parent = parent
    return shell.start()


def stop_shell(quiet=False):
    """Take the shell down. Called twice on the way out, and idempotent."""
    global _shell
    with _lock:
        shell = _shell
        _shell = None
    if shell is None:
        return False
    shell.stop(quiet=quiet)
    return True


def toggle_start_menu():
    shell = get_shell()
    if shell is None or not shell.is_running():
        return False
    return shell.toggle_start_menu()


def show_desktop():
    shell = get_shell()
    if shell is None or not shell.is_running():
        return False
    return shell.show_desktop()


def focus_tray():
    """Windows+B, when the shell is up."""
    shell = get_shell()
    if shell is None or not shell.is_running():
        return False
    return shell.focus_tray()


def focus_desktop():
    """Where Windows+D and Windows+M put the keyboard.

    This one answers whether or not the Titan shell is up: the desktop is
    the one place that is always there, so the shortcut has to land on it
    either way - Titan's own icons when Titan is drawing them, and Windows'
    when it is not.
    """
    shell = get_shell()
    if shell is not None and shell.is_running():
        return shell.focus_desktop()
    return win_shell.focus_windows_desktop()


def open_explorer(path=None, new_window=False):
    """Open the shell's file browser, starting the shell's own window only.

    It works with the desktop shell switched off as well: the browser is a
    window like any other, and "Modify system interface" is about the
    desktop and the bar rather than about being able to read a folder.
    """
    shell = get_shell(create=True)
    if shell is None:
        from src.shell.explorer import open_explorer as open_browser
        return open_browser(path, new_window=new_window)
    return shell.open_explorer(path, new_window=new_window)


def refresh_shell(skin_changed=False):
    shell = get_shell()
    if shell is None or not shell.is_running():
        return False
    return shell.refresh(skin_changed=skin_changed)


def apply_shell_settings(parent=None):
    """Start, stop or refresh the shell to match the settings.

    Called after the settings dialog is saved, so turning the mode on shows
    the desktop straight away instead of on the next start.
    """
    should_run = desktop_shell_enabled()
    running = is_shell_running()
    if should_run and not running:
        return start_shell(parent=parent)
    if running and not should_run:
        return stop_shell()
    if running:
        return refresh_shell(skin_changed=True)
    return False
