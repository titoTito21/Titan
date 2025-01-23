import sys
import os
import wx
import datetime
import shutil
import pygame
import platform

# Dodaj ścieżkę do głównego katalogu Titan Launcher
launcher_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.append(launcher_path)

from tfm_settings import SettingsManager, SettingsDialog
from sound import play_sound, initialize_sound, resource_path

# Inicjalizacja pygame
initialize_sound()

def get_app_sfx_path():
    return os.path.join(os.path.dirname(__file__), 'sfx')

class FileManager(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None, title="Menedżer Plików", size=(800, 600))
        self.current_path = os.path.expanduser("~")
        self.clipboard = []
        self.selected_items = set()
        self.settings = SettingsManager()
        
        self.view_settings = self.settings.get_view_settings()
        self.show_hidden = self.settings.get_show_hidden()
        self.show_extensions = self.settings.get_show_extensions()

        self.init_tts()

        # Panel główny
        panel = wx.Panel(self)

        # Niewidzialny tekst do komunikatów dla screenreadera
        self.status_text = wx.StaticText(panel, label="", pos=(-1000, -1000))

        # Menu
        menubar = wx.MenuBar()
        from menu import create_file_menu, create_edit_menu
        
        file_menu = create_file_menu(self)
        edit_menu = create_edit_menu(self)
        
        menubar.Append(file_menu, '&Plik')
        menubar.Append(edit_menu, '&Edycja')
        
        self.SetMenuBar(menubar)
        
        # Lista plików
        self.file_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.update_file_list_columns()
        self.populate_file_list()

        # Layout
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(self.file_list, 1, wx.EXPAND | wx.ALL, 10)
        vbox.Add(self.status_text, 0, wx.ALL, 10)
        panel.SetSizer(vbox)

        # Bindy do obsługi
        self.file_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open)
        self.file_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.file_list.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        panel.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

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

        self.Show()

    def update_file_list_columns(self):
        self.file_list.ClearAll()
        col_index = 0
        if 'name' in self.view_settings:
            self.file_list.InsertColumn(col_index, 'Nazwa', width=300)
            col_index += 1
        if 'date' in self.view_settings:
            self.file_list.InsertColumn(col_index, 'Data modyfikacji', width=200)
            col_index += 1
        if 'type' in self.view_settings:
            self.file_list.InsertColumn(col_index, 'Typ', width=100)

    def populate_file_list(self):
        self.file_list.DeleteAllItems()
        self.selected_items.clear()
        try:
            entries = os.listdir(self.current_path)
            if not self.show_hidden:
                entries = [e for e in entries if not e.startswith('.')]
            entries = [e for e in entries if e != '.DS_Store']  # Ignoruj .DS_Store na macOS
            if not entries:
                index = self.file_list.InsertItem(self.file_list.GetItemCount(), 'Ten folder jest pusty')
                if 'date' in self.view_settings:
                    self.file_list.SetItem(index, 1, '')
                if 'type' in self.view_settings:
                    self.file_list.SetItem(index, len(self.view_settings) - 1, '')
            else:
                entries = sorted(entries, key=lambda x: (not os.path.isdir(os.path.join(self.current_path, x)), x.lower()))

                for entry in entries:
                    path = os.path.join(self.current_path, entry)
                    modified = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
                    entry_type = 'Folder' if os.path.isdir(path) else 'Plik'
                    display_name = entry if self.show_extensions else os.path.splitext(entry)[0]
                    index = self.file_list.InsertItem(self.file_list.GetItemCount(), display_name)
                    col_index = 1
                    if 'date' in self.view_settings:
                        self.file_list.SetItem(index, col_index, modified)
                        col_index += 1
                    if 'type' in self.view_settings:
                        self.file_list.SetItem(index, col_index, entry_type)
                self.file_list.Select(0)  # Automatycznie wybierz pierwszy element
        except PermissionError:
            wx.MessageBox("Brak dostępu do katalogu", "Błąd", wx.OK | wx.ICON_ERROR)

    def update_display_names(self):
        for i in range(self.file_list.GetItemCount()):
            name = self.file_list.GetItemText(i)
            if name in self.selected_items:
                self.file_list.SetItemText(i, f'(wybrany) {name}')
            else:
                self.file_list.SetItemText(i, name.replace('(wybrany) ', ''))

    def announce(self, message):
        self.status_text.SetLabel(message)
        self.speak(message)

    def init_tts(self):
        system = platform.system()
        if system == 'Windows':
            self.speak = self.speak_windows
        elif system == 'Darwin':  # macOS
            self.speak = self.speak_mac
        else:  # Assume Linux
            self.speak = self.speak_linux

    def speak_windows(self, text):
        import win32com.client
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Speak(text)

    def speak_mac(self, text):
        os.system(f"say {text}")

    def speak_linux(self, text):
        os.system(f"spd-say {text}")

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
            os.makedirs(os.path.join(self.current_path, folder_name))
            self.populate_file_list()
            self.announce(f"Utworzono nowy folder {folder_name}")
        dlg.Destroy()

    def on_rename(self, event):
        item = self.file_list.GetFocusedItem()
        if item != -1:
            name = self.file_list.GetItemText(item).replace('(wybrany) ', '')
            new_name = wx.GetTextFromUser("Podaj nową nazwę", "Zmiana nazwy", name)
            if new_name:
                os.rename(os.path.join(self.current_path, name), os.path.join(self.current_path, new_name))
                self.populate_file_list()
                self.announce(f"Zmieniono nazwę z {name} na {new_name}")

    def on_copy(self, event):
        self.clipboard = [(os.path.join(self.current_path, name), 'copy') for name in self.selected_items]
        self.announce(f"Skopiowano {', '.join(self.selected_items)} do schowka")

    def on_cut(self, event):
        self.clipboard = [(os.path.join(self.current_path, name), 'cut') for name in self.selected_items]
        self.announce(f"Wycięto {', '.join(self.selected_items)} do schowka")

    def on_paste(self, event):
        for path, action in self.clipboard:
            new_path = os.path.join(self.current_path, os.path.basename(path))
            if action == 'copy':
                if os.path.isdir(path):
                    shutil.copytree(path, new_path)
                else:
                    shutil.copy2(path, new_path)
            elif action == 'cut':
                shutil.move(path, new_path)
        self.clipboard = []
        self.populate_file_list()
        self.announce(f"Wklejono elementy ze schowka")

    def on_select_all(self, event):
        self.selected_items = {self.file_list.GetItemText(i) for i in range(self.file_list.GetItemCount())}
        self.update_display_names()
        self.announce(f"Zaznaczono wszystkie elementy")

    def on_open(self, event):
        item = self.file_list.GetFocusedItem()
        if item != -1:
            name = self.file_list.GetItemText(item).replace('(wybrany) ', '')
            if name == 'Ten folder jest pusty':
                return
            path = os.path.join(self.current_path, name)
            if os.path.isdir(path):
                self.current_path = path
                self.populate_file_list()
            else:
                if platform.system() == 'Windows':
                    os.startfile(path)
                elif platform.system() == 'Darwin':  # macOS
                    os.system(f'open "{path}"')
                else:  # Assume Linux
                    os.system(f'xdg-open "{path}"')
            play_sound(os.path.join(get_app_sfx_path(), 'select.ogg'))

    def on_focus(self, event):
        play_sound(os.path.join(get_app_sfx_path(), 'focus.ogg'))
        event.Skip()

    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_BACK:
            self.current_path = os.path.dirname(self.current_path)
            self.populate_file_list()
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
                    self.selected_items.add(name)
                self.update_display_names()
        else:
            event.Skip()

    def on_delete(self, event=None):
        selected_count = len(self.selected_items)
        if selected_count > 0:
            names = ', '.join(self.selected_items)
            message = f"Czy na pewno chcesz usunąć te elementy? {names}" if selected_count > 1 else f"Czy na pewno chcesz usunąć ten element? {names}"
            if wx.MessageBox(message, "Potwierdzenie", wx.YES_NO | wx.ICON_WARNING) == wx.YES:
                for name in self.selected_items:
                    path = os.path.join(self.current_path, name)
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                self.populate_file_list()
                self.announce(f"Usunięto {names}")

    def on_settings(self, event):
        settings_dialog = SettingsDialog(self, self.settings)
        if settings_dialog.ShowModal() == wx.ID_OK:
            self.view_settings = self.settings.get_view_settings()
            self.show_hidden = self.settings.get_show_hidden()
            self.show_extensions = self.settings.get_show_extensions()
            self.update_file_list_columns()
            self.populate_file_list()
        settings_dialog.Destroy()

if __name__ == '__main__':
    app = wx.App()
    frame = FileManager()
    frame.Show()
    app.MainLoop()
