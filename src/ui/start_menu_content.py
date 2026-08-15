# -*- coding: utf-8 -*-
"""
What is *in* the Start menu, with no opinion about how it looks.

Titan has two Start menus - the XP one the shell puts up
(`src/shell/start_menu.py`) and the classic Windows 95 one
(`src/ui/classic_start_menu.py`) - and they are two faces, not two menus.
Everything they list is the same: the Titan applications and games, the
Titan IM services and modules, the user's macros, the settings, the
packaged Windows apps and the whole Windows Start Menu.  That belongs in
one place, or the classic menu is forever the one missing whatever was
added to the other last.

So this module holds the *contents*: `MenuEntry` (a label, what kind of
thing it is, and what to do with it), the branches that fill themselves
when they are opened, the search index over all of it, and what activating
an entry does.  `MenuTree` is here for the same reason - both menus show
their branches in one, and a branch must not behave differently depending
on which face is up.  A face mixes `StartMenuContent` in and decides only
how to draw it: a tree with a banner down its side, or two columns with a
search box.

`self.shell` is the running Titan shell when there is one and `None`
otherwise, which is the only thing that changes here between the two: with
the shell up a folder opens in the shell's own accessible browser, and
without it in Titan's file manager application.
"""

import os
import threading

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import win_shell
from src.shell.a11y import name_control
from src.titan_core.translation import _


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
        # Frozen while it is rebuilt: a tree control lays itself out and
        # works out its scrollbars on every `AppendItem`, which for the ten
        # items of a top level measured 20 ms - on the open of a menu, where
        # every millisecond is one the user is waiting with the Start button
        # already pressed.
        # Nothing in here is the user arriving anywhere: emptying the tree
        # moves the selection off each item in turn, and putting the first
        # item back selects it - so a menu that cued on every selection
        # change clicked TEN TIMES on every open.  The cue belongs to moving
        # through a menu, not to the menu being built.
        self._rebuilding = True
        self.Freeze()
        try:
            self.DeleteChildren(self._root)
            self.entries = list(entries)
            for entry in self.entries:
                self._add(self._root, entry)
            first = self.GetFirstChild(self._root)[0]
            if first and first.IsOk():
                self.SelectItem(first)
        finally:
            self.Thaw()
            self._rebuilding = False

    def rebuilding(self):
        """True while `set_entries` is putting the tree back together."""
        return bool(getattr(self, '_rebuilding', False))

    @staticmethod
    def signature(entries):
        """What identifies a set of entries, for "has this changed?"."""
        return [(entry.label, entry.kind,
                 entry.payload if isinstance(entry.payload, str) else None)
                for entry in (entries or [])]

    def matches(self, entries):
        """True when the tree already shows exactly these entries."""
        current = getattr(self, 'entries', None)
        if not current or len(current) != len(entries or []):
            return False
        return self.signature(current) == self.signature(entries)

    def reset_branches(self):
        """Put the branches back to unopened, keeping the tree itself.

        A Start menu rebuilds itself on every open so that an application, a
        macro or a module installed since the last one is on it without
        Titan being restarted - but the TOP level of the menu never changes,
        and rebuilding it measured 14 ms of the 55 an open cost.  What has
        to be thrown away is what the BRANCHES read, and only a branch that
        was actually opened has read anything, so that is all this touches.
        """
        self._rebuilding = True
        self.Freeze()
        try:
            item, cookie = self.GetFirstChild(self._root)
            while item.IsOk():
                entry = self.GetItemData(item)
                if entry is not None and entry.kind == 'folder' \
                        and entry.filled:
                    if self.IsExpanded(item):
                        self.Collapse(item)
                    self.DeleteChildren(item)
                    # A branch has to look like one again.
                    self.AppendItem(item, '')
                    entry.filled = False
                item, cookie = self.GetNextChild(self._root, cookie)
            first = self.GetFirstChild(self._root)[0]
            if first and first.IsOk():
                self.SelectItem(first)
        finally:
            self.Thaw()
            self._rebuilding = False
        return True

    def find_branch(self, payload, parent=None):
        """The item for a branch, by what it is a branch OF."""
        parent = self._root if parent is None else parent
        item, cookie = self.GetFirstChild(parent)
        while item.IsOk():
            entry = self.GetItemData(item)
            if entry is not None and entry.kind == 'folder' \
                    and entry.payload == payload:
                return item
            found = self.find_branch(payload, item)
            if found is not None:
                return found
            item, cookie = self.GetNextChild(parent, cookie)
        return None

    def refill(self, payload, children):
        """Put a branch's children back - for one that filled itself late.

        The Windows apps branch can be opened before Windows has answered
        what is installed; when the answer comes, the branch is filled in
        where it stands rather than the user being asked to close the menu
        and open it again.
        """
        item = self.find_branch(payload)
        if item is None:
            return False
        entry = self.GetItemData(item)
        self._rebuilding = True
        self.Freeze()
        try:
            self.DeleteChildren(item)
            for child in (children or []):
                self._add(item, child)
        finally:
            self.Thaw()
            self._rebuilding = False
        if entry is not None:
            entry.filled = True
        return True

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

