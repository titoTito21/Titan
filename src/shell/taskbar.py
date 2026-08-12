# -*- coding: utf-8 -*-
"""
The taskbar: the Start button, the window buttons, the notification area and
the clock, docked along one edge of the screen as a real appbar.

Two things make it a taskbar rather than a strip of colour.  It registers as
an appbar, so a maximised window stops above it instead of covering it.  And
it is driven by the shell hook - Windows posts a message when a window
appears, disappears, is activated or flashes - so the buttons change with the
system instead of a second later.

The keyboard model is XP's own.  Tab and Shift+Tab step between the bar's
*groups* - the Start button, the quick launch buttons, the window buttons and
the notification area - and the arrows move inside whichever group has the
focus, with Home and End going to its ends.  Shift+F10 opens a window's menu
(Restore, Minimise, Maximise, Close); Escape hands the keyboard back.

None of that could work before the bar became the foreground window:
`SetFocus` only moves the focus inside the window that is already active, so
a bar shown with `ShowWithoutActivating` and never activated swallowed every
key.  `activate()` is what every entry point into the bar now goes through.
"""

import threading
import time

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import luna, win_shell
from src.shell.a11y import (ROLE_BUTTON, ROLE_LISTITEM, ROLE_TOOLBAR,
                            SHELL_NAME, STATE_FOCUSABLE, STATE_FOCUSED,
                            STATE_PRESSED, edge_cue, shell_setting)
from src.shell.controls import (IconTextControl, ShellControl, TextControl,
                                bitmap_from_icon_handle)
from src.shell.quick_launch import (QuickLaunchButton, quick_launch_folder,
                                    quick_launch_items)
from src.titan_core.translation import _

try:
    from src.accessibility.messages import announce_shell_group as announce_group
except Exception:  # pragma: no cover - the shell works without the helper
    def announce_group(_label):
        return False

START_BUTTON_WIDTH = 99          # XP's own, at 96 dpi
TASK_BUTTON_MAX_WIDTH = 160
TASK_BUTTON_MIN_WIDTH = 40
CLOCK_WIDTH = 62
TRAY_ICON_WIDTH = 22
TRAY_ICON_MIN_WIDTH = 14
# At most this much of the bar may go to the notification area.
TRAY_MAX_SHARE = 0.45
# Every this many poll ticks (3s each) the notification area is re-read.
TRAY_POLL_TICKS = 10
# The Show Desktop button, which lives at the end of the notification area -
# where ReactOS' CTrayShowDesktopButton is - and not next to Start.
SHOW_DESKTOP_WIDTH = 22
# One quick launch button: XP's is the icon and nothing else.
QUICK_LAUNCH_WIDTH = 24

# How thick the bar is standing on its side.  A vertical taskbar has to be
# wide enough for the Start button, which is what sets this.
VERTICAL_THICKNESS = 100
# One window button on a vertical bar, where they stack instead of sharing a
# row.
VERTICAL_TASK_HEIGHT = 24

# What a screen reader says when Tab arrives in one of the bar's groups.
# The bar cannot speak - it is the system interface, and a screen reader is
# already reading it - so the group's name is put in front of the control's
# own name for that one announcement, which is how a Titan window's tab bar
# announces the tab before the list under it.
GROUP_LABELS = {
    'start': lambda: _("Start"),
    'quicklaunch': lambda: _("Dock"),
    'tasks': lambda: _("Open windows"),
    'tray': lambda: _("System tray"),
}


def group_label(name):
    """The words for one group of the bar, in the user's language."""
    maker = GROUP_LABELS.get(name)
    return maker() if maker else ''


# The edges, by the name a setting or an action uses for them.
POSITION_EDGES = {
    'bottom': win_shell.ABE_BOTTOM,
    'top': win_shell.ABE_TOP,
    'left': win_shell.ABE_LEFT,
    'right': win_shell.ABE_RIGHT,
}

# Auto-hide, with ReactOS' own timings (traywnd.cpp): a long wait before it
# goes away, a short one before it comes back, and a 10 ms animation whose
# steps differ in each direction - hiding creeps, showing snaps.
AUTOHIDE_DELAY_HIDE = 2000
AUTOHIDE_DELAY_SHOW = 50
AUTOHIDE_INTERVAL_ANIMATING = 10
AUTOHIDE_SPEED_SHOW = 10
AUTOHIDE_SPEED_HIDE = 1
AUTOHIDE_HIDDEN = 0
AUTOHIDE_SHOWING = 1
AUTOHIDE_SHOWN = 2
AUTOHIDE_HIDING = 3
# What is left of the bar when it has hidden itself: enough to put the
# pointer on, and enough that the bar never disappears entirely from a
# screen reader's view of the desktop.
AUTOHIDE_SLIVER = 2


class StartButton(ShellControl):
    """The green capsule.  Opens the Start menu; also answers the Windows key."""

    def __init__(self, parent, on_press):
        super().__init__(parent, size=(START_BUTTON_WIDTH, -1),
                         name=_("Start"))
        self._on_press = on_press
        self.accessible_action = _("Open the Start menu")
        self._menu_open = False
        self.set_tooltip(_("Click here to begin"))

    def show_context_menu(self):
        """XP's own Start-button menu, cut down to what Titan can honour."""
        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("&Open"))
        explore = menu.Append(wx.ID_ANY, _("&Explore"))
        menu.AppendSeparator()
        properties = menu.Append(wx.ID_ANY, _("P&roperties"))
        self.Bind(wx.EVT_MENU, lambda event: self.shell_activate(), open_item)
        self.Bind(wx.EVT_MENU,
                  lambda event: self.GetTopLevelParent().shell.open_programs_folder(),
                  explore)
        self.Bind(wx.EVT_MENU,
                  lambda event: self.GetTopLevelParent().shell.open_settings(),
                  properties)
        self.PopupMenu(menu)
        menu.Destroy()

    def set_menu_open(self, is_open):
        if self._menu_open != bool(is_open):
            self._menu_open = bool(is_open)
            self.Refresh()

    def shell_state(self):
        state = STATE_FOCUSABLE
        if self.HasFocus():
            state |= STATE_FOCUSED
        if self._menu_open:
            state |= STATE_PRESSED
        return state

    def shell_activate(self):
        if callable(self._on_press):
            self._on_press()

    def paint(self, dc, rect):
        state = 'pressed' if self._menu_open else self.state_name()
        label = _("start") if self.palette.style == 'luna' else _("Start")
        luna.draw_start_button(dc, wx.Rect(0, 0, rect.width, rect.height),
                               self.palette, state=state,
                               focused=self.HasFocus(), label=label)


