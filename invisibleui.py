from pynput import keyboard
import threading
import time
import accessible_output3.outputs.auto
from sound import play_sound, play_focus_sound, play_endoflist_sound, play_statusbar_sound, play_applist_sound
from settings import load_settings, get_setting
from translation import set_language
from app_manager import get_applications, open_application
from game_manager import get_games, open_game
import componentmanagergui
import settingsgui
import sys
import wx
import os
import importlib.util

_ = set_language(get_setting('language', 'pl'))
speaker = accessible_output3.outputs.auto.Auto()

class GlobalHotKeys(threading.Thread):
    def __init__(self, hotkeys):
        super().__init__()
        self.hotkeys = hotkeys
        self.listener = None
        self.daemon = True

    def run(self):
        self.listener = keyboard.GlobalHotKeys(self.hotkeys)
        self.listener.start()

    def stop(self):
        if self.listener:
            self.listener.stop()
            try:
                self.listener.join()
            except RuntimeError:
                pass
        self.listener = None

class BaseWidget:
    def __init__(self, speak_func):
        self.speak = speak_func
        self.view = None

    def set_border(self):
        if self.view:
            try:
                self.view.setStyleSheet("border: 1px solid black;")
            except AttributeError:
                pass

    def get_current_element(self):
        raise NotImplementedError

    def navigate(self, direction):
        """
        Navigates within the widget.
        Should return a tuple: (success, current_horizontal_index, total_horizontal_items).
        - success (bool): True if navigation was successful, False otherwise.
        - current_horizontal_index (int): The new index on the horizontal axis (e.g., column).
        - total_horizontal_items (int): The total number of items on the horizontal axis.
        For vertical navigation or widgets without a horizontal axis, this can return (success, 0, 1).
        """
        raise NotImplementedError

    def activate_current_element(self):
        raise NotImplementedError

