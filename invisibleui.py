from pynput import keyboard
import threading
import time
import accessible_output3.outputs.auto
from sound import play_sound, play_focus_sound, play_endoflist_sound, play_statusbar_sound, play_applist_sound, play_voice_message, toggle_voice_message, is_voice_message_playing, is_voice_message_paused
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
import json
import traceback
import re
from key_blocker import start_key_blocking, stop_key_blocking, is_key_blocking_active
try:
    import telegram_client
    import messenger_client
except ImportError:
    telegram_client = None
    messenger_client = None
    print("Warning: Telegram/Messenger clients not available")

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
    def __init__(self, main_frame, component_manager=None):
        self.main_frame = main_frame
        self.component_manager = component_manager
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
        self.titan_ui_mode = False
        self.titan_im_mode = None  # 'telegram', 'messenger', or None
        self.current_contacts = []
        self.current_groups = []
        self.current_chat_history = []
        self.current_chat_user = None
        self.titan_im_submenu = None  # 'contacts', 'groups', 'history'
        self.current_voice_message_path = None
        self.current_selected_message = None
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
            if self.component_manager:
                dialog = componentmanagergui.ComponentManagerDialog(self.main_frame, _("Component Manager"), self.component_manager)
                dialog.ShowModal()
                dialog.Destroy()
            else:
                self.speak(_("Component manager is not available"))

        def show_settings():
            settings_frame = settingsgui.SettingsFrame(None, title=_("Settings"))
            settings_frame.Show()

        # Main menu actions
        main_menu_actions = {
            _("Component Manager"): lambda: wx.CallAfter(show_component_manager),
            _("Program settings"): lambda: wx.CallAfter(show_settings),
            _("Back to graphical interface"): self.main_frame.restore_from_tray,
            _("Exit"): lambda: wx.CallAfter(self.main_frame.Close)
        }

        # Component menu actions
        component_menu_actions = {}
        if self.component_manager:
            component_menu_functions = self.component_manager.get_component_menu_functions()
            for name, func in component_menu_functions.items():
                component_menu_actions[name] = func

        # Build Titan IM menu
        titan_im_elements = []
        if telegram_client:
            titan_im_elements.append(_("Telegram"))
        if messenger_client:
            titan_im_elements.append(_("Messenger"))
        
        if not titan_im_elements:
            titan_im_elements = [_("No IM clients available")]

        self.categories = [
            {"name": _("Applications"), "sound": "focus.ogg", "elements": apps if apps else [_("No applications")], "action": self.launch_app_by_name},
            {"name": _("Games"), "sound": "focus.ogg", "elements": games if games else [_("No games")], "action": self.launch_game_by_name},
            {"name": _("Widgets"), "sound": "focus.ogg", "elements": [w['name'] for w in widgets] if widgets else [_("No widgets found")], "action": self.activate_widget, "widget_data": widgets},
            {"name": _("Titan IM"), "sound": "titannet/iui.ogg", "elements": titan_im_elements, "action": self.activate_titan_im},
            {"name": _("Status Bar"), "sound": "statusbar.ogg", "elements": self.get_statusbar_items(), "action": self.activate_statusbar_item},
            {"name": _("Menu"), "sound": "applist.ogg", "elements": list(main_menu_actions.keys()), "action": lambda name: main_menu_actions[name]()}
        ]

        # Add Components as a sub-menu if there are any component menu actions
        if component_menu_actions:
            self.categories[-1]["elements"].append(_("Components"))
            self.categories.append({"name": _("Components"), "sound": "applist.ogg", "elements": list(component_menu_actions.keys()), "action": lambda name: component_menu_actions[name]()})


    def load_widgets(self):
        widgets = []
        applets_dir = 'data/applets'
        if not os.path.exists(applets_dir):
            return widgets

        for applet_name in os.listdir(applets_dir):
            applet_dir = os.path.join(applets_dir, applet_name)
            if not os.path.isdir(applet_dir):
                continue

            # Sprawdź plik init.py dla wstecznej zgodności
            init_file = os.path.join(applet_dir, 'init.py')
            if os.path.exists(init_file):
                try:
                    spec = importlib.util.spec_from_file_location(applet_name, init_file)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    info = module.get_widget_info()
                    widgets.append({
                        "name": info["name"],
                        "type": info["type"],
                        "module": module
                    })
                    continue # Przejdź do następnego apletu
                except Exception as e:
                    print(f"Error loading widget from init.py '{applet_name}': {e}")
                    self.speak(_("Error loading widget: {}").format(applet_name))

            # Nowy system oparty na applet.json i main.py
            json_path = os.path.join(applet_dir, 'applet.json')
            main_py_path = os.path.join(applet_dir, 'main.py')

            if os.path.exists(json_path) and os.path.exists(main_py_path):
                try:
                    spec = importlib.util.spec_from_file_location(f"applets.{applet_name}.main", main_py_path)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[spec.name] = module
                    spec.loader.exec_module(module)
                    
                    # Po załadowaniu modułu, gettext wewnątrz niego jest już aktywny
                    info = module.get_widget_info()
                    
                    widgets.append({
                        "name": info.get("name", applet_name),
                        "type": info.get("type", "grid"),
                        "module": module
                    })
                except Exception as e:
                    print(f"Error loading applet '{applet_name}': {e}")
                    traceback.print_exc() # Print full traceback for debugging
                    self.speak(_("Error loading widget: {}").format(applet_name))
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
                    if new_category['name'] == _("Status Bar"):
                        play_statusbar_sound()
                    else:
                        pan = 0.5
                        if num_categories > 1:
                            pan = new_index / (num_categories - 1)
                        play_sound(new_category.get('sound', 'focus.ogg'), pan=pan)
                
                speak_text = new_category['name']
                if get_setting('announce_first_item', 'False', section='invisible_interface').lower() == 'true':
                    if new_category['elements']:
                        speak_text += f", {new_category['elements'][0]}"
                self.speak(speak_text)
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
                
                announce_index = get_setting('announce_index', 'False', section='invisible_interface').lower() == 'true'
                announce_widget_type = get_setting('announce_widget_type', 'False', section='invisible_interface').lower() == 'true'
                
                speak_text = element_name
                if announce_index:
                    speak_text += ", " + _("{} of {}").format(self.current_element_index + 1, num_elements)
                
                if announce_widget_type and category['name'] == _("Widgets") and 'widget_data' in category:
                    widget_type = category['widget_data'][self.current_element_index]['type']
                    speak_text += f", {_('button') if widget_type == 'button' else _('widget')}"
                
                self.speak(speak_text)
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
            
            # Special handling for chat history with voice messages
            if (self.titan_ui_mode and self.titan_im_mode and 
                self.titan_im_submenu == 'history'):
                # Check if current element contains voice message
                self.check_for_voice_message(element_name)
                if self.current_voice_message_path:
                    # This is a voice message - toggle play/pause
                    self.handle_voice_message_toggle()
                    return
            
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
        if self.active_widget:
            self.active_widget.set_border()
        play_sound("widget.ogg")
        self.speak(_("In widget"))
        self.speak(f"{self.active_widget_name}, {self.active_widget.get_current_element()}")
        self._update_hotkeys()

    def exit_widget_mode(self):
        if not self.in_widget_mode: return
        self.in_widget_mode = False
        self.active_widget = None
        self.active_widget_name = None
        play_sound("widgetclose.ogg")
        self.speak(_("Out of widget"))
        self._update_hotkeys()

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
    
    def activate_titan_im(self, platform_name):
        """Activate Titan IM platform (Telegram/Messenger)"""
        if platform_name == _("No IM clients available"):
            self.speak(_("No IM clients available"))
            return
            
        # Set current platform
        if platform_name == _("Telegram"):
            self.titan_im_mode = 'telegram'
        elif platform_name == _("Messenger"):
            self.titan_im_mode = 'messenger'
        else:
            return
        
        # Check if connected
        is_connected = False
        if self.titan_im_mode == 'telegram' and telegram_client:
            is_connected = telegram_client.is_connected()
        elif self.titan_im_mode == 'messenger' and messenger_client:
            is_connected = messenger_client.is_connected()
        
        if not is_connected:
            self.speak(_("Not connected to {}").format(platform_name))
            return
        
        # Create submenu
        submenu_elements = [_("Contacts"), _("Groups"), _("Back")]
        
        # Add submenu category
        titan_im_submenu_category = {
            "name": _("{} Menu").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": submenu_elements,
            "action": self.activate_titan_im_submenu,
            "parent_mode": self.titan_im_mode
        }
        
        # Insert submenu after current category
        current_index = self.current_category_index
        self.categories.insert(current_index + 1, titan_im_submenu_category)
        
        # Navigate to submenu
        self.current_category_index += 1
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'focus.ogg'))
        self.speak(f"{category['name']}, {category['elements'][0]}")
    
    def activate_titan_im_submenu(self, submenu_name):
        """Activate Titan IM submenu item"""
        if submenu_name == _("Back"):
            # Remove submenu and go back
            self.categories.pop(self.current_category_index)
            self.current_category_index -= 1
            self.current_element_index = 0
            self.titan_im_submenu = None
            
            category = self.categories[self.current_category_index]
            play_sound(category.get('sound', 'focus.ogg'))
            self.speak(f"{category['name']}, {category['elements'][self.current_element_index]}")
            return
        
        if submenu_name == _("Contacts"):
            self.load_titan_im_contacts()
        elif submenu_name == _("Groups"):
            self.load_titan_im_groups()
    
    def load_titan_im_contacts(self):
        """Load contacts for current IM platform"""
        contacts = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            contacts = telegram_client.get_contacts()
        elif self.titan_im_mode == 'messenger' and messenger_client:
            conversations = messenger_client.get_conversations()
            # Convert conversations to contact format
            contacts = [{'username': conv['name'], 'type': 'contact'} for conv in conversations]
        
        if not contacts:
            contacts = [_("No contacts")]
        else:
            contacts = [contact['username'] for contact in contacts]
        
        self.current_contacts = contacts
        
        # Create contacts category
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        contacts_category = {
            "name": _("{} Contacts").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": contacts + [_("Back")],
            "action": self.activate_titan_im_contact,
            "parent_mode": self.titan_im_mode
        }
        
        # Replace current submenu with contacts
        self.categories[self.current_category_index] = contacts_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'focus.ogg'))
        self.speak(f"{category['name']}, {len(contacts)} {_('contacts')}, {category['elements'][0]}")
    
    def load_titan_im_groups(self):
        """Load groups for current IM platform"""
        groups = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            groups = telegram_client.get_group_chats()
        elif self.titan_im_mode == 'messenger' and messenger_client:
            # Messenger doesn't separate groups clearly, so we skip for now
            groups = []
        
        if not groups:
            groups = [_("No groups")]
        else:
            groups = [group['name'] if 'name' in group else group.get('title', 'Unknown') for group in groups]
        
        self.current_groups = groups
        
        # Create groups category
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        groups_category = {
            "name": _("{} Groups").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": groups + [_("Back")],
            "action": self.activate_titan_im_group,
            "parent_mode": self.titan_im_mode
        }
        
        # Replace current submenu with groups
        self.categories[self.current_category_index] = groups_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'focus.ogg'))
        self.speak(f"{category['name']}, {len(groups)} {_('groups')}, {category['elements'][0]}")
    
    def activate_titan_im_contact(self, contact_name):
        """Activate contact to view chat history"""
        if contact_name == _("Back") or contact_name == _("No contacts"):
            self.go_back_to_titan_im_submenu()
            return
        
        self.current_chat_user = contact_name
        self.load_chat_history(contact_name)
    
    def activate_titan_im_group(self, group_name):
        """Activate group to view chat history"""
        if group_name == _("Back") or group_name == _("No groups"):
            self.go_back_to_titan_im_submenu()
            return
        
        self.current_chat_user = group_name
        self.load_group_chat_history(group_name)
    
    def load_chat_history(self, contact_name):
        """Load private chat history"""
        self.current_chat_history = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            # Request chat history - this will be received via callback
            telegram_client.get_chat_history(contact_name)
        elif self.titan_im_mode == 'messenger' and messenger_client:
            # Messenger doesn't have direct history API in current implementation
            pass
        
        # Create temporary history view
        self.show_chat_history_view(contact_name, is_group=False)
    
    def load_group_chat_history(self, group_name):
        """Load group chat history"""
        self.current_chat_history = []
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            # Request group chat history - this will be received via callback
            telegram_client.get_group_chat_history(group_name)
        elif self.titan_im_mode == 'messenger' and messenger_client:
            # Messenger group history not implemented
            pass
        
        # Create temporary history view
        self.show_chat_history_view(group_name, is_group=True)
    
    def show_chat_history_view(self, chat_name, is_group=False):
        """Show chat history interface"""
        # Create history elements - will be populated by callback
        history_elements = [_("Loading messages..."), _("Send message"), _("Back")]
        
        chat_type = _("Group") if is_group else _("Contact")
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        
        history_category = {
            "name": _("{} {} - {}").format(platform_name, chat_type, chat_name),
            "sound": "titannet/iui.ogg",
            "elements": history_elements,
            "action": self.activate_chat_history_item,
            "parent_mode": self.titan_im_mode,
            "chat_name": chat_name,
            "is_group": is_group
        }
        
        # Replace current category with history view
        self.categories[self.current_category_index] = history_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'focus.ogg'))
        self.speak(f"{category['name']}, {category['elements'][0]}")
    
    def activate_chat_history_item(self, item_name):
        """Activate chat history item"""
        if item_name == _("Back"):
            self.go_back_to_titan_im_submenu()
            return
        elif item_name == _("Send message"):
            self.show_send_message_dialog()
            return
        elif item_name == _("Loading messages..."):
            self.speak(_("Messages are loading, please wait"))
            return
        
        # Store current selected message
        self.current_selected_message = item_name
        
        # Check if this message contains voice message
        self.check_for_voice_message(item_name)
        
        # This is a message - read it
        self.speak(item_name)
    
    def check_for_voice_message(self, message_text):
        """Check if message contains voice message and extract path"""
        # Look for voice message patterns like [Voice: path/to/file.ogg]
        voice_pattern = r'\[Voice:\s*([^\]]+)\]'
        match = re.search(voice_pattern, message_text)
        
        if match:
            voice_path = match.group(1).strip()
            self.current_voice_message_path = voice_path
            play_sound('titannet/voice_select.ogg')
        else:
            self.current_voice_message_path = None
    
    def handle_voice_message_toggle(self):
        """Handle play/pause of voice messages"""
        if self.current_voice_message_path:
            success = toggle_voice_message()
            if success:
                if is_voice_message_playing():
                    play_sound('titannet/voice_play.ogg')
                    self.speak(_("Playing voice message"))
                elif is_voice_message_paused():
                    play_sound('titannet/voice_pause.ogg')
                    self.speak(_("Voice message paused"))
            else:
                # Try to start playing the voice message
                if play_voice_message(self.current_voice_message_path):
                    play_sound('titannet/voice_play.ogg')
                    self.speak(_("Playing voice message"))
                else:
                    play_sound('error.ogg')
                    self.speak(_("Error playing voice message"))
        else:
            self.speak(_("No voice message selected"))
    
    def handle_titan_enter(self):
        """Handle Titan+Enter key combination for voice message playback and widget actions"""
        # Handle widget mode first
        if self.in_widget_mode and self.active_widget:
            # Check if widget has handle_titan_enter method
            if hasattr(self.active_widget, 'handle_titan_enter'):
                self.active_widget.handle_titan_enter()
                return
        
        if (self.titan_ui_mode and self.titan_im_mode and 
            self.titan_im_submenu == 'history'):
            # Check if current element contains voice message
            category = self.categories[self.current_category_index]
            if category['elements']:
                element_name = category['elements'][self.current_element_index]
                self.check_for_voice_message(element_name)
                if self.current_voice_message_path:
                    self.handle_voice_message_toggle()
                    return
        
        # If not in a voice message context, just speak current element
        if self.titan_ui_mode:
            category = self.categories[self.current_category_index]
            if category['elements']:
                element_name = category['elements'][self.current_element_index]
                self.speak(element_name)
    
    def show_send_message_dialog(self):
        """Show dialog to send message"""
        if not self.current_chat_user:
            return
        
        def show_dialog():
            dlg = wx.TextEntryDialog(
                None,
                _("Enter message to send to {}:").format(self.current_chat_user),
                _("Send Message")
            )
            
            if dlg.ShowModal() == wx.ID_OK:
                message = dlg.GetValue()
                if message.strip():
                    self.send_titan_im_message(self.current_chat_user, message)
            
            dlg.Destroy()
        
        wx.CallAfter(show_dialog)
    
    def send_titan_im_message(self, recipient, message):
        """Send message through current IM platform"""
        success = False
        
        if self.titan_im_mode == 'telegram' and telegram_client:
            # Check if it's a group
            category = self.categories[self.current_category_index]
            if category.get('is_group', False):
                success = telegram_client.send_group_message(recipient, message)
            else:
                success = telegram_client.send_message(recipient, message)
        elif self.titan_im_mode == 'messenger' and messenger_client:
            success = messenger_client.send_message(recipient, message)
        
        if success:
            self.speak(_("Message sent to {}").format(recipient))
        else:
            self.speak(_("Failed to send message"))
    
    def go_back_to_titan_im_submenu(self):
        """Go back to Titan IM submenu"""
        platform_name = _("Telegram") if self.titan_im_mode == 'telegram' else _("Messenger")
        submenu_elements = [_("Contacts"), _("Groups"), _("Back")]
        
        titan_im_submenu_category = {
            "name": _("{} Menu").format(platform_name),
            "sound": "titannet/iui.ogg",
            "elements": submenu_elements,
            "action": self.activate_titan_im_submenu,
            "parent_mode": self.titan_im_mode
        }
        
        self.categories[self.current_category_index] = titan_im_submenu_category
        self.current_element_index = 0
        
        category = self.categories[self.current_category_index]
        play_sound(category.get('sound', 'focus.ogg'))
        self.speak(f"{category['name']}, {category['elements'][0]}")
    
    def update_chat_history(self, history_data):
        """Update chat history when received from callback"""
        if not history_data or history_data.get('type') not in ['chat_history', 'group_chat_history']:
            return
        
        messages = history_data.get('messages', [])
        
        # Format messages for display
        formatted_messages = []
        for msg in messages[-10:]:  # Show last 10 messages
            sender = msg.get('sender_username', 'Unknown')
            text = msg.get('message', '')
            timestamp = msg.get('timestamp', '')
            voice_file = msg.get('voice_file', '')  # Path to voice message file
            
            # Format timestamp
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                time_str = dt.strftime('%H:%M')
            except:
                time_str = ''
            
            if text or voice_file:
                message_content = text
                
                # Add voice message indicator
                if voice_file:
                    voice_indicator = f"[Voice: {voice_file}]"
                    if message_content:
                        message_content += f" {voice_indicator}"
                    else:
                        message_content = f"{_('Voice message')} {voice_indicator}"
                
                if time_str:
                    formatted_msg = f"[{time_str}] {sender}: {message_content}"
                else:
                    formatted_msg = f"{sender}: {message_content}"
                formatted_messages.append(formatted_msg)
        
        # Update current category if it's a chat history view
        if (self.current_category_index < len(self.categories) and 
            'chat_name' in self.categories[self.current_category_index]):
            
            category = self.categories[self.current_category_index]
            
            # Replace loading message with actual history
            new_elements = formatted_messages + [_("Send message"), _("Back")]
            category['elements'] = new_elements
            
            # Announce update
            if formatted_messages:
                self.speak(_("Chat history loaded, {} messages").format(len(formatted_messages)))
            else:
                self.speak(_("No messages in chat history"))

    def start_listening(self, rebuild=True):
        if self.active: return
        self.active = True
        self.stop_event.clear()
        self.speak(_("Invisible interface active"))
        if rebuild:
            self.build_structure()
        
        # Register callbacks for message history updates
        if telegram_client:
            telegram_client.add_message_callback(self._handle_im_message_callback)
        if messenger_client:
            messenger_client.add_message_callback(self._handle_im_message_callback)
        
        self.refresh_thread = threading.Thread(target=self._run, daemon=True)
        self.refresh_thread.start()

        self._update_hotkeys()
        
    def _handle_im_message_callback(self, message_data):
        """Handle incoming message callbacks from IM clients"""
        try:
            if message_data.get('type') in ['chat_history', 'group_chat_history']:
                # Update chat history in UI thread
                wx.CallAfter(self.update_chat_history, message_data)
        except Exception as e:
            print(f"Error handling IM message callback: {e}")

    def stop_listening(self):
        if not self.active: return
        self.active = False
        self.titan_ui_mode = False
        self.in_widget_mode = False
        self.titan_im_mode = None
        self.titan_im_submenu = None
        self.current_chat_user = None
        # Stop key blocking when stopping invisible UI
        stop_key_blocking()
        self.stop_event.set()
        if self.refresh_thread: self.refresh_thread.join()
        if self.hotkey_thread:
            self.hotkey_thread.stop()
        self.hotkey_thread = None

    def _update_hotkeys(self):
        if self.hotkey_thread:
            self.hotkey_thread.stop()

        hotkeys = {}
        
        # The tilde key is always available to toggle TUI mode if enabled
        if get_setting('enable_titan_ui', 'False', section='invisible_interface').lower() == 'true':
            hotkeys['`'] = self.toggle_titan_ui_mode
            # Titan+Enter for voice message playback (works in both modes)
            hotkeys['`+<enter>'] = self.handle_titan_enter
        
        # Alt+F1 for Start Menu (when minimized to tray) - Linux style only
        import platform
        if platform.system() == "Windows":
            hotkeys['<alt>+<f1>'] = self.show_start_menu

        if self.in_widget_mode:
            if self.titan_ui_mode:
                # TUI mode inside a widget
                hotkeys.update({
                    '<up>': lambda: self.navigate_widget('up'),
                    '<down>': lambda: self.navigate_widget('down'),
                    '<left>': lambda: self.navigate_widget('left'),
                    '<right>': lambda: self.navigate_widget('right'),
                    '<enter>': self.activate_element,
                    '<space>': self.activate_element,
                    '<backspace>': self.exit_widget_mode,
                    '<esc>': self.exit_widget_mode,
                })
            else:
                # Normal mode inside a widget
                hotkeys.update({
                    '<ctrl>+<shift>+<up>': lambda: self.navigate_widget('up'),
                    '<ctrl>+<shift>+<down>': lambda: self.navigate_widget('down'),
                    '<ctrl>+<shift>+<left>': lambda: self.navigate_widget('left'),
                    '<ctrl>+<shift>+<right>': lambda: self.navigate_widget('right'),
                    '<ctrl>+<shift>+<enter>': self.activate_element,
                    '<ctrl>+<shift>+<101>': self.activate_element,
                    '<ctrl>+<shift>+<backspace>': self.exit_widget_mode,
                })
                # Don't register simple keys at all when in normal mode - they'll be blocked by key_blocker
        else:
            if self.titan_ui_mode:
                # TUI mode in main view
                hotkeys.update({
                    '<up>': lambda: self.navigate_category(-1),
                    '<down>': lambda: self.navigate_category(1),
                    '<left>': lambda: self.navigate_element(-1),
                    '<right>': lambda: self.navigate_element(1),
                    '<enter>': self.activate_element,
                    '<space>': self.activate_element,
                    '<backspace>': lambda: None,  # No action in main view
                    '<esc>': lambda: None,       # No action in main view
                })
            else:
                # Normal mode in main view
                hotkeys.update({
                    '<ctrl>+<shift>+<up>': lambda: self.navigate_category(-1),
                    '<ctrl>+<shift>+<down>': lambda: self.navigate_category(1),
                    '<ctrl>+<shift>+<left>': lambda: self.navigate_element(-1),
                    '<ctrl>+<shift>+<right>': lambda: self.navigate_element(1),
                    '<ctrl>+<shift>+<enter>': self.activate_element,
                    '<ctrl>+<shift>+<101>': self.activate_element,
                })
                # Don't register simple keys at all when in normal mode - they'll be blocked by key_blocker

        self.hotkey_thread = GlobalHotKeys(hotkeys)
        self.hotkey_thread.start()

    def toggle_titan_ui_mode(self):
        self.titan_ui_mode = not self.titan_ui_mode
        if self.titan_ui_mode:
            play_sound('TUI_open.ogg')
            self.speak(_("Titan UI on"))
            # Start blocking navigation keys when Titan UI is enabled
            keys_to_block = {'up', 'down', 'left', 'right', 'enter', 'space', 'escape', 'backspace'}
            success = start_key_blocking(keys_to_block)
            if not success:
                print("Warning: Could not enable full key blocking. Some keys may still reach other applications.")
        else:
            play_sound('TUI_close.ogg')
            self.speak(_("Titan UI off"))
            # Stop blocking keys when Titan UI is disabled
            stop_key_blocking()
        self._update_hotkeys()
    
    def show_start_menu(self):
        """Pokaż klasyczne Menu Start gdy aplikacja jest zminimalizowana"""
        try:
            # Sprawdź czy aplikacja główna ma start menu
            if hasattr(self.main_frame, 'start_menu') and self.main_frame.start_menu:
                import platform
                if platform.system() == "Windows":
                    # Pokaż menu Start
                    wx.CallAfter(self.main_frame.start_menu.show_menu)
                    self.speak(_("Menu Start"))
        except Exception as e:
            print(f"Error showing start menu from invisible UI: {e}")