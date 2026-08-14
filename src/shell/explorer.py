# -*- coding: utf-8 -*-
"""
The file browser: My Computer, drives and folders, as Explorer has them.

This is the shell's own window over the file system, rebuilt from ReactOS'
`dll/win32/browseui` (`CShellBrowser` - the frame, its menu bar, its toolbar,
the address band, the status bar and the Folders bar) and `dll/win32/shell32`
(`CDefView` - the list of what is in a folder, its four views, its columns and
the menus on an item).  It is what "My Computer" and every folder open into
while the Titan shell is up, so the user never falls through to a window Titan
cannot make readable.

    File  Edit  View  Go  Help
    [Back] [Forward] [Up]  [Folders] [Views]
    Address [ C:\\Users\\...                              v ] [ Go ]
    +--------------+------------------------------------------+
    | Desktop      | Name        Size    Type       Modified   |
    |  My Computer | Documents           File folder ...       |
    |   C:         | notes.txt   2 KB    Text file  ...        |
    +--------------+------------------------------------------+
    | 12 object(s) | 3.40 MB              | My Computer        |

**Why it is accessible**: every part of it is a real, native control rather
than a painted one.  The folders bar is a `SysTreeView32`, the file list is a
`SysListView32` in report mode, and the menu bar, toolbar and status bar are
Windows' own - so a screen reader already knows how to read all of it, and the
arrow keys, first-letter jumping, the columns and the selection come from the
controls themselves.  Titan Access reads it with the accessibility tiers it
always uses instead of needing OCR.  The one thing a native control does not
do is *name* itself for MSAA, which is why `a11y.name_control` is used on the
tree, the list and the address field.

**The keyboard is complete without the toolbar.**  A native toolbar is not a
tab stop - in Explorer either - so every command on it is also a menu entry
with the key Explorer gives it: Alt+Left / Alt+Right / Backspace to move
about, F5 to re-read, F2 to rename, Delete to the Recycle Bin, Alt+Enter for
the properties, Ctrl+X / Ctrl+C / Ctrl+V, Ctrl+A, and F6 for the next pane.

**Alt+F4 closes this window** and nothing else: unlike the taskbar and the
desktop, a browser window *is* a window with something in it, and closing one
is what Windows does with the key here.
"""

import os
import threading
import time

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import fileops, win_shell
from src.shell import keyboard_handover as handover
from src.shell.deferred import Coalesced, alive, call_after
from src.system import key_state
from src.shell.a11y import (SOUND_NAVIGATE, edge_cue, name_control,
                            shell_setting, shell_sound)
from src.titan_core.translation import _

try:
    from src.accessibility.messages import announce_shell_location
except Exception:                                        # pragma: no cover
    def announce_shell_location(*_args, **_kwargs):
        return False


# The one location that is not a path.  Everything else the browser shows is
# a real folder, so a plain string is enough to say where it is.
COMPUTER = '::computer'

# The four views `CDefView` offers, in its own order.
VIEW_LARGE = 'large'
VIEW_SMALL = 'small'
VIEW_LIST = 'list'
VIEW_DETAILS = 'details'

_VIEW_STYLES = {
    VIEW_LARGE: wx.LC_ICON,
    VIEW_SMALL: wx.LC_SMALL_ICON,
    VIEW_LIST: wx.LC_LIST,
    VIEW_DETAILS: wx.LC_REPORT,
}

SMALL_ICON = 16
LARGE_ICON = 32

# How many rows of an icon view go in before the message loop is let run
# again.  Big enough that an ordinary folder is filled in one go, small
# enough that a huge one never holds the window for long.
FILL_CHUNK = 750

# How long the window will sit waiting for a folder to answer before it goes
# back to answering the keyboard instead.  Long enough that an ordinary
# folder - which answers in single-figure milliseconds - is on the screen
# before `navigate` returns, short enough that a share that has gone away
# cannot hold the shell.
READ_WAIT = 1.5

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def _drive_type_names():
    """Windows' own names for what a drive is, translated when asked for."""
    return {
        win_shell.DRIVE_REMOVABLE: _("Removable Disk"),
        win_shell.DRIVE_FIXED: _("Local Disk"),
        win_shell.DRIVE_REMOTE: _("Network Drive"),
        win_shell.DRIVE_CDROM: _("CD Drive"),
        win_shell.DRIVE_RAMDISK: _("RAM Disk"),
    }


# --------------------------------------------------------------------------- #
# What a location is, and what is in it
# --------------------------------------------------------------------------- #
def is_computer(location):
    return str(location or '') == COMPUTER


def drive_type_name(kind):
    return _drive_type_names().get(kind, _("Disk"))


def drive_name(drive):
    """"Local Disk (C:)", or the volume's own label with the letter after."""
    label = drive.get('label') or drive_type_name(drive.get('type'))
    return "{} ({})".format(label, drive.get('letter', ''))


def location_name(location):
    """What the window is called while it is showing this place.

    Kept, because this is another `SHGetFileInfo` and the status bar, the
    title and the list's accessible name all ask for the same one - and the
    status bar asks again every time the selection changes.
    """
    if is_computer(location):
        return _("My Computer")
    path = str(location or '')
    if not path:
        return _("My Computer")
    key = os.path.normcase(path)
    name = _DISPLAY_NAMES.get(key)
    if name is None:
        name = (win_shell.file_display_name(path)
                or os.path.basename(path.rstrip('\\/')) or path)
        if len(_DISPLAY_NAMES) > 512:
            _DISPLAY_NAMES.clear()
        _DISPLAY_NAMES[key] = name
    return name


def parent_location(location):
    """One level up, or None at the top.

    A drive's parent is My Computer and My Computer has none, which is what
    makes Backspace stop where Explorer stops rather than at "C:".
    """
    if is_computer(location):
        return None
    path = str(location or '')
    if not path:
        return None
    stripped = path.rstrip('\\/')
    if len(stripped) <= 2 and stripped.endswith(':'):
        return COMPUTER
    parent = os.path.dirname(stripped)
    if not parent or parent == stripped:
        return COMPUTER
    if len(parent) == 2 and parent.endswith(':'):
        parent += os.sep
    return parent


def format_size(size):
    """Explorer's own sizes: whole KB for a file, MB or GB for a disk."""
    if not size:
        return ''
    size = int(size)
    if size >= 1024 ** 3:
        return _("{value} GB").format(
            value="{:,.2f}".format(size / float(1024 ** 3)))
    if size >= 10 * 1024 * 1024:
        return _("{value} MB").format(
            value="{:,.1f}".format(size / float(1024 ** 2)))
    # Explorer rounds every file up to the next whole KB.
    return _("{value} KB").format(value="{:,}".format((size + 1023) // 1024))


def format_time(stamp):
    """The date and time in the user's own format, as the column shows it."""
    if not stamp:
        return ''
    try:
        moment = wx.DateTime.FromTimeT(int(stamp))
        return "{} {}".format(moment.FormatDate(), moment.FormatTime())
    except Exception:
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(stamp))


def _is_hidden(entry_path, stat_result=None):
    if os.path.basename(entry_path).startswith('.'):
        return True
    attributes = getattr(stat_result, 'st_file_attributes', 0) \
        if stat_result else 0
    return bool(attributes & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))


def list_computer():
    """My Computer: the drives, with what Explorer shows about each."""
    entries = []
    for drive in win_shell.list_drives():
        entries.append({
            'name': drive_name(drive),
            'path': drive['root'],
            'kind': 'drive',
            'type': drive_type_name(drive.get('type')),
            'size': None,
            'modified': None,
            'total': drive.get('total') or None,
            'free': drive.get('free') or None,
        })
    return entries


def list_folder(path, show_hidden=False):
    """One folder, folders first and then files, each sorted by name."""
    folders, files = [], []
    with os.scandir(path) as scan:
        for item in scan:
            try:
                stat_result = item.stat(follow_symlinks=False)
            except Exception:
                stat_result = None
            if not show_hidden and _is_hidden(item.path, stat_result):
                continue
            try:
                is_folder = item.is_dir()
            except Exception:
                is_folder = False
            entry = {
                'name': item.name,
                'path': item.path,
                'kind': 'folder' if is_folder else 'file',
                'type': '',
                'size': None if is_folder
                        else getattr(stat_result, 'st_size', None),
                'modified': getattr(stat_result, 'st_mtime', None),
                'total': None,
                'free': None,
            }
            (folders if is_folder else files).append(entry)
    folders.sort(key=lambda entry: entry['name'].lower())
    files.sort(key=lambda entry: entry['name'].lower())
    return folders + files


