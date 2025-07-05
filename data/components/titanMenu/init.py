import wx
import os
import sys
import threading
import platform
import subprocess
import accessible_output3.outputs.auto
from sound import play_focus_sound, play_select_sound, play_statusbar_sound, play_applist_sound

speaker = accessible_output3.outputs.auto.Auto()

class TitanMenu(wx.Frame):
    def __init__(self, *args, **kw):
        super(TitanMenu, self).__init__(*args, **kw)
        self.current_menu = 'main'
        self.InitUI()

    def InitUI(self):
        self.SetTitle("Titan Menu")
        self.SetSize((600, 600))
        self.Centre()

        self.panel = wx.Panel(self)
        self.vbox = wx.BoxSizer(wx.VERTICAL)
        self.panel.SetSizer(self.vbox)

        self.Bind(wx.EVT_CLOSE, self.on_close)

        # Tworzenie TreeCtrl dla hierarchicznego menu
        self.menu_tree = wx.TreeCtrl(self.panel, style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT)
        self.menu_tree.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.menu_tree.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.menu_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_select)
        self.menu_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_item_selected)
        self.menu_tree.Bind(wx.EVT_MOTION, self.on_mouse_motion)
        self.vbox.Add(self.menu_tree, 1, wx.EXPAND | wx.ALL, 5)

        # Wypełnienie menu
        self.populate_menu()

        self.Layout()

    def populate_menu(self):
        self.menu_tree.DeleteAllItems()
        root = self.menu_tree.AddRoot("Menu")

        # Wypełnienie aplikacjami zgodnie z platformą
        if platform.system() == 'Windows':
            self.populate_windows_start_menu(root)
        elif platform.system() == 'Darwin':  # macOS
            self.populate_mac_applications(root)
        else:  # Linux
            self.populate_linux_applications(root)

        # Dodanie opcji Zamknij komputer
        self.menu_tree.AppendItem(root, "Zamknij komputer")

        # Nie rozwijaj wszystkich elementów
        # self.menu_tree.ExpandAll()  # Usunięto, aby katalogi były zwinięte domyślnie

        # Rozwiń tylko główny element, jeśli chcesz
        # self.menu_tree.Expand(root)

        self.menu_tree.SetFocus()

    def populate_windows_start_menu(self, parent_item):
        start_menu_paths = [
            os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs'),
            os.path.join(os.getenv('PROGRAMDATA'), r'Microsoft\Windows\Start Menu\Programs')
        ]

        for start_menu in start_menu_paths:
            if os.path.exists(start_menu):
                self.add_directory_to_tree(start_menu, parent_item)

    def populate_mac_applications(self, parent_item):
        applications_dir = "/Applications"
        if os.path.exists(applications_dir):
            self.add_directory_to_tree(applications_dir, parent_item)

    def populate_linux_applications(self, parent_item):
        desktop_dirs = [
            '/usr/share/applications',
            os.path.expanduser('~/.local/share/applications')
        ]
        categories = {}

        for desktop_dir in desktop_dirs:
            if os.path.exists(desktop_dir):
                for filename in os.listdir(desktop_dir):
                    if filename.endswith('.desktop'):
                        filepath = os.path.join(desktop_dir, filename)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                lines = f.readlines()
                                entry = {}
                                for line in lines:
                                    line = line.strip()
                                    if '=' in line and not line.startswith('#'):
                                        key, value = line.split('=', 1)
                                        entry[key.strip()] = value.strip()
                                if 'Name' in entry and 'Exec' in entry and 'Type' in entry and entry['Type'] == 'Application':
                                    name = entry['Name']
                                    categories_list = entry.get('Categories', '').split(';')
                                    for category in categories_list:
                                        if category:
                                            if category not in categories:
                                                categories[category] = []
                                            categories[category].append((name, entry['Exec']))
                        except Exception as e:
                            print(f"Błąd podczas odczytu {filepath}: {e}")
        # Dodanie kategorii i aplikacji do drzewa
        for category, apps in categories.items():
            category_item = self.menu_tree.AppendItem(parent_item, category)
            for app_name, app_exec in apps:
                app_item = self.menu_tree.AppendItem(category_item, app_name)
                self.menu_tree.SetItemData(app_item, app_exec)

    def add_directory_to_tree(self, dir_path, parent_item):
        for item in sorted(os.listdir(dir_path)):
            item_path = os.path.join(dir_path, item)
            if os.path.isdir(item_path):
                # Utwórz nowy element drzewa dla katalogu
                dir_item = self.menu_tree.AppendItem(parent_item, item)
                # Rekurencyjnie dodaj pod-elementy
                self.add_directory_to_tree(item_path, dir_item)
            elif os.path.isfile(item_path):
                # Sprawdź pliki aplikacji
                if platform.system() == 'Windows':
                    if item.endswith('.lnk'):
                        app_item = self.menu_tree.AppendItem(parent_item, os.path.splitext(item)[0])
                        self.menu_tree.SetItemData(app_item, item_path)
                elif platform.system() == 'Darwin':
                    if item.endswith('.app'):
                        app_item = self.menu_tree.AppendItem(parent_item, os.path.splitext(item)[0])
                        self.menu_tree.SetItemData(app_item, item_path)

    def on_focus(self, event):
        play_focus_sound()
        event.Skip()

    def on_item_selected(self, event):
        play_focus_sound()
        event.Skip()

    def on_mouse_motion(self, event):
        # Sprawdź, czy wskaźnik myszy jest nad elementem
        item, flags = self.menu_tree.HitTest(event.GetPosition())
        if item and item != self.menu_tree.GetSelection():
            self.menu_tree.SelectItem(item)
            play_focus_sound()
        event.Skip()

    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_BACK:
            parent_item = self.menu_tree.GetItemParent(self.menu_tree.GetSelection())
            if parent_item and parent_item != self.menu_tree.GetRootItem():
                self.menu_tree.SelectItem(parent_item)
        else:
            event.Skip()

    def on_select(self, event=None):
        item = self.menu_tree.GetSelection()
        item_text = self.menu_tree.GetItemText(item)
        item_data = self.menu_tree.GetItemData(item)
        play_select_sound()
        if item_text == "Zamknij komputer":
            self.shutdown_computer()
        elif self.menu_tree.ItemHasChildren(item):
            # Rozwiń lub zwiń element
            if self.menu_tree.IsExpanded(item):
                self.menu_tree.Collapse(item)
            else:
                self.menu_tree.Expand(item)
        else:
            # Otwórz aplikację
            self.open_program(item, item_text, item_data)

    def shutdown_computer(self):
        play_select_sound()
        if platform.system() == 'Windows':
            os.system("shutdown /s /f /t 0")
        elif platform.system() == 'Darwin':  # macOS
            os.system("sudo shutdown -h now")
        else:  # Linux
            os.system("shutdown -h now")

    def open_program(self, item, item_text, item_data):
        threading.Thread(target=self._open_program, args=(item_text, item_data)).start()

    def _open_program(self, item_text, item_data):
        play_select_sound()
        if platform.system() == 'Windows':
            if item_data:
                os.startfile(item_data)
            else:
                pass  # Możesz dodać obsługę błędu
        elif platform.system() == 'Darwin':
            if item_data:
                subprocess.call(['open', item_data])
            else:
                pass  # Możesz dodać obsługę błędu
        else:  # Linux
            if item_data:
                subprocess.call(item_data, shell=True)
            else:
                pass  # Możesz dodać obsługę błędu

    def show_menu(self):
        self.Show()
        play_statusbar_sound()
        self.menu_tree.SetFocus()

    def hide_menu(self):
        self.Hide()
        play_applist_sound()

    def on_close(self, event):
        self.Hide()
        play_applist_sound()
        event.Veto()  # Zapobiega zamknięciu okna

def initialize(app):
    titan_menu = TitanMenu(None)

    def toggle_menu():
        if titan_menu.IsShown():
            titan_menu.hide_menu()
        else:
            titan_menu.show_menu()

    app.Bind(wx.EVT_CHAR_HOOK, lambda evt: toggle_menu() if evt.GetKeyCode() == wx.WXK_F2 and evt.AltDown() else evt.Skip())

    return titan_menu

def add_menu(menubar):
    pass  # Opcjonalnie dodaj elementy menu związane z Titan Menu
