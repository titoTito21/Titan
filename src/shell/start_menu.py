# -*- coding: utf-8 -*-
"""
The Start menu, in its XP shape: a blue header with the user's name, a white
left column of programs, a pale blue right column of places, and a footer
with Log Off and Turn Off Computer.

It is `ClassicStartMenu` with a different face.  Everything that finds
programs, runs a Titan application or a game, opens the Run dialog or asks
about shutting down already lives there and is inherited unchanged, and
everything the menu LISTS - the applications and games, the Titan IM
services and modules, the macros, the settings, the Windows apps and the
Windows Start Menu - lives in `src/ui/start_menu_content.py`, which the
classic menu lists from as well.  This module supplies the XP layout and
the two panes, not a second start menu and not a second set of contents.

**Every part of it takes the keyboard.**  ReactOS' own menu is a chain of
windows a mouse walks and a keyboard cannot, so the pieces here are ordinary
focusable controls instead: the user's name is a real button, the search box
is a real edit field, both columns are list controls and the two power
commands are real buttons - and Tab walks the ring of them in that order,
with Shift+Tab going back.  The arrow keys, first-letter jumping and the
mouse then come from the controls themselves, and so does everything a
screen reader reads.

"All Programs" opens *inside* the left column, with Backspace and Escape
stepping back out, rather than as a cascade of flyouts a keyboard cannot
follow; typing in the search box replaces that column with what was found,
across the Titan applications and games and the whole Windows Start Menu.
"""

import os

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import luna, win_shell
from src.shell import keyboard_handover as handover
from src.shell.deferred import call_after, call_later
from src.system import key_state
from src.shell.a11y import ROLE_BUTTON, edge_cue, name_control
from src.shell.controls import ShellControl
from src.ui.classic_start_menu import ClassicStartMenu
from src.ui.start_menu_content import MenuEntry, MenuTree
from src.titan_core.translation import _

# How long to wait for the activation that hands the keyboard over before
# doing it anyway.  There is no activation when the menu was already the
# active window, and Windows can refuse the foreground outright.
FOCUS_FALLBACK_MS = 300

MENU_WIDTH = 420
MENU_HEIGHT = 520
HEADER_HEIGHT = 58
FOOTER_HEIGHT = 42
LEFT_WIDTH = 224


class MenuList(wx.ListCtrl):
    """A column of the Start menu.

    A report-mode list view with no header is what XP's own columns are, and
    it is read by name and role by every screen reader without any help.
    """

    def __init__(self, parent, on_activate, background, foreground, name):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_NO_HEADER
                         | wx.LC_SINGLE_SEL | wx.NO_BORDER | wx.WANTS_CHARS)
        name_control(self, name)
        self.entries = []
        self._on_activate = on_activate
        self.InsertColumn(0, name)
        self.SetBackgroundColour(background)
        self.SetForegroundColour(foreground)

        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._activate)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)
        self.Bind(wx.EVT_LEFT_DCLICK, lambda event: self._activate(event))

    def set_name_for_reader(self, name):
        """Rename the list for wx and for MSAA in one call."""
        name_control(self, name)

    def set_columns(self, headings):
        """One column per thing a row has to say.

        A screen reader reads every column of a list view row, so a search
        result that is "Notepad" in one column and "Accessories" in the
        next is read as both - which is how Windows' own results say what
        they are without a sighted user having to guess from an icon.
        """
        current = self.GetColumnCount()
        for index in range(current, len(headings)):
            self.InsertColumn(index, headings[index])
        while self.GetColumnCount() > len(headings):
            self.DeleteColumn(self.GetColumnCount() - 1)
        for index, heading in enumerate(headings):
            column = self.GetColumn(index)
            column.SetText(heading)
            self.SetColumn(index, column)
        self.set_name_for_reader(headings[0])

    def set_heading(self, name):
        """Rename the column: what a screen reader reads on arriving in it.

        It is also the list view's single column header, which is what makes
        "Search results: 12" appear without a word being spoken.
        """
        self.set_name_for_reader(name)
        try:
            column = self.GetColumn(0)
            column.SetText(name)
            self.SetColumn(0, column)
        except Exception:
            pass

    @staticmethod
    def signature(entries):
        return [(entry.label, entry.kind,
                 entry.payload if isinstance(entry.payload, str) else None)
                for entry in (entries or [])]

    def matches(self, entries):
        """True when the column already shows exactly these entries."""
        current = getattr(self, 'entries', None)
        if not current or len(current) != len(entries or []):
            return False
        return self.signature(current) == self.signature(entries)

    def set_entries(self, entries, select_first=True):
        self.Freeze()
        try:
            self._set_entries(entries, select_first)
        finally:
            self.Thaw()

    def _set_entries(self, entries, select_first=True):
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
            if self.GetColumnCount() > 1:
                self.SetItem(index, 1, entry.description or '')
        for column in range(self.GetColumnCount()):
            self.SetColumnWidth(column, wx.LIST_AUTOSIZE_USEHEADER)
        if self.entries and select_first:
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