def list_location(location, show_hidden=False):
    if is_computer(location):
        return list_computer()
    return list_folder(str(location), show_hidden=show_hidden)


def subfolders(location, show_hidden=False):
    """What the folders bar shows under a place - folders and drives only.

    Read for itself rather than by filtering a whole listing: opening a
    branch of the folders bar wants the directories in it, and a folder
    holding fifty thousand files should not cost fifty thousand entries to
    find the four directories among them.
    """
    if is_computer(location):
        try:
            return list_computer()
        except Exception:
            return []
    entries = []
    try:
        with os.scandir(str(location)) as scan:
            for item in scan:
                try:
                    if not item.is_dir():
                        continue
                    stat_result = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not show_hidden and _is_hidden(item.path, stat_result):
                    continue
                entries.append({
                    'name': item.name,
                    'path': item.path,
                    'kind': 'folder',
                    'type': '',
                    'size': None,
                    'modified': None,
                    'total': None,
                    'free': None,
                })
    except Exception:
        return []
    entries.sort(key=lambda entry: entry['name'].lower())
    return entries


# "Text Document" is Windows' answer for every `.txt` on the machine, so it
# is asked for once per EXTENSION and never once per file.  Asking is a
# `SHGetFileInfo`, which can reach into a shell extension somebody else
# wrote, and a folder of three thousand files made three thousand of those
# calls before it could show a single row - most of the six seconds such a
# folder took to open.
_TYPE_NAMES = {}

# What Windows calls a folder and a drive is Titan's own word for them, so
# those two never go near the shell at all.
_DISPLAY_NAMES = {}


def clear_caches():
    """Forget what Windows told us - after a language change, in a test."""
    _TYPE_NAMES.clear()
    _DISPLAY_NAMES.clear()


def _extension_type_name(path):
    """The type of a file, cached against its extension rather than its name."""
    key = os.path.splitext(str(path))[1].lower() or '::none'
    name = _TYPE_NAMES.get(key)
    if name is None:
        name = win_shell.file_type_name(path) or _("File")
        _TYPE_NAMES[key] = name
    return name


def type_name_of(entry):
    """"File folder", "Text Document" - asked of Windows, and kept.

    Filled in lazily and cached twice over: on the entry itself, so a
    re-sort does not ask again, and by extension in `_TYPE_NAMES`, so the
    second `.txt` in a folder costs nothing at all.
    """
    if entry.get('type'):
        return entry['type']
    if entry['kind'] == 'folder':
        entry['type'] = _("File folder")
    elif entry['kind'] == 'drive':
        entry['type'] = _("Local Disk")
    else:
        entry['type'] = _extension_type_name(entry['path'])
    return entry['type']


# --------------------------------------------------------------------------- #
# Icons
# --------------------------------------------------------------------------- #
class IconCache:
    """Real Windows icons, asked for once per kind of thing.

    A folder of five thousand files must not mean five thousand
    `SHGetFileInfo` calls, and it does not have to: every `.txt` in it draws
    the same icon.  So files are cached by extension and only the things
    that carry an icon of their own - programs, shortcuts, folders and
    drives - are asked about one at a time.

    The cache belongs to the WINDOW, not to a reading of a folder.  It used
    to be built afresh on every fill, which meant that going into a folder,
    coming back out of it and sorting a column each fetched every icon
    again - and fetched both sizes of every one of them, since a list that
    might be switched to large icons was given both image lists up front.
    Now it outlives the fill, and the view asks for the size it is actually
    showing, one row at a time, as those rows are painted.
    """

    PER_PATH = ('.exe', '.lnk', '.ico', '.url', '.cpl', '.msc')

    def __init__(self, size):
        self.size = size
        self.image_list = wx.ImageList(size, size)
        self._by_key = {}

    def _fallback_index(self, folder=False):
        art = wx.ART_FOLDER if folder else wx.ART_NORMAL_FILE
        bitmap = wx.ArtProvider.GetBitmap(art, wx.ART_OTHER,
                                          (self.size, self.size))
        return self.image_list.Add(bitmap)

    def index_for(self, entry):
        kind = entry.get('kind')
        path = entry.get('path') or ''
        extension = os.path.splitext(path)[1].lower()
        if kind in ('folder', 'drive') or extension in self.PER_PATH:
            key = os.path.normcase(path)
        else:
            key = extension or '::file'
        if key in self._by_key:
            return self._by_key[key]

        bitmap = None
        if IS_WINDOWS:
            handle = win_shell.file_icon_handle(
                path, large=(self.size >= LARGE_ICON))
            if handle:
                from src.shell.controls import bitmap_from_icon_handle
                bitmap = bitmap_from_icon_handle(handle, self.size)
        if bitmap is not None and bitmap.IsOk():
            index = self.image_list.Add(bitmap)
        else:
            index = self._fallback_index(folder=(kind in ('folder', 'drive')))
        self._by_key[key] = index
        return index


# --------------------------------------------------------------------------- #
# The view
# --------------------------------------------------------------------------- #
class FileListCtrl(wx.ListCtrl):
    """The list of what is in a folder - which in Details is *virtual*.

    A folder with three thousand files in it used to be three thousand
    `InsertItem` calls and twelve thousand `SetItem` calls before the window
    could be shown, each of them a message to the native control, and every
    one of the cells they carried worked out in advance whether anybody was
    ever going to look at it.  Measured on such a folder, opening it took
    just under six seconds.

    `LVS_OWNERDATA` - `wx.LC_VIRTUAL` - is what Explorer's own list view
    uses and it inverts that: the control is told how many rows there are
    and asks for a row's text and icon when it comes to paint it, so only
    the thirty rows on the screen cost anything.  Going into the folder is
    then one `SetItemCount`.

    It changes nothing for a screen reader: this is the same native
    `SysListView32` answering MSAA the same way, which is exactly why the
    virtual list is worth having rather than a list Titan draws itself.

    wxWidgets only offers virtual mode in report view, so the three icon
    views are still filled item by item - they are the views nobody opens a
    thirty-thousand-file folder in, and their icons come from the same
    cache.
    """

    def __init__(self, parent, style, browser):
        super().__init__(parent, style=style)
        self.browser = browser

    def OnGetItemText(self, item, column):
        return self.browser.cell_at(item, column)

    def OnGetItemImage(self, item):
        return self.browser.image_at(item)

    def OnGetItemColumnImage(self, item, column):
        # Only the first column carries a picture, as in Explorer.
        return self.browser.image_at(item) if column == 0 else -1


