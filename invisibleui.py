import keyboard
import threading
import time
import accessible_output3.outputs.auto
from sound import play_sound, play_focus_sound, play_endoflist_sound, play_statusbar_sound, play_applist_sound
from settings import load_settings, get_setting
from translation import set_language
from app_manager import get_applications, open_application
from game_manager import get_games, open_game
# Te importy mogą wymagać dostosowania, jeśli funkcje są w innych miejscach
import componentmanagergui
import settingsgui
import sys
import wx

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Inicjalizacja mowy, tak jak w main.py
speaker = accessible_output3.outputs.auto.Auto()

class InvisibleUI:
    def __init__(self, main_frame):
        self.main_frame = main_frame
        self.categories = []
        self.current_category_index = 0
        self.current_element_index = 0
        self.active = False
        self.lock = threading.Lock()
        self.build_structure()

    def build_structure(self):
        """Buduje strukturę nawigacyjną interfejsu."""
        # Pobieranie list aplikacji i gier
        apps = [app['name'] for app in get_applications()]
        games = [game['name'] for game in get_games()]

        # Definicje akcji dla menu, dostosowane do wxPython
        def show_component_manager():
            # Menedżer komponentów wymaga instancji ComponentManager z głównej ramki
            if hasattr(self.main_frame, 'component_manager'):
                dialog = componentmanagergui.ComponentManagerDialog(self.main_frame, _("Component Manager"), self.main_frame.component_manager)
                dialog.ShowModal()
                dialog.Destroy()
            else:
                self.speak(_("Component manager is not available"))

        def show_settings():
            # Tworzymy i pokazujemy nową ramkę ustawień
            settings_frame = settingsgui.SettingsFrame(None, title=_("Settings"))
            settings_frame.Show()

        menu_actions = {
            _("Component Manager"): lambda: wx.CallAfter(show_component_manager),
            _("Program settings"): lambda: wx.CallAfter(show_settings),
            _("Back to graphical interface"): self.main_frame.restore_from_tray,
            _("Exit"): lambda: wx.CallAfter(self.main_frame.Close)
        }

        self.categories = [
            {
                "name": _("Applications"),
                "sound": "applist.ogg", # Dźwięk używany przy przejściu z Paska Statusu
                "elements": apps if apps else [_("No applications")],
                "action": self.launch_app_by_name
            },
            {
                "name": _("Games"),
                "sound": "focus.ogg", # Dźwięk używany przy przejściu z Aplikacji
                "elements": games if games else [_("No games")],
                "action": self.launch_game_by_name
            },
            {
                "name": _("Status Bar"),
                "sound": "statusbar.ogg",
                "elements": self.get_statusbar_items(), # Przechowujemy pełne stringi
                "action": self.activate_statusbar_item
            },
            {
                "name": _("Menu"),
                "sound": "focus.ogg",
                "elements": list(menu_actions.keys()),
                "action": lambda name: menu_actions[name]()
            }
        ]

    def get_statusbar_items(self):
        """Pobiera aktualne elementy paska statusu z głównego okna."""
        if self.main_frame and hasattr(self.main_frame, 'statusbar_listbox'):
            return [self.main_frame.statusbar_listbox.GetString(i) for i in range(self.main_frame.statusbar_listbox.GetCount())]
        return [_("No status bar data")]

    def speak(self, text, interrupt=True):
        """Wątkowo-bezpieczna funkcja mówienia."""
        threading.Thread(target=speaker.speak, args=(text,), kwargs={'interrupt': interrupt}).start()

    def navigate_category(self, step):
        """Nawigacja w górę/dół między kategoriami z zaawansowaną logiką dźwięku i mowy."""
        with self.lock:
            num_categories = len(self.categories)
            old_index = self.current_category_index
            new_index = self.current_category_index + step

            if 0 <= new_index < num_categories:
                self.current_category_index = new_index
                self.current_element_index = 0
                
                old_category = self.categories[old_index]
                new_category = self.categories[new_index]
                
                # Zaawansowana logika dźwięku
                sound_to_play = new_category['sound'] # Dźwięk domyślny
                if new_category['name'] == _('Status Bar'):
                    sound_to_play = 'statusbar.ogg'
                elif old_category['name'] == _('Status Bar'):
                    sound_to_play = 'applist.ogg'
                elif (old_category['name'] == _('Applications') and new_category['name'] == _('Games')) or \
                     (old_category['name'] == _('Games') and new_category['name'] == _('Applications')):
                    sound_to_play = 'focus.ogg'

                play_sound(sound_to_play)

                # Zaawansowana logika mowy
                if new_category['name'] == _('Status Bar'):
                    self.speak(_("Status bar"))
                    # Od razu odczytaj pierwszy element
                    if new_category['elements']:
                        self.speak(new_category['elements'][0], interrupt=False)
                elif new_category['name'] == _('Menu'):
                    self.speak(_("Titan Menu"))
                else:
                    self.speak(f"{new_category['name']}, {self.current_category_index + 1} z {num_categories}")
            else:
                play_endoflist_sound()

    def navigate_element(self, step):
        """Nawigacja w lewo/prawo między elementami w kategorii."""
        with self.lock:
            category = self.categories[self.current_category_index]
            num_elements = len(category['elements'])
            
            new_index = self.current_element_index + step
            
            if 0 <= new_index < num_elements:
                self.current_element_index = new_index
                element_name = category['elements'][self.current_element_index]
                
                # Dźwięk stereo
                settings = load_settings()
                stereo_enabled = settings.get('sound', {}).get('stereo_sound', 'False').lower() in ['true', '1']
                pan = None
                if stereo_enabled and num_elements > 1:
                    pan = self.current_element_index / (num_elements - 1)
                
                play_focus_sound(pan=pan)

                # Logika mowy
                if category['name'] == _('Status Bar'):
                    self.speak(element_name) # Odczytaj pełną informację
                else:
                    self.speak(f"{element_name}, {self.current_element_index + 1} z {num_elements}")
            else:
                play_endoflist_sound()

    def activate_element(self):
        """Aktywuje wybrany element."""
        with self.lock:
            category = self.categories[self.current_category_index]
            element_name = category['elements'][self.current_element_index]
            
            play_sound('select.ogg')
            self.speak(_("Activated: {}").format(element_name))
            
            if element_name in [_("Back to graphical interface"), _("Exit")]:
                self.stop_listening()

            action = category.get('action')
            if action:
                try:
                    action(element_name)
                except Exception as e:
                    self.speak(_("Error during activation: {}").format(e))
                    print(f"Error activating element '{element_name}': {e}")

    # --- Funkcje pomocnicze do akcji ---

    def launch_app_by_name(self, name):
        for app in get_applications():
            if app.get("name") == name:
                open_application(app)
                return
        self.speak(_("Application not found: {}").format(name))

    def launch_game_by_name(self, name):
        for game in get_games():
            if game.get("name") == name:
                open_game(game)
                return
        self.speak(_("Game not found: {}").format(name))

    def activate_statusbar_item(self, item_string):
        """Wywołuje odpowiednią akcję dla elementu paska statusu."""
        if _("clock:") in item_string:
            wx.CallAfter(self.main_frame.open_time_settings)
        elif _("battery level:") in item_string:
            wx.CallAfter(self.main_frame.open_power_settings)
        elif _("volume:") in item_string:
            wx.CallAfter(self.main_frame.open_volume_mixer)
        elif _("network status:") in item_string:
            wx.CallAfter(self.main_frame.open_network_settings)
        else:
            self.speak(_("No action for this item"))

    # --- Kontrola nasłuchiwania ---

    def start_listening(self):
        """Aktywuje nasłuchiwanie globalnych skrótów klawiszowych."""
        if self.active:
            return
        self.active = True
        self.speak(_("Invisible interface active"))
        # Odśwież strukturę na wypadek zmian
        self.build_structure()
        
        # Używamy suppress=True, aby inne aplikacje nie otrzymywały tych wciśnięć
        keyboard.add_hotkey('ctrl+shift+up', lambda: self.navigate_category(-1), suppress=True)
        keyboard.add_hotkey('ctrl+shift+down', lambda: self.navigate_category(1), suppress=True)
        keyboard.add_hotkey('ctrl+shift+left', lambda: self.navigate_element(-1), suppress=True)
        keyboard.add_hotkey('ctrl+shift+right', lambda: self.navigate_element(1), suppress=True)
        keyboard.add_hotkey('ctrl+shift+enter', self.activate_element, suppress=True)

    def stop_listening(self):
        """Dezaktywuje nasłuchiwanie."""
        if not self.active:
            return
        self.active = False
        keyboard.remove_all_hotkeys()
        # Nie mówimy nic przy deaktywacji, bo zwykle dzieje się to w tle przywracania okna