class UserButton(ShellControl):
    """The blue header: who is logged in, and a way into their own files.

    XP paints the user's name and picture up here and opens User Accounts
    when it is clicked.  A painted strip is nothing to a screen reader, so
    this is a real focusable control with a name and a role - pressing it
    opens the user's own folder, and its menu offers the account settings.
    """

    accessible_role = ROLE_BUTTON

    def __init__(self, parent, on_open=None):
        self._user = win_shell.user_display_name()
        super().__init__(parent, size=(MENU_WIDTH, HEADER_HEIGHT),
                         name=self._user)
        self._on_open = on_open
        self.accessible_description = _("Your user account")
        self.accessible_action = _("Open your files")
        self.refresh_accessible_name()
        self.set_tooltip(_("Your user account"))

    def refresh_user(self):
        self._user = win_shell.user_display_name()
        self.accessible_name = self._user
        self.refresh_accessible_name()
        self.Refresh()

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        rect = wx.Rect(0, 0, *self.GetSize())
        luna.draw_gradient(dc, rect, self.palette['menu_header'])
        dc.SetFont(self.palette.font(size=12, bold=True))
        dc.SetTextForeground(self.palette['menu_header_text'])
        _width, height = dc.GetTextExtent(self._user)
        dc.DrawText(self._user, 12, (rect.height - height) // 2)
        if self.HasFocus():
            dc.SetPen(wx.Pen(self.palette['menu_header_text'], 1,
                             wx.PENSTYLE_DOT))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle(3, 3, rect.width - 6, rect.height - 6)

    def shell_activate(self):
        if callable(self._on_open):
            self._on_open()

    def show_context_menu(self):
        menu = wx.Menu()
        files = menu.Append(wx.ID_ANY, _("Open your &files"))
        account = menu.Append(wx.ID_ANY, _("&User accounts"))
        self.Bind(wx.EVT_MENU, lambda event: self.shell_activate(), files)
        self.Bind(wx.EVT_MENU,
                  lambda event: win_shell.shell_execute(
                      'control nusrmgr.cpl' if IS_WINDOWS else ''),
                  account)
        self.PopupMenu(menu)
        menu.Destroy()


class XPStartMenu(ClassicStartMenu):
    """The Start menu of the Titan shell."""

    def __init__(self, parent, shell=None):
        self.shell = shell
        self.palette = luna.get_palette()
        self._program_stack = []
        # Built on the first keystroke in the search box and thrown away
        # when the menu is next opened, so a program installed in between is
        # found without Titan being restarted.
        self._search_index = None
        self._prefetching = False
        self._announce_timer = None
        self._announce_count = 0
        # Set while the menu is opening: the keyboard belongs to the
        # opening sequence until the activation has handed it over.
        self._focus_pending = False
        super().__init__(parent)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def init_ui(self):
        palette = self.palette
        panel = wx.Panel(self)
        panel.SetBackgroundColour(palette['menu_right_background'])
        self.panel = panel

        self.header = UserButton(panel, on_open=self._open_user_folder)

        # The search box.  A visible label beside a real edit field, because
        # that is what makes an edit field readable on Windows: the label is
        # what a screen reader falls back to when it asks a text control what
        # it is called.
        self.search_label = wx.StaticText(panel, label=_("&Search:"))
        self.search_field = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        name_control(self.search_field, _("Search programs and files"))
        self.search_field.SetHint(_("Search programs and files"))
        self.search_field.Bind(wx.EVT_TEXT, self._on_search_text)
        self.search_field.Bind(wx.EVT_TEXT_ENTER, self._on_search_enter)

        # The menu itself is the tree; the list beside it is what search
        # results are shown in, because results want columns and a tree
        # cannot have them.  Only one of the two is ever on screen.
        self.left_tree = MenuTree(
            panel, self._activate_entry, self._children_of,
            palette['menu_left_background'], palette['menu_left_text'],
            _("Programs"))
        self.left_list = MenuList(
            panel, self._activate_entry, palette['menu_left_background'],
            palette['menu_left_text'], _("Search results"))
        self.left_list.Hide()
        self.right_list = MenuList(
            panel, self._activate_entry, palette['menu_right_background'],
            palette['menu_right_text'], _("Places"))

        self.footer = wx.Panel(panel, size=(MENU_WIDTH, FOOTER_HEIGHT))
        self.footer.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.footer.Bind(wx.EVT_PAINT, self._paint_footer)
        self.footer.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)

        # Power.  XP has two commands here and the second one opens msgina's
        # dialog, which is where restarting, sleeping and hibernating live -
        # so everything the machine can be told to do is one Tab away.
        self.lock_button = wx.Button(self.footer, label=_("Loc&k"))
        self.logoff_button = wx.Button(self.footer, label=_("&Log Off"))
        self.shutdown_button = wx.Button(self.footer,
                                         label=_("&Turn Off Computer"))
        # A button's label *is* its accessible name on Windows, so there is
        # nothing else to name here.
        self.lock_button.Bind(wx.EVT_BUTTON, self._on_lock)
        self.logoff_button.Bind(wx.EVT_BUTTON, self._on_logoff)
        self.shutdown_button.Bind(wx.EVT_BUTTON, self.on_shutdown)

        footer_sizer = wx.BoxSizer(wx.HORIZONTAL)
        footer_sizer.AddStretchSpacer(1)
        for button in (self.lock_button, self.logoff_button,
                       self.shutdown_button):
            footer_sizer.Add(button, 0, wx.ALL | wx.ALIGN_CENTRE, 4)
        self.footer.SetSizer(footer_sizer)

        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_sizer.Add(self.search_label, 0,
                         wx.ALIGN_CENTRE_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        search_sizer.Add(self.search_field, 1,
                         wx.ALIGN_CENTRE_VERTICAL | wx.RIGHT, 6)

        columns = wx.BoxSizer(wx.HORIZONTAL)
        columns.Add(self.left_tree, 0, wx.EXPAND)
        columns.Add(self.left_list, 0, wx.EXPAND)
        columns.Add(self.right_list, 1, wx.EXPAND)
        self.left_tree.SetMinSize((LEFT_WIDTH, -1))
        self.left_list.SetMinSize((LEFT_WIDTH, -1))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.header, 0, wx.EXPAND)
        sizer.Add(search_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 4)
        sizer.Add(columns, 1, wx.EXPAND)
        sizer.Add(self.footer, 0, wx.EXPAND)
        panel.SetSizer(sizer)

        self.SetSize((MENU_WIDTH, MENU_HEIGHT))

    def _paint_footer(self, event):
        dc = wx.AutoBufferedPaintDC(self.footer)
        rect = wx.Rect(0, 0, *self.footer.GetSize())
        luna.draw_gradient(dc, rect, self.palette['menu_footer'])

    # ------------------------------------------------------------------
    # Contents
    # ------------------------------------------------------------------
    def build_menu_structure(self):
        """Both columns, rebuilt only where something has changed.

        Neither column's top level changes between one open and the next -
        what changes is what a branch reads when it is opened - and putting
        the entries back into the controls measured 14 ms of the taskbar's
        Start button feeling slow.
        """
        self.menu_items = []
        self._program_stack = []
        self._search_index = None
        self._programs_structure = None
        entries = self._top_level_entries()
        if self.left_tree.matches(entries):
            self.left_tree.reset_branches()
        else:
            self.left_tree.set_entries(entries)
        places = self._places_entries()
        if not self.right_list.matches(places):
            self.right_list.set_entries(places)

    def _top_level_entries(self):
        """The left column, as branches that open where they stand.

        What a shell add-on contributes goes at the end, after All
        Programs: the column's own ten entries are where the user has
        learnt they are, and something installed afterwards must not move
        them.
        """
        return [
            MenuEntry(_("Titan"), 'action', 'titan_window'),
            MenuEntry(_("Applications"), 'folder', '__apps__'),
            MenuEntry(_("Games"), 'folder', '__games__'),
            MenuEntry(_("Titan IM"), 'folder', '__im__'),
            MenuEntry(_("Macros"), 'folder', '__macros__'),
            MenuEntry(_("Settings"), 'folder', '__settings__'),
            MenuEntry(_("File manager"), 'action', 'file_manager'),
            MenuEntry(_("Internet"), 'action', 'internet'),
            MenuEntry(_("Windows apps"), 'folder', '__windows_apps__'),
            MenuEntry(_("All Programs"), 'folder', '__all_programs__'),
        ] + self.addon_entries()

    def _places_entries(self):
        """The right column: places and the things that are not settings."""
        return [
            MenuEntry(_("My Documents"), 'action', 'my_documents'),
            MenuEntry(_("My Pictures"), 'action', 'my_pictures'),
            MenuEntry(_("My Music"), 'action', 'my_music'),
            MenuEntry(_("My Computer"), 'action', 'my_computer'),
            MenuEntry(_("Notification centre"), 'action', 'notifications'),
            MenuEntry(_("Search"), 'action', 'find'),
            MenuEntry(_("Run..."), 'action', 'run'),
            MenuEntry(_("Help and Support"), 'action', 'help'),
        ]

    def _on_search_text(self, event):
        text = self.search_field.GetValue()
        if not text.strip():
            self._show_menu_tree()
            event.Skip()
            return
        results = self.search_entries(text)
        self._show_results_list()
        # Two columns while searching: what it is called, and where it came
        # from.  A reader then says "Notepad, Accessories" for the row.
        self.left_list.set_columns([
            _("Search results: {count}").format(count=len(results)),
            _("Where")])
        self.left_list.set_entries(results, select_first=False)
        if not results:
            self.left_list.set_heading(_("Nothing found"))
        self._announce_results(len(results))
        event.Skip()

    def _announce_results(self, count):
        """Say the count, once the typing has stopped.

        On every keystroke would talk over the letters themselves, so it
        waits out a short pause first - which is also what stops a fast
        typist hearing five counts for one word.
        """
        try:
            if self._announce_timer is None:
                self._announce_timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self._on_announce_tick,
                          self._announce_timer)
            self._announce_count = count
            self._announce_timer.Start(400, wx.TIMER_ONE_SHOT)
        except Exception:
            pass

    def _on_announce_tick(self, _event):
        try:
            from src.accessibility.messages import announce_search_results
            announce_search_results(self._announce_count)
        except Exception:
            pass

    def _on_search_enter(self, event):
        results = self.left_list.entries
        if results:
            self.left_list.Select(0)
            self.left_list.Focus(0)
            self._activate_entry(results[0])
        else:
            edge_cue()

    def clear_search(self):
        """Empty the box and put the menu back; True when there was any."""
        if not self.search_field.GetValue():
            return False
        self.search_field.ChangeValue('')
        self._show_menu_tree()
        return True

    def _show_menu_tree(self):
        """The menu itself is in the left column."""
        self._program_stack = []
        entries = self._top_level_entries()
        if self.left_tree.matches(entries):
            self.left_tree.reset_branches()
        else:
            self.left_tree.set_entries(entries)
        if not self.left_tree.IsShown():
            self.left_list.Hide()
            self.left_tree.Show()
            self.panel.Layout()

    def _show_results_list(self):
        """Search results are, so the columns can say where each came from."""
        if not self.left_list.IsShown():
            self.left_tree.Hide()
            self.left_list.Show()
            self.panel.Layout()

    def left_column(self):
        """Whichever of the two is on screen - the menu, or the results."""
        return self.left_list if self.left_list.IsShown() else self.left_tree

    def _open_user_folder(self):
        """The header: the user's own files."""
        win_shell.open_path(os.path.expanduser('~'))
        self.Hide()

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

    def _on_lock(self, event):
        self.Hide()
        win_shell.lock_workstation()

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
    def focus_ring(self):
        """Every stop of the menu, in the order Tab visits them.

        The whole menu is one ring - the user's name, the search box, the
        two columns and the three power commands - so nothing in it can be
        reached only with a mouse.  Tab has to be handled here rather than
        left to wx: both columns are list controls asked for `WANTS_CHARS`
        (that is what gives them first-letter jumping), and a control that
        wants the characters is given Tab as well.
        """
        ring = [self.header, self.search_field, self.left_column(),
                self.right_list, self.lock_button, self.logoff_button,
                self.shutdown_button]
        return [control for control in ring
                if control is not None and control.IsShown()]

    def _move_focus(self, delta):
        ring = self.focus_ring()
        if not ring:
            return
        focused = wx.Window.FindFocus()
        index = -1
        for position, control in enumerate(ring):
            if control is focused or (focused is not None
                                      and control.IsDescendant(focused)):
                index = position
                break
        if index < 0:
            index = 0 if delta > 0 else len(ring) - 1
        else:
            index = (index + delta) % len(ring)
        try:
            ring[index].SetFocus()
        except Exception:
            pass

    def on_char_hook(self, event):
        """The frame's char hook, which `ClassicStartMenu` binds.

        Binding a second one here would leave both running for every key -
        the classic menu's Escape closes the menu, this one's clears the
        search box first - so the XP menu's keys are an override of the one
        binding rather than a binding of their own.
        """
        self._on_char_hook(event)

    def _on_char_hook(self, event):
        key = event.GetKeyCode()
        # A key before the activation has handed the keyboard over: take it
        # now, so the first keystroke is never the one that goes nowhere.
        if self._focus_pending:
            self._hand_over_focus()
        focused = wx.Window.FindFocus()

        if key == wx.WXK_F4 and event.AltDown():
            # The menu is part of the shell, so Alt+F4 in it means what it
            # means anywhere else in the shell: the Shut Down dialog.
            from src.shell.shutdown_dialog import shell_alt_f4
            self.Hide()
            shell_alt_f4(self.shell.parent if self.shell else None)
            return
        if key == wx.WXK_TAB:
            self._move_focus(-1 if key_state.shift_down(event) else 1)
            return
        if key == wx.WXK_ESCAPE:
            # Escape undoes one thing at a time: the search first, then the
            # folder that was opened in the left column, and only then does
            # it close the menu - the same rule as everywhere else in Titan.
            if self.clear_search():
                self.search_field.SetFocus()
                return
            if not self._go_back():
                self.close_to_start_button()
            return
        if focused is self.search_field:
            # The box hands the keyboard down to the results, and nothing
            # else it does is the menu's business - a letter typed in a
            # search box is a letter, not a first-letter jump.
            if key in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN):
                column = self.left_column()
                column.SetFocus()
                if column is self.left_list and self.left_list.entries:
                    self.left_list.Select(0)
                    self.left_list.Focus(0)
                return
            event.Skip()
            return
        if key == wx.WXK_BACK and focused is self.left_list:
            self._go_back()
            return
        if focused is self.left_tree:
            # Inside the tree the arrows belong to the tree: Left closes a
            # branch or steps up to its parent, Right opens it.  Moving
            # between the columns is Tab's job, as it is in any window.
            event.Skip()
            return
        if key == wx.WXK_LEFT and focused is self.right_list:
            self.left_column().SetFocus()
            return
        if key == wx.WXK_UP and focused is self.left_list                 and self.left_list.GetFirstSelected() == 0                 and self.search_field.GetValue():
            # Off the top of the results is the box they came from.
            self.search_field.SetFocus()
            self.search_field.SetInsertionPointEnd()
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

    def close_to_start_button(self):
        """Escape: close, and leave the keyboard where Windows leaves it.

        On Windows the menu closes onto the Start button it came out of -
        not onto a window of its own, and not nowhere.  Escape there is
        then the taskbar's own, which hands the keyboard back to whatever
        the user was working in, so two presses of Escape are the whole way
        out of the shell.
        """
        self.Hide()
        shell = self.shell
        if shell is None:
            return False
        try:
            return bool(shell.focus_start_button())
        except Exception as error:
            print(f"[TitanShell] could not go back to Start: {error}")
            return False

    def show_menu(self):
        self.apply_skin_settings()
        import time
        self._shown_at = time.time()
        try:
            self.search_field.ChangeValue('')
            self.header.refresh_user()
        except Exception:
            pass
        self.build_menu_structure()
        self.prefetch()
        self.position_menu()
        # Claimed BEFORE the window is shown: `Show()` answers the
        # activation synchronously, and `on_activate` focusing the tree
        # there and then is what put the control in front of the window's
        # name however carefully the name was said first.
        self._focus_pending = True
        self.Show()
        self.Raise()
        # A menu is furniture too - it must not turn up in Alt+Tab beside
        # the user's own windows.
        try:
            win_shell.hide_from_alt_tab(self.GetHandle())
        except Exception:
            pass
        try:
            from src.titan_core.tce_system import force_foreground
            force_foreground(self)
        except Exception:
            pass
        # The keyboard is handed over from the ACTIVATION (see
        # `on_activate`), not from here; this is only the fallback for when
        # no activation arrives - the menu was already the active window,
        # or Windows refused the foreground.
        call_later(self, FOCUS_FALLBACK_MS, self._hand_over_focus)
        if self.shell is not None:
            self.shell.set_start_button_pressed(True)

    def _hand_over_focus(self):
        """Put the keyboard in the menu, once however this is reached.

        Once, because twice is what a screen reader reads as the control
        twice: wxWidgets answers WM_ACTIVATE by focusing the FRAME, so a
        focus set before the window has finished becoming active is undone
        and then put back.  That is why the hand-over is driven by the
        activation (see `on_activate`) and why this is a one-shot.

        Nothing is SAID here.  The window is called "Start menu" and a
        screen reader reads the name of a window it has just entered -
        Titan Access does it from `context_presenter`, NVDA from the
        foreground change - so an announcement of Titan's own would be a
        second copy of the title, and the focus would have to be held back
        for it or the reader would cut it off mid-word.
        """
        if not self._focus_pending:
            return
        self._focus_pending = False
        self.focus_now()

    def focus_now(self):
        """The keyboard goes to whichever column the menu is showing."""
        self._focus_pending = False
        try:
            column = self.left_column()
            if column is not None and wx.Window.FindFocus() is not column:
                column.SetFocus()
        except Exception:
            pass

    # `Hide` is not overridden here: the classic menu's own already lets the
    # Start button up, and doing it twice is two answers to one question.

    def on_activate(self, event):
        # A menu with a search box in it: every key belongs to the menu
        # while it is up, exactly as they belong to the main window when
        # that is up.
        handover.follows_activation(event)
        if event.GetActive():
            # Opening: this is the hand-over.  It happens here because
            # wxWidgets has just focused the frame in answer to
            # WM_ACTIVATE, so this is the first moment a focus will stay
            # where it is put - and doing it before that meant setting it,
            # having it undone, and setting it again, which a screen reader
            # reads as the control twice.
            if self._focus_pending:
                call_after(self, self._hand_over_focus)
                return
            # Already in the menu - an activation that changes nothing must
            # not make the reader say the control again.
            focused = wx.Window.FindFocus()
            if focused is not None and self.IsDescendant(focused):
                return
            # No announcement here: coming back to a menu that is already
            # up must not say its name a second time.
            call_after(self, lambda: self.left_column().SetFocus())

    def apply_skin_settings(self):
        """The Start menu follows the skin like everything else."""
        try:
            self.palette = luna.get_palette()
            self.header.refresh_palette(self.palette)
            self.left_tree.SetBackgroundColour(
                self.palette['menu_left_background'])
            self.left_tree.SetForegroundColour(self.palette['menu_left_text'])
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