# --------------------------------------------------------------------------- #
# The window
# --------------------------------------------------------------------------- #
class ExplorerFrame(wx.Frame):
    """`CShellBrowser`: the frame everything else lives in."""

    def __init__(self, parent=None, location=COMPUTER):
        super().__init__(parent, title=location_name(location),
                         size=(820, 560))

        self.ID_UP = wx.NewIdRef()
        self.ID_FOLDERS = wx.NewIdRef()
        self.ID_VIEWS = wx.NewIdRef()

        self.location = COMPUTER
        self.entries = []
        self._history = []
        self._history_index = -1
        self._cut_paths = []
        self._sort_column = 0
        self._sort_reverse = False
        # One icon cache per size, for the life of the window rather than of
        # a fill, and the image lists inside them are ours: the list control
        # is given them with `SetImageList`, which does not take them over,
        # so replacing the control when the view changes cannot destroy the
        # cache under us.
        self._icons = {}
        # Where a chunked fill of an icon view has got to, and which fill it
        # belongs to: a new folder moves the token on and what is left of
        # the last one stops.
        self._fill_from = None
        self._fill_token = 0
        # Which folder read the window is waiting for; an older one's answer
        # is stale and is dropped rather than shown over a newer one.
        self._read_token = 0
        # A folder is read once; something asking to read it again while it
        # is being read would put the window into a state where the list and
        # `self.entries` disagree.
        self._navigating = False

        self.view = str(shell_setting('explorer_view', VIEW_DETAILS))
        if self.view not in _VIEW_STYLES:
            self.view = VIEW_DETAILS
        self.show_hidden = bool(shell_setting('explorer_show_hidden', False))
        self._folders_shown = bool(shell_setting('explorer_folders', True))

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_status_bar()

        # Selecting a thousand files fires a thousand selection events, and
        # working the status bar out costs a walk of the selection - which
        # is what made Ctrl+A in a three-thousand-file folder take
        # thirty-seven seconds.  The bar is worked out once, at the end of
        # the burst.
        self._status_update = Coalesced(self, self._update_status)

        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        # A window with a file list and an address band in it: while it is
        # in front the keys are its own, not the Invisible UI's.
        self.Bind(wx.EVT_ACTIVATE, self._on_window_activate)

        self.CentreOnScreen()
        self.navigate(location)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build_menu(self):
        """The menu bar `CShellBrowser` builds, minus what it greys out.

        Every command here does something: ReactOS' own commented-out
        entries, and the ones that would need a shell namespace Titan does
        not have, are absent rather than dead.
        """
        bar = wx.MenuBar()

        # Enter, Delete and F2 are deliberately NOT menu accelerators.  A
        # menu accelerator fires wherever the keyboard is, so a Del written
        # into this bar would delete the selected files while the user was
        # typing in the address field or renaming an icon.  They are handled
        # in the frame's char hook instead, which knows where the focus is;
        # the key is named in the entry's help text so it is still findable.
        file_menu = wx.Menu()
        self.menu_open = file_menu.Append(
            wx.ID_ANY, _("&Open"), _("Open what is selected (Enter)"))
        self.menu_new_folder = file_menu.Append(
            wx.ID_ANY, _("Ne&w folder\tCtrl+Shift+N"))
        self.menu_shortcut = file_menu.Append(wx.ID_ANY,
                                              _("Create &shortcut"))
        file_menu.AppendSeparator()
        self.menu_delete = file_menu.Append(
            wx.ID_ANY, _("&Delete"),
            _("Send what is selected to the Recycle Bin (Delete)"))
        self.menu_rename = file_menu.Append(
            wx.ID_ANY, _("Rena&me"), _("Rename what is selected (F2)"))
        file_menu.AppendSeparator()
        self.menu_properties = file_menu.Append(
            wx.ID_ANY, _("P&roperties\tAlt+Enter"))
        file_menu.AppendSeparator()
        self.menu_close = file_menu.Append(wx.ID_CLOSE, _("&Close\tAlt+F4"))
        bar.Append(file_menu, _("&File"))

        edit_menu = wx.Menu()
        self.menu_cut = edit_menu.Append(wx.ID_CUT, _("Cu&t\tCtrl+X"))
        self.menu_copy = edit_menu.Append(wx.ID_COPY, _("&Copy\tCtrl+C"))
        self.menu_paste = edit_menu.Append(wx.ID_PASTE, _("&Paste\tCtrl+V"))
        edit_menu.AppendSeparator()
        self.menu_select_all = edit_menu.Append(
            wx.ID_SELECTALL, _("Select &All\tCtrl+A"))
        self.menu_invert = edit_menu.Append(wx.ID_ANY,
                                            _("&Invert Selection"))
        bar.Append(edit_menu, _("&Edit"))

        view_menu = wx.Menu()
        self.menu_toolbar = view_menu.AppendCheckItem(wx.ID_ANY, _("&Toolbar"))
        self.menu_status = view_menu.AppendCheckItem(wx.ID_ANY,
                                                     _("&Status Bar"))
        self.menu_folders = view_menu.AppendCheckItem(wx.ID_ANY,
                                                      _("&Folders"))
        view_menu.AppendSeparator()
        self.menu_view_large = view_menu.AppendRadioItem(wx.ID_ANY,
                                                         _("Lar&ge Icons"))
        self.menu_view_small = view_menu.AppendRadioItem(wx.ID_ANY,
                                                         _("S&mall Icons"))
        self.menu_view_list = view_menu.AppendRadioItem(wx.ID_ANY, _("&List"))
        self.menu_view_details = view_menu.AppendRadioItem(wx.ID_ANY,
                                                           _("&Details"))
        view_menu.AppendSeparator()
        self.menu_hidden = view_menu.AppendCheckItem(
            wx.ID_ANY, _("Show &hidden files"))
        view_menu.AppendSeparator()
        self.menu_refresh = view_menu.Append(wx.ID_ANY, _("R&efresh\tF5"))
        bar.Append(view_menu, _("&View"))

        go_menu = wx.Menu()
        self.menu_back = go_menu.Append(wx.ID_ANY, _("&Back\tAlt+Left"))
        self.menu_forward = go_menu.Append(wx.ID_ANY, _("&Forward\tAlt+Right"))
        self.menu_up = go_menu.Append(wx.ID_ANY, _("&Up One Level\tAlt+Up"))
        go_menu.AppendSeparator()
        self.menu_computer = go_menu.Append(wx.ID_ANY, _("My &Computer"))
        self.menu_home = go_menu.Append(wx.ID_ANY, _("My &Documents"))
        self.menu_desktop = go_menu.Append(wx.ID_ANY, _("&Desktop"))
        bar.Append(go_menu, _("&Go"))

        help_menu = wx.Menu()
        self.menu_about = help_menu.Append(wx.ID_ABOUT, _("&About"))
        bar.Append(help_menu, _("&Help"))

        self.SetMenuBar(bar)

        self.menu_toolbar.Check(True)
        self.menu_status.Check(True)
        self.menu_folders.Check(self._folders_shown)
        self.menu_hidden.Check(self.show_hidden)
        {VIEW_LARGE: self.menu_view_large,
         VIEW_SMALL: self.menu_view_small,
         VIEW_LIST: self.menu_view_list,
         VIEW_DETAILS: self.menu_view_details}[self.view].Check(True)

        bindings = (
            (self.menu_open, lambda event: self.open_selected()),
            (self.menu_new_folder, lambda event: self.new_folder()),
            (self.menu_shortcut, lambda event: self.create_shortcut()),
            (self.menu_delete, lambda event: self.delete_selected()),
            (self.menu_rename, lambda event: self.rename_selected()),
            (self.menu_properties, lambda event: self.show_properties()),
            (self.menu_close, lambda event: self.Close()),
            (self.menu_cut, lambda event: self.copy_selection(cut=True)),
            (self.menu_copy, lambda event: self.copy_selection()),
            (self.menu_paste, lambda event: self.paste()),
            (self.menu_select_all, lambda event: self.select_all()),
            (self.menu_invert, lambda event: self.invert_selection()),
            (self.menu_toolbar,
             lambda event: self.show_toolbar(self.menu_toolbar.IsChecked())),
            (self.menu_status,
             lambda event: self.show_status_bar(self.menu_status.IsChecked())),
            (self.menu_folders,
             lambda event: self.show_folders(self.menu_folders.IsChecked())),
            (self.menu_view_large, lambda event: self.set_view(VIEW_LARGE)),
            (self.menu_view_small, lambda event: self.set_view(VIEW_SMALL)),
            (self.menu_view_list, lambda event: self.set_view(VIEW_LIST)),
            (self.menu_view_details, lambda event: self.set_view(VIEW_DETAILS)),
            (self.menu_hidden,
             lambda event: self.set_show_hidden(self.menu_hidden.IsChecked())),
            (self.menu_refresh, lambda event: self.refresh()),
            (self.menu_back, lambda event: self.go_back()),
            (self.menu_forward, lambda event: self.go_forward()),
            (self.menu_up, lambda event: self.go_up()),
            (self.menu_computer, lambda event: self.navigate(COMPUTER)),
            (self.menu_home,
             lambda event: self.navigate(os.path.expanduser('~/Documents'))),
            (self.menu_desktop,
             lambda event: self.navigate(self._desktop_folder())),
            (self.menu_about, lambda event: self.show_about()),
        )
        for item, handler in bindings:
            self.Bind(wx.EVT_MENU, handler, item)

    def _build_toolbar(self):
        """`CShellBrowser`'s bands: Back, Forward, Up, Folders, Views, Address.

        The tools carry their text as well as their picture (`wx.TB_TEXT`):
        a toolbar button with a picture alone is a button with no name, and
        this one has to be readable with the mouse pointer over it as much
        as with a screen reader.
        """
        self.toolbar = self.CreateToolBar(
            wx.TB_HORIZONTAL | wx.TB_TEXT | wx.TB_FLAT)
        size = (16, 16)

        def art(identifier):
            return wx.ArtProvider.GetBitmap(identifier, wx.ART_TOOLBAR, size)

        self.toolbar.AddTool(wx.ID_BACKWARD, _("Back"), art(wx.ART_GO_BACK),
                             _("Back"))
        self.toolbar.AddTool(wx.ID_FORWARD, _("Forward"),
                             art(wx.ART_GO_FORWARD), _("Forward"))
        self.toolbar.AddTool(self.ID_UP, _("Up"), art(wx.ART_GO_DIR_UP),
                             _("Up One Level"))
        self.toolbar.AddSeparator()
        self.toolbar.AddCheckTool(self.ID_FOLDERS, _("Folders"),
                                  art(wx.ART_LIST_VIEW), art(wx.ART_LIST_VIEW),
                                  _("Show or hide the folders bar"))
        self.toolbar.AddTool(self.ID_VIEWS, _("Views"), art(wx.ART_REPORT_VIEW),
                             _("Change the view"))
        self.toolbar.AddSeparator()

        # The address band, which is what `CAddressBand` is made of: a
        # label, an editable combo box holding where the window has been,
        # and Go.
        self.address_label = wx.StaticText(self.toolbar, label=_("A&ddress"))
        self.toolbar.AddControl(self.address_label)
        self.address = wx.ComboBox(self.toolbar, size=(320, -1),
                                   style=wx.TE_PROCESS_ENTER)
        name_control(self.address, _("Address"))
        self.toolbar.AddControl(self.address)
        self.go_button = wx.Button(self.toolbar, label=_("&Go"), size=(48, -1))
        self.toolbar.AddControl(self.go_button)
        self.toolbar.Realize()

        self.toolbar.ToggleTool(self.ID_FOLDERS, self._folders_shown)
        self.Bind(wx.EVT_TOOL, lambda event: self.go_back(), id=wx.ID_BACKWARD)
        self.Bind(wx.EVT_TOOL, lambda event: self.go_forward(),
                  id=wx.ID_FORWARD)
        self.Bind(wx.EVT_TOOL, lambda event: self.go_up(), id=self.ID_UP)
        self.Bind(wx.EVT_TOOL,
                  lambda event: self.show_folders(
                      self.toolbar.GetToolState(self.ID_FOLDERS)),
                  id=self.ID_FOLDERS)
        self.Bind(wx.EVT_TOOL, self._on_views_tool, id=self.ID_VIEWS)
        self.address.Bind(wx.EVT_TEXT_ENTER, self._on_address_enter)
        self.go_button.Bind(wx.EVT_BUTTON, self._on_address_enter)

    def _build_body(self):
        """The folders bar and the view, with the splitter between them."""
        self.splitter = wx.SplitterWindow(
            self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        self.splitter.SetMinimumPaneSize(120)

        self.tree = wx.TreeCtrl(
            self.splitter,
            style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE
            | wx.TR_EDIT_LABELS)
        name_control(self.tree, _("Folders"))
        self.tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._on_tree_expanding)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_selected)
        # Enter on a folder in the bar opens it in the list, exactly as
        # double-clicking it does - the bar is a way of getting somewhere,
        # so it must answer the key that means "go there".
        self.tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_tree_activated)
        self.tree.Bind(wx.EVT_TREE_END_LABEL_EDIT, self._on_tree_renamed)

        self.list_holder = wx.Panel(self.splitter)
        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_holder.SetSizer(self.list_sizer)
        self.list = None
        self._make_list()

        if self._folders_shown:
            self.splitter.SplitVertically(self.tree, self.list_holder, 200)
        else:
            self.splitter.Initialize(self.list_holder)
            self.tree.Hide()
        self._build_tree_roots()

    def is_virtual(self):
        """True in Details, the one view wxWidgets will let be virtual."""
        return self.view == VIEW_DETAILS

    def _make_list(self):
        """The view itself, built for whichever of the four views is on.

        A list view's mode is a window style, so changing the view really
        does mean a new control - which is why what was selected is put
        back by path afterwards rather than by index.
        """
        style = _VIEW_STYLES[self.view] | wx.LC_EDIT_LABELS | wx.BORDER_SUNKEN
        if self.is_virtual():
            style |= wx.LC_VIRTUAL
        new_list = FileListCtrl(self.list_holder, style, self)
        new_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED,
                      lambda event: self.open_selected())
        new_list.Bind(wx.EVT_LIST_END_LABEL_EDIT, self._on_rename_done)
        new_list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_item_menu)
        new_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selection_changed)
        new_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_selection_changed)
        new_list.Bind(wx.EVT_LIST_COL_CLICK, self._on_column_click)
        new_list.Bind(wx.EVT_CONTEXT_MENU, self._on_background_menu)

        if self.list is not None:
            self.list_sizer.Detach(self.list)
            self.list.Destroy()
        self.list = new_list
        name_control(self.list, location_name(self.location))
        self.list_sizer.Add(self.list, 1, wx.EXPAND)
        self.list_holder.Layout()

    def _build_status_bar(self):
        """Explorer's three panes: how many, how big, and where."""
        self.status = self.CreateStatusBar(3)
        self.status.SetStatusWidths([-2, -1, -2])

    # ------------------------------------------------------------------
    # The folders bar
    # ------------------------------------------------------------------
    @staticmethod
    def _desktop_folder():
        folders = win_shell.desktop_folders()
        return folders[0] if folders else os.path.expanduser('~/Desktop')

    def _build_tree_roots(self):
        """Desktop at the root, with My Computer under it - XP's own tree."""
        self.tree.DeleteAllItems()
        root = self.tree.AddRoot(_("Desktop"))
        self.tree.SetItemData(root, self._desktop_folder())

        computer = self.tree.AppendItem(root, _("My Computer"))
        self.tree.SetItemData(computer, COMPUTER)
        self.tree.SetItemHasChildren(computer, True)

        documents = os.path.expanduser('~/Documents')
        if os.path.isdir(documents):
            item = self.tree.AppendItem(root, location_name(documents))
            self.tree.SetItemData(item, documents)
            self.tree.SetItemHasChildren(item, True)

        self.tree.Expand(root)
        self.tree.Expand(computer)

    def _on_tree_expanding(self, event):
        """A branch fills itself the first time it is opened, not before.

        Reading every drive to the bottom when the window opens is most of
        a minute the user would sit through; a branch that has never been
        opened costs nothing.
        """
        item = event.GetItem()
        if not item.IsOk():
            return
        if self.tree.GetChildrenCount(item, False) > 0:
            return
        location = self.tree.GetItemData(item)
        for entry in subfolders(location, self.show_hidden):
            child = self.tree.AppendItem(item, entry['name'])
            self.tree.SetItemData(child, entry['path'])
            self.tree.SetItemHasChildren(child, True)

    def _on_tree_selected(self, event):
        item = event.GetItem()
        if item.IsOk():
            location = self.tree.GetItemData(item)
            if location and str(location) != str(self.location):
                self.navigate(location, focus_list=False)
        event.Skip()

    def _on_tree_activated(self, event):
        """Enter (or a double click) in the folders bar: go there."""
        item = event.GetItem()
        if item.IsOk():
            location = self.tree.GetItemData(item)
            if location:
                self.navigate(location)
        event.Skip()

    def tree_location(self):
        """The folder the bar is on, or None - what its own keys act upon."""
        try:
            item = self.tree.GetSelection()
        except Exception:
            return None
        if not item or not item.IsOk():
            return None
        location = self.tree.GetItemData(item)
        return None if is_computer(location) else location

    def _on_tree_renamed(self, event):
        if event.IsEditCancelled():
            return
        item = event.GetItem()
        old_path = self.tree.GetItemData(item)
        new_name = event.GetLabel().strip()
        if not old_path or is_computer(old_path) or not new_name:
            event.Veto()
            return
        new_path = os.path.join(os.path.dirname(str(old_path).rstrip('\\/')),
                                new_name)
        try:
            os.rename(old_path, new_path)
            self.tree.SetItemData(item, new_path)
            if os.path.normcase(str(self.location)) == \
                    os.path.normcase(str(old_path)):
                self.location = new_path
                self._update_address()
                self._update_title()
        except Exception as error:
            print(f"[TitanShell] rename failed: {error}")
            event.Veto()
            wx.MessageBox(_("The item could not be renamed."),
                          location_name(self.location),
                          wx.OK | wx.ICON_ERROR, self)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def navigate(self, location, remember=True, focus_list=True,
                 select_named=None, select_paths=None):
        """Show a place, and remember where we came from.

        One at a time: putting the folders bar on the place the list has
        just gone to selects an item in the tree, which is a selection
        event, which asks to navigate.  It settles by itself because the
        second ask is for where we already are - but a slow folder read
        under a second one would leave the list and `self.entries`
        disagreeing about what is on the screen, and the guard is cheaper
        than the class of bug that follows from that.
        """
        if self._navigating:
            return False
        self._navigating = True
        try:
            return self._navigate(location, remember=remember,
                                  focus_list=focus_list,
                                  select_named=select_named,
                                  select_paths=select_paths)
        finally:
            self._navigating = False

    def _navigate(self, location, remember=True, focus_list=True,
                  select_named=None, select_paths=None):
        """Read the place on a thread, and wait for it only so long.

        Reading a folder is normally instant and the window fills in from
        this very call, exactly as it always did.  What it must not do is
        BLOCK: `os.path.isdir` and `os.scandir` on a network share that has
        gone away take as long as Windows' own timeouts, and this process
        is the shell - the appbar and the shell hook make it the thing
        every other program's broadcasts go through, so a GUI thread parked
        in a file system call for thirty seconds is a machine that has
        stopped, not merely a Titan that is thinking.

        So the read happens on a worker.  The window waits `READ_WAIT` for
        it - long enough that an ordinary folder is filled in before this
        returns - and if the answer has still not come it says so in the
        status bar, goes back to answering the keyboard, and fills itself
        in when the answer arrives.  A newer navigation makes an older
        answer stale, and a stale one is dropped.
        """
        location = COMPUTER if is_computer(location) else str(location)
        if not is_computer(location) and len(location) == 2 \
                and location.endswith(':'):
            location += os.sep

        self._read_token += 1
        request = {
            'token': self._read_token,
            'location': location,
            'remember': remember,
            'focus_list': focus_list,
            'select_named': select_named,
            'select_paths': select_paths,
        }
        ready = threading.Event()
        show_hidden = self.show_hidden

        def work():
            try:
                if not is_computer(location) and not os.path.isdir(location):
                    request['missing'] = os.path.isfile(location)
                else:
                    request['entries'] = list_location(location, show_hidden)
            except Exception as error:
                request['error'] = error
            ready.set()
            call_after(self, self._apply_read, request)

        threading.Thread(target=work, daemon=True,
                         name='TitanShellFolder').start()
        ready.wait(READ_WAIT)
        if not ready.is_set():
            self._show_working(location)
            return True
        return self._apply_read(request)

    def _show_working(self, location):
        """The folder is taking its time; say so and let the window be used.

        The old contents stay on the screen, which is what Explorer does
        while it is reading: an empty list would say the folder was empty.
        The name is taken apart rather than asked of Windows, because
        asking about a place that has just failed to answer is one more
        call that will not come back.
        """
        try:
            name = os.path.basename(str(location).rstrip('\\/')) or \
                str(location)
            self.status.SetStatusText(_("Working..."), 0)
            self.status.SetStatusText('', 1)
            self.status.SetStatusText(name, 2)
        except Exception:
            pass

    def _apply_read(self, request):
        """What the worker found, turned into a window - once, and if fresh."""
        if request.get('applied') or request['token'] != self._read_token:
            return False
        request['applied'] = True
        location = request['location']

        if 'missing' in request:
            if request['missing']:
                # A file, not a folder: open it and stay where we are.
                win_shell.open_path(location)
                self._update_status()
                return True
            wx.MessageBox(
                _("{name} is not available.").format(name=location),
                _("My Computer"), wx.OK | wx.ICON_ERROR, self)
            self._update_status()
            return False

        error = request.get('error')
        if error is not None:
            print(f"[TitanShell] could not read {location}: {error}")
            wx.MessageBox(
                _("Windows will not let this folder be opened.")
                if isinstance(error, PermissionError)
                else _("This folder could not be read."),
                location_name(location), wx.OK | wx.ICON_ERROR, self)
            self._update_status()
            return False

        entries = request.get('entries') or []
        if request.get('remember'):
            del self._history[self._history_index + 1:]
            self._history.append(location)
            self._history_index = len(self._history) - 1

        self.location = location
        self.entries = entries
        self._fill_list()
        self._update_address()
        self._update_title()
        self._update_status()
        self._update_commands()
        if request.get('focus_list'):
            self.list.SetFocus()
            self._focus_first()
        self._select_in_tree(location)
        # What the caller wanted picked out once the folder was there: the
        # folder we came up out of, or the selection a refresh is putting
        # back.  It has to happen here rather than after `navigate` returns,
        # or a folder that answered late would be filled in after the
        # selection had been asked for.
        if request.get('select_named'):
            self._select_named(*request['select_named'])
        if request.get('select_paths'):
            self._select_paths(request['select_paths'])
        # Explorer's "Start Navigation": going into a folder, back out of
        # one, or anywhere else, makes the same sound.
        shell_sound(SOUND_NAVIGATE)
        # The one change that is not where the focus is: the list has been
        # replaced under the reader, so what it now holds is said once.
        announce_shell_location(location_name(location), len(entries))
        return True

    def go_back(self):
        if self._history_index <= 0:
            edge_cue()
            return False
        self._history_index -= 1
        self.navigate(self._history[self._history_index], remember=False)
        return True

    def go_forward(self):
        if self._history_index >= len(self._history) - 1:
            edge_cue()
            return False
        self._history_index += 1
        self.navigate(self._history[self._history_index], remember=False)
        return True

    def go_up(self):
        parent = parent_location(self.location)
        if parent is None:
            edge_cue()
            return False
        came_from = self.location
        # Explorer leaves the folder you came out of selected, so one press
        # of Enter goes straight back into it - and the read is told to do
        # that, so it still happens when the folder answers late.
        return self.navigate(
            parent, select_named=(location_name(came_from), came_from))

    def refresh(self):
        selected = [entry['path'] for entry in self.selected_entries()]
        return self.navigate(self.location, remember=False,
                             select_paths=selected)

    # ------------------------------------------------------------------
    # The list
    # ------------------------------------------------------------------
    def columns(self):
        """What the columns are here - My Computer's are not a folder's."""
        if is_computer(self.location):
            return [(_("Name"), 220), (_("Type"), 120),
                    (_("Total Size"), 110), (_("Free Space"), 110)]
        return [(_("Name"), 240), (_("Size"), 90), (_("Type"), 140),
                (_("Date Modified"), 150)]

    def cell_text(self, entry, column):
        """One cell of the details view, column by column."""
        if is_computer(self.location):
            values = [entry['name'], type_name_of(entry),
                      format_size(entry.get('total')),
                      format_size(entry.get('free'))]
        else:
            values = [entry['name'], format_size(entry.get('size')),
                      type_name_of(entry), format_time(entry.get('modified'))]
        return values[column] if 0 <= column < len(values) else ''

    def _icon_cache(self, size):
        """The window's cache for one icon size, built the first time asked."""
        cache = self._icons.get(size)
        if cache is None:
            cache = IconCache(size)
            self._icons[size] = cache
        return cache

    def _icon_size(self):
        """The size the view on show draws its icons at."""
        return LARGE_ICON if self.view == VIEW_LARGE else SMALL_ICON

    # The two questions a virtual list asks about a row.  Both are answered
    # out of what is already in hand - the entry, and a cached icon - so the
    # answer costs nothing for a row that has been painted before and one
    # shell call for a row of a kind that has not.
    def cell_at(self, row, column):
        if not (0 <= row < len(self.entries)):
            return ''
        return self.cell_text(self.entries[row], column)

    def image_at(self, row):
        if not (0 <= row < len(self.entries)):
            return -1
        return self._icon_cache(self._icon_size()).index_for(self.entries[row])

    def _fill_list(self):
        """Show what `self.entries` holds - in Details, by saying how many.

        Report view is virtual, so filling it is one call however many files
        the folder has; the icon views are still filled row by row, with the
        icons coming from the window's own cache rather than from Windows.
        """
        self.list.Freeze()
        try:
            if self.list.IsVirtual():
                # A control still holding rows walks them all as its columns
                # are deleted; it must be emptied before it is cleared.
                self.list.SetItemCount(0)
            self.list.ClearAll()

            columns = self.columns()
            if self.view == VIEW_DETAILS:
                for index, (label, width) in enumerate(columns):
                    self.list.InsertColumn(index, label, width=width)

            # `SetImageList`, never `AssignImageList`: the caches outlive the
            # control, and a control that owned one would destroy it when the
            # view changed and leave the window drawing from freed memory.
            self.list.SetImageList(self._icon_cache(LARGE_ICON).image_list,
                                   wx.IMAGE_LIST_NORMAL)
            self.list.SetImageList(self._icon_cache(SMALL_ICON).image_list,
                                   wx.IMAGE_LIST_SMALL)

            # Whatever was still being filled in was for the last folder.
            self._fill_token += 1
            self._fill_from = None

            if self.list.IsVirtual():
                self.list.SetItemCount(len(self.entries))
            else:
                self._fill_from = 0
                self._fill_rows(FILL_CHUNK, self._fill_token)
            # The list's accessible name is where it is showing, so a reader
            # says "Documents, list" when the keyboard lands in it.
            name_control(self.list, location_name(self.location))
        finally:
            self.list.Thaw()

    def _fill_rows(self, count, token):
        """Put the next block of rows into an icon view.

        wxWidgets will not make an icon view virtual, so these three views
        really are filled row by row - three thousand rows measured 1.3
        seconds, and a folder ten times that size would be a window that
        answers nothing for a quarter of a minute.  So they arrive a block
        at a time with the message loop run in between: the first block is
        on the screen at once and the window is usable while the rest
        follows.  Anything that needs every row asks for it first
        (`_finish_fill`), and a new folder cancels what was left of the old
        one by moving the token on.
        """
        if token != self._fill_token or self._fill_from is None:
            return False
        start = self._fill_from
        total = len(self.entries)
        end = total if count is None else min(total, start + int(count))
        cache = self._icon_cache(self._icon_size())
        self.list.Freeze()
        try:
            for row in range(start, end):
                entry = self.entries[row]
                self.list.InsertItem(row, entry['name'],
                                     cache.index_for(entry))
        finally:
            self.list.Thaw()
        if end >= total:
            self._fill_from = None
            return True
        self._fill_from = end
        call_after(self, self._fill_rows, FILL_CHUNK, token)
        return False

    def _finish_fill(self):
        """Complete a chunked fill now: something wants the whole list."""
        if self._fill_from is not None:
            self._fill_rows(None, self._fill_token)

    def _focus_first(self):
        """A list view with no focused item reads as an empty container."""
        if self.list.GetItemCount() <= 0:
            return
        self.list.SetItemState(0, wx.LIST_STATE_FOCUSED,
                               wx.LIST_STATE_FOCUSED)

    def _select_path(self, path):
        self._finish_fill()
        wanted = os.path.normcase(str(path))
        for index, entry in enumerate(self.entries):
            if os.path.normcase(entry['path']) == wanted:
                self.list.SetItemState(
                    index, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                    wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
                self.list.EnsureVisible(index)
                return True
        return False

    def _select_paths(self, paths):
        """Put a whole selection back, in one pass over the folder.

        Asking for each path in turn is a search of the folder per path, so
        restoring the selection after a refresh cost as much as the number
        of selected files times the number of files - the reason F5 with
        everything selected took the best part of a minute.
        """
        wanted = {os.path.normcase(str(path)) for path in paths}
        if not wanted:
            return 0
        self._finish_fill()
        if len(wanted) >= len(self.entries) > 0:
            # Everything was selected, which after a refresh is everything
            # again: one message rather than one per file.
            self._select_every_item()
            self.list.EnsureVisible(0)
            return len(self.entries)
        found = 0
        self.list.Freeze()
        try:
            for index, entry in enumerate(self.entries):
                if os.path.normcase(entry['path']) in wanted:
                    self.list.SetItemState(index, wx.LIST_STATE_SELECTED,
                                           wx.LIST_STATE_SELECTED)
                    if found == 0:
                        self.list.SetItemState(index, wx.LIST_STATE_FOCUSED,
                                               wx.LIST_STATE_FOCUSED)
                        first = index
                    found += 1
        finally:
            self.list.Thaw()
        if found:
            self.list.EnsureVisible(first)
        return found

    def _select_named(self, name, path=None):
        if path and self._select_path(path):
            return True
        self._finish_fill()
        lowered = str(name).lower()
        for index, entry in enumerate(self.entries):
            if entry['name'].lower() == lowered:
                self.list.SetItemState(
                    index, wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                    wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED)
                self.list.EnsureVisible(index)
                return True
        return False

    def selected_count(self):
        """How many are selected, without walking the selection to count."""
        try:
            return self.list.GetSelectedItemCount()
        except Exception:
            return 0

    def selected_entries(self):
        if self.list is None:
            return []
        # Everything selected is what Ctrl+A leaves, and asking the control
        # for each of thirty thousand rows in turn to be told what we already
        # have is the walk this avoids.
        if self.selected_count() >= len(self.entries) > 0:
            return list(self.entries)
        entries = []
        index = self.list.GetFirstSelected()
        while index != -1:
            if 0 <= index < len(self.entries):
                entries.append(self.entries[index])
            index = self.list.GetNextSelected(index)
        return entries

    def selected_entry(self):
        entries = self.selected_entries()
        return entries[0] if entries else None

    def select_all(self):
        field = self.text_focus()
        if field is not None:
            field.SetSelection(-1, -1)
            return True
        self._select_every_item()
        self._status_update.request()
        return True

    def _select_every_item(self):
        """Select the lot - in one message, where Windows will take one.

        A list view reads -1 as "every item", which is a single message
        rather than one per row; the loop is what happens where that is
        refused.
        """
        self._finish_fill()
        count = self.list.GetItemCount()
        if count <= 0:
            return False
        state = wx.LIST_STATE_SELECTED
        try:
            if self.list.SetItemState(-1, state, state):
                return True
        except Exception:
            pass
        self.list.Freeze()
        try:
            for index in range(count):
                self.list.SetItemState(index, state, state)
        finally:
            self.list.Thaw()
        return True

    def invert_selection(self):
        self._finish_fill()
        self.list.Freeze()
        try:
            for index in range(self.list.GetItemCount()):
                selected = self.list.GetItemState(index,
                                                  wx.LIST_STATE_SELECTED)
                self.list.SetItemState(
                    index, 0 if selected else wx.LIST_STATE_SELECTED,
                    wx.LIST_STATE_SELECTED)
        finally:
            self.list.Thaw()
        self._status_update.request()
        return True

    def _on_selection_changed(self, event):
        # One event per selected file arrives here; the bar is worked out
        # once, when they have stopped coming.
        self._status_update.request()
        event.Skip()

    def _on_column_click(self, event):
        column = event.GetColumn()
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self.sort_entries()

    def sort_entries(self, column=None, reverse=None):
        """Sort by a column, folders staying above files as Explorer does."""
        if column is not None:
            self._sort_column = column
        if reverse is not None:
            self._sort_reverse = bool(reverse)
        index = self._sort_column

        def key(entry):
            if is_computer(self.location):
                values = [entry['name'].lower(), type_name_of(entry),
                          entry.get('total') or 0, entry.get('free') or 0]
            else:
                values = [entry['name'].lower(), entry.get('size') or 0,
                          type_name_of(entry), entry.get('modified') or 0]
            return values[index] if 0 <= index < len(values) \
                else entry['name'].lower()

        folders = [entry for entry in self.entries
                   if entry['kind'] in ('folder', 'drive')]
        files = [entry for entry in self.entries if entry['kind'] == 'file']
        folders.sort(key=key, reverse=self._sort_reverse)
        files.sort(key=key, reverse=self._sort_reverse)
        self.entries = folders + files
        self._fill_list()
        self._focus_first()
        return True

    # ------------------------------------------------------------------
    # Commands on what is in the list
    # ------------------------------------------------------------------
    # Where the keyboard is decides what a command acts on: the file list,
    # the folders bar, or the text in the address field.  Without this a
    # command bound to a key would act on the selected files while the user
    # was typing somewhere else in the window.
    def text_focus(self):
        """The address field, when it is what has the keyboard."""
        focused = wx.Window.FindFocus()
        if focused is None:
            return None
        if focused is self.address:
            return self.address
        try:
            if self.address.IsDescendant(focused):
                return self.address
        except Exception:
            pass
        return None

    def editing_label(self):
        """True while a name is being typed over an item in place."""
        for control in (self.list, self.tree):
            try:
                if control is not None and control.GetEditControl() is not None:
                    return True
            except Exception:
                continue
        return False

    def tree_has_focus(self):
        focused = wx.Window.FindFocus()
        return focused is self.tree

    def open_selected(self):
        if self.text_focus() is not None:
            self._on_address_enter(None)
            return True
        if self.tree_has_focus():
            location = self.tree_location()
            if location:
                return self.navigate(location)
        entry = self.selected_entry()
        if not entry:
            edge_cue()
            return False
        if entry['kind'] in ('folder', 'drive'):
            return self.navigate(entry['path'])
        win_shell.open_path(entry['path'])
        return True

    def new_folder(self):
        if is_computer(self.location):
            edge_cue()
            return False
        path = win_shell.make_directory(self.location, _("New Folder"))
        if not path:
            return False
        self.refresh()
        if self._select_path(path):
            self.rename_selected()
        return True

    def create_shortcut(self):
        entry = self.selected_entry()
        if not entry or is_computer(self.location):
            edge_cue()
            return False
        if win_shell.create_shortcut(entry['path'], self.location):
            self.refresh()
            return True
        return False

    def rename_selected(self):
        if self.text_focus() is not None or self.editing_label():
            return False
        if self.tree_has_focus():
            item = self.tree.GetSelection()
            if item and item.IsOk() and self.tree_location():
                self.tree.EditLabel(item)
                return True
            edge_cue()
            return False
        if is_computer(self.location):
            edge_cue()
            return False
        index = self.list.GetFirstSelected()
        if index < 0:
            edge_cue()
            return False
        self.list.EditLabel(index)
        return True

    def _on_rename_done(self, event):
        if event.IsEditCancelled():
            return
        index = event.GetIndex()
        if not (0 <= index < len(self.entries)):
            return
        entry = self.entries[index]
        new_name = event.GetLabel().strip()
        if not new_name or new_name == entry['name']:
            return
        new_path = os.path.join(os.path.dirname(entry['path']), new_name)
        try:
            os.rename(entry['path'], new_path)
            entry['path'] = new_path
            entry['name'] = new_name
            if self.list.IsVirtual():
                # A virtual list draws what it was told when it asked; the
                # row has to be asked again for it to show the new name.
                self.list.RefreshItem(index)
        except Exception as error:
            print(f"[TitanShell] rename failed: {error}")
            event.Veto()
            wx.MessageBox(_("The item could not be renamed."),
                          location_name(self.location),
                          wx.OK | wx.ICON_ERROR, self)

    def delete_selected(self):
        if self.text_focus() is not None or self.editing_label():
            # Delete belongs to the text being typed, not to the files.
            return False
        if self.tree_has_focus():
            location = self.tree_location()
            if not location:
                edge_cue()
                return False
            if win_shell.recycle([str(location)]):
                self._build_tree_roots()
                return self.refresh()
            return False
        entries = self.selected_entries()
        if not entries or is_computer(self.location):
            edge_cue()
            return False
        if win_shell.recycle([entry['path'] for entry in entries]):
            self.refresh()
            return True
        return False

    def copy_selection(self, cut=False):
        """Ctrl+C / Ctrl+X - on the text when the address field has it."""
        field = self.text_focus()
        if field is not None:
            field.Cut() if cut else field.Copy()
            return True
        if self.tree_has_focus():
            location = self.tree_location()
            if location:
                paths = [str(location)]
                if not fileops.copy_to_clipboard(paths, cut=cut):
                    return False
                self._cut_paths = paths if cut else []
                return True
        entries = self.selected_entries()
        if not entries:
            edge_cue()
            return False
        paths = [entry['path'] for entry in entries]
        if not fileops.copy_to_clipboard(paths, cut=cut):
            return False
        self._cut_paths = paths if cut else []
        return True

    def paste(self):
        field = self.text_focus()
        if field is not None:
            field.Paste()
            return True
        if is_computer(self.location):
            edge_cue()
            return False
        paths, move = fileops.clipboard_files(self._cut_paths)
        if not paths:
            edge_cue()
            return False
        if win_shell.file_operation(paths, self.location, move=move):
            self._cut_paths = []
            self.refresh()
            return True
        return False

    def show_properties(self):
        """Windows' own property sheet, owned by this window.

        Given an owner, or with Explorer's bar hidden the sheet comes up
        behind everything on the screen.
        """
        entry = self.selected_entry()
        if entry:
            target = entry['path']
        elif is_computer(self.location):
            target = ''
        else:
            target = self.location
        if not target:
            edge_cue()
            return False
        try:
            owner = self.GetHandle()
        except Exception:
            owner = 0
        return win_shell.show_properties(target, owner)

    def show_about(self):
        wx.MessageBox(
            _("The Titan file browser: My Computer, drives and folders, "
              "readable with the keyboard and with a screen reader."),
            _("About"), wx.OK | wx.ICON_INFORMATION, self)

    # ------------------------------------------------------------------
    # The bars
    # ------------------------------------------------------------------
    def show_toolbar(self, shown):
        self.toolbar.Show(bool(shown))
        self.Layout()
        return True

    def show_status_bar(self, shown):
        self.status.Show(bool(shown))
        self.Layout()
        return True

    def show_folders(self, shown):
        """The Folders bar: the toolbar button and the View entry, as one."""
        self._folders_shown = bool(shown)
        if shown and not self.splitter.IsSplit():
            self.tree.Show()
            self.splitter.SplitVertically(self.tree, self.list_holder, 200)
        elif not shown and self.splitter.IsSplit():
            self.splitter.Unsplit(self.tree)
        self.menu_folders.Check(bool(shown))
        try:
            self.toolbar.ToggleTool(self.ID_FOLDERS, bool(shown))
        except Exception:
            pass
        self._remember('explorer_folders', bool(shown))
        return True

    def set_view(self, view):
        if view not in _VIEW_STYLES:
            return False
        self.view = view
        self._make_list()
        self._fill_list()
        self._focus_first()
        self.list.SetFocus()
        self._remember('explorer_view', view)
        return True

    def set_show_hidden(self, shown):
        self.show_hidden = bool(shown)
        self._remember('explorer_show_hidden', bool(shown))
        self._build_tree_roots()
        return self.refresh()

    @staticmethod
    def _remember(key, value):
        try:
            from src.settings.settings import set_setting
            set_setting(key, str(value), 'titan_shell')
        except Exception as error:
            print(f"[TitanShell] could not save {key}: {error}")

    def _on_views_tool(self, event):
        """The Views button, which in Explorer drops the four views down."""
        menu = wx.Menu()
        for view, label in ((VIEW_LARGE, _("Large Icons")),
                            (VIEW_SMALL, _("Small Icons")),
                            (VIEW_LIST, _("List")),
                            (VIEW_DETAILS, _("Details"))):
            item = menu.AppendRadioItem(wx.ID_ANY, label)
            item.Check(view == self.view)
            self.Bind(wx.EVT_MENU,
                      lambda event, chosen=view: self.set_view(chosen), item)
        self.PopupMenu(menu)
        menu.Destroy()

    # ------------------------------------------------------------------
    # The address band
    # ------------------------------------------------------------------
    def _update_address(self):
        text = _("My Computer") if is_computer(self.location) \
            else str(self.location)
        self.address.SetValue(text)
        if self.address.FindString(text) == wx.NOT_FOUND:
            self.address.Append(text)

    def _on_address_enter(self, event):
        """What was typed: a place to go, or something to run.

        Explorer's address bar does both, and so does this - a path is
        opened here, and anything else is handed to `ShellExecute` exactly
        as the Run dialog hands it.
        """
        text = self.address.GetValue().strip()
        if not text:
            return
        if text == _("My Computer"):
            self.navigate(COMPUTER)
            return
        expanded = os.path.expandvars(os.path.expanduser(text))
        if os.path.isdir(expanded):
            self.navigate(expanded)
            return
        if os.path.isfile(expanded):
            win_shell.open_path(expanded)
            return
        if not win_shell.shell_execute(text):
            wx.MessageBox(
                _("Windows cannot find {name}. Check the spelling and try "
                  "again.").format(name=text), _("My Computer"),
                wx.OK | wx.ICON_ERROR, self)

    def _select_in_tree(self, location):
        """Put the folders bar on the place the list is showing."""
        if not self._folders_shown or not self.tree.IsShown():
            return False
        root = self.tree.GetRootItem()
        if not root.IsOk():
            return False
        found = self._find_in_tree(root, str(location))
        if found is None:
            return False
        self.tree.SelectItem(found)
        self.tree.EnsureVisible(found)
        return True

    def _find_in_tree(self, parent, location):
        wanted = os.path.normcase(location)
        item, cookie = self.tree.GetFirstChild(parent)
        while item.IsOk():
            data = self.tree.GetItemData(item)
            if data is not None and os.path.normcase(str(data)) == wanted:
                return item
            if self.tree.IsExpanded(item):
                found = self._find_in_tree(item, location)
                if found is not None:
                    return found
            item, cookie = self.tree.GetNextChild(parent, cookie)
        return None

    # ------------------------------------------------------------------
    # The status bar
    # ------------------------------------------------------------------
    def status_texts(self):
        """The three panes as text - what the status bar is told to say."""
        count = len(self.entries)
        selected = self.selected_entries() if self.list else []
        if selected:
            first = _("{count} of {total} selected").format(
                count=len(selected), total=count)
            total = sum(entry.get('size') or 0 for entry in selected)
        else:
            first = _("{count} object(s)").format(count=count)
            total = sum(entry.get('size') or 0 for entry in self.entries)
        return [first, format_size(total), location_name(self.location)]

    def _update_status(self):
        for index, text in enumerate(self.status_texts()):
            self.status.SetStatusText(text, index)

    def _update_title(self):
        self.SetTitle(location_name(self.location))

    def _update_commands(self):
        """Grey out what cannot be done here, rather than failing later."""
        computer = is_computer(self.location)
        for item in (self.menu_new_folder, self.menu_paste, self.menu_rename,
                     self.menu_delete, self.menu_shortcut):
            item.Enable(not computer)
        can_back = self._history_index > 0
        can_forward = self._history_index < len(self._history) - 1
        can_up = parent_location(self.location) is not None
        self.menu_back.Enable(can_back)
        self.menu_forward.Enable(can_forward)
        self.menu_up.Enable(can_up)
        try:
            self.toolbar.EnableTool(wx.ID_BACKWARD, can_back)
            self.toolbar.EnableTool(wx.ID_FORWARD, can_forward)
            self.toolbar.EnableTool(self.ID_UP, can_up)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Menus on an item and on the background
    # ------------------------------------------------------------------
    def _on_item_menu(self, event):
        index = event.GetIndex()
        if not (0 <= index < len(self.entries)):
            return
        self._popup([
            (_("&Open"), self.open_selected),
            (None, None),
            (_("Cu&t"), lambda: self.copy_selection(cut=True)),
            (_("&Copy"), self.copy_selection),
            (_("Create &shortcut"), self.create_shortcut),
            (_("&Delete"), self.delete_selected),
            (_("Rena&me"), self.rename_selected),
            (None, None),
            (_("P&roperties"), self.show_properties),
        ])

    def _on_background_menu(self, event):
        self._popup([
            (_("&Refresh"), self.refresh),
            (None, None),
            (_("&Paste"), self.paste),
            (_("Ne&w folder"), self.new_folder),
            (None, None),
            (_("P&roperties"), self.show_properties),
        ])

    def _popup(self, entries):
        menu = wx.Menu()
        for label, handler in entries:
            if label is None:
                menu.AppendSeparator()
                continue
            item = menu.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda event, call=handler: call(), item)
        self.PopupMenu(menu)
        menu.Destroy()

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def _on_char_hook(self, event):
        """Every key Explorer answers, routed by where the keyboard is.

        The char hook rather than accelerators, because a menu accelerator
        fires wherever the focus happens to be: Del would delete the
        selected files while a name was being typed over an icon, and Enter
        in the address field would open the selection instead of going to
        what was typed.  Here the window can ask first.
        """
        key = event.GetKeyCode()
        typing = self.text_focus() is not None
        renaming = self.editing_label()

        if renaming:
            # The keyboard belongs to the edit box: Enter commits, Escape
            # cancels, Delete deletes a character.  None of it is ours.
            event.Skip()
            return

        if key == wx.WXK_F4 and event.AltDown():
            # A browser window is a window with something in it, so Alt+F4
            # here really does close it - unlike the taskbar and the desktop,
            # where it means the Shut Down dialog.
            self.Close()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and event.AltDown():
            self.show_properties()
            return
        if key == wx.WXK_LEFT and event.AltDown():
            self.go_back()
            return
        if key == wx.WXK_RIGHT and event.AltDown():
            self.go_forward()
            return
        if key == wx.WXK_UP and event.AltDown():
            self.go_up()
            return
        if key == wx.WXK_F5:
            self.refresh()
            return
        if key == wx.WXK_F6:
            # Explorer's own "next pane": the address, the folders bar, the
            # list, and round again.
            self._next_pane(-1 if key_state.shift_down(event) else 1)
            return

        if typing:
            # In the address field the keys are the field's own: Delete
            # deletes a character, Backspace goes back a character, and
            # nothing here touches a file.  Enter goes where it says, and
            # Escape gives the keyboard back to the list.
            if key == wx.WXK_ESCAPE:
                self.list.SetFocus()
                return
            if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                self._on_address_enter(None)
                return
            event.Skip()
            return

        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.open_selected()
            return
        if key == wx.WXK_BACK:
            self.go_up()
            return
        if key == wx.WXK_DELETE:
            self.delete_selected()
            return
        if key == wx.WXK_F2:
            self.rename_selected()
            return
        if key == wx.WXK_F4 or (event.AltDown() and key == ord('D')):
            # Explorer's own two ways into the address band: F4 drops it
            # open, Alt+D puts the keyboard in it.
            self.address.SetFocus()
            self.address.SelectAll()
            if key == wx.WXK_F4:
                try:
                    self.address.Popup()
                except Exception:
                    pass
            return
        if event.ControlDown() and not event.AltDown():
            if key in (ord('C'), ord('X')):
                self.copy_selection(cut=(key == ord('X')))
                return
            if key == ord('V'):
                self.paste()
                return
            if key == ord('A'):
                self.select_all()
                return
        event.Skip()

    def panes(self):
        panes = [self.address]
        if self._folders_shown and self.tree.IsShown():
            panes.append(self.tree)
        panes.append(self.list)
        return panes

    def _next_pane(self, direction):
        panes = self.panes()
        focused = wx.Window.FindFocus()
        index = 0
        for position, pane in enumerate(panes):
            if pane is focused or (focused is not None and
                                   pane.IsDescendant(focused)):
                index = position
                break
        panes[(index + direction) % len(panes)].SetFocus()

    def _on_window_activate(self, event):
        handover.follows_activation(event)
        event.Skip()

    def _on_close(self, event):
        # Nothing queued may fire into a window that is going.  The guarded
        # calls would drop themselves anyway, but a folder still being read
        # on a worker is made stale here so its answer is never applied, and
        # a fill still arriving in blocks stops where it is.
        self._read_token += 1
        self._fill_token += 1
        self._fill_from = None
        try:
            self._status_update.cancel()
        except Exception:
            pass
        _forget(self)
        event.Skip()


