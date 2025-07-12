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
        self.invisible_ui = InvisibleUI(self)

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

        self.toolbar.Realize()

        self.Bind(wx.EVT_TOOL, self.on_show_apps, self.tool_apps)
        self.Bind(wx.EVT_TOOL, self.on_show_games, self.tool_games)


        self.list_label = wx.StaticText(panel, label=_("Application List:"))
        main_vbox.Add(self.list_label, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.app_listbox = wx.ListBox(panel)

        self.game_listbox = wx.ListBox(panel)

        list_sizer = wx.BoxSizer(wx.VERTICAL)
        list_sizer.Add(self.app_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        list_sizer.Add(self.game_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)

        main_vbox.Add(list_sizer, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)

        main_vbox.Add(wx.StaticText(panel, label=_("Status Bar:")), flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.statusbar_listbox = wx.ListBox(panel)
        self.populate_statusbar()

        main_vbox.Add(self.statusbar_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

        self.app_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_app_selected)
        self.game_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_game_selected)

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

        if keycode == wx.WXK_RETURN:
            if current_focus == self.app_listbox and self.app_listbox.IsShown():
                 self.on_app_selected(event)
            elif current_focus == self.game_listbox and self.game_listbox.IsShown():
                 self.on_game_selected(event)
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
                  elif current_focus == self.statusbar_listbox:
                      if self.current_list == "apps":
                           self.app_listbox.SetFocus()
                           play_applist_sound()
                      elif self.current_list == "games":
                           self.game_listbox.SetFocus()
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
                  event.Skip()
                  return


        if keycode in [wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_HOME, wx.WXK_END]:
             self.handle_navigation(event, keycode, current_focus)
             return

        event.Skip()

    def handle_navigation(self, event, keycode, current_focus):
        target_listbox = None
        if current_focus == self.app_listbox and self.app_listbox.IsShown():
            target_listbox = self.app_listbox
        elif current_focus == self.game_listbox and self.game_listbox.IsShown():
            target_listbox = self.game_listbox
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
        self.list_label.SetLabel(_("Application List:"))
        self.current_list = "apps"
        speaker.speak(_("Application list, 1 of 2"))
        self.Layout()
        if self.app_listbox.GetCount() > 0:
             self.app_listbox.SetFocus()


    def show_game_list(self):
        self.app_listbox.Hide()
        self.game_listbox.Show()
        self.list_label.SetLabel(_("Game List:"))
        self.current_list = "games"
        speaker.speak(_("Game list, 2 of 2"))
        self.Layout()
        if self.game_listbox.GetCount() > 0:
             self.game_listbox.SetFocus()


    def on_toggle_list(self):
        play_sound('sectionchange.ogg')

        if self.current_list == "apps":
            self.show_game_list()
        else:
            self.show_app_list()


    def on_show_apps(self, event):
        if self.current_list != "apps":
             self.show_app_list()
        event.Skip()

    def on_show_games(self, event):
        if self.current_list != "games":
             self.show_game_list()
        event.Skip()


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
        print("INFO: Scheduling application termination in 1 second.")
        
        # This ensures that any final sounds have a moment to play before the process is killed.
        def delayed_exit():
            os._exit(0)
        
        # Using a threading.Timer to call os._exit without blocking the main thread.
        threading.Timer(1.0, delayed_exit).start()
        
        # We can hide the window immediately to give the user feedback that the command was received.
        self.Hide()

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
