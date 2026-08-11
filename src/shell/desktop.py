# -*- coding: utf-8 -*-
"""
The desktop: the icons, the wallpaper and the menu you get by right-clicking
the background.

It is a real `SysListView32` in icon mode - the same control the Windows
desktop is - which is both the faithful choice and the accessible one: every
screen reader on the machine already knows how to read a list view, the
arrow keys, first-letter jumping, rubber-band selection and icon dragging all
come from the control itself, and Titan does not have to reimplement any of
it (or get it subtly wrong).

It is laid out as a **grid**, the way a desktop is and not the way a list is:
`LVS_ALIGN_LEFT` fills a column from the top of the screen downwards and then
starts the next one - which is what puts My Computer above the Recycle Bin
rather than beside it - and `LVS_EX_SNAPTOGRID` keeps every icon on the grid
however it was dragged.  With `LVS_ALIGN_TOP`, which is wxWidgets' default,
the icons ran across the top of the screen in one line instead.

What Titan adds on top is the shell behaviour: which folders the items come
from, the real Windows icon for each one, Enter to open, F2 to rename, Delete
to the Recycle Bin, the two context menus, and remembering where the user
dragged an icon to.
"""

import json
import os

import wx

from src.platform_utils import IS_WINDOWS, get_user_data_dir
from src.shell import luna, win_shell
from src.shell.a11y import shell_setting
from src.titan_core.translation import _

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    LVM_FIRST = 0x1000
    LVM_SETICONSPACING = LVM_FIRST + 53
    LVM_SETEXTENDEDLISTVIEWSTYLE = LVM_FIRST + 54
    LVS_EX_SNAPTOGRID = 0x00080000
    LVS_EX_DOUBLEBUFFER = 0x00010000
    # The two window styles ReactOS' CDefView gives the desktop view:
    # aligned left (columns, filled downwards) and auto arranged.
    LVS_ALIGNLEFT = 0x0800
    LVS_ALIGNTOP = 0x0000
    LVS_ALIGNMASK = 0x0C00
    LVS_AUTOARRANGE = 0x0100
    GWL_STYLE = -16
    SM_CXICONSPACING = 13
    SM_CYICONSPACING = 14
    LVM_SETBKIMAGEW = LVM_FIRST + 138
    LVM_SETTEXTBKCOLOR = LVM_FIRST + 38
    LVM_SETTEXTCOLOR = LVM_FIRST + 36
    LVM_SETBKCOLOR = LVM_FIRST + 1
    LVBKIF_SOURCE_URL = 0x00000002
    LVBKIF_STYLE_TILE = 0x00000010
    LVBKIF_STYLE_NORMAL = 0x00000000
    CLR_NONE = 0xFFFFFFFF

    class LVBKIMAGEW(ctypes.Structure):
        _fields_ = [
            ('ulFlags', wintypes.ULONG),
            ('hbm', ctypes.c_void_p),
            ('pszImage', wintypes.LPWSTR),
            ('cchImageMax', wintypes.UINT),
            ('xOffsetPercent', ctypes.c_int),
            ('yOffsetPercent', ctypes.c_int),
        ]


ICON_SIZE = 32
# The cell one icon and its caption sit in.  XP's own, at 96 dpi: wide enough
# for two lines of a file name, tall enough that the captions do not touch.
GRID_CELL_WIDTH = 76
GRID_CELL_HEIGHT = 88


