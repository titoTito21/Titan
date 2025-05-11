import wx
import os
import platform
import threading
import subprocess
import shutil
import traceback
import configparser

from app_manager import get_applications, open_application
from game_manager import get_games, open_game
from notifications import get_current_time, get_battery_status, get_volume_level, get_network_status
from sound import initialize_sound, play_focus_sound, play_select_sound, play_statusbar_sound, play_applist_sound, play_endoflist_sound, play_sound
from menu import MenuBar
from bg5reader import speak

SKINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skins')
DEFAULT_SKIN_NAME = "Domyślna"


class TitanApp(wx.Frame):
    def __init__(self, *args, version, settings=None, **kw):
        super(TitanApp, self).__init__(*args, **kw)
        self.version = version
        self.settings = settings

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

        self.tool_apps = self.toolbar.AddTool(wx.ID_ANY, "Lista Aplikacji", empty_bitmap, shortHelp="Pokaż listę aplikacji")
        self.tool_games = self.toolbar.AddTool(wx.ID_ANY, "Lista Gier", empty_bitmap, shortHelp="Pokaż listę gier")

        self.toolbar.Realize()

        self.Bind(wx.EVT_TOOL, self.on_show_apps, self.tool_apps)
        self.Bind(wx.EVT_TOOL, self.on_show_games, self.tool_games)


        self.list_label = wx.StaticText(panel, label="Lista Aplikacji:")
        main_vbox.Add(self.list_label, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.app_listbox = wx.ListBox(panel)

        self.game_listbox = wx.ListBox(panel)

        list_sizer = wx.BoxSizer(wx.VERTICAL)
        list_sizer.Add(self.app_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)
        list_sizer.Add(self.game_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=0)

        main_vbox.Add(list_sizer, proportion=1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.BOTTOM, border=10)

        main_vbox.Add(wx.StaticText(panel, label="Pasek statusu:"), flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.statusbar_listbox = wx.ListBox(panel)
        self.populate_statusbar()

        main_vbox.Add(self.statusbar_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)

        self.app_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_app_selected)
        self.game_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_game_selected)

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        self.app_listbox.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu)
        self.game_listbox.Bind(wx.EVT_CONTEXT_MENU, self.on_list_context_menu)

        self.app_listbox.Bind(wx.EVT_MOTION, self.on_focus_change)
        self.game_listbox.Bind(wx.EVT_MOTION, self.on_focus_change)
        self.statusbar_listbox.Bind(wx.EVT_MOTION, self.on_focus_change_status)


        panel.SetSizer(main_vbox)

        self.SetSize((600, 800))
        self.SetTitle("Titan App Suite")
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
            print(f"INFO: Ładowanie domyślnej skórki lub plik skin.ini nie znaleziono w {skin_path}")
            skin_data['Colors'] = {
                'frame_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_FRAMEBK),
                'panel_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
                'listbox_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
                'listbox_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                'listbox_selection_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT),
                'listbox_selection_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT),
                'label_foreground_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNTEXT),
                'toolbar_background_color': wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE) # Zmieniono z wx.SYS_COLOUR_TOOLBAR
            }
            skin_data['Fonts']['default_font_size'] = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetPointSize()
            skin_data['Fonts']['listbox_font_face'] = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetFaceName()
            skin_data['Fonts']['statusbar_font_face'] = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT).GetFaceName()

            skin_data['Icons'] = {}


        else:
            print(f"INFO: Ładowanie skórki z: {skin_ini_path}")
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
                                print(f"WARNING: Niepoprawny format koloru w skin.ini: {value} dla klucza {key}")
                                skin_data['Colors'][key] = wx.NullColour
                        except ValueError:
                             print(f"WARNING: Niepoprawny format koloru w skin.ini: {value} dla klucza {key}")
                             skin_data['Colors'][key] = wx.NullColour


                if 'Fonts' in config:
                    if 'default_font_size' in config['Fonts']:
                         try:
                             skin_data['Fonts']['default_font_size'] = int(config['Fonts']['default_font_size'])
                         except ValueError:
                             print(f"WARNING: Niepoprawny format rozmiaru czcionki w skin.ini: {config['Fonts']['default_font_size']}")

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
                             print(f"WARNING: Plik ikony nie znaleziono: {icon_full_path}")
                             skin_data['Icons'][key] = None


            except configparser.Error as e:
                print(f"ERROR: Błąd podczas czytania pliku skin.ini: {e}")
            except Exception as e:
                 print(f"ERROR: Nieoczekiwany błąd podczas ładowania skórki: {e}")


        return skin_data

    def apply_skin(self, skin_data):
        if not skin_data:
            print("WARNING: Brak danych skórki do zastosowania.")
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
                     print(f"WARNING: Nie udało się wczytać bitmapy ikony: {icons['app_list_icon']}")
            except Exception as e:
                 print(f"ERROR: Błąd podczas stosowania ikony {icons['app_list_icon']}: {e}")

        if 'game_list_icon' in icons and icons['game_list_icon']:
             try:
                  icon_bitmap = wx.Bitmap(icons['game_list_icon'], wx.BITMAP_TYPE_ANY)
                  if icon_bitmap.IsOk():
                      self.toolbar.SetToolNormalBitmap(self.tool_games.GetId(), icon_bitmap)
                      self.toolbar.Realize()
                  else:
                      print(f"WARNING: Nie udało się wczytać bitmapy ikony: {icons['game_list_icon']}")
             except Exception as e:
                  print(f"ERROR: Błąd podczas stosowania ikony {icons['game_list_icon']}: {e}")


        self.Refresh()
        self.Update()
        self.Layout()


    def apply_selected_skin(self):
        skin_name = DEFAULT_SKIN_NAME
        if self.settings and 'interface' in self.settings and 'skin' in self.settings['interface']:
             skin_name = self.settings['interface']['skin']

        print(f"INFO: Stosowanie skórki: {skin_name}")
        skin_data = self.load_skin_data(skin_name)
        self.apply_skin(skin_data)


    def populate_app_list(self):
        applications = get_applications()
        self.app_listbox.Clear()
        for app in applications:
            self.app_listbox.Append(app.get("name", "Unknown App"), clientData=app)


    def populate_game_list(self):
        games = get_games()
        self.game_listbox.Clear()
        for game in games:
            self.game_listbox.Append(game.get("name", "Unknown Game"), clientData=game)


    def populate_statusbar(self):
        self.statusbar_listbox.Clear()
        self.statusbar_listbox.Append(f"zegar: {get_current_time()}")
        self.statusbar_listbox.Append(f"poziom baterii: {get_battery_status()}")
        self.statusbar_listbox.Append(f"głośność: {get_volume_level()}")
        self.statusbar_listbox.Append(get_network_status())

    def update_statusbar(self, event):
        self.statusbar_listbox.SetString(0, f"zegar: {get_current_time()}")
        self.statusbar_listbox.SetString(1, f"poziom baterii: {get_battery_status()}")
        self.statusbar_listbox.SetString(2, f"głośność: {get_volume_level()}")
        self.statusbar_listbox.SetString(3, get_network_status())


    def on_app_selected(self, event):
        selection = self.app_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            app_info = self.app_listbox.GetClientData(selection)
            if app_info:
                 play_select_sound()
                 open_application(app_info)
            else:
                 print("WARNING: Brak danych ClientData dla wybranej aplikacji.")


    def on_game_selected(self, event):
        selection = self.game_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            game_info = self.game_listbox.GetClientData(selection)
            if game_info:
                 play_select_sound()
                 open_game(game_info)
            else:
                 print("WARNING: Brak danych ClientData dla wybranej gry.")

    def on_list_context_menu(self, event):
        listbox = event.GetEventObject()
        selected_index = listbox.GetSelection()

        if selected_index != wx.NOT_FOUND:
            item_data = listbox.GetClientData(selected_index)
            if not item_data:
                 print("WARNING: Brak danych ClientData dla zaznaczonego elementu menu kontekstowego.")
                 event.Skip()
                 return

            item_type = None
            if listbox == self.app_listbox:
                 item_type = "app"
            elif listbox == self.game_listbox:
                 item_type = "game"

            if not item_type:
                 print("ERROR: Nie można określić typu elementu menu kontekstowego.")
                 event.Skip()
                 return

            play_sound('contextmenu.ogg')

            menu = wx.Menu()

            run_label = f"Uruchom {item_data.get('name', 'element')}..."
            run_item = menu.Append(wx.ID_ANY, run_label)
            self.Bind(wx.EVT_MENU, lambda evt, data=item_data, type=item_type: self.on_run_from_context_menu(evt, item_data=data, item_type=type), run_item)

            uninstall_label = f"Odinstaluj {item_data.get('name', 'element')}"
            uninstall_item = menu.Append(wx.ID_ANY, uninstall_label)
            self.Bind(wx.EVT_MENU, lambda evt, data=item_data, type=item_type: self.on_uninstall(evt, item_data=data, item_type=type), uninstall_item)

            listbox.PopupMenu(menu, event.GetPosition())

            play_sound('contextmenuclose.ogg')

            menu.Destroy()

        event.Skip()


    def on_run_from_context_menu(self, event, item_data=None, item_type=None):
        if not item_data or not item_type:
            print("ERROR: Brak danych elementu do uruchomienia z menu kontekstowego.")
            wx.MessageBox("Wystąpił błąd: Brak danych do uruchomienia.", "Błąd", wx.OK | wx.ICON_ERROR)
            return

        if item_type == "app":
            play_select_sound()
            open_application(item_data)
        elif item_type == "game":
            play_select_sound()
            open_game(item_data)
        else:
            print(f"ERROR: Nieznany typ elementu ({item_type}) do uruchomienia z menu kontekstowego.")


    def on_uninstall(self, event, item_data=None, item_type=None):
        if not item_data or not item_type:
            print("ERROR: Brak danych elementu lub typu do odinstalowania z menu kontekstowego.")
            wx.MessageBox("Wystąpił błąd: Brak danych do odinstalowania.", "Błąd", wx.OK | wx.ICON_ERROR)
            return

        item_name = item_data.get('name', 'nieznany element')
        item_path = item_data.get('path')

        if not item_path or not os.path.exists(item_path):
            print(f"ERROR: Ścieżka do odinstalowania niepoprawna lub katalog nie istnieje: {item_path}")
            wx.MessageBox(f"Błąd: Nie można odnaleźć katalogu '{item_name}' do odinstalowania.", "Błąd", wx.OK | wx.ICON_ERROR)
            return

        confirm_dialog = wx.MessageDialog(
            self,
            f"Czy na pewno chcesz odinstalować '{item_name}' z Titana?\n\nSpowoduje to usunięcie całego katalogu: {item_path}",
            "Potwierdź odinstalowanie",
            wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
        )

        result = confirm_dialog.ShowModal()
        confirm_dialog.Destroy()

        if result == wx.ID_YES:
            print(f"INFO: Użytkownik potwierdził odinstalowanie '{item_name}'. Usuwanie katalogu: {item_path}")
            try:
                shutil.rmtree(item_path)
                print(f"INFO: Katalog '{item_path}' usunięty pomyślnie.")

                if item_type == "app":
                    self.populate_app_list()
                    print(f"INFO: Lista aplikacji odświeżona.")
                elif item_type == "game":
                    self.populate_game_list()
                    print(f"INFO: Lista gier odświeżona.")

                play_select_sound()
                wx.MessageBox(f"'{item_name}' został pomyślnie odinstalowany.", "Sukces", wx.OK | wx.ICON_INFORMATION)


            except OSError as e:
                print(f"ERROR: Błąd podczas usuwania katalogu '{item_path}': {e}")
                play_endoflist_sound()
                wx.MessageBox(f"Błąd podczas odinstalowywania '{item_name}':\n{e}\n\nUpewnij się, że katalog nie jest używany.", "Błąd", wx.OK | wx.ICON_ERROR)
            except Exception as e:
                 print(f"ERROR: Nieoczekiwany błąd podczas odinstalowywania '{item_name}': {e}")
                 play_endoflist_sound()
                 wx.MessageBox(f"Nieoczekiwany błąd podczas odinstalowywania '{item_name}':\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)

        else:
            print(f"INFO: Odinstalowanie '{item_name}' anulowane przez użytkownika.")
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
             self.handle_navigation_key_sound(keycode, current_focus)
             event.Skip()
             return

        event.Skip()

    def handle_navigation_key_sound(self, keycode, current_focus):
        target_listbox = None
        if current_focus == self.app_listbox and self.app_listbox.IsShown():
            target_listbox = self.app_listbox
            list_type = "app"
        elif current_focus == self.game_listbox and self.game_listbox.IsShown():
            target_listbox = self.game_listbox
            list_type = "game"
        elif current_focus == self.statusbar_listbox:
             target_listbox = self.statusbar_listbox
             list_type = "status"
        else:
             return

        if target_listbox:
            current_selection = target_listbox.GetSelection()
            item_count = target_listbox.GetCount()

            if keycode in [wx.WXK_UP, wx.WXK_DOWN]:
                if keycode == wx.WXK_UP and current_selection <= 0:
                     play_endoflist_sound()
                elif keycode == wx.WXK_DOWN and current_selection >= item_count - 1:
                     play_endoflist_sound()
                else:
                     play_focus_sound()

            elif keycode in [wx.WXK_LEFT, wx.WXK_RIGHT]:
                 play_focus_sound()


            elif keycode in [wx.WXK_HOME, wx.WXK_END]:
                play_endoflist_sound()


    def on_focus_change(self, event):
        play_focus_sound()
        event.Skip()

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
        if "zegar:" in item:
            self.open_time_settings()
        elif "poziom baterii:" in item:
            self.open_power_settings()
        elif "głośność:" in item:
            self.open_volume_mixer()
        elif "status sieci:" in item:
             self.open_network_settings()
        else:
            print(f"WARNING: Nieznany element statusbaru wybrany: {item}")


    def show_app_list(self):
        self.app_listbox.Show()
        self.game_listbox.Hide()
        self.list_label.SetLabel("Lista Aplikacji:")
        self.current_list = "apps"
        self.Layout()
        if self.app_listbox.GetCount() > 0:
             self.app_listbox.SetFocus()


    def show_game_list(self):
        self.app_listbox.Hide()
        self.game_listbox.Show()
        self.list_label.SetLabel("Lista Gier:")
        self.current_list = "games"
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


    def open_time_settings(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(["timedate.cpl"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć ustawień daty/czasu:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/System/Library/PreferencePanes/DateAndTime.prefPane"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć ustawień daty/czasu:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)

    def open_power_settings(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(["powercfg.cpl"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć ustawień zasilania:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/System/Library/PreferencePanes/EnergySaver.prefPane"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć ustawień zasilania:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)

    def open_volume_mixer(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(["sndvol.exe"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć miksera głośności:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/Applications/Utilities/Audio MIDI Setup.app"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć ustawień audio:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)


    def open_network_settings(self):
        if platform.system() == "Windows":
            try:
                subprocess.run(["explorer", "ms-settings:network-status"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć ustawień sieciowych:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        elif platform.system() == "Darwin":
            try:
                subprocess.run(["open", "/System/Library/PreferencePanes/Network.prefPane"], check=True)
            except Exception as e:
                 wx.MessageBox(f"Nie można otworzyć ustawień sieciowych:\n{e}", "Błąd", wx.OK | wx.ICON_ERROR)
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)


if __name__ == "__main__":
    def get_applications():
        return [{"name": "Dummy App 1", "openfile": "dummy1.exe", "path": "."},
                {"name": "Dummy App 2", "openfile": "dummy2.py", "path": "."}]

    def open_application(app_info):
        speak(f"Uruchamiam {app_info.get('name', 'Unknown App')}")

    def get_games():
        return [{"name": "Dummy Game A", "openfile": "dummya.exe", "path": "."},
                {"name": "Dummy Game B", "openfile": "dummyb.py", "path": "."}]

    def open_game(game_info):
         speak(f"Uruchamiam grę {game_info.get('name', 'Unknown Game')}")

    def get_current_time(): return "12:00"
    def get_battery_status(): return "100%"
    def get_volume_level(): return "50%"
    def get_network_status(): return "Online"

    def initialize_sound(): pass
    def play_focus_sound(): pass
    def play_select_sound(): pass
    def play_statusbar_sound(): pass
    def play_applist_sound(): pass
    def play_endoflist_sound(): pass
    def play_sound(sound_file): pass

    def speak(text): pass
    def MenuBar(parent): pass

    app = wx.App(False)
    frame = TitanApp(None, title="Interfejs graficzny Titana - Test", version="Test")
    frame.Show()
    app.MainLoop()