# --------------------------------------------------------------------------- #
# Opening one
# --------------------------------------------------------------------------- #
_frames = []


def _forget(frame):
    if frame in _frames:
        _frames.remove(frame)


def open_windows():
    """Every browser window that is open, oldest first."""
    for frame in list(_frames):
        if not alive(frame):
            _forget(frame)
    return list(_frames)


def open_explorer(path=None, parent=None, new_window=False):
    """Open the file browser at a place, reusing the window already up.

    XP opens one folder into one window by default, and so does this: a
    second request goes to the window that is already there unless a new
    one was asked for.  Returns the frame.
    """
    location = COMPUTER if path in (None, '', COMPUTER) else str(path)
    if not new_window:
        for frame in reversed(list(_frames)):
            # A window destroyed by something other than its own Close -
            # Titan exiting, its parent going - never ran `_on_close`, so
            # the list can hold one whose C++ side has gone.  Asking it
            # anything raises `RuntimeError`, which is how it is recognised.
            if not alive(frame):
                _forget(frame)
                continue
            try:
                frame.navigate(location)
                frame.Show()
                frame.Raise()
                frame.list.SetFocus()
                return frame
            except RuntimeError:
                _forget(frame)
            except Exception as error:
                print(f"[TitanShell] could not reuse a browser window: "
                      f"{error}")
    frame = ExplorerFrame(parent, location)
    _frames.append(frame)
    frame.Show()
    frame.Raise()
    try:
        frame.list.SetFocus()
    except Exception:
        pass
    return frame
