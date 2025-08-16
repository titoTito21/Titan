# TFM/gui.py
import sys
import os
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

def _get_drives():
    drives = []
    if platform.system() == "Windows":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append(drive)
    return drives

# Inicjalizacja pygame do dźwięku
# Initialize sound AFTER wx.App is created in tfm.py (handled there now)
# initialize_sound()

def get_app_sfx_path():
    # This function is likely not needed anymore if get_sfx_directory handles resource_path
    return get_sfx_directory() # Use the function from sound.py

class FileManager(wx.Frame):
    def __init__(self, initial_path=None):
        wx.Frame.__init__(self, None, title=_("Menedżer Plików"), size=(800, 600))
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
        self.is_drive_selection_mode = False # New flag for drive selection mode

        self.view_settings = self.settings.get_view_settings()
        self.show_hidden = self.settings.get_show_hidden()
        self.show_extensions = self.settings.get_show_extensions()
        self.sort_mode = self.settings.get_sort_mode()

        # Validate initial path and switch to drive selection mode if path is invalid
        if not os.path.isdir(self.current_path):
            self.is_drive_selection_mode = True
            self.announce(_("Nie można uzyskać dostępu do ostatniego katalogu. Przełączam na widok wyboru dysku."))

        # Removed direct TTS initialization
        # self.init_tts()

        # Panel główny
        panel = wx.Panel(self)

        # Text for screen reader announcements (this will be used for announcements)
        # Position it visibly or ensure it's in a layout that screen readers can access if not off-screen
        # Keeping it off-screen but in the sizer might work for some screen readers
        self.status_text = wx.StaticText(panel, label="")
        # Consider adding wx.StaticText to a sizer to make it part of the layout,
        # even if its position is set off-screen, to help screen readers detect it.
        # For now, keeping the off-screen position as it was.
        self.status_text.SetPosition((-1000, -1000))


        # Menu
        menubar = wx.MenuBar()

        file_menu = create_file_menu(self)
        edit_menu = create_edit_menu(self)
        view_menu = create_view_menu(self)

        menubar.Append(file_menu, _('&Plik'))
        menubar.Append(edit_menu, _('&Edycja'))
        menubar.Append(view_menu, _('&Widok'))

        self.SetMenuBar(menubar)

        # W zależności od trybu widoku eksploratora tworzony jest odpowiedni interfejs
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        explorer_view_mode = self.settings.get_explorer_view_mode()

        if explorer_view_mode == "lista":
            self.file_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list() # Call populate_file_list without ctrl, it will use self.file_list
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
            self.populate_file_list(ctrl=self.left_list) # Populate left list initially
            # self.populate_file_list(ctrl=self.right_list) # Decide how to handle the right list's initial path

            commander_sizer = wx.BoxSizer(wx.HORIZONTAL)
            commander_sizer.Add(self.left_list, 1, wx.EXPAND | wx.ALL, 5)
            commander_sizer.Add(self.right_list, 1, wx.EXPAND | wx.ALL, 5)
            self.main_sizer.Add(commander_sizer, 1, wx.EXPAND)

            # Bind events for commander mode - need to handle selected_items for each list separately
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


        elif explorer_view_mode == "wiele kart":
            self.notebook = wx.Notebook(panel)
            # Need to manage list controls within each tab page
            self.file_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT | wx.LC_SINGLE_SEL) # This will be the first tab's list
            self.update_file_list_columns()
            self.populate_file_list() # Call populate_file_list without ctrl, it will use the active list ctrl (the first tab's list)
            self.notebook.AddPage(self.file_list, _("Karta 1")) # Consider how to add/manage multiple tabs
            self.main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 10)

            # Bind events for the list control within the first tab
            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)
            self.file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
            self.file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)

            # Need to handle events for new tabs and their list controls when added


        else: # Tryb klasyczny (default)
            self.file_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list() # Call populate_file_list without ctrl, it will use self.file_list
            self.main_sizer.Add(self.file_list, 1, wx.EXPAND | wx.ALL, 10)

            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)
            self.file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
            self.file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)


        # Add status_text to the sizer, even if positioned off-screen, for potential accessibility
        # This placement might help screen readers detect the control.
        # main_sizer.Add(self.status_text, 0, wx.ALL, 10) # Removed from visible layout


        panel.SetSizer(self.main_sizer)

        # Skróty klawiaturowe
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('C'), wx.ID_COPY),
            (wx.ACCEL_CTRL, ord('X'), wx.ID_CUT),
            (wx.ACCEL_CTRL, ord('V'), wx.ID_PASTE),
            (wx.ACCEL_CTRL, ord('A'), wx.ID_SELECTALL),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, wx.ID_DELETE),
            (wx.ACCEL_NORMAL, wx.WXK_NUMPAD_DELETE, wx.ID_DELETE),
            # Use the custom ID for the Rename accelerator
            (wx.ACCEL_NORMAL, wx.WXK_F2, ID_RENAME)
        ])
        self.SetAcceleratorTable(accel_tbl)

        self.Bind(wx.EVT_MENU, self.on_copy, id=wx.ID_COPY)
        self.Bind(wx.EVT_MENU, self.on_cut, id=wx.ID_CUT)
        self.Bind(wx.EVT_MENU, self.on_paste, id=wx.ID_PASTE)
        self.Bind(wx.EVT_MENU, self.on_select_all, id=wx.ID_SELECTALL)
        self.Bind(wx.EVT_MENU, self.on_delete, id=wx.ID_DELETE)
        # Bind the custom ID for rename
        self.Bind(wx.EVT_MENU, self.on_rename, id=ID_RENAME)


        self.populate_file_list() # Initial population based on current_path or drive selection mode
        self.update_window_title()
        self.Show()

    def update_window_title(self):
        if self.is_drive_selection_mode:
            self.SetTitle(_("Wybór dysku"))
            return

        mode = self.settings.get_window_title_mode()
        path = self.current_path
        if self.settings.get_explorer_view_mode() == 'commander':
            if self.active_panel == 'left':
                path = self.left_path
            else:
                path = self.right_path

        if mode == 'nazwa katalogu':
            self.SetTitle(os.path.basename(path) or _("Menedżer Plików"))
        elif mode == 'ścieżka':
            self.SetTitle(path)
        else:
            # nazwa aplikacji
            self.SetTitle(_("Menedżer Plików"))

    def update_file_list_columns(self, ctrl=None):
        if ctrl is None:
            # Determine which list control to update based on the current view mode
            explorer_view_mode = self.settings.get_explorer_view_mode()
            if explorer_view_mode == "commander":
                 # In commander mode, need to decide which panel to update or update both
                 # For now, let's assume this is called to update the currently focused list
                 # This will need refinement based on actual focus
                 if hasattr(self, 'left_list') and self.left_list.HasFocus():
                     ctrl = self.left_list
                 elif hasattr(self, 'right_list') and self.right_list.HasFocus():
                     ctrl = self.right_list
                 else:
                     # Default to left list if no list has focus in commander mode
                     ctrl = self.left_list
            elif explorer_view_mode == "wiele kart":
                 # In many tabs mode, update the list control in the currently selected tab
                 ctrl = self.get_active_list_ctrl() # Use the helper to get the list from the current tab
            else: # lista or klasyczny
                 ctrl = self.file_list

        if ctrl is None: return # Avoid errors if no list control is determined

        ctrl.ClearAll()
        col_index = 0
        if 'name' in self.view_settings:
            ctrl.InsertColumn(col_index, _('Nazwa'), width=300)
            col_index += 1
        if 'date' in self.view_settings:
            ctrl.InsertColumn(col_index, _('Data modyfikacji'), width=200)
            col_index += 1
        if 'type' in self.view_settings:
            ctrl.InsertColumn(col_index, _('Typ'), width=100)

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
             # Determine which list control to populate based on the current view mode
            explorer_view_mode = self.settings.get_explorer_view_mode()
            if explorer_view_mode == "commander":
                 # In commander mode, need to decide which panel to update or update both
                 # For now, assume this populates the left list by default, using self.current_path
                 ctrl = self.left_list
                 # Note: Commander mode would ideally have separate paths for left and right panels
                 # current_path_to_list = self.left_panel_path # Example for separate paths
            elif explorer_view_mode == "wiele kart":
                 # In many tabs mode, populate the list control in the currently selected tab
                 ctrl = self.get_active_list_ctrl() # Use the helper to get the list from the current tab
                 # Note: Many tabs mode would ideally have separate paths for each tab
                 # current_path_to_list = self.get_path_for_tab(self.notebook.GetSelection()) # Example for separate paths
            else: # lista or klasyczny
                 ctrl = self.file_list
                 # current_path_to_list = self.current_path # Already set at the beginning of the method


        if ctrl is None: return # Avoid errors if no list control is determined

        ctrl.DeleteAllItems()
        self.selected_items.clear() # Clear selections when repopulating
        # No need to call update_display_names here as items are newly inserted without the prefix

        if self.is_drive_selection_mode:
            drives = _get_drives()
            if not drives:
                index = ctrl.InsertItem(ctrl.GetItemCount(), _('Brak dostępnych dysków'))
            else:
                for drive in drives:
                    index = ctrl.InsertItem(ctrl.GetItemCount(), drive)
                    # Uzułnij ewentualnie pozostałe kolumny pustymi danymi
                    if 'date' in self.view_settings:
                        col_index_date = -1
                        for i in range(ctrl.GetColumnCount()):
                            if ctrl.GetColumn(i).GetText() == _('Data modyfikacji'):
                                col_index_date = i
                                break
                        if col_index_date != -1:
                            ctrl.SetItem(index, col_index_date, '')

                    if 'type' in self.view_settings:
                        col_index_type = -1
                        for i in range(ctrl.GetColumnCount()):
                            if ctrl.GetColumn(i).GetText() == _('Typ'):
                                col_index_type = i
                                break
                        if col_index_type != -1:
                            ctrl.SetItem(index, col_index_type, _('Dysk'))
            if ctrl.GetItemCount() > 0:
                ctrl.Select(0)
                ctrl.Focus(0)
            return

        try:
            # Use the determined path for listing
            entries = os.listdir(current_path_to_list)
            if not self.show_hidden:
                entries = [e for e in entries if not e.startswith('.')]
            entries = [e for e in entries if e != '.DS_Store']  # Ignoruj .DS_Store na macOS

            if not entries:
                index = ctrl.InsertItem(ctrl.GetItemCount(), _('Ten folder jest pusty'))
                # Uzułnij ewentualnie pozostałe kolumny pustymi danymi
                if 'date' in self.view_settings:
                    # Find the column index for 'date' using the corrected method
                    col_index_date = -1
                    for i in range(ctrl.GetColumnCount()):
                        # Corrected: Use GetColumn(i).GetText()
                        if ctrl.GetColumn(i).GetText() == _('Data modyfikacji'):
                            col_index_date = i
                            break
                    if col_index_date != -1:
                         ctrl.SetItem(index, col_index_date, '')

                if 'type' in self.view_settings:
                     # Find the column index for 'type' using the corrected method
                     col_index_type = -1
                     for i in range(ctrl.GetColumnCount()):
                         # Corrected: Use GetColumn(i).GetText()
                         if ctrl.GetColumn(i).GetText() == _('Typ'):
                             col_index_type = i
                             break
                     if col_index_type != -1:
                          ctrl.SetItem(index, col_index_type, '')


            else:
                if self.sort_mode == 'name':
                    # Use current_path_to_list for joining
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(current_path_to_list, x)), x.lower()))
                elif self.sort_mode == 'date':
                    # Use current_path_to_list for joining
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(current_path_to_list, x)), os.path.getmtime(os.path.join(current_path_to_list, x))))
                elif self.sort_mode == 'type':
                    # Use current_path_to_list for joining
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(current_path_to_list, x)), os.path.splitext(x.lower())[1], x.lower()))

                for entry in entries:
                    # Use current_path_to_list for joining
                    path = os.path.join(current_path_to_list, entry)
                    modified = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
                    entry_type = _('Folder') if os.path.isdir(path) else _('Plik')
                    display_name = entry if self.show_extensions else os.path.splitext(entry)[0]
                    index = ctrl.InsertItem(ctrl.GetItemCount(), display_name)

                    # Populate other columns based on the current view settings and their column index
                    col_index = 0 # Reset column index for each item

                    if 'name' in self.view_settings:
                        # Name is always the first column (index 0) because it's inserted first
                        pass # Name is already set by InsertItem
                        col_index += 1 # Increment for the next potential column

                    if 'date' in self.view_settings:
                        # Find the column index for 'date' using the corrected method
                        col_index_date = -1
                        for i in range(ctrl.GetColumnCount()):
                             # Corrected: Use GetColumn(i).GetText()
                            if ctrl.GetColumn(i).GetText() == _('Data modyfikacji'):
                                col_index_date = i
                                break
                        if col_index_date != -1:
                            ctrl.SetItem(index, col_index_date, modified)


                    if 'type' in self.view_settings:
                        # Find the column index for 'type' using the corrected method
                        col_index_type = -1
                        for i in range(ctrl.GetColumnCount()):
                            # Corrected: Use GetColumn(i).GetText()
                            if ctrl.GetColumn(i).GetText() == _('Typ'):
                                col_index_type = i
                                break
                        if col_index_type != -1:
                            ctrl.SetItem(index, col_index_type, entry_type)


                # Reselect items that were selected before repopulating if they still exist
                items_to_reselect = [i for i in range(ctrl.GetItemCount())
                                      # Get the actual name without any prefixes for comparison
                                      if ctrl.GetItemText(i) in self.selected_items # Simplified check now that prefix is removed
                                      and ctrl.GetItemText(i) != _('Ten folder jest pusty')]
                for i in items_to_reselect:
                     ctrl.Select(i)

                if ctrl.GetItemCount() > 0 and not items_to_reselect:
                   # Select the first item if the list is not empty and no previous items were reselected
                   ctrl.Select(0)
                   ctrl.Focus(0) # Set focus to the first item


        except PermissionError:
            wx.MessageBox(_("Brak dostępu do katalogu"), _("Błąd"), wx.OK | wx.ICON_ERROR)
            self.announce(_("Brak dostępu do katalogu."))
            # Optionally, navigate back to the previous directory or a default directory
            if self.current_path != os.path.expanduser("~"):
                 self.current_path = os.path.dirname(self.current_path)
                 self.populate_file_list(ctrl=ctrl) # Repopulate with the parent directory
                 self.update_window_title()

    # Removed update_display_names and _update_list_display_names as the prefix is no longer used
    # def update_display_names(self, ctrl=None):
    #    ...
    # def _update_list_display_names(self, ctrl):
    #    ...


    def announce(self, message):
        # Update the status text label. Screen readers should pick this up.
        self.status_text.SetLabel(message)
        # print(f"Announcement: {message}") # Optional: Print announcements to console
        # Direct TTS removed as requested
        # self.speak(message)


    # Removed init_tts and speak_dummy as direct TTS is no longer used
    # def init_tts(self):
    # ...
    # def speak_dummy(self, text):
    # ...


    def on_exit(self, event):
        self.Close()

    def on_new_file(self, event):
        dlg = wx.TextEntryDialog(self, _('Podaj nazwę nowego pliku:'), _('Nowy Plik'))
        if dlg.ShowModal() == wx.ID_OK:
            file_name = dlg.GetValue()
            if file_name: # Check if the user entered a file name
                new_file_path = os.path.join(self.current_path, file_name)
                try:
                    open(new_file_path, 'w').close()
                    self.populate_file_list()
                    self.announce(_("Utworzono nowy plik {}").format(file_name))
                except Exception as e:
                    wx.MessageBox(_("Nie udało się utworzyć pliku {}: {}").format(file_name, e), _("Błąd Tworzenia Pliku"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Błąd tworzenia pliku {}").format(file_name))

        dlg.Destroy()

    def on_new_folder(self, event):
        dlg = wx.TextEntryDialog(self, _('Podaj nazwę nowego folderu:'), _('Nowy Folder'))
        if dlg.ShowModal() == wx.ID_OK:
            folder_name = dlg.GetValue()
            if folder_name: # Check if the user entered a folder name
                new_folder_path = os.path.join(self.current_path, folder_name)
                try:
                    os.makedirs(new_folder_path, exist_ok=True)
                    self.populate_file_list()
                    self.announce(_("Utworzono nowy folder {}").format(folder_name))
                except Exception as e:
                    wx.MessageBox(_("Nie udało się utworzyć folderu {}: {}").format(folder_name, e), _("Błąd Tworzenia Folderu"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Błąd tworzenia folderu {}").format(folder_name))
        dlg.Destroy()

    def on_rename(self, event):
        # Determine which list control is active
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("Brak aktywnej listy plików do zmiany nazwy."))
            return

        item_index = ctrl.GetFocusedItem()
        if item_index != -1:
            # Get the actual name without expecting any prefix
            old_name = ctrl.GetItemText(item_index)

            if old_name == _('Ten folder jest pusty'):
                 self.announce(_("Nie można zmienić nazwy wpisu 'Ten folder jest pusty'."))
                 return

            # Find the real file name with extension if extensions are hidden
            real_old_name = old_name
            if not self.show_extensions and os.path.splitext(old_name)[1] == '':
                 # Try to find the real file name with extension in the current directory
                 # Prioritize exact match of base name
                 matches = [entry for entry in os.listdir(self.current_path) if os.path.splitext(entry)[0] == old_name]
                 if matches:
                     # If there are multiple matches, just take the first one found by listdir
                     real_old_name = matches[0]
                 else:
                     # If no match with extension, assume the name as is (might be a directory or file without extension)
                     pass


            dlg = wx.TextEntryDialog(self, _("Podaj nową nazwę:"), _("Zmiana nazwy"), real_old_name) # Use real_old_name for the dialog
            if dlg.ShowModal() == wx.ID_OK:
                new_name = dlg.GetValue()
                if new_name and new_name != real_old_name:
                    old_path = os.path.join(self.current_path, real_old_name)
                    new_path = os.path.join(self.current_path, new_name)
                    try:
                        os.rename(old_path, new_path)
                        # If the renamed item was selected, update the selected_items set
                        if real_old_name in self.selected_items:
                            self.selected_items.remove(real_old_name)
                            self.selected_items.add(new_name)

                        self.populate_file_list(ctrl=ctrl) # Repopulate the active list
                        self.announce(_("Zmieniono nazwę z {} na {}").format(real_old_name, new_name))
                    except Exception as e:
                        wx.MessageBox(str(e), _("Błąd zmiany nazwy"), wx.OK | wx.ICON_ERROR)
                        self.announce(_("Błąd zmiany nazwy {}").format(real_old_name))
                elif new_name == real_old_name:
                     self.announce(_("Nazwa nie została zmieniona."))
                else:
                     self.announce(_("Anulowano zmianę nazwy."))
            else:
                 self.announce(_("Anulowano zmianę nazwy."))
            dlg.Destroy()
        else:
            self.announce(_("Nie wybrano elementu do zmiany nazwy."))


    def on_copy(self, event):
        # Determine which list control is active
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("Brak aktywnej listy plików do skopiowania."))
            return

        # Get selected names without expecting any prefix
        selected_names = {ctrl.GetItemText(i)
                          for i in range(ctrl.GetItemCount()) if ctrl.IsSelected(i)
                          and ctrl.GetItemText(i) != _('Ten folder jest pusty')}


        if selected_names:
            path = self.current_path
            if self.settings.get_explorer_view_mode() == 'commander':
                if self.active_panel == 'left':
                    path = self.left_path
                else:
                    path = self.right_path
            # Store full paths and action in clipboard
            self.clipboard = [(os.path.join(path, name), 'copy') for name in selected_names]
            self.announce(_("Skopiowano {} elementów do schowka.").format(len(selected_names)))
        else:
            self.clipboard = []
            self.announce(_("Nie wybrano elementów do skopiowania."))


    def on_cut(self, event):
        # Determine which list control is active
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("Brak aktywnej listy plików do wycięcia."))
            return

        # Get selected names without expecting any prefix
        selected_names = {ctrl.GetItemText(i)
                          for i in range(ctrl.GetItemCount()) if ctrl.IsSelected(i)
                          and ctrl.GetItemText(i) != _('Ten folder jest pusty')}


        if selected_names:
            path = self.current_path
            if self.settings.get_explorer_view_mode() == 'commander':
                if self.active_panel == 'left':
                    path = self.left_path
                else:
                    path = self.right_path
            # Store full paths and action in clipboard
            self.clipboard = [(os.path.join(path, name), 'cut') for name in selected_names]
            self.announce(_("Wycięto {} elementów do schowka.").format(len(selected_names)))
        else:
            self.clipboard = []
            self.announce(_("Nie wybrano elementów do wycięcia."))


    def on_paste(self, event):
        if not self.clipboard:
            self.announce(_("Schowek jest pusty."))
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

        # Get the active list control before potential dialogs or operations
        ctrl = self.get_active_list_ctrl()


        if copy_dialog_mode == 'systemowy':
            for src in copy_files:
                dst = os.path.join(dst_folder, os.path.basename(src))
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True) # Use dirs_exist_ok for directories
                    else:
                        shutil.copy2(src, dst)
                except Exception as e:
                    wx.MessageBox(_("Błąd kopiowania {}: {}").format(os.path.basename(src), e), _("Błąd Kopiowania"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Błąd kopiowania {}").format(os.path.basename(src)))

            for src in move_files:
                dst = os.path.join(dst_folder, os.path.basename(src))
                try:
                    shutil.move(src, dst)
                except Exception as e:
                    wx.MessageBox(_("Błąd przenoszenia {}: {}").format(os.path.basename(src), e), _("Błąd Przenoszenia"), wx.OK | wx.ICON_ERROR)
                    self.announce(_("Błąd przenoszenia {}").format(os.path.basename(src)))

            # Clear clipboard only after attempting system operations
            self.clipboard = []
            self.populate_file_list(ctrl=ctrl_to_refresh)
            self.announce(_("Zakończono operację wklejania."))

        else:
            # klasyczny dialog with progress
            if copy_files:
                # The dialog and threading are handled in copy_move.py
                # The dialog should refresh the list upon completion
                copy_files_with_progress(self, copy_files, dst_folder) # Pass self as parent
                self.clipboard = [] # Clear clipboard when using classic dialog

            if move_files:
                # The dialog and threading are handled in copy_move.py
                # The dialog should refresh the list upon completion
                move_files_with_progress(self, move_files, dst_folder) # Pass self as parent
                self.clipboard = [] # Clear clipboard when using classic dialog

            if not copy_files and not move_files:
                 self.announce(_("Brak elementów do wklejenia w schowku."))
            # The list population and announcement will be handled by the dialog completion in copy_move.py


    def on_select_all(self, event):
        # Determine which list control is active
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("Brak aktywnej listy plików do zaznaczenia."))
            return

        self.selected_items.clear() # Clear existing selections
        items_selected_count = 0
        for i in range(ctrl.GetItemCount()):
            name = ctrl.GetItemText(i) # Get the actual item text
            if name != _('Ten folder jest pusty'):
                self.selected_items.add(name)
                ctrl.Select(i) # Select the item in the list control visually
                items_selected_count += 1


        # No longer update display names with prefix
        # self.update_display_names(ctrl=ctrl) # Update display names with '(wybrany)' prefix
        if items_selected_count > 0:
            self.announce(_("Zaznaczono wszystkie ({}) elementy.").format(items_selected_count))
        else:
            self.announce(_("Brak elementów do zaznaczenia w obecnym folderze."))


    def on_item_selected(self, event):
        # Handle item selection for single list mode
        item_index = event.GetItem().GetId()
        ctrl = event.GetEventObject() # Get the list control that triggered the event
        name = ctrl.GetItemText(item_index) # Get the actual item text
        if name != _('Ten folder jest pusty'):
            self.selected_items.add(name)
            # No longer update display names with prefix
            # self.update_display_names(ctrl=ctrl)
            # Optional: Announce selection change
            # self.announce(f"Wybrano: {name}. Razem: {len(self.selected_items)}")
        event.Skip() # Allows other handlers (like OnActivate) to also process

    def on_item_deselected(self, event):
        # Handle item deselection for single list mode
        item_index = event.GetItem().GetId()
        ctrl = event.GetEventObject() # Get the list control that triggered the event
        name = ctrl.GetItemText(item_index) # Get the actual item text
        if name in self.selected_items:
            self.selected_items.remove(name)
            # No longer update display names with prefix
            # self.update_display_names(ctrl=ctrl)
            # Optional: Announce deselection change
            # self.announce(f"Odznaczono: {name}. Razem: {len(self.selected_items)}")
        event.Skip()


    def on_open(self, event):
        # Handle item activation for single list mode (triggered by double-click or Enter key)
        # The event object can be a wx.ListEvent (from double-click) or a wx.KeyEvent (from Enter key)
        # We need to get the item index regardless of the event type.

        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("Brak aktywnej listy plików do otwarcia."))
            return

        item_index = -1
        # Check if the event is a ListEvent (double-click)
        if isinstance(event, wx.ListEvent):
            item_index = event.GetItem().GetId()
        # Check if the event is a KeyEvent (Enter key)
        elif isinstance(event, wx.KeyEvent):
            # When triggered by a key event, get the focused item
            item_index = ctrl.GetFocusedItem()


        if item_index != -1:
            # Get the actual name without expecting any prefix
            name = ctrl.GetItemText(item_index)

            if name == _('Ten folder jest pusty'):
                play_sound(os.path.join(get_sfx_directory(), 'error.ogg')) # Play error sound
                self.announce(_("Folder jest pusty."))
                return

            if self.is_drive_selection_mode:
                selected_drive = name
                if os.path.exists(selected_drive):
                    self.current_path = selected_drive
                    self.is_drive_selection_mode = False
                    self.populate_file_list(ctrl=ctrl)
                    self.update_window_title()
                    play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
                    self.announce(_("Przejście na dysk: {}").format(selected_drive))
                else:
                    play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                    self.announce(_("Wybrany dysk nie istnieje: {}").format(selected_drive))
                return

            # Find the real path, considering hidden extensions
            real_path = os.path.join(self.current_path, name)
            if not self.show_extensions and os.path.splitext(name)[1] == '':
                 # Try to find the real file name with extension in the current directory
                 found_match = False
                 for entry in os.listdir(self.current_path):
                     if os.path.splitext(entry)[0] == name:
                         real_path = os.path.join(self.current_path, entry)
                         found_match = True
                         break
                 if not found_match:
                      # If no match found with extension, assume the name as is (might be a directory or file without extension)
                      pass


            if os.path.isdir(real_path):
                # Clear selected items when navigating into a directory
                self.selected_items.clear()
                self.current_path = real_path
                self.populate_file_list(ctrl=ctrl) # Populate the list in the current view mode
                self.update_window_title()
                play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
                self.announce(_("Otwarto folder: {}").format(name))
            elif os.path.exists(real_path): # Check if it's a file and exists
                try:
                    self.open_file_in_system(real_path)
                    play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
                    self.announce(_("Otwarto plik: {}").format(name))
                except Exception as e:
                    wx.MessageBox(_("Nie udało się otworzyć pliku {}: {}").format(name, e), _("Błąd Otwierania Pliku"), wx.OK | wx.ICON_ERROR)
                    play_sound(os.path.join(get_sfx_directory(), 'error.ogg')) # Play error sound
                    self.announce(_("Błąd otwierania pliku: {}").format(name))
            else:
                 play_sound(os.path.join(get_sfx_directory(), 'error.ogg')) # Play error sound
                 self.announce(_("Element nie istnieje: {}").format(name))
        else:
            # This case should ideally not happen if triggered by key/list event on an item
            self.announce(_("Nie wybrano elementu do otwarcia."))


    def open_file_in_system(self, path):
        system = platform.system()
        try:
            if system == 'Windows':
                os.startfile(path)
            elif system == 'Darwin':  # macOS
                # Using subprocess.run is generally preferred over os.system for better control and security
                # import subprocess
                # subprocess.run(['open', path])
                os.system(f'open "{path}"') # Keep os.system for consistency with original code
            else:  # Linux
                # Using subprocess.run is generally preferred over os.system
                # import subprocess
                # subprocess.run(['xdg-open', path])
                os.system(f'xdg-open "{path}"') # Keep os.system for consistency with original code
        except Exception as e:
            print(f"System file open error for {path}: {e}") # Log the error
            raise # Re-raise the exception to be caught by the caller (on_open)


    def on_focus(self, event):
        play_sound(os.path.join(get_sfx_directory(), 'focus.ogg'))
        # When focus changes to the list control, announce the current directory and focused item if any
        ctrl = event.GetEventObject()
        focused_item_index = ctrl.GetFocusedItem()
        current_dir_annonce = _("Aktualny katalog: {}").format(os.path.basename(self.current_path) or self.current_path)
        if focused_item_index != -1:
             # Get the actual focused item name without expecting any prefix
             focused_item_name = ctrl.GetItemText(focused_item_index)
             self.announce(_("{}. Fokus na: {}.").format(current_dir_annonce, focused_item_name)) # Announce focus, not selection
        else:
             self.announce(current_dir_annonce)

        event.Skip()

    def on_key_down(self, event):
        # Handle key presses for single list mode
        ctrl = event.GetEventObject() # Get the list control that triggered the event
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_BACK:
            self.go_back()

        elif keycode == wx.WXK_F2:
            self.on_rename(None) # Trigger rename action (event=None is fine as on_rename gets active ctrl)

        elif keycode in [wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE]:
            self.on_delete(None) # Trigger delete action (event=None is fine as on_delete gets active ctrl)

        elif keycode == wx.WXK_RETURN:
            # Trigger the file open logic for the focused item
            self.on_open(event) # Pass the key event to on_open

        elif keycode == wx.WXK_SPACE:
            item_index = ctrl.GetFocusedItem()
            if item_index != -1:
                # Get the actual item name without expecting any prefix
                name = ctrl.GetItemText(item_index)

                if name != _('Ten folder jest pusty'):
                    if name in self.selected_items:
                        self.selected_items.remove(name)
                        # Deselect the item visually
                        ctrl.Select(item_index, 0)
                        self.announce(_("Odznaczono: {}. Razem: {}").format(name, len(self.selected_items)))
                    else:
                        self.selected_items.add(name)
                        # Select the item visually
                        ctrl.Select(item_index)
                        self.announce(_("Wybrano: {}. Razem: {}").format(name, len(self.selected_items)))
                else:
                     play_sound(os.path.join(get_sfx_directory(), 'error.ogg')) # Play error sound
                     self.announce(_("Nie można zaznaczyć wpisu 'Ten folder jest pusty'."))
            event.Skip() # Still allow default space behavior if any

        else:
            event.Skip() # Process other keys normally


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

        # Check if current_path is a drive root (e.g., 'C:\')
        is_drive_root = (len(current_path) == 3 and current_path[1] == ':' and current_path[2] == '\\')

        if self.is_drive_selection_mode:
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Jesteś w widoku wyboru dysku."))
            return

        if is_drive_root:
            self.is_drive_selection_mode = True
            self.populate_file_list(ctrl=active_ctrl)
            self.update_window_title()
            play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
            self.announce(_("Przejście do widoku wyboru dysku."))
        elif parent_path != current_path and os.path.isdir(parent_path):
            setattr(self, current_path_attr, parent_path)
            getattr(self, selected_items_attr).clear()
            
            self.populate_file_list(ctrl=active_ctrl, path=parent_path)
            
            # Find and select the item
            for i in range(active_ctrl.GetItemCount()):
                if active_ctrl.GetItemText(i) == folder_to_select:
                    active_ctrl.Select(i)
                    active_ctrl.Focus(i)
                    break
            
            self.update_window_title()
            play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
            self.announce(_("Przejście do katalogu nadrzędnego: {}")).format(os.path.basename(parent_path) or '/')
        else:
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Jesteś w katalogu głównym."))


    def on_delete(self, event=None):
        # Determine which list control is active
        ctrl = self.get_active_list_ctrl()
        if ctrl is None:
            self.announce(_("Brak aktywnej listy plików do usunięcia."))
            return

        selected_names = list(self.selected_items) # Work with a copy of selected items

        if not selected_names:
            self.announce(_("Nie wybrano elementów do usunięcia."))
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg')) # Play error sound
            return

        selected_count = len(selected_names)
        names_display = ', '.join(selected_names)

        # Potwierdzenie jeśli włączone
        if self.settings.get_confirm_delete():
            message = _("Czy na pewno chcesz usunąć te elementy? {}").format(names_display) if selected_count > 1 else _("Czy na pewno chcesz usunąć ten element? {}").format(names_display)
            if wx.MessageBox(message, _("Potwierdzenie Usunięcia"), wx.YES_NO | wx.ICON_WARNING) != wx.YES:
                self.announce(_("Anulowano usunięcie."))
                return

        deleted_count = 0
        items_to_remove_from_selection = [] # Track items successfully deleted to remove from self.selected_items

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
                items_to_remove_from_selection.append(name) # Mark for removal from selected_items
                deleted_count += 1
                self.announce(_("Usunięto: {}").format(name)) # Announce each deletion
            except Exception as e:
                wx.MessageBox(_("Nie udało się usunąć {}: {}").format(name, e), _("Błąd Usuwania"), wx.OK | wx.ICON_ERROR)
                self.announce(_("Błąd usuwania: {}").format(name)) # Announce deletion error

        # Remove successfully deleted items from the selected_items set
        for item in items_to_remove_from_selection:
            if item in self.selected_items:
                self.selected_items.remove(item)


        if deleted_count > 0:
            play_delete_sound() # Play a delete sound if any item was deleted
            self.populate_file_list(ctrl=ctrl) # Refresh the list after deletion
            self.announce(_("Usunięto {} z {} elementów.").format(deleted_count, selected_count))
        else:
            self.announce(_("Nie udało się usunąć żadnych elementów."))


    def on_settings(self, event):
        settings_dialog = SettingsDialog(self, self.settings)
        if settings_dialog.ShowModal() == wx.ID_OK:
            # Settings have been saved by the dialog, now apply them
            self.view_settings = self.settings.get_view_settings()
            self.show_hidden = self.settings.get_show_hidden()
            self.show_extensions = self.settings.get_show_extensions()
            self.sort_mode = self.settings.get_sort_mode()
            self.refresh_interface() # Refresh interface based on new settings
            self.update_window_title() # Update window title based on new setting
            self.announce(_("Ustawienia zapisane i zastosowane."))
        else:
            self.announce(_("Anulowano ustawienia."))

        settings_dialog.Destroy()

    def on_sort_by_name(self, event):
        self.settings.set_sort_mode('name')
        self.sort_mode = 'name'
        self.populate_file_list()
        self.announce(_("Sortowanie według nazwy."))

    def on_sort_by_date(self, event):
        self.settings.set_sort_mode('date')
        self.sort_mode = 'date'
        self.populate_file_list()
        self.announce(_("Sortowanie według daty modyfikacji."))


    def on_sort_by_type(self, event):
        self.settings.set_sort_mode('type')
        self.sort_mode = 'type'
        self.populate_file_list()
        self.announce(_("Sortowanie według typu."))


    def refresh_interface(self):
        # Dynamically update interface elements based on settings without recreating the frame
        current_view_mode = self.settings.get_explorer_view_mode()
        # Get the currently active list control before potentially destroying the old one
        active_ctrl = self.get_active_list_ctrl()

        # Check if the current panel/list structure matches the setting
        # If not, then destroy and recreate the frame
        # This is a simplification; a better approach would be dynamic sizer management.
        needs_recreate = False
        # Check if the current list control type matches the settings
        # If the current active control is None or its type doesn't match the setting, we might need to recreate.
        if current_view_mode == "lista" and (active_ctrl is None or not isinstance(active_ctrl, wx.ListCtrl) or hasattr(self, 'notebook') or hasattr(self, 'left_list')): needs_recreate = True
        elif current_view_mode == "commander" and (active_ctrl is None or not hasattr(self, 'left_list')): needs_recreate = True # Commander mode needs left_list and right_list
        elif current_view_mode == "wiele kart" and (active_ctrl is None or not hasattr(self, 'notebook')): needs_recreate = True # Many tabs needs a notebook
        elif current_view_mode == "klasyczny" and (active_ctrl is None or not isinstance(active_ctrl, wx.ListCtrl) or hasattr(self, 'notebook') or hasattr(self, 'left_list')): needs_recreate = True


        if needs_recreate:
             # This part retains the old behavior for structural changes
             # Ideally, this would be handled by dynamic sizer/panel swapping
             self.Destroy()
             frame = FileManager()
             frame.Show()
        else:
             # For settings that don't change the fundamental layout (columns, hidden, sort),
             # we just update the existing UI elements.
             if active_ctrl: # Only update if there is an active list control
                 self.update_file_list_columns(ctrl=active_ctrl) # Update columns based on view settings for the active control
                 self.populate_file_list(ctrl=active_ctrl) # Repopulate list with new view/sort settings and hidden/extensions
                 # No need to call update_display_names explicitly here as populate_file_list clears selections and rebuilds


    # Helper to get the currently active list control
    def get_active_list_ctrl(self):
        explorer_view_mode = self.settings.get_explorer_view_mode()
        if explorer_view_mode == "commander":
            # In commander mode, return the list that has focus
            if hasattr(self, 'left_list') and self.left_list.HasFocus():
                return self.left_list
            elif hasattr(self, 'right_list') and self.right_list.HasFocus():
                return self.right_list
            else:
                # If neither has focus, maybe return the last one interacted with or None
                # For commander, default to left list if no focus
                return getattr(self, 'left_list', None)
        elif explorer_view_mode == "wiele kart":
             if hasattr(self, 'notebook'):
                 # Return the list control within the currently selected page
                 current_page = self.notebook.GetCurrentPage()
                 if current_page:
                      # Assuming the list control is a direct child of the page
                      for child in current_page.GetChildren():
                          if isinstance(child, wx.ListCtrl):
                              return child
                 return None # Return None if no ListCtrl found in the current page or no page selected
             else:
                 return None
        else: # lista or klasyczny
             if hasattr(self, 'file_list'):
                 return self.file_list
             else:
                 return None


    # --- Commander Mode Handlers (Need Full Implementation) ---
    # Update these to call get_active_list_ctrl and perform actions on the relevant list
    # Need to manage current paths and selections for both left and right panels independently

    def on_open_commander_left(self, event):
        self.on_open_commander(event, 'left')

    def on_open_commander_right(self, event):
        self.on_open_commander(event, 'right')

    def on_open_commander(self, event, panel_side):
        ctrl = self.left_list if panel_side == 'left' else self.right_list
        item_index = event.GetItem().GetId()
        if item_index == -1:
            return

        name = ctrl.GetItemText(item_index)
        if name == _('Ten folder jest pusty'):
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Folder jest pusty."))
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
                self.announce(_("Przejście na dysk: {}").format(selected_drive))
            else:
                play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                self.announce(_("Wybrany dysk nie istnieje: {}").format(selected_drive))
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
            self.announce(_("Otwarto folder: {}").format(name))
        elif os.path.exists(real_path):
            try:
                self.open_file_in_system(real_path)
                play_sound(os.path.join(get_sfx_directory(), 'select.ogg'))
                self.announce(_("Otwarto plik: {}").format(name))
            except Exception as e:
                wx.MessageBox(_("Nie udało się otworzyć pliku {}: {}").format(name, e), _("Błąd Otwierania Pliku"), wx.OK | wx.ICON_ERROR)
                play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                self.announce(_("Błąd otwierania pliku: {}").format(name))
        else:
            play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
            self.announce(_("Element nie istnieje: {}").format(name))

        event.Skip()

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
            self.on_open_commander(event, panel_side)

        elif keycode == wx.WXK_SPACE:
            item_index = ctrl.GetFocusedItem()
            if item_index != -1:
                name = ctrl.GetItemText(item_index)
                if name != _('Ten folder jest pusty'):
                    selected_items = self.left_selected_items if panel_side == 'left' else self.right_selected_items
                    if name in selected_items:
                        selected_items.remove(name)
                        ctrl.Select(item_index, 0)
                        self.announce(_("Odznaczono: {}. Razem: {}").format(name, len(selected_items)))
                    else:
                        selected_items.add(name)
                        ctrl.Select(item_index)
                        self.announce(_("Wybrano: {}. Razem: {}").format(name, len(selected_items)))
                else:
                    play_sound(os.path.join(get_sfx_directory(), 'error.ogg'))
                    self.announce(_("Nie można zaznaczyć wpisu 'Ten folder jest pusty'."))
            event.Skip()

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
        if name != _('Ten folder jest pusty'):
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

    # --- End Commander Mode Handlers ---


if __name__ == '__main__':
    app = wx.App()
    # Initialize sound after wx.App is created
    initialize_sound()
    play_startup_sound()

    frame = FileManager()
    frame.Show()
    app.MainLoop()
