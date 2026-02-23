# TFM/gui.py
import sys
import os
import subprocess
import wx
import datetime
import shutil
import pygame
import platform
from translation import _
# Import the custom ID from menu.py
from menu import create_file_menu, create_edit_menu, create_view_menu, ID_RENAME
from tfm_settings import SettingsManager, SettingsDialog
from copy_move import copy_files_with_progress, move_files_with_progress
# Import sound functions (will use sound effects, but remove direct TTS calls)
from sound import initialize_sound, play_startup_sound, get_sfx_directory, play_sound, play_delete_sound, play_focus_sound, play_error_sound, play_select_sound

import string

# TCE Speech: use Titan TTS engine (stereo speech) when available
try:
    from src.titan_core.tce_speech import speak as _tce_speak
except ImportError:
    _tce_speak = None

if _tce_speak is None:
    # Standalone fallback (outside Titan environment)
    try:
        import accessible_output3.outputs.auto as _ao3
        _speaker = _ao3.Auto()
    except Exception:
        _speaker = None


def _get_drives():
    """Return available storage roots for the current platform.

    - Windows: drive letters (C:\\, D:\\, ...)
    - macOS:   /Volumes entries + home directory shortcut
    - Linux:   /mnt and /media entries + home directory shortcut
    """
    system = platform.system()
    if system == "Windows":
        drives = []
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
        return drives
    elif system == "Darwin":  # macOS
        volumes = []
        volumes_dir = "/Volumes"
        try:
            if os.path.isdir(volumes_dir):
                for entry in sorted(os.listdir(volumes_dir)):
                    full = os.path.join(volumes_dir, entry)
                    if os.path.isdir(full):
                        volumes.append(full)
        except Exception:
            pass
        home = os.path.expanduser("~")
        if home not in volumes:
            volumes.insert(0, home)
        return volumes
    else:  # Linux
        roots = []
        for base in ("/mnt", "/media"):
            try:
                if os.path.isdir(base):
                    for entry in sorted(os.listdir(base)):
                        full = os.path.join(base, entry)
                        if os.path.isdir(full):
                            roots.append(full)
            except Exception:
                pass
        home = os.path.expanduser("~")
        if home not in roots:
            roots.insert(0, home)
        if not roots:
            roots.append("/")
        return roots


def _is_fs_root(path):
    """Return True when *path* is a filesystem root that has no parent."""
    return os.path.dirname(path) == path


def get_app_sfx_path():
    return get_sfx_directory()


