# -*- coding: utf-8 -*-
"""Screen-reader menu for Titan Access (NVDA-style Insert+C menu).

A small popup menu, opened with the reader modifier + ``C`` (Insert+C), that
collects reader-level actions the user would otherwise have to hunt for in TCE:

* **Screen reader settings** -- jumps straight to the Titan Access settings
  category inside the TCE settings window (``tce/settings`` -> the screen-reader
  category), pre-selected so the user lands on the right page.
* **Return to the Titan environment** -- only shown while the launcher is
  minimised to the tray; restores it.

The menu is a native ``wx.Menu``, so the running reader announces its items
through the normal UIA menu path as the user arrows through them. Building and
showing wx widgets must happen on the GUI thread, so :func:`show` is always
marshalled there with ``wx.CallAfter`` by the engine.

When the launcher is minimised its frame is hidden and cannot host a popup, so
we spawn a tiny, effectively invisible top-level frame to host the menu and
destroy it once the menu is dismissed. This keeps the menu reachable (and the
"return to Titan" item usable) even from the tray.
"""

from titan_access.localization import L

try:
    import wx
    WX_AVAILABLE = True
except Exception:  # pragma: no cover - headless / no display
    wx = None
    WX_AVAILABLE = False


def _find_launcher_frame():
    """Return the running TCE launcher frame, or ``None``.

    The launcher (``src/ui/gui.py`` ``TitanApp``) is the top-level window that
    carries both a ``settings_frame`` reference and the ``restore_from_tray``
    method (see ``main.py``). We match on those rather than the class so this
    module stays import-light and independent of the launcher internals.
    """
    if not WX_AVAILABLE:
        return None
    try:
        for win in wx.GetTopLevelWindows():
            if (hasattr(win, "settings_frame")
                    and hasattr(win, "restore_from_tray")):
                return win
    except Exception:
        pass
    try:
        return wx.GetApp().GetTopWindow()
    except Exception:
        return None


def _open_settings_category(launcher):
    """Open TCE settings pre-selected on the Titan Access category."""
    category = L("settings.categoryName")
    settings_frame = getattr(launcher, "settings_frame", None) if launcher else None
    try:
        if settings_frame is not None and hasattr(settings_frame, "open_at_category"):
            settings_frame.open_at_category(category)
            return
        # Fallback: just show whatever settings window we can reach.
        if settings_frame is not None:
            settings_frame.Show(True)
            settings_frame.Raise()
    except Exception as e:  # pragma: no cover - host dependent
        print(f"[TitanAccess] open settings category error: {e}")


def _restore_launcher(launcher):
    """Restore the launcher window from the system tray."""
    try:
        if launcher is not None and hasattr(launcher, "restore_from_tray"):
            launcher.restore_from_tray()
    except Exception as e:  # pragma: no cover - host dependent
        print(f"[TitanAccess] restore launcher error: {e}")


def _set_menu_host(engine, hwnd):
    """Tell the engine which window hosts our popup, so its focus is not read."""
    try:
        if engine is not None:
            engine._menu_host_hwnd = int(hwnd or 0)
    except Exception:
        pass


def _show_on_gui_thread(engine):
    """Build and pop the reader menu. MUST run on the wx GUI thread."""
    if not WX_AVAILABLE:
        return

    launcher = _find_launcher_frame()
    # The launcher is "minimised" when its window is hidden in the tray.
    minimized = False
    try:
        if launcher is not None:
            minimized = not launcher.IsShown()
    except Exception:
        minimized = False

    menu = wx.Menu()

    settings_item = menu.Append(wx.ID_ANY, L("readerMenu.settings"))
    menu.Bind(wx.EVT_MENU,
              lambda _evt: _open_settings_category(launcher), settings_item)

    if minimized:
        restore_item = menu.Append(wx.ID_ANY, L("readerMenu.returnToTitan"))
        menu.Bind(wx.EVT_MENU,
                  lambda _evt: _restore_launcher(launcher), restore_item)

    # Insert+C is a GLOBAL reader gesture: it can fire while focus is in any
    # application, not just the launcher. A popup menu only receives keyboard
    # input if its host window is foreground, so we always host the menu on a
    # dedicated tiny STAY_ON_TOP frame that we bring to the front -- hosting on
    # the launcher would silently fail to take focus whenever it sits in the
    # background. The frame is parked at the centre of the primary display so a
    # sighted helper can also see the menu; the popup opens at its origin.
    host = wx.Frame(None, style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP,
                    size=(1, 1))
    try:
        dx, dy, dw, dh = wx.Display().GetGeometry()
        host.SetPosition((dx + dw // 2, dy + dh // 2))
    except Exception:
        pass
    host.Show()
    try:
        host.Raise()
        host.SetFocus()
    except Exception:
        pass

    # Stop the reader from announcing the empty host window ("panel") while the
    # menu is up; the menu items themselves (a separate menu window) still read.
    try:
        _set_menu_host(engine, host.GetHandle())
    except Exception:
        pass

    try:
        host.PopupMenu(menu)
    except Exception as e:  # pragma: no cover - host dependent
        print(f"[TitanAccess] reader menu popup error: {e}")
    finally:
        _set_menu_host(engine, 0)
        try:
            menu.Destroy()
        except Exception:
            pass
        try:
            host.Destroy()
        except Exception:
            pass


def show(engine):
    """Open the screen-reader menu.

    Marshals the wx popup onto the GUI thread. The menu title ("Czytnik ekranu.
    Menu." / "Screen reader. Menu.") is announced together with the first option
    by the menu tracker when the popup opens (so the title is never cut), and the
    empty host window is kept silent via the engine's menu-host guard. Safe to
    call from the engine worker thread.
    """
    if not WX_AVAILABLE:
        return
    try:
        wx.CallAfter(_show_on_gui_thread, engine)
    except Exception as e:  # pragma: no cover - host dependent
        print(f"[TitanAccess] reader menu schedule error: {e}")
