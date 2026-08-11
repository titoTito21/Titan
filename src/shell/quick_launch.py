# -*- coding: utf-8 -*-
"""
The Quick Launch band.

ReactOS' taskbar is a rebar with bands in it, and the first band is
`CQuickLaunchBand` (`base/shell/rshell/CQuickLaunchBand.cpp`) - a toolbar
over the shell folder `%APPDATA%\\Microsoft\\Internet Explorer\\Quick Launch`.
Titan's bar had the *name* of that group but only one button in it (Show
Desktop), which meant the row of one-click launchers that is half the point
of an XP taskbar was simply missing.

This is that band: whatever is in the folder, in the order Explorer shows it,
each with its **real** icon (`SHGetFileInfo`, so a shortcut shows what it
points at) and each opened the way a double click would open it.  The
folder is the real one, so anything the user drags into it in Explorer -
or anything an installer puts there - appears on Titan's bar too.

Show Desktop stays at the end of the band whether or not the folder has the
`.scf` file XP kept there, because on a machine that has never had Explorer's
quick launch turned on the folder is empty or absent, and the one button that
must always be reachable is that one.
"""

import os

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import luna, win_shell
from src.shell.controls import ShellControl, bitmap_from_icon_handle
from src.titan_core.translation import _

# The button is square: XP's quick launch shows the icon and no text.
BUTTON_WIDTH = 24
ICON_SIZE = 16

# Matched on the *file* name, never on the displayed one, because the
# displayed one is translated: `Shows Desktop.lnk` is "Pokaz pulpit" on a
# Polish Windows and would slip through a list written in English.
#
# The two Windows puts there itself are left out because Titan already has
# both, and a band with two buttons that say the same thing is worse than a
# band with one: Show Desktop is at the end of the notification area, where
# ReactOS' `CTrayShowDesktopButton` puts it, and the window switcher is
# Titan's own.  Anything the user or an installer put in the folder appears.
SKIP_NAMES = ('desktop.ini', 'thumbs.db', 'show desktop.scf',
              'shows desktop.lnk', 'window switcher.lnk')


def quick_launch_folder():
    """The real Quick Launch folder, or None where there is not one."""
    if not IS_WINDOWS:
        return None
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return None
    folder = os.path.join(appdata, 'Microsoft', 'Internet Explorer',
                          'Quick Launch')
    return folder if os.path.isdir(folder) else None


def quick_launch_items():
    """What is in the band, as [{'name', 'path'}].

    Sorted by name, which is what an XP quick launch looks like once the
    user has never reordered it; the order Explorer remembers lives in a
    binary registry stream that is not worth reading to put four icons in a
    different order.
    """
    folder = quick_launch_folder()
    if not folder:
        return []
    items = []
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except Exception as error:
        print(f"[TitanShell] could not read the quick launch folder: {error}")
        return []
    for name in names:
        if name.lower() in SKIP_NAMES:
            continue
        if name.lower().endswith('.ini'):
            continue
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            continue
        items.append({'name': win_shell.file_display_name(path),
                      'path': path})
    return items


class QuickLaunchButton(ShellControl):
    """One launcher: its real icon, its name spoken, one press to open it."""

    def __init__(self, parent, item):
        super().__init__(parent, size=(BUTTON_WIDTH, -1),
                         name=item.get('name') or _("Quick Launch"))
        self.item = item
        self.accessible_action = _("Open")
        self.set_tooltip(self.accessible_name)
        self._icon = None
        self._load_icon()

    def _load_icon(self):
        handle = win_shell.file_icon_handle(self.item['path'], large=False)
        self._icon = bitmap_from_icon_handle(handle, ICON_SIZE)

    def update(self, item):
        """Point the button at another launcher, keeping the focus on it."""
        self.item = item
        name = item.get('name') or _("Quick Launch")
        if name != self.accessible_name:
            self.accessible_name = name
            self.refresh_accessible_name()
            self.set_tooltip(name)
        self._load_icon()
        self.Refresh()

    def paint(self, dc, rect):
        luna.draw_task_button(dc, wx.Rect(0, 3, rect.width - 2,
                                          rect.height - 6),
                              self.palette, state=self.state_name(),
                              focused=self.HasFocus())
        if self._icon is not None and self._icon.IsOk():
            dc.DrawBitmap(self._icon,
                          (rect.width - self._icon.GetWidth()) // 2,
                          (rect.height - self._icon.GetHeight()) // 2, True)
        else:
            # No icon rather than a letter standing in for one: a character
            # in an icon's place is read out as that character.
            dc.SetPen(wx.Pen(self.palette['task_text']))
            dc.SetBrush(wx.TRANSPARENT_BRUSH)
            dc.DrawRectangle((rect.width - ICON_SIZE) // 2,
                             (rect.height - ICON_SIZE) // 2,
                             ICON_SIZE, ICON_SIZE)

    def shell_activate(self):
        win_shell.open_path(self.item['path'])

    def show_context_menu(self):
        """What Explorer offers for a quick launch button."""
        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("&Open"))
        folder_item = menu.Append(wx.ID_ANY, _("Open the &folder"))
        menu.AppendSeparator()
        delete_item = menu.Append(wx.ID_ANY, _("&Delete"))
        properties = menu.Append(wx.ID_ANY, _("P&roperties"))

        self.Bind(wx.EVT_MENU,
                  lambda event: win_shell.open_path(self.item['path']),
                  open_item)
        self.Bind(wx.EVT_MENU,
                  lambda event: win_shell.open_path(quick_launch_folder()
                                                    or ''),
                  folder_item)
        self.Bind(wx.EVT_MENU, lambda event: self._delete(), delete_item)
        self.Bind(wx.EVT_MENU,
                  lambda event: win_shell.show_properties(self.item['path']),
                  properties)

        self.PopupMenu(menu)
        menu.Destroy()

    def _delete(self):
        answer = wx.MessageBox(
            _("Remove \"{name}\" from Quick Launch?").format(
                name=self.accessible_name),
            _("Quick Launch"), wx.YES_NO | wx.ICON_QUESTION, self)
        if answer != wx.YES:
            return
        if win_shell.recycle([self.item['path']], confirm=False):
            parent = self.GetParent()
            refresh = getattr(parent, 'refresh_quick_launch', None)
            if refresh is None:
                refresh = getattr(getattr(parent, 'taskbar', None),
                                  'refresh_quick_launch', None)
            if refresh is not None:
                wx.CallAfter(refresh)
