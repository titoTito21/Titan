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
from src.shell.deferred import call_after
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
        # Off by default, unlike Windows': the appbar already keeps the
        # strip clear, so a bar in the background is covered by nothing the
        # user opens - and it can never end up over a dialog or a game.
        self.on_top = self.add_check(
            box, _("Keep the &taskbar on top of other windows"),
            'taskbar_on_top', False,
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
    """`IDD_TASKBARPROP_STARTMENU`: which Start menu this machine has.

    XP's own page offers two, and this is where a third belongs as well: a
    shell add-on that provides a Start menu is a Start menu the user can
    choose, so it appears here beside them rather than in a settings screen
    of its own.  Each is a radio button with a line saying what it is -
    which for an add-on is its manifest's description, so an add-on author
    writes that sentence once.
    """

    def build(self):
        box = self.add_group(_("Start menu"))
        parent = box.GetStaticBox()

        style = str(shell_setting('start_menu_style', 'xp')).lower()
        chosen_addon = str(shell_setting('provider_start_menu', '') or '')

        self.choices = []          # (button, style value, add-on id)

        self.modern = wx.RadioButton(parent, label=_("&Start menu"),
                                     style=wx.RB_GROUP)
        box.Add(self.modern, 0, wx.ALL, 6)
        box.Add(wx.StaticText(
            parent,
            label=_("This menu style gives you easy access to your folders, "
                    "favorite programs, and search.")),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)
        self.choices.append((self.modern, 'xp', ''))

        self.classic = wx.RadioButton(parent, label=_("Classic Start &menu"))
        box.Add(self.classic, 0, wx.ALL, 6)
        box.Add(wx.StaticText(
            parent,
            label=_("This menu style gives you the classic look and "
                    "functionality.")),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)
        self.choices.append((self.classic, 'classic', ''))

        for config in self._addon_menus():
            button = wx.RadioButton(parent, label=config.name)
            box.Add(button, 0, wx.ALL, 6)
            description = config.description or _(
                "A Start menu from an installed shell add-on.")
            box.Add(wx.StaticText(parent, label=description),
                    0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 24)
            self.choices.append((button, 'addon', config.id))

        selected = None
        if style == 'addon' and chosen_addon:
            selected = next((button for button, kind, addon_id in self.choices
                             if kind == 'addon' and addon_id == chosen_addon),
                            None)
        elif style == 'classic':
            selected = self.classic
        # An add-on that has been uninstalled since it was chosen leaves the
        # user with Titan's own menu, which is what actually opens - never a
        # ticked box for something that is not there.
        (selected or self.modern).SetValue(True)

        for button, _kind, _addon_id in self.choices:
            button.Bind(wx.EVT_RADIOBUTTON, self._changed)

    @staticmethod
    def _addon_menus():
        """The installed add-ons offering a Start menu of their own."""
        try:
            from src.shell import addons
            return addons.manager().providers('start_menu')
        except Exception as error:
            print(f"[TaskbarProperties] could not list Start menus: {error}")
            return []

    def _changed(self, _event):
        for button, kind, addon_id in self.choices:
            if not button.GetValue():
                continue
            _write('start_menu_style', kind)
            # Written even for Titan's own menus, so that turning an add-on
            # off and on again does not silently bring back a menu the user
            # has since stopped using.
            _write('provider_start_menu', addon_id)
            break
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
        call_after(self, self._sync_seconds)

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
