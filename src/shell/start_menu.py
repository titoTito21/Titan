# -*- coding: utf-8 -*-
"""
The Start menu, in its XP shape: a blue header with the user's name, a white
left column of programs, a pale blue right column of places, and a footer
with Log Off and Turn Off Computer.

It is `ClassicStartMenu` with a different face.  Everything that finds
programs, runs a Titan application or a game, opens the Run dialog or asks
about shutting down already lives there and is inherited unchanged - this
module supplies the XP layout and the two panes, not a second start menu.

Both columns are real list controls, so the arrow keys, first-letter
jumping, the mouse and every screen reader work without Titan implementing
any of them.  "All Programs" opens *inside* the left column, with Backspace
and Escape stepping back out, rather than as a cascade of flyouts that a
keyboard cannot follow.
"""

import os

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import luna, win_shell
from src.shell.a11y import edge_cue
from src.ui.classic_start_menu import ClassicStartMenu
from src.titan_core.translation import _

MENU_WIDTH = 400
MENU_HEIGHT = 500
HEADER_HEIGHT = 58
FOOTER_HEIGHT = 42
LEFT_WIDTH = 216


class MenuEntry:
    """One line of either column."""

    __slots__ = ('label', 'kind', 'payload', 'description')

    def __init__(self, label, kind='action', payload=None, description=''):
        self.label = label
        self.kind = kind          # action | app | game | program | folder |
        self.payload = payload    # back | separator
        self.description = description


class MenuList(wx.ListCtrl):
    """A column of the Start menu.

    A report-mode list view with no header is what XP's own columns are, and
    it is read by name and role by every screen reader without any help.
    """

    def __init__(self, parent, on_activate, background, foreground, name):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_NO_HEADER
                         | wx.LC_SINGLE_SEL | wx.NO_BORDER | wx.WANTS_CHARS)
        self.SetName(name)
        self.entries = []
        self._on_activate = on_activate
        self.InsertColumn(0, name)
        self.SetBackgroundColour(background)
        self.SetForegroundColour(foreground)

        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._activate)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda event: self._activate(event))

    def set_entries(self, entries):
        self.DeleteAllItems()
        self.entries = list(entries)
        for index, entry in enumerate(self.entries):
            label = entry.label
            if entry.kind == 'folder':
                # XP draws an arrow here.  A glyph cannot go in the item's text,
                # because a list item's text **is** its accessible name: the
                # reader then says the name of the character instead of saying
                # that the entry opens something.  So it is written in words,
                # which is what a screen reader announces for a real menu with
                # a submenu under it.
                label = _("{name}, submenu").format(name=entry.label)
            self.InsertItem(index, label)
        self.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        if self.entries:
            self.Select(0)
            self.Focus(0)

    def selected_entry(self):
        index = self.GetFirstSelected()
        if 0 <= index < len(self.entries):
            return self.entries[index]
        return None

    def _activate(self, event):
        entry = self.selected_entry()
        if entry is not None and callable(self._on_activate):
            self._on_activate(entry)

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._activate(event)
        else:
            event.Skip()