class StartMenuContent:
    """The contents of a Start menu, whatever draws it.

    Mixed into a `wx.Frame` (see `ClassicStartMenu`), so everything here may
    call `self.Hide()`, and into whichever face is in use, so it may call
    the things a face supplies - `_top_level_entries`, `_places_entries` and
    `execute_action`.
    """

    #: The running shell, when the menu is part of one.
    shell = None
    #: Everything the menu can open, flattened.  Built on demand and thrown
    #: away when the menu is next opened, so a program installed in between
    #: is found without Titan being restarted.
    _search_index = None
    _prefetching = False
    #: The Windows Start Menu as it was read for THIS open of the menu.  Both
    #: the All Programs branch and the search index want it, and walking two
    #: folder trees twice for one open is a walk too many.
    _programs_structure = None

    def windows_programs(self):
        """The Windows Start Menu, read once per open of the menu."""
        if self._programs_structure is None:
            try:
                self._programs_structure =                     self.load_windows_programs_with_folders() or {}
            except Exception as error:
                print(f"[TitanShell] could not read the Start Menu: {error}")
                self._programs_structure = {}
        return self._programs_structure

    def addon_entries(self):
        """What the shell add-ons put on the Start menu.

        Both menus ask for these, because both are built from this file:
        an add-on writes `start_menu_items` once and it is on the XP menu
        and on the classic one, in the left column and in the search box.

        An entry is the usual `{'id', 'label', 'action'}`; one that carries
        `children` (a list of the same, or a callable returning one) becomes
        a branch instead, which is how an add-on with six commands adds one
        line to the menu rather than six.
        """
        try:
            from src.shell import addons as shell_addons
        except Exception:
            return []
        entries = []
        for item in shell_addons.collect('start_menu', 'start_menu_items',
                                         self):
            label = str(item.get('label', ''))
            if not label:
                continue
            if item.get('children') is not None:
                entries.append(MenuEntry(label, 'folder', ('__addon__', item),
                                         description=item.get('addon_name',
                                                              '')))
            else:
                entries.append(MenuEntry(label, 'addon', item,
                                         description=item.get('addon_name',
                                                              '')))
        return entries

    @staticmethod
    def _addon_children(item):
        """A contributed branch's children, asked for when it is opened."""
        children = item.get('children')
        if callable(children):
            try:
                children = children()
            except Exception as error:
                print(f"[ShellAddons] {item.get('addon')} children failed: "
                      f"{error}")
                children = []
        entries = []
        for child in children or []:
            if not isinstance(child, dict):
                continue
            label = str(child.get('label', ''))
            if not label or not callable(child.get('action')):
                continue
            child = dict(child)
            child.setdefault('addon', item.get('addon'))
            child.setdefault('addon_name', item.get('addon_name'))
            entries.append(MenuEntry(label, 'addon', child,
                                     description=item.get('label', '')))
        return entries

    def _children_of(self, entry):
        """What is under a branch, worked out the first time it is opened."""
        payload = entry.payload
        if isinstance(payload, tuple) and payload[:1] == ('__addon__',):
            return self._addon_children(payload[1])
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
        if payload == '__programs__':
            return self._programs_entries()
        if payload == '__documents__':
            return self._document_entries()
        if payload == '__find__':
            return self._find_entries()
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
        """The packaged Windows apps - the Store ones, and ONLY those.

        `shell:AppsFolder` is the list the Windows Start menu is made of,
        and it holds two quite different things: packaged (UWP / Store)
        applications, which exist nowhere else - there is no shortcut on
        disk to find, only an Application User Model ID to launch - and
        every desktop program's shortcut, `steam://` URL and auto-generated
        entry besides.  Measured here: 309 entries, 60 of them packaged.

        Listing all 309 made this branch a second, worse copy of All
        Programs with the Store apps buried in it, so only the packaged ones
        are here (`win_shell.is_packaged_app`); everything else is where it
        already was, under Programs / All Programs.

        Reading the folder is about a second, so the branch never waits for
        it: whatever is known is shown at once, and if nothing is known yet
        the branch says so and fills itself in when the read comes back.
        """
        apps = win_shell.installed_apps(packaged_only=True, wait=False)
        if apps:
            return [MenuEntry(name, 'uwp', app_id,
                              description=_("Windows apps"))
                    for name, app_id in apps]
        if IS_WINDOWS:
            win_shell.read_installed_apps_async(then=self._apps_arrived)
            return [MenuEntry(_("Reading..."), 'separator')]
        return [MenuEntry(_("No applications"), 'separator')]

    def _apps_arrived(self, _apps):
        """The Apps folder has been read; put the branch right.

        Called on the reader's thread, so nothing here touches wx until it
        is back on the GUI one.
        """
        wx.CallAfter(self._refill_windows_apps)

    def _refill_windows_apps(self):
        """Fill the Windows apps branch again, if it is still on the screen."""
        tree = getattr(self, 'menu_tree', None) or getattr(self, 'left_tree',
                                                           None)
        if tree is None:
            return False
        try:
            if not tree:
                return False
            # The search looks inside this branch too, so what it flattened
            # while the list was still being read is out of date.
            self._search_index = None
            return tree.refill('__windows_apps__', self._windows_app_entries())
        except RuntimeError:
            return False

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
            MenuEntry(_("Printers and Faxes"), 'action', 'printers',
                      description=_("Settings")),
            MenuEntry(_("Network Connections"), 'action',
                      'network_connections', description=_("Settings")),
            MenuEntry(_("Display properties"), 'action', 'display_properties',
                      description=_("Settings")),
            MenuEntry(_("Windows settings"), 'action', 'windows_settings',
                      description=_("Settings")),
        ]
        return entries

    def _programs_entries(self):
        """Programs, as the classic menu has it.

        ReactOS' `IDM_PROGRAMS` is `CSIDL_PROGRAMS` and `CSIDL_COMMON_PROGRAMS`
        merged into one submenu, and that is what the bottom of this list is.
        Above it are the groups that belong to Titan rather than to Windows -
        the applications, the games, the Titan IM services and the macros -
        which is exactly where a program group went on a Windows 95 machine:
        into Programs, not beside it.
        """
        entries = [
            MenuEntry(_("Titan applications"), 'folder', '__apps__',
                      description=_("Programs")),
            MenuEntry(_("Titan games"), 'folder', '__games__',
                      description=_("Programs")),
            MenuEntry(_("Titan IM"), 'folder', '__im__',
                      description=_("Programs")),
            MenuEntry(_("Macros"), 'folder', '__macros__',
                      description=_("Programs")),
            MenuEntry(_("Windows apps"), 'folder', '__windows_apps__',
                      description=_("Programs")),
        ]
        entries.extend(self._all_programs_entries())
        return entries

    def _document_entries(self):
        """Documents: the user's own folders, then what they opened last.

        `IDM_DOCUMENTS` is `CSIDL_RECENT` alone, but a menu that offers no
        way to reach My Documents itself is a menu the user then has to
        leave, so the three folders come first and the recent files after
        them.
        """
        entries = [
            MenuEntry(_("My Documents"), 'action', 'my_documents',
                      description=_("Documents")),
            MenuEntry(_("My Pictures"), 'action', 'my_pictures',
                      description=_("Documents")),
            MenuEntry(_("My Music"), 'action', 'my_music',
                      description=_("Documents")),
            MenuEntry(_("My Computer"), 'action', 'my_computer',
                      description=_("Documents")),
        ]
        recent = self._recent_documents()
        if recent:
            entries.append(MenuEntry(_("Recent documents"), 'separator'))
            entries.extend(recent)
        return entries

    #: How many of the recent documents the menu shows.  Windows' own list
    #: is fifteen, and a menu longer than the screen helps nobody.
    RECENT_LIMIT = 15

    def _recent_documents(self):
        """What Windows itself remembers the user opening.

        The Recent folder is full of shortcuts, so each entry is run the
        way any other shortcut in the menu is - `run_program` with a
        `shortcut`, which resolves and opens whatever it points at.
        """
        if not IS_WINDOWS:
            return []
        folder = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft',
                              'Windows', 'Recent')
        if not os.path.isdir(folder):
            return []
        try:
            files = [os.path.join(folder, name) for name in os.listdir(folder)
                     if name.lower().endswith('.lnk')]
            files.sort(key=os.path.getmtime, reverse=True)
        except Exception as error:
            print(f"[TitanShell] could not read the recent documents: {error}")
            return []
        entries = []
        for path in files[:self.RECENT_LIMIT]:
            name = os.path.splitext(os.path.basename(path))[0]
            entries.append(MenuEntry(
                name, 'program', {'name': name, 'path': path,
                                  'type': 'shortcut'},
                description=_("Recent documents")))
        return entries

    def _find_entries(self):
        """Search, with the three things Windows 95 could look for."""
        return [
            MenuEntry(_("Files or Folders..."), 'action', 'find_files',
                      description=_("Search")),
            MenuEntry(_("Computer..."), 'action', 'find_computer',
                      description=_("Search")),
            MenuEntry(_("On the Internet..."), 'action', 'find_internet',
                      description=_("Search")),
        ]

    def _all_programs_entries(self):
        """The Windows Start Menu, folder by folder.

        Titan's own applications and games are branches of their own at the
        top of the column, so they are not repeated in here.
        """
        entries = []
        structure = self.windows_programs()
        loose = []
        for folder, programs in structure.items():
            if not folder:
                # A shortcut lying loose in Programs itself: it has no group
                # to go under, and a branch with no name is a branch a
                # screen reader reads as nothing.  Windows 95 shows these
                # at the bottom of Programs, and so does this.
                loose = [MenuEntry(program.get('name', ''), 'program',
                                   program, description=_("Programs"))
                         for program in programs]
                continue
            entries.append(MenuEntry(folder, 'folder', programs))
        entries.extend(loose)
        return entries

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def prefetch(self, build_index=True):
        """Get the slow lists ready before anybody asks for them.

        Reading `shell:AppsFolder` is over a second and walking the Windows
        Start Menu is a few hundred milliseconds - on the first keystroke in
        the search box that is a keystroke that appears to hang, and on
        opening the Windows apps branch it is a branch that appears to
        hang.  So it is done on a thread the moment the menu opens, and
        whichever asks for it uses whatever is ready by then.

        `build_index` is what the classic menu turns off: it has no search
        box (neither Windows 95 nor ReactOS' classic menu has one), so
        flattening everything it could open would be a walk of the Start
        Menu that nothing ever reads.
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
                index = self._build_search_index() if build_index else None
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
        for folder, programs in self.windows_programs().items():
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
                + self._settings_entries() + self._windows_app_entries()
                + self.addon_entries())

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
        if entry.kind == 'addon':
            # The menu goes away first: an add-on's command usually opens a
            # window, and a Start menu still standing in front of it is a
            # Start menu the user has to dismiss before they can use what
            # they just asked for.
            self.Hide()
            item = entry.payload or {}
            try:
                item['action']()
            except Exception as error:
                print(f"[ShellAddons] {item.get('addon')}."
                      f"{item.get('id')} failed: {error}")
                import traceback
                traceback.print_exc()
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

    def _run_action(self, action):
        """Everything an entry can ask for that is not a program to run.

        With the shell up, a folder opens in the shell's own browser,
        which is the one Titan can make readable; with the shell off it
        opens in Titan's file manager application, as it always did.
        Anything not named here is the classic menu's own action
        (`execute_action`), which is where the oldest of them live.
        """
        shell = self.shell
        if action == 'titan_window':
            if shell:
                shell.show_titan_window()
            elif self.parent is not None:
                # No shell: the menu was opened from Titan itself, and the
                # window it came from is the one to go back to.
                try:
                    self.parent.Show()
                    self.parent.Raise()
                except Exception as error:
                    print(f"[TitanShell] could not raise Titan: {error}")
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
        elif action == 'printers':
            win_shell.open_path('shell:PrintersFolder' if IS_WINDOWS else '')
            self.Hide()
        elif action == 'network_connections':
            win_shell.open_path('shell:ConnectionsFolder' if IS_WINDOWS else '')
            self.Hide()
        elif action == 'lock':
            self.Hide()
            win_shell.lock_workstation()
        elif action == 'logoff':
            # Asked before it is done: logging off closes every program the
            # user has open, and a menu entry two rows from Shut Down is
            # easy to press by mistake.
            dialog = wx.MessageDialog(
                self, _("Do you want to log off?"), _("Log Off"),
                wx.YES_NO | wx.ICON_QUESTION)
            answer = dialog.ShowModal()
            dialog.Destroy()
            self.Hide()
            if answer == wx.ID_YES:
                win_shell.exit_windows('logoff')
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
