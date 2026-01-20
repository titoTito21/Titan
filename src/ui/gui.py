import wx
import wx.adv
import os
import platform
import threading
import subprocess
import shutil
import traceback
import configparser
import sys
import time
from src.network import telegram_client
from src.network import telegram_windows
from src.network import messenger_webview
from src.network import whatsapp_webview

from src.titan_core.app_manager import get_applications, open_application
from src.titan_core.game_manager import get_games, open_game
from src.system.notifications import get_current_time, get_battery_status, get_volume_level, get_network_status
from src.titan_core.sound import initialize_sound, play_focus_sound, play_select_sound, play_statusbar_sound, play_applist_sound, play_endoflist_sound, play_sound
import accessible_output3.outputs.auto
from src.ui.menu import MenuBar
from src.ui.invisibleui import InvisibleUI
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.ui.shutdown_question import show_shutdown_dialog
from src.ui.classic_start_menu import create_classic_start_menu
from src.ui.help import show_help
from src.controller.controller_vibrations import (
    vibrate_cursor_move, vibrate_menu_open, vibrate_menu_close, vibrate_selection,
    vibrate_focus_change, vibrate_error, vibrate_notification
)
from src.controller.controller_ui import initialize_controller_system, shutdown_controller_system
from src.titan_core.skin_manager import get_skin_manager, get_current_skin, apply_skin_to_window
from src.accessibility.messages import show_invisible_ui_tip

# Get the translation function
_ = set_language(get_setting('language', 'pl'))


def _get_base_path():
    """Get base path for resources, supporting PyInstaller and Nuitka."""
    # For both PyInstaller and Nuitka, use executable directory
    # (data directories are placed next to exe for backward compatibility)
    if hasattr(sys, '_MEIPASS') or getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        # Development mode - get project root (2 levels up from src/ui/)
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


# Get project root directory (supports PyInstaller and Nuitka)
PROJECT_ROOT = _get_base_path()
SKINS_DIR = os.path.join(PROJECT_ROOT, 'skins')
DEFAULT_SKIN_NAME = _("Default")
speaker = accessible_output3.outputs.auto.Auto()

class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame, version, skin_data):
        """Initialize TaskBarIcon with comprehensive error handling."""
        try:
            super(TaskBarIcon, self).__init__()
            self.frame = frame
            
            # Safely get icon path
            icon_path = None
            try:
                if skin_data and isinstance(skin_data, dict):
                    if 'Icons' in skin_data and isinstance(skin_data['Icons'], dict):
                        if 'taskbar_icon' in skin_data['Icons']:
                            icon_path = skin_data['Icons']['taskbar_icon']
            except (TypeError, AttributeError, KeyError):
                pass

            # Create icon safely
            icon = None
            if icon_path and os.path.exists(icon_path):
                try:
                    icon = wx.Icon(icon_path)
                    if not icon.IsOk():
                        print(f"WARNING: Could not load taskbar icon from: {icon_path}")
                        icon = None
                except (wx.PyAssertionError, Exception) as e:
                    print(f"Error loading taskbar icon: {e}")
                    icon = None
            
            # Fallback to default icon if needed
            if icon is None:
                try:
                    icon = wx.Icon(wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_OTHER, (16, 16)))
                except Exception as e:
                    print(f"Error creating fallback taskbar icon: {e}")
                    # Create empty icon as last resort
                    try:
                        icon = wx.Icon()
                    except:
                        icon = None

            # Set icon safely
            if icon:
                try:
                    self.SetIcon(icon, _("Titan v{}").format(version))
                except Exception as e:
                    print(f"Error setting taskbar icon: {e}")
            
            # Bind events safely
            try:
                self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_left_dclick)
            except Exception as e:
                print(f"Error binding taskbar events: {e}")
                
        except Exception as e:
            print(f"Critical error in TaskBarIcon.__init__: {e}")
            # Don't re-raise here, let the app continue without taskbar icon

    def CreatePopupMenu(self):
        menu = wx.Menu()
        menu.Append(wx.ID_ANY, _("Back to Titan"), _("Restores the application window"))
        menu.Bind(wx.EVT_MENU, self.on_restore)
        return menu

    def on_left_dclick(self, event):
        self.frame.restore_from_tray()

    def on_restore(self, event):
        self.frame.restore_from_tray()


