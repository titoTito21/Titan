# -*- coding: utf-8 -*-
"""
Taskbar and Start Menu Properties.

`base/shell/explorer/trayprop.cpp` puts up a property sheet with three pages
- `IDD_TASKBARPROP_TASKBAR`, `IDD_TASKBARPROP_STARTMENU` and
`IDD_TASKBARPROP_NOTIFY` - and this is that sheet, page for page and control
for control, as a `wx.Notebook` whose pages are real controls with real
labels.

The one rule applied throughout: **a control is here only if it does
something.**  ReactOS' own sheet carries a couple of switches its taskbar
does not read yet (it says so in the source, commented out beside them), and
copying a dead checkbox would be worse than leaving it out - a blind user has
no way to tell a switch that does nothing from one that is broken.  So
"Group similar taskbar buttons" and "Use small icons" are absent until the
bar groups buttons and has a small mode, while "Hide inactive icons", which
belongs to Windows' own notification area rather than to Titan's reading of
it, is a button that opens the page in Windows where that choice lives.

Everything here writes into the `titan_shell` settings and then tells the
running shell, so a change takes effect while the dialog is still open -
which is also what makes it testable without a screen.
"""

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import win_shell
from src.shell.a11y import shell_setting
from src.titan_core.translation import _

POSITIONS = ('bottom', 'top', 'left', 'right')


def position_labels():
    return {'bottom': _("Bottom"), 'top': _("Top"),
            'left': _("Left"), 'right': _("Right")}


def _write(key, value):
    from src.settings.settings import set_setting
    set_setting(key, str(value), 'titan_shell')