class XPStartMenu(ClassicStartMenu):
    """The Start menu of the Titan shell."""

    def __init__(self, parent, shell=None):
        self.shell = shell
        self.palette = luna.get_palette()
        self._program_stack = []
        super().__init__(parent)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def init_ui(self):
        palette = self.palette
        panel = wx.Panel(self)
        panel.SetBackgroundColour(palette['menu_right_background'])

        self.header = wx.Window(panel, size=(MENU_WIDTH, HEADER_HEIGHT))
        self.header.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.header.SetName(win_shell.user_display_name())
        self.header.Bind(wx.EVT_PAINT, self._paint_header)
        self.header.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)

        self.left_list = MenuList(
            panel, self._activate_entry, palette['menu_left_background'],
            palette['menu_left_text'], _("Programs"))
        self.right_list = MenuList(
            panel, self._activate_entry, palette['menu_right_background'],
            palette['menu_right_text'], _("Places"))

        self.footer = wx.Panel(panel, size=(MENU_WIDTH, FOOTER_HEIGHT))
        self.footer.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.footer.Bind(wx.EVT_PAINT, self._paint_footer)
        self.footer.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)

        self.logoff_button = wx.Button(self.footer, label=_("&Log Off"))
        self.shutdown_button = wx.Button(self.footer,
                                         label=_("&Turn Off Computer"))
        self.logoff_button.Bind(wx.EVT_BUTTON, self._on_logoff)
        self.shutdown_button.Bind(wx.EVT_BUTTON, self.on_shutdown)

        footer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        footer_sizer.AddStretchSpacer(1)
        footer_sizer.Add(self.logoff_button, 0, wx.ALL | wx.ALIGN_CENTRE, 6)
        footer_sizer.Add(self.shutdown_button, 0, wx.ALL | wx.ALIGN_CENTRE, 6)
        self.footer.SetSizer(footer_sizer)

        columns = wx.BoxSizer(wx.HORIZONTAL)
        columns.Add(self.left_list, 0, wx.EXPAND)
        columns.Add(self.right_list, 1, wx.EXPAND)
        self.left_list.SetMinSize((LEFT_WIDTH, -1))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.header, 0, wx.EXPAND)
        sizer.Add(columns, 1, wx.EXPAND)
        sizer.Add(self.footer, 0, wx.EXPAND)
        panel.SetSizer(sizer)

        self.SetSize((MENU_WIDTH, MENU_HEIGHT))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _paint_header(self, event):
        dc = wx.AutoBufferedPaintDC(self.header)
        rect = wx.Rect(0, 0, *self.header.GetSize())
        luna.draw_gradient(dc, rect, self.palette['menu_header'])
        dc.SetFont(self.palette.font(size=12, bold=True))
        dc.SetTextForeground(self.palette['menu_header_text'])
        name = win_shell.user_display_name()
        _width, height = dc.GetTextExtent(name)
        dc.DrawText(name, 12, (rect.height - height) // 2)

    def _paint_footer(self, event):
        dc = wx.AutoBufferedPaintDC(self.footer)
        rect = wx.Rect(0, 0, *self.footer.GetSize())
        luna.draw_gradient(dc, rect, self.palette['menu_footer'])

    # ------------------------------------------------------------------
    # Contents
    # ------------------------------------------------------------------
    def build_menu_structure(self):
        self.menu_items = []
        self._program_stack = []
        self.left_list.set_entries(self._top_level_entries())
        self.right_list.set_entries(self._places_entries())

    def _top_level_entries(self):
        entries = [
            MenuEntry(_("Titan"), 'action', 'titan_window'),
            MenuEntry(_("Applications"), 'action', 'titan_apps'),
            MenuEntry(_("Games"), 'action', 'titan_games'),
            MenuEntry(_("File manager"), 'action', 'file_manager'),
            MenuEntry(_("Internet"), 'action', 'internet'),
            MenuEntry('', 'separator'),
            MenuEntry(_("All Programs"), 'folder', '__all_programs__'),
        ]
        return [entry for entry in entries if entry.kind != 'separator'
                or True]

    def _places_entries(self):
        return [
            MenuEntry(_("My Documents"), 'action', 'my_documents'),
            MenuEntry(_("My Pictures"), 'action', 'my_pictures'),
            MenuEntry(_("My Music"), 'action', 'my_music'),
            MenuEntry(_("My Computer"), 'action', 'my_computer'),
            MenuEntry(_("Control Panel"), 'action', 'control_panel'),
            MenuEntry(_("Titan settings"), 'action', 'titan_settings'),
            MenuEntry(_("Notification centre"), 'action', 'notifications'),
            MenuEntry(_("Search"), 'action', 'find'),
            MenuEntry(_("Run..."), 'action', 'run'),
            MenuEntry(_("Help and Support"), 'action', 'help'),
        ]

    def _all_programs_entries(self):
        """Titan's own add-ons first, then the Windows Start Menu folders."""
        entries = [MenuEntry(_("Titan applications"), 'folder', '__apps__'),
                   MenuEntry(_("Titan games"), 'folder', '__games__')]
        try:
            structure = self.load_windows_programs_with_folders() or {}
        except Exception as error:
            print(f"[TitanShell] could not read the Start Menu: {error}")
            structure = {}
        for folder, programs in structure.items():
            entries.append(MenuEntry(folder, 'folder', programs))
        entries.append(MenuEntry(_("Back"), 'back'))
        return entries

    def _titan_app_entries(self, games=False):
        entries = []
        try:
            if games:
                from src.titan_core.game_manager import get_games
                items = get_games() or []
            else:
                from src.titan_core.app_manager import get_applications
                items = get_applications() or []
        except Exception as error:
            print(f"[TitanShell] could not list add-ons: {error}")
            items = []
        for item in items:
            name = item.get('name') or item.get('shortname') or ''
            if name:
                entries.append(MenuEntry(name, 'game' if games else 'app',
                                         item))
        if not entries:
            entries.append(MenuEntry(
                _("No games found") if games else _("No applications"),
                'separator'))
        entries.append(MenuEntry(_("Back"), 'back'))
        return entries

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------
    def _activate_entry(self, entry):
        if entry is None:
            return
        if entry.kind == 'separator':
            return
        if entry.kind == 'back':
            self._go_back()
            return
        if entry.kind == 'folder':
            self._enter_folder(entry)
            return
        if entry.kind == 'app':
            self.run_titan_app(entry.payload)
            self.Hide()
            return
        if entry.kind == 'game':
            self.run_titan_game(entry.payload)
            self.Hide()
            return
        if entry.kind == 'program':
            self.run_program(entry.payload)
            self.Hide()
            return
        self._run_action(entry.payload)

    def _enter_folder(self, entry):
        """Drill into the left column instead of opening a flyout."""
        self._program_stack.append(self.left_list.entries)
        if entry.payload == '__all_programs__':
            self.left_list.set_entries(self._all_programs_entries())
        elif entry.payload == '__apps__':
            self.left_list.set_entries(self._titan_app_entries(games=False))
        elif entry.payload == '__games__':
            self.left_list.set_entries(self._titan_app_entries(games=True))
        elif isinstance(entry.payload, list):
            entries = [MenuEntry(program.get('name', ''), 'program', program)
                       for program in entry.payload]
            entries.append(MenuEntry(_("Back"), 'back'))
            self.left_list.set_entries(entries)
        else:
            self._program_stack.pop()
            return
        self.left_list.SetFocus()

    def _go_back(self):
        if not self._program_stack:
            edge_cue()
            return False
        self.left_list.set_entries(self._program_stack.pop())
        self.left_list.SetFocus()
        return True

    def _run_action(self, action):
        """Actions the XP menu has that the classic one does not."""
        shell = self.shell
        if action == 'titan_window':
            if shell:
                shell.show_titan_window()
            self.Hide()
        elif action == 'file_manager':
            self._open_titan_app('tfm')
            self.Hide()
        elif action == 'internet':
            self._open_titan_app('tweb')
            self.Hide()
        elif action == 'my_pictures':
            win_shell.open_path(os.path.expanduser('~/Pictures'))
            self.Hide()
        elif action == 'my_music':
            win_shell.open_path(os.path.expanduser('~/Music'))
            self.Hide()
        elif action == 'my_computer':
            win_shell.open_path('shell:MyComputerFolder' if IS_WINDOWS
                                else os.path.expanduser('~'))
            self.Hide()
        elif action == 'notifications':
            try:
                from src.ui.notificationcenter import show_notification_center
                show_notification_center(self.parent)
            except Exception as error:
                print(f"[TitanShell] notification centre failed: {error}")
            self.Hide()
        elif action == 'titan_apps' and shell is not None:
            shell.show_titan_window(view='apps')
            self.Hide()
        elif action == 'titan_games' and shell is not None:
            shell.show_titan_window(view='games')
            self.Hide()
        else:
            # Everything else is already implemented by the classic menu.
            self.execute_action(action)

    def _open_titan_app(self, shortname):
        try:
            from src.titan_core.app_manager import (find_application_by_shortname,
                                                    open_application)
            app = find_application_by_shortname(shortname)
            if app:
                open_application(app)
                return True
        except Exception as error:
            print(f"[TitanShell] could not open {shortname}: {error}")
        return False

    def _on_logoff(self, event):
        dialog = wx.MessageDialog(
            self, _("Do you want to log off?"), _("Log Off"),
            wx.YES_NO | wx.ICON_QUESTION)
        answer = dialog.ShowModal()
        dialog.Destroy()
        if answer == wx.ID_YES:
            win_shell.exit_windows('logoff')
        self.Hide()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def _on_char_hook(self, event):
        key = event.GetKeyCode()
        focused = wx.Window.FindFocus()

        if key == wx.WXK_ESCAPE:
            # Escape steps out of a folder first, and only then closes -
            # the same rule as everywhere else in Titan.
            if not self._go_back():
                self.Hide()
            return
        if key == wx.WXK_BACK and focused is self.left_list:
            self._go_back()
            return
        if key == wx.WXK_LEFT and focused is self.right_list:
            self.left_list.SetFocus()
            return
        if key == wx.WXK_RIGHT and focused is self.left_list:
            entry = self.left_list.selected_entry()
            if entry is not None and entry.kind == 'folder':
                self._enter_folder(entry)
            else:
                self.right_list.SetFocus()
            return
        event.Skip()

    # ------------------------------------------------------------------
    # Placement and skinning
    # ------------------------------------------------------------------
    def position_menu(self):
        """Bottom left, sitting on the taskbar, as XP puts it."""
        width, height = win_shell.screen_size()
        size = self.GetSize()
        taskbar_height = self.palette.taskbar_height
        if self.shell is not None:
            taskbar_height = self.shell.taskbar_height()
        self.SetPosition((0, max(0, height - size.height - taskbar_height)))

    def show_menu(self):
        self.apply_skin_settings()
        import time
        self._shown_at = time.time()
        self.build_menu_structure()
        self.position_menu()
        self.Show()
        self.Raise()
        try:
            from src.titan_core.tce_system import force_foreground
            force_foreground(self)
        except Exception:
            pass
        wx.CallAfter(self.left_list.SetFocus)
        if self.shell is not None:
            self.shell.set_start_button_pressed(True)

    def Hide(self):  # noqa: N802 - wx naming
        result = super().Hide()
        if self.shell is not None:
            try:
                self.shell.set_start_button_pressed(False)
            except Exception:
                pass
        return result

    def on_activate(self, event):
        if event.GetActive():
            wx.CallAfter(self.left_list.SetFocus)

    def apply_skin_settings(self):
        """The Start menu follows the skin like everything else."""
        try:
            self.palette = luna.get_palette()
            self.left_list.SetBackgroundColour(
                self.palette['menu_left_background'])
            self.left_list.SetForegroundColour(self.palette['menu_left_text'])
            self.right_list.SetBackgroundColour(
                self.palette['menu_right_background'])
            self.right_list.SetForegroundColour(
                self.palette['menu_right_text'])
            self.Refresh()
        except Exception as error:
            print(f"[TitanShell] could not skin the Start menu: {error}")

    def configure_from_skin(self, start_menu_config, colors):
        """The classic menu's hook; the palette already did the work."""
        self.apply_skin_settings()


def create_xp_start_menu(parent, shell=None):
    return XPStartMenu(parent, shell=shell)
