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
from src.titan_core.statusbar_applet_manager import StatusbarAppletManager
from src.titan_core.sound import initialize_sound, play_focus_sound, play_select_sound, play_statusbar_sound, play_applist_sound, play_endoflist_sound, play_sound
import accessible_output3.outputs.auto
from src.ui.menu import MenuBar
from src.ui.invisibleui import InvisibleUI
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.ui.shutdown_question import show_shutdown_dialog
from src.platform_utils import IS_WINDOWS, IS_LINUX, IS_MACOS
from src.ui.classic_start_menu import create_classic_start_menu
from src.ui.help import show_help
from src.ui.window_switcher import show_window_switcher, register_window, unregister_window
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

class _SilentSpeaker:
    """No-op fallback used when accessible_output3 cannot be initialized."""
    def speak(self, text, **kwargs):
        pass
    def braille(self, text, **kwargs):
        pass

# Lazy, shared speaker: defers the costly accessible_output3 stack-walk out of
# import time (see src/accessibility/lazy_speaker.py). Falls back to a no-op
# speaker internally if accessible_output3 cannot initialize.
from src.accessibility.lazy_speaker import LazySpeaker
speaker = LazySpeaker()


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = _new_message_dialog(parent, message, caption, style)
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


def _new_message_dialog(parent, message, caption, style):
    dlg = wx.MessageDialog(parent, message, caption, style)
    try:
        apply_skin_to_window(dlg)
    except Exception:
        pass
    return dlg