class DesktopFrame(wx.Frame):
    """The window that owns the whole screen and sits under everything."""

    def __init__(self, shell, parent=None):
        super().__init__(parent, title=_("Desktop"),
                         style=wx.FRAME_NO_TASKBAR | wx.BORDER_NONE)
        self.shell = shell
        self.palette = luna.get_palette()
        self.SetName(_("Desktop"))

        self.items = []            # [{'name','path','type'}]
        self._image_list = None
        self._positions = self._load_positions()

        self.list = wx.ListCtrl(
            self, style=wx.LC_ICON | wx.LC_SINGLE_SEL | wx.LC_ALIGN_LEFT
            | wx.NO_BORDER | wx.WANTS_CHARS)
        self.list.SetName(_("Desktop icons"))
        self._apply_grid()

        self._apply_look()
        self.refresh()

        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        self.list.Bind(wx.EVT_LIST_END_LABEL_EDIT, self._on_rename)
        self.list.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_item_menu)
        # Dragging an icon somewhere else is the one desktop behaviour the
        # list view does not do by itself: it reports the start of a drag and
        # leaves the rest to the program, exactly as Explorer does.
        self._dragging = -1
        self.list.Bind(wx.EVT_LIST_BEGIN_DRAG, self._on_begin_drag)
        self.list.Bind(wx.EVT_LEFT_UP, self._on_drop)
        self.list.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)
        self.list.Bind(wx.EVT_CONTEXT_MENU, self._on_background_menu)
        self.list.Bind(wx.EVT_KEY_DOWN, self._on_key)
        # Tab and Shift+Tab leave the desktop for the bar, the way they do on
        # Windows: the desktop, the Start button and the notification area are
        # the stops of one round trip.  A char hook and not a key handler,
        # because the list view eats Tab to move between its own items.
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    def cover_screen(self):
        """Fill the screen and go to the bottom of the z-order.

        A desktop that can come to the front is not a desktop; every other
        window has to be able to sit on top of it, so it is pushed to the
        bottom and shown without taking the focus.
        """
        width, height = win_shell.screen_size()
        self.SetSize(0, 0, width, height)
        self.list.SetSize(0, 0, width, height)
        try:
            self.ShowWithoutActivating()
        except Exception:
            self.Show()
        self.send_to_back()
        # Now that the desktop really is the screen, the grid is worth
        # working out: until this point a column was a few pixels tall.
        self.layout_grid()

    def send_to_back(self):
        if not IS_WINDOWS:
            return
        try:
            HWND_BOTTOM = 1
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
            win_shell.user32.SetWindowPos(
                self.GetHandle(), HWND_BOTTOM, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def _on_size(self, event):
        try:
            self.list.SetSize(0, 0, *self.GetSize())
        except Exception:
            pass
        # A column holds as many icons as the screen is tall, so the grid is
        # worked out again whenever that changes.
        try:
            self.layout_grid()
        except Exception:
            pass
        event.Skip()

    def _apply_grid(self):
        """Make the list view behave as a desktop rather than as a list.

        Windows has both behaviours in the one control, and ReactOS'
        `CDefView::CreateList` picks the desktop one with three flags:
        `LVS_ALIGNLEFT` (columns, filled downwards), `LVS_AUTOARRANGE` and
        `LVS_EX_SNAPTOGRID`.  The styles are set on the window itself rather
        than left to wxWidgets, because wx only translates the alignment
        flag it was given at construction and never the auto-arrange one -
        and a list view without `LVS_AUTOARRANGE` puts every item it is
        given wherever there is room at that moment, which is what turned
        the desktop into a row of icons along the top of the screen.
        """
        if not IS_WINDOWS:
            return
        hwnd = self.list.GetHandle()
        try:
            win_shell.user32.SendMessageW(
                hwnd, LVM_SETEXTENDEDLISTVIEWSTYLE,
                LVS_EX_SNAPTOGRID | LVS_EX_DOUBLEBUFFER,
                LVS_EX_SNAPTOGRID | LVS_EX_DOUBLEBUFFER)
            cell_width, cell_height = self._grid_cell()
            spacing = (cell_height << 16) | (cell_width & 0xFFFF)
            win_shell.user32.SendMessageW(hwnd, LVM_SETICONSPACING, 0, spacing)
        except Exception as error:
            print(f"[TitanShell] desktop grid failed: {error}")
        self._apply_arrange_style()

    def _apply_arrange_style(self):
        """Left alignment always; auto arrange only when it is asked for.

        Auto arrange is what packs the icons into the grid, but it is also
        what stops the user putting one where they want it, so it follows
        the setting - and the placement below fills the grid either way.
        """
        if not IS_WINDOWS:
            return
        try:
            hwnd = self.list.GetHandle()
            style = win_shell.user32.GetWindowLongW(hwnd, GWL_STYLE)
            wanted = (style & ~LVS_ALIGNMASK) | LVS_ALIGNLEFT
            if self.auto_arrange():
                wanted |= LVS_AUTOARRANGE
            else:
                wanted &= ~LVS_AUTOARRANGE
            if wanted != style:
                win_shell.user32.SetWindowLongW(hwnd, GWL_STYLE, wanted)
        except Exception as error:
            print(f"[TitanShell] desktop arrange style failed: {error}")

    def _grid_cell(self):
        """The size of one cell of the grid.

        Windows' own icon spacing is what Explorer lays a desktop out on, so
        it is what Titan uses; the constants below are the floor, for a
        machine that reports something too small to fit a two-line caption.
        """
        width, height = GRID_CELL_WIDTH, GRID_CELL_HEIGHT
        if IS_WINDOWS:
            try:
                width = max(width, int(win_shell.user32.GetSystemMetrics(
                    SM_CXICONSPACING)))
                height = max(height, int(win_shell.user32.GetSystemMetrics(
                    SM_CYICONSPACING)))
            except Exception:
                pass
        return width, height

    def layout_grid(self, force=False):
        """Place the icons on the grid, column by column.

        The alignment style alone is not enough, because the control decides
        where an item goes at the moment it is inserted - and the icons are
        read in before the desktop has been given the screen to cover, when
        the list is still a few pixels tall and a column holds one icon.
        That is a row of icons across the top, not a desktop.  So the grid is
        worked out here, from the screen the desktop actually covers, and
        every icon is put where it belongs; anything the user has dragged
        somewhere keeps its place unless auto arrange is on.
        """
        count = self.list.GetItemCount()
        if not count:
            return
        cell_width, cell_height = self._grid_cell()
        width, height = self.list.GetClientSize()
        if height < cell_height * 2 or width < cell_width:
            # Not sized yet - the desktop is the screen, so use that.
            width, height = win_shell.screen_size()
        rows = max(1, int(height) // cell_height)

        arrange_all = force or self.auto_arrange()

        # The slots the user has already claimed by dragging something onto
        # them, so an icon that has never been moved is not put underneath
        # one that has.
        taken = set()
        placed = {}
        if not arrange_all:
            for index in range(count):
                entry = self.items[index] if index < len(self.items) else None
                saved = entry and self._positions.get(entry['path'].lower())
                if not saved:
                    continue
                point = wx.Point(int(saved[0]), int(saved[1]))
                placed[index] = point
                taken.add((point.x // cell_width, point.y // cell_height))

        column = row = 0
        for index in range(count):
            point = placed.get(index)
            if point is None:
                while (column, row) in taken:
                    row += 1
                    if row >= rows:
                        row, column = 0, column + 1
                point = wx.Point(column * cell_width, row * cell_height)
                taken.add((column, row))
            try:
                self.list.SetItemPosition(index, point)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Look
    # ------------------------------------------------------------------
    def _apply_look(self):
        """Wallpaper, or the desktop colour, plus XP's transparent labels."""
        background = self.palette['desktop_background']
        text = self.palette['desktop_text']
        self.SetBackgroundColour(background)
        self.list.SetBackgroundColour(background)
        self.list.SetForegroundColour(text)

        if not IS_WINDOWS:
            return
        hwnd = self.list.GetHandle()
        try:
            def to_colorref(colour):
                return colour.Red() | (colour.Green() << 8) | \
                    (colour.Blue() << 16)

            win_shell.user32.SendMessageW(hwnd, LVM_SETBKCOLOR, 0,
                                          to_colorref(background))
            win_shell.user32.SendMessageW(hwnd, LVM_SETTEXTCOLOR, 0,
                                          to_colorref(text))
            # Transparent label backgrounds are what makes an icon caption
            # sit on the wallpaper instead of in a coloured box.
            win_shell.user32.SendMessageW(hwnd, LVM_SETTEXTBKCOLOR, 0,
                                          CLR_NONE)
        except Exception as error:
            print(f"[TitanShell] desktop colours failed: {error}")

        self._apply_wallpaper()

    def _apply_wallpaper(self):
        """Show the user's own wallpaper behind the icons.

        The list view can draw a background image itself (it is how Explorer
        did it), so the picture the user has already chosen in Windows is
        used rather than Titan inventing a second wallpaper setting.
        """
        if not IS_WINDOWS or not shell_setting('show_wallpaper', True):
            return
        path = win_shell.wallpaper_path()
        if not path:
            return
        try:
            image = LVBKIMAGEW()
            image.ulFlags = LVBKIF_SOURCE_URL | LVBKIF_STYLE_NORMAL
            image.hbm = None
            image.pszImage = ctypes.c_wchar_p(path)
            image.cchImageMax = len(path) + 1
            image.xOffsetPercent = 0
            image.yOffsetPercent = 0
            win_shell.user32.SendMessageW(self.list.GetHandle(),
                                          LVM_SETBKIMAGEW, 0,
                                          ctypes.byref(image))
        except Exception as error:
            print(f"[TitanShell] wallpaper failed: {error}")

    def apply_palette(self, palette):
        self.palette = palette
        self._apply_look()
        self.Refresh()

    # ------------------------------------------------------------------
    # Contents
    # ------------------------------------------------------------------
    def refresh(self):
        """Re-read the desktop folders and rebuild the icons."""
        self.items = self._read_items()
        self.list.ClearAll()

        self._image_list = wx.ImageList(ICON_SIZE, ICON_SIZE)
        fallback = wx.ArtProvider.GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER,
                                            (ICON_SIZE, ICON_SIZE))
        for entry in self.items:
            bitmap = self._icon_for(entry['path']) or fallback
            entry['image'] = self._image_list.Add(bitmap)
        self.list.AssignImageList(self._image_list, wx.IMAGE_LIST_NORMAL)

        for index, entry in enumerate(self.items):
            self.list.InsertItem(index, entry['name'], entry['image'])
            self.list.SetItemData(index, index)

        self._restore_positions()

    def _read_items(self):
        entries = []
        seen = set()
        for folder in win_shell.desktop_folders():
            try:
                names = sorted(os.listdir(folder), key=str.lower)
            except Exception:
                continue
            for name in names:
                if name.lower() in ('desktop.ini', 'thumbs.db'):
                    continue
                path = os.path.join(folder, name)
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                entries.append({
                    'name': win_shell.file_display_name(path),
                    'path': path,
                    'type': win_shell.file_type_name(path),
                    'image': -1,
                })
        # Folders first, then files - the order Explorer sorts a desktop in.
        entries.sort(key=lambda item: (not os.path.isdir(item['path']),
                                       item['name'].lower()))
        return entries

    def _icon_for(self, path):
        """The real Windows icon, converted into something wx can hold."""
        if not IS_WINDOWS:
            return None
        handle = win_shell.file_icon_handle(path, large=True)
        if not handle:
            return None
        try:
            icon = wx.Icon()
            icon.SetHandle(handle)
            icon.SetWidth(ICON_SIZE)
            icon.SetHeight(ICON_SIZE)
            bitmap = wx.Bitmap()
            bitmap.CopyFromIcon(icon)
            return bitmap if bitmap.IsOk() else None
        except Exception:
            return None
        finally:
            # wx.Icon took ownership of the handle through SetHandle; the
            # icon object destroys it, so it must not be destroyed here.
            pass

    def selected_index(self):
        return self.list.GetFirstSelected()

    def selected_entry(self):
        index = self.selected_index()
        if 0 <= index < len(self.items):
            return self.items[index]
        return None

    # ------------------------------------------------------------------
    # Icon positions
    # ------------------------------------------------------------------
    def _positions_file(self):
        try:
            return os.path.join(get_user_data_dir(), 'shell_desktop.json')
        except Exception:
            return None

    def _load_positions(self):
        path = self._positions_file()
        if not path or not os.path.isfile(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                return json.load(handle) or {}
        except Exception:
            return {}

    def _save_positions(self):
        path = self._positions_file()
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(self._positions, handle, indent=2)
        except Exception as error:
            print(f"[TitanShell] could not save icon positions: {error}")

    def auto_arrange(self):
        return bool(shell_setting('auto_arrange_icons', False))

    def _restore_positions(self):
        """Put every icon back where the user dragged it, and the rest on
        the grid.  `layout_grid` does both."""
        self._apply_arrange_style()
        self.layout_grid()

    def _on_begin_drag(self, event):
        if self.auto_arrange():
            # With auto arrange on, the icons are not the user's to place.
            return
        self._dragging = event.GetIndex()
        try:
            if not self.list.HasCapture():
                self.list.CaptureMouse()
        except Exception:
            pass

    def _on_drop(self, event):
        index, self._dragging = self._dragging, -1
        try:
            if self.list.HasCapture():
                self.list.ReleaseMouse()
        except Exception:
            pass
        if index is not None and index >= 0:
            try:
                point = event.GetPosition()
                # Drop by the icon's top left corner, not its middle, so an
                # icon lands where the pointer is rather than below and right.
                self.list.SetItemPosition(
                    index, wx.Point(max(0, point.x - ICON_SIZE // 2),
                                    max(0, point.y - ICON_SIZE // 2)))
                self._remember_positions()
            except Exception as error:
                print(f"[TitanShell] could not move the icon: {error}")
        event.Skip()

    def _on_capture_lost(self, event):
        self._dragging = -1

    def _remember_positions(self):
        if self.auto_arrange():
            return
        for index, entry in enumerate(self.items):
            try:
                point = self.list.GetItemPosition(index)
                self._positions[entry['path'].lower()] = [point.x, point.y]
            except Exception:
                pass
        self._save_positions()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def open_selected(self):
        entry = self.selected_entry()
        if entry:
            win_shell.open_path(entry['path'])

    def rename_selected(self):
        index = self.selected_index()
        if index >= 0:
            self.list.EditLabel(index)

    def delete_selected(self):
        entry = self.selected_entry()
        if not entry:
            return
        if win_shell.recycle([entry['path']]):
            self.refresh()

    def properties_of_selected(self):
        entry = self.selected_entry()
        if entry:
            win_shell.show_properties(entry['path'])

    def _on_activate(self, event):
        self.open_selected()

    def _on_rename(self, event):
        if event.IsEditCancelled():
            return
        index = event.GetIndex()
        if not (0 <= index < len(self.items)):
            return
        entry = self.items[index]
        new_label = event.GetLabel().strip()
        if not new_label or new_label == entry['name']:
            return
        old_path = entry['path']
        extension = os.path.splitext(old_path)[1]
        new_path = os.path.join(os.path.dirname(old_path),
                                new_label + extension)
        try:
            os.rename(old_path, new_path)
            entry['path'] = new_path
            entry['name'] = new_label
        except Exception as error:
            print(f"[TitanShell] rename failed: {error}")
            event.Veto()
            wx.MessageBox(_("The item could not be renamed."), _("Desktop"),
                          wx.OK | wx.ICON_ERROR, self)

    # ------------------------------------------------------------------
    # Keyboard and menus
    # ------------------------------------------------------------------
    def _on_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and event.AltDown():
            self.properties_of_selected()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.open_selected()
        elif key == wx.WXK_F2:
            self.rename_selected()
        elif key == wx.WXK_DELETE:
            self.delete_selected()
        elif key == wx.WXK_F5:
            self.refresh()
        else:
            event.Skip()

    def _on_char_hook(self, event):
        """Tab goes to the Start button, Shift+Tab to the notification area.

        This is the round trip Windows itself does from the desktop, and it
        is what makes the shell reachable with the keyboard alone from
        wherever the user happens to be: forwards is the beginning of the
        bar, backwards is its end.
        """
        if event.GetKeyCode() != wx.WXK_TAB or event.ControlDown()                 or event.AltDown():
            event.Skip()
            return
        shell = self.shell
        moved = False
        try:
            if event.ShiftDown():
                moved = shell.focus_tray()
            else:
                moved = shell.focus_start_button()
        except Exception as error:
            print(f"[TitanShell] could not leave the desktop: {error}")
        if not moved:
            event.Skip()

    def _on_item_menu(self, event):
        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("&Open"))
        menu.AppendSeparator()
        rename = menu.Append(wx.ID_ANY, _("Re&name"))
        delete = menu.Append(wx.ID_ANY, _("&Delete"))
        menu.AppendSeparator()
        properties = menu.Append(wx.ID_ANY, _("P&roperties"))

        self.Bind(wx.EVT_MENU, lambda e: self.open_selected(), open_item)
        self.Bind(wx.EVT_MENU, lambda e: self.rename_selected(), rename)
        self.Bind(wx.EVT_MENU, lambda e: self.delete_selected(), delete)
        self.Bind(wx.EVT_MENU, lambda e: self.properties_of_selected(),
                  properties)
        self.list.PopupMenu(menu)
        menu.Destroy()

    def _on_background_menu(self, event):
        """The background menu, reachable by mouse and by the Apps key."""
        if self.selected_index() >= 0 and event.GetEventObject() is self.list:
            # A right click on an item is handled by the item menu above.
            position = self.list.ScreenToClient(event.GetPosition()) \
                if event.GetPosition() != wx.DefaultPosition else None
            if position is not None:
                hit, _flags = self.list.HitTest(position)
                if hit >= 0:
                    return

        menu = wx.Menu()
        arrange = menu.AppendCheckItem(wx.ID_ANY, _("Auto &Arrange"))
        arrange.Check(self.auto_arrange())
        line_up = menu.Append(wx.ID_ANY, _("Line Up &Icons"))
        menu.AppendSeparator()
        refresh = menu.Append(wx.ID_ANY, _("Re&fresh"))
        menu.AppendSeparator()
        new_folder = menu.Append(wx.ID_ANY, _("&New Folder"))
        menu.AppendSeparator()
        titan = menu.Append(wx.ID_ANY, _("&Titan settings"))
        display = menu.Append(wx.ID_ANY, _("Display &properties"))

        self.Bind(wx.EVT_MENU, lambda e: self._toggle_auto_arrange(), arrange)
        self.Bind(wx.EVT_MENU, lambda e: self._line_up(), line_up)
        self.Bind(wx.EVT_MENU, lambda e: self.refresh(), refresh)
        self.Bind(wx.EVT_MENU, lambda e: self._new_folder(), new_folder)
        self.Bind(wx.EVT_MENU, lambda e: self.shell.open_settings(), titan)
        self.Bind(wx.EVT_MENU, lambda e: win_shell.open_path(
            'ms-settings:personalization-background'), display)

        self.list.PopupMenu(menu)
        menu.Destroy()

    def _toggle_auto_arrange(self):
        from src.settings.settings import set_setting
        new_value = not self.auto_arrange()
        set_setting('auto_arrange_icons', str(new_value), 'titan_shell')
        self._apply_arrange_style()
        self.layout_grid(force=new_value)

    def _line_up(self):
        """Line the icons up on the grid, keeping the order they are in."""
        try:
            self.layout_grid(force=True)
            self._remember_positions()
        except Exception as error:
            print(f"[TitanShell] could not line the icons up: {error}")

    def _new_folder(self):
        folders = win_shell.desktop_folders()
        if not folders:
            return
        base = os.path.join(folders[0], _("New Folder"))
        path, index = base, 2
        while os.path.exists(path):
            path = "{} ({})".format(base, index)
            index += 1
        try:
            os.makedirs(path)
        except Exception as error:
            print(f"[TitanShell] could not create the folder: {error}")
            return
        self.refresh()
        for index, entry in enumerate(self.items):
            if os.path.normcase(entry['path']) == os.path.normcase(path):
                self.list.Select(index)
                self.list.Focus(index)
                self.list.EditLabel(index)
                break

    def focus_icons(self):
        """Give the keyboard to the desktop, on the first icon.

        The desktop is not raised over the user's windows to do it - it is
        the bottom of the z-order by definition - but it does have to become
        the foreground window, or `SetFocus` moves a focus that is not
        Windows' idea of the focus and every key still goes elsewhere.
        """
        try:
            if IS_WINDOWS:
                win_shell.take_foreground(self.GetHandle())
            self.list.SetFocus()
            if self.list.GetItemCount() and self.selected_index() < 0:
                self.list.Select(0)
                self.list.Focus(0)
            return True
        except Exception as error:
            print(f"[TitanShell] could not focus the desktop: {error}")
            return False

    def _on_close(self, event):
        self._remember_positions()
        event.Skip()