class _Page(wx.Panel):
    """A page of the sheet, with the group boxes ReactOS' pages have."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.build()
        self.SetSizer(self.sizer)

    def build(self):
        raise NotImplementedError

    def add_group(self, title):
        box = wx.StaticBoxSizer(wx.VERTICAL, self, title)
        self.sizer.Add(box, 0, wx.ALL | wx.EXPAND, 8)
        return box

    def add_check(self, box, label, key, default, on_change=None):
        check = wx.CheckBox(box.GetStaticBox(), label=label)
        check.SetValue(bool(shell_setting(key, default)))
        box.Add(check, 0, wx.ALL, 6)

        def changed(_event, key=key, check=check, on_change=on_change):
            _write(key, check.GetValue())
            if on_change is not None:
                on_change(check.GetValue())

        check.Bind(wx.EVT_CHECKBOX, changed)
        return check


class TaskbarPage(_Page):
    """`IDD_TASKBARPROP_TASKBAR`: what the bar does and where it is."""

    def build(self):
        box = self.add_group(_("Taskbar appearance"))
        parent = box.GetStaticBox()

        self.lock = self.add_check(
            box, _("&Lock the taskbar"), 'taskbar_locked', True,
            self._locked_changed)
        self.hide = self.add_check(
            box, _("A&uto-hide the taskbar"), 'taskbar_auto_hide', False,
            lambda value: self.dialog.taskbar_do('set_auto_hide', value))
        self.on_top = self.add_check(
            box, _("Keep the &taskbar on top of other windows"),
            'taskbar_on_top', True,
            lambda value: self.dialog.taskbar_do('apply_always_on_top'))
        self.quick = self.add_check(
            box, _("Show &Quick Launch"), 'show_quick_launch', True,
            lambda value: self.dialog.taskbar_do('refresh_quick_launch'))

        # Where the bar is.  Windows' own dialog grew this control in a
        # later version than the one this sheet copies, and Titan needs it:
        # its bar is moved from here and from the taskbar's menu, never by
        # dragging, so without it three of the four edges are unreachable.
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(parent, label=_("Taskbar location on &screen:")),
                0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        labels = position_labels()
        self.position = wx.ComboBox(
            parent, choices=[labels[name] for name in POSITIONS],
            style=wx.CB_READONLY)
        self.position.SetName(_("Taskbar location on screen"))
        current = str(shell_setting('taskbar_position', 'bottom')).lower()
        self.position.SetSelection(
            POSITIONS.index(current) if current in POSITIONS else 0)
        self.position.Bind(wx.EVT_COMBOBOX, self._position_changed)
        row.Add(self.position, 1, wx.ALIGN_CENTER_VERTICAL)
        box.Add(row, 0, wx.ALL | wx.EXPAND, 6)

        self._locked_changed(self.lock.GetValue())

    def _locked_changed(self, locked):
        # A locked bar cannot be moved, so the control that moves it says so
        # rather than silently doing nothing.
        self.position.Enable(not locked)

    def _position_changed(self, _event):
        index = self.position.GetSelection()
        if 0 <= index < len(POSITIONS):
            self.dialog.taskbar_do('set_position', POSITIONS[index])


class StartMenuPage(_Page):
    """`IDD_TASKBARPROP_STARTMENU`: which of the two menus."""

    def build(self):
        box = self.add_group(_("Start menu"))
        parent = box.GetStaticBox()

        classic = str(shell_setting('start_menu_style', 'xp')).lower() \
            == 'classic'

        self.modern = wx.RadioButton(parent, label=_("&Start menu"),
                                     style=wx.RB_GROUP)
        box.Add(self.modern, 0, wx.ALL, 6)
        box.Add(wx.StaticText(
            parent,
            label=_("This menu style gives you easy access to your folders, "
                    "favorite programs, and search.")),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)

        self.classic = wx.RadioButton(parent, label=_("Classic Start &menu"))
        box.Add(self.classic, 0, wx.ALL, 6)
        box.Add(wx.StaticText(
            parent,
            label=_("This menu style gives you the classic look and "
                    "functionality.")),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)

        (self.classic if classic else self.modern).SetValue(True)
        for button in (self.modern, self.classic):
            button.Bind(wx.EVT_RADIOBUTTON, self._changed)

    def _changed(self, _event):
        _write('start_menu_style',
               'classic' if self.classic.GetValue() else 'xp')
        # The menu is rebuilt the next time it is opened, so the one already
        # made has to go.
        self.dialog.drop_start_menu()


class NotificationPage(_Page):
    """`IDD_TASKBARPROP_NOTIFY`: the icons, the clock, Show Desktop."""

    def build(self):
        icons = self.add_group(_("Icons"))
        parent = icons.GetStaticBox()
        icons.Add(wx.StaticText(
            parent,
            label=_("You can keep the notification area uncluttered by "
                    "hiding icons that you have not clicked recently.")),
            0, wx.ALL, 6)
        # Which icons are hidden is Windows' own choice and Titan reads the
        # result, so this opens the page where that choice is made rather
        # than offering a switch of its own that could disagree with it.
        customise = wx.Button(parent, label=_("&Customize..."))
        customise.Bind(wx.EVT_BUTTON, self._customise)
        customise.Enable(IS_WINDOWS)
        icons.Add(customise, 0, wx.ALL, 6)

        system = self.add_group(_("System icons"))
        system.Add(wx.StaticText(
            system.GetStaticBox(),
            label=_("Select which system icons to always show.")),
            0, wx.ALL, 6)
        self.clock = self.add_check(
            system, _("Cloc&k"), 'show_clock', True, self._relayout)
        self.seconds = self.add_check(
            system, _("Show &seconds"), 'clock_seconds', False,
            self._relayout)
        self.desktop = self.add_check(
            system, _("&Desktop"), 'show_desktop_button', True,
            self._relayout)
        self._sync_seconds()
        self.clock.Bind(wx.EVT_CHECKBOX, self._clock_toggled)

    def _clock_toggled(self, event):
        event.Skip()
        wx.CallAfter(self._sync_seconds)

    def _sync_seconds(self):
        # Seconds are a property of a clock that is there; ReactOS greys
        # this one for the same reason.
        self.seconds.Enable(self.clock.GetValue())

    def _relayout(self, _value=None):
        self.dialog.taskbar_do('_layout_bar')
        self.dialog.taskbar_do('Refresh')

    def _customise(self, _event):
        win_shell.open_path('ms-settings:taskbar')


class TaskbarPropertiesDialog(wx.Dialog):
    """The sheet itself: three pages, and Close."""

    def __init__(self, parent=None, shell=None, page=0):
        super().__init__(parent,
                         title=_("Taskbar and Start Menu Properties"),
                         style=wx.DEFAULT_DIALOG_STYLE)
        self.shell = shell

        outer = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(self)
        self.notebook.AddPage(TaskbarPage(self.notebook, self), _("Taskbar"))
        self.notebook.AddPage(StartMenuPage(self.notebook, self),
                              _("Start Menu"))
        self.notebook.AddPage(NotificationPage(self.notebook, self),
                              _("Notification area"))
        try:
            self.notebook.SetSelection(page)
        except Exception:
            pass
        outer.Add(self.notebook, 1, wx.ALL | wx.EXPAND, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer()
        close = wx.Button(self, wx.ID_OK, _("Close"))
        buttons.Add(close, 0, wx.ALL, 6)
        outer.Add(buttons, 0, wx.EXPAND)

        self.SetSizerAndFit(outer)
        self.CentreOnScreen()
        close.SetDefault()
        self.notebook.SetFocus()

    # -- talking to the running shell ---------------------------------
    def taskbar(self):
        return getattr(self.shell, 'taskbar', None)

    def taskbar_do(self, method, *args):
        """Apply a change to the bar that is up, if one is.

        Everything on this sheet is also a setting on disk, so the dialog
        still works with the shell switched off - it just has nothing to
        tell.
        """
        bar = self.taskbar()
        if bar is None:
            return None
        function = getattr(bar, method, None)
        if function is None:
            return None
        try:
            return function(*args)
        except Exception as error:
            print(f"[TitanShell] properties: {method} failed: {error}")
            return None

    def drop_start_menu(self):
        """Throw the built Start menu away so the other one is made next."""
        shell = self.shell
        menu = getattr(shell, 'start_menu', None)
        if menu is None:
            return
        try:
            menu.Destroy()
        except Exception:
            pass
        shell.start_menu = None


def show_taskbar_properties(parent=None, shell=None, page=0):
    """Put the sheet up.  Everything it changes is applied as it is changed."""
    if shell is None:
        try:
            from src.shell.shell_manager import get_shell
            shell = get_shell()
        except Exception:
            shell = None
    dialog = TaskbarPropertiesDialog(parent, shell, page)
    try:
        dialog.ShowModal()
    finally:
        dialog.Destroy()