class TaskButton(IconTextControl):
    """One open window.  Press to raise it, press again to minimise it."""

    accessible_role = ROLE_LISTITEM

    def __init__(self, parent, window, taskbar):
        super().__init__(parent, text=window.title, name=window.title)
        self.window = window
        self.taskbar = taskbar
        self.accessible_action = _("Switch to this window")
        self.set_tooltip(window.title)
        self._icon_asked_at = 0.0
        self._load_icon()

    def _load_icon(self):
        """The window's own icon, which is what a task button shows."""
        self._icon_asked_at = time.monotonic()
        try:
            handle = win_shell.window_icon_handle(self.window.hwnd)
        except Exception:
            handle = 0
        self.set_icon(bitmap_from_icon_handle(handle, 16) if handle else None)

    # How long to leave a window that gave no icon alone.  Asking costs a
    # message into its process, and the poll comes round every three
    # seconds: a program that answers nothing (or has hung) would otherwise
    # be asked twenty times a minute, for ever.
    ICON_RETRY_SECONDS = 30.0

    def update(self, window):
        changed = window.hwnd != self.window.hwnd
        self.window = window
        if window.title != self._text:
            self.set_text(window.title)
            self.set_tooltip(window.title)
        if changed:
            self._load_icon()
        elif self._icon is None and (time.monotonic() - self._icon_asked_at
                                     > self.ICON_RETRY_SECONDS):
            # A program that had no icon when it started may have one now,
            # so an empty one is worth asking about again - occasionally.
            self._load_icon()
        self.Refresh()

    def middle_activate(self):
        """Middle click closes the window, as it does on later taskbars."""
        self._then_refresh(win_shell.close_window, self.window.hwnd)

    def button_state(self):
        if self.window.flashing:
            return 'flashing'
        if self.window.active and not self.window.minimized:
            return 'active'
        return self.state_name()

    def shell_description(self):
        if self.window.flashing:
            return _("needs attention")
        if self.window.minimized:
            return _("minimised")
        if self.window.active:
            return _("active")
        return ''

    def shell_state(self):
        state = STATE_FOCUSABLE
        if self.HasFocus():
            state |= STATE_FOCUSED
        if self.window.active and not self.window.minimized:
            state |= STATE_PRESSED
        return state

    def shell_activate(self):
        """XP's rule: the active window's button minimises it."""
        hwnd = self.window.hwnd
        if self.window.active and not self.window.minimized:
            win_shell.minimize_window(hwnd)
        else:
            win_shell.activate_window(hwnd)
        wx.CallLater(120, self.taskbar.refresh_windows)

    def show_context_menu(self):
        menu = wx.Menu()
        restore = menu.Append(wx.ID_ANY, _("&Restore"))
        minimise = menu.Append(wx.ID_ANY, _("Mi&nimise"))
        maximise = menu.Append(wx.ID_ANY, _("Ma&ximise"))
        menu.AppendSeparator()
        close = menu.Append(wx.ID_ANY, _("&Close"))

        hwnd = self.window.hwnd
        self.Bind(wx.EVT_MENU,
                  lambda event: self._then_refresh(win_shell.restore_window, hwnd),
                  restore)
        self.Bind(wx.EVT_MENU,
                  lambda event: self._then_refresh(win_shell.minimize_window, hwnd),
                  minimise)
        self.Bind(wx.EVT_MENU,
                  lambda event: self._then_refresh(win_shell.maximize_window, hwnd),
                  maximise)
        self.Bind(wx.EVT_MENU,
                  lambda event: self._then_refresh(win_shell.close_window, hwnd),
                  close)
        self.PopupMenu(menu)
        menu.Destroy()

    def _then_refresh(self, action, hwnd):
        try:
            action(hwnd)
        finally:
            wx.CallLater(150, self.taskbar.refresh_windows)


