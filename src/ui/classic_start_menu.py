# -*- coding: utf-8 -*-
"""
The classic Start menu: Windows 95's, as ReactOS still builds it.

ReactOS' Explorer does not draw this menu in one place - `CStartMenu`
(`base/shell/rshell/CStartMenu.cpp`) binds the shell folders and
`IDM_STARTMENU` (`base/shell/explorer/lang/en-US.rc`) supplies the rest,
which together are:

    Programs        >   CSIDL_PROGRAMS + CSIDL_COMMON_PROGRAMS
    Favorites       >   CSIDL_FAVORITES
    Documents       >   CSIDL_RECENT
    Settings        >   Control Panel, Printers and Faxes,
                        Network Connections, Taskbar and Start Menu
    Search              (IDM_SEARCH)
    Help and Support    (IDM_HELPANDSUPPORT)
    Run...              (IDM_RUN)
    -----------------------------------------
    Log Off "<user>"... (IDM_LOGOFF)
    Shut Down...        (IDM_SHUTDOWN)

That is the menu built here, entry for entry and in that order, with the
grey 3D frame and the banner down its left-hand side.  What is missing from
it is missing on purpose: `IDM_SYNCHRONIZE`, `IDM_DISCONNECT` and
`IDM_UNDOCKCOMPUTER` are for a machine with a briefcase, a dial-up
connection and a docking station, and a control is here only if it does
something.

**It lists exactly what the XP menu lists.**  The two are faces, not two
menus: the Titan applications and games, the Titan IM services and modules,
the user's macros, the settings, the packaged Windows apps and the whole
Windows Start Menu all come from `src/ui/start_menu_content.py`, which
`src/shell/start_menu.py` reads from as well.  Choosing the classic look in
Settings -> Titan shell changes how the menu is drawn and nothing about
what is on it.

**A branch opens where it stands.**  Windows 95 cascaded flyouts sideways,
which is a menu a keyboard cannot follow and a screen reader cannot
describe; the same `MenuTree` the XP menu uses is here instead, so the
arrows open and close a branch, the reader says "collapsed" or "expanded"
from the control's own state, and first-letter jumping comes from the
control.  Branches fill themselves the first time they are opened, because
reading the Windows Start Menu, every add-on and every macro up front is
most of a second the user would wait for a menu.
"""

import os
import subprocess
import time

import wx

from src.titan_core.sound import play_sound, initialize_sound
from src.controller.controller_vibrations import (
    vibrate_cursor_move, vibrate_menu_open, vibrate_menu_close, vibrate_selection,
    vibrate_focus_change, vibrate_error, vibrate_notification
)
from src.settings.settings import get_setting
from src.titan_core.translation import set_language
from src.titan_core.skin_manager import get_current_skin, apply_skin_to_window
from src.shell import keyboard_handover as handover
from src.ui.start_menu_content import MenuEntry, MenuTree, StartMenuContent

from src.platform_utils import IS_WINDOWS, IS_LINUX, IS_MACOS, open_file_manager

# Windows-specific imports
WIN32_AVAILABLE = False
WINREG_AVAILABLE = False

if IS_WINDOWS:
    try:
        import winreg
        WINREG_AVAILABLE = True
    except ImportError:
        print("Warning: winreg not available")

    try:
        import win32gui
        import win32con
        import win32api
        WIN32_AVAILABLE = True
    except ImportError:
        print("Warning: win32gui not available, using fallback menu")

# Initialize translation system
_ = set_language(get_setting('language', 'pl'))


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = _new_message_dialog(parent, message, caption, style)
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _new_text_entry_dialog(*args, **kwargs):
    dlg = wx.TextEntryDialog(*args, **kwargs)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    return dlg


def _new_message_dialog(*args, **kwargs):
    dlg = wx.MessageDialog(*args, **kwargs)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    return dlg


def _apply_skin_to_tree(window):
    """Apply Titan skin recursively to a window and all descendants."""
    try:
        apply_skin_to_window(window)
    except Exception:
        return

    for child in window.GetChildren():
        _apply_skin_to_tree(child)


class ClassicMenuItem:
    """One line of the menu, as the first version of this file had it.

    The menu is built out of `MenuEntry` now, so that both Start menus list
    the same things; this is kept because a skin or an add-on may still be
    holding one.
    """

    def __init__(self, name, action=None, submenu=None, icon=None, shortcut=None):
        self.name = name
        self.action = action
        self.submenu = submenu
        self.icon = icon
        self.shortcut = shortcut
        self.is_separator = name == "---"


