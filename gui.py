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
import telegram_client
import telegram_windows
import messenger_webview

from app_manager import get_applications, open_application
from game_manager import get_games, open_game
from notifications import get_current_time, get_battery_status, get_volume_level, get_network_status
from sound import initialize_sound, play_focus_sound, play_select_sound, play_statusbar_sound, play_applist_sound, play_endoflist_sound, play_sound
import accessible_output3.outputs.auto
from menu import MenuBar
from invisibleui import InvisibleUI
from translation import set_language
from settings import get_setting
from shutdown_question import show_shutdown_dialog

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

SKINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skins')
DEFAULT_SKIN_NAME = _("Default")
speaker = accessible_output3.outputs.auto.Auto()

class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame, version, skin_data):
        super(TaskBarIcon, self).__init__()
        self.frame = frame
        
        icon_path = None
        if skin_data and 'Icons' in skin_data and 'taskbar_icon' in skin_data['Icons']:
            icon_path = skin_data['Icons']['taskbar_icon']

        if icon_path and os.path.exists(icon_path):
            icon = wx.Icon(icon_path)
            if not icon.IsOk():
                print(f"WARNING: Could not load taskbar icon from: {icon_path}")
                icon = wx.Icon(wx.ArtProvider.GetBitmap(wx.ART_MISSING_IMAGE, wx.ART_OTHER, (16, 16)))
        else:
            # Default icon if not defined in skin or file does not exist
            icon = wx.Icon(wx.ArtProvider.GetBitmap(wx.ART_QUESTION, wx.ART_OTHER, (16, 16)))

        self.SetIcon(icon, _("Titan v{}").format(version))
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_left_dclick)

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
    def __init__(self, *args, version, settings=None, component_manager=None, **kw):
        super(TitanApp, self).__init__(*args, **kw)
        self.version = version
        self.settings = settings
        self.component_manager = component_manager
        self.task_bar_icon = None
        self.invisible_ui = InvisibleUI(self, component_manager=self.component_manager)
        self.logged_in = False
        self.telegram_client = None
        self.online_users = []
        self.current_chat_user = None
        self.unread_messages = {}
        self.call_active = False
        self.call_window = None

        initialize_sound()

        self.current_list = "apps"

        self.InitUI()

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_statusbar, self.timer)
        self.timer.Start(5000)

        self.populate_app_list()
        self.populate_game_list()

        self.apply_selected_skin()

        self.show_app_list()


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
        self.game_listbox = wx.ListBox(panel)
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
        self.password_label = wx.StaticText(self.login_panel, label=_("Hasło 2FA (jeśli włączone):"))
        self.password_text = wx.TextCtrl(self.login_panel, style=wx.TE_PASSWORD)
        self.login_button = wx.Button(self.login_panel, label=_("OK"))
        # Remove the second button - communicators will be in list
        # self.register_button = wx.Button(self.login_panel, label=_("Inne komunikatory wkrótce"))

        login_sizer.Add(self.username_label, 0, wx.ALL, 5)
        login_sizer.Add(self.username_text, 0, wx.EXPAND|wx.ALL, 5)
        login_sizer.Add(self.password_label, 0, wx.ALL, 5)
        login_sizer.Add(self.password_text, 0, wx.EXPAND|wx.ALL, 5)
        login_sizer.Add(self.login_button, 0, wx.ALL, 5)
        # Only add the OK button now
        # login_sizer.Add(self.register_button, 0, wx.ALL, 5)

        self.login_panel.SetSizer(login_sizer)
        self.login_panel.Hide()

        self.login_button.Bind(wx.EVT_BUTTON, self.on_login)
        # self.register_button.Bind(wx.EVT_BUTTON, self.on_register)

        self.logout_button = wx.Button(panel, label=_("Logout"))
        self.logout_button.Bind(wx.EVT_BUTTON, self.on_logout)
        self.logout_button.Hide()


        list_sizer = wx.BoxSizer(wx.VERTICAL)
        list_sizer.Add(self.app_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        list_sizer.Add(self.game_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
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
        send_btn = wx.Button(panel, label=_("Wyślij"))
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
        self.game_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_game_selected)
        self.network_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_network_option_selected)
        self.users_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_user_selected)
        self.users_listbox.Bind(wx.EVT_RIGHT_UP, self.on_users_context_menu)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.Bind(wx.EVT_ICONIZE, self.on_minimize)

        self.app_listbox.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu)
        self.game_listbox.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu)

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

        listbox_elements = [self.app_listbox, self.game_listbox, self.statusbar_listbox]
        for listbox in listbox_elements:
             if 'listbox_background_color' in colors:
                 listbox.SetBackgroundColour(colors['listbox_background_color'])
             if 'listbox_foreground_color' in colors:
                 listbox.SetForegroundColour(colors['listbox_foreground_color'])


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
        skin_name = DEFAULT_SKIN_NAME
        if self.settings and 'interface' in self.settings and 'skin' in self.settings['interface']:
             skin_name = self.settings['interface']['skin']

        print(f"INFO: Applying skin: {skin_name}")
        skin_data = self.load_skin_data(skin_name)
        self.apply_skin(skin_data)


    def populate_app_list(self):
        applications = get_applications()
        self.app_listbox.Clear()
        for app in applications:
            self.app_listbox.Append(app.get("name", _("Unknown App")), clientData=app)


    def populate_game_list(self):
        games = get_games()
        self.game_listbox.Clear()
        for game in games:
            self.game_listbox.Append(game.get("name", _("Unknown Game")), clientData=game)


    def populate_statusbar(self):
        self.statusbar_listbox.Clear()
        self.statusbar_listbox.Append(_("Clock: {}").format(get_current_time()))
        self.statusbar_listbox.Append(_("Battery level: {}").format(get_battery_status()))
        self.statusbar_listbox.Append(_("Volume: {}").format(get_volume_level()))
        self.statusbar_listbox.Append(get_network_status())

    def update_statusbar(self, event):
        self.statusbar_listbox.SetString(0, _("Clock: {}").format(get_current_time()))
        self.statusbar_listbox.SetString(1, _("Battery level: {}").format(get_battery_status()))
        self.statusbar_listbox.SetString(2, _("Volume: {}").format(get_volume_level()))
        self.statusbar_listbox.SetString(3, get_network_status())


    def on_app_selected(self, event):
        selection = self.app_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            app_info = self.app_listbox.GetClientData(selection)
            if app_info:
                 play_select_sound()
                 open_application(app_info)
            else:
                 print("WARNING: No ClientData for selected application.")


    def on_game_selected(self, event):
        selection = self.game_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            game_info = self.game_listbox.GetClientData(selection)
            if game_info:
                 play_select_sound()
                 open_game(game_info)
            else:
                 print("WARNING: No ClientData for selected game.")

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
            elif listbox == self.game_listbox:
                 item_type = "game"

            if not item_type:
                 print("ERROR: Could not determine context menu item type.")
                 event.Skip()
                 return

            play_sound('contextmenu.ogg')

            menu = wx.Menu()

            run_label = _("Run {}...").format(item_data.get('name', _('item')))
            run_item = menu.Append(wx.ID_ANY, run_label)
            self.Bind(wx.EVT_MENU, lambda evt, data=item_data, type=item_type: self.on_run_from_context_menu(evt, item_data=data, item_type=type), run_item)

            uninstall_label = _("Uninstall {}").format(item_data.get('name', _('item')))
            uninstall_item = menu.Append(wx.ID_ANY, uninstall_label)
            self.Bind(wx.EVT_MENU, lambda evt, data=item_data, type=item_type: self.on_uninstall(evt, item_data=data, item_type=type), uninstall_item)

            listbox.PopupMenu(menu, event.GetPosition())

            play_sound('contextmenuclose.ogg')

            menu.Destroy()

        event.Skip()


    def on_run_from_context_menu(self, event, item_data=None, item_type=None):
        if not item_data or not item_type:
            print("ERROR: No item data to run from context menu.")
            wx.MessageBox(_("An error occurred: No data to run."), _("Error"), wx.OK | wx.ICON_ERROR)
            return

        if item_type == "app":
            play_select_sound()
            open_application(item_data)
        elif item_type == "game":
            play_select_sound()
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
            try:
                shutil.rmtree(item_path)
                print(f"INFO: Directory '{item_path}' deleted successfully.")

                if item_type == "app":
                    self.populate_app_list()
                    print(f"INFO: Application list refreshed.")
                elif item_type == "game":
                    self.populate_game_list()
                    print(f"INFO: Game list refreshed.")

                play_select_sound()
                wx.MessageBox(_("'{}' has been successfully uninstalled.").format(item_name), _("Success"), wx.OK | wx.ICON_INFORMATION)


            except OSError as e:
                print(f"ERROR: Error deleting directory '{item_path}': {e}")
                play_endoflist_sound()
                wx.MessageBox(_("Error uninstalling '{}':\n{}\n\nMake sure the directory is not in use.").format(item_name, e), _("Error"), wx.OK | wx.ICON_ERROR)
            except Exception as e:
                 print(f"ERROR: Unexpected error during uninstall of '{item_name}': {e}")
                 play_endoflist_sound()
                 wx.MessageBox(_("An unexpected error occurred while uninstalling '{}':\n{}").format(item_name, e), _("Error"), wx.OK | wx.ICON_ERROR)

        else:
            print(f"INFO: Uninstall of '{item_name}' canceled by user.")
            play_focus_sound()


    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        current_focus = self.FindFocus()

        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self.on_toggle_list()
            return

        # Handle ESC key - return from users/contacts/group_chats list to network list
        if keycode == wx.WXK_ESCAPE:
            if self.current_list in ["users", "contacts", "group_chats"]:
                play_sound('popupclose.ogg')
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
                    # Trigger context menu on Enter
                    self.on_users_context_menu(event)
                    return

        if keycode == wx.WXK_RETURN:
            if current_focus == self.app_listbox and self.app_listbox.IsShown():
                 self.on_app_selected(event)
            elif current_focus == self.game_listbox and self.game_listbox.IsShown():
                 self.on_game_selected(event)
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
                  elif current_focus == self.game_listbox and self.game_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                  elif current_focus == self.network_listbox and self.network_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                  elif current_focus == self.users_listbox and self.users_listbox.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                  elif current_focus == self.message_input and self.message_input.IsShown():
                      self.statusbar_listbox.SetFocus()
                      play_statusbar_sound()
                  elif current_focus == self.statusbar_listbox:
                      if self.current_list == "apps":
                           self.app_listbox.SetFocus()
                           play_applist_sound()
                      elif self.current_list == "games":
                           self.game_listbox.SetFocus()
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
                  else:
                      event.Skip()
                  return
             elif modifiers == wx.MOD_SHIFT:
                  if current_focus == self.statusbar_listbox:
                      if self.current_list == "apps":
                           self.app_listbox.SetFocus()
                           play_applist_sound()
                      elif self.current_list == "games":
                           self.game_listbox.SetFocus()
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
        target_listbox = None
        if current_focus == self.app_listbox and self.app_listbox.IsShown():
            target_listbox = self.app_listbox
        elif current_focus == self.game_listbox and self.game_listbox.IsShown():
            target_listbox = self.game_listbox
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
                pan = 0
                if item_count > 1:
                    pan = new_selection / (item_count - 1)
                play_focus_sound(pan=pan)
            else:
                play_endoflist_sound()


    def on_focus_change_status(self, event):
         play_statusbar_sound()
         event.Skip()


    def on_status_selected(self, event):
        selection = self.statusbar_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            play_select_sound()
            status_item = self.statusbar_listbox.GetString(selection)
            threading.Thread(target=self.handle_status_action, args=(status_item,)).start()

    def handle_status_action(self, item):
        if _("Clock:") in item:
            self.open_time_settings()
        elif _("Battery level:") in item:
            self.open_power_settings()
        elif _("Volume:") in item:
            self.open_volume_mixer()
        elif _("Network status:") in item:
             self.open_network_settings()
        else:
            print(f"WARNING: Unknown statusbar item selected: {item}")


    def show_app_list(self):
        self.app_listbox.Show()
        self.game_listbox.Hide()
        self.network_listbox.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        self.list_label.SetLabel(_("Application List:"))
        self.current_list = "apps"
        speaker.speak(_("Application list, 1 of 3"))
        self.Layout()
        if self.app_listbox.GetCount() > 0:
             self.app_listbox.SetFocus()


    def show_game_list(self):
        self.app_listbox.Hide()
        self.game_listbox.Show()
        self.network_listbox.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        self.list_label.SetLabel(_("Game List:"))
        self.current_list = "games"
        speaker.speak(_("Game list, 2 of 3"))
        self.Layout()
        if self.game_listbox.GetCount() > 0:
             self.game_listbox.SetFocus()

    def show_network_list(self):
        self.app_listbox.Hide()
        self.game_listbox.Hide()
        self.network_listbox.Show()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        self.list_label.SetLabel(_("Titan IM:"))
        self.current_list = "network"
        speaker.speak(_("Titan IM, 3 of 3"))
        
        # Always populate the network list based on login status
        self.populate_network_list()
        
        self.Layout()
        if self.network_listbox.GetCount() > 0:
            self.network_listbox.SetFocus()

    def populate_network_options(self):
        self.network_listbox.Clear()
        self.network_listbox.Append(_("Telegram"))
        self.network_listbox.Append(_("Facebook Messenger"))
        # Future messaging platforms:
        # self.network_listbox.Append(_("Mastodon"))
        # self.network_listbox.Append(_("Matrix"))

    def on_network_option_selected(self, event):
        if not self.logged_in:
            selection = self.network_listbox.GetSelection()
            if selection != wx.NOT_FOUND:
                if selection == 0: # Telegram
                    self.show_telegram_login()
                elif selection == 1: # Facebook Messenger
                    self.show_messenger_login()
                elif selection == 2: # Other communicators
                    wx.MessageBox(_("Other communicators will be available soon."), _("Information"), wx.OK | wx.ICON_INFORMATION)
        else:
            selection = self.network_listbox.GetSelection()
            if selection != wx.NOT_FOUND:
                if selection == 0: # Contacts
                    self.show_contacts_view()
                elif selection == 1: # Group Chats
                    self.show_group_chats_view()
                elif selection == 2: # Settings
                    self.show_network_settings()
                elif selection == 3: # Info
                    self.show_network_info()

    def show_telegram_login(self):
        """Show Telegram login interface"""
        self.app_listbox.Hide()
        self.game_listbox.Hide()
        self.network_listbox.Hide()
        self.users_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Show()
        
        self.list_label.SetLabel(_("Telegram Login"))
        self.login_button.Show()
        # self.register_button.Show()  # Removed - communicators now in list
        
        self.current_list = "telegram_login"
        self.Layout()
        self.username_text.SetFocus()
        
    def show_messenger_login(self):
        """Show Facebook Messenger WebView interface"""
        try:
            messenger_webview.show_messenger_webview(self)
        except Exception as e:
            print(f"WebView Messenger error: {e}")
            wx.MessageBox(
                _("Nie można uruchomić Messenger WebView.\n"
                  "Sprawdź czy WebView2 jest zainstalowany."),
                _("Błąd Messenger WebView"),
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

        play_sound('connecting.ogg')
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
            self.telegram_client = telegram_client.connect_to_server(phone_number, twofa_password, _("TCE User"))
            
            # Setup callbacks for real-time events
            self.telegram_client.add_message_callback(self.on_message_received)
            self.telegram_client.add_status_callback(self.on_user_status_change)
            self.telegram_client.add_typing_callback(self.on_typing_indicator)
            telegram_client.add_call_callback(self.on_call_event)
            
            # No dialog - just TTS announcement
            self.populate_network_list()
            self.show_network_list()
            self.logout_button.Show()
            self.logged_in = True
            
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
        
        if not self.logged_in:
            # Show communicator options when not logged in
            self.network_listbox.Append(_("Telegram"))
            self.network_listbox.Append(_("Facebook Messenger"))
            self.network_listbox.Append(_("Other communicators"))
        else:
            # Show logged in options
            self.network_listbox.Append(_("Contacts"))
            self.network_listbox.Append(_("Group Chats"))
            self.network_listbox.Append(_("Settings"))
            self.network_listbox.Append(_("Information"))

    def on_toggle_list(self):
        play_sound('sectionchange.ogg')

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
            try:
                subprocess.run(["timedate.cpl"], check=True)
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
                subprocess.run(["powercfg.cpl"], check=True)
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
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/Applications/Utilities/Audio MIDI Setup.app"], check=True)
            except Exception as e:
                 wx.MessageBox(_("Could not open audio settings:\n{}").format(e), _("Error"), wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox(_("This feature is not supported on this platform."), _("Information"), wx.OK | wx.ICON_INFORMATION)


    def open_network_settings(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(["explorer", "ms-settings:network-status"], check=True)
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
        play_sound('minimalize.ogg')
        self.invisible_ui.start_listening()

    def restore_from_tray(self):
        self.Show()
        self.Raise()
        self.task_bar_icon.Destroy()
        self.task_bar_icon = None
        play_sound('normalize.ogg')
        self.invisible_ui.stop_listening()

    def shutdown_app(self):
        """Handles the complete shutdown of the application by terminating the process after a delay."""
        print("INFO: Shutting down application...")
        
        # Hide window immediately for user feedback
        self.Hide()
        
        # Safely disconnect from Telegram if connected
        def safe_shutdown():
            try:
                if self.logged_in and self.telegram_client:
                    print("INFO: Disconnecting from Telegram before shutdown...")
                    try:
                        telegram_client.disconnect_from_server()
                        # Give disconnect process time to complete
                        time.sleep(1)
                    except Exception as e:
                        print(f"Warning: Error disconnecting from Telegram: {e}")
                
                print("INFO: Application terminating now.")
                os._exit(0)
                
            except Exception as e:
                print(f"Error during shutdown: {e}")
                # Force exit even if there were errors
                os._exit(1)
        
        # Run shutdown process in background thread with slightly longer delay
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
        self.game_listbox.Hide()
        self.network_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.users_listbox.Show()
        self.list_label.SetLabel(_("Contacts"))
        self.current_list = "contacts"
        
        # Play popup sound when opening contacts view
        play_sound('popup.ogg')
        
        self.refresh_contacts()
        self.Layout()
        
        if self.users_listbox.GetCount() > 0:
            self.users_listbox.SetFocus()
    
    def show_group_chats_view(self):
        """Show group chats list"""
        self.app_listbox.Hide()
        self.game_listbox.Hide()
        self.network_listbox.Hide()
        self.chat_display.Hide()
        self.message_input.Hide()
        self.login_panel.Hide()
        
        self.users_listbox.Show()
        self.list_label.SetLabel(_("Group Chats"))
        self.current_list = "group_chats"
        
        # Play popup sound when opening group chats view
        play_sound('popup.ogg')
        
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
            info_text += f"{_('Użytkowników online')}: {online_count}\n"
            info_text += f"{_('Status połączenia')}: {_('Połączony')}"
        else:
            info_text = f"{_('Connection status')}: {_('Disconnected')}"
        
        wx.MessageBox(info_text, _("Telegram Information"), wx.OK | wx.ICON_INFORMATION)
    
    def refresh_contacts(self):
        """Refresh the contacts list (private chats)"""
        if self.telegram_client and telegram_client.is_connected():
            contacts = telegram_client.get_contacts()
            self.online_users = contacts  # Keep compatibility
            
            print(f"DEBUG: {_('Refreshing contacts list, found')}: {len(contacts)} {_('contacts')}")
            
            self.users_listbox.Clear()
            for contact in contacts:
                username = contact.get('username', contact)
                unread_count = self.unread_messages.get(username, 0)
                display_name = f"{username} ({unread_count} {_('unread')})" if unread_count > 0 else username
                self.users_listbox.Append(display_name)
                print(f"DEBUG: {_('Added contact')}: {display_name}")
        else:
            print(f"DEBUG: {_('No connection or client to refresh contacts')}")
    
    def refresh_group_chats(self):
        """Refresh the group chats list"""
        if self.telegram_client and telegram_client.is_connected():
            groups = telegram_client.get_group_chats()
            
            print(f"DEBUG: {_('Refreshing group chats, found')}: {len(groups)} {_('groups')}")
            
            self.users_listbox.Clear()
            for group in groups:
                group_name = group.get('name', group.get('title', 'Unknown Group'))
                unread_count = self.unread_messages.get(group_name, 0)
                display_name = f"{group_name} ({unread_count} {_('unread')})" if unread_count > 0 else group_name
                self.users_listbox.Append(display_name)
                print(f"DEBUG: {_('Added group')}: {display_name}")
        else:
            print(f"DEBUG: {_('No connection or client to refresh groups')}")
    
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
            play_sound('select.ogg')
    
    # Chat history loading moved to separate windows
    
    def on_users_context_menu(self, event):
        """Show context menu for selected user or group"""
        selection = self.users_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        
        user_text = self.users_listbox.GetString(selection)
        username = user_text.split(' (')[0]  # Remove unread count if present
        
        # Play context menu sound
        play_sound('contextmenu.ogg')
        
        # Create context menu
        menu = wx.Menu()
        
        # Add menu items based on current list type
        if self.current_list == "contacts":
            private_msg_item = menu.Append(wx.ID_ANY, _("Private message"), _("Send private message"))
            voice_call_item = menu.Append(wx.ID_ANY, _("Call"), _("Start voice call"))
            
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
            voice_call_item = menu.Append(wx.ID_ANY, _("Call"), _("Start voice call"))
            
            # Bind menu events
            self.Bind(wx.EVT_MENU, lambda evt: self.on_private_message(username), private_msg_item)
            self.Bind(wx.EVT_MENU, lambda evt: self.on_voice_call(username), voice_call_item)
        
        # Show menu at cursor position
        self.PopupMenu(menu)
        
        # Play context menu close sound
        play_sound('contextmenuclose.ogg')
        
        menu.Destroy()
    
    def on_private_message(self, username):
        """Start private message with user"""
        # Clear unread messages for this user
        if username in self.unread_messages:
            self.unread_messages[username] = 0
        
        # Open separate private message window
        telegram_windows.open_private_message_window(self, username)
        
        play_sound('select.ogg')
    
    def on_voice_call(self, username):
        """Start voice call with user"""
        if not telegram_client.is_voice_calls_available():
            play_sound('error.ogg')
            wx.MessageBox(_("Voice calls are not available.\nCheck if py-tgcalls is installed."), 
                         _("Error"), wx.OK | wx.ICON_ERROR)
            return
        
        play_sound('dialog.ogg')
        message = _("Do you want to start a voice call with {}?").format(username)
        result = wx.MessageBox(message, _("Voice call"), wx.YES_NO | wx.ICON_QUESTION)
        
        if result == wx.YES:
            # Start voice call
            success = telegram_client.start_voice_call(username)
            if success:
                # Open separate voice call window
                telegram_windows.open_voice_call_window(self, username, 'outgoing')
                self.call_active = True
            else:
                play_sound('error.ogg')
                wx.MessageBox(_("Nie udało się rozpocząć rozmowy."), _("Błąd"), wx.OK | wx.ICON_ERROR)
        
        play_sound('dialogclose.ogg')
    
    def on_group_chat(self, group_name):
        """Open group chat window"""
        # Clear unread messages for this group
        if group_name in self.unread_messages:
            self.unread_messages[group_name] = 0
        
        # Open separate group chat window 
        telegram_windows.open_group_chat_window(self, group_name)
        
        play_sound('select.ogg')
    
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
            play_sound('error.ogg')
            wx.MessageBox(_("Połączenie nie powiodło się: {}").format(data.get('error', 'Unknown error')), 
                         _("Błąd połączenia"), wx.OK | wx.ICON_ERROR)
    
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
                self.SetStatusText(_("{} dołączył do Telegramem").format(username))
                play_sound('user_online')
            elif status == 'offline':
                self.SetStatusText(_("{} opuścił Telegrama").format(username))
                play_sound('user_offline')
            
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
