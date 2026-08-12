# -*- coding: utf-8 -*-
"""
The Start menu, in its XP shape: a blue header with the user's name, a white
left column of programs, a pale blue right column of places, and a footer
with Log Off and Turn Off Computer.

It is `ClassicStartMenu` with a different face.  Everything that finds
programs, runs a Titan application or a game, opens the Run dialog or asks
about shutting down already lives there and is inherited unchanged - this
module supplies the XP layout and the two panes, not a second start menu.

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
import threading

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import luna, win_shell
from src.shell.a11y import ROLE_BUTTON, edge_cue, name_control
from src.shell.controls import ShellControl
from src.ui.classic_start_menu import ClassicStartMenu
from src.titan_core.translation import _

MENU_WIDTH = 420
MENU_HEIGHT = 520
HEADER_HEIGHT = 58
FOOTER_HEIGHT = 42
LEFT_WIDTH = 224


class MenuEntry:
    """One line of either column."""

    __slots__ = ('label', 'kind', 'payload', 'description', 'filled')

    def __init__(self, label, kind='action', payload=None, description=''):
        self.label = label
        # action | app | game | program | folder | im_module | macro |
        # back | separator
        self.kind = kind
        self.payload = payload
        self.description = description
        # A branch fills itself the first time it is opened; this is how it
        # knows it already has.
        self.filled = False


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

    def set_entries(self, entries, select_first=True):
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


class MenuTree(wx.TreeCtrl):
    """The left column: the menu as a tree that opens where it stands.

    A submenu that flies out is a menu a keyboard cannot follow, and the
    word "submenu" written into an entry is a word a screen reader then
    reads out.  A tree control has both problems solved already: it is
    expanded and collapsed with the arrows, and the reader says "collapsed"
    or "expanded" itself, from the control's own state - so nothing here
    puts that into the text.

    Branches fill themselves the first time they are opened, because
    reading the whole Windows Start Menu, every Titan add-on and every
    macro up front is most of a second the user would wait for a menu.
    """

    def __init__(self, parent, on_activate, children_of, background,
                 foreground, name):
        super().__init__(parent, style=wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS
                         | wx.TR_SINGLE | wx.TR_LINES_AT_ROOT
                         | wx.TR_FULL_ROW_HIGHLIGHT | wx.NO_BORDER
                         | wx.WANTS_CHARS)
        name_control(self, name)
        self._on_activate = on_activate
        self._children_of = children_of
        self._root = self.AddRoot('')
        self.SetBackgroundColour(background)
        self.SetForegroundColour(foreground)

        self.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._activate)
        self.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._expanding)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key)

    # -- contents ---------------------------------------------------------
    def set_entries(self, entries):
        self.DeleteChildren(self._root)
        self.entries = list(entries)
        for entry in self.entries:
            self._add(self._root, entry)
        first = self.GetFirstChild(self._root)[0]
        if first and first.IsOk():
            self.SelectItem(first)

    def _add(self, parent, entry):
        item = self.AppendItem(parent, entry.label)
        self.SetItemData(item, entry)
        if entry.kind == 'folder':
            # A branch has to look like one before it is filled, and this is
            # how a tree control is told so.
            self.AppendItem(item, '')
        return item

    def _expanding(self, event):
        item = event.GetItem()
        entry = self.GetItemData(item)
        if entry is None or entry.kind != 'folder':
            return
        if entry.filled:
            return
        self.DeleteChildren(item)
        for child in (self._children_of(entry) or []):
            self._add(item, child)
        entry.filled = True

    # -- what is on it ----------------------------------------------------
    def selected_entry(self):
        item = self.GetSelection()
        if item and item.IsOk():
            return self.GetItemData(item)
        return None

    def _activate(self, event):
        entry = self.selected_entry()
        if entry is None:
            return
        if entry.kind == 'folder':
            # Enter on a branch opens it, which is what Enter does to a
            # branch everywhere else in Windows.
            item = self.GetSelection()
            if self.IsExpanded(item):
                self.Collapse(item)
            else:
                self.Expand(item)
            return
        if callable(self._on_activate):
            self._on_activate(entry)

    def _on_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
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
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

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
        self._search_index = None
        self.left_tree.set_entries(self._top_level_entries())
        self.right_list.set_entries(self._places_entries())

    def _top_level_entries(self):
        """The left column, as branches that open where they stand."""
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
        ]

    def _children_of(self, entry):
        """What is under a branch, worked out the first time it is opened."""
        payload = entry.payload
        if payload == '__all_programs__':
            return self._all_programs_entries()
        if payload == '__apps__':
            return self._titan_app_entries(games=False)
        if payload == '__games__':
            return self._titan_app_entries(games=True)
        if payload == '__im__':
            return self._im_entries()
        if payload == '__macros__':
            return self._macro_entries()
        if payload == '__settings__':
            return self._settings_entries()
        if payload == '__windows_apps__':
            return self._windows_app_entries()
        if isinstance(payload, list):
            return [MenuEntry(program.get('name', ''), 'program', program,
                              description=entry.label)
                    for program in payload]
        return []

    # The services Titan brings itself, in the order its own Titan IM list
    # has them.  Each is (id, label): what the entry is called, and which of
    # the main window's own flows opens it - the menu must not have a second
    # opinion about whether somebody is logged in.
    BUILTIN_IM = (
        ('telegram', "Telegram"),
        ('messenger', "Facebook Messenger"),
        ('whatsapp', "WhatsApp"),
        ('titannet', "Titan-Net"),
        ('elten', "EltenLink"),
    )

    def _im_entries(self):
        """Titan IM: the services Titan has built in, then the modules."""
        entries = [MenuEntry(label, 'im_builtin', identifier,
                             description=_("Titan IM"))
                   for identifier, label in self.BUILTIN_IM]
        try:
            from src.network.im_module_manager import im_module_manager
            if not getattr(im_module_manager, 'modules', None)                     and wx.IsMainThread():
                # Nothing has asked for them yet in this process - the menu
                # is allowed to be the first, and it happens once, on the
                # branch actually being opened.  Never off the GUI thread:
                # loading a module runs its author's code, which is written
                # expecting to be on it.
                im_module_manager.load_modules()
            for info in getattr(im_module_manager, 'modules', []) or []:
                name = info.get('name') or info.get('id') or ''
                if name:
                    entries.append(MenuEntry(name, 'im_module', info,
                                             description=_("Titan IM")))
        except Exception as error:
            print(f"[TitanShell] could not list the IM modules: {error}")
        return entries

    def _open_builtin_im(self, service):
        """Open one of Titan's own messengers, through the main window.

        Whether Telegram shows its options or its login, whether Titan-Net
        is connected, whether EltenLink already has a window open - the main
        window knows and the menu must not guess, so this calls the very
        methods its own Titan IM list calls.
        """
        frame = self.parent
        if frame is None:
            app = wx.GetApp()
            frame = app.GetTopWindow() if app else None
        if frame is None:
            print("[TitanShell] there is no Titan window to open IM in")
            return False

        def opener():
            try:
                active = getattr(frame, 'active_services', {}) or {}
                if service == 'telegram':
                    if 'telegram' in active:
                        frame.current_service = 'telegram'
                        frame.show_telegram_options()
                    else:
                        frame.show_telegram_login()
                elif service == 'messenger':
                    frame.show_messenger_login()
                elif service == 'whatsapp':
                    frame.show_whatsapp_login()
                elif service == 'titannet':
                    if getattr(frame, 'titan_logged_in', False) and \
                            getattr(getattr(frame, 'titan_client', None),
                                    'is_connected', False):
                        frame.show_titannet_main()
                    else:
                        frame.titan_logged_in = False
                        frame.show_titannet_login()
                elif service == 'elten':
                    window = (active.get('eltenlink') or {}).get('window')
                    client = getattr(window, 'client', None)
                    if window and getattr(client, 'is_connected', False):
                        window.Show()
                        window.Raise()
                    else:
                        frame.show_elten_login()
            except Exception as error:
                print(f"[TitanShell] could not open {service}: {error}")

        wx.CallAfter(opener)
        return True

    def _macro_entries(self):
        """The user's macros - the same ones the macro manager lists."""
        entries = []
        for macro in self._macros():
            name = macro.get('name') or macro.get('folder_name') or ''
            if not name:
                continue
            hotkey = macro.get('hotkey') or ''
            entries.append(MenuEntry(
                "{} ({})".format(name, hotkey) if hotkey else name,
                'macro', macro, description=_("Macros")))
        if not entries:
            entries.append(MenuEntry(_("No macros"), 'separator'))
        return entries

    def _macros(self):
        """Ask the macro manager component itself, so this list is its own.

        The component is already loaded - it is what runs the macros and
        owns their shortcuts - so the menu reads its manager rather than
        parsing `__macro__.TCE` a second time and drifting from it.
        """
        module = self._macro_component()
        if module is None:
            return []
        try:
            manager = module.MacroManager(module.MACROS_DIR,
                                          module.USER_MACROS_DIR)
            manager.load_macros()
            return list(manager.macros)
        except Exception as error:
            print(f"[TitanShell] could not read the macros: {error}")
            return []

    @staticmethod
    def _macro_component():
        import sys
        for module in list(sys.modules.values()):
            if module is None:
                continue
            if hasattr(module, 'MacroManager') and hasattr(module, 'run_macro') \
                    and hasattr(module, 'MACROS_DIR'):
                return module
        return None

    def _windows_app_entries(self):
        """Every app Windows itself would show, UWP ones included.

        `shell:AppsFolder` is the list the Windows Start menu is made of -
        Store apps, packaged apps and desktop programs alike - and it is the
        only place a UWP app appears at all: there is no shortcut on disk to
        find, only an Application User Model ID to launch.  Reading it takes
        over a second, so it is read once, in the background (see
        `prefetch`), and kept until the menu is next opened.
        """
        entries = []
        for name, app_id in win_shell.installed_apps():
            entries.append(MenuEntry(name, 'uwp', app_id,
                                     description=_("Windows apps")))
        if not entries:
            entries.append(MenuEntry(_("No applications"), 'separator'))
        return entries

    def _settings_entries(self):
        """Everything that changes how the machine or Titan behaves.

        Titan's own settings belong here rather than out among the places:
        "where do I change something" has one answer.
        """
        entries = [
            MenuEntry(_("Titan settings"), 'action', 'titan_settings',
                      description=_("Settings")),
            MenuEntry(_("Control Panel"), 'action', 'control_panel',
                      description=_("Settings")),
            MenuEntry(_("Taskbar and Start menu"), 'action',
                      'taskbar_properties', description=_("Settings")),
            MenuEntry(_("Display properties"), 'action', 'display_properties',
                      description=_("Settings")),
            MenuEntry(_("Windows settings"), 'action', 'windows_settings',
                      description=_("Settings")),
        ]
        return entries

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

    def _all_programs_entries(self):
        """The Windows Start Menu, folder by folder.

        Titan's own applications and games are branches of their own at the
        top of the column, so they are not repeated in here.
        """
        entries = []
        try:
            structure = self.load_windows_programs_with_folders() or {}
        except Exception as error:
            print(f"[TitanShell] could not read the Start Menu: {error}")
            structure = {}
        for folder, programs in structure.items():
            entries.append(MenuEntry(folder, 'folder', programs))
        return entries

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def prefetch(self):
        """Get the slow lists ready before anybody asks for them.

        Reading `shell:AppsFolder` is over a second and walking the Windows
        Start Menu is a few hundred milliseconds - on the first keystroke in
        the search box that is a keystroke that appears to hang.  So it is
        done on a thread the moment the menu opens, and the box uses
        whatever is ready by the time it is typed in.
        """
        if self._prefetching:
            return
        self._prefetching = True

        def work():
            # Everything read here goes through the shell one way or
            # another - the Apps folder, the shortcut names - and a thread
            # of its own has no COM apartment until it says so.
            initialised = False
            try:
                import pythoncom
                pythoncom.CoInitialize()
                initialised = True
            except Exception:
                pass
            try:
                win_shell.installed_apps()      # fills its own cache
                index = self._build_search_index()
            except Exception as error:
                print(f"[TitanShell] could not prepare the menu: {error}")
                index = None
            finally:
                self._prefetching = False
                if initialised:
                    try:
                        import pythoncom
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass
            if index is not None:
                # Only a plain assignment crosses back to the GUI thread -
                # the list is finished and never touched again.
                self._search_index = index

        threading.Thread(target=work, daemon=True,
                         name='TitanShellMenuIndex').start()

    def _build_search_index(self):
        """Everything the menu can open, flattened into one list.

        Built once per open of the menu rather than per keystroke: reading
        the Windows Start Menu is a walk of two folder trees, and doing that
        on every letter is what would make the box feel broken.
        """
        entries = []
        for entry in self._top_level_entries():
            entry.description = entry.description or _("Titan")
            entries.append(entry)
        for entry in self._places_entries():
            entry.description = entry.description or _("Places")
            entries.append(entry)
        for entry in self._titan_app_entries(games=False):
            if entry.kind == 'app':
                entry.description = _("Titan application")
                entries.append(entry)
        for entry in self._titan_app_entries(games=True):
            if entry.kind == 'game':
                entry.description = _("Titan game")
                entries.append(entry)
        entries.extend(self._searchable_branches())
        try:
            structure = self.load_windows_programs_with_folders() or {}
        except Exception as error:
            print(f"[TitanShell] could not read the Start Menu: {error}")
            structure = {}
        for folder, programs in structure.items():
            for program in programs:
                name = program.get('name', '')
                if name:
                    entries.append(MenuEntry(name, 'program', program,
                                             description=folder))
        return [entry for entry in entries
                if entry.kind not in ('separator', 'back', 'folder')]

    def _searchable_branches(self):
        """The branches whose contents the search box looks inside.

        A user typing three letters is looking for a thing, not for the
        branch it happens to live under - so the modules, the macros and
        the settings are searched exactly like the programs are.
        """
        return (self._im_entries() + self._macro_entries()
                + self._settings_entries() + self._windows_app_entries())

    def search_entries(self, text):
        """What the left column shows while there is something in the box.

        A name that *starts* with what was typed comes before one that
        merely contains it, which is the order somebody typing three letters
        of a program's name is expecting.
        """
        needle = (text or '').strip().lower()
        if not needle:
            return []
        if self._search_index is None:
            self._search_index = self._build_search_index()
        starts, contains = [], []
        for entry in self._search_index:
            label = (entry.label or '').lower()
            if label.startswith(needle):
                starts.append(entry)
            elif needle in label:
                contains.append(entry)
        return starts + contains

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
        self.left_tree.set_entries(self._top_level_entries())
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
        return entries

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------
    def _activate_entry(self, entry):
        if entry is None:
            return
        if entry.kind == 'separator':
            return
        if entry.kind == 'im_builtin':
            self._open_builtin_im(entry.payload)
            self.Hide()
            return
        if entry.kind == 'im_module':
            self._open_im_module(entry.payload)
            self.Hide()
            return
        if entry.kind == 'uwp':
            win_shell.launch_app_id(entry.payload)
            self.Hide()
            return
        if entry.kind == 'macro':
            self._run_macro(entry.payload)
            self.Hide()
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

    def _open_im_module(self, info):
        """Open a Titan IM module the way its own manager does."""
        try:
            from src.network.im_module_manager import im_module_manager
            im_module_manager.open_module(
                info.get('id') or info.get('name'), self.parent)
        except Exception as error:
            print(f"[TitanShell] could not open the IM module: {error}")

    def _run_macro(self, macro):
        """Run a macro through the macro manager, shortcuts and all."""
        module = self._macro_component()
        if module is None:
            print("[TitanShell] the macro manager is not loaded")
            return
        try:
            module.run_macro(macro, self.parent)
        except Exception as error:
            print(f"[TitanShell] could not run the macro: {error}")

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
            # The shell's own browser while the shell is up - a folder must
            # open into a window Titan can make readable.  With the shell
            # off, Titan's file manager application, as before.
            self.Hide()
            if shell is not None:
                shell.open_explorer()
            else:
                self._open_titan_app('tfm')
        elif action == 'internet':
            self._open_titan_app('tweb')
            self.Hide()
        elif action == 'my_documents' and shell is not None:
            self.Hide()
            shell.open_explorer(os.path.expanduser('~/Documents'))
        elif action in ('my_pictures', 'my_music'):
            folder = os.path.expanduser(
                '~/Pictures' if action == 'my_pictures' else '~/Music')
            self.Hide()
            if shell is not None:
                shell.open_explorer(folder)
            else:
                win_shell.open_path(folder)
        elif action == 'my_computer':
            self.Hide()
            if shell is not None:
                shell.open_explorer()
            else:
                win_shell.open_path('shell:MyComputerFolder' if IS_WINDOWS
                                    else os.path.expanduser('~'))
        elif action == 'taskbar_properties':
            self.Hide()
            if shell is not None and shell.taskbar is not None:
                shell.taskbar.show_properties()
            else:
                from src.shell.taskbar_properties import show_taskbar_properties
                show_taskbar_properties(self.parent)
        elif action == 'display_properties':
            win_shell.open_path('ms-settings:personalization-background'
                                if IS_WINDOWS else '')
            self.Hide()
        elif action == 'windows_settings':
            win_shell.open_path('ms-settings:' if IS_WINDOWS else '')
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

    def _on_char_hook(self, event):
        key = event.GetKeyCode()
        focused = wx.Window.FindFocus()

        if key == wx.WXK_F4 and event.AltDown():
            # The menu is part of the shell, so Alt+F4 in it means what it
            # means anywhere else in the shell: the Shut Down dialog.
            from src.shell.shutdown_dialog import shell_alt_f4
            self.Hide()
            shell_alt_f4(self.shell.parent if self.shell else None)
            return
        if key == wx.WXK_TAB:
            self._move_focus(-1 if event.ShiftDown() else 1)
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
        wx.CallAfter(lambda: self.left_column().SetFocus())
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
            wx.CallAfter(lambda: self.left_column().SetFocus())

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
