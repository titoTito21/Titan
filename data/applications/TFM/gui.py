import sys
import os
import wx
import datetime
import shutil
import pygame
import platform
from menu import create_file_menu, create_edit_menu, create_view_menu
from tfm_settings import SettingsManager, SettingsDialog
from copy_move import copy_files_with_progress, move_files_with_progress
from sound import play_sound, initialize_sound

# Inicjalizacja pygame do dźwięku
initialize_sound()

def get_app_sfx_path():
    return os.path.join(os.path.dirname(__file__), 'sfx')

class FileManager(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None, title="Menedżer Plików", size=(800, 600))
        self.settings = SettingsManager()
        self.current_path = os.path.expanduser("~")
        self.clipboard = []
        self.selected_items = set()

        self.view_settings = self.settings.get_view_settings()
        self.show_hidden = self.settings.get_show_hidden()
        self.show_extensions = self.settings.get_show_extensions()
        self.sort_mode = self.settings.get_sort_mode()

        self.init_tts()

        # Panel główny
        panel = wx.Panel(self)

        # Niewidzialny tekst do komunikatów dla screenreadera
        self.status_text = wx.StaticText(panel, label="", pos=(-1000, -1000))

        # Menu
        menubar = wx.MenuBar()

        file_menu = create_file_menu(self)
        edit_menu = create_edit_menu(self)
        view_menu = create_view_menu(self)

        menubar.Append(file_menu, '&Plik')
        menubar.Append(edit_menu, '&Edycja')
        menubar.Append(view_menu, '&Widok')

        self.SetMenuBar(menubar)

        # W zależności od trybu widoku eksploratora tworzony jest odpowiedni interfejs
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        explorer_view_mode = self.settings.get_explorer_view_mode()

        if explorer_view_mode == "lista":
            # Widok lista - pojedyncza lista, można go modyfikować wedle potrzeb
            self.file_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list()
            self.main_sizer.Add(self.file_list, 1, wx.EXPAND | wx.ALL, 10)

            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)

        elif explorer_view_mode == "commander":
            # Tryb commander - dwa panele obok siebie
            # Poniższa implementacja jest przykładowa.
            self.left_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.right_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)

            self.update_file_list_columns(ctrl=self.left_list)
            self.update_file_list_columns(ctrl=self.right_list)
            self.populate_file_list(ctrl=self.left_list)
            self.populate_file_list(ctrl=self.right_list)

            commander_sizer = wx.BoxSizer(wx.HORIZONTAL)
            commander_sizer.Add(self.left_list, 1, wx.EXPAND | wx.ALL, 5)
            commander_sizer.Add(self.right_list, 1, wx.EXPAND | wx.ALL, 5)
            self.main_sizer.Add(commander_sizer, 1, wx.EXPAND)

            # Obsługa zdarzeń - w tej wersji jedynie przykładowo
            self.left_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_commander_left)
            self.right_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_commander_right)
            self.left_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down_commander_left)
            self.right_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down_commander_right)

        elif explorer_view_mode == "wiele kart":
            # Tryb wiele kart - Notebook
            self.notebook = wx.Notebook(panel)
            self.file_list = wx.ListCtrl(self.notebook, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list()
            self.notebook.AddPage(self.file_list, "Karta 1")
            self.main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 10)

            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)

        else:
            # Tryb klasyczny - jak dotychczas
            self.file_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.update_file_list_columns()
            self.populate_file_list()
            self.main_sizer.Add(self.file_list, 1, wx.EXPAND | wx.ALL, 10)

            self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
            self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)

        self.main_sizer.Add(self.status_text, 0, wx.ALL, 10)
        panel.SetSizer(self.main_sizer)

        # Skróty klawiaturowe
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord('C'), wx.ID_COPY),
            (wx.ACCEL_CTRL, ord('X'), wx.ID_CUT),
            (wx.ACCEL_CTRL, ord('V'), wx.ID_PASTE),
            (wx.ACCEL_CTRL, ord('A'), wx.ID_SELECTALL),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, wx.ID_DELETE),
            (wx.ACCEL_NORMAL, wx.WXK_NUMPAD_DELETE, wx.ID_DELETE)
        ])
        self.SetAcceleratorTable(accel_tbl)

        self.Bind(wx.EVT_MENU, self.on_copy, id=wx.ID_COPY)
        self.Bind(wx.EVT_MENU, self.on_cut, id=wx.ID_CUT)
        self.Bind(wx.EVT_MENU, self.on_paste, id=wx.ID_PASTE)
        self.Bind(wx.EVT_MENU, self.on_select_all, id=wx.ID_SELECTALL)
        self.Bind(wx.EVT_MENU, self.on_delete, id=wx.ID_DELETE)

        self.update_window_title()
        self.Show()

    def update_window_title(self):
        mode = self.settings.get_window_title_mode()
        if mode == 'nazwa katalogu':
            self.SetTitle(os.path.basename(self.current_path) or "Menedżer Plików")
        elif mode == 'ścieżka':
            self.SetTitle(self.current_path)
        else:
            # nazwa aplikacji
            self.SetTitle("Menedżer Plików")

    def update_file_list_columns(self, ctrl=None):
        if ctrl is None:
            ctrl = self.file_list
        ctrl.ClearAll()
        col_index = 0
        if 'name' in self.view_settings:
            ctrl.InsertColumn(col_index, 'Nazwa', width=300)
            col_index += 1
        if 'date' in self.view_settings:
            ctrl.InsertColumn(col_index, 'Data modyfikacji', width=200)
            col_index += 1
        if 'type' in self.view_settings:
            ctrl.InsertColumn(col_index, 'Typ', width=100)

    def populate_file_list(self, ctrl=None):
        if ctrl is None:
            ctrl = self.file_list
        ctrl.DeleteAllItems()
        try:
            entries = os.listdir(self.current_path)
            if not self.show_hidden:
                entries = [e for e in entries if not e.startswith('.')]
            entries = [e for e in entries if e != '.DS_Store']  # Ignoruj .DS_Store na macOS
            if not entries:
                index = ctrl.InsertItem(ctrl.GetItemCount(), 'Ten folder jest pusty')
                # Uzupełnij ewentualnie pozostałe kolumny pustymi danymi
                if 'date' in self.view_settings:
                    ctrl.SetItem(index, 1, '')
                if 'type' in self.view_settings:
                    ctrl.SetItem(index, len(self.view_settings) - 1, '')
            else:
                if self.sort_mode == 'name':
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(self.current_path, x)), x.lower()))
                elif self.sort_mode == 'date':
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(self.current_path, x)), os.path.getmtime(os.path.join(self.current_path, x))))
                elif self.sort_mode == 'type':
                    entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(self.current_path, x)), os.path.splitext(x.lower())[1], x.lower()))

                for entry in entries:
                    path = os.path.join(self.current_path, entry)
                    modified = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
                    entry_type = 'Folder' if os.path.isdir(path) else 'Plik'
                    display_name = entry if self.show_extensions else os.path.splitext(entry)[0]
                    index = ctrl.InsertItem(ctrl.GetItemCount(), display_name)
                    col_index = 1
                    if 'date' in self.view_settings:
                        ctrl.SetItem(index, col_index, modified)
                        col_index += 1
                    if 'type' in self.view_settings:
                        ctrl.SetItem(index, col_index, entry_type)
                ctrl.Select(0)
        except PermissionError:
            wx.MessageBox("Brak dostępu do katalogu", "Błąd", wx.OK | wx.ICON_ERROR)

    def update_display_names(self):
        if hasattr(self, 'file_list'):
            for i in range(self.file_list.GetItemCount()):
                name = self.file_list.GetItemText(i)
                base_name = name.replace('(wybrany) ', '')
                if base_name in self.selected_items:
                    self.file_list.SetItemText(i, f'(wybrany) {base_name}')
                else:
                    self.file_list.SetItemText(i, base_name)

    def announce(self, message):
        self.status_text.SetLabel(message)
        self.speak(message)

    def init_tts(self):
        self.speak = self.speak_dummy
        system = platform.system()
        if system == 'Windows':
            # Spróbuj zaimportować win32com, jeśli się nie uda - fallback
            try:
                import win32com.client
                def speak_windows(text):
                    try:
                        speaker = win32com.client.Dispatch("SAPI.SpVoice")
                        speaker.Speak(text)
                    except:
                        pass
                self.speak = speak_windows
            except ImportError:
                pass
        elif system == 'Darwin':  # macOS
            def speak_mac(text):
                try:
                    os.system(f"say {text}")
                except:
                    pass
            self.speak = speak_mac
        else:  # Linux
            def speak_linux(text):
                try:
                    os.system(f"spd-say '{text}'")
                except:
                    pass
            self.speak = speak_linux

    def speak_dummy(self, text):
        # Fallback jeśli brak systemowego wsparcia
        pass

    def on_exit(self, event):
        self.Close()

    def on_new_file(self, event):
        dlg = wx.TextEntryDialog(self, 'Podaj nazwę nowego pliku:', 'Nowy Plik')
        if dlg.ShowModal() == wx.ID_OK:
            file_name = dlg.GetValue()
            open(os.path.join(self.current_path, file_name), 'w').close()
            self.populate_file_list()
            self.announce(f"Utworzono nowy plik {file_name}")
        dlg.Destroy()

    def on_new_folder(self, event):
        dlg = wx.TextEntryDialog(self, 'Podaj nazwę nowego folderu:', 'Nowy Folder')
        if dlg.ShowModal() == wx.ID_OK:
            folder_name = dlg.GetValue()
            os.makedirs(os.path.join(self.current_path, folder_name), exist_ok=True)
            self.populate_file_list()
            self.announce(f"Utworzono nowy folder {folder_name}")
        dlg.Destroy()

    def on_rename(self, event):
        if hasattr(self, 'file_list'):
            item = self.file_list.GetFocusedItem()
            if item != -1:
                name = self.file_list.GetItemText(item).replace('(wybrany) ', '')
                new_name = wx.GetTextFromUser("Podaj nową nazwę", "Zmiana nazwy", name)
                if new_name:
                    old_path = os.path.join(self.current_path, name)
                    new_path = os.path.join(self.current_path, new_name)
                    try:
                        os.rename(old_path, new_path)
                        self.populate_file_list()
                        self.announce(f"Zmieniono nazwę z {name} na {new_name}")
                    except Exception as e:
                        wx.MessageBox(str(e), "Błąd zmiany nazwy", wx.OK | wx.ICON_ERROR)

    def on_copy(self, event):
        if hasattr(self, 'file_list'):
            self.clipboard = [(os.path.join(self.current_path, name), 'copy') for name in self.selected_items]
            if self.selected_items:
                self.announce(f"Skopiowano {', '.join(self.selected_items)} do schowka")

    def on_cut(self, event):
        if hasattr(self, 'file_list'):
            self.clipboard = [(os.path.join(self.current_path, name), 'cut') for name in self.selected_items]
            if self.selected_items:
                self.announce(f"Wycięto {', '.join(self.selected_items)} do schowka")

    def on_paste(self, event):
        if hasattr(self, 'file_list'):
            dst_folder = self.current_path
            copy_dialog_mode = self.settings.get_copy_dialog_mode()
            if self.clipboard:
                copy_files = [path for path, action in self.clipboard if action == 'copy']
                move_files = [path for path, action in self.clipboard if action == 'cut']

                # Obsługa dialogu kopiowania:
                if copy_dialog_mode == 'systemowy':
                    # Brak niestandardowego dialogu, po prostu kopiujemy/przenosimy
                    for src in copy_files:
                        dst = os.path.join(dst_folder, os.path.basename(src))
                        if os.path.isdir(src):
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)
                    for src in move_files:
                        dst = os.path.join(dst_folder, os.path.basename(src))
                        shutil.move(src, dst)
                else:
                    # klasyczny dialog
                    if copy_files:
                        copy_files_with_progress(copy_files, dst_folder)
                    if move_files:
                        move_files_with_progress(move_files, dst_folder)

                self.clipboard = []
                self.populate_file_list()
                self.announce("Wklejono elementy ze schowka")

    def on_select_all(self, event):
        if hasattr(self, 'file_list'):
            self.selected_items = {self.file_list.GetItemText(i).replace('(wybrany) ', '') 
                                   for i in range(self.file_list.GetItemCount()) 
                                   if self.file_list.GetItemText(i) != 'Ten folder jest pusty'}
            self.update_display_names()
            self.announce("Zaznaczono wszystkie elementy")

    def on_open(self, event):
        if hasattr(self, 'file_list'):
            item = self.file_list.GetFocusedItem()
            if item != -1:
                name = self.file_list.GetItemText(item).replace('(wybrany) ', '')
                if name == 'Ten folder jest pusty':
                    return
                path = os.path.join(self.current_path, name)
                if os.path.isdir(path):
                    self.current_path = path
                    self.populate_file_list()
                    self.update_window_title()
                else:
                    if not self.show_extensions:
                        possible_extensions = [f for f in os.listdir(self.current_path) if f.startswith(name)]
                        if possible_extensions:
                            path = os.path.join(self.current_path, possible_extensions[0])
                    self.open_file_in_system(path)
                play_sound(os.path.join(get_app_sfx_path(), 'select.ogg'))

    def open_file_in_system(self, path):
        system = platform.system()
        if system == 'Windows':
            os.startfile(path)
        elif system == 'Darwin':  # macOS
            os.system(f'open "{path}"')
        else:  # Linux
            os.system(f'xdg-open "{path}"')

    def on_focus(self, event):
        play_sound(os.path.join(get_app_sfx_path(), 'focus.ogg'))
        event.Skip()

    def on_key_down(self, event):
        if hasattr(self, 'file_list'):
            keycode = event.GetKeyCode()
            if keycode == wx.WXK_BACK:
                parent_path = os.path.dirname(self.current_path)
                if parent_path and os.path.isdir(parent_path):
                    self.current_path = parent_path
                    self.populate_file_list()
                    self.update_window_title()
                    play_sound(os.path.join(get_app_sfx_path(), 'select.ogg'))
            elif keycode == wx.WXK_F2:
                self.on_rename(None)
            elif keycode in [wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE]:
                self.on_delete()
            elif keycode == wx.WXK_RETURN:
                self.on_open(None)
            elif keycode == wx.WXK_SPACE:
                item = self.file_list.GetFocusedItem()
                if item != -1:
                    name = self.file_list.GetItemText(item).replace('(wybrany) ', '')
                    if name in self.selected_items:
                        self.selected_items.remove(name)
                    else:
                        if name != 'Ten folder jest pusty':
                            self.selected_items.add(name)
                    self.update_display_names()
            else:
                event.Skip()
        else:
            event.Skip()

    def on_delete(self, event=None):
        if hasattr(self, 'file_list'):
            selected_count = len(self.selected_items)
            if selected_count > 0:
                names = ', '.join(self.selected_items)
                # Potwierdzenie jeśli włączone
                if self.settings.get_confirm_delete():
                    message = f"Czy na pewno chcesz usunąć te elementy? {names}" if selected_count > 1 else f"Czy na pewno chcesz usunąć ten element? {names}"
                    if wx.MessageBox(message, "Potwierdzenie", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
                        return
                for name in self.selected_items:
                    path = os.path.join(self.current_path, name)
                    try:
                        if os.path.isdir(path):
                            shutil.rmtree(path)
                        else:
                            os.remove(path)
                    except Exception as e:
                        wx.MessageBox(str(e), "Błąd usuwania", wx.OK | wx.ICON_ERROR)
                self.selected_items.clear()
                self.populate_file_list()
                self.announce(f"Usunięto {names}")

    def on_settings(self, event):
        settings_dialog = SettingsDialog(self, self.settings)
        if settings_dialog.ShowModal() == wx.ID_OK:
            self.view_settings = self.settings.get_view_settings()
            self.show_hidden = self.settings.get_show_hidden()
            self.show_extensions = self.settings.get_show_extensions()
            self.sort_mode = self.settings.get_sort_mode()
            self.refresh_interface()
        settings_dialog.Destroy()

    def on_sort_by_name(self, event):
        self.settings.set_sort_mode('name')
        self.sort_mode = 'name'
        self.populate_file_list()

    def on_sort_by_date(self, event):
        self.settings.set_sort_mode('date')
        self.sort_mode = 'date'
        self.populate_file_list()

    def on_sort_by_type(self, event):
        self.settings.set_sort_mode('type')
        self.sort_mode = 'type'
        self.populate_file_list()

    def refresh_interface(self):
        # Odświeżamy interfejs po zmianie ustawień
        # Tu zastosowano prosty sposób: niszczymy okno i tworzymy ponownie
        # W realnej aplikacji można to zrobić dynamicznie.
        self.Destroy()
        frame = FileManager()
        frame.Show()

    # Metody dla trybu commander (przykładowe, można rozbudować)
    def on_open_commander_left(self, event):
        item = self.left_list.GetFocusedItem()
        if item != -1:
            name = self.left_list.GetItemText(item)
            if name == 'Ten folder jest pusty':
                return
            path = os.path.join(self.current_path, name)
            if os.path.isdir(path):
                self.current_path = path
                self.populate_file_list(ctrl=self.left_list)
                self.update_window_title()
            else:
                if not self.show_extensions:
                    possible_extensions = [f for f in os.listdir(self.current_path) if f.startswith(name)]
                    if possible_extensions:
                        path = os.path.join(self.current_path, possible_extensions[0])
                self.open_file_in_system(path)
            play_sound(os.path.join(get_app_sfx_path(), 'select.ogg'))

    def on_open_commander_right(self, event):
        # Analogiczna obsługa jak dla lewej listy, na razie pusta.
        pass

    def on_key_down_commander_left(self, event):
        # Obsługa klawiatury dla lewej listy commander - analogiczna do on_key_down
        event.Skip()

    def on_key_down_commander_right(self, event):
        # Obsługa klawiatury dla prawej listy commander
        event.Skip()

if __name__ == '__main__':
    app = wx.App()
    frame = FileManager()
    frame.Show()
    app.MainLoop()