class FileManager(wx.Frame):
    def __init__(self, initial_path=None):
        wx.Frame.__init__(self, None, title=_("File Manager"), size=(800, 600))
        self.settings = SettingsManager()
        self.clipboard = []
        self.active_panel = None

        # Set initial path or default to home
        default_path = initial_path if initial_path and os.path.exists(initial_path) else os.path.expanduser("~")

        # Commander mode paths and selections
        self.left_path = default_path
        self.right_path = default_path
        self.left_selected_items = set()
        self.right_selected_items = set()

        # Single list and classic mode path and selection
        self.current_path = default_path
        self.selected_items = set()
        self.is_drive_selection_mode = False

        self.view_settings = self.settings.get_view_settings()
        self.show_hidden = self.settings.get_show_hidden()
        self.show_extensions = self.settings.get_show_extensions()
        self.sort_mode = self.settings.get_sort_mode()

        # Validate initial path and switch to drive selection mode if path is invalid
        if not os.path.isdir(self.current_path):
            self.is_drive_selection_mode = True
            self.announce(_("Cannot access last directory. Switching to drive selection view."))

        # Main panel
        panel = wx.Panel(self)

        # Off-screen label for screen reader announcements
        self.status_text = wx.StaticText(panel, label="")
        self.status_text.SetPosition((-1000, -1000))

        # Menu
        menubar = wx.MenuBar()

        file_menu = create_file_menu(self)
        edit_menu = create_edit_menu(self)
        view_menu = create_view_menu(self)

        menubar.Append(file_menu, _('&File'))
        menubar.Append(edit_menu, _('&Edit'))
        menubar.Append(view_menu, _('&View'))

        self.SetMenuBar(menubar)

        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        explorer_view_mode = self.settings.get_explorer_view_mode()

        if explorer_view_mode == "list":
            self.file_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list()
            self.main_sizer.Add(self.file_list, 1, wx.EXPAND | wx.ALL, 10)

            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)
            self.file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
            self.file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)

        elif explorer_view_mode == "commander":
            self.left_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.right_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)

            self.update_file_list_columns(ctrl=self.left_list)
            self.update_file_list_columns(ctrl=self.right_list)
            self.populate_file_list(ctrl=self.left_list, path=self.left_path)
            self.populate_file_list(ctrl=self.right_list, path=self.right_path)

            commander_sizer = wx.BoxSizer(wx.HORIZONTAL)
            commander_sizer.Add(self.left_list, 1, wx.EXPAND | wx.ALL, 5)
            commander_sizer.Add(self.right_list, 1, wx.EXPAND | wx.ALL, 5)
            self.main_sizer.Add(commander_sizer, 1, wx.EXPAND)

            self.left_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_commander_left)
            self.right_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_commander_right)
            self.left_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down_commander_left)
            self.right_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down_commander_right)
            self.left_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected_commander_left)
            self.left_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected_commander_left)
            self.right_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected_commander_right)
            self.right_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected_commander_right)
            self.left_list.Bind(wx.EVT_SET_FOCUS, self.on_focus_commander)
            self.right_list.Bind(wx.EVT_SET_FOCUS, self.on_focus_commander)

        elif explorer_view_mode == "multi-tab":
            self.notebook = wx.Notebook(panel)
            self.file_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list()
            self.notebook.AddPage(self.file_list, _("Tab 1"))
            self.main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 10)

            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)
            self.file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
            self.file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)

        else:  # classic (default)
            self.file_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list()
            self.main_sizer.Add(self.file_list, 1, wx.EXPAND | wx.ALL, 10)

            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)
            self.file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
            self.file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)

        panel.SetSizer(self.main_sizer)

        # macOS VoiceOver: assign accessible names to list controls
        if platform.system() == 'Darwin':
            self._setup_voiceover_names()

        # Keyboard shortcuts
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('C'), wx.ID_COPY),
            (wx.ACCEL_CTRL, ord('X'), wx.ID_CUT),
            (wx.ACCEL_CTRL, ord('V'), wx.ID_PASTE),
            (wx.ACCEL_CTRL, ord('A'), wx.ID_SELECTALL),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, wx.ID_DELETE),
            (wx.ACCEL_NORMAL, wx.WXK_NUMPAD_DELETE, wx.ID_DELETE),
            (wx.ACCEL_NORMAL, wx.WXK_F2, ID_RENAME)
        ])
        self.SetAcceleratorTable(accel_tbl)

        self.Bind(wx.EVT_MENU, self.on_copy, id=wx.ID_COPY)
        self.Bind(wx.EVT_MENU, self.on_cut, id=wx.ID_CUT)
        self.Bind(wx.EVT_MENU, self.on_paste, id=wx.ID_PASTE)
        self.Bind(wx.EVT_MENU, self.on_select_all, id=wx.ID_SELECTALL)
        self.Bind(wx.EVT_MENU, self.on_delete, id=wx.ID_DELETE)
        self.Bind(wx.EVT_MENU, self.on_rename, id=ID_RENAME)

        self.update_window_title()
        self.Show()

    def _setup_voiceover_names(self):
        """Set VoiceOver-readable names on interactive controls (macOS only)."""
        try:
            if hasattr(self, 'file_list'):
                self.file_list.SetName(_("File list"))
            if hasattr(self, 'left_list'):
                self.left_list.SetName(_("Left panel"))
            if hasattr(self, 'right_list'):
                self.right_list.SetName(_("Right panel"))
            if hasattr(self, 'notebook'):
                self.notebook.SetName(_("File tabs"))
        except Exception as e:
            print(f"TFM: VoiceOver name setup failed: {e}")

    def update_window_title(self):
        if self.is_drive_selection_mode:
            if platform.system() == 'Darwin':
                self.SetTitle(_("Volume selection"))
            elif platform.system() == 'Linux':
                self.SetTitle(_("Mount point selection"))
            else:
                self.SetTitle(_("Drive selection"))
            return

        mode = self.settings.get_window_title_mode()
        path = self.current_path
        if self.settings.get_explorer_view_mode() == 'commander':
            if self.active_panel == 'left':
                path = self.left_path
            else:
                path = self.right_path

        if mode == 'folder-name':
            self.SetTitle(os.path.basename(path) or _("File Manager"))
        elif mode == 'path':
            self.SetTitle(path)
        else:
            # app-name
            self.SetTitle(_("File Manager"))

    def update_file_list_columns(self, ctrl=None):
        if ctrl is None:
            explorer_view_mode = self.settings.get_explorer_view_mode()
            if explorer_view_mode == "commander":
                if hasattr(self, 'left_list') and self.left_list.HasFocus():
                    ctrl = self.left_list
                elif hasattr(self, 'right_list') and self.right_list.HasFocus():
                    ctrl = self.right_list
                else:
                    ctrl = getattr(self, 'left_list', None)
            elif explorer_view_mode == "multi-tab":
                ctrl = self.get_active_list_ctrl()
            else:
                ctrl = self.file_list

        if ctrl is None:
            return

        ctrl.ClearAll()
        col_index = 0
        if 'name' in self.view_settings:
            ctrl.InsertColumn(col_index, _('Name'), width=300)
            col_index += 1
        if 'date' in self.view_settings:
            ctrl.InsertColumn(col_index, _('Date modified'), width=200)
            col_index += 1
        if 'type' in self.view_settings:
            ctrl.InsertColumn(col_index, _('Type'), width=100)

    def populate_file_list(self, ctrl=None, path=None):
        if ctrl is None:
            ctrl = self.get_active_list_ctrl()

        if path is None:
            if hasattr(self, 'left_list') and ctrl == self.left_list:
                path = self.left_path
            elif hasattr(self, 'right_list') and ctrl == self.right_list:
                path = self.right_path
            else:
                path = self.current_path

        current_path_to_list = path

        if ctrl is None:
            explorer_view_mode = self.settings.get_explorer_view_mode()
            if explorer_view_mode == "commander":
                ctrl = self.left_list
            elif explorer_view_mode == "multi-tab":
                ctrl = self.get_active_list_ctrl()
            else:
                ctrl = self.file_list

        if ctrl is None:
            return

        ctrl.DeleteAllItems()
        self.selected_items.clear()

        if self.is_drive_selection_mode:
            drives = _get_drives()
            if not drives:
                index = ctrl.InsertItem(ctrl.GetItemCount(), _('No drives available'))
            else:
                for drive in drives:
                    index = ctrl.InsertItem(ctrl.GetItemCount(), drive)
                    if 'date' in self.view_settings:
                        col_index_date = -1
                        for i in range(ctrl.GetColumnCount()):
                            if ctrl.GetColumn(i).GetText() == _('Date modified'):
                                col_index_date = i
                                break
                        if col_index_date != -1:
                            ctrl.SetItem(index, col_index_date, '')
                    if 'type' in self.view_settings:
                        col_index_type = -1
                        for i in range(ctrl.GetColumnCount()):
                            if ctrl.GetColumn(i).GetText() == _('Type'):
                                col_index_type = i
                                break
                        if col_index_type != -1:
                            ctrl.SetItem(index, col_index_type, _('Drive'))
            if ctrl.GetItemCount() > 0:
                ctrl.Select(0)
                ctrl.Focus(0)
            return

        try:
            entries = os.listdir(current_path_to_list)
            if not self.show_hidden:
                entries = [e for e in entries if not e.startswith('.')]
            entries = [e for e in entries if e != '.DS_Store']

            if not entries:
                index = ctrl.InsertItem(ctrl.GetItemCount(), _('This folder is empty'))
                if 'date' in self.view_settings:
                    col_index_date = -1
                    for i in range(ctrl.GetColumnCount()):
                        if ctrl.GetColumn(i).GetText() == _('Date modified'):
                            col_index_date = i
                            break
                    if col_index_date != -1:
                        ctrl.SetItem(index, col_index_date, '')
                if 'type' in self.view_settings:
                    col_index_type = -1
                    for i in range(ctrl.GetColumnCount()):
                        if ctrl.GetColumn(i).GetText() == _('Type'):
                            col_index_type = i
                            break
                    if col_index_type != -1:
                        ctrl.SetItem(index, col_index_type, '')

            else:
                if self.sort_mode == 'name':
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(current_path_to_list, x)), x.lower()))
                elif self.sort_mode == 'date':
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(current_path_to_list, x)), os.path.getmtime(os.path.join(current_path_to_list, x))))
                elif self.sort_mode == 'type':
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(current_path_to_list, x)), os.path.splitext(x.lower())[1], x.lower()))

                for entry in entries:
                    entry_path = os.path.join(current_path_to_list, entry)
                    modified = datetime.datetime.fromtimestamp(os.path.getmtime(entry_path)).strftime('%Y-%m-%d %H:%M:%S')
                    entry_type = _('Folder') if os.path.isdir(entry_path) else _('File')
                    display_name = entry if self.show_extensions else os.path.splitext(entry)[0]
                    index = ctrl.InsertItem(ctrl.GetItemCount(), display_name)

                    if 'date' in self.view_settings:
                        col_index_date = -1
                        for i in range(ctrl.GetColumnCount()):
                            if ctrl.GetColumn(i).GetText() == _('Date modified'):
                                col_index_date = i
                                break
                        if col_index_date != -1:
                            ctrl.SetItem(index, col_index_date, modified)

                    if 'type' in self.view_settings:
                        col_index_type = -1
                        for i in range(ctrl.GetColumnCount()):
                            if ctrl.GetColumn(i).GetText() == _('Type'):
                                col_index_type = i
                                break
                        if col_index_type != -1:
                            ctrl.SetItem(index, col_index_type, entry_type)

                # Reselect items that were selected before repopulating
                items_to_reselect = [i for i in range(ctrl.GetItemCount())
                                     if ctrl.GetItemText(i) in self.selected_items
                                     and ctrl.GetItemText(i) != _('This folder is empty')]
                for i in items_to_reselect:
                    ctrl.Select(i)

                if ctrl.GetItemCount() > 0 and not items_to_reselect:
                    ctrl.Select(0)
                    ctrl.Focus(0)

        except PermissionError:
            wx.MessageBox(_("Access denied"), _("Error"), wx.OK | wx.ICON_ERROR)
            self.announce(_("Access denied."))
            if self.current_path != os.path.expanduser("~"):
                self.current_path = os.path.dirname(self.current_path)
                self.populate_file_list(ctrl=ctrl)
                self.update_window_title()


    def announce(self, message):
        self.status_text.SetLabel(message)
        if _tce_speak is not None:
            _tce_speak(message)
            return
        if _speaker:
            try:
                _speaker.speak(message, interrupt=True)
                return
            except Exception:
                pass
        try:
            _sys = platform.system()
            if _sys == 'Windows':
                import win32com.client
                win32com.client.Dispatch("SAPI.SpVoice").Speak(message)
            elif _sys == 'Darwin':
                subprocess.Popen(['say', message])
            else:
                subprocess.Popen(['spd-say', message])
        except Exception:
            pass


    def on_exit(self, event):
        self.Close()

    def on_new_file(self, event):
        dlg = wx.TextEntryDialog(self, _('Enter new file name:'), _('New File'))
        if dlg.ShowModal() == wx.ID_OK:
            file_name = dlg.GetValue()
            if file_name:
                new_file_path = os.path.join(self.current_path, file_name)
                try:
                    open(new_file_path, 'w').close()
                    self.populate_file_list()
                    self.announce(_("Created new file: {}").format(file_name))
                except Exception as e:
                    wx.MessageBox(_("Could not create file {}: {}").format(file_name, e), _("File Creation Error"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Error creating file: {}").format(file_name))
        dlg.Destroy()

    def on_new_folder(self, event):
        dlg = wx.TextEntryDialog(self, _('Enter new folder name:'), _('New Folder'))
        if dlg.ShowModal() == wx.ID_OK:
            folder_name = dlg.GetValue()
            if folder_name:
                new_folder_path = os.path.join(self.current_path, folder_name)
                try:
                    os.makedirs(new_folder_path, exist_ok=True)
                    self.populate_file_list()
                    self.announce(_("Created new folder: {}").format(folder_name))
                except Exception as e:
                    wx.MessageBox(_("Could not create folder {}: {}").format(folder_name, e), _("Folder Creation Error"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Error creating folder: {}").format(folder_name))
        dlg.Destroy()

    def on_rename(self, event):
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("No active file list to rename from."))
            return

        item_index = ctrl.GetFocusedItem()
        if item_index != -1:
            old_name = ctrl.GetItemText(item_index)

            if old_name == _('This folder is empty'):
                self.announce(_("Cannot rename this entry."))
                return

            real_old_name = old_name
            if not self.show_extensions and os.path.splitext(old_name)[1] == '':
                matches = [entry for entry in os.listdir(self.current_path) if os.path.splitext(entry)[0] == old_name]
                if matches:
                    real_old_name = matches[0]

            dlg = wx.TextEntryDialog(self, _("Enter new name:"), _("Rename"), real_old_name)
            if dlg.ShowModal() == wx.ID_OK:
                new_name = dlg.GetValue()
                if new_name and new_name != real_old_name:
                    old_path = os.path.join(self.current_path, real_old_name)
                    new_path = os.path.join(self.current_path, new_name)
                    try:
                        os.rename(old_path, new_path)
                        if real_old_name in self.selected_items:
                            self.selected_items.remove(real_old_name)
                            self.selected_items.add(new_name)
                        self.populate_file_list(ctrl=ctrl)
                        self.announce(_("Renamed {} to {}").format(real_old_name, new_name))
                    except Exception as e:
                        wx.MessageBox(str(e), _("Rename Error"), wx.OK | wx.ICON_ERROR)
                        self.announce(_("Error renaming: {}").format(real_old_name))
                elif new_name == real_old_name:
                    self.announce(_("Name not changed."))
                else:
                    self.announce(_("Rename cancelled."))
            else:
                self.announce(_("Rename cancelled."))
            dlg.Destroy()
        else:
            self.announce(_("No item selected to rename."))


    def on_copy(self, event):
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("No active file list to copy from."))
            return

        selected_names = {ctrl.GetItemText(i)
                          for i in range(ctrl.GetItemCount()) if ctrl.IsSelected(i)
                          and ctrl.GetItemText(i) != _('This folder is empty')}

        if selected_names:
            path = self.current_path
            if self.settings.get_explorer_view_mode() == 'commander':
                if self.active_panel == 'left':
                    path = self.left_path
                else:
                    path = self.right_path
            self.clipboard = [(os.path.join(path, name), 'copy') for name in selected_names]
            self.announce(_("Copied {} items to clipboard.").format(len(selected_names)))
        else:
            self.clipboard = []
            self.announce(_("No items selected to copy."))


    def on_cut(self, event):
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("No active file list to cut from."))
            return

        selected_names = {ctrl.GetItemText(i)
                          for i in range(ctrl.GetItemCount()) if ctrl.IsSelected(i)
                          and ctrl.GetItemText(i) != _('This folder is empty')}

        if selected_names:
            path = self.current_path
            if self.settings.get_explorer_view_mode() == 'commander':
                if self.active_panel == 'left':
                    path = self.left_path
                else:
                    path = self.right_path
            self.clipboard = [(os.path.join(path, name), 'cut') for name in selected_names]
            self.announce(_("Cut {} items to clipboard.").format(len(selected_names)))
        else:
            self.clipboard = []
            self.announce(_("No items selected to cut."))


    def on_paste(self, event):
        if not self.clipboard:
            self.announce(_("Clipboard is empty."))
            return

        explorer_view_mode = self.settings.get_explorer_view_mode()
        if explorer_view_mode == 'commander':
            if self.active_panel == 'left':
                dst_folder = self.right_path
                ctrl_to_refresh = self.right_list
            else:
                dst_folder = self.left_path
                ctrl_to_refresh = self.left_list
        else:
            dst_folder = self.current_path
            ctrl_to_refresh = self.get_active_list_ctrl()

        copy_dialog_mode = self.settings.get_copy_dialog_mode()

        copy_files = [path for path, action in self.clipboard if action == 'copy']
        move_files = [path for path, action in self.clipboard if action == 'cut']

        ctrl = self.get_active_list_ctrl()

        if copy_dialog_mode == 'system':
            for src in copy_files:
                dst = os.path.join(dst_folder, os.path.basename(src))
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                except Exception as e:
                    wx.MessageBox(_("Copy error for {}: {}").format(os.path.basename(src), e), _("Copy Error"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Error copying: {}").format(os.path.basename(src)))

            for src in move_files:
                dst = os.path.join(dst_folder, os.path.basename(src))
                try:
                    shutil.move(src, dst)
                except Exception as e:
                    wx.MessageBox(_("Move error for {}: {}").format(os.path.basename(src), e), _("Move Error"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Error moving: {}").format(os.path.basename(src)))

            self.clipboard = []
            self.populate_file_list(ctrl=ctrl_to_refresh)
            self.announce(_("Paste operation complete."))

        else:
            if copy_files:
                copy_files_with_progress(self, copy_files, dst_folder)
                self.clipboard = []

            if move_files:
                move_files_with_progress(self, move_files, dst_folder)
                self.clipboard = []

            if not copy_files and not move_files:
                self.announce(_("Nothing to paste."))


    def on_select_all(self, event):
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("No active file list."))
            return

        self.selected_items.clear()
        items_selected_count = 0
        for i in range(ctrl.GetItemCount()):
            name = ctrl.GetItemText(i)
            if name != _('This folder is empty'):
                self.selected_items.add(name)
                ctrl.Select(i)
                items_selected_count += 1

        if items_selected_count > 0:
            self.announce(_("Selected all ({}) items.").format(items_selected_count))
        else:
            self.announce(_("No items to select."))


    def on_item_selected(self, event):
        item_index = event.GetItem().GetId()
        ctrl = event.GetEventObject()
        name = ctrl.GetItemText(item_index)
        if name != _('This folder is empty'):
            self.selected_items.add(name)
        event.Skip()

    def on_item_deselected(self, event):
        item_index = event.GetItem().GetId()
        ctrl = event.GetEventObject()
        name = ctrl.GetItemText(item_index)
        if name in self.selected_items:
            self.selected_items.remove(name)
        event.Skip()


    def on_open(self, event):
        """Handle item activation for single list / list / tabs mode."""
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("No active file list."))
            return

        if isinstance(event, wx.ListEvent):
            item_index = event.GetIndex()
        else:
            item_index = ctrl.GetFocusedItem()

        if item_index == -1:
            self.announce(_("No item selected."))
            return

        name = ctrl.GetItemText(item_index)

        if name == _('This folder is empty'):
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Folder is empty."))
            return

        if self.is_drive_selection_mode:
            selected_drive = name
            if os.path.exists(selected_drive):
                self.current_path = selected_drive
                self.is_drive_selection_mode = False
                self.populate_file_list(ctrl=ctrl)
                self.update_window_title()
                play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
            else:
                play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                self.announce(_("Selected drive does not exist: {}").format(selected_drive))
            return

        # Find the real path, considering hidden extensions
        real_path = os.path.join(self.current_path, name)
        if not self.show_extensions and os.path.splitext(name)[1] == '':
            for entry in os.listdir(self.current_path):
                if os.path.splitext(entry)[0] == name:
                    real_path = os.path.join(self.current_path, entry)
                    break

        if os.path.isdir(real_path):
            self.selected_items.clear()
            self.current_path = real_path
            self.populate_file_list(ctrl=ctrl)
            self.update_window_title()
            play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
        elif os.path.exists(real_path):
            try:
                self.open_file_in_system(real_path)
                play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
                self.announce(_("Opened: {}").format(name))
            except Exception as e:
                wx.MessageBox(_("Could not open {}: {}").format(name, e), _("Open Error"), wx.OK | wx.ICON_ERROR)
                play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                self.announce(_("Error opening: {}").format(name))
        else:
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Item not found: {}").format(name))


    def open_file_in_system(self, path):
        system = platform.system()
        try:
            if system == 'Windows':
                os.startfile(path)
            elif system == 'Darwin':
                subprocess.Popen(['open', path])
            else:
                subprocess.Popen(['xdg-open', path])
        except Exception as e:
            print(f"System file open error for {path}: {e}")
            raise


    def on_focus(self, event):
        play_sound(os.path.join(get_sfx_directory(), 'focus.ogg'))
        ctrl = event.GetEventObject()
        focused_item_index = ctrl.GetFocusedItem()
        current_dir_announce = _("Current directory: {}").format(os.path.basename(self.current_path) or self.current_path)
        if focused_item_index != -1:
            focused_item_name = ctrl.GetItemText(focused_item_index)
            self.announce(_("{}. Focus: {}.").format(current_dir_announce, focused_item_name))
        else:
            self.announce(current_dir_announce)
        event.Skip()

    def on_key_down(self, event):
        """Handle key presses for single list / list / tabs mode."""
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_BACK:
            self.go_back()

        elif keycode == wx.WXK_F2:
            self.on_rename(None)

        elif keycode in [wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE]:
            self.on_delete(None)

        elif keycode == wx.WXK_RETURN:
            self.on_open(event)

        elif keycode == wx.WXK_SPACE:
            ctrl = event.GetEventObject()
            item_index = ctrl.GetFocusedItem()
            if item_index != -1:
                name = ctrl.GetItemText(item_index)
                if name != _('This folder is empty'):
                    if name in self.selected_items:
                        self.selected_items.remove(name)
                        ctrl.Select(item_index, 0)
                        self.announce(_("Deselected: {}. Total: {}").format(name, len(self.selected_items)))
                    else:
                        self.selected_items.add(name)
                        ctrl.Select(item_index)
                        self.announce(_("Selected: {}. Total: {}").format(name, len(self.selected_items)))
                else:
                    play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                    self.announce(_("Cannot select this entry."))
            event.Skip()

        else:
            event.Skip()


    def go_back(self):
        active_ctrl = self.get_active_list_ctrl()
        if not active_ctrl:
            return

        current_path_attr = 'current_path'
        selected_items_attr = 'selected_items'

        if self.settings.get_explorer_view_mode() == 'commander':
            if self.active_panel == 'left':
                current_path_attr = 'left_path'
                selected_items_attr = 'left_selected_items'
            else:
                current_path_attr = 'right_path'
                selected_items_attr = 'right_selected_items'

        current_path = getattr(self, current_path_attr)
        folder_to_select = os.path.basename(current_path)
        parent_path = os.path.dirname(current_path)

        is_drive_root = _is_fs_root(current_path)

        if self.is_drive_selection_mode:
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Already in drive selection view."))
            return

        if is_drive_root:
            self.is_drive_selection_mode = True
            self.populate_file_list(ctrl=active_ctrl)
            self.update_window_title()
            play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
        elif parent_path != current_path and os.path.isdir(parent_path):
            setattr(self, current_path_attr, parent_path)
            getattr(self, selected_items_attr).clear()

            self.populate_file_list(ctrl=active_ctrl, path=parent_path)

            # Select the folder we came from
            for i in range(active_ctrl.GetItemCount()):
                if active_ctrl.GetItemText(i) == folder_to_select:
                    active_ctrl.Select(i)
                    active_ctrl.Focus(i)
                    break

            self.update_window_title()
            play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
        else:
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Already at root."))


    def on_delete(self, event=None):
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("No active file list."))
            return

        selected_names = list(self.selected_items)

        if not selected_names:
            self.announce(_("No items selected to delete."))
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            return

        selected_count = len(selected_names)
        names_display = ', '.join(selected_names)

        if self.settings.get_confirm_delete():
            message = (
                _("Delete these items? {}").format(names_display) if selected_count > 1
                else _("Delete this item? {}").format(names_display)
            )
            if wx.MessageBox(message, _("Confirm Delete"), wx.YES_NO | wx.ICON_WARNING) != wx.YES:
                self.announce(_("Delete cancelled."))
                return

        deleted_count = 0
        items_to_remove_from_selection = []

        for name in selected_names:
            path = self.current_path
            if self.settings.get_explorer_view_mode() == 'commander':
                if self.active_panel == 'left':
                    path = self.left_path
                else:
                    path = self.right_path
            item_path = os.path.join(path, name)
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)
                items_to_remove_from_selection.append(name)
                deleted_count += 1
            except Exception as e:
                wx.MessageBox(_("Could not delete {}: {}").format(name, e), _("Delete Error"), wx.OK | wx.ICON_ERROR)
                self.announce(_("Error deleting: {}").format(name))

        for item in items_to_remove_from_selection:
            if item in self.selected_items:
                self.selected_items.remove(item)

        if deleted_count > 0:
            play_delete_sound()
            self.populate_file_list(ctrl=ctrl)
            self.announce(_("Deleted {} of {} items.").format(deleted_count, selected_count))
        else:
            self.announce(_("Could not delete any items."))


    def on_settings(self, event):
        settings_dialog = SettingsDialog(self, self.settings)
        if settings_dialog.ShowModal() == wx.ID_OK:
            self.view_settings = self.settings.get_view_settings()
            self.show_hidden = self.settings.get_show_hidden()
            self.show_extensions = self.settings.get_show_extensions()
            self.sort_mode = self.settings.get_sort_mode()
            self.refresh_interface()
            self.update_window_title()
            self.announce(_("Settings saved and applied."))
        else:
            self.announce(_("Settings cancelled."))
        settings_dialog.Destroy()

    def on_sort_by_name(self, event):
        self.settings.set_sort_mode('name')
        self.sort_mode = 'name'
        self.populate_file_list()
        self.announce(_("Sorted by name."))

    def on_sort_by_date(self, event):
        self.settings.set_sort_mode('date')
        self.sort_mode = 'date'
        self.populate_file_list()
        self.announce(_("Sorted by date modified."))

    def on_sort_by_type(self, event):
        self.settings.set_sort_mode('type')
        self.sort_mode = 'type'
        self.populate_file_list()
        self.announce(_("Sorted by type."))


    def refresh_interface(self):
        current_view_mode = self.settings.get_explorer_view_mode()
        active_ctrl = self.get_active_list_ctrl()

        needs_recreate = False
        if current_view_mode == "list" and (active_ctrl is None or not isinstance(active_ctrl, wx.ListCtrl) or hasattr(self, 'notebook') or hasattr(self, 'left_list')):
            needs_recreate = True
        elif current_view_mode == "commander" and (active_ctrl is None or not hasattr(self, 'left_list')):
            needs_recreate = True
        elif current_view_mode == "multi-tab" and (active_ctrl is None or not hasattr(self, 'notebook')):
            needs_recreate = True
        elif current_view_mode == "classic" and (active_ctrl is None or not isinstance(active_ctrl, wx.ListCtrl) or hasattr(self, 'notebook') or hasattr(self, 'left_list')):
            needs_recreate = True

        if needs_recreate:
            self.Destroy()
            frame = FileManager()
            frame.Show()
        else:
            if active_ctrl:
                self.update_file_list_columns(ctrl=active_ctrl)
                self.populate_file_list(ctrl=active_ctrl)


    def get_active_list_ctrl(self):
        explorer_view_mode = self.settings.get_explorer_view_mode()
        if explorer_view_mode == "commander":
            if hasattr(self, 'left_list') and self.left_list.HasFocus():
                return self.left_list
            elif hasattr(self, 'right_list') and self.right_list.HasFocus():
                return self.right_list
            else:
                return getattr(self, 'left_list', None)
        elif explorer_view_mode == "multi-tab":
            if hasattr(self, 'notebook'):
                current_page = self.notebook.GetCurrentPage()
                if current_page:
                    for child in current_page.GetChildren():
                        if isinstance(child, wx.ListCtrl):
                            return child
            return None
        else:
            if hasattr(self, 'file_list'):
                return self.file_list
            return None


    # --- Commander Mode Handlers ---

    def on_open_commander_left(self, event):
        self.on_open_commander(event, 'left')

    def on_open_commander_right(self, event):
        self.on_open_commander(event, 'right')

    def on_open_commander(self, event, panel_side):
        """Handle folder/file activation in commander mode.
        Works with both wx.ListEvent (double-click) and wx.KeyEvent (Enter key).
        """
        ctrl = self.left_list if panel_side == 'left' else self.right_list
        if isinstance(event, wx.ListEvent):
            item_index = event.GetIndex()
        else:
            item_index = ctrl.GetFocusedItem()

        if item_index == -1:
            return

        name = ctrl.GetItemText(item_index)
        if name == _('This folder is empty'):
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Folder is empty."))
            return

        if self.is_drive_selection_mode:
            selected_drive = name
            if os.path.exists(selected_drive):
                if panel_side == 'left':
                    self.left_path = selected_drive
                else:
                    self.right_path = selected_drive
                self.is_drive_selection_mode = False
                self.populate_file_list(ctrl=ctrl)
                self.update_window_title()
                play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
            else:
                play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                self.announce(_("Selected drive does not exist: {}").format(selected_drive))
            return

        path = self.left_path if panel_side == 'left' else self.right_path
        real_path = os.path.join(path, name)

        if os.path.isdir(real_path):
            if panel_side == 'left':
                self.left_path = real_path
                self.left_selected_items.clear()
            else:
                self.right_path = real_path
                self.right_selected_items.clear()
            self.populate_file_list(ctrl=ctrl, path=real_path)
            self.update_window_title()
            play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
        elif os.path.exists(real_path):
            try:
                self.open_file_in_system(real_path)
                play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
                self.announce(_("Opened: {}").format(name))
            except Exception as e:
                wx.MessageBox(_("Could not open {}: {}").format(name, e), _("Open Error"), wx.OK | wx.ICON_ERROR)
                play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                self.announce(_("Error opening: {}").format(name))
        else:
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Item not found: {}").format(name))

    def on_key_down_commander_left(self, event):
        self.on_key_down_commander(event, 'left')

    def on_key_down_commander_right(self, event):
        self.on_key_down_commander(event, 'right')

    def on_key_down_commander(self, event, panel_side):
        ctrl = self.left_list if panel_side == 'left' else self.right_list
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_BACK:
            self.go_back()

        elif keycode == wx.WXK_RETURN:
            # Pass the key event directly; on_open_commander handles KeyEvent correctly
            self.on_open_commander(event, panel_side)

        elif keycode == wx.WXK_SPACE:
            item_index = ctrl.GetFocusedItem()
            if item_index != -1:
                name = ctrl.GetItemText(item_index)
                if name != _('This folder is empty'):
                    selected_items = self.left_selected_items if panel_side == 'left' else self.right_selected_items
                    if name in selected_items:
                        selected_items.remove(name)
                        ctrl.Select(item_index, 0)
                        self.announce(_("Deselected: {}. Total: {}").format(name, len(selected_items)))
                    else:
                        selected_items.add(name)
                        ctrl.Select(item_index)
                        self.announce(_("Selected: {}. Total: {}").format(name, len(selected_items)))
                else:
                    play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                    self.announce(_("Cannot select this entry."))
            event.Skip()

        elif keycode == wx.WXK_F5:
            self.copy_to_other_panel_commander(panel_side)

        elif keycode == wx.WXK_F6:
            self.move_to_other_panel_commander(panel_side)

        else:
            event.Skip()

    def on_item_selected_commander_left(self, event):
        self.on_item_selected_commander(event, 'left')

    def on_item_deselected_commander_left(self, event):
        self.on_item_deselected_commander(event, 'left')

    def on_item_selected_commander_right(self, event):
        self.on_item_selected_commander(event, 'right')

    def on_item_deselected_commander_right(self, event):
        self.on_item_deselected_commander(event, 'right')

    def on_item_selected_commander(self, event, panel_side):
        item_index = event.GetItem().GetId()
        ctrl = self.left_list if panel_side == 'left' else self.right_list
        name = ctrl.GetItemText(item_index)
        if name != _('This folder is empty'):
            selected_items = self.left_selected_items if panel_side == 'left' else self.right_selected_items
            selected_items.add(name)
        event.Skip()

    def on_item_deselected_commander(self, event, panel_side):
        item_index = event.GetItem().GetId()
        ctrl = self.left_list if panel_side == 'left' else self.right_list
        name = ctrl.GetItemText(item_index)
        selected_items = self.left_selected_items if panel_side == 'left' else self.right_selected_items
        if name in selected_items:
            selected_items.remove(name)
        event.Skip()


    def on_focus_commander(self, event):
        ctrl = event.GetEventObject()
        if ctrl == self.left_list:
            self.active_panel = 'left'
        else:
            self.active_panel = 'right'
        self.update_panel_styles()
        event.Skip()

    def update_panel_styles(self):
        if not hasattr(self, 'left_list'):
            return

        active_color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
        inactive_color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)

        if self.active_panel == 'left':
            self.left_list.SetBackgroundColour(active_color)
            self.right_list.SetBackgroundColour(inactive_color)
        else:
            self.left_list.SetBackgroundColour(inactive_color)
            self.right_list.SetBackgroundColour(active_color)

        self.left_list.Refresh()
        self.right_list.Refresh()

    def copy_to_other_panel_commander(self, panel_side):
        """Copy selected files from current panel to other panel (F5)"""
        src_path = self.left_path if panel_side == 'left' else self.right_path
        dst_path = self.right_path if panel_side == 'left' else self.left_path

        selected_items = self.left_selected_items if panel_side == 'left' else self.right_selected_items

        if not selected_items:
            ctrl = self.left_list if panel_side == 'left' else self.right_list
            item_index = ctrl.GetFocusedItem()
            if item_index != -1:
                name = ctrl.GetItemText(item_index)
                if name != _('This folder is empty'):
                    selected_items = {name}
                else:
                    play_error_sound()
                    self.announce(_("No files to copy."))
                    return
            else:
                play_error_sound()
                self.announce(_("No files to copy."))
                return

        copied_count = 0
        error_count = 0

        for item_name in selected_items:
            src_file = os.path.join(src_path, item_name)
            dst_file = os.path.join(dst_path, item_name)
            try:
                if os.path.isdir(src_file):
                    shutil.copytree(src_file, dst_file, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_file, dst_file)
                copied_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error copying {item_name}: {e}")

        selected_items.clear()

        self.populate_file_list(ctrl=self.left_list)
        self.populate_file_list(ctrl=self.right_list)

        if error_count > 0:
            play_error_sound()
            self.announce(_("Copied {} files, {} errors.").format(copied_count, error_count))
        else:
            play_sound(os.path.join(get_sfx_directory(), 'copy.ogg'))
            self.announce(_("Copied {} files.").format(copied_count))

    def move_to_other_panel_commander(self, panel_side):
        """Move selected files from current panel to other panel (F6)"""
        src_path = self.left_path if panel_side == 'left' else self.right_path
        dst_path = self.right_path if panel_side == 'left' else self.left_path

        selected_items = self.left_selected_items if panel_side == 'left' else self.right_selected_items

        if not selected_items:
            ctrl = self.left_list if panel_side == 'left' else self.right_list
            item_index = ctrl.GetFocusedItem()
            if item_index != -1:
                name = ctrl.GetItemText(item_index)
                if name != _('This folder is empty'):
                    selected_items = {name}
                else:
                    play_error_sound()
                    self.announce(_("No files to move."))
                    return
            else:
                play_error_sound()
                self.announce(_("No files to move."))
                return

        moved_count = 0
        error_count = 0

        for item_name in selected_items:
            src_file = os.path.join(src_path, item_name)
            dst_file = os.path.join(dst_path, item_name)
            try:
                shutil.move(src_file, dst_file)
                moved_count += 1
            except Exception as e:
                error_count += 1
                print(f"Error moving {item_name}: {e}")

        selected_items.clear()

        self.populate_file_list(ctrl=self.left_list)
        self.populate_file_list(ctrl=self.right_list)

        if error_count > 0:
            play_error_sound()
            self.announce(_("Moved {} files, {} errors.").format(moved_count, error_count))
        else:
            play_sound(os.path.join(get_sfx_directory(), 'move.ogg'))
            self.announce(_("Moved {} files.").format(moved_count))

    # --- End Commander Mode Handlers ---


if __name__ == '__main__':
    app = wx.App()
    initialize_sound()
    play_startup_sound()

    frame = FileManager()
    frame.Show()
    app.MainLoop()
