# -*- coding: utf-8 -*-
"""
The reference shell add-on: one function per surface, doing the smallest
honest thing on each.

Every function here is optional.  A shell add-on that only wants one entry
in the desktop's menu writes `desktop_menu_items` and nothing else - Titan
asks for what is there and skips what is not.

Every one of them is handed `api` first (`src/shell/addons.py`'s
`ShellAddonAPI`), then whatever the surface is about, and answers with a
list of entries:

    {'id': 'something', 'label': "What it says", 'action': callable}

`action` takes no arguments and runs on the GUI thread, because that is
where menus, toolbars and lists live.  Anything slow belongs on a thread of
the add-on's own.
"""

import os

import wx

# Titan's own translation, so an add-on speaks the user's language with no
# catalogue of its own.  A `.mo` beside the add-on would be the way to add
# words Titan does not already have.
try:
    from src.titan_core.translation import _
except Exception:                                    # pragma: no cover
    def _(text):
        return text


# --------------------------------------------------------------------------
# The shell itself
# --------------------------------------------------------------------------
def setup(api):
    """Called once, when the add-on is loaded."""
    api.log("loaded")


def on_shell_start(api, shell):
    """The shell is up: its desktop, bar and Start menu exist.

    Called on a worker thread, so anything that touches a window has to go
    through `wx.CallAfter`.
    """
    api.log("the shell is up")


def on_shell_stop(api, shell):
    """The shell is going away - take down anything of ours that is left."""
    api.log("the shell is going away")


# --------------------------------------------------------------------------
# The Start menu (both of them - XP and classic are built from one list)
# --------------------------------------------------------------------------
def start_menu_items(api, menu):
    """Entries for the left column, at the end of it.

    An entry with `children` becomes a branch that opens where it stands
    instead of a line of its own, which is how an add-on with several
    commands adds one entry rather than several.
    """
    def open_folder():
        from src.shell import explorer
        explorer.open_explorer(os.path.expanduser('~'))

    def say_hello():
        api.speak(_("Hello from the example shell add-on"))

    return [
        {'id': 'home', 'label': _("Example: my home folder"),
         'action': open_folder},
        {'id': 'more', 'label': _("Example add-on"),
         'children': [
             {'id': 'hello', 'label': _("Say hello"), 'action': say_hello},
             {'id': 'settings', 'label': _("Titan settings"),
              'action': lambda: api.run_action('titan', 'open_settings')},
         ]},
    ]


# --------------------------------------------------------------------------
# The file browser
# --------------------------------------------------------------------------
def explorer_menu_items(api, browser):
    """Commands for the browser's Tools menu, which exists because of these."""
    def where_am_i():
        wx.MessageBox(str(browser.location), _("Example add-on"),
                      wx.OK | wx.ICON_INFORMATION, browser)

    return [{'id': 'where', 'label': _("Where am I?"), 'action': where_am_i}]


def explorer_toolbar_items(api, browser):
    """A button on the band, with its text showing - never a picture alone."""
    return [{'id': 'up_twice', 'label': _("Up twice"),
             'help': _("Go up two folders at once"),
             'art': wx.ART_GO_DIR_UP,
             'action': lambda: (browser.go_up(), browser.go_up())}]


def explorer_context_items(api, browser, where, selection):
    """Commands on the menu of an item, or of the folder's background.

    `where` is 'item' or 'background', and `selection` is what the menu is
    about - so this is Windows' context-menu handler, and an add-on can
    offer a command for THIS file rather than a command in general.
    """
    if where != 'item' or not selection:
        return []
    entry = selection[0]
    path = entry.get('path') or ''
    if not path:
        return []

    def copy_path():
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(path))
            finally:
                wx.TheClipboard.Close()

    return [{'id': 'copy_path', 'label': _("Copy the full path"),
             'action': copy_path}]


def explorer_columns(api, browser, location):
    """A column of the add-on's own, in the details view.

    Asked once per folder; `value` is then called per row, out of the entry
    that is already in hand - the view is a virtual list, so a column that
    went and asked Windows something per row would undo what makes a folder
    of three thousand files open in milliseconds.
    """
    # My Computer is drives, not files - there is no extension to show.
    # (`browser.is_virtual()` is about the LIST being a virtual control,
    # which is the normal case, and asking that here is the mistake this
    # comment exists to stop somebody repeating.)
    from src.shell.explorer import is_computer
    if is_computer(location):
        return []

    def extension(entry):
        name = entry.get('name') or ''
        if entry.get('directory'):
            return ''
        return os.path.splitext(name)[1].lstrip('.').upper()

    return [{'id': 'extension', 'label': _("Extension"), 'width': 90,
             'value': extension}]


# --------------------------------------------------------------------------
# The taskbar
# --------------------------------------------------------------------------
def taskbar_bands(api, taskbar):
    """A control of our own on the bar - what Windows calls a deskband.

    It is built in the notification area, so it is a real child window of
    the bar: focusable with Tab and the arrows like everything else there,
    and named, so a screen reader says what it is.
    """
    def make(parent):
        from src.shell.controls import TextControl
        control = TextControl(parent, _("Example"))
        return control

    return [{'id': 'band', 'label': _("Example band"), 'width': 70,
             'control': make}]


def taskbar_menu_items(api, taskbar):
    """Entries on the bar's own menu, after Titan's."""
    return [{'id': 'refresh', 'label': _("Example: refresh the bar"),
             'action': taskbar.refresh_windows}]


# --------------------------------------------------------------------------
# The desktop
# --------------------------------------------------------------------------
def desktop_menu_items(api, desktop, where, entry):
    """Entries on the desktop's menus.

    `where` is 'item' (an icon was right-clicked) or 'background'.
    """
    if where == 'background':
        return [{'id': 'count', 'label': _("Example: how many icons?"),
                 'action': lambda: api.speak(
                     _("{count} icons on the desktop").format(
                         count=len(desktop.entries)))}]
    name = (entry or {}).get('name') or ''
    if not name:
        return []
    return [{'id': 'say', 'label': _("Example: say the name"),
             'action': lambda: api.speak(name)}]

