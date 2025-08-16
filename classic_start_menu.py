import wx
import os
import sys
import platform
import subprocess
import threading
import time
try:
    import accessible_output3.outputs.auto
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("Warning: accessible_output3 not available")
from sound import play_sound, initialize_sound
from settings import get_setting, load_settings
from translation import set_language
import winreg
import glob
try:
    import win32gui
    import win32con
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("Warning: win32gui not available, using fallback menu")

# Initialize translation system
_ = set_language(get_setting('language', 'pl'))

class ClassicMenuItem:
    """Element menu w stylu Windows 95"""
    def __init__(self, name, action=None, submenu=None, icon=None, shortcut=None):
        self.name = name
        self.action = action
        self.submenu = submenu
        self.icon = icon
        self.shortcut = shortcut
        self.is_separator = name == "---"

class ClassicStartMenu(wx.Frame):
    """Klasyczne Menu Start w stylu Windows 95/98"""
    
    def __init__(self, parent):
        super().__init__(parent, title="Titan Menu", 
                         style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP)
        
        self.parent = parent
        # Disable TTS in Start Menu to avoid conflicts with screen readers
        self.speaker = None
        
        self.is_windows = platform.system() == "Windows"
        self.menu_items = []
        self.current_submenu = None
        
        # Inicjalizacja dźwięku
        initialize_sound()
        
        self.init_ui()
        self.build_menu_structure()
        self.position_menu()
        
        # Zastosuj ustawienia skórki
        self.apply_skin_settings()
        
        # Bind events
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        self.Bind(wx.EVT_KILL_FOCUS, self.on_kill_focus)
    
    def init_ui(self):
        """Inicjalizacja interfejsu w stylu Windows 95"""
        # Panel główny z klasycznym szarym tłem
        main_panel = wx.Panel(self)
        main_panel.SetBackgroundColour(wx.Colour(192, 192, 192))  # Klasyczny szary
        
        # Sizer główny
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Lewy panel z logo Windows (niebieski gradient)
        self.logo_panel = wx.Panel(main_panel)
        self.logo_panel.SetBackgroundColour(wx.Colour(0, 0, 128))  # Ciemny niebieski
        self.logo_panel.SetMinSize((32, 300))
        
        # Logo text (pionowo)
        logo_sizer = wx.BoxSizer(wx.VERTICAL)
        logo_text = wx.StaticText(self.logo_panel, label="Windows", style=wx.ALIGN_CENTER)
        logo_text.SetForegroundColour(wx.Colour(255, 255, 255))
        logo_font = wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        logo_text.SetFont(logo_font)
        
        logo_sizer.AddStretchSpacer(1)
        logo_sizer.Add(logo_text, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        
        titan_text = wx.StaticText(self.logo_panel, label="Titan", style=wx.ALIGN_CENTER)
        titan_text.SetForegroundColour(wx.Colour(192, 192, 255))
        titan_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        titan_text.SetFont(titan_font)
        logo_sizer.Add(titan_text, 0, wx.ALIGN_CENTER | wx.ALL, 2)
        logo_sizer.AddStretchSpacer(1)
        
        self.logo_panel.SetSizer(logo_sizer)
        
        # Prawy panel z menu
        menu_panel = wx.Panel(main_panel)
        menu_panel.SetBackgroundColour(wx.Colour(192, 192, 192))
        menu_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Drzewo menu w stylu Windows 95
        self.menu_tree = wx.TreeCtrl(menu_panel, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE)
        self.menu_tree.SetBackgroundColour(wx.Colour(255, 255, 255))
        self.menu_tree.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        
        menu_sizer.Add(self.menu_tree, 1, wx.ALL | wx.EXPAND, 3)
        
        # Separator
        separator = wx.StaticLine(menu_panel, style=wx.LI_HORIZONTAL)
        menu_sizer.Add(separator, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 3)
        
        # Bottom buttons (Shut Down, etc.)
        bottom_panel = wx.Panel(menu_panel)
        bottom_panel.SetBackgroundColour(wx.Colour(192, 192, 192))
        bottom_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.shutdown_button = wx.Button(bottom_panel, label=_("Shut Down"))
        self.shutdown_button.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        
        bottom_sizer.Add(self.shutdown_button, 1, wx.ALL | wx.EXPAND, 2)
        bottom_panel.SetSizer(bottom_sizer)
        
        menu_sizer.Add(bottom_panel, 0, wx.EXPAND | wx.ALL, 3)
        menu_panel.SetSizer(menu_sizer)
        
        # Layout główny
        main_sizer.Add(self.logo_panel, 0, wx.EXPAND)
        main_sizer.Add(menu_panel, 1, wx.EXPAND)
        
        main_panel.SetSizer(main_sizer)
        
        # Bind events
        self.menu_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_tree_select)
        self.menu_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_tree_activate)
        self.menu_tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.on_tree_expanding)
        self.menu_tree.Bind(wx.EVT_TREE_ITEM_COLLAPSING, self.on_tree_collapsing)
        self.menu_tree.Bind(wx.EVT_KEY_DOWN, self.on_tree_key)
        self.shutdown_button.Bind(wx.EVT_BUTTON, self.on_shutdown)
        
        # Rozmiar okna
        self.SetSize((280, 400))
    
    def build_menu_structure(self):
        """Budowanie struktury menu w stylu Windows 95"""
        self.menu_items = [
            ClassicMenuItem(_("Programs"), submenu="programs"),
            ClassicMenuItem(_("Documents"), submenu="documents"),
            ClassicMenuItem(_("Titan - Applications"), submenu="titan_apps"),
            ClassicMenuItem(_("Titan - Games"), submenu="titan_games"),
            ClassicMenuItem(_("Settings"), submenu="settings"),
            ClassicMenuItem(_("Find"), action="find"),
            ClassicMenuItem(_("Help"), action="help"),
            ClassicMenuItem(_("Run..."), action="run"),
        ]
        
        self.update_menu_display()
    
    def update_menu_display(self):
        """Aktualizacja wyświetlania menu"""
        self.menu_tree.DeleteAllItems()
        
        # Create invisible root
        root = self.menu_tree.AddRoot("Root")
        
        for item in self.menu_items:
            if not item.is_separator:
                tree_item = self.menu_tree.AppendItem(root, item.name)
                self.menu_tree.SetItemData(tree_item, item)
                
                # If it has submenu, add placeholder child to show expand button
                if item.submenu:
                    placeholder = self.menu_tree.AppendItem(tree_item, "...")
                    self.menu_tree.SetItemData(placeholder, None)
        
        # Select first item (root is already hidden, no need to expand)
        first_child = self.menu_tree.GetFirstChild(root)[0]
        if first_child.IsOk():
            self.menu_tree.SelectItem(first_child)
    
    def on_tree_select(self, event):
        """Obsługa wyboru elementu w drzewie"""
        item_id = event.GetItem()
        if item_id.IsOk():
            item_data = self.menu_tree.GetItemData(item_id)
            if item_data:
                play_sound('focus.ogg')
    
    def on_tree_activate(self, event):
        """Obsługa aktywacji elementu w drzewie (double-click)"""
        self.execute_tree_item()
    
    def on_tree_expanding(self, event):
        """Obsługa rozwijania węzła"""
        item_id = event.GetItem()
        item_data = self.menu_tree.GetItemData(item_id)
        
        play_sound('focus_expanded.ogg')
        
        if item_data and item_data.submenu:
            # Remove placeholder
            child, cookie = self.menu_tree.GetFirstChild(item_id)
            if child.IsOk():
                self.menu_tree.Delete(child)
            
            # Load submenu items
            self.load_submenu_items(item_id, item_data.submenu)
    
    def on_tree_collapsing(self, event):
        """Obsługa zwijania węzła"""
        play_sound('focus_collabsed.ogg')
    
    def on_tree_key(self, event):
        """Obsługa klawiszy w drzewie"""
        key_code = event.GetKeyCode()
        
        if key_code == wx.WXK_RETURN:
            self.execute_tree_item()
        elif key_code == wx.WXK_ESCAPE:
            self.on_close(event)
        else:
            event.Skip()
    
    def execute_tree_item(self):
        """Wykonanie akcji dla wybranego elementu w drzewie"""
        selection = self.menu_tree.GetSelection()
        if not selection.IsOk():
            print("DEBUG: No valid selection")
            return
        
        item = self.menu_tree.GetItemData(selection)
        if not item:
            print("DEBUG: No item data")
            return
        
        print(f"DEBUG: Executing tree item: {type(item)} - {item}")
        play_sound('select.ogg')
        
        # Handle new data structure for apps and games
        if isinstance(item, dict):
            if item.get('type') == 'titan_app':
                print(f"DEBUG: Running titan app: {item['data'].get('name')}")
                self.run_titan_app(item['data'])
                return
            elif item.get('type') == 'titan_game':
                print(f"DEBUG: Running titan game: {item['data'].get('name')}")
                self.run_titan_game(item['data'])
                return
            elif item.get('type') == 'windows_program':
                print(f"DEBUG: Running windows program: {item['data'].get('name')}")
                self.run_program(item['data'])
                return
        
        # Handle ClassicMenuItem objects
        if hasattr(item, 'submenu') and item.submenu:
            print(f"DEBUG: Toggling submenu: {item.name}")
            # Toggle expansion of the node
            if self.menu_tree.IsExpanded(selection):
                self.menu_tree.Collapse(selection)
            else:
                self.menu_tree.Expand(selection)
        elif hasattr(item, 'action') and item.action:
            print(f"DEBUG: Executing action: {item.action}")
            if callable(item.action):
                item.action()
            else:
                self.execute_action(item.action)
        else:
            print(f"DEBUG: No action found for item: {item}")
    
    def load_submenu_items(self, parent_item, submenu_type):
        """Ładowanie elementów submenu do drzewa"""
        if submenu_type == "programs":
            self.load_programs_submenu(parent_item)
        elif submenu_type == "documents":
            self.load_documents_submenu(parent_item)
        elif submenu_type == "titan_apps":
            self.load_titan_apps_submenu(parent_item)
        elif submenu_type == "titan_games":
            self.load_titan_games_submenu(parent_item)
        elif submenu_type == "settings":
            self.load_settings_submenu(parent_item)
    
    def load_programs_submenu(self, parent_item):
        """Ładowanie programów jako drzewo"""
        try:
            if self.is_windows:
                folder_structure = self.load_windows_programs_with_folders()
                for folder_name, items in folder_structure.items():
                    folder_item = self.menu_tree.AppendItem(parent_item, folder_name)
                    self.menu_tree.SetItemData(folder_item, ClassicMenuItem(folder_name))
                    
                    for program in items:
                        program_item = self.menu_tree.AppendItem(folder_item, program['name'])
                        # Store program data directly in tree item instead of lambda
                        self.menu_tree.SetItemData(program_item, {'type': 'windows_program', 'data': program})
        except Exception as e:
            print(f"Error loading programs: {e}")
    
    def load_documents_submenu(self, parent_item):
        """Ładowanie dokumentów jako drzewo"""
        my_docs = self.menu_tree.AppendItem(parent_item, _('My Documents'))
        self.menu_tree.SetItemData(my_docs, ClassicMenuItem(_('My Documents'), action='my_documents'))
    
    def load_titan_apps_submenu(self, parent_item):
        """Ładowanie aplikacji Titan jako drzewo - bez folderów, bezpośrednio"""
        try:
            from app_manager import get_applications
            apps = get_applications()
            
            # Add all applications directly to the tree
            for app in apps:
                app_item = self.menu_tree.AppendItem(parent_item, app['name'])
                # Store app data directly in tree item instead of lambda
                self.menu_tree.SetItemData(app_item, {'type': 'titan_app', 'data': app})
                    
        except Exception as e:
            print(f"Error loading Titan applications: {e}")
    
    def load_titan_games_submenu(self, parent_item):
        """Ładowanie gier Titan jako drzewo - bez kategorii, bezpośrednio"""
        try:
            from game_manager import get_games
            games = get_games()
            
            # Add all games directly to the tree
            if games:
                for game in games:
                    game_item = self.menu_tree.AppendItem(parent_item, game['name'])
                    # Store game data directly in tree item instead of lambda
                    self.menu_tree.SetItemData(game_item, {'type': 'titan_game', 'data': game})
            else:
                # Add "No games found" item if no games
                no_games_item = self.menu_tree.AppendItem(parent_item, _("No games found"))
                self.menu_tree.SetItemData(no_games_item, ClassicMenuItem(_("No games found")))
                    
        except Exception as e:
            print(f"Error loading Titan games: {e}")
    
    def load_settings_submenu(self, parent_item):
        """Ładowanie ustawień jako drzewo"""
        # Titan Settings - make it work like menu bar
        titan_settings = self.menu_tree.AppendItem(parent_item, _("Titan Settings"))
        self.menu_tree.SetItemData(titan_settings, ClassicMenuItem(_("Titan Settings"), action="titan_settings"))
        
        # Control Panel
        if self.is_windows:
            control_panel = self.menu_tree.AppendItem(parent_item, _("Control Panel"))
            self.menu_tree.SetItemData(control_panel, ClassicMenuItem(_("Control Panel"), action="control_panel"))
    
    def run_titan_app(self, app):
        """Uruchamianie aplikacji Titan"""
        try:
            print(f"DEBUG: Start Menu running Titan app: {app.get('name', 'Unknown')}")
            print(f"DEBUG: App data: {app}")
            from app_manager import open_application
            
            # Use open_application with app_info object directly like GUI does
            open_application(app)
            self.Hide()
        except Exception as e:
            print(f"Error running Titan app: {e}")
            import traceback
            traceback.print_exc()
    
    def run_titan_game(self, game):
        """Uruchamianie gry Titan"""
        try:
            from game_manager import get_games, open_game
            
            # Find game by name in the games list
            games = get_games()
            game_info = None
            for g in games:
                if g['name'] == game['name']:
                    game_info = g
                    break
            
            if game_info:
                # Use open_game with game_info object like gui.py does
                open_game(game_info)
                self.Hide()
            else:
                print(f"Game {game['name']} not found")
        except Exception as e:
            print(f"Error running Titan game: {e}")
    
    def show_submenu(self, submenu_type):
        """Wyświetlanie podmenu"""
        if submenu_type == "programs":
            self.show_programs_menu()
        elif submenu_type == "documents":
            self.show_documents_menu()
        elif submenu_type == "settings":
            self.show_settings_menu()
    
    def show_programs_menu(self):
        """Podmenu Programy - struktura folderów jak Windows XP"""
        if not self.is_windows:
            return
        
        # Create programs submenu window
        programs_menu = ClassicSubmenu(self, _("Programy"))
        
        # Load Windows programs with folder structure
        folder_structure = self.load_windows_programs_with_folders()
        
        # Add folder structure to menu
        for folder_name, items in folder_structure.items():
            if len(items) > 1:
                # Folder with multiple items - create submenu
                programs_menu.add_item(ClassicMenuItem(
                    folder_name,
                    submenu=items
                ))
            elif len(items) == 1:
                # Single item - add directly
                program = items[0]
                # Create a closure to capture program variable properly
                def make_single_action(prog):
                    return lambda: self.run_program(prog)
                
                programs_menu.add_item(ClassicMenuItem(
                    program['name'],
                    action=make_single_action(program)
                ))
        
        programs_menu.show_at_cursor()
    
    def show_documents_menu(self):
        """Podmenu Dokumenty"""
        docs_menu = ClassicSubmenu(self, _("Dokumenty"))
        
        # Recent documents (mock)
        docs_menu.add_item(ClassicMenuItem(_("Moje dokumenty"), action="my_documents"))
        docs_menu.add_item(ClassicMenuItem("---"))
        docs_menu.add_item(ClassicMenuItem(_("(puste)"), action=None))
        
        docs_menu.show_at_cursor()
    
    def show_settings_menu(self):
        """Podmenu Ustawienia"""
        settings_menu = ClassicSubmenu(self, _("Ustawienia"))
        
        settings_menu.add_item(ClassicMenuItem(_("Panel sterowania"), action="control_panel"))
        settings_menu.add_item(ClassicMenuItem(_("Drukarki"), action="printers"))
        settings_menu.add_item(ClassicMenuItem(_("Pasek zadań..."), action="taskbar"))
        settings_menu.add_item(ClassicMenuItem("---"))
        settings_menu.add_item(ClassicMenuItem(_("Ustawienia Titan"), action="titan_settings"))
        
        settings_menu.show_at_cursor()
    
    def show_native_programs_menu(self):
        """Pokaż natywne Windows popup menu z programami"""
        if not WIN32_AVAILABLE or not self.is_windows:
            # Fallback to tree-based menu
            self.show_programs_menu()
            return
            
        try:
            # Stwórz natywne Windows popup menu
            menu = win32gui.CreatePopupMenu()
            submenu_dict = {}  # Przechowuj referencje do podmenu
            
            # Załaduj strukturę programów
            folder_structure = self.load_windows_programs_with_folders()
            menu_id = 1000  # Start ID dla menu items
            
            for folder_name, programs in folder_structure.items():
                if len(programs) > 1:
                    # Stwórz podmenu dla folderu z wieloma programami
                    submenu = win32gui.CreatePopupMenu()
                    submenu_dict[menu_id] = submenu
                    
                    # Dodaj programy do podmenu
                    for program in programs:
                        win32gui.AppendMenu(submenu, win32con.MF_STRING, menu_id + 1, program['name'])
                        # Zapisz dane programu dla późniejszego użycia
                        setattr(self, f'program_data_{menu_id + 1}', program)
                        menu_id += 1
                    
                    # Dodaj podmenu do głównego menu
                    win32gui.AppendMenu(menu, win32con.MF_POPUP, submenu, folder_name)
                    menu_id += 1
                    
                elif len(programs) == 1:
                    # Pojedynczy program - dodaj bezpośrednio
                    program = programs[0]
                    win32gui.AppendMenu(menu, win32con.MF_STRING, menu_id, program['name'])
                    setattr(self, f'program_data_{menu_id}', program)
                    menu_id += 1
            
            # Dodaj separator i opcje dodatkowe na końcu menu
            if folder_structure:
                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            
            # Dodaj opcje systemowe
            win32gui.AppendMenu(menu, win32con.MF_STRING, menu_id, _("Control Panel"))
            setattr(self, f'action_data_{menu_id}', "control_panel")
            menu_id += 1
            
            win32gui.AppendMenu(menu, win32con.MF_STRING, menu_id, _("Run..."))
            setattr(self, f'action_data_{menu_id}', "run")
            menu_id += 1
            
            # Pokaż menu przy kursorze myszki
            cursor_pos = win32gui.GetCursorPos()
            
            # Ustaw okno jako foreground, żeby menu działało prawidłowo
            hwnd = self.GetHandle()
            win32gui.SetForegroundWindow(hwnd)
            
            # Pokaż menu i poczekaj na wybór użytkownika
            selected = win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_LEFTBUTTON | win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY,
                cursor_pos[0],
                cursor_pos[1],
                0,
                hwnd,
                None
            )
            
            # Obsłuż wybór użytkownika
            if selected > 0:
                program_data = getattr(self, f'program_data_{selected}', None)
                action_data = getattr(self, f'action_data_{selected}', None)
                
                if program_data:
                    # Uruchom program
                    play_sound('select.ogg')
                    self.run_program(program_data)
                    self.Hide()
                elif action_data:
                    # Wykonaj akcję systemową
                    play_sound('select.ogg')
                    self.execute_action(action_data)
                    self.Hide()
            
            # Wyczyść menu i dane
            win32gui.DestroyMenu(menu)
            for submenu in submenu_dict.values():
                win32gui.DestroyMenu(submenu)
            
            # Wyczyść zapisane dane programów i akcji
            for attr_name in list(self.__dict__.keys()):
                if attr_name.startswith('program_data_') or attr_name.startswith('action_data_'):
                    delattr(self, attr_name)
                
        except Exception as e:
            print(f"Error creating native menu: {e}")
            # Fallback do zwykłego menu
            self.show_programs_menu()

    def execute_action(self, action):
        """Wykonanie akcji menu"""
        try:
            if action == "run":
                self.show_run_dialog()
            elif action == "find":
                self.show_find_dialog()
            elif action == "help":
                self.show_help()
            elif action == "titan_apps":
                self.parent.show_app_list()
                self.Hide()
            elif action == "titan_games":
                self.parent.show_game_list()
                self.Hide()
            elif action == "control_panel":
                if self.is_windows:
                    subprocess.run(['control'], shell=True)
            elif action == "titan_settings":
                # Open Titan settings like from menu bar
                try:
                    from settingsgui import SettingsFrame
                    settings_frame = SettingsFrame(None, title=_("Settings"))
                    settings_frame.Show()
                    self.Hide()
                except Exception as e:
                    print(f"Error opening Titan settings: {e}")
            elif action == "my_documents":
                # Open My Documents folder in TFM
                try:
                    from app_manager import find_application_by_shortname, open_application
                    import sys
                    
                    # Find TFM application
                    tfm_app = find_application_by_shortname("tfm")
                    if tfm_app:
                        documents_path = os.path.expanduser("~/Documents")
                        # Open TFM with documents path using app_manager
                        open_application(tfm_app, documents_path)
                    else:
                        print("TFM application not found")
                        # Ultimate fallback: open with system explorer
                        if self.is_windows:
                            documents_path = os.path.expanduser("~/Documents")
                            subprocess.run(['explorer', documents_path], shell=True)
                    
                    self.Hide()
                except Exception as e:
                    print(f"Error opening TFM: {e}")
                    # Ultimate fallback: open with system explorer
                    if self.is_windows:
                        documents_path = os.path.expanduser("~/Documents")
                        subprocess.run(['explorer', documents_path], shell=True)
            
        except Exception as e:
            print(f"Error executing action {action}: {e}")
    
    def load_windows_programs(self):
        """Ładowanie programów Windows (uproszczona wersja)"""
        programs = []
        
        try:
            # Programs from Start Menu
            start_menu_path = os.path.join(
                os.environ.get('ALLUSERSPROFILE', ''),
                'Microsoft', 'Windows', 'Start Menu', 'Programs'
            )
            
            if os.path.exists(start_menu_path):
                for root, dirs, files in os.walk(start_menu_path):
                    for file in files[:10]:  # Limit files
                        if file.endswith('.lnk'):
                            name = os.path.splitext(file)[0]
                            programs.append({
                                'name': name,
                                'path': os.path.join(root, file),
                                'type': 'shortcut'
                            })
                            if len(programs) >= 20:
                                break
                    if len(programs) >= 20:
                        break
            
        except Exception as e:
            print(f"Error loading programs: {e}")
        
        return programs
    
    def get_localized_folder_name(self, folder_path):
        """Pobierz zlokalizowaną nazwę folderu z Windows"""
        try:
            import ctypes
            from ctypes import wintypes, windll
            
            # Sprawdź czy to specjalny folder systemowy
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
            
            # Zwróć zlokalizowaną nazwę jeśli istnieje
            return special_folders.get(folder_name, folder_name)
            
        except Exception as e:
            print(f"Error getting localized folder name: {e}")
            return os.path.basename(folder_path)
    
    def get_system_folder_name(self, english_name):
        """Pobierz zlokalizowaną nazwę folderu systemowego"""
        try:
            # Mapowanie dla języka polskiego
            polish_names = {
                'Accessories': 'Akcesoria',
                'Administrative Tools': 'Narzędzia administracyjne',
                'Games': 'Gry',
                'Maintenance': 'Konserwacja',
                'System Tools': 'Narzędzia systemowe',
                'Startup': 'Autostart',
            }
            
            # Sprawdź język systemu
            import locale
            system_lang = locale.getdefaultlocale()[0]
            
            if system_lang and system_lang.startswith('pl'):
                return polish_names.get(english_name, english_name)
            
            return english_name
            
        except Exception:
            return english_name
    
    def load_windows_programs_with_folders(self):
        """Ładowanie programów Windows z zachowaniem struktury folderów"""
        folder_structure = {}
        
        try:
            # Ścieżki do Menu Start
            start_menu_paths = [
                os.path.join(os.environ.get('ALLUSERSPROFILE', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
                os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs')
            ]
            
            for start_path in start_menu_paths:
                if not os.path.exists(start_path):
                    continue
                
                # Przejdź przez wszystkie foldery
                for root, dirs, files in os.walk(start_path):
                    # Pomiń folder główny Programs
                    if root == start_path:
                        continue
                    
                    # Pobierz nazwę folderu
                    relative_path = os.path.relpath(root, start_path)
                    folder_parts = relative_path.split(os.sep)
                    
                    # Użyj tylko pierwszego poziomu folderów (jak Windows XP)
                    if len(folder_parts) > 1:
                        continue
                    
                    folder_name = self.get_localized_folder_name(root)
                    
                    # Inicjalizuj folder jeśli nie istnieje
                    if folder_name not in folder_structure:
                        folder_structure[folder_name] = []
                    
                    # Dodaj programy z tego folderu
                    for file in files:
                        if file.endswith('.lnk'):
                            full_path = os.path.join(root, file)
                            name = os.path.splitext(file)[0]
                            
                            # Skip uninstall and help shortcuts
                            if any(skip in name.lower() for skip in 
                                   ['uninstall', 'uninstaller', 'remove', 'readme', 'help', 'manual']):
                                continue
                            
                            # Try to get better display name from shortcut properties
                            display_name = self.get_shortcut_display_name(full_path) or name
                            
                            folder_structure[folder_name].append({
                                'name': display_name,
                                'path': full_path,
                                'type': 'shortcut'
                            })
                    
                    # Load all folders - no limit for complete menu
                    # if len(folder_structure) >= 15:
                    #     break
            
            # Sortuj foldery alfabetycznie
            sorted_structure = {}
            for folder_name in sorted(folder_structure.keys()):
                if folder_structure[folder_name]:  # Tylko niepuste foldery
                    sorted_structure[folder_name] = folder_structure[folder_name]
            
            return sorted_structure
            
        except Exception as e:
            print(f"Error loading Windows programs with folders: {e}")
            return {}
    
    def get_shortcut_display_name(self, shortcut_path):
        """Get display name from Windows shortcut file"""
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
                description = shortcut.GetDescription(0)
                if description and description.strip():
                    return description.strip()
                    
                # Fallback: get target executable name
                target_path, _ = shortcut.GetPath(0)
                if target_path:
                    return os.path.splitext(os.path.basename(target_path))[0]
                    
            except ImportError:
                # win32com not available, use simpler approach
                pass
                
        except Exception as e:
            # Any error, fallback to filename
            pass
            
        return None
    
    
    def run_program(self, program):
        """Uruchomienie programu"""
        try:
            if program['type'] == 'shortcut' and self.is_windows:
                # Use Windows startfile for .lnk shortcuts
                os.startfile(program['path'])
            elif program['type'] == 'exe':
                # Direct executable
                subprocess.run([program['path']], shell=True)
            else:
                # Fallback - try to open with system default
                os.startfile(program['path'])
            
            self.Hide()
            
        except Exception as e:
            print(f"Error running program {program['name']}: {e}")
    
    def show_run_dialog(self):
        """Dialog 'Uruchom...' - systemowy Windows Run dialog"""
        try:
            # Use Windows native Run dialog
            if self.is_windows:
                subprocess.run(['rundll32', 'shell32.dll,#61'], shell=True)
                self.Hide()
            else:
                # Fallback for non-Windows systems
                dlg = wx.TextEntryDialog(self, _("Enter program name:"), _("Run..."))
                if dlg.ShowModal() == wx.ID_OK:
                    command = dlg.GetValue()
                    if command:
                        try:
                            subprocess.run(command, shell=True)
                            self.Hide()
                        except Exception as e:
                            wx.MessageBox(f"Error: {e}", "Error", wx.OK | wx.ICON_ERROR)
                dlg.Destroy()
        except Exception as e:
            print(f"Error opening run dialog: {e}")
    
    def show_find_dialog(self):
        """Dialog wyszukiwania - systemowy Windows Search"""
        try:
            if self.is_windows:
                # Use Windows native search
                subprocess.run(['rundll32', 'shell32.dll,SHFindFiles'], shell=True)
                self.Hide()
            else:
                wx.MessageBox(_("Search function in development"), _("Find"), wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            print(f"Error opening find dialog: {e}")
    
    def show_help(self):
        """Pomoc - systemowa Windows Help"""
        try:
            if self.is_windows:
                # Use Windows native help
                subprocess.run(['hh.exe'], shell=True)
                self.Hide()
            else:
                wx.MessageBox(_("Help function"), _("Help"), wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            print(f"Error opening help: {e}")
    
    def on_shutdown(self, event):
        """Obsługa przycisku zamknij system - systemowy dialog Windows jak Alt+F4 na pulpicie"""
        try:
            if self.is_windows:
                # Use Windows shutdown dialog (same as Alt+F4 on desktop)  
                try:
                    import ctypes
                    from ctypes import wintypes
                    
                    # Call ExitWindowsEx API to show shutdown dialog
                    user32 = ctypes.windll.user32
                    # EWX_LOGOFF | EWX_POWEROFF
                    user32.ExitWindowsEx(0, 0)
                    self.Hide()
                except Exception:
                    # Fallback to shutdown command
                    subprocess.run(['shutdown', '/s', '/t', '60'], shell=True)  # 60 second delay
                    self.Hide()
            else:
                # Fallback for non-Windows systems
                dlg = wx.MessageDialog(self, 
                                      _("Do you want to shut down the system?"),
                                      _("Shut Down Windows"),
                                      wx.YES_NO | wx.ICON_QUESTION)
                
                if dlg.ShowModal() == wx.ID_YES:
                    self.parent.Close()
                
                dlg.Destroy()
                self.Hide()
        except Exception as e:
            print(f"Error opening shutdown dialog: {e}")
            # Fallback to remote shutdown if SlShutdown not available
            try:
                subprocess.run(['shutdown', '/s', '/t', '0'], shell=True)
            except Exception as e2:
                print(f"Fallback shutdown failed: {e2}")
    
    def on_close(self, event):
        """Zamknięcie menu"""
        self.Hide()
    
    def on_activate(self, event):
        """Obsługa aktywacji okna"""
        if event.GetActive():
            wx.CallAfter(self.menu_tree.SetFocus)
    
    def on_kill_focus(self, event):
        """Ukryj menu gdy straci focus"""
        wx.CallLater(100, self.check_and_hide)
    
    def check_and_hide(self):
        """Sprawdź czy ukryć menu"""
        focus_window = wx.Window.FindFocus()
        if not focus_window or not self.IsDescendant(focus_window):
            self.Hide()
    
    def position_menu(self):
        """Umieszczenie menu w lewym dolnym rogu"""
        screen_size = wx.GetDisplaySize()
        menu_size = self.GetSize()
        
        x = 10
        y = screen_size.height - menu_size.height - 50
        
        self.SetPosition((x, y))
    
    def show_menu(self):
        """Pokaż menu"""
        self.Show()
        self.Raise()
        wx.CallAfter(self.menu_tree.SetFocus)
    
    def toggle_menu(self):
        """Przełącz widoczność menu"""
        if self.IsShown():
            self.Hide()
        else:
            self.show_menu()
    
    def apply_skin_settings(self):
        """Zastosuj ustawienia skórki do menu"""
        try:
            # Pobierz aktualne ustawienia skórki z rodzica
            if hasattr(self.parent, 'settings') and self.parent.settings:
                skin_name = self.parent.settings.get('interface', {}).get('skin', 'default')
                skin_data = self.parent.load_skin_data(skin_name) if hasattr(self.parent, 'load_skin_data') else {}
                
                self.configure_from_skin(skin_data.get('StartMenu', {}), skin_data.get('Colors', {}))
        except Exception as e:
            print(f"Error applying skin to start menu: {e}")
    
    def configure_from_skin(self, start_menu_config, colors):
        """Konfiguruj menu na podstawie ustawień skórki"""
        try:
            # Logo text
            logo_text = start_menu_config.get('logo_text', 'Windows')
            if hasattr(self, 'logo_panel'):
                logo_children = self.logo_panel.GetChildren()
                if logo_children and len(logo_children) >= 2:
                    logo_label = logo_children[0]  # Windows text
                    if hasattr(logo_label, 'SetLabel'):
                        logo_label.SetLabel(logo_text)
            
            # Logo colors
            logo_text_color = start_menu_config.get('logo_text_color', '#FFFFFF')
            logo_bg_color = start_menu_config.get('logo_background_color', '#000080')
            
            if hasattr(self, 'logo_panel'):
                try:
                    # Convert hex colors to wx.Colour
                    bg_color = wx.Colour(logo_bg_color)
                    self.logo_panel.SetBackgroundColour(bg_color)
                    
                    text_color = wx.Colour(logo_text_color)
                    
                    for child in self.logo_panel.GetChildren():
                        if hasattr(child, 'SetForegroundColour'):
                            child.SetForegroundColour(text_color)
                except Exception as e:
                    print(f"Error setting logo colors: {e}")
            
            # Main panel colors
            if hasattr(self, 'GetChildren'):
                main_panel = self.GetChildren()[0] if self.GetChildren() else None
                if main_panel and colors.get('panel_background_color'):
                    try:
                        panel_color = wx.Colour(colors['panel_background_color'])
                        
                        # Apply to main panels
                        for child in main_panel.GetChildren():
                            if hasattr(child, 'SetBackgroundColour'):
                                child.SetBackgroundColour(panel_color)
                    except Exception as e:
                        print(f"Error setting panel colors: {e}")
            
            # Refresh display
            self.Refresh()
            self.Update()
            
        except Exception as e:
            print(f"Error configuring menu from skin: {e}")


class ClassicSubmenu(wx.Frame):
    """Podmenu w stylu Windows 95"""
    
    def __init__(self, parent, title):
        super().__init__(parent, title="", 
                         style=wx.FRAME_NO_TASKBAR | wx.STAY_ON_TOP | wx.BORDER_SIMPLE)
        
        self.parent = parent
        self.items = []
        
        # Panel główny
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(192, 192, 192))
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.listbox = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.listbox.SetBackgroundColour(wx.Colour(255, 255, 255))
        self.listbox.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        
        sizer.Add(self.listbox, 1, wx.ALL | wx.EXPAND, 2)
        panel.SetSizer(sizer)
        
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_activate)
        self.listbox.Bind(wx.EVT_KEY_DOWN, self.on_key)
        
        self.SetSize((200, 150))
    
    def add_item(self, item):
        """Dodaj element do podmenu"""
        self.items.append(item)
        
        if item.is_separator:
            self.listbox.Append("─" * 20, None)
        else:
            self.listbox.Append(item.name, item)
    
    def show_at_cursor(self):
        """Pokaż podmenu przy kursorze"""
        mouse_pos = wx.GetMousePosition()
        self.SetPosition((mouse_pos.x + 10, mouse_pos.y))
        self.Show()
        self.listbox.SetFocus()
    
    def on_activate(self, event):
        """Aktywacja elementu podmenu"""
        selection = self.listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            item = self.listbox.GetClientData(selection)
            if item:
                if item.submenu:
                    # Otwórz podmenu folderu
                    self.show_folder_submenu(item.submenu)
                elif item.action:
                    item.action()
                    self.Hide()
    
    def show_folder_submenu(self, programs):
        """Pokaż podmenu z programami z folderu"""
        try:
            folder_menu = ClassicSubmenu(self.parent, "Folder Programs")
            
            # Dodaj programy z folderu
            for program in programs:
                # Create a closure to capture program variable properly
                def make_action(prog):
                    return lambda: self.parent.run_program(prog)
                
                folder_menu.add_item(ClassicMenuItem(
                    program['name'],
                    action=make_action(program)
                ))
            
            # Pokaż menu obok obecnego
            current_pos = self.GetPosition()
            menu_size = self.GetSize()
            folder_menu.SetPosition((current_pos.x + menu_size.width + 5, current_pos.y))
            folder_menu.Show()
            folder_menu.listbox.SetFocus()
            
        except Exception as e:
            print(f"Error showing folder submenu: {e}")
    
    def on_key(self, event):
        """Obsługa klawiszy"""
        key_code = event.GetKeyCode()
        
        if key_code == wx.WXK_RETURN:
            self.on_activate(event)
        elif key_code == wx.WXK_ESCAPE:
            self.Hide()
        else:
            event.Skip()


def create_classic_start_menu(parent):
    """Tworzenie klasycznego menu Start"""
    return ClassicStartMenu(parent)