class TrayIconButton(ShellControl):
    """One notification-area icon, named after its tooltip.

    The tray is the least accessible part of Windows - on Windows 11 it is
    not even a Win32 control any more - so naming each icon and giving it
    Enter (activate) and Shift+F10 (its own menu) is most of what makes it
    usable at all.  The icons come from `src.system.tray_icons`, which reads
    whichever notification area this Windows actually has.
    """

    def __init__(self, parent, icon, taskbar=None):
        name = (getattr(icon, 'text', '') or getattr(icon, 'tooltip', '')
                or _("Notification icon"))
        if getattr(icon, 'hidden', False):
            name = _("{icon} (hidden)").format(icon=name)
        super().__init__(parent, size=(TRAY_ICON_WIDTH, -1), name=name)
        self.icon = icon
        self.taskbar = taskbar
        self._bitmap = None
        self._load_bitmap()
        self.accessible_action = (_("Show the hidden icons")
                                  if getattr(icon, 'chevron', False)
                                  else _("Activate"))
        self.set_tooltip(name)

    def _load_bitmap(self):
        """The icon's real picture, when this Windows will give one up."""
        try:
            handle = self.icon.icon_handle()
        except Exception:
            handle = 0
        self._bitmap = bitmap_from_icon_handle(handle, 16) if handle else None

    def update(self, icon):
        """Point the button at the same icon in the state it is in now."""
        self.icon = icon
        self._load_bitmap()
        name = (getattr(icon, 'text', '') or getattr(icon, 'tooltip', '')
                or _("Notification icon"))
        if getattr(icon, 'hidden', False):
            name = _("{icon} (hidden)").format(icon=name)
        if name != self.accessible_name:
            self.accessible_name = name
            self.refresh_accessible_name()
            self.set_tooltip(name)
            self.Refresh()

    def _background_rect(self, rect):
        return rect

    def paint(self, dc, rect):
        # The tray's own gradient, not the bar's, runs behind these.
        luna.draw_gradient(dc, rect, self.palette['tray_gradient'])
        if self._bitmap is not None and self._bitmap.IsOk():
            # The real icon whenever there is one to draw.
            dc.DrawBitmap(self._bitmap,
                          (rect.width - self._bitmap.GetWidth()) // 2,
                          (rect.height - self._bitmap.GetHeight()) // 2, True)
        else:
            # Otherwise its first letter, which at least tells two icons
            # apart at a glance - and which the screen reader never sees,
            # because the button is named after the whole tooltip.
            dc.SetFont(self.palette.font(size=7))
            dc.SetTextForeground(self.palette['clock_text'])
            initial = (self.accessible_name or '?')[:1].upper()
            width, height = dc.GetTextExtent(initial)
            dc.DrawText(initial, (rect.width - width) // 2,
                        (rect.height - height) // 2)
        if self.HasFocus():
            dc.SetPen(wx.Pen(self.palette['clock_text'], 1, wx.PENSTYLE_DOT))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(1, 2, rect.width - 2, rect.height - 4)

    def shell_activate(self):
        try:
            if getattr(self.icon, 'chevron', False) and self.taskbar:
                # "Show hidden icons" belongs in the bar rather than in a
                # flyout the user then has to go and find: the hidden icons
                # are read and put in beside the visible ones.
                self.taskbar.show_hidden_tray_icons()
                return
            self.icon.left_click()
        except Exception as error:
            print(f"[TitanShell] tray icon activation failed: {error}")

    def show_context_menu(self):
        try:
            self.icon.right_click()
        except Exception as error:
            print(f"[TitanShell] tray icon menu failed: {error}")


class ShowDesktopButton(ShellControl):
    """The quick-launch button that clears the screen and puts it back."""

    def __init__(self, parent, taskbar):
        super().__init__(parent, size=(22, -1), name=_("Show desktop"))
        self.taskbar = taskbar
        self.accessible_action = _("Show the desktop")
        self.set_tooltip(_("Show desktop"))

    def paint(self, dc, rect):
        luna.draw_task_button(dc, wx.Rect(0, 3, rect.width - 2,
                                          rect.height - 6),
                              self.palette, state=self.state_name(),
                              focused=self.HasFocus())
        dc.SetPen(wx.Pen(self.palette['task_text']))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(6, rect.height // 2 - 4, 9, 8)

    def shell_activate(self):
        self.taskbar.toggle_show_desktop()


class ClockControl(TextControl):
    """The clock, named with the full time and date so it reads as one."""

    def __init__(self, parent):
        super().__init__(parent, text='', name=_("Clock"),
                         colour_key='clock_text', size=(CLOCK_WIDTH, -1))
        self.accessible_action = _("Show the date")
        self.update_time()

    def set_text(self, text, name=None):
        super().set_text(text, name=name)
        # XP's clock tip is the full date; the accessible name says the same
        # thing, so sighted and screen-reader users are told the same thing.
        self.set_tooltip(name or text)

    def update_time(self):
        now = time.localtime()
        show_seconds = bool(shell_setting('clock_seconds', False))
        fmt = '%H:%M:%S' if show_seconds else '%H:%M'
        text = time.strftime(fmt, now)
        # The name carries the date too: a screen reader user asking the
        # clock what time it is should not have to hunt for the date.
        name = time.strftime('%H:%M, %A, %d %B %Y', now)
        self.set_text(text, name=name)

    def shell_activate(self):
        wx.MessageBox(time.strftime('%A, %d %B %Y, %H:%M:%S'),
                      _("Date and time"), wx.OK | wx.ICON_INFORMATION, self)


class TaskbarFrame(wx.Frame):
    """The bar itself."""

    def __init__(self, shell, parent=None):
        style = (wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_NONE
                 | wx.FRAME_TOOL_WINDOW)
        # The bar is the shell, so it carries the shell's own name rather
        # than being announced as a piece of the Titan application.
        super().__init__(parent, title=SHELL_NAME, style=style)

        self.shell = shell
        self.palette = luna.get_palette()
        self.SetName(SHELL_NAME)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self._appbar = None
        self._appbar_thread = None
        self._hook = None
        self._windows = []
        self._buttons = {}
        self._tray_buttons = []
        self._existing_tray = {}
        self._tray_expanded = False
        self._group_memory = {}
        self._desktop_shown = False
        self._minimised_by_show_desktop = []
        self._last_foreground = 0
        self._previous_foreground = 0
        self._refresh_pending = False
        self._auto_hide_state = AUTOHIDE_SHOWN
        self._auto_hide_offset = 0
        self._auto_hide_timer = None
        self._track_timer = None

        self._build()
        self._layout_bar()

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self.Bind(wx.EVT_SIZE, lambda event: (self._layout_bar(),
                                              self.Refresh()))
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        # A bar that lives in the background is brought to the front to be
        # used and put back the moment it is done with, so it is never left
        # standing over the window the user went back to.
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)
        for target in (self, self.task_area, self.tray_area):
            target.Bind(wx.EVT_RIGHT_UP, self._on_bar_context_menu)

        self._clock_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._clock_timer)
        self._clock_timer.Start(1000)

        # A poll is the safety net, not the mechanism: the shell hook does
        # the work, and this only catches what a hook cannot see (a title
        # changed without a redraw notification, a hook that failed to
        # install at all).
        self._poll_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_poll, self._poll_timer)
        self._poll_timer.Start(3000)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self):
        self.start_button = StartButton(self, self.shell.toggle_start_menu)
        # The quick launch band: the real folder's launchers, between the
        # Start button and the window buttons, as on the bar it copies.
        self.quick_launch_area = wx.Window(self, style=wx.TAB_TRAVERSAL)
        self.quick_launch_area.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.quick_launch_area.SetName(group_label('quicklaunch'))
        self.quick_launch_area.taskbar = self
        self.quick_launch_area.Bind(wx.EVT_ERASE_BACKGROUND,
                                    lambda event: None)
        self.quick_launch_area.Bind(wx.EVT_PAINT,
                                    self._on_quick_launch_paint)
        self.quick_launch_area.Bind(wx.EVT_RIGHT_UP,
                                    self._on_quick_launch_menu)
        self._quick_launch_buttons = []
        self.task_area = wx.Window(self, style=wx.TAB_TRAVERSAL)
        self.task_area.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.task_area.SetName(group_label('tasks'))
        self.task_area.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self.task_area.Bind(wx.EVT_PAINT, self._on_task_area_paint)
        self.tray_area = wx.Window(self, style=wx.TAB_TRAVERSAL)
        self.tray_area.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.tray_area.SetName(group_label('tray'))
        self.tray_area.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self.tray_area.Bind(wx.EVT_PAINT, self._on_tray_paint)
        self.clock = ClockControl(self.tray_area)
        # Show Desktop is the last thing on the bar, after the clock, which
        # is where ReactOS puts it and where Shift+Tab from the desktop
        # expects to arrive.
        self.show_desktop_button = ShowDesktopButton(self.tray_area, self)
        self.refresh_quick_launch()

    def _on_quick_launch_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self.quick_launch_area)
        rect = wx.Rect(0, 0, *self.quick_launch_area.GetSize())
        luna.draw_gradient(dc, rect, self.palette['taskbar_gradient'])

    def _on_quick_launch_menu(self, event):
        """The band's own menu, as Explorer has it for a toolbar."""
        menu = wx.Menu()
        open_folder = menu.Append(wx.ID_ANY, _("Open the &folder"))
        refresh = menu.Append(wx.ID_ANY, _("&Refresh"))
        self.Bind(wx.EVT_MENU,
                  lambda e: win_shell.open_path(quick_launch_folder() or ''),
                  open_folder)
        self.Bind(wx.EVT_MENU, lambda e: self.refresh_quick_launch(), refresh)
        self.quick_launch_area.PopupMenu(menu)
        menu.Destroy()

    def refresh_quick_launch(self):
        """Rebuild the band from the folder as it stands now.

        Buttons are reused rather than recreated, the same way the window
        buttons are, so a refresh cannot throw the keyboard out of the band.
        """
        items = quick_launch_items() if self.shows_quick_launch() else []
        buttons = self._quick_launch_buttons
        for index, item in enumerate(items):
            if index < len(buttons):
                buttons[index].update(item)
            else:
                buttons.append(QuickLaunchButton(self.quick_launch_area,
                                                 item))
        while len(buttons) > len(items):
            button = buttons.pop()
            try:
                button.Destroy()
            except Exception:
                pass
        self._layout_bar()
        self.quick_launch_area.Refresh()

    def _on_task_area_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self.task_area)
        rect = wx.Rect(0, 0, *self.task_area.GetSize())
        luna.draw_gradient(dc, rect, self.palette['taskbar_gradient'])

    def _on_tray_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self.tray_area)
        rect = wx.Rect(0, 0, *self.tray_area.GetSize())
        luna.draw_tray_background(dc, rect, self.palette)

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        rect = wx.Rect(0, 0, *self.GetSize())
        luna.draw_taskbar_background(dc, rect, self.palette)

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Which edge the bar is on, and how thick it is
    # ------------------------------------------------------------------
    def position_name(self):
        """The edge the bar is docked to, by name."""
        name = str(shell_setting('taskbar_position', 'bottom')).lower()
        return name if name in POSITION_EDGES else 'bottom'

    def edge(self):
        return POSITION_EDGES[self.position_name()]

    def is_horizontal(self):
        return self.edge() in (win_shell.ABE_TOP, win_shell.ABE_BOTTOM)

    def thickness(self):
        """How deep the bar is: its height lying down, its width standing up."""
        if self.is_horizontal():
            return max(20, int(shell_setting('taskbar_height',
                                             self.palette.taskbar_height)))
        return max(48, int(shell_setting('taskbar_width',
                                         VERTICAL_THICKNESS)))

    def auto_hide(self):
        return bool(shell_setting('taskbar_auto_hide', False))

    def always_on_top(self):
        """Whether the bar covers other windows, or lives behind them.

        Off by default, unlike XP's own: the appbar has already reserved
        the strip the bar stands on, so nothing the user opens covers it
        anyway, and a bar that is not topmost can never end up over the
        Titan window, over a full-screen game or over a dialog it did not
        put up.
        """
        return bool(shell_setting('taskbar_on_top', False))

    def shows_quick_launch(self):
        return bool(shell_setting('show_quick_launch', True))

    def shows_clock(self):
        return bool(shell_setting('show_clock', True))

    def shows_show_desktop(self):
        return bool(shell_setting('show_desktop_button', True))

    def apply_always_on_top(self):
        """Keep the bar over other windows, or let them cover it.

        The style is set on the window rather than at construction, because
        this is a setting the user changes while the bar is already up.
        """
        if self.always_on_top():
            self._set_z_order(topmost=True)
        else:
            self.send_to_background()

    def send_to_background(self):
        """Put the bar behind every window, and the desktop behind the bar.

        "In the background" is a place in the z-order, not a state.  Giving
        up topmost is only half of it: a window that was topmost and is
        merely told it is not stays exactly where it was in the stack, so
        the bar is sent to the bottom as well - and the desktop, which is
        the bottom by definition, is put back underneath it afterwards, or
        the thing the bar was just put behind would be covering it.  Every
        move carries SWP_NOACTIVATE, so the bar changes places without ever
        taking the keyboard.
        """
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            # The frame has already gone; a queued call must not raise into
            # wx's event loop.
            return
        self._set_z_order(topmost=False, bottom=True)
        desktop = getattr(self.shell, 'desktop', None)
        if desktop is not None:
            try:
                desktop.send_to_back()
            except Exception:
                pass

    def is_locked(self):
        return bool(shell_setting('taskbar_locked', True))

    def _shown_rect(self):
        """Where the bar sits when it is all the way out."""
        width, height = win_shell.screen_size()
        thickness = self.thickness()
        edge = self.edge()
        if edge == win_shell.ABE_BOTTOM:
            return (0, height - thickness, width, thickness)
        if edge == win_shell.ABE_TOP:
            return (0, 0, width, thickness)
        if edge == win_shell.ABE_LEFT:
            return (0, 0, thickness, height)
        return (width - thickness, 0, thickness, height)

    def dock(self, after=None):
        """Take the strip along the chosen edge of the screen and hold it.

        The bar is on the screen when this returns; **the appbar is
        registered on a worker**.  `ABM_NEW` is a call into Explorer that
        moves the work area and tells every top-level window about it -
        close to a second on this machine - and the shell must not be inside
        it, because a shell that is not answering Windows is a machine that
        feels stuck rather than a slow Titan.

        `after` is the event that says Explorer's own bar has gone; ours has
        to be registered after that or Windows places it above the strip the
        other one still owns.
        """
        self.SetSize(*self._shown_rect())

        if IS_WINDOWS:
            try:
                self._hook = win_shell.ShellHook(
                    self.GetHandle(),
                    on_shell_event=self._on_shell_event,
                    on_appbar_event=self._on_appbar_event)
                self._hook.install()
            except Exception as error:
                print(f"[TitanShell] shell hook failed: {error}")

        self.ShowWithoutActivating()
        # Furniture, not an application: never an Alt+Tab stop.
        try:
            win_shell.hide_from_alt_tab(self.GetHandle())
        except Exception:
            pass
        self._layout_bar()
        self.refresh_windows()
        self._start_auto_hide()
        self.apply_always_on_top()
        if IS_WINDOWS:
            self.register_appbar(after=after)
        else:
            wx.CallAfter(self._first_tray_read)

    def register_appbar(self, after=None):
        """Claim the strip, on a thread of our own.

        Nothing here touches wx: `SHAppBarMessage` is Windows IPC and the
        rectangle it hands back is arithmetic, so the only thing that comes
        back to the GUI thread is the size to be.
        """
        if self._appbar is not None or self._appbar_thread is not None:
            return False
        handle = self.GetHandle()
        edge = self.edge()
        thickness = self.thickness()

        def work():
            appbar, rect = None, None
            try:
                if after is not None:
                    # Long enough for Explorer to answer, short enough that
                    # a machine which never answers still gets a taskbar.
                    after.wait(8.0)
                appbar = win_shell.AppBar(handle, edge=edge, height=thickness)
                if appbar.register():
                    rect = appbar.reposition()
                else:
                    appbar = None
            except Exception as error:
                print(f"[TitanShell] docking failed: {error}")
                appbar = None
            wx.CallAfter(self._appbar_ready, appbar, rect)

        self._appbar_thread = threading.Thread(
            target=work, daemon=True, name='TitanShellAppBar')
        self._appbar_thread.start()
        return True

    def _appbar_ready(self, appbar, rect):
        """The strip is ours: take the size Windows agreed to."""
        self._appbar_thread = None
        if not self:
            # The shell went away while Windows was thinking about it; the
            # reservation must not outlive the bar.
            if appbar is not None:
                try:
                    appbar.unregister()
                except Exception:
                    pass
            return
        self._appbar = appbar
        if appbar is not None and rect and not self.auto_hide():
            self.SetSize(*rect)
            self._layout_bar()
        # And only now the notification area.  Reading it is UI Automation
        # into Explorer's own windows, and Explorer has just been made to
        # move the work area: asking it anything before it has settled is
        # seconds of a shell that has stopped answering Windows, and the
        # answer comes back empty anyway.
        wx.CallLater(400, self._first_tray_read)

    def _first_tray_read(self, attempt=1):
        """Read the notification area, and again if Explorer was not ready.

        Reading it is UI Automation into Explorer's own windows, and this
        happens seconds after Explorer has been made to move the work area:
        asked too early it answers nothing at all.  An empty answer is
        therefore treated as "not yet" rather than as "no icons", and tried
        again a few times before the ordinary slow refresh takes over.
        """
        if not self:
            return
        try:
            self.refresh_tray()
        except Exception as error:
            print(f"[TitanShell] the notification area could not be read: "
                  f"{error}")
        if not self._tray_buttons and attempt < 4:
            wx.CallLater(1000 * attempt, self._first_tray_read, attempt + 1)

    # ------------------------------------------------------------------
    # Auto-hide
    # ------------------------------------------------------------------
    def _auto_hide_extent(self):
        """How far the bar travels: all of it but the sliver left behind."""
        return max(0, self.thickness() - AUTOHIDE_SLIVER)

    def _start_auto_hide(self):
        """Put the machinery up, or take it down when the setting is off."""
        if self._auto_hide_timer is None:
            self._auto_hide_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_auto_hide_tick,
                      self._auto_hide_timer)
        if self._track_timer is None:
            self._track_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_track_tick, self._track_timer)

        if not self.auto_hide():
            self._auto_hide_timer.Stop()
            self._track_timer.Stop()
            self._auto_hide_state = AUTOHIDE_SHOWN
            self._auto_hide_offset = 0
            self._apply_auto_hide()
            return

        self._track_timer.Start(100)
        self._auto_hide_state = AUTOHIDE_HIDING
        self._auto_hide_timer.Start(AUTOHIDE_DELAY_HIDE, wx.TIMER_ONE_SHOT)

    def _apply_auto_hide(self):
        """Move the window by however far it has slid off the edge."""
        x, y, width, height = self._shown_rect()
        offset = self._auto_hide_offset
        edge = self.edge()
        if edge == win_shell.ABE_BOTTOM:
            y += offset
        elif edge == win_shell.ABE_TOP:
            y -= offset
        elif edge == win_shell.ABE_LEFT:
            x -= offset
        else:
            x += offset
        try:
            self.SetSize(x, y, width, height)
        except Exception:
            pass

    def _on_auto_hide_tick(self, event):
        extent = self._auto_hide_extent()
        if self._auto_hide_state == AUTOHIDE_HIDING:
            self._auto_hide_offset = min(
                extent, self._auto_hide_offset + AUTOHIDE_SPEED_HIDE)
            done = self._auto_hide_offset >= extent
            self._auto_hide_state = AUTOHIDE_HIDDEN if done else AUTOHIDE_HIDING
        elif self._auto_hide_state == AUTOHIDE_SHOWING:
            self._auto_hide_offset = max(
                0, self._auto_hide_offset - AUTOHIDE_SPEED_SHOW)
            done = self._auto_hide_offset <= 0
            self._auto_hide_state = AUTOHIDE_SHOWN if done else AUTOHIDE_SHOWING
        else:
            return
        self._apply_auto_hide()
        if self._auto_hide_state in (AUTOHIDE_HIDING, AUTOHIDE_SHOWING):
            self._auto_hide_timer.Start(AUTOHIDE_INTERVAL_ANIMATING,
                                        wx.TIMER_ONE_SHOT)

    def auto_hide_show(self):
        """Bring the bar out, and keep it out while it is being used."""
        if not self.auto_hide():
            return
        if self._auto_hide_timer is None:
            # Asked to come out before the bar was docked - which happens
            # when auto-hide is switched on and the shortcut that reveals
            # the bar is the very next thing to run.
            self._start_auto_hide()
        if self._auto_hide_state in (AUTOHIDE_SHOWN, AUTOHIDE_SHOWING):
            return
        self._auto_hide_state = AUTOHIDE_SHOWING
        self._auto_hide_timer.Start(AUTOHIDE_DELAY_SHOW, wx.TIMER_ONE_SHOT)

    def auto_hide_conceal(self):
        """Let the bar go away again."""
        if not self.auto_hide() or self._auto_hide_timer is None:
            return
        if self._auto_hide_state in (AUTOHIDE_HIDDEN, AUTOHIDE_HIDING):
            return
        self._auto_hide_state = AUTOHIDE_HIDING
        self._auto_hide_timer.Start(AUTOHIDE_DELAY_HIDE, wx.TIMER_ONE_SHOT)

    def _wants_to_be_seen(self):
        """True while the bar is being used: the pointer on it, or the focus.

        The keyboard half matters more than the mouse one here - a bar that
        slid away while somebody was tabbing through it would be a bar that
        cannot be used without a mouse at all.
        """
        try:
            focused = wx.Window.FindFocus()
            if focused is not None and (focused is self
                                        or focused.GetTopLevelParent() is self):
                return True
        except Exception:
            pass
        if not IS_WINDOWS:
            return False
        try:
            x, y = wx.GetMousePosition()
        except Exception:
            return False
        left, top, width, height = self._shown_rect()
        return (left <= x < left + width) and (top <= y < top + height)

    def _on_track_tick(self, event):
        if self._wants_to_be_seen():
            self.auto_hide_show()
        else:
            self.auto_hide_conceal()

    def undock(self):
        for timer in (getattr(self, '_clock_timer', None),
                      getattr(self, '_poll_timer', None),
                      getattr(self, '_auto_hide_timer', None),
                      getattr(self, '_track_timer', None)):
            try:
                if timer:
                    timer.Stop()
            except Exception:
                pass
        if self._hook:
            self._hook.uninstall()
            self._hook = None
        if self._appbar:
            self._appbar.unregister()
            self._appbar = None

    def _layout_bar(self):
        try:
            width, height = self.GetSize()
        except Exception:
            return
        if width <= 0 or height <= 0:
            return

        if self.is_horizontal():
            self._layout_horizontal(width, height)
        else:
            self._layout_vertical(width, height)

    def _layout_horizontal(self, width, height):
        """Start, the band, the windows, the notification area, left to right."""
        self.start_button.SetSize(0, 0, START_BUTTON_WIDTH, height)
        x = START_BUTTON_WIDTH + 2

        quick_width = self._quick_launch_width()
        self.quick_launch_area.SetSize(x, 0, quick_width, height)
        self._layout_quick_launch()
        x += quick_width + (2 if quick_width else 0)

        tray_width = self._tray_width()
        task_width = max(0, width - x - tray_width)
        self.task_area.SetSize(x, 0, task_width, height)
        self.tray_area.SetSize(width - tray_width, 0, tray_width, height)
        self._layout_tray()
        self._layout_task_buttons()

    def _layout_vertical(self, width, height):
        """The same order, top to bottom, on a bar standing on its side.

        A taskbar docked to the left or the right of the screen is not a
        horizontal one turned round: the window buttons stack, each one as
        wide as the bar, and the notification area sits at the bottom with
        its icons in a column.  Everything keeps the order it has lying
        down, so Tab and the arrows lead through the bar the same way
        whichever edge it is on.
        """
        row = self.palette.taskbar_height
        self.start_button.SetSize(0, 0, width, row)
        y = row + 2

        quick_height = self._quick_launch_extent()
        self.quick_launch_area.SetSize(0, y, width, quick_height)
        self._layout_quick_launch()
        y += quick_height + (2 if quick_height else 0)

        tray_height = self._tray_extent()
        task_height = max(0, height - y - tray_height)
        self.task_area.SetSize(0, y, width, task_height)
        self.tray_area.SetSize(0, height - tray_height, width, tray_height)
        self._layout_tray()
        self._layout_task_buttons()

    def _quick_launch_width(self):
        count = len(self._quick_launch_buttons)
        return count * QUICK_LAUNCH_WIDTH + (4 if count else 0)

    def _quick_launch_extent(self):
        """How much of the bar the band takes along the bar's own length."""
        return self._quick_launch_width()

    def _layout_quick_launch(self):
        width, height = self.quick_launch_area.GetSize()
        if self.is_horizontal():
            x = 2
            for button in self._quick_launch_buttons:
                button.SetSize(x, 0, QUICK_LAUNCH_WIDTH, height)
                x += QUICK_LAUNCH_WIDTH
            return
        y = 2
        for button in self._quick_launch_buttons:
            button.SetSize(0, y, width, QUICK_LAUNCH_WIDTH)
            y += QUICK_LAUNCH_WIDTH

    def _tray_icon_width(self):
        """How wide one icon can be without the tray eating the bar.

        A Windows 11 machine showing its hidden icons can have twenty of
        them; XP never had to think about it, and a notification area taking
        half the taskbar would leave no room for the windows, which are what
        the bar is for.
        """
        count = len(self._tray_buttons)
        if not count:
            return TRAY_ICON_WIDTH
        try:
            bar_width = self.GetSize().width
        except Exception:
            bar_width = 0
        budget = int(bar_width * TRAY_MAX_SHARE) - CLOCK_WIDTH \
            - SHOW_DESKTOP_WIDTH - 14
        if budget <= 0:
            return TRAY_ICON_WIDTH
        return max(TRAY_ICON_MIN_WIDTH,
                   min(TRAY_ICON_WIDTH, budget // count))

    def _tray_width(self):
        furniture = 14
        if self.shows_clock():
            furniture += CLOCK_WIDTH
        if self.shows_show_desktop():
            furniture += SHOW_DESKTOP_WIDTH
        return furniture + self._tray_icon_width() * len(
            self._tray_buttons)

    def _tray_extent(self):
        """The notification area's depth on a bar standing on its side.

        The clock needs a row of its own there - it is text, not an icon -
        and so does Show Desktop.
        """
        row = TRAY_ICON_WIDTH
        return row * len(self._tray_buttons) + row + row + 10

    def _layout_tray(self):
        width, height = self.tray_area.GetSize()
        self.clock.Show(self.shows_clock())
        self.show_desktop_button.Show(self.shows_show_desktop())
        if not self.is_horizontal():
            row = TRAY_ICON_WIDTH
            y = 4
            for button in self._tray_buttons:
                button.SetSize(0, y, width, row)
                y += row
            self.clock.SetSize(0, y + 2, width, row)
            y += 2 + row
            self.show_desktop_button.SetSize(0, y, width, row)
            return
        icon_width = self._tray_icon_width()
        x = 6
        for button in self._tray_buttons:
            button.SetSize(x, 0, icon_width, height)
            x += icon_width
        self.clock.SetSize(x + 2, 0, CLOCK_WIDTH, height)
        x += 2 + CLOCK_WIDTH
        self.show_desktop_button.SetSize(x + 2, 0, SHOW_DESKTOP_WIDTH,
                                         height)

    def _layout_task_buttons(self):
        width, height = self.task_area.GetSize()
        count = len(self._windows)
        if not count or width <= 0:
            return
        if not self.is_horizontal():
            # Standing up, the buttons stack: each is the width of the bar
            # and they share its length between them.
            button_height = min(VERTICAL_TASK_HEIGHT,
                                max(16, (height - 4) // count - 2))
            y = 2
            for window in self._windows:
                button = self._buttons.get(window.hwnd)
                if button is None:
                    continue
                button.SetSize(0, y, width, button_height)
                y += button_height + 2
            return
        available = width - 4
        button_width = min(TASK_BUTTON_MAX_WIDTH, max(
            TASK_BUTTON_MIN_WIDTH, available // count - 2))
        x = 2
        for window in self._windows:
            button = self._buttons.get(window.hwnd)
            if button is None:
                continue
            button.SetSize(x, 0, button_width, height)
            x += button_width + 2

    # ------------------------------------------------------------------
    # The window list
    # ------------------------------------------------------------------
    def own_hwnds(self):
        return self.shell.own_hwnds()

    def refresh_windows(self):
        """Rebuild the buttons from what is open now.

        Buttons are reused across refreshes so the keyboard focus survives a
        window list changing under the user's hands.
        """
        if not IS_WINDOWS:
            return
        try:
            windows = win_shell.list_windows(self.own_hwnds())
        except Exception as error:
            print(f"[TitanShell] could not list windows: {error}")
            return

        seen = set()
        for window in windows:
            seen.add(window.hwnd)
            button = self._buttons.get(window.hwnd)
            if button is None:
                button = TaskButton(self.task_area, window, self)
                self._buttons[window.hwnd] = button
            else:
                # Keep a flash we were told about until the window is used.
                window.flashing = button.window.flashing and not window.active
                button.update(window)

        for hwnd in list(self._buttons):
            if hwnd not in seen:
                button = self._buttons.pop(hwnd)
                try:
                    button.Destroy()
                except Exception:
                    pass

        self._windows = windows
        self._layout_task_buttons()
        self.task_area.Refresh()

    def refresh_tray(self, expand_hidden=None):
        """Rebuild the notification area.

        `expand_hidden` opens the Windows 11 overflow flyout once and brings
        what is in it into the bar; without it only what Windows shows on the
        bar itself is read, so the periodic refresh never makes the screen
        flicker.
        """
        if not IS_WINDOWS or not shell_setting('show_tray', True):
            return
        if expand_hidden is None:
            expand_hidden = self._tray_expanded
        icons = []
        try:
            from src.system.tray_icons import (expand_hidden_icons,
                                               get_tray_icons, is_chevron)
            icons = list(get_tray_icons(include_hidden=False) or [])
            if expand_hidden:
                hidden = expand_hidden_icons() or []
                if hidden:
                    icons = [icon for icon in icons if not is_chevron(icon)]
                    icons.extend(hidden)
        except Exception as error:
            print(f"[TitanShell] could not read the notification area: {error}")

        icons = [icon for icon in icons if not self._is_titans_own(icon)]

        # Buttons are kept and re-pointed rather than rebuilt, exactly as
        # the window buttons are: a tray icon is renamed every few seconds
        # (the battery percentage, the volume, "syncing"), and destroying the
        # button under the user's focus to say so would throw the keyboard
        # out of the notification area every time the battery moved.
        existing = dict(self._existing_tray)
        buttons = []
        for icon in icons:
            button = existing.pop(icon.key, None)
            if button is None:
                button = TrayIconButton(self.tray_area, icon, self)
            else:
                button.update(icon)
            buttons.append(button)
            self._existing_tray[icon.key] = button
        for key, button in existing.items():
            self._existing_tray.pop(key, None)
            try:
                button.Destroy()
            except Exception:
                pass

        self._tray_buttons = buttons
        self._layout_bar()
        self.tray_area.Refresh()

    @staticmethod
    def _is_titans_own(icon):
        """Leave out the two buttons Titan's own bar already carries.

        Windows' notification area ends with its clock and its Show Desktop
        button, and Titan draws both itself - so reading them in as icons
        put two clocks and two Show Desktop buttons on the bar, one of each
        pair belonging to a taskbar the user cannot even see.  They are left
        out only while Titan is showing its own; switch Titan's clock off in
        the taskbar properties and Windows' one is there to press.
        """
        try:
            from src.system.tray_icons import is_clock, is_show_desktop
        except Exception:
            return False
        from src.shell.a11y import shell_setting as setting
        if is_show_desktop(icon):
            return bool(setting('show_desktop_button', True))
        if is_clock(icon):
            return bool(setting('show_clock', True))
        return False

    def show_hidden_tray_icons(self):
        """What pressing "Show hidden icons" does."""
        self._tray_expanded = True
        self.refresh_tray(expand_hidden=True)
        wx.CallAfter(self.focus_tray)

    def tray_buttons(self):
        return list(self._tray_buttons)

    def find_button(self, hwnd):
        return self._buttons.get(int(hwnd))

    def windows(self):
        return list(self._windows)

    # ------------------------------------------------------------------
    # Events from Windows
    # ------------------------------------------------------------------
    def _on_shell_event(self, code, hwnd):
        """Called from the window procedure - hand it to the GUI thread."""
        if code in (win_shell.HSHELL_WINDOWCREATED,
                    win_shell.HSHELL_WINDOWDESTROYED,
                    win_shell.HSHELL_WINDOWACTIVATED,
                    win_shell.HSHELL_RUDEAPPACTIVATED,
                    win_shell.HSHELL_REDRAW):
            self._request_refresh()
        elif code == win_shell.HSHELL_FLASH:
            wx.CallAfter(self._flash, hwnd)

    def _request_refresh(self):
        """Coalesce a burst of notifications into one rebuild.

        Opening a program can fire created/activated/redraw within a few
        milliseconds; rebuilding on each one would rebuild the bar three
        times and take the focus with it.
        """
        if self._refresh_pending:
            return
        self._refresh_pending = True

        def run():
            self._refresh_pending = False
            self.refresh_windows()

        wx.CallLater(60, run)

    def _flash(self, hwnd):
        button = self._buttons.get(int(hwnd))
        if button is None:
            return
        button.window.flashing = True
        button.refresh_accessible_name()
        button.Refresh()

    def _on_appbar_event(self, code, _lparam):
        if code in (win_shell.ABN_POSCHANGED, win_shell.ABN_STATECHANGE):
            wx.CallAfter(self._reposition)
        elif code == win_shell.ABN_FULLSCREENAPP:
            wx.CallAfter(self._on_fullscreen, bool(_lparam))

    def _reposition(self):
        if self._appbar:
            rect = self._appbar.reposition(self.thickness())
            if rect:
                self.SetSize(*rect)
                self._layout_bar()
                # A bar that has slid away must not jump back out because
                # the screen changed shape underneath it.
                self._apply_auto_hide()

    def _on_fullscreen(self, is_fullscreen):
        """A full-screen program (a game, a video) owns the whole screen.

        The z-order is changed and **the foreground is not touched**.
        `wx.Frame.Raise()` on Windows calls `SetForegroundWindow`, so the
        bar took the keyboard away from whatever the user was in every time
        Windows said a full-screen application had come or gone - which it
        says on ordinary Alt+Tabs, so switching windows kept dropping the
        user on the taskbar.  Going behind everything also has to give up
        topmost first, or a topmost window sent to the bottom is still in
        front of every window that is not.
        """
        try:
            if is_fullscreen:
                self._set_z_order(topmost=False, bottom=True)
            else:
                self.apply_always_on_top()
        except Exception as error:
            print(f"[TitanShell] z-order change failed: {error}")

    def _set_z_order(self, topmost=True, bottom=False):
        """Put the bar where it belongs in the z-order, without activating it."""
        if not IS_WINDOWS:
            return
        HWND_TOPMOST, HWND_NOTOPMOST, HWND_BOTTOM = -1, -2, 1
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        handle = self.GetHandle()
        try:
            if topmost:
                win_shell.user32.SetWindowPos(handle, HWND_TOPMOST,
                                              0, 0, 0, 0, flags)
                return
            win_shell.user32.SetWindowPos(handle, HWND_NOTOPMOST,
                                          0, 0, 0, 0, flags)
            if bottom:
                win_shell.user32.SetWindowPos(handle, HWND_BOTTOM,
                                              0, 0, 0, 0, flags)
        except Exception as error:
            print(f"[TitanShell] could not set the taskbar z-order: {error}")

    def _on_timer(self, event):
        try:
            self.clock.update_time()
        except Exception:
            pass

    def _on_poll(self, event):
        self._poll_count = getattr(self, '_poll_count', 0) + 1
        # Reading the notification area costs about sixty milliseconds - it
        # is a walk of Windows' own accessibility tree - so it happens on a
        # tick of its own rather than with the windows.  Anything that
        # changes an icon the user is looking at is still one F5 away.
        if self._poll_count % TRAY_POLL_TICKS == 0:
            try:
                self.refresh_tray()
            except Exception:
                pass
        try:
            if self._hook is None or not IS_WINDOWS:
                self.refresh_windows()
                return
            # Cheap check: only rebuild when the foreground actually moved.
            foreground = win_shell.user32.GetForegroundWindow()
            titles_changed = any(
                window.title != win_shell.window_title(window.hwnd)
                for window in self._windows)
            if foreground != self._last_foreground or titles_changed:
                self._last_foreground = foreground
                self.refresh_windows()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def _on_char_hook(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_F4 and event.AltDown():
            # The bar has nothing to close: Alt+F4 on the shell means the
            # Shut Down dialog, as it does on the desktop.
            from src.shell.shutdown_dialog import shell_alt_f4
            shell_alt_f4(self)
            return
        if key == wx.WXK_ESCAPE:
            self.hand_keyboard_back()
            return
        if key == wx.WXK_F5:
            self.refresh_windows()
            self.refresh_tray()
            self.refresh_quick_launch()
            return
        if key == wx.WXK_TAB:
            # XP's own model: Tab is for the groups, the arrows for what is
            # inside one.  Without this the bar was a dead end - every
            # control asks for all keys (wxWANTS_CHARS), so wx never turns a
            # Tab in one of them into a navigation of its own.
            self._move_between_groups(-1 if event.ShiftDown() else 1)
            return
        if key == wx.WXK_WINDOWS_MENU or (key == wx.WXK_F10 and
                                          event.ShiftDown()):
            focused = wx.Window.FindFocus()
            if not isinstance(focused, ShellControl):
                self._on_bar_context_menu(event)
                return
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT):
            if self._move_within_group(-1 if key == wx.WXK_LEFT else 1):
                return
        if key in (wx.WXK_HOME, wx.WXK_END):
            if self._move_to_group_end(key == wx.WXK_END):
                return
        event.Skip()

    # ------------------------------------------------------------------
    # The groups the bar is made of
    # ------------------------------------------------------------------
    def groups(self):
        """The bar as XP has it: Start, quick launch, windows, the tray.

        The clock belongs to the notification area rather than being a group
        of its own, which is why Windows+B lands on the icons and one more
        press of End reaches the clock.
        """
        groups = [('start', [self.start_button]),
                  ('quicklaunch', list(self._quick_launch_buttons))]
        tasks = [self._buttons.get(window.hwnd) for window in self._windows]
        groups.append(('tasks', [button for button in tasks if button]))
        tray = list(self._tray_buttons)
        if self.shows_clock():
            tray.append(self.clock)
        if self.shows_show_desktop():
            tray.append(self.show_desktop_button)
        groups.append(('tray', tray))
        return [(name, controls) for name, controls in groups if controls]

    def _group_of(self, control):
        for index, (name, controls) in enumerate(self.groups()):
            if control in controls:
                return index, name, controls
        return -1, '', []

    def _focus_group(self, index):
        groups = self.groups()
        if not groups:
            return False
        name, controls = groups[index % len(groups)]
        # Coming back to a group puts the user where they left it, which is
        # what makes Tab a way of getting about rather than a way of losing
        # your place.
        remembered = self._group_memory.get(name)
        target = remembered if remembered in controls else controls[0]
        return self.focus_in_group(name, target)

    def focus_in_group(self, group, control):
        """Put the keyboard on a control and say which group it is in.

        The group is announced the way a Titan window announces its tab bar:
        to the screen reader only, through
        `accessibility.messages.announce_shell_group`, and *before* the
        focus moves, so the reader says "Dock" and then reads the control it
        landed on.  The bar itself still says nothing - if no screen reader
        is running, nothing is spoken at all.
        """
        if control is None:
            return False
        try:
            announce_group(group_label(group))
        except Exception:
            pass
        try:
            control.SetFocus()
            self._group_memory[group] = control
            return True
        except Exception:
            return False

    def _move_between_groups(self, delta):
        groups = self.groups()
        if not groups:
            return False
        focused = wx.Window.FindFocus()
        index, name, _controls = self._group_of(focused)
        if index < 0:
            return self._focus_group(0 if delta > 0 else len(groups) - 1)
        self._group_memory[name] = focused
        target = index + delta
        if target < 0 or target >= len(groups):
            # Off the end of the bar is the desktop, not the other end of
            # the bar: the desktop, the Start button, the window buttons and
            # the notification area are one round trip, which is what Tab
            # does on Windows and what the desktop's own Tab expects to find
            # at the other side.
            if self._leave_to_desktop():
                return True
        return self._focus_group(target)

    def _leave_to_desktop(self):
        try:
            return bool(self.shell.focus_desktop())
        except Exception as error:
            print(f"[TitanShell] could not go to the desktop: {error}")
            return False

    def _move_within_group(self, delta):
        """Arrows walk the controls of whichever group has the focus.

        The taskbar reads as a handful of lists, and inside a list the arrows
        move - which is what a list is for, and what Tab must not have to do.
        """
        focused = wx.Window.FindFocus()
        index, name, controls = self._group_of(focused)
        if index < 0:
            return False
        position = controls.index(focused) + delta
        if position < 0 or position >= len(controls):
            edge_cue()
            return True
        controls[position].SetFocus()
        self._group_memory[name] = controls[position]
        return True

    def _move_to_group_end(self, last):
        focused = wx.Window.FindFocus()
        index, name, controls = self._group_of(focused)
        if index < 0:
            return False
        target = controls[-1] if last else controls[0]
        target.SetFocus()
        self._group_memory[name] = target
        return True

    def _on_bar_context_menu(self, event):
        """The taskbar's own menu, as XP has it.

        Reachable with the mouse anywhere on an empty part of the bar, and
        with Shift+F10 from the keyboard, so neither way of using the shell
        is the second-class one.
        """
        menu = wx.Menu()
        cascade = menu.Append(wx.ID_ANY, _("&Cascade Windows"))
        tile_h = menu.Append(wx.ID_ANY, _("Tile Windows &Horizontally"))
        tile_v = menu.Append(wx.ID_ANY, _("Tile Windows &Vertically"))
        menu.AppendSeparator()
        show_desktop = menu.Append(wx.ID_ANY, _("&Show the Desktop"))
        menu.AppendSeparator()
        task_manager = menu.Append(wx.ID_ANY, _("Tas&k Manager"))
        window_list = menu.Append(wx.ID_ANY, _("&Window list"))
        menu.AppendSeparator()

        # Where the bar is, and whether it stays there.  ReactOS keeps these
        # on the same menu; the position is a submenu because four edges as
        # four top-level items would bury everything else.
        position_menu = wx.Menu()
        position_items = {}
        for name, label in (('bottom', _("&Bottom")), ('top', _("&Top")),
                            ('left', _("&Left")), ('right', _("&Right"))):
            item = position_menu.AppendRadioItem(wx.ID_ANY, label)
            position_items[item.GetId()] = name
            if name == self.position_name():
                item.Check(True)
        position_submenu = menu.AppendSubMenu(position_menu, _("&Position"))
        # A locked taskbar is one that cannot be moved - which is the whole
        # of what the lock means here, since Titan's bar is moved from this
        # menu and from the properties dialog rather than by dragging it.
        if self.is_locked():
            position_submenu.Enable(False)

        lock_item = menu.AppendCheckItem(wx.ID_ANY, _("&Lock the taskbar"))
        lock_item.Check(self.is_locked())
        hide_item = menu.AppendCheckItem(wx.ID_ANY,
                                         _("A&uto-hide the taskbar"))
        hide_item.Check(self.auto_hide())
        menu.AppendSeparator()
        properties = menu.Append(wx.ID_ANY, _("P&roperties"))

        for identifier, name in position_items.items():
            position_menu.Bind(
                wx.EVT_MENU,
                lambda e, edge=name: self.set_position(edge), id=identifier)
        self.Bind(wx.EVT_MENU,
                  lambda e: self.set_locked(not self.is_locked()), lock_item)
        self.Bind(wx.EVT_MENU,
                  lambda e: self.set_auto_hide(not self.auto_hide()),
                  hide_item)

        self.Bind(wx.EVT_MENU,
                  lambda e: self._arrange(win_shell.cascade_windows), cascade)
        self.Bind(wx.EVT_MENU,
                  lambda e: self._arrange(win_shell.tile_windows_horizontally),
                  tile_h)
        self.Bind(wx.EVT_MENU,
                  lambda e: self._arrange(win_shell.tile_windows_vertically),
                  tile_v)
        self.Bind(wx.EVT_MENU, lambda e: self.toggle_show_desktop(),
                  show_desktop)
        self.Bind(wx.EVT_MENU, lambda e: win_shell.open_task_manager(),
                  task_manager)
        self.Bind(wx.EVT_MENU, lambda e: self.shell.show_window_switcher(),
                  window_list)
        self.Bind(wx.EVT_MENU, lambda e: self.show_properties(), properties)

        self.PopupMenu(menu)
        menu.Destroy()

    def set_position(self, name):
        """Move the bar to another edge of the screen.

        A locked bar stays where it is: that is what the lock is for, and
        refusing here rather than only greying the menu means an action or a
        macro cannot move it behind the user's back either.
        """
        if name not in POSITION_EDGES or self.is_locked():
            return False
        from src.settings.settings import set_setting
        set_setting('taskbar_position', name, 'titan_shell')
        self.redock()
        return True

    def set_auto_hide(self, enabled):
        from src.settings.settings import set_setting
        set_setting('taskbar_auto_hide', str(bool(enabled)), 'titan_shell')
        self._auto_hide_offset = 0
        self._start_auto_hide()
        return True

    def set_locked(self, locked):
        from src.settings.settings import set_setting
        set_setting('taskbar_locked', str(bool(locked)), 'titan_shell')
        return True

    def redock(self):
        """Take the bar off the edge it is on and put it on the current one.

        The appbar reservation belongs to an edge, so it has to be given up
        and taken again - leaving it registered would keep the old strip of
        screen reserved and maximised windows would stop short of nothing.
        """
        try:
            if self._appbar:
                self._appbar.unregister()
                self._appbar = None
        except Exception:
            pass
        thickness = self.thickness()
        self.SetSize(*self._shown_rect())
        if IS_WINDOWS:
            try:
                self._appbar = win_shell.AppBar(self.GetHandle(),
                                                edge=self.edge(),
                                                height=thickness)
                if self._appbar.register():
                    rect = self._appbar.reposition()
                    if rect:
                        self.SetSize(*rect)
            except Exception as error:
                print(f"[TitanShell] moving the taskbar failed: {error}")
        self._auto_hide_offset = 0
        self._layout_bar()
        self._start_auto_hide()
        self.apply_always_on_top()
        self.Refresh()

    def show_properties(self):
        """The taskbar's own properties sheet, not Titan's settings window.

        Right-clicking a taskbar and asking for its properties has meant one
        particular dialog for thirty years, and it is not a program's
        settings: it is the bar, the Start menu and the notification area.
        """
        try:
            from src.shell.taskbar_properties import show_taskbar_properties
            show_taskbar_properties(self, self.shell)
        except Exception as error:
            print(f"[TitanShell] properties failed: {error}")
            try:
                self.shell.open_settings()
            except Exception:
                pass

    def _arrange(self, arranger):
        try:
            arranger(self.own_hwnds())
        finally:
            wx.CallLater(200, self.refresh_windows)

    def activate(self):
        """Make the bar the window the keyboard is talking to."""
        # A hidden bar has to come out first, or the keyboard would go to a
        # two-pixel sliver at the edge of the screen.
        self.auto_hide_show()
        try:
            self.Raise()
        except Exception:
            pass
        if IS_WINDOWS:
            try:
                # Remembered before we take it: Escape gives the keyboard
                # back to the window the user came from, as XP does, rather
                # than dropping them on a desktop that then has to be
                # brought in front of everything they were working in.
                previous = win_shell.user32.GetForegroundWindow()
                if previous and previous not in self.own_hwnds():
                    self._previous_foreground = previous
            except Exception:
                pass
            win_shell.take_foreground(self.GetHandle())
        return True

    def _on_activate(self, event):
        try:
            if not event.GetActive() and not self.always_on_top():
                wx.CallAfter(self.send_to_background)
        except Exception:
            pass
        event.Skip()

    def hand_keyboard_back(self):
        """Escape: back to whatever the user was in before the bar."""
        previous = self._previous_foreground
        self._previous_foreground = 0
        if previous and IS_WINDOWS:
            try:
                if win_shell.user32.IsWindow(previous) and \
                        win_shell.user32.IsWindowVisible(previous):
                    win_shell.activate_window(previous)
                    return True
            except Exception:
                pass
        return self.shell.focus_desktop()

    def focus_clock(self):
        self.activate()
        return self.focus_in_group('tray', self.clock)

    def focus_first_task(self):
        """Where the keyboard lands when the user asks for the taskbar."""
        self.activate()
        for window in self._windows:
            button = self._buttons.get(window.hwnd)
            if button:
                return self.focus_in_group('tasks', button)
        self.focus_in_group('start', self.start_button)
        return False

    def focus_start_button(self):
        self.activate()
        return self.focus_in_group('start', self.start_button)

    def focus_tray(self):
        """Windows+B: the keyboard goes to the notification area."""
        self.activate()
        target = self._tray_buttons[0] if self._tray_buttons else self.clock
        return self.focus_in_group('tray', target)

    # ------------------------------------------------------------------
    # Show desktop
    # ------------------------------------------------------------------
    def toggle_show_desktop(self):
        if self._desktop_shown and self._minimised_by_show_desktop:
            win_shell.restore_all(self._minimised_by_show_desktop)
            self._minimised_by_show_desktop = []
            self._desktop_shown = False
        else:
            self._minimised_by_show_desktop = win_shell.minimize_all(
                self.own_hwnds())
            self._desktop_shown = True
            # The windows are asked to minimise, not made to: the keyboard
            # can only go to the desktop once they have actually gone.
            wx.CallLater(150, self.shell.focus_desktop)
        wx.CallLater(200, self.refresh_windows)

    # ------------------------------------------------------------------
    # Skin
    # ------------------------------------------------------------------
    def apply_palette(self, palette):
        self.palette = palette
        for child in (self.start_button, self.show_desktop_button, self.clock):
            try:
                child.refresh_palette(palette)
            except Exception:
                pass
        for button in list(self._buttons.values()) + self._tray_buttons:
            try:
                button.refresh_palette(palette)
            except Exception:
                pass
        self._reposition()
        self.Refresh()

    def allow_close(self):
        """The shell is taking itself down; the bar may really close."""
        self._allow_close = True

    def _on_close(self, event):
        if not getattr(self, '_allow_close', False):
            # The taskbar is furniture, not a window with a document in it:
            # closing it leaves the shell holding a destroyed frame.  Anything
            # that asks for it - Alt+F4, the system menu - is asking to shut
            # down instead.
            event.Veto()
            from src.shell.shutdown_dialog import shell_alt_f4
            shell_alt_f4(self)
            return
        self.undock()
        event.Skip()