class TitanApp(wx.Frame):
    def __init__(self, *args, version, settings=None, component_manager=None, start_minimized=False, **kw):
        """Initialize TitanApp with comprehensive error handling to prevent segfaults."""
        try:
            super(TitanApp, self).__init__(*args, **kw)
            
            # Initialize basic attributes first
            self.version = version
            self.settings = settings or {}
            self.component_manager = component_manager
            self.task_bar_icon = None
            self.start_minimized = start_minimized
            self.timer = None  # Initialize timer to None first
            
            # Initialize invisible UI safely
            try:
                self.invisible_ui = InvisibleUI(self, component_manager=self.component_manager)
            except Exception as e:
                print(f"Warning: Failed to initialize InvisibleUI: {e}")
                self.invisible_ui = None

            
            # Multi-service session management
            self.active_services = {}  # Dict to store active service connections
            self.current_service = None  # Currently selected service for chat
            
            # Legacy compatibility - will be removed gradually
            self.logged_in = False
            self.telegram_client = None
            self.online_users = []
            self.current_chat_user = None
            self.unread_messages = {}
            self.call_active = False
            self.call_window = None
            
            # Debouncing for mouse motion sounds
            self.last_statusbar_sound_time = 0
            self.statusbar_sound_delay = 0.2  # 200ms delay for statusbar sounds

            # Flag to skip focus sound during expand/collapse/endoflist
            self._skip_focus_sound = False

            # Status cache to prevent GUI blocking
            self.status_cache = {
                'time': get_current_time(),
                'battery': 'Loading...',
                'volume': 'Loading...',
                'network': 'Loading...'
            }
            self.status_cache_lock = threading.Lock()
            self.status_update_thread = None
            self.status_thread_running = True
            self.status_thread_stop_event = threading.Event()  # Event for immediate thread shutdown

            # Initialize sound system safely
            try:
                initialize_sound()
            except Exception as e:
                print(f"Warning: Failed to initialize sound in TitanApp: {e}")

            # Initialize controller system with this window
            try:
                initialize_controller_system(parent_window=self)
                print("[GUI] Controller system initialized with TitanApp window")
            except Exception as e:
                print(f"Warning: Failed to initialize controller in TitanApp: {e}")

            self.current_list = "apps"
            
            # Inicjalizacja Start Menu (tylko dla Windows) - zawsze klasyczne
            # Defer Start Menu creation to avoid blocking during initialization
            self.start_menu = None
            if platform.system() == "Windows":
                # Create Start Menu later using CallAfter to avoid blocking
                wx.CallAfter(self._create_start_menu_deferred)

            # Start background status update thread
            try:
                self.status_update_thread = threading.Thread(target=self._update_status_cache_loop, daemon=True)
                self.status_update_thread.start()
                print("[GUI] Background status update thread started")
            except Exception as e:
                print(f"Warning: Failed to start status update thread: {e}")
                self.status_update_thread = None
            # Initialize timer safely - defer to avoid blocking
            self.timer = None
            wx.CallAfter(self._create_timer_deferred)

            # Only initialize UI if not starting minimized
            if not self.start_minimized:
                try:
                    self.InitUI()
                    self.populate_app_list()
                    self.populate_game_list()
                    self.apply_selected_skin()
                    self.show_app_list()
                    print("[GUI] UI initialization complete")
                except Exception as e:
                    print(f"Error initializing UI: {e}")
                    import traceback
                    traceback.print_exc()
                    # Continue anyway, app might still work in minimal mode
                    
        except Exception as e:
            print(f"Critical error in TitanApp.__init__: {e}")
            # Re-raise to let main.py handle it
            raise
    
    def get_skin_start_menu_style(self, skin_name):
        """Pobierz styl Start Menu ze skórki"""
        try:
            skin_data = self.load_skin_data(skin_name)
            start_menu_config = skin_data.get('StartMenu', {})
            return start_menu_config.get('style', 'modern')
        except:
            return 'modern'
    
    def get_available_skins(self):
        """Pobierz listę dostępnych skórek"""
        skins = [DEFAULT_SKIN_NAME]
        
        if os.path.exists(SKINS_DIR):
            for item in os.listdir(SKINS_DIR):
                skin_path = os.path.join(SKINS_DIR, item)
                if os.path.isdir(skin_path):
                    skin_ini = os.path.join(skin_path, 'skin.ini')
                    if os.path.exists(skin_ini):
                        skins.append(item)
        
        return skins

    def _create_start_menu_deferred(self):
        """Create Start Menu in a deferred manner to avoid blocking initialization"""
        try:
            if self.start_menu is None:
                self.start_menu = create_classic_start_menu(self)
                print("[GUI] Start Menu created successfully (deferred)")
        except Exception as e:
            print(f"Warning: Failed to create start menu (deferred): {e}")
            import traceback
            traceback.print_exc()
            self.start_menu = None

    def _create_timer_deferred(self):
        """Create timer in a deferred manner to avoid blocking initialization"""
        try:
            if self.timer is None:
                self.timer = wx.Timer(self)
                self.Bind(wx.EVT_TIMER, self.update_statusbar, self.timer)
                self.timer.Start(5000)
                print("[GUI] Timer created and started successfully (deferred)")
        except Exception as e:
            print(f"Warning: Failed to create timer (deferred): {e}")
            import traceback
            traceback.print_exc()

    def switch_skin(self, skin_name):
        """Switch application skin using skin manager"""
        try:
            skin_manager = get_skin_manager()

            # Switch skin and save to settings
            if skin_manager.switch_skin(skin_name):
                # Apply new skin
                self.apply_selected_skin()

                # Refresh Start Menu with new skin
                if platform.system() == "Windows" and self.start_menu:
                    try:
                        self.start_menu.apply_skin_settings()
                    except Exception as e:
                        print(f"Error refreshing start menu skin: {e}")

                print(f"Switched to skin: {skin_name}")
            else:
                print(f"Failed to switch to skin: {skin_name}")

        except Exception as e:
            print(f"Error switching skin: {e}")
    
    def apply_skin_to_start_menu(self, skin_data):
        """Zastosuj ustawienia skórki do Start Menu"""
        if not self.start_menu or not skin_data:
            return
        
        start_menu_config = skin_data.get('StartMenu', {})
        colors = skin_data.get('Colors', {})
        
        # Konfiguracja Start Menu
        if hasattr(self.start_menu, 'configure_from_skin'):
            self.start_menu.configure_from_skin(start_menu_config, colors)
    
    def apply_skin_sound_theme(self, skin_name):
        """Zastosuj motyw dźwiękowy ze skórki"""
        try:
            skin_data = self.load_skin_data(skin_name)
            sounds_config = skin_data.get('Sounds', {})
            sound_theme = sounds_config.get('theme')
            
            if sound_theme:
                from sound import set_theme
                set_theme(sound_theme)
                print(f"Applied sound theme: {sound_theme} for skin: {skin_name}")
        except Exception as e:
            print(f"Error applying sound theme for skin {skin_name}: {e}")


    def InitUI(self):
        panel = wx.Panel(self)
        main_vbox = wx.BoxSizer(wx.VERTICAL)

        self.toolbar = self.CreateToolBar()

        empty_bitmap = wx.Bitmap(1, 1)

        self.tool_apps = self.toolbar.AddTool(wx.ID_ANY, _("Application List"), empty_bitmap, shortHelp=_("Show application list"))
        self.tool_games = self.toolbar.AddTool(wx.ID_ANY, _("Game List"), empty_bitmap, shortHelp=_("Show game list"))
        self.tool_network = self.toolbar.AddTool(wx.ID_ANY, _("Titan IM"), empty_bitmap, shortHelp=_("Show Titan IM"))

        self.toolbar.Realize()

        self.Bind(wx.EVT_TOOL, self.on_show_apps, self.tool_apps)
        self.Bind(wx.EVT_TOOL, self.on_show_games, self.tool_games)
        self.Bind(wx.EVT_TOOL, self.on_show_network, self.tool_network)


        self.list_label = wx.StaticText(panel, label=_("Application List:"))
        main_vbox.Add(self.list_label, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.app_listbox = wx.ListBox(panel)
        self.game_tree = wx.TreeCtrl(panel, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_SINGLE)
        self.network_listbox = wx.ListBox(panel)
        self.users_listbox = wx.ListBox(panel)
        
        # Chat elements (hidden - functionality moved to separate windows)
        self.chat_display = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.message_input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.chat_display.Hide()
        self.message_input.Hide()

        # Login Panel
        self.login_panel = wx.Panel(panel)
        login_sizer = wx.BoxSizer(wx.VERTICAL)

        self.username_label = wx.StaticText(self.login_panel, label=_("Numer telefonu (z kodem kraju):"))
        self.username_text = wx.TextCtrl(self.login_panel)
        
        # Load last used phone number
        last_phone = telegram_client.get_last_phone_number()
        if last_phone:
            self.username_text.SetValue(last_phone)
        self.password_label = wx.StaticText(self.login_panel, label=_("2FA Password (if enabled):"))
        self.password_text = wx.TextCtrl(self.login_panel, style=wx.TE_PASSWORD)
        self.login_button = wx.Button(self.login_panel, label=_("OK"))
        self.create_account_button = wx.Button(self.login_panel, label=_("Create Account"))

        login_sizer.Add(self.username_label, 0, wx.ALL, 5)
        login_sizer.Add(self.username_text, 0, wx.EXPAND|wx.ALL, 5)
        login_sizer.Add(self.password_label, 0, wx.ALL, 5)
        login_sizer.Add(self.password_text, 0, wx.EXPAND|wx.ALL, 5)
        login_sizer.Add(self.login_button, 0, wx.ALL, 5)
        login_sizer.Add(self.create_account_button, 0, wx.ALL, 5)

        self.login_panel.SetSizer(login_sizer)
        self.login_panel.Hide()
        self.create_account_button.Hide()  # Hidden by default, shown for Titan-Net

        self.login_button.Bind(wx.EVT_BUTTON, self.on_login)
        # create_account_button binding is set dynamically in show_titannet_login

        self.logout_button = wx.Button(panel, label=_("Logout"))
        self.logout_button.Bind(wx.EVT_BUTTON, self.on_logout)
        self.logout_button.Hide()


        list_sizer = wx.BoxSizer(wx.VERTICAL)
        list_sizer.Add(self.app_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        list_sizer.Add(self.game_tree, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        list_sizer.Add(self.network_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        list_sizer.Add(self.users_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        
        # Chat panel (hidden - functionality moved to separate windows)
        chat_sizer = wx.BoxSizer(wx.VERTICAL)
        chat_label = wx.StaticText(panel, label=_("Chat:"))
        chat_label.Hide()
        chat_sizer.Add(chat_label, 0, wx.ALL, 5)
        chat_sizer.Add(self.chat_display, 1, wx.EXPAND | wx.ALL, 5)
        
        input_sizer = wx.BoxSizer(wx.HORIZONTAL)
        input_sizer.Add(self.message_input, 1, wx.EXPAND | wx.ALL, 5)
        send_btn = wx.Button(panel, label=_("Send"))
        send_btn.Hide()  # Hidden since functionality moved to separate windows
        input_sizer.Add(send_btn, 0, wx.ALL, 5)
        chat_sizer.Add(input_sizer, 0, wx.EXPAND)
        
        list_sizer.Add(chat_sizer, proportion=2, flag=wx.EXPAND|wx.ALL, border=0)
        list_sizer.Add(self.login_panel, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        main_vbox.Add(list_sizer, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)
        main_vbox.Add(self.logout_button, 0, wx.ALL, 5)

        main_vbox.Add(list_sizer, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)

        main_vbox.Add(wx.StaticText(panel, label=_("Status Bar:")), flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.statusbar_listbox = wx.ListBox(panel)
        self.populate_statusbar()

        main_vbox.Add(self.statusbar_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

        self.app_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_app_selected)
        self.game_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_game_tree_activated)
        self.game_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_game_tree_selection_changed)
        self.game_tree.Bind(wx.EVT_TREE_ITEM_EXPANDED, self.on_game_tree_expanded)
        self.game_tree.Bind(wx.EVT_TREE_ITEM_COLLAPSED, self.on_game_tree_collapsed)
        self.game_tree.Bind(wx.EVT_KEY_DOWN, self.on_game_tree_key_down)
        self.network_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_network_option_selected)
        self.users_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_user_selected)
        self.users_listbox.Bind(wx.EVT_RIGHT_UP, self.on_users_context_menu)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.Bind(wx.EVT_ICONIZE, self.on_minimize)

        self.app_listbox.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu)
        self.game_tree.Bind(wx.EVT_CONTEXT_MENU, self.on_game_tree_context_menu)

        self.statusbar_listbox.Bind(wx.EVT_MOTION, self.on_focus_change_status)


        panel.SetSizer(main_vbox)

        self.SetSize((600, 800))
        self.SetTitle(_("Titan App Suite"))
        self.Centre()

    def load_skin_data(self, skin_name):
        skin_data = {
            'Colors': {},
            'Fonts': {},
            'Icons': {}
        }
        skin_path = os.path.join(SKINS_DIR, skin_name)
        skin_ini_path = os.path.join(skin_path, 'skin.ini')

        if skin_name == DEFAULT_SKIN_NAME or not os.path.exists(skin_ini_path):
            print(f"INFO: Loading default skin or skin.ini file not found in {skin_path}")
            skin_data['Colors'] = {
                'frame_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_FRAMEBK),
                'panel_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
                'listbox_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
                'listbox_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                'listbox_selection_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT),
                'listbox_selection_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT),
                'label_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT),
                'toolbar_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE) # Changed from wx.SYS_COLOUR_TOOLBAR
            }
            skin_data['Fonts']['default_font_size'] = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetPointSize()
            skin_data['Fonts']['listbox_font_face'] = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetFaceName()
            skin_data['Fonts']['statusbar_font_face'] = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetFaceName()

            skin_data['Icons'] = {}


        else:
            print(f"INFO: Loading skin from: {skin_ini_path}")
            config = configparser.ConfigParser()
            try:
                config.read(skin_ini_path, encoding='utf-8')

                if 'Colors' in config:
                    for key, value in config['Colors'].items():
                        try:
                            color = wx.Colour(value)
                            if color.IsOk():
                                skin_data['Colors'][key] = color
                            else:
                                print(f"WARNING: Invalid color format in skin.ini: {value} for key {key}")
                                skin_data['Colors'][key] = wx.NullColour
                        except ValueError:
                             print(f"WARNING: Invalid color format in skin.ini: {value} for key {key}")
                             skin_data['Colors'][key] = wx.NullColour


                if 'Fonts' in config:
                    if 'default_font_size' in config['Fonts']:
                         try:
                             skin_data['Fonts']['default_font_size'] = int(config['Fonts']['default_font_size'])
                         except ValueError:
                             print(f"WARNING: Invalid font size format in skin.ini: {config['Fonts']['default_font_size']}")

                    if 'listbox_font_face' in config['Fonts']:
                         skin_data['Fonts']['listbox_font_face'] = config['Fonts']['listbox_font_face']

                    if 'statusbar_font_face' in config['Fonts']:
                         skin_data['Fonts']['statusbar_font_face'] = config['Fonts']['statusbar_font_face']


                if 'Icons' in config:
                    icon_base_path = skin_path
                    for key, value in config['Icons'].items():
                        icon_full_path = os.path.join(icon_base_path, value)
                        if os.path.exists(icon_full_path):
                             skin_data['Icons'][key] = icon_full_path
                        else:
                             print(f"WARNING: Icon file not found: {icon_full_path}")
                             skin_data['Icons'][key] = None


            except configparser.Error as e:
                print(f"ERROR: Error reading skin.ini file: {e}")
            except Exception as e:
                 print(f"ERROR: Unexpected error while loading skin: {e}")


        return skin_data

    def apply_skin(self, skin_data):
        if not skin_data:
            print("WARNING: No skin data to apply.")
            return

        colors = skin_data.get('Colors', {})
        fonts = skin_data.get('Fonts', {})
        icons = skin_data.get('Icons', {})

        if 'frame_background_color' in colors:
             self.SetBackgroundColour(colors['frame_background_color'])

        if hasattr(self, 'GetSizer') and self.GetSizer():
             panel = self.GetSizer().GetContainingWindow()
             if panel and 'panel_background_color' in colors:
                 panel.SetBackgroundColour(colors['panel_background_color'])

        listbox_elements = [self.app_listbox, self.statusbar_listbox]
        tree_elements = [self.game_tree]

        for listbox in listbox_elements:
             if 'listbox_background_color' in colors:
                 listbox.SetBackgroundColour(colors['listbox_background_color'])
             if 'listbox_foreground_color' in colors:
                 listbox.SetForegroundColour(colors['listbox_foreground_color'])

        for tree in tree_elements:
             if 'listbox_background_color' in colors:
                 tree.SetBackgroundColour(colors['listbox_background_color'])
             if 'listbox_foreground_color' in colors:
                 tree.SetForegroundColour(colors['listbox_foreground_color'])


        if 'label_foreground_color' in colors:
             self.list_label.SetForegroundColour(colors['label_foreground_color'])


        default_font_size = fonts.get('default_font_size', wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetPointSize())

        if 'listbox_font_face' in fonts:
             listbox_font_face = fonts['listbox_font_face']
             listbox_font = wx.Font(default_font_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName=listbox_font_face)
             for listbox in listbox_elements:
                 listbox.SetFont(listbox_font)
        else:
             listbox_font = self.app_listbox.GetFont()
             listbox_font.SetPointSize(default_font_size)
             for listbox in listbox_elements:
                  listbox.SetFont(listbox_font)


        if 'statusbar_font_face' in fonts:
             statusbar_font_face = fonts['statusbar_font_face']
             statusbar_font = wx.Font(default_font_size, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName=statusbar_font_face)
             if hasattr(self, 'statusbar_listbox'):
                 self.statusbar_listbox.SetFont(statusbar_font)


        if 'app_list_icon' in icons and icons['app_list_icon']:
            try:
                 icon_bitmap = wx.Bitmap(icons['app_list_icon'], wx.BITMAP_TYPE_ANY)
                 if icon_bitmap.IsOk():
                     self.toolbar.SetToolNormalBitmap(self.tool_apps.GetId(), icon_bitmap)
                     self.toolbar.Realize()
                 else:
                     print(f"WARNING: Could not load icon bitmap: {icons['app_list_icon']}")
            except Exception as e:
                 print(f"ERROR: Error applying icon {icons['app_list_icon']}: {e}")

        if 'game_list_icon' in icons and icons['game_list_icon']:
             try:
                  icon_bitmap = wx.Bitmap(icons['game_list_icon'], wx.BITMAP_TYPE_ANY)
                  if icon_bitmap.IsOk():
                      self.toolbar.SetToolNormalBitmap(self.tool_games.GetId(), icon_bitmap)
                      self.toolbar.Realize()
                  else:
                      print(f"WARNING: Could not load icon bitmap: {icons['game_list_icon']}")
             except Exception as e:
                  print(f"ERROR: Error applying icon {icons['game_list_icon']}: {e}")


        self.Refresh()
        self.Update()
        self.Layout()


    def apply_selected_skin(self):
        """Apply current skin using skin manager"""
        try:
            skin = get_current_skin()
            print(f"INFO: Applying skin: {skin.name}")

            # Apply to main window
            apply_skin_to_window(self)

            # Apply to all child windows recursively
            def apply_to_children(parent):
                for child in parent.GetChildren():
                    if isinstance(child, (wx.Panel, wx.Window)):
                        apply_skin_to_window(child)
                        apply_to_children(child)

            apply_to_children(self)

            # Refresh
            self.Refresh()
            self.Update()
            self.Layout()

        except Exception as e:
            print(f"Error applying skin: {e}")


    def _update_status_cache_loop(self):
        """Background thread to update status information without blocking GUI."""
        print("[GUI] Status cache update loop started")
        while self.status_thread_running:
            try:
                # Update time (fast operation)
                time_str = get_current_time()

                # Update battery (potentially slow)
                battery_str = get_battery_status()

                # Update volume (potentially very slow due to COM initialization)
                volume_str = get_volume_level()

                # Update network (potentially very slow due to subprocess)
                network_str = get_network_status()

                # Update cache atomically
                with self.status_cache_lock:
                    self.status_cache['time'] = time_str
                    self.status_cache['battery'] = battery_str
                    self.status_cache['volume'] = volume_str
                    self.status_cache['network'] = network_str

            except Exception as e:
                print(f"Warning: Error updating status cache: {e}")

            # Wait for 5 seconds or until stop event is set (for fast shutdown)
            if self.status_thread_stop_event.wait(timeout=5.0):
                break  # Stop event was set, exit immediately

        print("[GUI] Status cache update loop stopped")

    def populate_app_list(self):
        applications = get_applications()
        self.app_listbox.Clear()
        for app in applications:
            self.app_listbox.Append(app.get("name", _("Unknown App")), clientData=app)


    def populate_game_list(self):
        """Populate game tree with platform grouping"""
        from src.titan_core.game_manager import get_games_by_platform

        self.game_tree.DeleteAllItems()

        # Create invisible root
        root = self.game_tree.AddRoot("Root")

        # Get games grouped by platform
        games_by_platform = get_games_by_platform()

        # Platform display order
        platform_order = ['Titan-Games', 'Steam', 'Battle.net']

        # Store tree items for later reference
        self.game_platform_nodes = {}

        for platform in platform_order:
            if platform not in games_by_platform or not games_by_platform[platform]:
                continue

            games = games_by_platform[platform]

            # Create platform node with translated name
            platform_display = _(platform)
            platform_node = self.game_tree.AppendItem(root, f"{platform_display} ({len(games)})")
            self.game_tree.SetItemData(platform_node, {'type': 'platform', 'name': platform})
            self.game_platform_nodes[platform] = platform_node

            # Add games under platform
            for game in games:
                game_item = self.game_tree.AppendItem(platform_node, game.get('name', _('Unknown Game')))
                self.game_tree.SetItemData(game_item, {'type': 'game', 'data': game})

        # Expand all platform nodes by default
        for platform_node in self.game_platform_nodes.values():
            self.game_tree.Expand(platform_node)


    def populate_statusbar(self):
        """Populate statusbar with cached data to avoid blocking GUI."""
        self.statusbar_listbox.Clear()
        with self.status_cache_lock:
            self.statusbar_listbox.Append(_("Clock: {}").format(self.status_cache['time']))
            self.statusbar_listbox.Append(_("Battery level: {}").format(self.status_cache['battery']))
            self.statusbar_listbox.Append(_("Volume: {}").format(self.status_cache['volume']))
            self.statusbar_listbox.Append(self.status_cache['network'])

    def update_statusbar(self, event):
        """Update statusbar with cached data to avoid blocking GUI."""
        # If UI is not initialized (minimized start), update invisible UI status instead
        if self.start_minimized and not hasattr(self, 'statusbar_listbox'):
            # Update status data for invisible UI
            if hasattr(self, 'invisible_ui') and self.invisible_ui:
                self.invisible_ui.refresh_status_bar()
        else:
            # Normal status bar update for GUI mode - read from cache
            with self.status_cache_lock:
                self.statusbar_listbox.SetString(0, _("Clock: {}").format(self.status_cache['time']))
                self.statusbar_listbox.SetString(1, _("Battery level: {}").format(self.status_cache['battery']))
                self.statusbar_listbox.SetString(2, _("Volume: {}").format(self.status_cache['volume']))
                self.statusbar_listbox.SetString(3, self.status_cache['network'])


    def on_app_selected(self, event):
        selection = self.app_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            app_info = self.app_listbox.GetClientData(selection)
            if app_info:
                 play_select_sound()
                 vibrate_selection()  # Add vibration for app selection
                 open_application(app_info)
            else:
                 print("WARNING: No ClientData for selected application.")


    def on_game_tree_activated(self, event):
        """Handle game tree item activation (double-click or Enter)"""
        item = event.GetItem()
        if not item.IsOk():
            return

        item_data = self.game_tree.GetItemData(item)
        if not item_data:
            return

        if item_data.get('type') == 'game':
            game_info = item_data.get('data')
            if game_info:
                play_select_sound()
                vibrate_selection()
                open_game(game_info)
        elif item_data.get('type') == 'platform':
            # Toggle expansion on activation
            if self.game_tree.IsExpanded(item):
                self.game_tree.Collapse(item)
            else:
                self.game_tree.Expand(item)

    def on_game_tree_selection_changed(self, event):
        """Handle game tree selection change (for screen reader announcements)"""
        item = event.GetItem()
        if not item.IsOk():
            return

        item_data = self.game_tree.GetItemData(item)

        # Don't announce during expand/collapse to avoid conflicts with navigation sounds
        if self._skip_focus_sound:
            self._skip_focus_sound = False
            return

        # Announce selection with type information for screen readers
        text = self.game_tree.GetItemText(item)

        # Add type information if available
        if item_data and 'type' in item_data:
            item_type = item_data['type']
            if item_type == 'platform':
                # Check if expanded or collapsed
                if self.game_tree.IsExpanded(item):
                    text = f"{text}, {_('expanded folder')}"
                else:
                    text = f"{text}, {_('collapsed folder')}"
            elif item_type == 'game':
                text = f"{text}, {_('game')}"

        try:
            from src.titan_core.sound import speaker
            speaker.speak(text, interrupt=True)  # Interrupt previous announcements for smooth navigation
        except:
            pass

    def on_game_tree_expanded(self, event):
        """Handle game tree node expansion"""
        self._skip_focus_sound = True
        play_sound('ui/focus_expanded.ogg')

    def on_game_tree_collapsed(self, event):
        """Handle game tree node collapse"""
        self._skip_focus_sound = True
        play_sound('ui/focus_collabsed.ogg')

    def on_game_tree_key_down(self, event):
        """Handle keyboard navigation in game tree with end of list detection"""
        keycode = event.GetKeyCode()

        if keycode in [wx.WXK_UP, wx.WXK_DOWN]:
            current_item = self.game_tree.GetSelection()
            if not current_item.IsOk():
                event.Skip()
                return

            # Get next or previous item
            if keycode == wx.WXK_DOWN:
                next_item = self.get_next_tree_item(current_item)
                if not next_item or not next_item.IsOk():
                    # End of list - play sound and skip focus sound
                    self._skip_focus_sound = True
                    play_endoflist_sound()
                    return
            elif keycode == wx.WXK_UP:
                prev_item = self.get_prev_tree_item(current_item)
                if not prev_item or not prev_item.IsOk():
                    # Beginning of list - play sound and skip focus sound
                    self._skip_focus_sound = True
                    play_endoflist_sound()
                    return

        event.Skip()

    def get_next_tree_item(self, item):
        """Get next visible item in tree"""
        if not item.IsOk():
            return None

        # If item has children and is expanded, return first child
        if self.game_tree.ItemHasChildren(item) and self.game_tree.IsExpanded(item):
            child, cookie = self.game_tree.GetFirstChild(item)
            if child.IsOk():
                return child

        # Otherwise, get next sibling
        next_sibling = self.game_tree.GetNextSibling(item)
        if next_sibling.IsOk():
            return next_sibling

        # If no next sibling, go up and find parent's next sibling
        parent = self.game_tree.GetItemParent(item)
        root = self.game_tree.GetRootItem()
        while parent.IsOk() and parent != root:
            next_sibling = self.game_tree.GetNextSibling(parent)
            if next_sibling.IsOk():
                return next_sibling
            parent = self.game_tree.GetItemParent(parent)

        return None

    def get_prev_tree_item(self, item):
        """Get previous visible item in tree"""
        if not item.IsOk():
            return None

        # Get previous sibling
        prev_sibling = self.game_tree.GetPrevSibling(item)
        if prev_sibling.IsOk():
            # If prev sibling has children and is expanded, return last descendant
            while self.game_tree.ItemHasChildren(prev_sibling) and self.game_tree.IsExpanded(prev_sibling):
                last_child, cookie = self.game_tree.GetLastChild(prev_sibling)
                if last_child.IsOk():
                    prev_sibling = last_child
                else:
                    break
            return prev_sibling

        # If no previous sibling, return parent
        parent = self.game_tree.GetItemParent(item)
        if parent.IsOk() and parent != self.game_tree.GetRootItem():
            return parent

        return None

    def on_game_tree_context_menu(self, event):
        """Handle context menu on game tree"""
        selection = self.game_tree.GetSelection()
        if not selection.IsOk():
            return

        item_data = self.game_tree.GetItemData(selection)
        if not item_data or item_data.get('type') != 'game':
            return

        game_info = item_data.get('data')
        if not game_info:
            return

        play_sound('ui/contextmenu.ogg')
        vibrate_menu_open()

        # Create context menu
        menu = wx.Menu()
        open_item = menu.Append(wx.ID_ANY, _("Open"))

        def on_open(e):
            play_select_sound()
            vibrate_selection()
            open_game(game_info)

        self.Bind(wx.EVT_MENU, on_open, open_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def on_list_context_menu(self, event):
        listbox = event.GetEventObject()
        selected_index = listbox.GetSelection()

        if selected_index != wx.NOT_FOUND:
            item_data = listbox.GetClientData(selected_index)
            if not item_data:
                 print("WARNING: No ClientData for selected context menu item.")
                 event.Skip()
                 return

            item_type = None
            if listbox == self.app_listbox:
                 item_type = "app"

            if not item_type:
                 print("ERROR: Could not determine context menu item type.")
                 event.Skip()
                 return

            play_sound('ui/contextmenu.ogg')
            vibrate_menu_open()  # Add vibration for menu opening

            menu = wx.Menu()

            run_label = _("Run {}...").format(item_data.get('name', _('item')))
            run_item = menu.Append(wx.ID_ANY, run_label)
            self.Bind(wx.EVT_MENU, lambda evt, data=item_data, type=item_type: self.on_run_from_context_menu(evt, item_data=data, item_type=type), run_item)

            uninstall_label = _("Uninstall {}").format(item_data.get('name', _('item')))
            uninstall_item = menu.Append(wx.ID_ANY, uninstall_label)
            self.Bind(wx.EVT_MENU, lambda evt, data=item_data, type=item_type: self.on_uninstall(evt, item_data=data, item_type=type), uninstall_item)

            listbox.PopupMenu(menu, event.GetPosition())

            play_sound('ui/contextmenuclose.ogg')
            vibrate_menu_close()  # Add vibration for menu closing

            menu.Destroy()

        event.Skip()


    def on_run_from_context_menu(self, event, item_data=None, item_type=None):
        if not item_data or not item_type:
            print("ERROR: No item data to run from context menu.")
            wx.MessageBox(_("An error occurred: No data to run."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        if item_type == "app":
            play_select_sound()
            vibrate_selection()  # Add vibration for selection/activation
            open_application(item_data)
        elif item_type == "game":
            play_select_sound()
            vibrate_selection()  # Add vibration for selection/activation
            open_game(item_data)
        else:
            print(f"ERROR: Unknown item type ({item_type}) to run from context menu.")


    def on_uninstall(self, event, item_data=None, item_type=None):
        if not item_data or not item_type:
            print("ERROR: No item data or type to uninstall from context menu.")
            wx.MessageBox(_("An error occurred: No data to uninstall."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        item_name = item_data.get('name', _('unknown item'))
        item_path = item_data.get('path')

        if not item_path or not os.path.exists(item_path):
            print(f"ERROR: Uninstall path is invalid or directory does not exist: {item_path}")
            wx.MessageBox(_("Error: Cannot find the directory '{}' to uninstall.").format(item_name), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        confirm_dialog = wx.MessageDialog(
            self,
            _("Are you sure you want to uninstall '{}' from Titan?\n\nThis will delete the entire directory: {}").format(item_name, item_path),
            _("Confirm Uninstall"),
            wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
        )

        result = confirm_dialog.ShowModal()
        confirm_dialog.Destroy()

        if result == wx.ID_YES:
            print(f"INFO: User confirmed uninstall of '{item_name}'. Deleting directory: {item_path}")

            # Run uninstall in background thread to avoid GUI blocking
            def uninstall_thread():
                try:
                    shutil.rmtree(item_path)
                    print(f"INFO: Directory '{item_path}' deleted successfully.")

                    # Refresh list on main thread
                    def refresh_ui():
                        if item_type == "app":
                            self.populate_app_list()
                            print(f"INFO: Application list refreshed.")
                        elif item_type == "game":
                            self.populate_game_list()
                            print(f"INFO: Game list refreshed.")

                        play_select_sound()
                        vibrate_selection()  # Add vibration for successful uninstall
                        wx.MessageBox(_("'{}' has been successfully uninstalled.").format(item_name), _("Success"), wx.OK | wx.ICON_INFORMATION)

                    wx.CallAfter(refresh_ui)

                except OSError as e:
                    print(f"ERROR: Error deleting directory '{item_path}': {e}")

                    def show_error():
                        play_endoflist_sound()
                        vibrate_error()  # Add vibration for uninstall error
                        wx.MessageBox(_("Error uninstalling '{}':\n{}\n\nMake sure the directory is not in use.").format(item_name, e), _("Error"), wx.OK | wx.ICON_ERROR)

                    wx.CallAfter(show_error)

            threading.Thread(target=uninstall_thread, daemon=True).start()

        else:
            print(f"INFO: Uninstall of '{item_name}' canceled by user.")
            play_focus_sound()
            vibrate_focus_change()  # Add vibration for cancel action


    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        current_focus = self.FindFocus()

        # Handle F1 (Help)
        if keycode == wx.WXK_F1 and modifiers == wx.MOD_NONE:
            show_help()
            return

        # Handle Alt+F1 (Start Menu) - Linux style only
        if keycode == wx.WXK_F1 and modifiers == wx.MOD_ALT:
            if self.start_menu and platform.system() == "Windows":
                self.start_menu.toggle_menu()
                return

        # Note: Ctrl+Shift+A (AI Voice Recognition) is now a global hotkey registered in __init__

        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self.on_toggle_list()
            return

        # Handle ESC key - return from users/contacts/group_chats list to network list
        if keycode == wx.WXK_ESCAPE:
            if self.current_list in ["users", "contacts", "group_chats"]:
                play_sound('ui/popupclose.ogg')
                vibrate_menu_close()  # Add vibration for menu/view closing
                self.show_network_list()
                if self.network_listbox.GetCount() > 0:
                    self.network_listbox.SetFocus()
                return
            else:
                event.Skip()
            return
        
        # Handle ENTER key for contacts and group chats
        if keycode == wx.WXK_RETURN:
            if self.current_list in ["contacts", "group_chats"] and current_focus == self.users_listbox:
                selection = self.users_listbox.GetSelection()
                if selection != wx.NOT_FOUND:
                    # Trigger context menu on Enter for contact types
                    self.on_users_context_menu(event)
                    return

        if keycode == wx.WXK_RETURN:
            if current_focus == self.app_listbox and self.app_listbox.IsShown():
                 self.on_app_selected(event)
            elif current_focus == self.game_tree and self.game_tree.IsShown():
                 selection = self.game_tree.GetSelection()
                 if selection.IsOk():
                     activate_event = wx.TreeEvent(wx.wxEVT_TREE_ITEM_ACTIVATED, self.game_tree, selection)
                     self.on_game_tree_activated(activate_event)
            elif current_focus == self.network_listbox and self.network_listbox.IsShown():
                 self.on_network_option_selected(event)
            elif current_focus == self.users_listbox and self.users_listbox.IsShown():
                 self.on_user_selected(event)
            elif current_focus == self.message_input and self.message_input.IsShown():
                 pass  # Message sending moved to separate windows
            elif current_focus == self.statusbar_listbox:
                self.on_status_selected(event)
            else:
                event.Skip()
            return

        if keycode == wx.WXK_TAB:
             if modifiers == wx.MOD_NONE:
                  if current_focus == self.app_listbox and self.app_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()  # Add vibration for focus change to statusbar
                  elif current_focus == self.game_tree and self.game_tree.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()  # Add vibration for focus change to statusbar
                  elif current_focus == self.network_listbox and self.network_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()  # Add vibration for focus change to statusbar
                  elif current_focus == self.users_listbox and self.users_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()  # Add vibration for focus change to statusbar
                  elif current_focus == self.message_input and self.message_input.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()  # Add vibration for focus change to statusbar
                  elif current_focus == self.statusbar_listbox:
                      if self.current_list == "apps":
                           self.app_listbox.SetFocus()
                           play_applist_sound()
                           vibrate_focus_change()  # Add vibration for focus change to app list
                      elif self.current_list == "games":
                           self.game_tree.SetFocus()
                           play_applist_sound()
                           vibrate_focus_change()  # Add vibration for focus change to game list
                      elif self.current_list == "network":
                           self.network_listbox.SetFocus()
                           play_applist_sound()
                           vibrate_focus_change()  # Add vibration for focus change to network list
                      elif self.current_list == "users":
                           self.users_listbox.SetFocus()
                           play_applist_sound()
                           vibrate_focus_change()  # Add vibration for focus change to users list
                      elif self.current_list == "messages":
                           self.message_input.SetFocus()
                           play_applist_sound()
                           vibrate_focus_change()  # Add vibration for focus change to message input
                  else:
                      event.Skip()
                  return
             elif modifiers == wx.MOD_SHIFT:
                  if current_focus == self.statusbar_listbox:
                      if self.current_list == "apps":
                           self.app_listbox.SetFocus()
                           play_applist_sound()
                      elif self.current_list == "games":
                           self.game_tree.SetFocus()
                           play_applist_sound()
                      elif self.current_list == "network":
                           self.network_listbox.SetFocus()
                           play_applist_sound()
                      elif self.current_list == "users":
                           self.users_listbox.SetFocus()
                           play_applist_sound()
                      elif self.current_list == "messages":
                           self.message_input.SetFocus()
                           play_applist_sound()
                  event.Skip()
                  return


        if keycode in [wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_HOME, wx.WXK_END]:
             self.handle_navigation(event, keycode, current_focus)
             return
        
        # Handle context menu key (Applications/Menu key)
        if keycode == wx.WXK_MENU or (keycode == wx.WXK_F10 and modifiers == wx.MOD_SHIFT):
            if current_focus == self.users_listbox and self.users_listbox.IsShown():
                self.on_users_context_menu(event)
                return

        event.Skip()

    def handle_navigation(self, event, keycode, current_focus):
        # Handle tree navigation separately (TreeCtrl has built-in navigation)
        if current_focus == self.game_tree and self.game_tree.IsShown():
            # Let TreeCtrl handle its own navigation, just add audio feedback
            play_focus_sound()
            vibrate_cursor_move()
            event.Skip()
            return

        target_listbox = None
        if current_focus == self.app_listbox and self.app_listbox.IsShown():
            target_listbox = self.app_listbox
        elif current_focus == self.network_listbox and self.network_listbox.IsShown():
            target_listbox = self.network_listbox
        elif current_focus == self.users_listbox and self.users_listbox.IsShown():
            target_listbox = self.users_listbox
        elif current_focus == self.statusbar_listbox:
            target_listbox = self.statusbar_listbox
        else:
            event.Skip()
            return

        if target_listbox:
            current_selection = target_listbox.GetSelection()
            item_count = target_listbox.GetCount()
            
            new_selection = current_selection

            if keycode == wx.WXK_UP or keycode == wx.WXK_LEFT:
                new_selection -= 1
            elif keycode == wx.WXK_DOWN or keycode == wx.WXK_RIGHT:
                new_selection += 1
            elif keycode == wx.WXK_HOME:
                new_selection = 0
            elif keycode == wx.WXK_END:
                new_selection = item_count - 1

            if new_selection >= 0 and new_selection < item_count:
                target_listbox.SetSelection(new_selection)
                vibrate_cursor_move()  # Add vibration for cursor movement
                pan = 0
                if item_count > 1:
                    pan = new_selection / (item_count - 1)
                play_focus_sound(pan=pan)
            else:
                play_endoflist_sound()


    def on_focus_change_status(self, event):
        import time
        # Debouncing - odtwórz dźwięk tylko jeśli minęło wystarczająco czasu
        current_time = time.time()
        if current_time - self.last_statusbar_sound_time >= self.statusbar_sound_delay:
            play_statusbar_sound()
            self.last_statusbar_sound_time = current_time
        event.Skip()


    def on_status_selected(self, event):
        selection = self.statusbar_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            play_select_sound()
            status_item = self.statusbar_listbox.GetString(selection)
            status_thread = threading.Thread(target=self.handle_status_action, args=(status_item,), daemon=True)
            status_thread.start()

    def handle_status_action(self, item):
        # CRITICAL FIX: WiFi operations must run on main GUI thread!
        # Running GUI operations from background threads can cause hanging
        print(f"handle_status_action called with item: '{item}'")
        
        if _("Network status:") in item or "połączono" in item.lower() or "connected" in item.lower() or "nie połączono" in item.lower() or "disconnected" in item.lower():
            # WiFi network operations - MUST run on main thread
            print(f"Network item detected: '{item}' - scheduling WiFi operation on main GUI thread...")
            wx.CallAfter(self.open_network_settings_safe)
            return
        
        # Other operations can run in background thread
        if _("Clock:") in item:
            self.open_time_settings()
        elif _("Battery level:") in item:
            self.open_power_settings()
        elif _("Volume:") in item:
            self.open_volume_mixer()
        else:
            print(f"WARNING: Unknown statusbar item selected: {item}")


    def show_app_list(self):
        self.app_listbox.Show()
        self.game_tree.Hide()
        self.network_listbox.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        self.list_label.SetLabel(_("Application List:"))
        self.current_list = "apps"
        speaker.speak(_("Application list, 1 of 3"))
        vibrate_menu_open()  # Add vibration for switching to application list
        self.Layout()
        if self.app_listbox.GetCount() > 0:
             self.app_listbox.SetFocus()


    def show_game_list(self):
        self.app_listbox.Hide()
        self.game_tree.Show()
        self.network_listbox.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        self.list_label.SetLabel(_("Game List:"))
        self.current_list = "games"
        speaker.speak(_("Game list, 2 of 3"))
        vibrate_menu_open()  # Add vibration for switching to game list
        self.Layout()

        # Focus on first element
        root = self.game_tree.GetRootItem()
        if root.IsOk():
            child, cookie = self.game_tree.GetFirstChild(root)
            if child.IsOk():
                self.game_tree.SelectItem(child)
                self.game_tree.SetFocus()

    def show_network_list(self):
        self.app_listbox.Hide()
        self.game_tree.Hide()
        self.network_listbox.Show()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        self.list_label.SetLabel(_("Titan IM:"))
        self.current_list = "network"
        speaker.speak(_("Titan IM, 3 of 3"))
        vibrate_menu_open()  # Add vibration for switching to network list

        # Always populate the network list based on login status
        self.populate_network_list()

        self.Layout()
        if self.network_listbox.GetCount() > 0:
            self.network_listbox.SetFocus()

    def populate_network_options(self):
        self.network_listbox.Clear()
        self.network_listbox.Append(_("Telegram"))
        self.network_listbox.Append(_("Facebook Messenger"))
        self.network_listbox.Append(_("WhatsApp"))
        # Future messaging platforms:
        # self.network_listbox.Append(_("Mastodon"))
        # self.network_listbox.Append(_("Matrix"))

    def on_network_option_selected(self, event):
        selection = self.network_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
            
        selected_text = self.network_listbox.GetString(selection)
        
        # Handle different contexts
        if self.current_list == "network":
            # Main network menu
            play_select_sound()  # Play select sound for network options
            vibrate_selection()  # Add vibration for network option selection
            if "Telegram" in selected_text:
                if "telegram" in self.active_services:
                    # Already logged in - show Telegram options
                    self.current_service = "telegram"
                    self.show_telegram_options()
                else:
                    # Not logged in - show login
                    self.show_telegram_login()
            elif "Facebook Messenger" in selected_text:
                # Always just show WebView (no integration with main UI)
                self.show_messenger_login()
            elif "WhatsApp" in selected_text:
                # Show WhatsApp WebView (like Messenger)
                self.show_whatsapp_login()
            # DISABLED - Titan-Net
            # elif "Titan-Net" in selected_text:
            #     if "titannet" in self.active_services:
            #         # Already logged in - show Titan-Net options
            #         self.current_service = "titannet"
            #         self.show_titannet_options()
            #     else:
            #         # Not logged in - show login dialog
            #         if hasattr(self, 'titan_client') and self.titan_client:
            #             try:
            #                 from titan_net_gui import show_login_dialog
            #                 logged_in, offline_mode = show_login_dialog(self, self.titan_client)

            #                 if logged_in:
            #                     # Store in active services
            #                     self.active_services["titannet"] = {
            #                         "client": self.titan_client,
            #                         "type": "titannet",
            #                         "name": "Titan-Net",
            #                         "online_users": [],
            #                         "unread_messages": {},
            #                         "user_data": {
            #                             "username": self.titan_client.username,
            #                             "titan_number": self.titan_client.titan_number
            #                         }
            #                     }

            #                     # Update UI
            #                     self.populate_network_list()
            #                     self.show_network_list()
            #                 elif offline_mode:
            #                     # User chose offline mode
            #                     # Application continues without Titan-Net connection
            #                     pass
            #             except Exception as e:
            #                 print(f"Error loading Titan-Net login dialog: {e}")
            #                 wx.MessageBox(_("Titan-Net is not available"), _("Error"), wx.OK | wx.ICON_ERROR)
            elif selected_text == _("Other communicators"):
                wx.MessageBox(_("Other communicators will be available soon."), _("Information"), wx.OK | wx.ICON_INFORMATION)
        
        elif self.current_list == "telegram_options":
            # Handle Telegram options
            play_select_sound()  # Play select sound for Telegram options
            vibrate_selection()  # Add vibration for Telegram option selection
            if selected_text == _("Contacts"):
                self.show_contacts_view()
            elif selected_text == _("Group Chats"):
                self.show_group_chats_view()
            elif selected_text == _("Settings"):
                self.show_network_settings()
            elif selected_text == _("Information"):
                self.show_network_info()
            elif selected_text == _("Logout"):
                self.logout_from_service("telegram")
            elif selected_text == _("Back to main menu"):
                self.show_network_list()

        # DISABLED - Titan-Net options
        # elif self.current_list == "titannet_options":
        #     # Handle Titan-Net options
        #     play_select_sound()  # Play select sound for Titan-Net options
        #     vibrate_selection()  # Add vibration for Titan-Net option selection
        #     if selected_text == _("Contacts"):
        #         self.show_contacts_view()
        #     elif selected_text == _("Settings"):
        #         self.show_network_settings()
        #     elif selected_text == _("Information"):
        #         self.show_titannet_info()
        #     elif selected_text == _("Logout"):
        #         self.logout_from_service("titannet")
        #     elif selected_text == _("Back to main menu"):
        #         self.show_network_list()

    def show_telegram_login(self):
        """Show Telegram login interface"""
        self.app_listbox.Hide()
        self.game_tree.Hide()
        self.network_listbox.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Show()

        # Update labels for Telegram
        self.username_label.SetLabel(_("Numer telefonu (z kodem kraju):"))
        self.password_label.SetLabel(_("2FA Password (if enabled):"))

        self.list_label.SetLabel(_("Telegram Login"))
        self.login_button.SetLabel(_("OK"))
        self.login_button.Show()
        self.create_account_button.Hide()  # Hide Create Account for Telegram

        # Unbind old event and bind new for Telegram
        self.login_button.Unbind(wx.EVT_BUTTON)
        self.login_button.Bind(wx.EVT_BUTTON, self.on_login)

        self.current_list = "telegram_login"
        self.Layout()
        self.username_text.SetFocus()
        
    def show_messenger_login(self):
        """Show Facebook Messenger WebView interface"""
        try:
            messenger_window = messenger_webview.show_messenger_webview(self)
            if messenger_window:
                # Add Messenger to active services when successfully connected
                # This will be handled by callback from messenger_window
                self.setup_messenger_callbacks(messenger_window)
        except Exception as e:
            print(f"WebView Messenger error: {e}")
            wx.MessageBox(
                _("Cannot launch Messenger WebView.\n"
                  "Check if WebView2 is installed."),
                _("Messenger WebView Error"),
                wx.OK | wx.ICON_ERROR
            )
    
    def show_whatsapp_login(self):
        """Show WhatsApp WebView interface"""
        try:
            whatsapp_window = whatsapp_webview.show_whatsapp_webview(self)
            if whatsapp_window:
                # Add WhatsApp to active services when successfully connected
                # This will be handled by callback from whatsapp_window
                self.setup_whatsapp_callbacks(whatsapp_window)
        except Exception as e:
            print(f"WebView WhatsApp error: {e}")
            # Only show MessageBox if we have a running wx.App
            if wx.GetApp():
                wx.MessageBox(
                    _("Cannot launch WhatsApp WebView.\n"
                      "Check if WebView2 is installed."),
                    _("WhatsApp WebView Error"),
                    wx.OK | wx.ICON_ERROR
                )
        
    def setup_messenger_callbacks(self, messenger_window):
        """Setup callbacks for Messenger integration"""
        # Create a callback to handle successful Messenger connection (WebView only)
        def on_messenger_status_change(status, data=None):
            if status == 'logged_in' or (hasattr(messenger_window, 'messenger_logged_in') and messenger_window.messenger_logged_in):
                print("✓ Messenger WebView logged in (standalone mode)")
                # Just keep running as standalone WebView, no UI integration
            elif status == 'disconnected':
                print("✓ Messenger WebView disconnected")
        
        # Setup the callback
        messenger_window.add_status_callback(on_messenger_status_change)
    
    def setup_whatsapp_callbacks(self, whatsapp_window):
        """Setup callbacks for WhatsApp integration"""
        # Create a callback to handle successful WhatsApp connection (WebView only)
        def on_whatsapp_status_change(status, data=None):
            if status == 'logged_in' or (hasattr(whatsapp_window, 'whatsapp_logged_in') and whatsapp_window.whatsapp_logged_in):
                print("✓ WhatsApp WebView logged in (standalone mode)")
                # Just keep running as standalone WebView, no UI integration
            elif status == 'disconnected':
                print("✓ WhatsApp WebView disconnected")
        
        # Setup the callback
        whatsapp_window.add_status_callback(on_whatsapp_status_change)
    
    def open_messenger_webview(self):
        """Open Messenger WebView window"""
        try:
            if "messenger" in self.active_services:
                # If already have a messenger service, try to show existing window
                messenger_instance = self.active_services["messenger"]["client"]
                if hasattr(messenger_instance, 'Show'):
                    messenger_instance.Show()
                    messenger_instance.Raise()
                    return
            
            # Open new Messenger WebView
            import messenger_webview
            messenger_window = messenger_webview.show_messenger_webview(self)
            if messenger_window:
                self.setup_messenger_callbacks(messenger_window)
                wx.MessageBox(
                    _("Messenger WebView opened.\nPlease log in to see your contacts in Titan IM."),
                    _("Messenger WebView"),
                    wx.OK | wx.ICON_INFORMATION
                )
        except Exception as e:
            print(f"Error opening Messenger WebView: {e}")
            wx.MessageBox(
                _("Failed to open Messenger WebView.\nCheck if WebView2 is installed."),
                _("Error"),
                wx.OK | wx.ICON_ERROR
            )

    # DISABLED - Titan-Net options
    # def show_titannet_options(self):
    #     """Show Titan-Net service options (Contacts, Settings, Logout)"""
    #     self.app_listbox.Hide()
    #     self.game_tree.Hide()
    #     self.users_listbox.Hide()
    #     self.chat_display.Hide()
    #     self.message_input.Hide()
    #     self.login_panel.Hide()

    #     self.network_listbox.Show()
    #     self.network_listbox.Clear()

    #     # Show Titan-Net specific options
    #     self.network_listbox.Append(_("Contacts"))
    #     self.network_listbox.Append(_("Settings"))
    #     self.network_listbox.Append(_("Information"))
    #     self.network_listbox.Append(_("Logout"))
    #     self.network_listbox.Append(_("Back to main menu"))

    #     self.list_label.SetLabel(_("Titan-Net Options"))
    #     self.current_list = "titannet_options"
    #     self.Layout()

    #     if self.network_listbox.GetCount() > 0:
    #         self.network_listbox.SetFocus()

    # def show_titannet_info(self):
    #     """Show Titan-Net information"""
    #     if hasattr(self, 'titan_client') and self.titan_client and self.titan_client.is_connected:
    #         user_data = {
    #             'username': self.titan_client.username,
    #             'titan_number': self.titan_client.titan_number
    #         }
    #         info_text = f"{_('Logged in as')}: {user_data.get('username', _('Unknown'))}\n"
    #         info_text += f"{_('Titan Number')}: {user_data.get('titan_number', _('Unknown'))}\n"
    #         info_text += f"{_('Connection status')}: {_('Connected')}"
    #     else:
    #         info_text = f"{_('Connection status')}: {_('Disconnected')}"

    #     wx.MessageBox(info_text, _("Titan-Net Information"), wx.OK | wx.ICON_INFORMATION)

    # DISABLED - Titan-Net callback methods
    # def _on_titannet_message(self, message):
    #     """Handle incoming Titan-Net private message"""
    #     try:
    #         sender_username = message.get('sender_username', 'Unknown')
    #         message_text = message.get('message', '')

    #         print(f"Received Titan-Net message from {sender_username}: {message_text}")

    #         # Play notification sound
    #         play_sound('titannet/new_message.ogg')

    #         # Show notification
    #         if hasattr(self, 'show_notification'):
    #             self.show_notification(_("New Titan-Net message from {user}").format(user=sender_username))

    #         # Update unread messages count
    #         if "titannet" in self.active_services:
    #             sender_id = message.get('sender_id')
    #             if sender_id:
    #                 if 'unread_messages' not in self.active_services["titannet"]:
    #                     self.active_services["titannet"]['unread_messages'] = {}

    #                 if sender_id not in self.active_services["titannet"]['unread_messages']:
    #                     self.active_services["titannet"]['unread_messages'][sender_id] = 0

    #                 self.active_services["titannet"]['unread_messages'][sender_id] += 1

    #     except Exception as e:
    #         print(f"Error handling Titan-Net message: {e}")

    # def _on_titannet_user_online(self, username):
    #     """Handle Titan-Net user coming online"""
    #     try:
    #         print(f"Titan-Net user online: {username}")

    #         # Play user online sound
    #         play_sound('system/user_online.ogg')

    #         # Update online users list
    #         if "titannet" in self.active_services:
    #             if 'online_users' not in self.active_services["titannet"]:
    #                 self.active_services["titannet"]['online_users'] = []

    #             if username not in self.active_services["titannet"]['online_users']:
    #                 self.active_services["titannet"]['online_users'].append(username)

    #     except Exception as e:
    #         print(f"Error handling Titan-Net user online: {e}")

    # def _on_titannet_user_offline(self, username):
    #     """Handle Titan-Net user going offline"""
    #     try:
    #         print(f"Titan-Net user offline: {username}")

    #         # Play user offline sound
    #         play_sound('system/user_offline.ogg')

    #         # Update online users list
    #         if "titannet" in self.active_services:
    #             if 'online_users' in self.active_services["titannet"]:
    #                 if username in self.active_services["titannet"]['online_users']:
    #                     self.active_services["titannet"]['online_users'].remove(username)

    #     except Exception as e:
    #         print(f"Error handling Titan-Net user offline: {e}")

    def show_telegram_options(self):
        """Show Telegram service options (Contacts, Groups, Settings, Logout)"""
        self.app_listbox.Hide()
        self.game_tree.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.network_listbox.Show()
        self.network_listbox.Clear()
        
        # Show Telegram specific options
        self.network_listbox.Append(_("Contacts"))
        self.network_listbox.Append(_("Group Chats"))
        self.network_listbox.Append(_("Settings"))
        self.network_listbox.Append(_("Information"))
        self.network_listbox.Append(_("Logout"))
        self.network_listbox.Append(_("Back to main menu"))
        
        self.list_label.SetLabel(_("Telegram Options"))
        self.current_list = "telegram_options"
        self.Layout()
        
        if self.network_listbox.GetCount() > 0:
            self.network_listbox.SetFocus()
    
    def logout_from_service(self, service_name):
        """Logout from specific service"""
        if service_name not in self.active_services:
            return
            
        service = self.active_services[service_name]
        
        try:
            if service_name == "telegram":
                # Disconnect from Telegram
                if service["client"]:
                    import telegram_client
                    telegram_client.disconnect_from_server()
                
                # Clear legacy compatibility variables if this was the primary client
                if self.telegram_client == service["client"]:
                    self.telegram_client = None
                    
            elif service_name == "messenger":
                # Close Messenger WebView
                if service["client"]:
                    try:
                        service["client"].Close()
                    except:
                        pass

            elif service_name == "titannet":
                # Logout from Titan-Net
                if service["client"]:
                    try:
                        service["client"].logout()
                    except Exception as e:
                        print(f"Error during Titan-Net logout: {e}")

            # Remove from active services
            del self.active_services[service_name]
            
            # Update legacy logged_in status
            self.logged_in = len(self.active_services) > 0
            
            # Hide logout button if no services are active
            if not self.active_services and hasattr(self, 'logout_button'):
                self.logout_button.Hide()
            
            # Return to main network menu
            self.show_network_list()
                
            wx.MessageBox(
                _("Successfully logged out from {}.").format(service["name"]), 
                _("Logout"), 
                wx.OK | wx.ICON_INFORMATION
            )
            
        except Exception as e:
            print(f"Error logging out from {service_name}: {e}")
            wx.MessageBox(
                _("Error logging out from {}: {}").format(service["name"], str(e)),
                _("Logout Error"),
                wx.OK | wx.ICON_ERROR
            )
    
    def show_login_panel(self, mode):
        """Legacy method - redirects to show_telegram_login"""
        self.show_telegram_login()


    def on_login(self, event):
        username = self.username_text.GetValue()
        password = self.password_text.GetValue()
        if not username:
            wx.MessageBox(_("Enter phone number with country code (e.g. +48123456789)."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        play_sound('system/connecting.ogg')
        # For Telegram, use phone number and optional 2FA password
        phone_number = username  # Phone number with country code
        twofa_password = password if password else None  # Optional 2FA password
        
        result = telegram_client.login(phone_number, twofa_password)
        if result.get("status") == "success":
            # Use TTS to announce connection attempt
            import accessible_output3.outputs.auto
            speaker = accessible_output3.outputs.auto.Auto()
            speaker.speak(_("Connecting to Telegram..."))
            
            # Start Telegram connection
            telegram_client_instance = telegram_client.connect_to_server(phone_number, twofa_password, _("TCE User"))
            
            if telegram_client_instance:
                # Store in active services
                self.active_services["telegram"] = {
                    "client": telegram_client_instance,
                    "type": "telegram",
                    "name": "Telegram",
                    "online_users": [],
                    "unread_messages": {}
                }
                
                # Setup callbacks for real-time events
                telegram_client_instance.add_message_callback(self.on_message_received)
                telegram_client_instance.add_status_callback(self.on_user_status_change)
                telegram_client_instance.add_typing_callback(self.on_typing_indicator)
                telegram_client.add_call_callback(self.on_call_event)
                
                # Legacy compatibility
                self.telegram_client = telegram_client_instance
                self.logged_in = True
            else:
                wx.MessageBox(_("Failed to connect to Telegram server."), _("Connection Error"), wx.OK | wx.ICON_ERROR)
                return
            
            # Update UI
            self.populate_network_list()
            self.show_network_list()
            if hasattr(self, 'logout_button'):
                self.logout_button.Show()
            
            # Wait a bit for connection and then refresh users
            wx.CallLater(1000, self.refresh_online_users)
        else:
            wx.MessageBox(result.get("message"), _("Error"), wx.OK | wx.ICON_ERROR)

    # on_register function removed - communicators are now in the list

    def on_logout(self, event):
        """Safe logout from Telegram"""
        try:
            print("Logging out from Telegram...")
            
            # Disable logout button immediately to prevent multiple clicks
            if hasattr(self, 'logout_button'):
                self.logout_button.Enable(False)
                wx.CallAfter(lambda: self.logout_button.SetLabel(_("Disconnecting...")))
            
            # Set logged out state immediately
            self.logged_in = False
            
            # Disconnect from Telegram safely in background thread
            def disconnect_safely():
                try:
                    if self.telegram_client:
                        telegram_client.disconnect_from_server()
                    
                    # Update UI on main thread after disconnect
                    wx.CallAfter(self.finish_logout)
                    
                except Exception as e:
                    print(f"Error during logout: {e}")
                    # Still update UI even if disconnect failed
                    wx.CallAfter(self.finish_logout)
            
            # Run disconnect in separate thread to avoid blocking UI
            import threading
            disconnect_thread = threading.Thread(target=disconnect_safely, daemon=True)
            disconnect_thread.start()
            
        except Exception as e:
            print(f"Error in logout process: {e}")
            # Fallback to immediate logout
            self.finish_logout()
    
    def finish_logout(self):
        """Finish logout process on main thread"""
        try:
            # Clear telegram client reference
            self.telegram_client = None
            
            # Reset UI state
            self.logged_in = False
            if hasattr(self, 'logout_button'):
                self.logout_button.Hide()
            
            # Clear user data
            self.online_users = []
            self.current_chat_user = None
            self.unread_messages = {}
            
            # Refresh network list to show communicator options again
            self.show_network_list()
            
            print("Logout completed successfully")
            
        except Exception as e:
            print(f"Error finishing logout: {e}")
            # Still try to show network list
            try:
                self.show_network_list()
            except:
                pass

    def populate_network_list(self):
        self.network_listbox.Clear()

        if not self.active_services:
            # Show communicator options when not logged in to any service
            self.network_listbox.Append(_("Telegram"))
            # self.network_listbox.Append(_("TeamTalk"))
            self.network_listbox.Append(_("Facebook Messenger"))
            self.network_listbox.Append(_("WhatsApp"))
            # self.network_listbox.Append(_("Titan-Net"))  # DISABLED
            self.network_listbox.Append(_("Other communicators"))
        else:
            # Show logged in services with connection status
            if "telegram" in self.active_services:
                # Try to get username from service data or telegram_client
                username = "user"  # Default
                try:
                    if self.telegram_client:
                        import telegram_client
                        user_data = telegram_client.get_user_data()
                        if user_data and 'username' in user_data:
                            username = user_data['username']
                except:
                    pass
                self.network_listbox.Append(_("Telegram - connected as {}").format(username))
            else:
                self.network_listbox.Append(_("Telegram"))

            if "messenger" in self.active_services:
                # Try to get username from messenger service
                username = "user"  # Default
                try:
                    messenger_service = self.active_services["messenger"]
                    if "user_data" in messenger_service and messenger_service["user_data"]:
                        username = messenger_service["user_data"].get("username", "user")
                except:
                    pass
                self.network_listbox.Append(_("Facebook Messenger - connected as {}").format(username))
            else:
                self.network_listbox.Append(_("Facebook Messenger"))
            
            if "whatsapp" in self.active_services:
                username = "user"  # Default
                try:
                    whatsapp_service = self.active_services["whatsapp"]
                    if "user_data" in whatsapp_service and whatsapp_service["user_data"]:
                        username = whatsapp_service["user_data"].get("username", "user")
                except:
                    pass
                self.network_listbox.Append(_("WhatsApp - connected as {}").format(username))
            else:
                self.network_listbox.Append(_("WhatsApp"))

            # DISABLED - Titan-Net
            # if "titannet" in self.active_services:
            #     username = "user"  # Default
            #     try:
            #         titannet_service = self.active_services["titannet"]
            #         if "user_data" in titannet_service and titannet_service["user_data"]:
            #             username = titannet_service["user_data"].get("username", "user")
            #     except:
            #         pass
            #     self.network_listbox.Append(_("Titan-Net - connected as {}").format(username))
            # else:
            #     self.network_listbox.Append(_("Titan-Net"))

            self.network_listbox.Append(_("Other communicators"))

    def on_toggle_list(self):
        play_sound('ui/switch_list.ogg')
        vibrate_menu_open()  # Add vibration for section/list switching

        # Ctrl+Tab przełącza tylko między 3 głównymi widokami
        if self.current_list == "apps":
            self.show_game_list()
        elif self.current_list == "games":
            self.show_network_list()
            if self.network_listbox.GetCount() > 0:
                self.network_listbox.SetFocus()
        elif self.current_list == "network" or self.current_list in ["users", "messages"]:
            # Z widoków sieciowych wracamy do aplikacji
            self.show_app_list()
        else:
            # Domyślnie wróć do aplikacji
            self.show_app_list()

    def on_show_apps(self, event):
        if self.current_list != "apps":
             self.show_app_list()
        event.Skip()

    def on_show_games(self, event):
        if self.current_list != "games":
             self.show_game_list()
        event.Skip()

    def on_show_network(self, event):
        self.show_network_list()


    def on_minimize(self, event):
        if self.IsIconized():
            self.minimize_to_tray()
        event.Skip()

    def open_time_settings(self):
        if platform.system() == "Windows":
            subprocess.run(["control", "timedate.cpl"])
        elif platform.system() == "Linux":
            try:
                # Try common Linux time/date settings applications
                settings_apps = [
                    ["gnome-control-center", "datetime"],  # GNOME
                    ["systemsettings5", "kcm_clock"],      # KDE Plasma 5
                    ["systemsettings", "clock"],           # KDE 4
                    ["unity-control-center", "datetime"],  # Unity
                    ["xfce4-settings-manager"],             # XFCE
                    ["lxqt-config-datetime"],               # LXQt
                    ["timedatectl", "status"]                # systemd (shows current settings)
                ]
                
                for app_cmd in settings_apps:
                    try:
                        subprocess.run(app_cmd, check=True, stderr=subprocess.DEVNULL)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                else:
                    # If all GUI options fail, show timedatectl info
                    try:
                        result = subprocess.run(["timedatectl", "status"], 
                                               capture_output=True, text=True, check=True)
                        wx.MessageBox(_("Current time settings:\n\n{}").format(result.stdout), 
                                     _("Time Settings"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        wx.MessageBox(_("Could not open time settings. Please use your system's settings application."), 
                                     _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(_("Could not open date/time settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/System/Library/PreferencePanes/DateAndTime.prefPane"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open date/time settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)

    def open_power_settings(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(["control", "powercfg.cpl"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open power settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Linux":
            try:
                # Try common Linux power management applications
                power_apps = [
                    ["gnome-control-center", "power"],      # GNOME
                    ["systemsettings5", "kcm_powerdevilprofilesconfig"],  # KDE Plasma 5
                    ["systemsettings", "powerdevil"],       # KDE 4
                    ["unity-control-center", "power"],      # Unity
                    ["xfce4-power-manager-settings"],       # XFCE
                    ["lxqt-config-powermanagement"],        # LXQt
                    ["mate-power-preferences"]               # MATE
                ]
                
                for app_cmd in power_apps:
                    try:
                        subprocess.run(app_cmd, check=True, stderr=subprocess.DEVNULL)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                else:
                    # If all GUI options fail, show power info using system commands
                    try:
                        # Show battery info if available
                        import glob
                        battery_paths = glob.glob("/sys/class/power_supply/BAT*")
                        if battery_paths:
                            info_text = "Battery Information:\n\n"
                            for bat_path in battery_paths:
                                bat_name = os.path.basename(bat_path)
                                try:
                                    with open(os.path.join(bat_path, "capacity"), 'r') as f:
                                        capacity = f.read().strip()
                                    with open(os.path.join(bat_path, "status"), 'r') as f:
                                        status = f.read().strip()
                                    info_text += f"{bat_name}: {capacity}% ({status})\n"
                                except Exception:
                                    info_text += f"{bat_name}: Information unavailable\n"
                            wx.MessageBox(_(info_text), _("Power Information"), wx.OK | wx.ICON_INFORMATION)
                        else:
                            wx.MessageBox(_("No battery detected. Power settings may not be available."), 
                                         _("Power Information"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        wx.MessageBox(_("Could not open power settings. Please use your system's settings application."), 
                                     _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(_("Could not open power settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/System/Library/PreferencePanes/EnergySaver.prefPane"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open power settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)

    def open_volume_mixer(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(["sndvol.exe"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open volume mixer:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Linux":
            try:
                # Try common Linux audio control applications
                audio_apps = [
                    ["pavucontrol"],                         # PulseAudio Volume Control
                    ["gnome-control-center", "sound"],      # GNOME
                    ["systemsettings5", "kcm_pulseaudio"],  # KDE Plasma 5
                    ["systemsettings", "phonon"],           # KDE 4
                    ["unity-control-center", "sound"],      # Unity
                    ["xfce4-mixer"],                         # XFCE
                    ["lxqt-config-audio"],                  # LXQt
                    ["mate-volume-control"],                # MATE
                    ["alsamixergui"],                        # ALSA GUI mixer
                    ["kmix"]                                 # KDE mixer
                ]
                
                for app_cmd in audio_apps:
                    try:
                        subprocess.run(app_cmd, check=True, stderr=subprocess.DEVNULL)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                else:
                    # If all GUI options fail, try terminal-based mixer
                    try:
                        # Check if alsamixer is available
                        subprocess.run(["which", "alsamixer"], check=True, 
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        wx.MessageBox(_("GUI volume mixer not found.\n\nYou can use 'alsamixer' in terminal for audio control."), 
                                     _("Volume Control"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        wx.MessageBox(_("Could not find audio mixer. Please install 'pavucontrol' or 'alsamixer'."), 
                                     _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(_("Could not open volume mixer:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/Applications/Utilities/Audio MIDI Setup.app"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open audio settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)


    def open_network_settings(self):
        """Open network settings - now guaranteed to run on main GUI thread"""
        print("open_network_settings called on main GUI thread")
        
        # Check if invisible UI is active - if so, use invisible WiFi interface
        if hasattr(self, 'invisible_ui') and self.invisible_ui.active:
            try:
                # Use invisible UI WiFi manager
                self.invisible_ui.activate_wifi_interface()
                return
            except Exception as e:
                print(f"Could not load invisible WiFi manager: {e}")
        
        # Show WiFi GUI - now much simpler since we're on main thread
        try:
            print("Opening WiFi GUI on main thread (should not hang)...")
            import tce_system_net
            
            # Direct call should work now that we're on main thread
            wifi_frame = tce_system_net.show_wifi_gui(self)
            
            if wifi_frame:
                print("WiFi GUI opened successfully on main thread!")
            else:
                print("WiFi GUI returned None")
                wx.MessageBox(
                    _("WiFi interface could not be initialized.\nThis may be due to missing drivers or system restrictions."),
                    _("WiFi Warning"),
                    wx.OK | wx.ICON_WARNING
                )
            return
                    
        except Exception as e:
            print(f"Error opening WiFi GUI on main thread: {e}")
            import traceback
            traceback.print_exc()
            
            try:
                wx.MessageBox(
                    _("Error opening WiFi interface: {}\n\nTrying system WiFi settings instead...").format(str(e)),
                    _("WiFi Error"),
                    wx.OK | wx.ICON_WARNING
                )
            except:
                pass
        
        # Fallback to system network settings
        if platform.system() == "Windows":
            try:
                subprocess.run(["explorer", "ms-settings:network-status"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open network settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Linux":
            try:
                # Try common Linux network management applications
                network_apps = [
                    ["nm-connection-editor"],               # NetworkManager GUI
                    ["gnome-control-center", "network"],    # GNOME
                    ["systemsettings5", "kcm_networkmanagement"],  # KDE Plasma 5
                    ["systemsettings", "network"],          # KDE 4
                    ["unity-control-center", "network"],    # Unity
                    ["network-manager-gnome"],              # GNOME NetworkManager
                    ["wicd-gtk"],                            # Wicd GUI
                    ["connman-gtk"],                         # ConnMan GUI
                    ["lxqt-config-network"],                # LXQt
                    ["mate-network-properties"]             # MATE
                ]
                
                for app_cmd in network_apps:
                    try:
                        subprocess.run(app_cmd, check=True, stderr=subprocess.DEVNULL)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                else:
                    # If all GUI options fail, show network info using nmcli
                    try:
                        result = subprocess.run(["nmcli", "device", "status"], 
                                               capture_output=True, text=True, check=True)
                        info_text = "Network Devices:\n\n" + result.stdout
                        
                        # Also show active connections
                        result2 = subprocess.run(["nmcli", "connection", "show", "--active"], 
                                                capture_output=True, text=True, check=True)
                        if result2.stdout.strip():
                            info_text += "\n\nActive Connections:\n" + result2.stdout
                        
                        wx.MessageBox(_(info_text), _("Network Information"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        # Final fallback - show basic IP info
                        try:
                            result = subprocess.run(["ip", "addr", "show"], 
                                                   capture_output=True, text=True, check=True)
                            wx.MessageBox(_("Network interface information:\n\n{}").format(result.stdout[:1000]), 
                                         _("Network Information"), wx.OK | wx.ICON_INFORMATION)
                        except Exception:
                            wx.MessageBox(_("Could not open network settings. Please use your system's network manager."), 
                                         _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(_("Could not open network settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/System/Library/PreferencePanes/Network.prefPane"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open network settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)

    def minimize_to_tray(self):
        self.Hide()
        skin_name = self.settings.get('interface', {}).get('skin', DEFAULT_SKIN_NAME)
        skin_data = self.load_skin_data(skin_name)
        self.task_bar_icon = TaskBarIcon(self, self.version, skin_data)
        play_sound('ui/minimalize.ogg')
        vibrate_menu_close()  # Add vibration for minimizing to tray
        self.invisible_ui.start_listening()

        # Show tip about invisible UI after 5-6 seconds
        show_invisible_ui_tip(delay=5.5)

    def restore_from_tray(self):
        # Auto-disable Titan UI when main window is restored
        if hasattr(self.invisible_ui, 'titan_ui_mode') and self.invisible_ui.titan_ui_mode:
            self.invisible_ui.temporarily_disable_titan_ui("main_window")
            # Bind window close event to re-enable if minimized again
            self.Bind(wx.EVT_ICONIZE, self._on_window_minimize)
        
        # Initialize UI if it wasn't initialized (when started minimized)
        if self.start_minimized and not hasattr(self, 'toolbar'):
            self.InitUI()
            self.populate_app_list()
            self.populate_game_list()
            self.apply_selected_skin()
            self.show_app_list()
            self.start_minimized = False  # Mark as no longer in minimized startup state
        
        self.Show()
        self.Raise()
        self.task_bar_icon.Destroy()
        self.task_bar_icon = None
        play_sound('ui/normalize.ogg')
        vibrate_menu_open()  # Add vibration for normalizing from tray
        self.invisible_ui.stop_listening()
    
    def _on_window_minimize(self, event):
        """Handle window minimization - re-enable Titan UI if it was disabled and minimize to tray"""
        if event.IsIconized():
            # Window is being minimized, re-enable Titan UI if it was disabled
            if (hasattr(self.invisible_ui, 'titan_ui_temporarily_disabled') and 
                self.invisible_ui.titan_ui_temporarily_disabled and 
                self.invisible_ui.disabled_by_dialog == "main_window"):
                self.invisible_ui._on_dialog_close("main_window", None)
            
            # Minimize to tray and start invisible UI
            self.minimize_to_tray()
        event.Skip()

    def shutdown_app(self):
        """Handles the complete shutdown of the application by terminating the process after a delay."""
        print("=" * 80)
        print("!!! SHUTDOWN_APP CALLED !!!")
        print("=" * 80)

        # Print stack trace to see who called shutdown
        import traceback
        print("SHUTDOWN CALLED FROM:")
        for line in traceback.format_stack()[:-1]:
            print(line.strip())
        print("=" * 80)

        print("INFO: Shutting down application...")

        # Hide window immediately for user feedback
        self.Hide()

        # Safely disconnect from Telegram if connected
        def safe_shutdown():
            try:
                # Stop status update thread immediately
                print("INFO: Stopping status update thread...")
                self.status_thread_running = False
                self.status_thread_stop_event.set()  # Signal thread to stop immediately
                # Don't wait for thread - it's daemon and will stop on its own
                print("INFO: Status update thread signal sent")

                if self.logged_in and self.telegram_client:
                    print("INFO: Disconnecting from Telegram before shutdown...")
                    try:
                        telegram_client.disconnect_from_server()
                        # Give disconnect process time to complete
                        time.sleep(1)
                    except Exception as e:
                        print(f"Warning: Error disconnecting from Telegram: {e}")

                # Stop system hooks before shutdown
                try:
                    from src.titan_core.tce_system import stop_system_hooks
                    stop_system_hooks()
                    print("INFO: System hooks stopped")
                except Exception as e:
                    print(f"Warning: Error stopping system hooks: {e}")

                # Final wait for daemon threads to wrap up
                print("INFO: Waiting for background threads to complete...")
                time.sleep(1)

                print("INFO: Application terminating now.")
                os._exit(0)

            except Exception as e:
                print(f"Error during shutdown: {e}")
                import traceback
                traceback.print_exc()
                # Force exit even if there were errors
                os._exit(1)

        # Run shutdown process in background thread
        shutdown_thread = threading.Thread(target=safe_shutdown, daemon=True)
        shutdown_thread.start()

    def on_close(self, event):
        """Handles the close event when confirmation is required."""
        result = show_shutdown_dialog()
        if result == wx.ID_OK:
            self.shutdown_app()
        else:
            print("INFO: Shutdown canceled by user.")
            event.Veto()

    def on_close_unconfirmed(self, event):
        """Handles the close event when no confirmation is required."""
        self.shutdown_app()
    
    # Titan-Net messaging methods
    # Messages view moved to separate windows
    
    def show_contacts_view(self):
        """Show contacts list"""
        self.app_listbox.Hide()
        self.game_tree.Hide()
        self.network_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.users_listbox.Show()
        self.list_label.SetLabel(_("Contacts"))
        self.current_list = "contacts"

        # Play popup sound when opening contacts view
        play_sound('ui/popup.ogg')

        self.refresh_contacts()
        self.Layout()
        
        if self.users_listbox.GetCount() > 0:
            self.users_listbox.SetFocus()
    
    def show_group_chats_view(self):
        """Show group chats list"""
        self.app_listbox.Hide()
        self.game_tree.Hide()
        self.network_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.users_listbox.Show()
        self.list_label.SetLabel(_("Group Chats"))
        self.current_list = "group_chats"

        # Play popup sound when opening group chats view
        play_sound('ui/popup.ogg')

        self.refresh_group_chats()
        self.Layout()
        
        if self.users_listbox.GetCount() > 0:
            self.users_listbox.SetFocus()
    
    def show_network_settings(self):
        """Show network settings"""
        wx.MessageBox(_("Ustawienia sieciowe - w przygotowaniu"), _("Informacja"), wx.OK | wx.ICON_INFORMATION)
    
    def show_network_info(self):
        """Show network information"""
        if self.telegram_client and telegram_client.is_connected():
            user_data = telegram_client.get_user_data()
            online_count = len(telegram_client.get_online_users())
            info_text = f"{_('Zalogowany jako')}: {user_data.get('username', _('Nieznany'))}\n"
            info_text += f"{_('Users online')}: {online_count}\n"
            info_text += f"{_('Connection status')}: {_('Connected')}"
        else:
            info_text = f"{_('Connection status')}: {_('Disconnected')}"
        
        wx.MessageBox(info_text, _("Telegram Information"), wx.OK | wx.ICON_INFORMATION)
    
    def refresh_contacts(self):
        """Refresh the contacts list (private chats)"""
        contacts = []
        service_name = self.current_service or "telegram"  # Default to telegram for legacy compatibility
        
        if service_name in self.active_services:
            service = self.active_services[service_name]
            
            if service["type"] == "telegram":
                import telegram_client
                if service["client"] and telegram_client.is_connected():
                    contacts = telegram_client.get_contacts()
            elif service["type"] == "messenger":
                # TODO: Implement messenger contacts retrieval
                contacts = []  # Placeholder
        
        # Legacy compatibility
        if self.telegram_client and telegram_client and hasattr(telegram_client, 'is_connected'):
            if telegram_client.is_connected():
                contacts = telegram_client.get_contacts()
        
        self.online_users = contacts  # Keep compatibility
        
        print(f"DEBUG: {_('Refreshing contacts list, found')}: {len(contacts)} {_('contacts')} for {service_name}")
        
        self.users_listbox.Clear()
        for contact in contacts:
            username = contact.get('username', contact)
            unread_count = self.unread_messages.get(username, 0)
            display_name = f"{username} ({unread_count} {_('unread')})" if unread_count > 0 else username
            self.users_listbox.Append(display_name)
            print(f"DEBUG: {_('Added contact')}: {display_name}")
        
        if not contacts:
            print(f"DEBUG: {_('No connection or client to refresh contacts')} for {service_name}")
    
    def refresh_group_chats(self):
        """Refresh the group chats list"""
        groups = []
        service_name = self.current_service or "telegram"  # Default to telegram for legacy compatibility
        
        if service_name in self.active_services:
            service = self.active_services[service_name]
            
            if service["type"] == "telegram":
                import telegram_client
                if service["client"] and telegram_client.is_connected():
                    groups = telegram_client.get_group_chats()
            elif service["type"] == "messenger":
                # TODO: Implement messenger group chats retrieval
                groups = []  # Placeholder
        
        # Legacy compatibility
        if self.telegram_client and telegram_client and hasattr(telegram_client, 'is_connected'):
            if telegram_client.is_connected():
                groups = telegram_client.get_group_chats()
        
        print(f"DEBUG: {_('Refreshing group chats, found')}: {len(groups)} {_('groups')} for {service_name}")
        
        self.users_listbox.Clear()
        for group in groups:
            group_name = group.get('name', group.get('title', 'Unknown Group'))
            unread_count = self.unread_messages.get(group_name, 0)
            display_name = f"{group_name} ({unread_count} {_('unread')})" if unread_count > 0 else group_name
            self.users_listbox.Append(display_name)
            print(f"DEBUG: {_('Added group')}: {display_name}")
        
        if not groups:
            print(f"DEBUG: {_('No connection or client to refresh groups')} for {service_name}")
    
    def refresh_online_users(self):
        """Legacy method - redirects to refresh_contacts"""
        self.refresh_contacts()
    
    def on_user_selected(self, event):
        """Handle user selection from online users list"""
        selection = self.users_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            user_text = self.users_listbox.GetString(selection)
            username = user_text.split(' (')[0]  # Remove unread count if present
            
            self.current_chat_user = username
            
            # Clear unread messages for this user
            if username in self.unread_messages:
                self.unread_messages[username] = 0

            # User selection now just sets current user - use context menu for actions
            play_sound('core/SELECT.ogg')
    
    # Chat history loading moved to separate windows
    
    def on_users_context_menu(self, event):
        """Show context menu for selected user or group"""
        selection = self.users_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        
        user_text = self.users_listbox.GetString(selection)
        username = user_text.split(' (')[0]  # Remove unread count if present

        # Play context menu sound
        play_sound('ui/contextmenu.ogg')

        # Create context menu
        menu = wx.Menu()
        
        # Add menu items based on current list type
        if self.current_list == "contacts":
            private_msg_item = menu.Append(wx.ID_ANY, _("Private message"), _("Send private message"))
            voice_call_item = menu.Append(wx.ID_ANY, _("Voice call"), _("Start voice call"))

            # Bind menu events for contacts
            self.Bind(wx.EVT_MENU, lambda evt: self.on_private_message(username), private_msg_item)
            self.Bind(wx.EVT_MENU, lambda evt: self.on_voice_call(username), voice_call_item)
            
        elif self.current_list == "group_chats":
            group_msg_item = menu.Append(wx.ID_ANY, _("Open group chat"), _("Open group chat window"))
            
            # Bind menu events for groups  
            self.Bind(wx.EVT_MENU, lambda evt: self.on_group_chat(username), group_msg_item)
            
        else:
            # Legacy users list
            private_msg_item = menu.Append(wx.ID_ANY, _("Private message"), _("Send private message"))
            voice_call_item = menu.Append(wx.ID_ANY, _("Voice call"), _("Start voice call"))

            # Bind menu events
            self.Bind(wx.EVT_MENU, lambda evt: self.on_private_message(username), private_msg_item)
            self.Bind(wx.EVT_MENU, lambda evt: self.on_voice_call(username), voice_call_item)
        
        # Show menu at cursor position
        self.PopupMenu(menu)

        # Play context menu close sound
        play_sound('ui/contextmenuclose.ogg')

        menu.Destroy()
    
    def on_private_message(self, username):
        """Start private message with user"""
        # Clear unread messages for this user
        if username in self.unread_messages:
            self.unread_messages[username] = 0
        
        # Open separate private message window
        telegram_windows.open_private_message_window(self, username)

        play_sound('core/SELECT.ogg')
    
    def on_voice_call(self, username):
        """Start voice call with user"""
        if not telegram_client.is_voice_calls_available():
            play_sound('core/error.ogg')
            wx.MessageBox(_("Voice calls are not available.\nCheck if py-tgcalls is installed."),
                         _("Error"), wx.OK | wx.ICON_ERROR)
            return

        play_sound('ui/dialog.ogg')
        message = _("Do you want to start a voice call with {}?").format(username)
        result = wx.MessageBox(message, _("Voice call"), wx.YES_NO | wx.ICON_QUESTION)
        
        if result == wx.YES:
            # Start voice call
            success = telegram_client.start_voice_call(username)
            if success:
                # Open separate voice call window and store reference
                self.call_window = telegram_windows.open_voice_call_window(self, username, 'outgoing')
                self.call_active = True
            else:
                play_sound('core/error.ogg')
                wx.MessageBox(_("Failed to start conversation."), _("Error"), wx.OK | wx.ICON_ERROR)

        play_sound('ui/dialogclose.ogg')
    
    def on_group_chat(self, group_name):
        """Open group chat window"""
        # Clear unread messages for this group
        if group_name in self.unread_messages:
            self.unread_messages[group_name] = 0

        # Open separate group chat window
        telegram_windows.open_group_chat_window(self, group_name)

        play_sound('core/SELECT.ogg')
    
    # Call window functions removed - using telegram_windows.py
    
    def on_call_event(self, event_type, data):
        """Handle voice call events"""
        if event_type == 'call_started':
            print(f"Call started with {data.get('recipient')}")
        elif event_type == 'call_connected':
            if self.call_window:
                self.call_window.set_call_connected()
            print(f"Call connected with {data.get('recipient')}")
        elif event_type == 'call_ended':
            if self.call_window:
                self.call_window.Close()
                self.call_window = None
            self.call_active = False
            duration = data.get('duration', 0)
            print(f"Call ended. Duration: {duration:.0f} seconds")
        elif event_type == 'call_failed':
            if self.call_window:
                self.call_window.Close()
                self.call_window = None
            self.call_active = False
            play_sound('core/error.ogg')
            wx.MessageBox(_("Connection failed: {}").format(data.get('error', 'Unknown error')),
                         _("Connection Error"), wx.OK | wx.ICON_ERROR)
    
    # Message sending moved to separate windows
    
    def on_message_received(self, message_data):
        """Handle received message callback"""
        msg_type = message_data.get('type')
        
        if msg_type == 'new_message':
            sender_username = message_data.get('sender_username')
            message = message_data.get('message')
            timestamp = message_data.get('timestamp', '')
            
            # Format timestamp
            if timestamp:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    time_str = dt.strftime('%H:%M:%S')
                except:
                    import time
                    time_str = time.strftime('%H:%M:%S')
            else:
                import time
                time_str = time.strftime('%H:%M:%S')
            
            # If chatting with this user, display message immediately
            if sender_username == self.current_chat_user and self.current_list == "messages":
                self.chat_display.AppendText(f"[{time_str}] {sender_username}: {message}\n")
                self.chat_display.SetInsertionPointEnd()
            else:
                # Add to unread messages
                if sender_username not in self.unread_messages:
                    self.unread_messages[sender_username] = 0
                self.unread_messages[sender_username] += 1
                
                # Refresh users list to show unread count
                if self.current_list == "users":
                    self.refresh_online_users()
            
            # Sound handled by telegram_client
            
        elif msg_type == 'chat_history':
            with_user = message_data.get('with_user')
            messages = message_data.get('messages', [])
            
            if with_user == self.current_chat_user and self.current_list == "messages":
                self.chat_display.Clear()
                self.chat_display.AppendText(f"--- Historia rozmowy z {with_user} ---\n\n")
                
                for msg in messages:
                    timestamp = msg.get('timestamp', '')
                    if timestamp:
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            time_str = dt.strftime('%H:%M:%S')
                        except:
                            time_str = timestamp[:8] if len(timestamp) > 8 else timestamp
                    else:
                        time_str = ''
                    
                    sender = msg.get('sender_username', '')
                    message = msg.get('message', '')
                    self.chat_display.AppendText(f"[{time_str}] {sender}: {message}\n")
                
                self.chat_display.AppendText("\n--- Koniec historii ---\n\n")
                self.chat_display.SetInsertionPointEnd()
        
        elif msg_type == 'message_sent':
            # Message was successfully sent
            pass
    
    def on_user_status_change(self, status_type, data):
        """Handle user status changes"""
        print(f"DEBUG: {_('Otrzymano zmianę statusu')}: {status_type}, {_('dane')}: {data}")
        
        if status_type == 'users_list':
            self.online_users = data
            print(f"DEBUG: {_('Zaktualizowano listę użytkowników online')}: {len(data)} {_('użytkowników')}")
            if self.current_list == "users":
                self.refresh_online_users()
                
        elif status_type == 'status_change':
            username = data.get('username')
            status = data.get('status')

            if status == 'online':
                self.SetStatusText(_("{} joined Telegram").format(username))
                play_sound('system/user_online.ogg')
            elif status == 'offline':
                self.SetStatusText(_("{} left Telegram").format(username))
                play_sound('system/user_offline.ogg')
            
            # Refresh users list
            if self.current_list == "users":
                self.refresh_online_users()
    
    def on_typing_indicator(self, data):
        """Handle typing indicators"""
        username = data.get('username')
        is_typing = data.get('is_typing', False)
        
        if username == self.current_chat_user and self.current_list == "messages":
            if is_typing:
                self.SetStatusText(_("{} pisze...").format(username))
                # Sound played by telegram_client
            else:
                self.SetStatusText(_("Rozmowa z {}").format(self.current_chat_user))


# VoiceCallWindow class moved to telegram_windows.py