def _is_screen_reader_running():
    """Return True only when a real screen reader (NVDA, JAWS, VoiceOver, Orca...) is active.

    Platform TTS fallbacks (SAPI, NSSpeech, spd) don't count as a screen reader.
    """
    try:
        auto_speaker = speaker
        if isinstance(auto_speaker, _SilentSpeaker):
            return False
        output = auto_speaker.get_first_available_output()
        if output is None:
            return False
        if output.is_system_output():
            return False
        is_active = getattr(output, 'is_active', None)
        if callable(is_active):
            return bool(is_active())
        return True
    except Exception:
        return False


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

            # Titan-Net Client - load configuration from settings
            from src.network.titan_net import TitanNetClient, register_active_titan_net_client
            from src.settings.titan_im_config import load_titan_im_config
            
            try:
                im_config = load_titan_im_config()
                tn = im_config.get('titannet_settings', {})
                server_host = tn.get('server_host', 'titosofttitan.com')
                server_port = int(tn.get('server_port', 8001))
                http_port = int(tn.get('http_port', 8000))
            except Exception:
                server_host = 'titosofttitan.com'
                server_port = 8001
                http_port = 8000

            self.titan_client = TitanNetClient(
                server_host=server_host,
                server_port=server_port,
                http_port=http_port
            )
            self.titan_logged_in = False
            self.titan_username = None
            # Publish this client so IUI / Klango / launcher frontends
            # can find it without reaching through the main GUI.
            register_active_titan_net_client(self.titan_client, logged_in=False)
            
            # Debouncing for mouse motion sounds
            self.last_statusbar_sound_time = 0
            self.statusbar_sound_delay = 0.2  # 200ms delay for statusbar sounds

            # Flag to skip focus sound during expand/collapse/endoflist
            self._skip_focus_sound = False

            # Startup guard: suppress the very first focus/list-item sound that
            # would otherwise fire while the UI is still being constructed.
            # Cleared shortly after InitUI finishes (see end of InitUI).
            self._startup_sound_guard = True

            # Status cache to prevent GUI blocking
            # Check if battery is available (desktops return None)
            _initial_battery = get_battery_status()
            self.has_battery = _initial_battery is not None
            self.status_cache = {
                'time': get_current_time(),
                'battery': _initial_battery if self.has_battery else None,
                'volume': 'Loading...',
                'network': 'Loading...'
            }
            self.status_cache_lock = threading.Lock()
            self.status_update_thread = None
            self.status_thread_running = True
            self.status_thread_stop_event = threading.Event()  # Event for immediate thread shutdown

            # Initialize statusbar applet manager
            try:
                self.statusbar_applet_manager = StatusbarAppletManager()
                # Add applet cache entries
                for applet_name in self.statusbar_applet_manager.get_applet_names():
                    self.status_cache[f'applet_{applet_name}'] = 'Loading...'
            except Exception as e:
                print(f"Warning: Failed to initialize statusbar applet manager: {e}")
                self.statusbar_applet_manager = None

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
            if IS_WINDOWS:
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
                    self._show_first_view()
                    print("[GUI] UI initialization complete")
                    # Register main window in the window switcher
                    register_window("Titan", window=self, callback=self._focus_current_view_control, category='main')
                    # Register global F2 hotkey for window switcher (works from TCE apps)
                    self._register_global_f2_hotkey()
                    # macOS: ensure the window is brought to the foreground so
                    # VoiceOver can detect it immediately after launch
                    if IS_MACOS:
                        wx.CallAfter(self._activate_macos_window)
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
                if IS_WINDOWS and self.start_menu:
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
        self.main_panel = wx.Panel(self)
        panel = self.main_panel  # Local alias for backward compatibility
        main_vbox = wx.BoxSizer(wx.VERTICAL)

        self.toolbar = self.CreateToolBar()

        empty_bitmap = wx.Bitmap(1, 1)

        # Toolbar buttons are built dynamically from registered_views below so
        # component-registered views (e.g. macros) also appear as toolbar items.
        self._view_tools = {}  # view_id -> wx.ToolBarToolBase

        # Virtual tab bar is injected as the FIRST ITEM inside each list
        # (app_listbox, game_tree, network_listbox, component listboxes).
        # See _get_tab_bar_item_text / handle_navigation for the behaviour.
        self.tab_bar = None  # legacy attribute, kept for back-compat
        self._tab_bar_tip_active = False

        # Drag-and-drop state (see _start_tab_bar_drag / _handle_list_item_move).
        # Tab bar "cards" are picked up with Space and moved with Left/Right;
        # list items are reordered with Ctrl+Up/Down or by mouse drag.
        self._tab_bar_drag_active = False
        self._tab_bar_drag_view_id = None
        self._tab_bar_drag_origin = None  # registered_views id order at pick-up (for Escape)
        self._lb_drag = None              # in-progress mouse drag on a list box
        self._tree_drag_item = None       # in-progress mouse drag on the game tree

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


        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        list_sizer = self.list_sizer  # Local alias
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

        # View registry for Ctrl+Tab cycling (built-in views + component views)
        all_views = [
            {'id': 'apps', 'label': _("Application List:"), 'short_name': _("Applications"),
             'control': self.app_listbox, 'show_method': self.show_app_list},
            {'id': 'games', 'label': _("Game List:"), 'short_name': _("Games"),
             'control': self.game_tree, 'show_method': self.show_game_list},
            {'id': 'network', 'label': _("Titan IM:"), 'short_name': _("Titan IM"),
             'control': self.network_listbox, 'show_method': self.show_network_list},
        ]

        # Filter views by visible_categories setting
        visible_cats_str = get_setting('visible_categories', 'apps,games,network')
        visible_cats = [c.strip() for c in visible_cats_str.split(',')] if visible_cats_str else ['apps', 'games', 'network']
        self.registered_views = [v for v in all_views if v['id'] in visible_cats]

        # Hide controls for excluded views
        for v in all_views:
            if v['id'] not in visible_cats:
                v['control'].Hide()

        # Apply the user's saved tab bar card order from .index.TCG (if any)
        # before the toolbar is built so toolbar buttons match the order too.
        self._apply_saved_tab_bar_order()

        # Build toolbar entries for all visible views (no more "Switch To" button;
        # component views get their own toolbar buttons via register_view()).
        for view in self.registered_views:
            self._add_toolbar_tool(view)
        self.toolbar.Realize()

        main_vbox.Add(wx.StaticText(panel, label=_("Status Bar:")), flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.statusbar_listbox = wx.ListBox(panel)
        self.populate_statusbar()

        main_vbox.Add(self.statusbar_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

        # Bind statusbar double-click for applet activation
        self.statusbar_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_statusbar_click)

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

        # Mouse drag-and-drop reordering for the built-in lists
        self._enable_listbox_dnd(self.app_listbox)
        self._enable_listbox_dnd(self.network_listbox)
        self._enable_tree_dnd(self.game_tree)

        # Drag-and-drop reordering on the status bar - every slot (Clock /
        # Battery / Volume / Network / each applet) is movable and the new
        # order is persisted in .index.TCG under "statusbar:items". The
        # listbox stores each row's stable key (time / battery / volume /
        # network / applet:<name>) as client data so update_statusbar can
        # refresh by key after a reorder.
        try:
            from src.titan_core.list_dnd import attach_listbox_dnd as _attach_sb_dnd

            def _sb_key(_idx, _text, data):
                return data if isinstance(data, str) else f"txt:{_text}"

            _attach_sb_dnd(
                self.statusbar_listbox,
                view_id='statusbar:items',
                has_tab_bar=False,
                item_key_func=_sb_key,
                auto_apply_on_focus=True,
            )
        except Exception as exc:
            print(f"[GUI] statusbar DnD setup error: {exc}")


        panel.SetSizer(main_vbox)

        self.SetSize((600, 800))
        self.SetTitle(_("Titan App Suite"))
        self.Centre()

        # macOS: configure VoiceOver accessibility names for all controls
        if IS_MACOS:
            self._setup_macos_voiceover()

        # Release the startup sound guard shortly after initial paint so any
        # subsequent user-driven focus/list-item sounds play normally.
        wx.CallLater(800, self._end_startup_sound_guard)

    def _end_startup_sound_guard(self):
        self._startup_sound_guard = False

    def _activate_macos_window(self):
        """Bring the window to the foreground on macOS so VoiceOver detects it."""
        try:
            self.Show(True)
            self.Raise()
            self.SetFocus()
        except Exception as e:
            print(f"Warning: macOS window activation failed: {e}")

    def _setup_macos_voiceover(self):
        """Set accessible names on controls so VoiceOver announces them correctly."""
        try:
            self.app_listbox.SetName(_("Application List"))
            self.game_tree.SetName(_("Game List"))
            self.network_listbox.SetName(_("Titan IM"))
            self.users_listbox.SetName(_("Online Users"))
            self.statusbar_listbox.SetName(_("Status Bar"))
            self.message_input.SetName(_("Type a message"))
            self.username_text.SetName(_("Phone number with country code"))
            self.password_text.SetName(_("2FA password"))
            self.login_button.SetName(_("Log in"))
            self.create_account_button.SetName(_("Create account"))
            self.logout_button.SetName(_("Log out"))
            print("[GUI] macOS VoiceOver accessibility names configured")
        except Exception as e:
            print(f"Warning: Failed to configure VoiceOver accessibility names: {e}")

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

                # Update statusbar applets
                if hasattr(self, 'statusbar_applet_manager') and self.statusbar_applet_manager:
                    for applet_name in self.statusbar_applet_manager.get_applet_names():
                        try:
                            self.statusbar_applet_manager.update_applet_cache(applet_name)
                        except Exception as applet_error:
                            print(f"Error updating statusbar applet '{applet_name}': {applet_error}")

                # Update cache atomically
                with self.status_cache_lock:
                    self.status_cache['time'] = time_str
                    self.status_cache['battery'] = battery_str
                    self.status_cache['volume'] = volume_str
                    self.status_cache['network'] = network_str

                    # Update applet cache entries
                    if hasattr(self, 'statusbar_applet_manager') and self.statusbar_applet_manager:
                        for applet_name in self.statusbar_applet_manager.get_applet_names():
                            try:
                                text = self.statusbar_applet_manager.get_applet_text(applet_name)
                                self.status_cache[f'applet_{applet_name}'] = text
                            except Exception as e:
                                print(f"Error getting applet text for '{applet_name}': {e}")

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
        # Restore the user's saved drag-and-drop order, then prepend the
        # virtual tab bar row as the first item.
        self._apply_saved_order_to_listbox('apps', self.app_listbox)
        self._inject_tab_bar_into_listbox(self.app_listbox)


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

        # User's saved drag-and-drop order for games (keys are platform-scoped)
        try:
            from src.titan_core import list_order
            saved_games = list_order.get_list_order('games')
        except Exception as e:
            print(f"[GUI] load game order error: {e}")
            saved_games = []

        for platform in platform_order:
            if platform not in games_by_platform or not games_by_platform[platform]:
                continue

            games = games_by_platform[platform]
            if saved_games:
                try:
                    from src.titan_core import list_order
                    games = list_order.apply_order(
                        saved_games, games,
                        lambda g, p=platform: self._game_order_key(p, g))
                except Exception as e:
                    print(f"[GUI] apply game order error: {e}")

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

        # Virtual tab bar row is always the first child of the invisible root
        self._inject_tab_bar_into_tree(self.game_tree)


    def _statusbar_items(self):
        """Return ``[(key, text)]`` for every statusbar slot, in default order.

        Each row is identified by a stable key:
        ``time``, ``battery``, ``volume``, ``network`` for built-ins and
        ``applet:<name>`` for plugin applets. The keys are stored as the
        listbox client data so DnD reordering can persist by key (not by
        position) and ``update_statusbar`` can refresh each slot by
        looking it up rather than indexing.
        """
        with self.status_cache_lock:
            items = [
                ('time', _("Clock: {}").format(self.status_cache['time'])),
            ]
            if self.has_battery:
                items.append(
                    ('battery',
                     _("Battery level: {}").format(self.status_cache['battery'])))
            items.append(
                ('volume', _("Volume: {}").format(self.status_cache['volume'])))
            items.append(('network', self.status_cache['network']))
            if hasattr(self, 'statusbar_applet_manager') and self.statusbar_applet_manager:
                for applet_name in self.statusbar_applet_manager.get_applet_names():
                    text = self.status_cache.get(f'applet_{applet_name}', 'Loading...')
                    items.append((f'applet:{applet_name}', text))
        return items

    def _find_statusbar_row(self, key):
        """Return the listbox row index for a statusbar key, or -1 if missing."""
        try:
            for i in range(self.statusbar_listbox.GetCount()):
                if self.statusbar_listbox.GetClientData(i) == key:
                    return i
        except Exception:
            pass
        return -1

    def populate_statusbar(self):
        """Populate statusbar with cached data including applets to avoid blocking GUI.

        Honors the user's saved drag-and-drop order from ``.index.TCG``
        (key list under ``statusbar:items``) so reorders survive a restart.
        Each row carries its key as client data, used by
        :meth:`update_statusbar` to refresh by key and by
        :meth:`on_statusbar_click` to identify applet slots after a move.
        """
        items = self._statusbar_items()
        try:
            from src.titan_core import list_order
            saved = list_order.get_list_order('statusbar:items')
            if saved:
                items = list_order.apply_order(saved, items, lambda it: it[0])
        except Exception:
            pass
        self.statusbar_listbox.Clear()
        for key, text in items:
            self.statusbar_listbox.Append(text, clientData=key)

    def update_statusbar(self, event):
        """Refresh statusbar slots from the cache, looking up each row by key.

        After DnD reorder, slot positions no longer correspond to the
        original built-in / applet ordering, so we identify each row via
        its client_data key instead of writing by index.
        """
        if self.start_minimized and not hasattr(self, 'statusbar_listbox'):
            if hasattr(self, 'invisible_ui') and self.invisible_ui:
                self.invisible_ui.refresh_status_bar()
            return
        for key, text in self._statusbar_items():
            row = self._find_statusbar_row(key)
            if row >= 0:
                try:
                    self.statusbar_listbox.SetString(row, text)
                except Exception:
                    pass
            else:
                # Newly added applet that wasn't in the listbox yet -
                # append it so it shows up; saved order will pick it up
                # on the next populate.
                try:
                    self.statusbar_listbox.Append(text, clientData=key)
                except Exception:
                    pass

    def on_statusbar_click(self, event):
        """Activate the applet whose row was double-clicked.

        The row's client_data is the stable key (``applet:<name>`` for
        plugin slots) so this works even after the user has reordered the
        statusbar via drag-and-drop.
        """
        selection = self.statusbar_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        try:
            key = self.statusbar_listbox.GetClientData(selection)
        except Exception:
            key = None
        if not isinstance(key, str) or not key.startswith('applet:'):
            return
        applet_name = key[len('applet:'):]
        if hasattr(self, 'statusbar_applet_manager') and self.statusbar_applet_manager:
            try:
                self.statusbar_applet_manager.activate_applet(applet_name, parent_frame=self)
            except Exception as e:
                print(f"Error activating statusbar applet '{applet_name}': {e}")
                import traceback
                traceback.print_exc()

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

        # Tab bar row: play the characteristic ui/tapbar.ogg earcon and
        # speak "Tab bar" (SR-only) — same affordance as the listbox views,
        # routed through src.accessibility.messages so the string lives in
        # the accessibility translation domain. Skip the regular text speech
        # below: the tree itself already reads "Name, N of M" natively.
        if isinstance(item_data, dict) and item_data.get('type') == 'tab_bar':
            if not getattr(self, '_suppress_tab_bar_nav_speech', False):
                self._announce_tab_bar()
                self._schedule_tab_bar_tip()
            return

        # Selection moved off the tab bar row — cancel any pending tip.
        self._cancel_tab_bar_tip()

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

        # Screen readers announce tree selection changes natively; only call
        # speaker.speak() when no SR is active (e.g., SAPI fallback) so we
        # don't stack two voices saying the same item name.
        if not _is_screen_reader_running():
            try:
                speaker.speak(text, interrupt=True)
            except Exception:
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
            _show_skinned_message(_("An error occurred: No data to run."), _("Error"), wx.OK | wx.ICON_ERROR)
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
            _show_skinned_message(_("An error occurred: No data to uninstall."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        item_name = item_data.get('name', _('unknown item'))
        item_path = item_data.get('path')

        if not item_path or not os.path.exists(item_path):
            print(f"ERROR: Uninstall path is invalid or directory does not exist: {item_path}")
            _show_skinned_message(_("Error: Cannot find the directory '{}' to uninstall.").format(item_name), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        confirm_dialog = _new_message_dialog(
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
                        _show_skinned_message(_("'{}' has been successfully uninstalled.").format(item_name), _("Success"), wx.OK | wx.ICON_INFORMATION)

                    wx.CallAfter(refresh_ui)

                except OSError as e:
                    print(f"ERROR: Error deleting directory '{item_path}': {e}")

                    def show_error():
                        play_endoflist_sound()
                        vibrate_error()  # Add vibration for uninstall error
                        _show_skinned_message(_("Error uninstalling '{}':\n{}\n\nMake sure the directory is not in use.").format(item_name, e), _("Error"), wx.OK | wx.ICON_ERROR)

                    wx.CallAfter(show_error)

            threading.Thread(target=uninstall_thread, daemon=True).start()

        else:
            print(f"INFO: Uninstall of '{item_name}' canceled by user.")
            play_focus_sound()
            vibrate_focus_change()  # Add vibration for cancel action


    def _focus_is_text_entry(self, ctrl):
        """True if a text-entry control is focused, so the Buffer System keys
        (- = [ ] , . etc.) stay normal typing characters there."""
        try:
            if ctrl is None:
                return False
            if isinstance(ctrl, (wx.TextCtrl, wx.ComboBox, wx.SearchCtrl, wx.SpinCtrl)):
                return True
            is_editable = getattr(ctrl, 'IsEditable', None)
            if callable(is_editable):
                try:
                    return bool(is_editable())
                except Exception:
                    return False
        except Exception:
            return False
        return False

    # Buffer System: base key -> (action without Shift, action with Shift).
    _BUFFER_BASE_KEYS = {
        ord('-'): ('prev_category', 'first_category'),
        ord('='): ('next_category', 'last_category'),
        ord('['): ('prev_buffer', 'first_buffer'),
        ord(']'): ('next_buffer', 'last_buffer'),
        ord(','): ('prev_element', 'first_element'),
        ord('.'): ('next_element', 'last_element'),
    }

    def _buffer_action_for_event(self, keycode, modifiers):
        """Map a key event to a buffer action name, or None. Ignores events
        carrying Ctrl/Alt so only the bare keys (and Shift) are used."""
        if modifiers & (wx.MOD_CONTROL | wx.MOD_ALT | wx.MOD_ALTGR):
            return None
        shift = bool(modifiers & wx.MOD_SHIFT)
        pair = self._BUFFER_BASE_KEYS.get(keycode)
        if pair:
            return pair[1] if shift else pair[0]
        # Some layouts deliver the shifted glyph (_ + { } < >) as the keycode.
        try:
            from src.buffers import buffer_controller
            return buffer_controller.action_for_char(chr(keycode))
        except Exception:
            return None

    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        current_focus = self.FindFocus()

        # ---- Titan Buffer System review keys ----
        # Local to this focused window (no global hook); suppressed while a
        # text-entry control is focused so the keys keep typing normally.
        if not self._focus_is_text_entry(current_focus):
            _buf_action = self._buffer_action_for_event(keycode, modifiers)
            if _buf_action:
                try:
                    from src.buffers import buffer_controller
                    if buffer_controller.dispatch(_buf_action):
                        return
                except Exception as e:
                    print(f"Error in buffer key handling: {e}")

        # While a tab bar card is "picked up" (Space on the tab bar row), the
        # keyboard is locked to dragging: Left/Right move the card, Space drops
        # it, Escape cancels. All other navigation keys are swallowed so focus
        # stays on the card being moved.
        if getattr(self, '_tab_bar_drag_active', False) and self._focused_registered_view() is not None:
            if keycode == wx.WXK_SPACE and modifiers == wx.MOD_NONE:
                self._drop_tab_bar_drag()
                return
            if keycode == wx.WXK_ESCAPE:
                self._cancel_tab_bar_drag()
                return
            if keycode == wx.WXK_LEFT and modifiers == wx.MOD_NONE:
                self._move_tab_bar_drag(-1)
                return
            if keycode == wx.WXK_RIGHT and modifiers == wx.MOD_NONE:
                self._move_tab_bar_drag(+1)
                return
            if keycode in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_HOME, wx.WXK_END, wx.WXK_TAB):
                return  # locked to the picked-up card

        # Space on the virtual tab bar row picks the current card up for
        # drag-and-drop reordering.
        if keycode == wx.WXK_SPACE and modifiers == wx.MOD_NONE and not getattr(self, '_tab_bar_drag_active', False):
            view = self._focused_registered_view()
            if view is not None and self._is_tab_bar_selection(view['control']):
                self._start_tab_bar_drag()
                return

        # Ctrl+Up / Ctrl+Down move the selected list item one row. When the
        # focused control is one of the registered views, _handle_list_item_move
        # does the work. For every OTHER list that opted in via the shared
        # list_dnd helper (status bar, Telegram, Titan-Net, Elten, Feedback
        # Hub, IM modules), the focused widget has its own EVT_KEY_DOWN
        # handler from the helper - we must Skip() so it actually fires
        # rather than being swallowed by handle_navigation below.
        if keycode in (wx.WXK_UP, wx.WXK_DOWN) and modifiers == wx.MOD_CONTROL:
            if self._handle_list_item_move(keycode):
                return
            event.Skip()
            return

        # Handle F1 (Help)
        if keycode == wx.WXK_F1 and modifiers == wx.MOD_NONE:
            show_help()
            return

        # Handle Alt+F1 (Start Menu) - Linux style only
        if keycode == wx.WXK_F1 and modifiers == wx.MOD_ALT:
            if self.start_menu and IS_WINDOWS:
                self.start_menu.toggle_menu()
                return

        # Handle F4 (Switch To) - only bare F4, not Alt+F4/Ctrl+F4/etc.
        if keycode == wx.WXK_F4 and modifiers == wx.MOD_NONE:
            self.on_show_window_switcher(event)
            return

        # Handle Alt+F4 — only this exact keypress respects the alt_f4_action
        # setting. All other close paths (menu Exit, IUI Exit, title bar X)
        # always close the program (subject to confirm_exit).
        if keycode == wx.WXK_F4 and modifiers == wx.MOD_ALT:
            try:
                from src.settings.settings import get_setting
                action = get_setting('alt_f4_action', 'close', section='general')
            except Exception:
                action = 'close'
            if action == 'tray':
                # Iconize triggers on_minimize, which honors minimize_action.
                try:
                    self.Iconize(True)
                except Exception as _e:
                    print(f"Warning: Iconize on Alt+F4 failed: {_e}")
                return
            # 'close' → fall through so the system delivers WM_CLOSE → EVT_CLOSE
            event.Skip()
            return

        # Note: Ctrl+Shift+A (AI Voice Recognition) is now a global hotkey registered in __init__

        # Ctrl alone — silence any ongoing Telegram / stereo TTS announcement
        # (screen reader convention). Long Telegram messages can chain up on
        # the pygame-backed stereo engine, which the screen reader can't
        # interrupt on its own.
        if keycode == wx.WXK_CONTROL:
            try:
                from src.titan_core.stereo_speech import stop_stereo_speech
                stop_stereo_speech()
            except Exception:
                pass
            try:
                from src.network import telegram_gui as _tg_gui
                _tg_speaker = getattr(_tg_gui, '_speaker', None)
                if _tg_speaker is not None and hasattr(_tg_speaker, 'stop'):
                    _tg_speaker.stop()
            except Exception:
                pass
            event.Skip()
            return

        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            # Ctrl+Tab cycles forward through registered views.
            self._cycle_tab_bar(+1)
            return
        if keycode == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._cycle_tab_bar(-1)
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
                # Check registered component views for on_activate
                handled = False
                for view in self.registered_views:
                    if view.get('on_activate') and current_focus == view['control'] and view['control'].IsShown():
                        try:
                            view['on_activate'](event)
                        except Exception as e:
                            print(f"[GUI] Error in on_activate for view '{view['id']}': {e}")
                        handled = True
                        break
                if not handled:
                    event.Skip()
            return

        if keycode == wx.WXK_TAB:
             if modifiers == wx.MOD_NONE:
                  if current_focus == self.app_listbox and self.app_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()
                  elif current_focus == self.game_tree and self.game_tree.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()
                  elif current_focus == self.network_listbox and self.network_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()
                  elif current_focus == self.users_listbox and self.users_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()
                  elif current_focus == self.message_input and self.message_input.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                      vibrate_focus_change()
                  elif current_focus == self.statusbar_listbox:
                      # Focus back on current view's control
                      self._focus_current_view_control()
                  else:
                      # Check registered component view controls
                      tab_handled = False
                      for view in self.registered_views:
                          if current_focus == view['control'] and view['control'].IsShown():
                              self.statusbar_listbox.SetFocus()
                              play_statusbar_sound()
                              vibrate_focus_change()
                              tab_handled = True
                              break
                      if not tab_handled:
                          event.Skip()
                  return
             elif modifiers == wx.MOD_SHIFT:
                  if current_focus == self.statusbar_listbox:
                      self._focus_current_view_control()
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
            # Tab bar row for the tree lives as the first child of the
            # invisible root; Left/Right on it cycles views (linear).
            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
                if self._is_tab_bar_selection(self.game_tree):
                    self._cycle_tab_bar(-1 if keycode == wx.WXK_LEFT else +1)
                    return
                # Left/Right on regular tree items is reserved for the tab bar
                # — fall through to native collapse/expand only when focus is
                # not on the tab bar row
            # Peek the next/prev item: if it's the tab bar row, suppress the
            # regular focus sound so on_game_tree_selection_changed can play
            # the dedicated ui/tapbar.ogg earcon without it being masked.
            will_land_on_tab_bar = False
            if keycode in (wx.WXK_UP, wx.WXK_DOWN):
                current_item = self.game_tree.GetSelection()
                if current_item.IsOk():
                    if keycode == wx.WXK_DOWN:
                        next_item = self.get_next_tree_item(current_item)
                    else:
                        next_item = self.get_prev_tree_item(current_item)
                    if next_item and next_item.IsOk():
                        ndata = self.game_tree.GetItemData(next_item)
                        if isinstance(ndata, dict) and ndata.get('type') == 'tab_bar':
                            will_land_on_tab_bar = True
            # Default: let TreeCtrl handle its own navigation with audio feedback
            if not will_land_on_tab_bar:
                play_focus_sound()
            vibrate_cursor_move()
            event.Skip()
            return

        target_listbox = None
        is_registered_view = False
        if current_focus == self.app_listbox and self.app_listbox.IsShown():
            target_listbox = self.app_listbox
            is_registered_view = True
        elif current_focus == self.network_listbox and self.network_listbox.IsShown():
            target_listbox = self.network_listbox
            is_registered_view = True
        elif current_focus == self.users_listbox and self.users_listbox.IsShown():
            target_listbox = self.users_listbox
        elif current_focus == self.statusbar_listbox:
            target_listbox = self.statusbar_listbox
        else:
            # Allow registered component listboxes to use the tab bar row too
            for view in getattr(self, 'registered_views', []):
                ctrl = view.get('control')
                if current_focus == ctrl and isinstance(ctrl, wx.ListBox) and ctrl.IsShown():
                    target_listbox = ctrl
                    is_registered_view = True
                    break
            if target_listbox is None:
                event.Skip()
                return

        if target_listbox:
            current_selection = target_listbox.GetSelection()
            item_count = target_listbox.GetCount()

            # Tab bar row lives at index 0 of every registered view listbox.
            # Left/Right on row 0 cycles between views (linear, edge sound).
            # Left/Right elsewhere is reserved for the tab bar — ignore.
            if is_registered_view:
                if current_selection == 0 and keycode == wx.WXK_LEFT:
                    self._cycle_tab_bar(-1)
                    return
                if current_selection == 0 and keycode == wx.WXK_RIGHT:
                    self._cycle_tab_bar(+1)
                    return
                if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
                    # On regular items Left/Right does nothing
                    return

            new_selection = current_selection

            if keycode == wx.WXK_UP:
                new_selection -= 1
            elif keycode == wx.WXK_DOWN:
                new_selection += 1
            elif keycode == wx.WXK_LEFT:
                new_selection -= 1
            elif keycode == wx.WXK_RIGHT:
                new_selection += 1
            elif keycode == wx.WXK_HOME:
                new_selection = 0
            elif keycode == wx.WXK_END:
                new_selection = item_count - 1

            if new_selection >= 0 and new_selection < item_count:
                target_listbox.SetSelection(new_selection)
                vibrate_cursor_move()  # Add vibration for cursor movement
                if getattr(self, '_startup_sound_guard', False):
                    # Suppress the very first focus/list-item sound during startup
                    return
                if is_registered_view and new_selection == 0:
                    # Landed on the tab bar row — play the tab bar focus sound,
                    # start the 4-second screen-reader tip, and speak "Tab bar"
                    # when an actual screen reader is running.
                    self._announce_tab_bar()
                    self._schedule_tab_bar_tip()
                else:
                    if is_registered_view and current_selection == 0:
                        self._cancel_tab_bar_tip()
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
        
        item_l = item.lower()
        if _("Network status:") in item or any(k in item_l for k in [
            'connected', 'disconnected', 'wifi', 'ethernet', 'signal strength',
            'połączono', 'nie połączono', 'sygnału', 'sieci',
        ]):
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
            # Check if this is a statusbar applet
            # Strategy: Check if item matches applet pattern (not exact text, since values change)
            applet_handled = False
            if hasattr(self, 'statusbar_applet_manager') and self.statusbar_applet_manager:
                for applet_name in self.statusbar_applet_manager.get_applet_names():
                    try:
                        # Get a fresh applet text to check the pattern
                        self.statusbar_applet_manager.update_applet_cache(applet_name)
                        applet_text = self.statusbar_applet_manager.get_applet_text(applet_name)

                        # Extract pattern keywords from applet text (words before colons)
                        # e.g., "CPU: 8%, RAM: 41%" -> ["CPU", "RAM"]
                        import re
                        applet_keywords = re.findall(r'(\w+):', applet_text)
                        item_keywords = re.findall(r'(\w+):', item)

                        # Check if item has same keyword pattern as applet
                        if applet_keywords and item_keywords and set(applet_keywords) == set(item_keywords):
                            print(f"Statusbar applet detected: '{applet_name}' (pattern match: {applet_keywords}) - activating...")
                            # Call activation on main thread (for GUI dialogs)
                            wx.CallAfter(self.statusbar_applet_manager.activate_applet, applet_name, self)
                            applet_handled = True
                            break
                    except Exception as e:
                        print(f"Error checking statusbar applet '{applet_name}': {e}")
                        import traceback
                        traceback.print_exc()

            if not applet_handled:
                print(f"WARNING: Unknown statusbar item selected: {item}")


    def _apply_list_label_for_sr(self, visible_text):
        """Set the StaticText list label above the current list."""
        try:
            self.list_label.SetLabel(visible_text)
        except Exception as e:
            print(f"[GUI] _apply_list_label_for_sr error: {e}")

    def _with_tab_bar_nav_speech_suppressed(self):
        """Mark the next programmatic selection/focus of the tab bar row as
        a show/cycle (not an arrow-nav) so the tree/listbox selection
        handler won't speak "Tab bar". The flag auto-clears on the next
        idle tick via ``wx.CallAfter``."""
        self._suppress_tab_bar_nav_speech = True
        try:
            wx.CallAfter(self._clear_suppress_tab_bar_nav_speech)
        except Exception:
            self._suppress_tab_bar_nav_speech = False

    def _clear_suppress_tab_bar_nav_speech(self):
        self._suppress_tab_bar_nav_speech = False

    def show_app_list(self, focus_list=True):
        self._hide_all_views()
        self.app_listbox.Show()
        self._apply_list_label_for_sr(_("Application List:"))
        self.current_list = "apps"
        self._update_tab_bar_display()
        self.Layout()
        self._with_tab_bar_nav_speech_suppressed()
        # Focus the tab bar row so the screen reader reads ONLY the plain
        # "Applications, N of M" announcement (from the row text). The user
        # explicitly asked that view switches say only that phrase, not
        # "Application list, list, Applications, 1 of 4". Arrow Up later
        # from a real item to row 0 is a different context — it announces
        # "Tab bar" via handle_navigation.
        if focus_list and self.app_listbox.GetCount() > 0:
            self.app_listbox.SetSelection(0)
            self.app_listbox.SetFocus()
        if focus_list:
            vibrate_menu_open()


    def show_game_list(self, focus_list=True):
        self._hide_all_views()
        self.game_tree.Show()
        self._apply_list_label_for_sr(_("Game List:"))
        self.current_list = "games"
        self._update_tab_bar_display()
        if focus_list:
            vibrate_menu_open()
        self.Layout()

        # Land on the tab bar row (first child of the invisible root) so the
        # screen reader reads only "Games, N of M" and Left/Right immediately
        # cycles views. The suppress flag stops on_game_tree_selection_changed
        # from speaking "Tab bar" on this programmatic selection.
        if focus_list:
            self._with_tab_bar_nav_speech_suppressed()
            root = self.game_tree.GetRootItem()
            if root.IsOk():
                first, cookie = self.game_tree.GetFirstChild(root)
                if first.IsOk():
                    self.game_tree.SelectItem(first)
                    self.game_tree.SetFocus()

    def show_network_list(self, focus_list=True):
        self._hide_all_views()
        self.network_listbox.Show()
        self._apply_list_label_for_sr(_("Titan IM:"))
        self.current_list = "network"
        self._update_tab_bar_display()
        if focus_list:
            vibrate_menu_open()

        # Always populate the network list based on login status
        self.populate_network_list()

        self.Layout()
        # Land on the tab bar row so the screen reader reads only the plain
        # "Titan IM, N of M" row text (no doubled label or "tab bar" prefix)
        # and the user can cycle views with Left/Right immediately.
        if focus_list and self.network_listbox.GetCount() > 0:
            self._with_tab_bar_nav_speech_suppressed()
            self.network_listbox.SetSelection(0)
            self.network_listbox.SetFocus()

    def _hide_all_views(self):
        """Hide all view controls (built-in and component-registered)."""
        for view in self.registered_views:
            view['control'].Hide()
        # Also hide non-cycling controls
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()

    def _view_short_name(self, view):
        """Get a short label for a view (for tab bar / toolbar)."""
        short = view.get('short_name')
        if short:
            return short
        label = view.get('label', view.get('id', ''))
        return label.rstrip(':').strip()

    def _get_tab_bar_announcement(self):
        """Return (short_name, index, total) for the currently selected view."""
        if not self.registered_views:
            return ("", 0, 0)
        idx = self._get_view_index(self.current_list)
        if idx < 0:
            idx = 0
        view = self.registered_views[idx]
        return (self._view_short_name(view), idx, len(self.registered_views))

    def _get_tab_bar_item_text(self):
        """Return the text used for the virtual tab bar first-item entry.

        The row text is the clean view announcement ("Applications, 1 of 4")
        with no "Tab bar:" prefix: that's what the user wants to hear when a
        view is shown or when cycling. The "Tab bar" indicator is instead
        spoken separately via ``speaker.speak`` when the user arrows up from
        a real item to row 0, so the two cases don't stomp on each other.
        """
        short, idx, total = self._get_tab_bar_announcement()
        if total <= 0:
            return _("Tab bar")
        return _("{}, {} of {}").format(short, idx + 1, total)

    def _is_tab_bar_selection(self, control):
        """Return True when the given list/tree control has the tab bar item selected."""
        try:
            if isinstance(control, wx.ListBox):
                return control.GetSelection() == 0
            if isinstance(control, wx.TreeCtrl):
                sel = control.GetSelection()
                if not sel.IsOk():
                    return False
                data = control.GetItemData(sel)
                return isinstance(data, dict) and data.get('type') == 'tab_bar'
        except Exception:
            pass
        return False

    def _is_tab_bar_row_text(self, text):
        """Heuristic: is `text` the tab bar first-item text for any currently
        registered view? Used to detect whether row 0 of a listbox is already
        the tab bar row (vs a regular item that happens to sit at index 0)."""
        if not text:
            return False
        total = len(self.registered_views)
        for i, view in enumerate(self.registered_views):
            if text == _("{}, {} of {}").format(self._view_short_name(view), i + 1, total):
                return True
        # Legacy tab bar text from before the short-name refactor. Still
        # counts as a tab bar row so we replace rather than insert duplicates.
        if text == _("Tab bar") or text.startswith(_("Tab bar")):
            return True
        return False

    def _cleanup_stale_tab_bar_rows_listbox(self, listbox, start=0):
        """Remove every tab bar row from ``listbox`` at index >= ``start``.

        Identified by either the ``{'type': 'tab_bar'}`` client-data marker
        (primary) or by a text pattern matching any registered view's
        short_name (fallback for rows created before the marker existed or
        whose totals have since changed). Walks from end to ``start`` to
        avoid index shifts.

        Pass ``start=1`` to preserve a known-good tab bar row at index 0.
        """
        try:
            import re
            patterns = []
            for view in getattr(self, 'registered_views', []):
                short = self._view_short_name(view)
                if short:
                    patterns.append(re.compile(rf'^{re.escape(short)}, \d+ \S+ \d+$'))
            for i in range(listbox.GetCount() - 1, start - 1, -1):
                is_tab_bar = False
                try:
                    data = listbox.GetClientData(i)
                    if isinstance(data, dict) and data.get('type') == 'tab_bar':
                        is_tab_bar = True
                except Exception:
                    pass
                if not is_tab_bar:
                    try:
                        text = listbox.GetString(i)
                        if text and any(p.match(text) for p in patterns):
                            is_tab_bar = True
                        elif text and (text == _("Tab bar") or text.startswith(_("Tab bar"))):
                            is_tab_bar = True
                    except Exception:
                        pass
                if is_tab_bar:
                    try:
                        listbox.Delete(i)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[GUI] cleanup stale tab bar rows error: {e}")

    def _cleanup_stale_tab_bar_nodes_tree(self, tree):
        """Remove every tab bar node from ``tree`` (top-level children).

        Identified by the ``{'type': 'tab_bar'}`` client-data marker.
        """
        try:
            root = tree.GetRootItem()
            if not root.IsOk():
                return
            to_delete = []
            child, cookie = tree.GetFirstChild(root)
            while child.IsOk():
                try:
                    data = tree.GetItemData(child)
                    if isinstance(data, dict) and data.get('type') == 'tab_bar':
                        to_delete.append(child)
                except Exception:
                    pass
                child, cookie = tree.GetNextChild(root, cookie)
            for item in to_delete:
                try:
                    tree.Delete(item)
                except Exception:
                    pass
        except Exception as e:
            print(f"[GUI] cleanup stale tab bar tree nodes error: {e}")

    def _inject_tab_bar_into_listbox(self, listbox):
        """Ensure the virtual tab bar row sits at index 0 of ``listbox``.

        Idempotent: if row 0 is already the correct tab bar row (right
        marker and text), the row is left untouched and only stray
        duplicates further down the list are removed. This preserves any
        current selection on row 0 when ``SetFocus()`` triggers an
        auto-sync inject (needed so switching to a component view lands
        selection ON the tab bar row, not above or below it).

        Otherwise the list is fully cleaned and a fresh tab bar row is
        prepended and marked via client data ``{'type': 'tab_bar'}``.
        """
        try:
            expected = self._get_tab_bar_item_text()

            # Fast path: row 0 is already a correct tab bar row — keep it and
            # only remove any stray duplicates below.
            try:
                if listbox.GetCount() > 0:
                    data0 = listbox.GetClientData(0)
                    if isinstance(data0, dict) and data0.get('type') == 'tab_bar':
                        if listbox.GetString(0) != expected:
                            listbox.SetString(0, expected)
                        self._cleanup_stale_tab_bar_rows_listbox(listbox, start=1)
                        return
            except Exception:
                pass

            # Slow path: row 0 is not our tab bar row. Clean every tab bar
            # row (including stale ones with outdated totals) and prepend a
            # fresh one.
            self._cleanup_stale_tab_bar_rows_listbox(listbox)
            listbox.Insert(expected, 0)
            try:
                listbox.SetClientData(0, {'type': 'tab_bar'})
            except Exception:
                pass
        except Exception as e:
            print(f"[GUI] tab bar listbox inject error: {e}")

    def _inject_tab_bar_into_tree(self, tree):
        """Ensure the virtual tab bar node is the first child of the tree's
        invisible root. Idempotent — if the first child is already a
        correctly-marked tab bar node, only its text is refreshed (so
        selection on that node is preserved across an auto-sync)."""
        try:
            root = tree.GetRootItem()
            if not root.IsOk():
                return
            expected = self._get_tab_bar_item_text()

            # Fast path: first child is already the tab bar node.
            first, cookie = tree.GetFirstChild(root)
            if first.IsOk():
                try:
                    data = tree.GetItemData(first)
                    if isinstance(data, dict) and data.get('type') == 'tab_bar':
                        if tree.GetItemText(first) != expected:
                            tree.SetItemText(first, expected)
                        # Remove any extra tab bar nodes past the first
                        extras = []
                        nxt, ncookie = tree.GetNextChild(root, cookie)
                        while nxt.IsOk():
                            ndata = tree.GetItemData(nxt)
                            if isinstance(ndata, dict) and ndata.get('type') == 'tab_bar':
                                extras.append(nxt)
                            nxt, ncookie = tree.GetNextChild(root, ncookie)
                        for e in extras:
                            try:
                                tree.Delete(e)
                            except Exception:
                                pass
                        return
                except Exception:
                    pass

            # Slow path: no leading tab bar node — clean + prepend fresh.
            self._cleanup_stale_tab_bar_nodes_tree(tree)
            new_item = tree.PrependItem(root, expected)
            tree.SetItemData(new_item, {'type': 'tab_bar'})
        except Exception as e:
            print(f"[GUI] tab bar tree inject error: {e}")

    def _refresh_all_tab_bar_items(self):
        """Refresh the tab bar text in every registered view's control (totals may have changed).

        Each control's tab bar row text is built against whichever view that
        control belongs to — so view A's tab bar row says "Tab bar: A, N of M".
        """
        saved_current = getattr(self, 'current_list', None)
        try:
            for view in getattr(self, 'registered_views', []):
                self.current_list = view['id']
                ctrl = view.get('control')
                if isinstance(ctrl, wx.ListBox):
                    self._inject_tab_bar_into_listbox(ctrl)
                elif isinstance(ctrl, wx.TreeCtrl):
                    self._inject_tab_bar_into_tree(ctrl)
        finally:
            if saved_current is not None:
                self.current_list = saved_current

    def _update_tab_bar_display(self):
        """Refresh only the current view's tab bar row."""
        view_idx = self._get_view_index(self.current_list)
        if view_idx < 0:
            return
        ctrl = self.registered_views[view_idx].get('control')
        if isinstance(ctrl, wx.ListBox):
            self._inject_tab_bar_into_listbox(ctrl)
        elif isinstance(ctrl, wx.TreeCtrl):
            self._inject_tab_bar_into_tree(ctrl)

    def _announce_tab_bar(self):
        """Play the tab bar focus sound and, when a real screen reader is
        active, announce "Tab bar".

        Delegates to ``src.accessibility.messages.announce_tab_bar`` so the
        "Tab bar" string lives in the ``accessibility`` translation domain
        rather than ``gui``.
        """
        try:
            from src.accessibility.messages import announce_tab_bar
            announce_tab_bar()
        except Exception as e:
            print(f"[GUI] announce_tab_bar error: {e}")

    def _announce_view_switched(self, view, idx, total):
        """Announce the view reached by cycling the tab bar (Left/Right).

        Delegates to ``src.accessibility.messages.announce_view_switched`` which
        plays the switch-list earcon and, when the in-process Titan Access reader
        is active, speaks "<view>, N of M, tab" (replacing the reader's own read
        of the list row). For an external SR it stays silent and lets that SR
        read the row text, avoiding the duplicate announcement.
        """
        try:
            from src.accessibility.messages import announce_view_switched
            announce_view_switched(self._view_short_name(view), idx, total)
        except Exception as e:
            print(f"[GUI] announce_view_switched error: {e}")
            try:
                play_sound('ui/switch_list.ogg')
            except Exception:
                pass

    def _schedule_tab_bar_tip(self):
        """Start the 4-second accessibility tip when focus sits on the tab bar item."""
        if self._tab_bar_tip_active:
            return
        if not _is_screen_reader_running():
            return
        try:
            from src.accessibility.messages import show_tab_bar_tip
            show_tab_bar_tip(delay=4.0)
            self._tab_bar_tip_active = True
        except Exception as e:
            print(f"[GUI] tip schedule error: {e}")

    def _cancel_tab_bar_tip(self):
        """Cancel the pending accessibility tip (selection moved off the tab bar item)."""
        try:
            from src.accessibility.messages import cancel_tab_bar_tip
            cancel_tab_bar_tip()
        except Exception:
            pass
        self._tab_bar_tip_active = False

    def _cycle_tab_bar(self, direction):
        """Switch to the previous (-1) or next (+1) registered view from the tab bar item.

        The tab bar is *linear* — navigating past the first/last view plays the
        end-of-tabbar edge sound and stays put.
        """
        if not self.registered_views:
            return
        current_idx = self._get_view_index(self.current_list)
        if current_idx < 0:
            current_idx = 0
        new_idx = current_idx + direction
        if new_idx < 0 or new_idx >= len(self.registered_views):
            # At an edge — play the edge sound and stay
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        new_view = self.registered_views[new_idx]

        if new_view.get('show_method'):
            new_view['show_method'](focus_list=False)
        else:
            self._show_registered_view(new_view['id'], focus_list=False)

        # Place focus on the new list's tab bar row (item 0) so subsequent
        # Up/Down/Left/Right keep working off the same virtual element. The
        # suppress flag prevents the tree selection handler from speaking
        # "Tab bar" on this programmatic move — the user wants only the
        # view-name announcement on cycle (from the row text itself).
        self._with_tab_bar_nav_speech_suppressed()
        ctrl = new_view.get('control')
        try:
            if isinstance(ctrl, wx.ListBox):
                if ctrl.GetCount() > 0:
                    ctrl.SetSelection(0)
                ctrl.SetFocus()
            elif isinstance(ctrl, wx.TreeCtrl):
                root = ctrl.GetRootItem()
                if root.IsOk():
                    first, cookie = ctrl.GetFirstChild(root)
                    if first.IsOk():
                        ctrl.SelectItem(first)
                ctrl.SetFocus()
        except Exception as e:
            print(f"[GUI] tab bar cycle focus error: {e}")

        self._announce_view_switched(new_view, new_idx, len(self.registered_views))
        vibrate_focus_change()
        # The tab bar row is still focused in the new list, so reset the tip timer.
        self._cancel_tab_bar_tip()
        self._schedule_tab_bar_tip()

    def focus_tab_bar(self):
        """Move focus to the current list and select its first item (the tab bar row)."""
        current_idx = self._get_view_index(self.current_list)
        if current_idx < 0 and self.registered_views:
            current_idx = 0
        if current_idx < 0:
            return
        view = self.registered_views[current_idx]
        ctrl = view.get('control')
        # Suppress the per-event "Tab bar" announcement from the tree
        # selection handler — we speak it exactly once via
        # _announce_tab_bar() below so Ctrl+Tab doesn't double-announce for
        # TreeCtrl views.
        self._with_tab_bar_nav_speech_suppressed()
        try:
            if isinstance(ctrl, wx.ListBox):
                if ctrl.GetCount() > 0:
                    ctrl.SetSelection(0)
                ctrl.SetFocus()
            elif isinstance(ctrl, wx.TreeCtrl):
                root = ctrl.GetRootItem()
                if root.IsOk():
                    first, cookie = ctrl.GetFirstChild(root)
                    if first.IsOk():
                        ctrl.SelectItem(first)
                ctrl.SetFocus()
        except Exception as e:
            print(f"[GUI] focus_tab_bar error: {e}")
        self._announce_tab_bar()
        self._cancel_tab_bar_tip()
        self._schedule_tab_bar_tip()

    # ------------------------------------------------------------------
    # Drag-and-drop reordering
    #
    # Two surfaces:
    #   * The virtual tab bar row: Space picks the current card up, Left/Right
    #     move it, Space drops it, Escape cancels. Mouse: not applicable (the
    #     tab bar row is reordered via the keyboard).
    #   * List/tree items: Ctrl+Up / Ctrl+Down move the selected item one row,
    #     or the item can be dragged with the mouse.
    # Positions persist to .index.TCG via src.titan_core.list_order.
    # Sounds: ui/drag.ogg on pick-up / move, ui/drop.ogg on drop.
    # ------------------------------------------------------------------

    def _view_by_control(self, ctrl):
        """Return the registered-view dict whose control is ``ctrl`` (or None)."""
        for view in getattr(self, 'registered_views', []):
            if view.get('control') is ctrl:
                return view
        return None

    def _focused_registered_view(self):
        """Return the registered-view dict for the currently focused control."""
        return self._view_by_control(self.FindFocus())

    def _apply_saved_tab_bar_order(self):
        """Reorder ``registered_views`` to match the saved tab bar order."""
        try:
            from src.titan_core import list_order
            saved = list_order.get_tab_bar_order()
            if not saved:
                return
            self.registered_views = list_order.apply_order(
                saved, self.registered_views, lambda v: v['id'])
        except Exception as e:
            print(f"[GUI] apply saved tab bar order error: {e}")

    def _show_first_view(self):
        """Show the first card in the tab bar.

        The first card is whatever the user dragged into slot 1 — not
        necessarily the application list — so startup honors the saved
        drag-and-drop order from .index.TCG.
        """
        if not self.registered_views:
            self.show_app_list()
            return
        first = self.registered_views[0]
        if first.get('show_method'):
            first['show_method']()
        else:
            self._show_registered_view(first['id'])

    def _rebuild_view_toolbar(self):
        """Rebuild the toolbar view buttons so they match ``registered_views``."""
        if not getattr(self, 'toolbar', None):
            return
        try:
            for tool in list(self._view_tools.values()):
                try:
                    self.toolbar.DeleteTool(tool.GetId())
                except Exception:
                    pass
            self._view_tools = {}
            for view in self.registered_views:
                self._add_toolbar_tool(view)
            self.toolbar.Realize()
        except Exception as e:
            print(f"[GUI] rebuild toolbar error: {e}")

    def _speak_drag(self, message, suppress_if_sr=False):
        """Speak a short drag-and-drop status message (screen reader feedback).

        ``suppress_if_sr=True`` means this string would duplicate what an
        active screen reader is already auto-announcing (e.g. the new row
        text "<View>, N of M" after focus changes). In that case we skip
        the manual speak so SR users don't hear the same line two or three
        times. Without an SR (SAPI/NSSpeech/spd fallback only) we always
        speak so the user still gets feedback.
        """
        if suppress_if_sr and _is_screen_reader_running():
            return
        try:
            speaker.speak(message, interrupt=True)
        except Exception:
            pass

    # --- Tab bar card drag ---------------------------------------------

    def _start_tab_bar_drag(self):
        """Pick up the current tab bar card for keyboard drag-and-drop."""
        view = self._focused_registered_view()
        if view is None:
            return
        self._tab_bar_drag_active = True
        self._tab_bar_drag_view_id = view['id']
        self._tab_bar_drag_origin = [v['id'] for v in self.registered_views]
        try:
            play_sound('ui/drag.ogg')
        except Exception:
            pass
        self._speak_drag(_("Picked up {}").format(self._view_short_name(view)))

    def _move_tab_bar_drag(self, direction):
        """Move the picked-up tab bar card one slot left (-1) or right (+1)."""
        if not self._tab_bar_drag_active:
            return
        idx = self._get_view_index(self._tab_bar_drag_view_id)
        if idx < 0:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self.registered_views):
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        views = self.registered_views
        views[idx], views[new_idx] = views[new_idx], views[idx]
        self._rebuild_view_toolbar()
        self._refresh_all_tab_bar_items()
        try:
            play_sound('ui/drag.ogg')
        except Exception:
            pass
        # Keep focus/selection on the picked-up card in its new position.
        # Skip SetSelection/SetFocus when the listbox is already in that
        # state - calling them anyway can fire EVT_LISTBOX / EVT_SET_FOCUS
        # which makes screen readers re-read the focused row text on top
        # of the natural read triggered by the SetString text refresh.
        view = self.registered_views[new_idx]
        ctrl = view.get('control')
        self._with_tab_bar_nav_speech_suppressed()
        try:
            if isinstance(ctrl, wx.ListBox):
                if ctrl.GetCount() > 0 and ctrl.GetSelection() != 0:
                    ctrl.SetSelection(0)
                if not ctrl.HasFocus():
                    ctrl.SetFocus()
            elif isinstance(ctrl, wx.TreeCtrl):
                root = ctrl.GetRootItem()
                if root.IsOk():
                    first, _cookie = ctrl.GetFirstChild(root)
                    if first.IsOk() and ctrl.GetSelection() != first:
                        ctrl.SelectItem(first)
                if not ctrl.HasFocus():
                    ctrl.SetFocus()
        except Exception as e:
            print(f"[GUI] tab bar drag focus error: {e}")
        # ``suppress_if_sr=True``: SR users already heard the new row text
        # ("<View>, N of M") auto-announced when SetString refreshed row 0.
        # Speaking it again here was the source of the doubled / tripled
        # "Titan-Net, 1 of 4" announcement during tab bar drag.
        self._speak_drag(_("{}, {} of {}").format(
            self._view_short_name(view), new_idx + 1, len(self.registered_views)),
            suppress_if_sr=True)
        vibrate_cursor_move()

    def _drop_tab_bar_drag(self):
        """Drop the picked-up tab bar card and persist the new order."""
        if not self._tab_bar_drag_active:
            return
        view_id = self._tab_bar_drag_view_id
        self._tab_bar_drag_active = False
        self._tab_bar_drag_view_id = None
        self._tab_bar_drag_origin = None
        try:
            from src.titan_core import list_order
            list_order.set_tab_bar_order([v['id'] for v in self.registered_views])
        except Exception as e:
            print(f"[GUI] save tab bar order error: {e}")
        try:
            play_sound('ui/drop.ogg')
        except Exception:
            pass
        idx = self._get_view_index(view_id)
        if idx >= 0:
            view = self.registered_views[idx]
            self._speak_drag(_("Dropped {} at position {}").format(
                self._view_short_name(view), idx + 1))
        vibrate_selection()

    def _cancel_tab_bar_drag(self):
        """Abort the in-progress tab bar drag and restore the original order."""
        if not self._tab_bar_drag_active:
            return
        origin = self._tab_bar_drag_origin or []
        view_id = self._tab_bar_drag_view_id
        self._tab_bar_drag_active = False
        self._tab_bar_drag_view_id = None
        self._tab_bar_drag_origin = None
        if origin:
            by_id = {v['id']: v for v in self.registered_views}
            restored = [by_id[i] for i in origin if i in by_id]
            for v in self.registered_views:
                if v['id'] not in origin:
                    restored.append(v)
            self.registered_views = restored
            self._rebuild_view_toolbar()
            self._refresh_all_tab_bar_items()
        try:
            play_sound('ui/popupclose.ogg')
        except Exception:
            pass
        self._speak_drag(_("Drag cancelled"))
        idx = self._get_view_index(view_id)
        if idx >= 0:
            ctrl = self.registered_views[idx].get('control')
            self._with_tab_bar_nav_speech_suppressed()
            try:
                if isinstance(ctrl, wx.ListBox):
                    if ctrl.GetCount() > 0:
                        ctrl.SetSelection(0)
                    ctrl.SetFocus()
                elif isinstance(ctrl, wx.TreeCtrl):
                    root = ctrl.GetRootItem()
                    if root.IsOk():
                        first, _cookie = ctrl.GetFirstChild(root)
                        if first.IsOk():
                            ctrl.SelectItem(first)
                    ctrl.SetFocus()
            except Exception:
                pass

    # --- List item move (Ctrl+Up / Ctrl+Down) --------------------------

    def _handle_list_item_move(self, keycode):
        """Move the selected item in the focused list/tree. Returns True if handled."""
        view = self._focused_registered_view()
        if view is None:
            return False
        direction = -1 if keycode == wx.WXK_UP else +1
        ctrl = view['control']
        if isinstance(ctrl, wx.ListBox):
            return self._move_listbox_item(view, ctrl, direction)
        if isinstance(ctrl, wx.TreeCtrl):
            return self._move_tree_item(view, ctrl, direction)
        return False

    def _move_listbox_item(self, view, listbox, direction):
        """Ctrl+Up/Down move for a list box item. Always returns True (handled)."""
        sel = listbox.GetSelection()
        if sel == wx.NOT_FOUND or sel == 0:
            return True  # index 0 is the virtual tab bar row — not movable
        target = sel + direction
        if target <= 0 or target >= listbox.GetCount():
            try:
                play_endoflist_sound()
            except Exception:
                pass
            return True
        self._move_listbox_item_to(listbox, sel, target)
        return True

    def _move_listbox_item_to(self, listbox, from_idx, to_idx):
        """Move a list box item from ``from_idx`` to ``to_idx`` (1-based; index 0
        is the virtual tab bar row and is left untouched). Persists the new
        order and gives audio/speech feedback."""
        count = listbox.GetCount()
        if from_idx <= 0 or to_idx <= 0 or from_idx >= count or to_idx >= count:
            return
        # Snapshot every real item (skip the tab bar row at 0).
        items = []
        for i in range(1, count):
            try:
                data = listbox.GetClientData(i)
            except Exception:
                data = None
            items.append((listbox.GetString(i), data))
        moved = items.pop(from_idx - 1)
        items.insert(to_idx - 1, moved)
        # Rewrite the real rows, leaving the tab bar row at index 0 in place.
        for i in range(count - 1, 0, -1):
            listbox.Delete(i)
        for text, data in items:
            if data is None:
                listbox.Append(text)
            else:
                listbox.Append(text, clientData=data)
        new_sel = items.index(moved) + 1
        listbox.SetSelection(new_sel)
        try:
            play_sound('ui/drop.ogg')
        except Exception:
            pass
        vibrate_selection()
        view = self._view_by_control(listbox)
        if view:
            self._persist_listbox_order(view, listbox)
        self._speak_drag(_("{}, {} of {}").format(moved[0], new_sel, count - 1))

    def _move_tree_item(self, view, tree, direction):
        """Ctrl+Up/Down move for a game in the tree (within its platform).
        Always returns True (handled)."""
        sel = tree.GetSelection()
        if not sel.IsOk():
            return True
        data = tree.GetItemData(sel)
        if not isinstance(data, dict) or data.get('type') != 'game':
            return True  # only games are movable (not platform or tab bar rows)
        parent = tree.GetItemParent(sel)
        if not parent.IsOk():
            return True
        siblings = []
        child, cookie = tree.GetFirstChild(parent)
        while child.IsOk():
            siblings.append((tree.GetItemText(child), tree.GetItemData(child)))
            child, cookie = tree.GetNextChild(parent, cookie)
        cur = next((i for i, (t, d) in enumerate(siblings) if d is data), -1)
        if cur < 0:
            return True
        new = cur + direction
        if new < 0 or new >= len(siblings):
            try:
                play_endoflist_sound()
            except Exception:
                pass
            return True
        siblings[cur], siblings[new] = siblings[new], siblings[cur]
        moved_item = self._rebuild_tree_children(tree, parent, siblings, data)
        if moved_item is not None:
            self._skip_focus_sound = True
            tree.SelectItem(moved_item)
            tree.SetFocus()
        try:
            play_sound('ui/drop.ogg')
        except Exception:
            pass
        vibrate_cursor_move()
        view2 = self._view_by_control(tree)
        if view2:
            self._persist_tree_order(view2, tree)
        game = data.get('data', {})
        self._speak_drag(_("{}, {} of {}").format(
            game.get('name', ''), new + 1, len(siblings)))
        return True

    def _rebuild_tree_children(self, tree, parent, siblings, moved_data):
        """Delete and re-create ``parent``'s children from the ``siblings`` list
        of ``(text, data)`` tuples. Returns the tree item whose data is
        ``moved_data`` (or None)."""
        tree.DeleteChildren(parent)
        moved_item = None
        for text, data in siblings:
            item = tree.AppendItem(parent, text)
            tree.SetItemData(item, data)
            if data is moved_data:
                moved_item = item
        tree.Expand(parent)
        return moved_item

    # --- Persistence helpers -------------------------------------------

    def _is_tab_bar_row_at(self, listbox, index):
        """True when ``index`` of ``listbox`` is the virtual tab bar row."""
        try:
            data = listbox.GetClientData(index)
            return isinstance(data, dict) and data.get('type') == 'tab_bar'
        except Exception:
            return False

    def _listbox_item_key(self, view_id, text, data):
        """Stable persistence key for a list box item.

        Apps use their ``shortname`` (survives renames/translations); every
        other list falls back to the visible text.
        """
        if view_id == 'apps' and isinstance(data, dict):
            shortname = data.get('shortname')
            if shortname:
                return f"app:{shortname}"
            path = data.get('path')
            if path:
                return f"app:{os.path.basename(path)}"
        return f"txt:{text}"

    def _game_order_key(self, platform, game):
        """Stable persistence key for a game (scoped to its platform)."""
        return f"game:{platform}/{game.get('name', '')}"

    def _apply_saved_order_to_listbox(self, view_id, listbox):
        """Reorder an already-populated list box to match the saved order in
        .index.TCG. Newly added items keep their default position at the end.
        Safe to call whether or not the tab bar row is present yet."""
        try:
            from src.titan_core import list_order
            saved = list_order.get_list_order(view_id)
            if not saved:
                return
            start = 1 if (listbox.GetCount() > 0 and self._is_tab_bar_row_at(listbox, 0)) else 0
            items = []
            for i in range(start, listbox.GetCount()):
                try:
                    data = listbox.GetClientData(i)
                except Exception:
                    data = None
                items.append((listbox.GetString(i), data))
            ordered = list_order.apply_order(
                saved, items,
                lambda it: self._listbox_item_key(view_id, it[0], it[1]))
            if ordered == items:
                return
            for i in range(listbox.GetCount() - 1, start - 1, -1):
                listbox.Delete(i)
            for text, data in ordered:
                if data is None:
                    listbox.Append(text)
                else:
                    listbox.Append(text, clientData=data)
        except Exception as e:
            print(f"[GUI] apply saved listbox order error: {e}")

    def _persist_listbox_order(self, view, listbox):
        """Save the current order of a list box (excluding the tab bar row)."""
        try:
            from src.titan_core import list_order
            keys = []
            for i in range(1, listbox.GetCount()):
                try:
                    data = listbox.GetClientData(i)
                except Exception:
                    data = None
                keys.append(self._listbox_item_key(view['id'], listbox.GetString(i), data))
            list_order.set_list_order(view['id'], keys)
        except Exception as e:
            print(f"[GUI] persist list order error: {e}")

    def _persist_tree_order(self, view, tree):
        """Save the current order of games in the tree (per platform)."""
        try:
            from src.titan_core import list_order
            keys = []
            root = tree.GetRootItem()
            if not root.IsOk():
                return
            plat, pcookie = tree.GetFirstChild(root)
            while plat.IsOk():
                pdata = tree.GetItemData(plat)
                if isinstance(pdata, dict) and pdata.get('type') == 'platform':
                    pname = pdata.get('name', '')
                    child, ccookie = tree.GetFirstChild(plat)
                    while child.IsOk():
                        cdata = tree.GetItemData(child)
                        if isinstance(cdata, dict) and cdata.get('type') == 'game':
                            keys.append(self._game_order_key(pname, cdata.get('data', {})))
                        child, ccookie = tree.GetNextChild(plat, ccookie)
                plat, pcookie = tree.GetNextChild(root, pcookie)
            list_order.set_list_order(view['id'], keys)
        except Exception as e:
            print(f"[GUI] persist tree order error: {e}")

    # --- Mouse drag-and-drop -------------------------------------------

    def _enable_listbox_dnd(self, listbox):
        """Bind the mouse handlers that let a list box item be dragged to a new
        position."""
        listbox.Bind(wx.EVT_LEFT_DOWN, lambda e, lb=listbox: self._on_listbox_left_down(e, lb))
        listbox.Bind(wx.EVT_MOTION, lambda e, lb=listbox: self._on_listbox_motion(e, lb))
        listbox.Bind(wx.EVT_LEFT_UP, lambda e, lb=listbox: self._on_listbox_left_up(e, lb))

    def _on_listbox_left_down(self, event, listbox):
        idx = listbox.HitTest(event.GetPosition())
        self._lb_drag = None
        # Index 0 is the virtual tab bar row and is not draggable.
        if idx != wx.NOT_FOUND and idx > 0:
            self._lb_drag = {
                'listbox': listbox, 'from': idx, 'active': False,
                'start': event.GetPosition(),
            }
        event.Skip()

    def _on_listbox_motion(self, event, listbox):
        drag = self._lb_drag
        if drag and drag['listbox'] is listbox and event.Dragging() and event.LeftIsDown():
            if not drag['active']:
                start = drag['start']
                now = event.GetPosition()
                if abs(now.y - start.y) >= 6:
                    drag['active'] = True
                    try:
                        play_sound('ui/drag.ogg')
                    except Exception:
                        pass
        event.Skip()

    def _on_listbox_left_up(self, event, listbox):
        drag = self._lb_drag
        self._lb_drag = None
        if not drag or drag['listbox'] is not listbox or not drag['active']:
            event.Skip()
            return
        target = listbox.HitTest(event.GetPosition())
        if target == wx.NOT_FOUND or target <= 0 or target == drag['from']:
            event.Skip()
            return
        # Consume the event (don't Skip) so the drop doesn't double as a click.
        self._move_listbox_item_to(listbox, drag['from'], target)

    def _enable_tree_dnd(self, tree):
        """Bind the mouse handlers that let a game be dragged to a new position
        within its platform."""
        tree.Bind(wx.EVT_TREE_BEGIN_DRAG, self._on_tree_begin_drag)
        tree.Bind(wx.EVT_TREE_END_DRAG, self._on_tree_end_drag)

    def _on_tree_begin_drag(self, event):
        tree = event.GetEventObject()
        item = event.GetItem()
        data = tree.GetItemData(item) if item.IsOk() else None
        if isinstance(data, dict) and data.get('type') == 'game':
            self._tree_drag_item = item
            event.Allow()
            try:
                play_sound('ui/drag.ogg')
            except Exception:
                pass
        else:
            self._tree_drag_item = None  # only games are draggable

    def _on_tree_end_drag(self, event):
        tree = event.GetEventObject()
        src = getattr(self, '_tree_drag_item', None)
        self._tree_drag_item = None
        if not src or not src.IsOk():
            return
        target = event.GetItem()
        if not target.IsOk():
            return
        self._reorder_tree_game(tree, src, target)

    def _reorder_tree_game(self, tree, src, target):
        """Move game ``src`` next to ``target`` (or into ``target`` if it is a
        platform node). Reordering only happens within a single platform."""
        src_data = tree.GetItemData(src)
        if not isinstance(src_data, dict) or src_data.get('type') != 'game':
            return
        tgt_data = tree.GetItemData(target)
        src_parent = tree.GetItemParent(src)
        if isinstance(tgt_data, dict) and tgt_data.get('type') == 'game':
            tgt_parent = tree.GetItemParent(target)
        elif isinstance(tgt_data, dict) and tgt_data.get('type') == 'platform':
            tgt_parent = target
        else:
            return
        if tgt_parent != src_parent:
            return  # don't move games between platforms
        siblings = []
        child, cookie = tree.GetFirstChild(src_parent)
        while child.IsOk():
            siblings.append((tree.GetItemText(child), tree.GetItemData(child)))
            child, cookie = tree.GetNextChild(src_parent, cookie)
        src_i = next((i for i, (t, d) in enumerate(siblings) if d is src_data), -1)
        if src_i < 0:
            return
        moved = siblings.pop(src_i)
        if isinstance(tgt_data, dict) and tgt_data.get('type') == 'game':
            tgt_i = next((i for i, (t, d) in enumerate(siblings) if d is tgt_data), len(siblings))
            siblings.insert(tgt_i, moved)
        else:
            siblings.append(moved)  # dropped on the platform node — go to the end
        moved_item = self._rebuild_tree_children(tree, src_parent, siblings, src_data)
        if moved_item is not None:
            self._skip_focus_sound = True
            tree.SelectItem(moved_item)
        try:
            play_sound('ui/drop.ogg')
        except Exception:
            pass
        vibrate_selection()
        view = self._view_by_control(tree)
        if view:
            self._persist_tree_order(view, tree)

    def _add_toolbar_tool(self, view):
        """Add a toolbar button for a registered view (built-in or component).

        Clicking the tool activates the corresponding view. Component views
        are rebuilt into the toolbar via register_view().
        """
        if not hasattr(self, 'toolbar') or self.toolbar is None:
            return
        if view['id'] in self._view_tools:
            return  # Already added

        empty_bitmap = wx.Bitmap(1, 1)
        label = self._view_short_name(view)
        help_text = _("Show {}").format(label)
        tool = self.toolbar.AddTool(wx.ID_ANY, label, empty_bitmap, shortHelp=help_text)
        self._view_tools[view['id']] = tool

        view_id = view['id']

        def _on_tool(evt, vid=view_id):
            self._show_view_by_id(vid)
            evt.Skip()

        self.Bind(wx.EVT_TOOL, _on_tool, tool)

        # Back-compat aliases for legacy skin-icon code paths
        if view['id'] == 'apps':
            self.tool_apps = tool
        elif view['id'] == 'games':
            self.tool_games = tool
        elif view['id'] == 'network':
            self.tool_network = tool

    def _show_view_by_id(self, view_id):
        """Activate a view (built-in or registered) by its id."""
        for view in self.registered_views:
            if view['id'] == view_id:
                if view.get('show_method'):
                    view['show_method']()
                else:
                    self._show_registered_view(view_id)
                return

    def _get_view_index(self, view_id):
        """Get the index of a view in registered_views by its id."""
        for i, view in enumerate(self.registered_views):
            if view['id'] == view_id:
                return i
        return -1

    def _focus_current_view_control(self):
        """Focus the control of the current view (used by Tab/Shift+Tab from statusbar)."""
        # Check registered views first (includes built-in)
        for view in self.registered_views:
            if view['id'] == self.current_list:
                view['control'].SetFocus()
                play_applist_sound()
                vibrate_focus_change()
                return
        # Fallback for sub-views (users, messages, contacts, etc.)
        if self.current_list == "users":
            self.users_listbox.SetFocus()
            play_applist_sound()
            vibrate_focus_change()
        elif self.current_list == "messages":
            self.message_input.SetFocus()
            play_applist_sound()
            vibrate_focus_change()
        elif self.current_list in ["contacts", "group_chats"]:
            self.users_listbox.SetFocus()
            play_applist_sound()
            vibrate_focus_change()

    def register_view(self, view_id, label, control, on_show=None, on_activate=None,
                      position='after_network', short_name=None):
        """Register a new view for the tab bar (built-in views + component views).

        Args:
            view_id: Unique string identifier (e.g., 'my_component')
            label: Display label for the view header (e.g., 'My List:')
            control: wx control (ListBox, TreeCtrl, etc.) parented to self.main_panel
            on_show: Optional callback called when view is shown
            on_activate: Optional callback for Enter key activation
            position: Where to insert - 'after_apps', 'after_games', 'after_network' (default), or int index
            short_name: Optional short label used for the tab bar and toolbar button
                (defaults to ``label`` with a trailing colon removed).
        """
        # Determine insertion index
        if isinstance(position, int):
            insert_idx = min(position, len(self.registered_views))
        elif position == 'after_apps':
            idx = self._get_view_index('apps')
            insert_idx = idx + 1 if idx >= 0 else len(self.registered_views)
        elif position == 'after_games':
            idx = self._get_view_index('games')
            insert_idx = idx + 1 if idx >= 0 else len(self.registered_views)
        elif position == 'after_network':
            idx = self._get_view_index('network')
            insert_idx = idx + 1 if idx >= 0 else len(self.registered_views)
        else:
            insert_idx = len(self.registered_views)

        view_entry = {
            'id': view_id,
            'label': label,
            'short_name': short_name or label.rstrip(':').strip(),
            'control': control,
            'show_method': None,
            'on_show': on_show,
            'on_activate': on_activate,
        }

        self.registered_views.insert(insert_idx, view_entry)

        # Add control to list_sizer (hidden)
        control.Hide()
        self.list_sizer.Insert(insert_idx, control, proportion=1, flag=wx.EXPAND | wx.ALL, border=0)

        # Inject the virtual tab bar row into the new control if supported
        if isinstance(control, wx.ListBox):
            self._inject_tab_bar_into_listbox(control)
        elif isinstance(control, wx.TreeCtrl):
            self._inject_tab_bar_into_tree(control)

        # Component code often calls ``control.Clear()`` / ``DeleteAllItems()``
        # to repopulate its list (macros, playlists, contact lists, ...).
        # Clearing wipes the virtual tab bar row together with the real data,
        # which is exactly what the user means by "additional views don't
        # behave like the normal ones" — built-in views always reinject the
        # row at the end of their populate_*() helpers, component views
        # usually don't. Bind EVT_SET_FOCUS (+ EVT_LISTBOX for list-box
        # controls) so we automatically re-inject whenever focus returns to
        # the view or selection changes, giving component code a "just works"
        # experience without requiring a manual sync call.
        try:
            control.Bind(wx.EVT_SET_FOCUS, lambda evt, c=control: self._auto_sync_tab_bar_on_focus(evt, c))
        except Exception as e:
            print(f"[GUI] Could not bind focus handler for view '{view_id}': {e}")
        if isinstance(control, wx.ListBox):
            try:
                control.Bind(wx.EVT_LISTBOX, lambda evt, c=control: self._auto_sync_tab_bar_on_select(evt, c))
            except Exception as e:
                print(f"[GUI] Could not bind listbox handler for view '{view_id}': {e}")

        # Enable drag-and-drop reordering (Ctrl+Up/Down + mouse) for the
        # component's control, same as the built-in views.
        try:
            if isinstance(control, wx.ListBox):
                self._enable_listbox_dnd(control)
            elif isinstance(control, wx.TreeCtrl):
                self._enable_tree_dnd(control)
        except Exception as e:
            print(f"[GUI] Could not enable drag-and-drop for view '{view_id}': {e}")

        # Honor the user's saved tab bar card order: a component reordered in a
        # previous session should re-appear in its saved slot, not its default
        # registration position.
        self._apply_saved_tab_bar_order()

        # Rebuild the toolbar so its buttons match the (possibly reordered)
        # view list — this also adds the button for the new component view.
        try:
            self._rebuild_view_toolbar()
        except Exception as e:
            print(f"[GUI] Error adding toolbar button for view '{view_id}': {e}")

        # Rebuild the Switch-to menu so the new view appears
        menubar = self.GetMenuBar()
        if menubar and hasattr(menubar, 'rebuild_switch_menu'):
            menubar.rebuild_switch_menu()

        # Refresh tab bar text in every view (totals changed)
        self._refresh_all_tab_bar_items()

        print(f"[GUI] Registered view '{view_id}' at position {insert_idx} (total views: {len(self.registered_views)})")

    def _auto_sync_tab_bar_on_focus(self, event, control):
        """Re-inject the virtual tab bar row whenever focus lands on a
        registered view's control. This fixes the case where component code
        cleared the list while the view was focused and never re-added the
        tab bar row itself."""
        try:
            if isinstance(control, wx.ListBox):
                self._inject_tab_bar_into_listbox(control)
            elif isinstance(control, wx.TreeCtrl):
                self._inject_tab_bar_into_tree(control)
        except Exception as e:
            print(f"[GUI] auto-sync tab bar on focus error: {e}")
        event.Skip()

    def _auto_sync_tab_bar_on_select(self, event, control):
        """Same intent as ``_auto_sync_tab_bar_on_focus`` but triggered on
        selection change for wx.ListBox controls, which also covers the case
        where the component repopulates its list while the user is navigating
        it."""
        try:
            if isinstance(control, wx.ListBox):
                self._inject_tab_bar_into_listbox(control)
        except Exception as e:
            print(f"[GUI] auto-sync tab bar on select error: {e}")
        event.Skip()

    def sync_view_tab_bar(self, view_id_or_control):
        """Public API for components: ensure the virtual tab bar row is
        present on a registered view's control.

        Components should call this after clearing and repopulating their
        list/tree (``listbox.Clear()`` + ``Append()``, ``tree.DeleteAllItems()``
        + rebuild). The call is safe to make at any time — it's a no-op if
        the row is already there.

        Args:
            view_id_or_control: either the ``view_id`` passed to
                ``register_view`` or the raw control instance.
        """
        try:
            control = None
            if isinstance(view_id_or_control, str):
                idx = self._get_view_index(view_id_or_control)
                if idx >= 0:
                    control = self.registered_views[idx].get('control')
            else:
                control = view_id_or_control
            if control is None:
                return
            if isinstance(control, wx.ListBox):
                self._inject_tab_bar_into_listbox(control)
            elif isinstance(control, wx.TreeCtrl):
                self._inject_tab_bar_into_tree(control)
        except Exception as e:
            print(f"[GUI] sync_view_tab_bar error: {e}")

    def _show_registered_view(self, view_id, focus_list=True):
        """Show a registered component view by its id."""
        view_idx = self._get_view_index(view_id)
        if view_idx < 0:
            return

        view = self.registered_views[view_idx]
        self._hide_all_views()
        view['control'].Show()
        self._apply_list_label_for_sr(view['label'])
        self.current_list = view['id']

        total = len(self.registered_views)

        # Inject/refresh the tab bar row for this component's control if it's a
        # supported type. Non-list controls are shown as-is.
        ctrl = view['control']
        if isinstance(ctrl, wx.ListBox):
            self._inject_tab_bar_into_listbox(ctrl)
        elif isinstance(ctrl, wx.TreeCtrl):
            self._inject_tab_bar_into_tree(ctrl)

        if focus_list:
            vibrate_menu_open()

        # Call on_show callback if provided
        if view.get('on_show') and callable(view['on_show']):
            try:
                view['on_show']()
            except Exception as e:
                print(f"[GUI] Error in on_show for view '{view_id}': {e}")

        # Components commonly repopulate their list inside on_show — re-inject
        # the tab bar row so it survives a Clear() inside that callback.
        if isinstance(ctrl, wx.ListBox):
            self._inject_tab_bar_into_listbox(ctrl)
        elif isinstance(ctrl, wx.TreeCtrl):
            self._inject_tab_bar_into_tree(ctrl)

        self.Layout()

        # Land on the tab bar row so Left/Right immediately cycles views and
        # the screen reader reads only the plain "Name, N of M" row text. The
        # user explicitly asked that component views NOT auto-jump to the
        # first real list item on switch, so they can keep switching views
        # without first having to arrow back up to the tab bar.
        if focus_list:
            self._with_tab_bar_nav_speech_suppressed()
            try:
                if isinstance(ctrl, wx.ListBox) and ctrl.GetCount() > 0:
                    ctrl.SetSelection(0)
                    ctrl.SetFocus()
                elif isinstance(ctrl, wx.TreeCtrl):
                    root = ctrl.GetRootItem()
                    if root.IsOk():
                        first, _c = ctrl.GetFirstChild(root)
                        if first.IsOk():
                            ctrl.SelectItem(first)
                    ctrl.SetFocus()
                else:
                    ctrl.SetFocus()
            except Exception:
                pass

    def populate_network_options(self):
        self.network_listbox.Clear()
        self.network_listbox.Append(_("Telegram"))
        self.network_listbox.Append(_("Facebook Messenger"))
        self.network_listbox.Append(_("WhatsApp"))
        self.network_listbox.Append(_("Titan-Net (Beta)"))
        self.network_listbox.Append(_("EltenLink (Beta)"))
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
            elif "Titan-Net" in selected_text:
                if self.titan_logged_in and self.titan_client.is_connected:
                    # Already logged in and connected - show Titan-Net main window
                    self.show_titannet_main()
                else:
                    # Not logged in or disconnected - show login dialog
                    if self.titan_logged_in and not self.titan_client.is_connected:
                        # Was logged in but disconnected - reset state
                        self.titan_logged_in = False
                    self.show_titannet_login()
            elif "EltenLink" in selected_text:
                # Check if already connected and window exists (may be hidden)
                if "eltenlink" in self.active_services:
                    service = self.active_services["eltenlink"]
                    window = service.get("window")
                    if window and window.client and window.client.is_connected:
                        window.Show()
                        window.Raise()
                        register_window("EltenLink", window=window, category='messenger')
                        return
                # Not connected - show login dialog
                self.show_elten_login()
            else:
                try:
                    from src.network.im_module_manager import im_module_manager
                    for info in im_module_manager.modules:
                        if info['name'] in selected_text:
                            im_module_manager.open_module(info['id'], self)
                            return
                except Exception as _e:
                    print(f"[GUI] IM module open: {_e}")
        
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
        """Show Telegram login using telegram_gui.py"""
        try:
            from src.network.telegram_gui import show_telegram_login

            print("[GUI] Opening Telegram login from telegram_gui.py")

            # Open Telegram login dialog
            chat_window = show_telegram_login(self)

            if chat_window:
                # Successfully logged in and opened chat window
                speaker.speak(_("Logged in to Telegram"))
                # Sound is played by telegram_gui.py window
                register_window("Telegram", window=chat_window, category='messenger')

                # Store in active services
                self.active_services["telegram"] = {
                    "client": telegram_client.telegram_client,
                    "type": "telegram",
                    "name": "Telegram",
                    "window": chat_window,
                    "online_users": [],
                    "unread_messages": {}
                }

                # Legacy compatibility
                self.telegram_client = telegram_client.telegram_client
                self.logged_in = True

                print("[GUI] Telegram login successful")
            else:
                speaker.speak(_("Login cancelled"))
                print("[GUI] Telegram login cancelled")

        except Exception as e:
            print(f"[GUI] Error loading Telegram: {e}")
            import traceback
            traceback.print_exc()
            _show_skinned_message(
                _("Cannot launch Telegram.\nError: {error}").format(error=str(e)),
                _("Telegram Error"),
                wx.OK | wx.ICON_ERROR
            )
        
    def show_messenger_login(self):
        """Show Facebook Messenger WebView interface"""
        try:
            messenger_window = messenger_webview.show_messenger_webview(self)
            if messenger_window:
                register_window("Messenger", window=messenger_window, category='messenger')
                # Add Messenger to active services when successfully connected
                # This will be handled by callback from messenger_window
                self.setup_messenger_callbacks(messenger_window)
        except Exception as e:
            print(f"WebView Messenger error: {e}")
            _show_skinned_message(
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
                register_window("WhatsApp", window=whatsapp_window, category='messenger')
                # Add WhatsApp to active services when successfully connected
                # This will be handled by callback from whatsapp_window
                self.setup_whatsapp_callbacks(whatsapp_window)
        except Exception as e:
            print(f"WebView WhatsApp error: {e}")
            # Only show MessageBox if we have a running wx.App
            if wx.GetApp():
                _show_skinned_message(
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

    def show_titannet_login(self):
        """Show Titan-Net login dialog"""
        try:
            from src.network.titan_net_gui import show_login_dialog, MOTDDialog

            logged_in, offline_mode, motd = show_login_dialog(self, self.titan_client)

            if logged_in:
                self.titan_logged_in = True
                self.titan_username = self.titan_client.username

                # Keep the shared Titan-Net registry in sync so IUI /
                # Klango / launcher frontends see the "logged in" state.
                try:
                    from src.network.titan_net import set_active_titan_logged_in
                    set_active_titan_logged_in(True)
                except Exception:
                    pass

                # Setup callbacks
                self.setup_titannet_callbacks()

                # Play welcome sound first, then open window
                play_sound('titannet/welcome to IM.ogg')
                speaker.speak(_("Logged in to Titan-Net as {username}").format(
                    username=self.titan_username
                ))

                # Show MOTD if new/updated (after 2s delay)
                if motd and motd.get('text'):
                    from src.settings.settings import get_setting, set_setting
                    last_motd_hash = get_setting('motd_hash', '', section='titannet')
                    current_hash = motd.get('hash', '')
                    if current_hash != last_motd_hash:
                        set_setting('motd_hash', current_hash, section='titannet')
                        def _show_motd(text=motd['text']):
                            dlg = MOTDDialog(self, text)
                            dlg.ShowModal()
                            dlg.Destroy()
                        wx.CallLater(5000, _show_motd)

                # Show main window after welcome
                self.show_titannet_main()

            elif offline_mode:
                speaker.speak(_("Continuing in offline mode"))
            else:
                speaker.speak(_("Login cancelled"))

        except Exception as e:
            print(f"Error loading Titan-Net login dialog: {e}")
            import traceback
            traceback.print_exc()
            _show_skinned_message(
                _("Cannot launch Titan-Net.\nError: {error}").format(error=str(e)),
                _("Titan-Net Error"),
                wx.OK | wx.ICON_ERROR
            )

    def show_titannet_main(self):
        """Show Titan-Net main window"""
        try:
            from src.network.titan_net_gui import show_titan_net_window

            if not self.titan_client.is_connected:
                speaker.speak(_("Not connected to Titan-Net"))
                play_sound('core/error.ogg')
                return

            titan_win = show_titan_net_window(self, self.titan_client)
            if titan_win:
                register_window("Titan-Net", window=titan_win, category='messenger')

        except Exception as e:
            print(f"Error opening Titan-Net window: {e}")
            import traceback
            traceback.print_exc()
            _show_skinned_message(
                _("Cannot open Titan-Net window.\nError: {error}").format(error=str(e)),
                _("Titan-Net Error"),
                wx.OK | wx.ICON_ERROR
            )

    def setup_titannet_callbacks(self):
        """Setup callbacks for Titan-Net integration"""
        import tempfile, threading
        from src.titan_core.sound import play_sound_file

        # Business card sound cache: {username: {sound_type: local_path}}
        self._business_card_cache = {}
        self._business_card_cache_dir = os.path.join(tempfile.gettempdir(), 'titan_business_cards')
        os.makedirs(self._business_card_cache_dir, exist_ok=True)

        def _download_and_cache_sound(username, sound_type):
            """Download a user's business card sound and cache it locally."""
            cached = self._business_card_cache.get(username, {}).get(sound_type)
            if cached and os.path.exists(cached):
                return cached
            try:
                result = self.titan_client.download_user_sound(username, sound_type)
                if result.get('success') and result.get('file_data'):
                    content_type = result.get('content_type', '')
                    if 'ogg' in content_type:
                        ext = '.ogg'
                    elif 'mp3' in content_type:
                        ext = '.mp3'
                    else:
                        ext = '.wav'
                    user_cache_dir = os.path.join(self._business_card_cache_dir, username)
                    os.makedirs(user_cache_dir, exist_ok=True)
                    local_path = os.path.join(user_cache_dir, f"{sound_type}{ext}")
                    with open(local_path, 'wb') as f:
                        f.write(result['file_data'])
                    if username not in self._business_card_cache:
                        self._business_card_cache[username] = {}
                    self._business_card_cache[username][sound_type] = local_path
                    return local_path
            except Exception as e:
                print(f"[TITAN-NET] Failed to download business card sound {sound_type} for {username}: {e}")
            return None

        def _get_local_business_card_sound(sound_type):
            """Get local business card sound path for the current user from settings."""
            try:
                from src.settings.titan_im_config import load_titan_im_config
                config = load_titan_im_config()
                tn = config.get('titannet_settings', {})
                if not tn.get('business_card_enabled', False):
                    return None
                path_key = f"{sound_type}_sound_path"
                path = tn.get(path_key, '')
                if path and os.path.exists(path):
                    return path
            except Exception:
                pass
            return None

        def _play_custom_or_default(username, sound_type, fallback, has_custom_sounds):
            """Play custom business card sound if available, otherwise default."""
            print(f"[BUSINESS-CARD] _play_custom_or_default: user={username}, type={sound_type}, has_custom={has_custom_sounds}")
            if has_custom_sounds:
                def download_and_play():
                    local_path = _download_and_cache_sound(username, sound_type)
                    print(f"[BUSINESS-CARD] Downloaded sound for {username}/{sound_type}: {local_path}")
                    if local_path:
                        play_sound_file(local_path)
                    else:
                        play_sound(fallback)
                threading.Thread(target=download_and_play, daemon=True).start()
            else:
                play_sound(fallback)

        def _play_self_or_default(sound_type, fallback):
            """Play local business card sound for the current user, or default."""
            local_path = _get_local_business_card_sound(sound_type)
            print(f"[BUSINESS-CARD] _play_self_or_default: type={sound_type}, local_path={local_path}")
            if local_path:
                play_sound_file(local_path)
            else:
                play_sound(fallback)

        def on_user_online(username, has_custom_sounds=False):
            print(f"[BUSINESS-CARD] on_user_online: {username}, has_custom={has_custom_sounds}, self_user={self.titan_client.username}")
            wx.CallAfter(speaker.speak, _("{user} is now online").format(user=username))
            # For the current user, use local sound files from settings
            if self.titan_client.username and username == self.titan_client.username:
                wx.CallAfter(_play_self_or_default, 'login', 'titannet/online.ogg')
            else:
                wx.CallAfter(_play_custom_or_default, username, 'login', 'titannet/online.ogg', has_custom_sounds)

        def on_user_offline(username, has_custom_sounds=False):
            print(f"[BUSINESS-CARD] on_user_offline: {username}, has_custom={has_custom_sounds}, self_user={self.titan_client.username}")
            wx.CallAfter(speaker.speak, _("{user} went offline").format(user=username))
            # For the current user, use local sound files from settings
            if self.titan_client.username and username == self.titan_client.username:
                wx.CallAfter(_play_self_or_default, 'logout', 'titannet/offline.ogg')
            else:
                wx.CallAfter(_play_custom_or_default, username, 'logout', 'titannet/offline.ogg', has_custom_sounds)

        def on_message_received(message):
            sender = message.get('sender_username')
            has_custom = message.get('has_custom_sounds', False)
            wx.CallAfter(speaker.speak, _("New message from {user}").format(user=sender))
            wx.CallAfter(_play_custom_or_default, sender, 'new_message', 'titannet/new_message.ogg', has_custom)

        def on_new_user_broadcast(message):
            """Handle new user registration broadcast"""
            from src.settings.settings import get_setting

            # Get broadcast message details
            broadcast_lang = message.get('language', 'en')
            broadcast_text = message.get('message', '')

            # Get current user's language
            current_lang = get_setting('language', 'en')

            # Only show broadcast if it matches user's language
            if broadcast_lang == current_lang and broadcast_text:
                wx.CallAfter(speaker.speak, broadcast_text)
                wx.CallAfter(play_sound, 'titannet/accountcreated.ogg')

        def on_cerberus_shutdown(message):
            """Cerberus Protocol - server detected intrusion from this client"""
            reason = message.get('reason', 'Intrusion detected')
            threat = message.get('threat_level', 'CERBERUS')
            import sys
            import subprocess

            def _do_cerberus_shutdown():
                # Play critical alarm sound
                play_sound('titannet/cerberus/critical.ogg')
                # Announce via TTS
                speaker.speak(
                    _("Cerberus Protocol activated. Security threat level: {level}. "
                      "Reason: {reason}. Your system will shut down in 10 seconds.").format(
                        level=threat, reason=reason
                    )
                )
                # Show dialog
                _show_skinned_message(
                    _("Cerberus Protocol: {level}\n\n"
                      "The server has detected a security violation from your connection.\n"
                      "Reason: {reason}\n\n"
                      "Your system will shut down.").format(level=threat, reason=reason),
                    _("Cerberus Protocol"),
                    wx.OK | wx.ICON_ERROR
                )
                # Shutdown the system
                if sys.platform == 'win32':
                    subprocess.Popen(
                        ['shutdown', '/s', '/f', '/t', '10',
                         '/c', f'Cerberus Protocol: {reason}'],
                        creationflags=0x08000000
                    )
                elif sys.platform == 'darwin':
                    subprocess.Popen(['osascript', '-e',
                        'tell app "System Events" to shut down'])
                else:
                    subprocess.Popen(['shutdown', '-h', '+0',
                        f'Cerberus Protocol: {reason}'])

            wx.CallAfter(_do_cerberus_shutdown)

        def on_cerberus_alert(message):
            """Cerberus security alert for admin users"""
            msg = message.get('message', '')
            threat_name = message.get('threat_name', 'ALERT')

            # Pick sound based on threat level
            # alert.ogg = ALERT, lockdown.ogg = LOCKDOWN, critical.ogg = CERBERUS
            # jail or ssh scam.ogg = honeypot triggered
            cerberus_sounds = {
                'ALERT': 'titannet/cerberus/alert.ogg',
                'LOCKDOWN': 'titannet/cerberus/lockdown.ogg',
                'CERBERUS': 'titannet/cerberus/critical.ogg',
            }
            sound = cerberus_sounds.get(threat_name, 'titannet/cerberus/alert.ogg')

            # Check if it's a honeypot trigger
            if 'honeypot' in msg.lower() or 'ssh' in msg.lower():
                sound = 'titannet/cerberus/jail or ssh scam.ogg'

            def _show_alert():
                play_sound(sound)
                speaker.speak(
                    _("Cerberus security alert: {level}. {message}").format(
                        level=threat_name, message=msg
                    )
                )

            wx.CallAfter(_show_alert)

        self.titan_client.on_user_online = on_user_online
        self.titan_client.on_user_offline = on_user_offline
        self.titan_client.on_message_received = on_message_received
        self.titan_client.on_new_user_broadcast = on_new_user_broadcast
        self.titan_client.on_cerberus_shutdown = on_cerberus_shutdown
        self.titan_client.on_cerberus_alert = on_cerberus_alert

    def show_elten_login(self):
        """Show EltenLink login dialog"""
        try:
            from src.eltenlink_client.elten_gui import show_elten_login

            chat_window = show_elten_login(self)

            if chat_window:
                # Store in active services
                self.active_services["eltenlink"] = {
                    "client": chat_window.client,
                    "type": "eltenlink",
                    "name": "EltenLink (Beta)",
                    "window": chat_window
                }
                register_window("EltenLink", window=chat_window, category='messenger')

                # Setup callbacks
                self.setup_elten_callbacks()

                speaker.speak(_("Connected to EltenLink (Beta)"))
                play_sound('titannet/welcome to IM.ogg')
            else:
                speaker.speak(_("Login cancelled"))

        except Exception as e:
            print(f"Error loading EltenLink (Beta) login dialog: {e}")
            import traceback
            traceback.print_exc()
            _show_skinned_message(
                _("Cannot open EltenLink (Beta).\nError: {error}").format(error=str(e)),
                _("EltenLink (Beta) Error"),
                wx.OK | wx.ICON_ERROR
            )

    def setup_elten_callbacks(self):
        """Setup callbacks for EltenLink integration"""
        if "eltenlink" not in self.active_services:
            return

        client = self.active_services["eltenlink"]["client"]

        def on_message(message):
            sender = message.get('sender', 'Unknown')
            wx.CallAfter(speaker.speak, _("New message from {user}").format(user=sender))
            wx.CallAfter(play_sound, 'titannet/new_chat.ogg')

        def on_user_online(username):
            wx.CallAfter(speaker.speak, _("{user} is now online").format(user=username))
            wx.CallAfter(play_sound, 'system/user_online.ogg')

        def on_user_offline(username):
            wx.CallAfter(speaker.speak, _("{user} went offline").format(user=username))
            wx.CallAfter(play_sound, 'system/user_offline.ogg')

        client.on_message_received = on_message
        client.on_user_online = on_user_online
        client.on_user_offline = on_user_offline

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
                register_window("Messenger", window=messenger_window, category='messenger')
                self.setup_messenger_callbacks(messenger_window)
                _show_skinned_message(
                    _("Messenger WebView opened.\nPlease log in to see your contacts in Titan IM."),
                    _("Messenger WebView"),
                    wx.OK | wx.ICON_INFORMATION
                )
        except Exception as e:
            print(f"Error opening Messenger WebView: {e}")
            _show_skinned_message(
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

    #     _show_skinned_message(info_text, _("Titan-Net Information"), wx.OK | wx.ICON_INFORMATION)

    # DISABLED - Titan-Net callback methods
    def _on_titannet_message(self, message):
        """Handle incoming Titan-Net private message"""
        try:
            from src.titan_core.stereo_speech import speak_stereo

            sender_username = message.get('sender_username', 'Unknown')
            message_text = message.get('message', '')

            print(f"[TITAN-NET] Received message from {sender_username}: {message_text[:50]}")

            # Play notification sound
            play_sound('titannet/new_message.ogg')

            # TTS notification with stereo positioning (center)
            notification_text = _("New Titan-Net message from {user}").format(user=sender_username)
            speak_stereo(notification_text, pan=0.0, pitch=0)

            # Update unread messages count
            if "titannet" in self.active_services:
                sender_id = message.get('sender_id')
                if sender_id:
                    if 'unread_messages' not in self.active_services["titannet"]:
                        self.active_services["titannet"]['unread_messages'] = {}

                    if sender_id not in self.active_services["titannet"]['unread_messages']:
                        self.active_services["titannet"]['unread_messages'][sender_id] = 0

                    self.active_services["titannet"]['unread_messages'][sender_id] += 1
                    print(f"[TITAN-NET] Unread messages from {sender_username}: {self.active_services['titannet']['unread_messages'][sender_id]}")

        except Exception as e:
            print(f"[TITAN-NET] Error handling message: {e}")

    def _on_titannet_user_online(self, username):
        """Handle Titan-Net user coming online"""
        try:
            from src.titan_core.stereo_speech import speak_stereo

            print(f"[TITAN-NET] User online: {username}")

            # Play user online sound
            play_sound('titannet/online.ogg')

            # TTS notification with stereo positioning (left side)
            notification_text = _("{user} is now online").format(user=username)
            speak_stereo(notification_text, pan=-0.3, pitch=-2)

            # Update online users list
            if "titannet" in self.active_services:
                if 'online_users' not in self.active_services["titannet"]:
                    self.active_services["titannet"]['online_users'] = []

                if username not in self.active_services["titannet"]['online_users']:
                    self.active_services["titannet"]['online_users'].append(username)

        except Exception as e:
            print(f"[TITAN-NET] Error handling user online: {e}")

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
        """Show Telegram window"""
        try:
            # Check if window already exists
            if "telegram" in self.active_services and "window" in self.active_services["telegram"]:
                window = self.active_services["telegram"]["window"]
                if window and not window.IsBeingDeleted():
                    window.Show()
                    window.Raise()
                    register_window("Telegram", window=window, category='messenger')
                    speaker.speak(_("Opening Telegram"))
                    play_sound('ui/window_open.ogg')
                    return

            # No existing window - create new one
            from src.network.telegram_gui import TelegramChatWindow
            from src.network.telegram_client import get_user_data

            user_data = get_user_data()
            username = user_data.get('username') or user_data.get('first_name', 'User')

            chat_window = TelegramChatWindow(self, username)
            chat_window.Show()
            register_window("Telegram", window=chat_window, category='messenger')

            # Store window reference
            if "telegram" in self.active_services:
                self.active_services["telegram"]["window"] = chat_window

            speaker.speak(_("Opening Telegram"))
            play_sound('ui/window_open.ogg')

        except Exception as e:
            print(f"[GUI] Error opening Telegram: {e}")
            import traceback
            traceback.print_exc()
            _show_skinned_message(
                _("Cannot open Telegram.\nError: {error}").format(error=str(e)),
                _("Telegram Error"),
                wx.OK | wx.ICON_ERROR
            )

    def _old_show_telegram_options(self):
        """OLD: Show Telegram service options (Contacts, Groups, Settings, Logout)"""
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
                
            _show_skinned_message(
                _("Successfully logged out from {}.").format(service["name"]), 
                _("Logout"), 
                wx.OK | wx.ICON_INFORMATION
            )
            
        except Exception as e:
            print(f"Error logging out from {service_name}: {e}")
            _show_skinned_message(
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
            _show_skinned_message(_("Enter phone number with country code (e.g. +48123456789)."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        play_sound('system/connecting.ogg')
        # For Telegram, use phone number and optional 2FA password
        phone_number = username  # Phone number with country code
        twofa_password = password if password else None  # Optional 2FA password
        
        result = telegram_client.login(phone_number, twofa_password)
        if result.get("status") == "success":
            # Use TTS to announce connection attempt
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
                _show_skinned_message(_("Failed to connect to Telegram server."), _("Connection Error"), wx.OK | wx.ICON_ERROR)
                return
            
            # Update UI
            self.populate_network_list()
            self.show_network_list()
            if hasattr(self, 'logout_button'):
                self.logout_button.Show()
            
            # Wait a bit for connection and then refresh users
            wx.CallLater(1000, self.refresh_online_users)
        else:
            _show_skinned_message(result.get("message"), _("Error"), wx.OK | wx.ICON_ERROR)

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
            self.network_listbox.Append(_("Titan-Net (Beta)"))
            self.network_listbox.Append(_("EltenLink (Beta)"))
            try:
                from src.network.im_module_manager import im_module_manager
                for info in im_module_manager.modules:
                    item = info['name']
                    status = im_module_manager.get_status_text(info['id'])
                    if status:
                        item = f"{item} {status}"
                    self.network_listbox.Append(item)
            except Exception as _e:
                print(f"[GUI] IM modules: {_e}")
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

            # Titan-Net (Beta)
            if self.titan_logged_in and self.titan_username:
                self.network_listbox.Append(_("Titan-Net (Beta) - connected as {}").format(self.titan_username))
            else:
                self.network_listbox.Append(_("Titan-Net (Beta)"))

            if "eltenlink" in self.active_services:
                eltenlink_service = self.active_services["eltenlink"]
                username = "user"
                try:
                    if "client" in eltenlink_service and hasattr(eltenlink_service["client"], "username"):
                        username = eltenlink_service["client"].username
                except:
                    pass
                self.network_listbox.Append(_("EltenLink (Beta) - connected as {}").format(username))
            else:
                self.network_listbox.Append(_("EltenLink (Beta)"))

            try:
                from src.network.im_module_manager import im_module_manager
                for info in im_module_manager.modules:
                    item = info['name']
                    status = im_module_manager.get_status_text(info['id'])
                    if status:
                        item = f"{item} {status}"
                    self.network_listbox.Append(item)
            except Exception as _e:
                print(f"[GUI] IM modules: {_e}")

        # Restore the user's saved drag-and-drop order, then prepend the
        # virtual tab bar row as the first item.
        self._apply_saved_order_to_listbox('network', self.network_listbox)
        self._inject_tab_bar_into_listbox(self.network_listbox)

    def on_toggle_list(self):
        """Legacy entry point — now focuses the virtual tab bar."""
        self.focus_tab_bar()

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

    def on_show_window_switcher(self, event):
        show_window_switcher(self)

    def _register_global_f2_hotkey(self):
        """Register F4 as a global hotkey so it works from TCE app windows too."""
        self._f4_hotkey_handle = None
        try:
            if IS_WINDOWS:
                try:
                    import keyboard as kb_module
                    def _on_global_f4(event):
                        # Only bare F4 - skip Alt+F4, Ctrl+F4, Shift+F4
                        if event.event_type == 'down' and not any([
                            kb_module.is_pressed('alt'),
                            kb_module.is_pressed('ctrl'),
                            kb_module.is_pressed('shift'),
                        ]):
                            wx.CallAfter(self._global_f4_handler)
                    self._f4_hotkey_handle = kb_module.on_press_key('f4', _on_global_f4, suppress=False)
                except ImportError:
                    print("[GUI] keyboard module not available for global F4 hotkey")
            else:
                try:
                    from pynput import keyboard as _pynput_kb
                    from pynput.keyboard import Key
                    def _on_pynput_f4(key):
                        if key == Key.f4:
                            wx.CallAfter(self._global_f4_handler)
                    self._f4_pynput_listener = _pynput_kb.Listener(on_press=_on_pynput_f4)
                    self._f4_pynput_listener.daemon = True
                    self._f4_pynput_listener.start()
                except ImportError:
                    print("[GUI] pynput not available for global F4 hotkey")
        except Exception as e:
            print(f"[GUI] Error registering global F4 hotkey: {e}")

    def _is_foreground_tce_process(self):
        """Check if the current foreground window belongs to TCE (main or child process)."""
        if IS_WINDOWS:
            try:
                import win32gui
                import win32process
                import psutil
                hwnd = win32gui.GetForegroundWindow()
                if not hwnd:
                    return False
                _, fg_pid = win32process.GetWindowThreadProcessId(hwnd)
                main_pid = os.getpid()
                if fg_pid == main_pid:
                    return True
                tce_pids = {main_pid}
                try:
                    for child in psutil.Process(main_pid).children(recursive=True):
                        tce_pids.add(child.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                return fg_pid in tce_pids
            except Exception as e:
                print(f"[GUI] Error checking foreground process: {e}")
                return False
        # On non-Windows, allow — no reliable cross-platform foreground check
        return True

    def _global_f4_handler(self):
        """Handle global F4 - show window switcher only when a TCE window is focused."""
        try:
            if not self._is_foreground_tce_process():
                return
            show_window_switcher(parent=None)
        except Exception as e:
            print(f"[GUI] Error in global F4 handler: {e}")

    def _unregister_global_f2_hotkey(self):
        """Cleanup global F4 hotkey on exit."""
        try:
            if IS_WINDOWS and self._f4_hotkey_handle is not None:
                import keyboard as kb_module
                kb_module.unhook(self._f4_hotkey_handle)
                self._f4_hotkey_handle = None
            if hasattr(self, '_f4_pynput_listener') and self._f4_pynput_listener:
                self._f4_pynput_listener.stop()
                self._f4_pynput_listener = None
        except Exception as e:
            print(f"[GUI] Error unregistering global F4 hotkey: {e}")

    def on_minimize(self, event):
        if self.IsIconized():
            try:
                from src.settings.settings import get_setting
                action = get_setting('minimize_action', 'invisible_ui', section='general')
            except Exception:
                action = 'invisible_ui'
            if action == 'invisible_ui':
                self.minimize_to_tray(activate_invisible_ui=True)
            elif action == 'tray':
                self.minimize_to_tray(activate_invisible_ui=False)
            # 'nothing' → leave the window iconized, take no extra action
        event.Skip()

    def open_time_settings(self):
        if IS_WINDOWS:
            subprocess.run(["control", "timedate.cpl"])
        elif IS_LINUX:
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
                        subprocess.Popen(app_cmd, stderr=subprocess.DEVNULL)
                        break
                    except FileNotFoundError:
                        continue
                else:
                    # If all GUI options fail, show timedatectl info
                    try:
                        result = subprocess.run(["timedatectl", "status"], 
                                               capture_output=True, text=True, check=True)
                        _show_skinned_message(_("Current time settings:\n\n{}").format(result.stdout), 
                                     _("Time Settings"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        _show_skinned_message(_("Could not open time settings. Please use your system's settings application."), 
                                     _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                _show_skinned_message(_("Could not open date/time settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif IS_MACOS:
            try:
                subprocess.Popen(["open", "/System/Library/PreferencePanes/DateAndTime.prefPane"])
            except Exception as e:
                 _show_skinned_message(_("Could not open date/time settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            _show_skinned_message(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)

    def open_power_settings(self):
        if IS_WINDOWS:
            try:
                subprocess.Popen(["control", "powercfg.cpl"])
            except Exception as e:
                 _show_skinned_message(_("Could not open power settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif IS_LINUX:
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
                        subprocess.Popen(app_cmd, stderr=subprocess.DEVNULL)
                        break
                    except FileNotFoundError:
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
                            _show_skinned_message(_(info_text), _("Power Information"), wx.OK | wx.ICON_INFORMATION)
                        else:
                            _show_skinned_message(_("No battery detected. Power settings may not be available."), 
                                         _("Power Information"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        _show_skinned_message(_("Could not open power settings. Please use your system's settings application."), 
                                     _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                _show_skinned_message(_("Could not open power settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif IS_MACOS:
            try:
                subprocess.Popen(["open", "/System/Library/PreferencePanes/EnergySaver.prefPane"])
            except Exception as e:
                 _show_skinned_message(_("Could not open power settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            _show_skinned_message(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)

    def open_volume_mixer(self):
        if IS_WINDOWS:
            try:
                subprocess.Popen(["sndvol.exe"])
            except Exception as e:
                 _show_skinned_message(_("Could not open volume mixer:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif IS_LINUX:
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
                        subprocess.Popen(app_cmd, stderr=subprocess.DEVNULL)
                        break
                    except FileNotFoundError:
                        continue
                else:
                    # If all GUI options fail, try terminal-based mixer
                    try:
                        # Check if alsamixer is available
                        subprocess.run(["which", "alsamixer"], check=True, 
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        _show_skinned_message(_("GUI volume mixer not found.\n\nYou can use 'alsamixer' in terminal for audio control."), 
                                     _("Volume Control"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        _show_skinned_message(_("Could not find audio mixer. Please install 'pavucontrol' or 'alsamixer'."), 
                                     _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                _show_skinned_message(_("Could not open volume mixer:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif IS_MACOS:
            try:
                subprocess.Popen(["open", "/Applications/Utilities/Audio MIDI Setup.app"])
            except Exception as e:
                 _show_skinned_message(_("Could not open audio settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            _show_skinned_message(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)


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
                _show_skinned_message(
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
                _show_skinned_message(
                    _("Error opening WiFi interface: {}\n\nTrying system WiFi settings instead...").format(str(e)),
                    _("WiFi Error"),
                    wx.OK | wx.ICON_WARNING
                )
            except:
                pass
        
        # Fallback to system network settings
        if IS_WINDOWS:
            try:
                subprocess.Popen(["explorer", "ms-settings:network-status"])
            except Exception as e:
                 _show_skinned_message(_("Could not open network settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif IS_LINUX:
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
                        subprocess.Popen(app_cmd, stderr=subprocess.DEVNULL)
                        break
                    except FileNotFoundError:
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
                        
                        _show_skinned_message(_(info_text), _("Network Information"), wx.OK | wx.ICON_INFORMATION)
                    except Exception:
                        # Final fallback - show basic IP info
                        try:
                            result = subprocess.run(["ip", "addr", "show"], 
                                                   capture_output=True, text=True, check=True)
                            _show_skinned_message(_("Network interface information:\n\n{}").format(result.stdout[:1000]), 
                                         _("Network Information"), wx.OK | wx.ICON_INFORMATION)
                        except Exception:
                            _show_skinned_message(_("Could not open network settings. Please use your system's network manager."), 
                                         _("Information"), wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                _show_skinned_message(_("Could not open network settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        elif IS_MACOS:
            try:
                subprocess.Popen(["open", "/System/Library/PreferencePanes/Network.prefPane"])
            except Exception as e:
                 _show_skinned_message(_("Could not open network settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            _show_skinned_message(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)

    def minimize_to_tray(self, activate_invisible_ui=True):
        self.Hide()
        skin_name = self.settings.get('interface', {}).get('skin', DEFAULT_SKIN_NAME)
        skin_data = self.load_skin_data(skin_name)
        self.task_bar_icon = TaskBarIcon(self, self.version, skin_data)
        play_sound('ui/minimalize.ogg')
        vibrate_menu_close()  # Add vibration for minimizing to tray
        if activate_invisible_ui:
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
            self._show_first_view()
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

        # Cleanup global F2 hotkey
        self._unregister_global_f2_hotkey()

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

                # Tear down ALL keyboard hooks BEFORE os._exit. The keyboard
                # module installs a low-level Windows hook (WH_KEYBOARD_LL).
                # remove_hotkey only detaches individual callbacks; the LL hook
                # itself stays installed until unhook_all(). If we exit
                # abruptly with an LL hook still registered, Windows keeps
                # dispatching keystrokes through a dead procedure pointer and
                # the next hook in the chain (NVDA) crashes.
                try:
                    import keyboard as _kb_cleanup
                    try:
                        _kb_cleanup.remove_all_hotkeys()
                    except Exception:
                        pass
                    try:
                        _kb_cleanup.unhook_all()
                    except Exception:
                        pass
                    print("INFO: keyboard hooks fully detached")
                except Exception as e:
                    print(f"Warning: Error detaching keyboard hooks: {e}")

                # Silence and tear down accessible_output3 so NVDA isn't left
                # mid-utterance against a dying process.
                try:
                    if hasattr(speaker, 'silence'):
                        speaker.silence()
                except Exception:
                    pass

                # Quit pygame mixer cleanly so audio device handles are
                # released before the process dies.
                try:
                    import pygame as _pg_cleanup
                    if _pg_cleanup.mixer.get_init():
                        _pg_cleanup.mixer.quit()
                except Exception as e:
                    print(f"Warning: Error quitting pygame mixer: {e}")

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
        _show_skinned_message(_("Network settings - coming soon"), _("Information"), wx.OK | wx.ICON_INFORMATION)
    
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
        
        _show_skinned_message(info_text, _("Telegram Information"), wx.OK | wx.ICON_INFORMATION)
    
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
            _show_skinned_message(_("Voice calls are not available.\nCheck if py-tgcalls is installed."),
                         _("Error"), wx.OK | wx.ICON_ERROR)
            return

        play_sound('ui/dialog.ogg')
        message = _("Do you want to start a voice call with {}?").format(username)
        result = _show_skinned_message(message, _("Voice call"), wx.YES_NO | wx.ICON_QUESTION)
        
        if result == wx.YES:
            # Start voice call
            success = telegram_client.start_voice_call(username)
            if success:
                # Open separate voice call window and store reference
                self.call_window = telegram_windows.open_voice_call_window(self, username, 'outgoing')
                self.call_active = True
            else:
                play_sound('core/error.ogg')
                _show_skinned_message(_("Failed to start conversation."), _("Error"), wx.OK | wx.ICON_ERROR)

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
            _show_skinned_message(_("Connection failed: {}").format(data.get('error', 'Unknown error')),
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