class InvisibleUI:
    def __init__(self, main_frame):
        self.main_frame = main_frame
        self.categories = []
        self.current_category_index = 0
        self.current_element_index = 0
        self.active = False
        self.lock = threading.Lock()
        self.refresh_thread = None
        self.stop_event = threading.Event()
        self.hotkey_thread = None
        self.in_widget_mode = False
        self.active_widget = None
        self.active_widget_name = None
        self.build_structure()

    def refresh_status_bar(self):
        with self.lock:
            for category in self.categories:
                if category["name"] == _("Status Bar"):
                    category["elements"] = self.get_statusbar_items()
                    break

    def _run(self):
        while not self.stop_event.is_set():
            self.refresh_status_bar()
            time.sleep(1)

    def build_structure(self):
        apps = [app['name'] for app in get_applications()]
        games = [game['name'] for game in get_games()]
        widgets = self.load_widgets()

        def show_component_manager():
            if hasattr(self.main_frame, 'component_manager'):
                dialog = componentmanagergui.ComponentManagerDialog(self.main_frame, _("Component Manager"), self.main_frame.component_manager)
                dialog.ShowModal()
                dialog.Destroy()
            else:
                self.speak(_("Component manager is not available"))

        def show_settings():
            settings_frame = settingsgui.SettingsFrame(None, title=_("Settings"))
            settings_frame.Show()

        menu_actions = {
            _("Component Manager"): lambda: wx.CallAfter(show_component_manager),
            _("Program settings"): lambda: wx.CallAfter(show_settings),
            _("Back to graphical interface"): self.main_frame.restore_from_tray,
            _("Exit"): lambda: wx.CallAfter(self.main_frame.Close)
        }

        self.categories = [
            {"name": _("Applications"), "sound": "focus.ogg", "elements": apps if apps else [_("No applications")], "action": self.launch_app_by_name},
            {"name": _("Games"), "sound": "focus.ogg", "elements": games if games else [_("No games")], "action": self.launch_game_by_name},
            {"name": _("Widgets"), "sound": "focus.ogg", "elements": [w['name'] for w in widgets] if widgets else [_("No widgets found")], "action": self.activate_widget, "widget_data": widgets},
            {"name": _("Status Bar"), "sound": "statusbar.ogg", "elements": self.get_statusbar_items(), "action": self.activate_statusbar_item},
            {"name": _("Menu"), "sound": "applist.ogg", "elements": list(menu_actions.keys()), "action": lambda name: menu_actions[name]()}
        ]

    def load_widgets(self):
        widgets = []
        applets_dir = 'data/applets'
        if not os.path.exists(applets_dir):
            return widgets

        for widget_name in os.listdir(applets_dir):
            widget_dir = os.path.join(applets_dir, widget_name)
            init_file = os.path.join(widget_dir, 'init.py')
            if os.path.isdir(widget_dir) and os.path.exists(init_file):
                try:
                    spec = importlib.util.spec_from_file_location(widget_name, init_file)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    info = module.get_widget_info()
                    widgets.append({
                        "name": info["name"],
                        "type": info["type"],
                        "module": module
                    })
                except Exception as e:
                    print(f"Error loading widget '{widget_name}': {e}")
                    self.speak(_("Error loading widget: {}").format(widget_name))
        return widgets

    def get_statusbar_items(self):
        if self.main_frame and hasattr(self.main_frame, 'statusbar_listbox'):
            return [self.main_frame.statusbar_listbox.GetString(i) for i in range(self.main_frame.statusbar_listbox.GetCount())]
        return [_("No status bar data")]

    def speak(self, text, interrupt=True):
        threading.Thread(target=speaker.speak, args=(text,), kwargs={'interrupt': interrupt}).start()

    def navigate_category(self, step):
        with self.lock:
            if self.in_widget_mode: return
            num_categories = len(self.categories)
            old_index = self.current_category_index
            new_index = self.current_category_index + step
    
            if 0 <= new_index < num_categories:
                self.current_category_index = new_index
                self.current_element_index = 0
                new_category = self.categories[new_index]
                
                statusbar_index = -1
                try:
                    statusbar_index = [c['name'] for c in self.categories].index(_("Status Bar"))
                except ValueError:
                    pass

                if statusbar_index != -1 and old_index == statusbar_index and (new_index == statusbar_index - 1 or new_index == statusbar_index + 1):
                    play_applist_sound()
                else:
                    pan = 0.5
                    if num_categories > 1:
                        pan = new_index / (num_categories - 1)
                    play_sound(new_category.get('sound', 'focus.ogg'), pan=pan)
                
                self.speak(new_category['name'])
            else:
                play_endoflist_sound()

    def navigate_element(self, step):
        with self.lock:
            if self.in_widget_mode: return
            category = self.categories[self.current_category_index]
            num_elements = len(category['elements'])
            if num_elements == 0:
                play_endoflist_sound()
                return

            new_index = self.current_element_index + step
            
            if 0 <= new_index < num_elements:
                self.current_element_index = new_index
                element_name = category['elements'][self.current_element_index]
                
                # Pan the sound based on the element's position in the list
                pan = 0
                if num_elements > 1:
                    pan = new_index / (num_elements - 1)
                play_focus_sound(pan=pan)
                
                if category['name'] == _("Widgets") and 'widget_data' in category:
                    widget_type = category['widget_data'][self.current_element_index]['type']
                    self.speak(f"{element_name}, {_('button') if widget_type == 'button' else _('widget')}")
                else:
                    self.speak(element_name)
            else:
                play_endoflist_sound()

    def activate_element(self):
        with self.lock:
            if self.in_widget_mode:
                self.active_widget.activate_current_element()
                return

            category = self.categories[self.current_category_index]
            if not category['elements'] or category['elements'][0] in [_("No applications"), _("No games"), _("No widgets found")]:
                return
            
            element_name = category['elements'][self.current_element_index]
            play_sound('select.ogg')
            
            if element_name in [_("Back to graphical interface"), _("Exit")]:
                self.stop_listening()

            action = category.get('action')
            if action:
                try:
                    if category['name'] == _("Widgets"):
                        widget_data = category['widget_data'][self.current_element_index]
                        action(widget_data)
                    else:
                        action(element_name)
                except Exception as e:
                    self.speak(_("Error during activation: {}").format(e))
                    print(f"Error activating element '{element_name}': {e}")

    def activate_widget(self, widget_data):
        widget_type = widget_data['type']
        module = widget_data['module']

        if widget_type == "button":
            self.active_widget = module.get_widget_instance(self.speak)
            self.active_widget.activate_current_element()
        elif widget_type == "grid":
            self.active_widget = module.get_widget_instance(self.speak)
            self.active_widget_name = widget_data['name']
            self.enter_widget_mode()
        else:
            self.speak(_("Invalid widget type: {}").format(widget_type))

    def enter_widget_mode(self):
        self.in_widget_mode = True
        self.hotkey_thread.stop()
        if self.active_widget:
            self.active_widget.set_border()
        play_sound("widget.ogg")
        self.speak(_("In widget"))
        self.speak(f"{self.active_widget_name}, {self.active_widget.get_current_element()}")
        
        widget_hotkeys = {
            '<ctrl>+<shift>+<up>': lambda: self.navigate_widget('up'),
            '<ctrl>+<shift>+<down>': lambda: self.navigate_widget('down'),
            '<ctrl>+<shift>+<left>': lambda: self.navigate_widget('left'),
            '<ctrl>+<shift>+<right>': lambda: self.navigate_widget('right'),
            '<ctrl>+<shift>+<enter>': lambda: self.activate_element(),
            '<ctrl>+<shift>+<101>': lambda: self.activate_element(),
            '<ctrl>+<shift>+<backspace>': self.exit_widget_mode,
        }
        self.hotkey_thread = GlobalHotKeys(widget_hotkeys)
        self.hotkey_thread.start()

    def exit_widget_mode(self):
        self.in_widget_mode = False
        self.active_widget = None
        self.active_widget_name = None
        self.hotkey_thread.stop()
        play_sound("widgetclose.ogg")
        self.speak(_("Out of widget"))
        self.start_listening(rebuild=False) # Wznów główne skróty

    def navigate_widget(self, direction):
        navigation_result = self.active_widget.navigate(direction)
        
        success = False
        pan = 0.5  # Domyślnie wyśrodkowany

        if isinstance(navigation_result, tuple) and len(navigation_result) == 3:
            # Nowy format: (success, current_horizontal_index, total_horizontal_items)
            success, h_index, h_total = navigation_result
            if success and h_total > 1:
                pan = h_index / (h_total - 1)
        elif isinstance(navigation_result, bool):
            # Starszy format: success
            success = navigation_result
            if direction == "left":
                pan = 0.0
            elif direction == "right":
                pan = 1.0
        
        if not success:
            play_endoflist_sound()
        else:
            play_focus_sound(pan=pan)
            self.speak(self.active_widget.get_current_element())

    def launch_app_by_name(self, name):
        app = next((app for app in get_applications() if app.get("name") == name), None)
        if app: open_application(app)
        else: self.speak(_("Application not found: {}").format(name))

    def launch_game_by_name(self, name):
        game = next((game for game in get_games() if game.get("name") == name), None)
        if game: open_game(game)
        else: self.speak(_("Game not found: {}").format(name))

    def activate_statusbar_item(self, item_string):
        actions = {
            _("clock:"): self.main_frame.open_time_settings,
            _("battery level:"): self.main_frame.open_power_settings,
            _("volume:"): self.main_frame.open_volume_mixer,
            _("network status:"): self.main_frame.open_network_settings
        }
        for key, action in actions.items():
            if key in item_string:
                wx.CallAfter(action)
                return
        self.speak(_("No action for this item"))

    def start_listening(self, rebuild=True):
        if self.active and not rebuild:
             # Reaktywacja głównych skrótów po wyjściu z widgetu
            hotkeys = self.get_main_hotkeys()
            self.hotkey_thread = GlobalHotKeys(hotkeys)
            self.hotkey_thread.start()
            return

        if self.active: return
        self.active = True
        self.stop_event.clear()
        self.speak(_("Invisible interface active"))
        if rebuild:
            self.build_structure()
        
        self.refresh_thread = threading.Thread(target=self._run, daemon=True)
        self.refresh_thread.start()

        hotkeys = self.get_main_hotkeys()
        self.hotkey_thread = GlobalHotKeys(hotkeys)
        self.hotkey_thread.start()

    def get_main_hotkeys(self):
        return {
            '<ctrl>+<shift>+<up>': lambda: self.navigate_category(-1),
            '<ctrl>+<shift>+<down>': lambda: self.navigate_category(1),
            '<ctrl>+<shift>+<left>': lambda: self.navigate_element(-1),
            '<ctrl>+<shift>+<right>': lambda: self.navigate_element(1),
            '<ctrl>+<shift>+<enter>': lambda: self.activate_element(),
            '<ctrl>+<shift>+<101>': lambda: self.activate_element()
        }

    def stop_listening(self):
        if not self.active: return
        self.active = False
        self.stop_event.set()
        if self.refresh_thread: self.refresh_thread.join()
        if self.hotkey_thread: self.hotkey_thread.stop()
        self.hotkey_thread = None