class MenuBanner(wx.Window):
    """The strip down the left-hand side, with the name written up it.

    Windows 95 drew a bitmap here and so does ReactOS; it is decoration and
    nothing else, so it takes no focus, has no accessible name and says
    nothing.  The text is the skin's (`logo_text`), rotated a quarter turn
    the way the original reads from the bottom up.
    """

    WIDTH = 26

    def __init__(self, parent):
        super().__init__(parent, size=(self.WIDTH, -1), style=wx.NO_BORDER)
        self.text = 'Titan'
        self.text_colour = wx.Colour(255, 255, 255)
        self.background = wx.Colour(0, 0, 128)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda event: self.Refresh())

    def configure(self, text, text_colour, background):
        self.text = text or 'Titan'
        self.text_colour = text_colour
        self.background = background
        self.Refresh()

    def _on_paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        width, height = self.GetSize()
        if width <= 0 or height <= 0:
            return
        # The original fades from black at the top to the logo colour at the
        # bottom, which is what makes it a banner rather than a blue bar.
        dc.GradientFillLinear(wx.Rect(0, 0, width, height),
                              wx.Colour(0, 0, 0), self.background, wx.SOUTH)
        dc.SetTextForeground(self.text_colour)
        dc.SetFont(wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL,
                           wx.FONTWEIGHT_BOLD, faceName='MS Sans Serif'))
        text_width, text_height = dc.GetTextExtent(self.text)
        x = max(0, (width - text_height) // 2)
        dc.DrawRotatedText(self.text, x, max(text_width + 4, height - 8), 90)

    def AcceptsFocus(self):  # noqa: N802 - wx naming
        return False

    def AcceptsFocusFromKeyboard(self):  # noqa: N802 - wx naming
        return False


class ClassicStartMenu(StartMenuContent, wx.Frame):
    """The Windows 95 Start menu, with everything Titan can start on it."""

    # How long after opening the menu ignores focus loss, so a menu opened
    # from a global shortcut is not hidden before Windows gives it focus.
    FOCUS_GRACE_SECONDS = 0.5

    #: How long to wait for the activation that hands the keyboard over
    #: before doing it anyway - there is none when the menu was already the
    #: active window, and Windows can refuse the foreground outright.
    FOCUS_FALLBACK_MS = 300

    MENU_WIDTH = 260
    MENU_HEIGHT = 420

    def __init__(self, parent, shell=None):
        # `XPStartMenu` sets its own shell before calling up, so this must
        # not put None back over it.
        if shell is not None:
            self.shell = shell
        try:
            # It is the Start menu of the machine, so that is what it is
            # called - "Titan Menu" named the program that draws it, which
            # is not what a user (or a screen reader) is looking for.
            super().__init__(parent, title=_("Start menu"),
                             style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP)
        except Exception as e:
            print(f"Warning: ClassicStartMenu init error: {e}")
            # Fallback to simpler style
            super().__init__(parent, title=_("Start menu"))

        self.parent = parent
        # Disable TTS in Start Menu to avoid conflicts with screen readers
        self.speaker = None

        self.is_windows = IS_WINDOWS
        self.menu_items = []
        self._shown_at = 0.0
        # Set while the menu is opening: the keyboard belongs to the
        # opening sequence until the activation has handed it over.
        self._focus_pending = False
        # Set only while Titan is taking the menu down for good, so a close
        # from anywhere else can be refused (see `on_close`).
        self._allow_close = False

        # Inicjalizacja dźwięku
        initialize_sound()

        self.init_ui()
        self.build_menu_structure()
        self.position_menu()

        # Zastosuj ustawienia skórki
        self.apply_skin_settings()

        # Bind events
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_CLOSE, self.on_close)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def init_ui(self):
        """The grey 3D frame, the banner, and the menu itself."""
        main_panel = wx.Panel(self)
        main_panel.SetBackgroundColour(wx.Colour(192, 192, 192))
        self.main_panel = main_panel

        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.banner = MenuBanner(main_panel)

        menu_panel = wx.Panel(main_panel)
        menu_panel.SetBackgroundColour(wx.Colour(192, 192, 192))
        self.menu_panel = menu_panel
        menu_sizer = wx.BoxSizer(wx.VERTICAL)

        # The same control the XP menu's left column is, so a branch behaves
        # identically in both and there is one implementation of the tree.
        self.menu_tree = MenuTree(
            menu_panel, self._activate_entry, self._children_of,
            wx.Colour(255, 255, 255), wx.Colour(0, 0, 0), _("Menu"))
        self.menu_tree.SetFont(wx.Font(8, wx.FONTFAMILY_SWISS,
                                       wx.FONTSTYLE_NORMAL,
                                       wx.FONTWEIGHT_NORMAL,
                                       faceName="MS Sans Serif"))
        self.menu_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_select)
        self.menu_tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.on_tree_expanding)
        self.menu_tree.Bind(wx.EVT_TREE_ITEM_COLLAPSING, self.on_tree_collapsing)

        menu_sizer.Add(self.menu_tree, 1, wx.ALL | wx.EXPAND, 3)
        menu_panel.SetSizer(menu_sizer)

        main_sizer.Add(self.banner, 0, wx.EXPAND)
        main_sizer.Add(menu_panel, 1, wx.EXPAND)

        main_panel.SetSizer(main_sizer)

        self.SetSize((self.MENU_WIDTH, self.MENU_HEIGHT))

    # ------------------------------------------------------------------
    # Contents
    # ------------------------------------------------------------------
    def build_menu_structure(self):
        """`IDM_STARTMENU`, in its own order.

        Rebuilt only when the top of the menu has actually changed, which it
        practically never does - what changes is what the branches hold, and
        `reset_branches` is what makes them read it again.  Putting ten
        items into a tree control costs 14 ms of an open the user is waiting
        through with the Start button already pressed.
        """
        self._search_index = None
        self._programs_structure = None
        entries = self._top_level_entries()
        if self.menu_tree.matches(entries):
            self.menu_tree.reset_branches()
            return
        self.menu_items = entries
        self.menu_tree.set_entries(self.menu_items)

    def _top_level_entries(self):
        try:
            user = os.environ.get('USERNAME') or os.environ.get('USER') or ''
        except Exception:
            user = ''
        log_off = (_("Log Off \"{user}\"...").format(user=user) if user
                   else _("Log Off..."))
        return [
            # Titan itself is what this machine's Start menu starts with:
            # the window every application, game and service is opened from.
            MenuEntry(_("Titan"), 'action', 'titan_window'),
            MenuEntry(_("Programs"), 'folder', '__programs__'),
            MenuEntry(_("Documents"), 'folder', '__documents__'),
            MenuEntry(_("Settings"), 'folder', '__settings__'),
            MenuEntry(_("Search"), 'folder', '__find__'),
            MenuEntry(_("Help and Support"), 'action', 'help'),
            MenuEntry(_("Run..."), 'action', 'run'),
        ] + self.addon_entries() + [
            # Thirteen dashes is what a screen reader reads as thirteen
            # dashes; the word is what it says for a real menu separator.
            MenuEntry(_("Separator"), 'separator'),
            MenuEntry(log_off, 'action', 'logoff'),
            MenuEntry(_("Shut Down..."), 'action', 'shutdown'),
        ]

    def _places_entries(self):
        """What the search box looks through besides the branches.

        The classic menu has no right-hand column, but these are things it
        can open all the same - they live under Documents and Search - so
        the search index is told about them.
        """
        return self._document_entries() + self._find_entries()

    # ------------------------------------------------------------------
    # The tree
    # ------------------------------------------------------------------
    def on_tree_select(self, event):
        """A cue on the way past, the same one the rest of Titan gives.

        Not while the tree is being rebuilt: putting the first item back is
        the menu's own doing, and a cue there is a click on every open that
        nobody moved anything to earn.
        """
        if not self.menu_tree.rebuilding():
            play_sound('core/FOCUS.ogg')
            vibrate_cursor_move()
        event.Skip()

    def on_tree_expanding(self, event):
        play_sound('ui/focus_expanded.ogg')
        vibrate_menu_open()
        event.Skip()

    def on_tree_collapsing(self, event):
        play_sound('ui/focus_collabsed.ogg')
        vibrate_menu_close()
        event.Skip()

    def _activate_entry(self, entry):
        """Enter on an entry: the cue first, then whatever it does."""
        if entry is None or entry.kind == 'separator':
            return
        play_sound('core/SELECT.ogg')
        vibrate_selection()
        super()._activate_entry(entry)

    # ------------------------------------------------------------------
    # Running things
    # ------------------------------------------------------------------
    def run_titan_app(self, app):
        """Uruchamianie aplikacji Titan"""
        try:
            from src.titan_core.app_manager import open_application

            # Use open_application with app_info object directly like GUI does
            open_application(app)
            self.Hide()
        except Exception as e:
            print(f"Error running Titan app: {e}")
            import traceback
            traceback.print_exc()

    def run_titan_game(self, game):
        """Uruchamianie gry Titan.

        The game manager's own record of the game is what `open_game`
        wants, and the menu already has it.  This used to look the game up
        again through a bare `import game_manager`, which is not where the
        module lives - so every game in the menu raised ImportError and not
        one of them ever started.
        """
        try:
            from src.titan_core.game_manager import get_games, open_game

            game_info = game if isinstance(game, dict) else None
            if game_info is not None and 'openfile' not in game_info \
                    and 'path' not in game_info:
                # Only a name to go on: find the manager's own record of it.
                for candidate in (get_games() or []):
                    if candidate.get('name') == game_info.get('name'):
                        game_info = candidate
                        break

            if game_info:
                open_game(game_info)
                self.Hide()
            else:
                print(f"Game not found: {game}")
        except Exception as e:
            print(f"Error running Titan game: {e}")
            import traceback
            traceback.print_exc()

    def run_program(self, program):
        """Uruchomienie programu"""
        try:
            if program['type'] == 'shortcut' and self.is_windows:
                # Use platform file opener for shortcuts
                open_file_manager(program['path'])
            elif program['type'] == 'exe':
                # Direct executable
                subprocess.run([program['path']], shell=True)
            else:
                # Fallback - try to open with system default
                open_file_manager(program['path'])

            self.Hide()

        except Exception as e:
            print(f"Error running program {program['name']}: {e}")

    def execute_action(self, action):
        """The actions that are the classic menu's own.

        Everything else an entry can ask for is
        `StartMenuContent._run_action`, which is where the two menus share
        their answers; this is what it falls through to.
        """
        try:
            if action == "run":
                self.show_run_dialog()
            elif action == "find":
                self.show_find_dialog()
            elif action == "help":
                self.show_help()
            elif action == "titan_apps":
                if self.parent is not None:
                    self.parent.show_app_list()
                self.Hide()
            elif action == "titan_games":
                if self.parent is not None:
                    self.parent.show_game_list()
                self.Hide()
            elif action == "control_panel":
                if self.is_windows:
                    subprocess.run(['control'], shell=True)
                self.Hide()
            elif action == "titan_settings":
                self.show_titan_settings()
            elif action == "my_documents":
                self.open_documents_folder()
            elif action == "shutdown":
                self.show_shutdown_dialog()
            elif action == "find_files":
                self.show_find_dialog()
            elif action == "find_computer":
                if self.is_windows:
                    # Open Network Places
                    subprocess.run(['explorer', 'shell:NetworkPlacesFolder'],
                                   shell=True)
                self.Hide()
            elif action == "find_internet":
                # The user's own browser - the same tWeb every other
                # "open a page" in Titan goes through.
                if not self._open_titan_app('tweb'):
                    from src.shell import win_shell
                    win_shell.open_path('https://www.google.com')
                self.Hide()
            else:
                print(f"DEBUG: no such start menu action: {action}")

        except Exception as e:
            print(f"Error executing action {action}: {e}")

    def show_titan_settings(self):
        """Titan's settings: whatever the menu bar opens.

        Which window that is is the user's choice (Settings -> Interface ->
        Settings interface), so this asks the one place that knows rather
        than building a `SettingsFrame` - two settings windows being two
        answers to the same question.
        """
        try:
            from src.settings.interfaces import open_settings
            open_settings(self.parent)
            self.Hide()
        except Exception as e:
            print(f"Error opening Titan settings: {e}")

    def open_documents_folder(self):
        """My Documents, in Titan's file manager where there is one."""
        documents_path = os.path.expanduser("~/Documents")
        try:
            from src.titan_core.app_manager import (find_application_by_shortname,
                                                    open_application)
            tfm_app = find_application_by_shortname("tfm")
            if tfm_app:
                open_application(tfm_app, documents_path)
            else:
                open_file_manager(documents_path)
            self.Hide()
        except Exception as e:
            print(f"Error opening TFM: {e}")
            # Ultimate fallback: open with system file manager
            open_file_manager(documents_path)
            self.Hide()

    # ------------------------------------------------------------------
    # The Windows Start Menu on disk
    # ------------------------------------------------------------------
    def get_localized_folder_name(self, folder_path):
        """Pobierz zlokalizowaną nazwę folderu z Windows"""
        try:
            folder_name = os.path.basename(folder_path)

            # Mapowanie specjalnych folderów na ich zlokalizowane nazwy
            special_folders = {
                'Accessories': self.get_system_folder_name('Accessories'),
                'Administrative Tools': self.get_system_folder_name('Administrative Tools'),
                'Games': self.get_system_folder_name('Games'),
                'Maintenance': self.get_system_folder_name('Maintenance'),
                'System Tools': self.get_system_folder_name('System Tools'),
                'Startup': self.get_system_folder_name('Startup'),
            }

            return special_folders.get(folder_name, folder_name)

        except Exception as e:
            print(f"Error getting localized folder name: {e}")
            return os.path.basename(folder_path)

    def get_system_folder_name(self, english_name):
        """Pobierz zlokalizowaną nazwę folderu systemowego"""
        try:
            polish_names = {
                'Accessories': 'Akcesoria',
                'Administrative Tools': 'Narzędzia administracyjne',
                'Games': 'Gry',
                'Maintenance': 'Konserwacja',
                'System Tools': 'Narzędzia systemowe',
                'Startup': 'Autostart',
            }

            import locale
            system_lang = locale.getdefaultlocale()[0]

            if system_lang and system_lang.startswith('pl'):
                return polish_names.get(english_name, english_name)

            return english_name

        except Exception:
            return english_name

    def load_windows_programs_with_folders(self):
        """Ładowanie programów Windows z zachowaniem struktury folderów.

        Both Start Menu trees are walked - the machine's and the user's -
        and merged, which is what `CSIDL_COMMON_PROGRAMS` and
        `CSIDL_PROGRAMS` are together.  A shortcut lying loose in Programs
        itself belongs at the top of the menu rather than nowhere, so it
        goes under the empty key and the caller puts it there.
        """
        folder_structure = {}

        try:
            start_menu_paths = [
                os.path.join(os.environ.get('ALLUSERSPROFILE', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
                os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs')
            ]

            for start_path in start_menu_paths:
                if not os.path.exists(start_path):
                    continue

                for root, dirs, files in os.walk(start_path):
                    if root == start_path:
                        folder_name = ''
                    else:
                        relative_path = os.path.relpath(root, start_path)
                        folder_parts = relative_path.split(os.sep)

                        # Użyj tylko pierwszego poziomu folderów (jak Windows XP)
                        if len(folder_parts) > 1:
                            continue

                        folder_name = self.get_localized_folder_name(root)

                    if folder_name not in folder_structure:
                        folder_structure[folder_name] = []

                    for file in files:
                        if file.endswith('.lnk'):
                            full_path = os.path.join(root, file)
                            name = os.path.splitext(file)[0]

                            # Skip uninstall and help shortcuts
                            if any(skip in name.lower() for skip in
                                   ['uninstall', 'uninstaller', 'remove', 'readme', 'help', 'manual']):
                                continue

                            # The shortcut's FILE name is what Windows
                            # shows in its own Start menu, and asking the
                            # link for a "better" one put a line of binary
                            # rubbish on the menu: `GetDescription` was
                            # called with a zero-length buffer, so what came
                            # back was whatever happened to be in memory -
                            # and a description, where a link even has one,
                            # is a sentence about the program rather than
                            # its name.
                            display_name = name

                            # The two trees are merged, and a program
                            # installed for everybody AND for this user has
                            # a shortcut in both - which is why "wsl" and
                            # "Ubuntu" each appeared on the menu twice.
                            if any(existing['name'].lower() == display_name.lower()
                                   for existing in folder_structure[folder_name]):
                                continue

                            folder_structure[folder_name].append({
                                'name': display_name,
                                'path': full_path,
                                'type': 'shortcut'
                            })

            # Sortuj foldery alfabetycznie; luźne skróty na końcu
            sorted_structure = {}
            for folder_name in sorted(key for key in folder_structure if key):
                if folder_structure[folder_name]:  # Tylko niepuste foldery
                    sorted_structure[folder_name] = folder_structure[folder_name]
            if folder_structure.get(''):
                sorted_structure[''] = sorted(folder_structure[''],
                                              key=lambda item: item['name'].lower())

            return sorted_structure

        except Exception as e:
            print(f"Error loading Windows programs with folders: {e}")
            return {}

    #: How much room to give the shell for a string it fills in.  A buffer
    #: it cannot fit the answer into is what made this return rubbish.
    SHELL_STRING_BUFFER = 1024

    def get_shortcut_display_name(self, shortcut_path):
        """The description a shortcut carries, where it has a sensible one.

        This is NOT what the menu labels a program with - Windows labels it
        with the shortcut's file name and so does Titan - because a
        description is usually a sentence about the program.  It is kept
        for anything that does want it, and fixed: both calls asked the
        shell to fill a buffer of length zero, which answers with whatever
        was in memory.
        """
        try:
            if not self.is_windows:
                return None

            # Try using win32com if available
            try:
                import pythoncom
                from win32com.shell import shell

                # Create shortcut object
                shortcut = pythoncom.CoCreateInstance(
                    shell.CLSID_ShellLink,
                    None,
                    pythoncom.CLSCTX_INPROC_SERVER,
                    shell.IID_IShellLink
                )

                # Load the shortcut
                persist_file = shortcut.QueryInterface(pythoncom.IID_IPersistFile)
                persist_file.Load(shortcut_path)

                # Get description (display name)
                description = shortcut.GetDescription(self.SHELL_STRING_BUFFER)
                if description and description.strip()                         and description.isprintable():
                    return description.strip()

                # Fallback: get target executable name.  Not unpacked into
                # `_`, which in this module is the translator.
                target_path = shortcut.GetPath(self.SHELL_STRING_BUFFER)[0]
                if target_path:
                    return os.path.splitext(os.path.basename(target_path))[0]

            except ImportError:
                # win32com not available, use simpler approach
                pass

        except Exception:
            # Any error, fallback to filename
            pass

        return None

    # ------------------------------------------------------------------
    # The dialogs
    # ------------------------------------------------------------------
    def show_run_dialog(self):
        """The Run dialog - Titan's own, not Explorer's.

        This used to run `rundll32 shell32.dll,#61`, which puts up a window
        belonging to Explorer: not skinned like the rest of Titan, nothing
        Titan can announce or drive, and the wrong window entirely on a
        machine whose shell Titan is replacing.  `src/shell/run_dialog.py`
        is the same dialog, control for control, built here.
        """
        try:
            from src.shell.run_dialog import show_run_dialog
        except Exception as error:
            print(f"Error opening run dialog: {error}")
            return
        try:
            self.Hide()
            show_run_dialog(self.GetParent())
        except Exception as e:
            print(f"Error opening run dialog: {e}")

    def show_find_dialog(self):
        """Search: the shell's own browser where there is one.

        `rundll32 shell32.dll,SHFindFiles` puts up Explorer's search - the
        one window Titan cannot make readable, and on a machine whose shell
        Titan has replaced it is the wrong window besides.  So the file
        browser opens instead, which is where somebody looking for a file
        was going.
        """
        try:
            self.Hide()
            if self.shell is not None:
                self.shell.open_explorer()
                return
            if not self._open_titan_app('tfm'):
                open_file_manager(os.path.expanduser('~'))
        except Exception as e:
            print(f"Error opening find dialog: {e}")

    def show_help(self):
        """Help: Titan's own, which is the help written for this program."""
        try:
            from src.ui.help import get_help_instance
            self.Hide()
            get_help_instance(self.parent).show_help()
            return
        except Exception as error:
            print(f"Error opening Titan help: {error}")
        try:
            if self.is_windows:
                subprocess.run(['hh.exe'], shell=True)
                self.Hide()
            else:
                _show_skinned_message(_("Help function"), _("Help"), wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            print(f"Error opening help: {e}")

    def show_shutdown_dialog(self):
        """The Shut Down dialog - the shell's own, with every choice on it.

        This used to be a yes/no box that could only shut the machine down,
        so logging off, restarting, sleeping and hibernating had nowhere to
        be asked for.  `src/shell/shutdown_dialog.py` is the dialog the
        shell actually has (msgina's `IDD_SHUTDOWN`): one list, one
        description of what the chosen entry does, OK and Cancel.
        """
        try:
            play_sound('ui/statusbar.ogg')

            from src.shell.shutdown_dialog import show_shutdown_dialog
            self.Hide()
            show_shutdown_dialog(self.GetParent())

            play_sound('ui/applist.ogg')

        except Exception as e:
            print(f"Error in shutdown dialog: {e}")
            # Dźwięk zamknięcia dialogu nawet przy błędzie
            play_sound('ui/applist.ogg')
            self.Hide()

    def on_shutdown(self, event):
        """Obsługa zamknięcia systemu - ta sama metoda co opcja menu"""
        self.show_shutdown_dialog()

    # ------------------------------------------------------------------
    # Keyboard, focus and closing
    # ------------------------------------------------------------------
    def on_char_hook(self, event):
        """Escape steps back out, and Alt+F4 is the shell's if the shell is up.

        With the Titan shell running this window is part of the system
        interface rather than a program, and Windows answers Alt+F4 there
        with the Shut Down dialog.  On its own - the classic menu opened
        from Titan itself - Alt+F4 closes the menu, which is what it does
        for every other Titan window.
        """
        # A key before the activation has handed the keyboard over: take
        # it now, so the first keystroke never goes nowhere.
        if getattr(self, '_focus_pending', False):
            self._hand_over_focus()

        key = event.GetKeyCode()
        if key == wx.WXK_F4 and event.AltDown():
            try:
                from src.shell.shell_manager import is_shell_running
                from src.shell.shutdown_dialog import shell_alt_f4
                if is_shell_running():
                    self.Hide()
                    shell_alt_f4(self.GetParent())
                    return
            except Exception as error:
                print(f"[TitanShell] Alt+F4 in the Start menu: {error}")
        if key == wx.WXK_ESCAPE:
            # Escape undoes one thing at a time: a branch that is open
            # closes first, and only a menu with nothing open closes.
            if self._collapse_current_branch():
                return
            self.close_to_start_button()
            return
        event.Skip()

    def _collapse_current_branch(self):
        """Escape inside an open branch closes that branch, not the menu."""
        try:
            item = self.menu_tree.GetSelection()
            if not item or not item.IsOk():
                return False
            if self.menu_tree.IsExpanded(item):
                self.menu_tree.Collapse(item)
                return True
            parent = self.menu_tree.GetItemParent(item)
            if parent and parent.IsOk() and parent != self.menu_tree.GetRootItem():
                self.menu_tree.SelectItem(parent)
                self.menu_tree.Collapse(parent)
                return True
        except Exception:
            pass
        return False

    def close_to_start_button(self):
        """Escape: close, and leave the keyboard where Windows leaves it.

        On Windows the menu closes onto the Start button it came out of -
        not onto a window of its own, and not nowhere.
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

    def on_close(self, event):
        """A Start menu is hidden, never destroyed.

        Titan keeps one of these and opens it again and again, so letting
        wx destroy it - which is what Alt+F4 outside the shell did - left
        the main window holding a dead frame and the next press of the
        Start key crashed on it.  Only a teardown that asked for it
        (`allow_close`) goes through.
        """
        if self._allow_close:
            event.Skip()
            return
        if hasattr(event, 'CanVeto') and event.CanVeto():
            event.Veto()
        self.Hide()

    def allow_close(self):
        """Let the next close really close it (Titan is going away)."""
        self._allow_close = True

    def on_activate(self, event):
        """Obsługa aktywacji okna"""
        # While the menu is the active window its keys are its own - the
        # same rule the main window follows, and the one the shell's
        # windows all follow now.
        handover.follows_activation(event)
        if event.GetActive():
            # Opening: this is the hand-over, and it happens here because
            # wxWidgets has just focused the frame in answer to
            # WM_ACTIVATE - the first moment a focus will stay where it is
            # put.
            if getattr(self, '_focus_pending', False):
                wx.CallAfter(self._hand_over_focus)
                return
            # Already in the menu - an activation that changes nothing must
            # not make the reader say the control again.
            focused = wx.Window.FindFocus()
            if focused is not None and self.IsDescendant(focused):
                return
            wx.CallAfter(self.focus_now)
        else:
            # The menu is dismissed by losing the foreground, which is what
            # a Start menu does everywhere.  A frame never gets
            # EVT_KILL_FOCUS - that is a control's event - so this is where
            # it has to be noticed.
            wx.CallLater(100, self.check_and_hide)

    def check_and_hide(self):
        """Sprawdź czy ukryć menu"""
        # Opened from a global shortcut the menu needs a moment before Windows
        # hands it the foreground; hiding on the focus loss that happens in
        # between would close the menu the instant it appears.
        if time.time() - getattr(self, '_shown_at', 0) < self.FOCUS_GRACE_SECONDS:
            return

        focus_window = wx.Window.FindFocus()
        if focus_window and self.IsDescendant(focus_window):
            return

        # FindFocus() only knows about our own process, so also accept the
        # case where this window is the system foreground window.
        if IS_WINDOWS and WIN32_AVAILABLE:
            try:
                if win32gui.GetForegroundWindow() == self.GetHandle():
                    return
            except Exception:
                pass

        self.Hide()

    def position_menu(self):
        """Bottom left, sitting on the taskbar, as Windows puts it."""
        try:
            screen_size = wx.GetDisplaySize()
            size = self.GetSize()
            taskbar_height = 40
            if self.shell is not None:
                taskbar_height = self.shell.taskbar_height()
            self.SetPosition((0, max(0, screen_size.height - size.height
                                     - taskbar_height)))
        except Exception as error:
            print(f"Error positioning the start menu: {error}")

    def show_menu(self):
        """Pokaż menu"""
        # Re-apply skin on every open so Alt+F1 always reflects current theme.
        self.apply_skin_settings()
        self._shown_at = time.time()
        # Rebuilt on every open, so an application, macro or IM module
        # installed since the last one is on it without Titan restarting.
        self.build_menu_structure()
        # The packaged Windows apps take over a second to read, and that is
        # a second of a branch that appears to hang; the search index is
        # not asked for, because this menu has no search box.
        self.prefetch(build_index=False)
        self.position_menu()
        # Claimed before the window is shown: `Show()` answers the
        # activation synchronously, and `on_activate` focusing the tree
        # there and then would put the control in front of the name.
        self._focus_pending = True
        self.Show()
        self.Raise()
        # A menu is furniture - it must not turn up in Alt+Tab beside the
        # user's own windows.
        try:
            from src.shell import win_shell
            win_shell.hide_from_alt_tab(self.GetHandle())
        except Exception:
            pass
        # Global shortcuts fire while another application owns the foreground,
        # so ask for it explicitly instead of relying on Raise().
        try:
            from src.titan_core.tce_system import force_foreground
            force_foreground(self)
        except Exception as e:
            print(f"Warning: could not foreground the Titan Menu: {e}")
        # The keyboard is handed over from the ACTIVATION (see
        # `on_activate`); this is only the fallback for when none arrives.
        # wxWidgets answers WM_ACTIVATE by focusing the FRAME, so a focus
        # set before the window has finished becoming active is undone and
        # then put back - and the reader says the control twice.
        wx.CallLater(self.FOCUS_FALLBACK_MS, self._hand_over_focus)
        if self.shell is not None:
            try:
                self.shell.set_start_button_pressed(True)
            except Exception:
                pass

    def Hide(self):  # noqa: N802 - wx naming
        result = super().Hide()
        if self.shell is not None:
            try:
                self.shell.set_start_button_pressed(False)
            except Exception:
                pass
        return result

    def _hand_over_focus(self):
        """Put the keyboard in the menu, once however this is reached.

        Once, because twice is what a screen reader reads as the control
        twice: wxWidgets answers WM_ACTIVATE by focusing the FRAME, so a
        focus set before the window has finished becoming active is undone
        and then put back.

        Nothing is said here: the window is called "Start menu" and a
        screen reader reads the name of a window it has just entered.
        """
        if not getattr(self, '_focus_pending', False):
            return
        self._focus_pending = False
        self.focus_now()

    def focus_now(self):
        """The keyboard goes to the menu tree."""
        self._focus_pending = False
        try:
            if wx.Window.FindFocus() is not self.menu_tree:
                self.menu_tree.SetFocus()
        except Exception:
            pass

    def toggle_menu(self):
        """Przełącz widoczność menu"""
        if self.IsShown():
            self.Hide()
        else:
            self.show_menu()

    # ------------------------------------------------------------------
    # Skinning
    # ------------------------------------------------------------------
    def apply_skin_settings(self):
        """Zastosuj ustawienia skórki do menu using skin manager"""
        try:
            skin = get_current_skin()

            # Apply skin to entire window tree (frame, panels, tree).
            _apply_skin_to_tree(self)

            # Configure from skin start menu settings
            self.configure_from_skin(skin.start_menu, skin.colors)
        except Exception as e:
            print(f"Error applying skin to start menu: {e}")

    def configure_from_skin(self, start_menu_config, colors):
        """Konfiguruj menu na podstawie ustawień skórki"""
        try:
            logo_text = start_menu_config.get('logo_text', 'Titan')
            logo_text_color = start_menu_config.get('logo_text_color', '#FFFFFF')
            logo_bg_color = start_menu_config.get('logo_background_color', '#000080')

            try:
                self.banner.configure(logo_text, wx.Colour(logo_text_color),
                                      wx.Colour(logo_bg_color))
            except Exception as e:
                print(f"Error setting banner colors: {e}")

            panel_color = colors.get('panel_background_color')
            if panel_color:
                try:
                    colour = wx.Colour(panel_color)
                    self.main_panel.SetBackgroundColour(colour)
                    self.menu_panel.SetBackgroundColour(colour)
                except Exception as e:
                    print(f"Error setting panel colors: {e}")

            try:
                listbox_bg = colors.get('listbox_background_color')
                listbox_fg = colors.get('listbox_foreground_color')
                if listbox_bg:
                    self.menu_tree.SetBackgroundColour(wx.Colour(listbox_bg))
                if listbox_fg:
                    self.menu_tree.SetForegroundColour(wx.Colour(listbox_fg))
            except Exception as e:
                print(f"Error setting menu colors: {e}")

            # Refresh display
            self.Refresh()
            self.Update()

        except Exception as e:
            print(f"Error configuring menu from skin: {e}")


def create_classic_start_menu(parent, shell=None):
    """Tworzenie klasycznego menu Start"""
    return ClassicStartMenu(parent, shell=shell)
