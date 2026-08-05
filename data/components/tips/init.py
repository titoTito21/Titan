# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import threading
import time
import random
import configparser
import wx
import platform
from src.titan_core.sound import play_sound, resource_path
from src.titan_core.translation import _

try:
    import accessible_output3.outputs.auto as _ao3
    _ao3_speaker = _ao3.Auto()
except Exception:
    _ao3_speaker = None

# Ścieżki
def get_config_path():
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        config_dir = os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings')
    elif platform.system() == 'Darwin':  # macOS
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings')
    else:  # Zakładamy Linux lub inne systemy Unix
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, '.config', 'Titosoft', 'Titan', 'appsettings')
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    config_path = os.path.join(config_dir, 'tips.ini')
    return config_path

CONFIG_PATH = get_config_path()
TIPS_FILE_PATH = resource_path(os.path.join('data', 'docu', 'tips.tdoc'))

# Interval options: internal keys (stored in config) -> seconds
INTERVAL_OPTIONS = {
    'every_minute': 60,
    'every_5_minutes': 5 * 60,
    'every_10_minutes': 10 * 60,
    'every_15_minutes': 15 * 60,
    'every_hour': 60 * 60,
    'disabled': None
}

# Backward compatibility: map legacy Polish keys to new English keys
_LEGACY_KEY_MAP = {
    'co minutę': 'every_minute',
    'co 5 minut': 'every_5_minutes',
    'co 10 minut': 'every_10_minutes',
    'co 15 minut': 'every_15_minutes',
    'co godzinę': 'every_hour',
    'wyłączone': 'disabled',
}

# Display labels for the UI (translated)
INTERVAL_LABELS = {
    'every_minute': _("Every minute"),
    'every_5_minutes': _("Every 5 minutes"),
    'every_10_minutes': _("Every 10 minutes"),
    'every_15_minutes': _("Every 15 minutes"),
    'every_hour': _("Every hour"),
    'disabled': _("Disabled"),
}

DEFAULT_SETTINGS = {
    'interval': 'every_15_minutes'
}

# Ładowanie ustawień
config = configparser.ConfigParser()
if not os.path.exists(CONFIG_PATH):
    config['Tips'] = DEFAULT_SETTINGS
    with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
        config.write(configfile)
else:
    config.read(CONFIG_PATH, encoding='utf-8')
    if 'Tips' not in config:
        config['Tips'] = DEFAULT_SETTINGS
        with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
    # Migrate legacy Polish keys to English keys
    current_key = config['Tips'].get('interval', 'every_15_minutes')
    if current_key in _LEGACY_KEY_MAP:
        config['Tips']['interval'] = _LEGACY_KEY_MAP[current_key]
        with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
            config.write(configfile)

# Ładowanie porad
def load_tips():
    tips = []
    if os.path.exists(TIPS_FILE_PATH):
        with open(TIPS_FILE_PATH, 'r', encoding='utf-8') as f:
            tips = f.readlines()
        tips = [tip.strip() for tip in tips if tip.strip()]
    else:
        print(f"Tips file not found: {TIPS_FILE_PATH}")
    return tips

# Funkcja mowy
def speak(text):
    def speak_thread():
        # 1) accessible_output3 – preferred (VoiceOver / NVDA / JAWS / Orca)
        if _ao3_speaker:
            try:
                _ao3_speaker.speak(text, interrupt=True)
                return
            except Exception:
                pass
        # 2) Platform fallback when ao3 is unavailable
        try:
            _sys = platform.system()
            if _sys == 'Windows':
                import win32com.client
                win32com.client.Dispatch("SAPI.SpVoice").Speak(text)
            elif _sys == 'Darwin':
                subprocess.Popen(['say', text])
            else:
                subprocess.Popen(['spd-say', text])
        except Exception:
            pass
    threading.Thread(target=speak_thread, daemon=True).start()

# Klasa TipManager
class TipManager(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True
        self.tips = load_tips()
        self.interval_option = config['Tips'].get('interval', 'every_15_minutes')
        if self.interval_option in _LEGACY_KEY_MAP:
            self.interval_option = _LEGACY_KEY_MAP[self.interval_option]
        self.interval = INTERVAL_OPTIONS.get(self.interval_option)
    
    def run(self):
        while self.running and self.interval is not None and self.tips:
            time.sleep(self.interval)
            if not self.running:
                break
            play_sound('ui/tip.ogg')
            time.sleep(2)
            tip = random.choice(self.tips)
            speak(_("Tip: %s") % tip)
    
    def update_settings(self):
        self.interval_option = config['Tips'].get('interval', 'every_15_minutes')
        if self.interval_option in _LEGACY_KEY_MAP:
            self.interval_option = _LEGACY_KEY_MAP[self.interval_option]
        self.interval = INTERVAL_OPTIONS.get(self.interval_option)
    
    def stop(self):
        self.running = False

# Okno ustawień
def show_settings_dialog(parent):
    app = wx.App(False)
    frame = wx.Frame(parent, wx.ID_ANY, _("Tips Settings"))
    panel = wx.Panel(frame, wx.ID_ANY)

    vbox = wx.BoxSizer(wx.VERTICAL)

    interval_label = wx.StaticText(panel, label=_("Speak tips:"))
    interval_keys = list(INTERVAL_OPTIONS.keys())
    interval_labels = [INTERVAL_LABELS.get(k, k) for k in interval_keys]
    interval_choice = wx.Choice(panel, choices=interval_labels)
    current_interval = config['Tips'].get('interval', 'every_15_minutes')
    if current_interval in _LEGACY_KEY_MAP:
        current_interval = _LEGACY_KEY_MAP[current_interval]
    try:
        current_idx = interval_keys.index(current_interval)
        interval_choice.SetSelection(current_idx)
    except ValueError:
        interval_choice.SetSelection(3)  # default: every 15 minutes

    save_button = wx.Button(panel, label=_("Save"))
    cancel_button = wx.Button(panel, label=_("Cancel"))

    def on_save(event):
        selected_idx = interval_choice.GetSelection()
        if selected_idx != wx.NOT_FOUND:
            selected_key = interval_keys[selected_idx]
            config['Tips']['interval'] = selected_key
            with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
                config.write(configfile)
            tip_manager.update_settings()
        frame.Close()

    def on_cancel(event):
        frame.Close()

    save_button.Bind(wx.EVT_BUTTON, on_save)
    cancel_button.Bind(wx.EVT_BUTTON, on_cancel)

    hbox_buttons = wx.BoxSizer(wx.HORIZONTAL)
    hbox_buttons.Add(save_button, flag=wx.ALL, border=5)
    hbox_buttons.Add(cancel_button, flag=wx.ALL, border=5)

    vbox.Add(interval_label, flag=wx.ALL, border=5)
    vbox.Add(interval_choice, flag=wx.ALL | wx.EXPAND, border=5)
    vbox.Add(hbox_buttons, flag=wx.ALIGN_CENTER)

    panel.SetSizer(vbox)
    frame.Show()
    app.MainLoop()

# Funkcja dodająca menu
def on_tips_settings_action(event):
    """Menu action handler"""
    show_settings_dialog()

def add_menu(component_manager):
    component_manager.register_menu_function(_("Tips Settings"), on_tips_settings_action)

# New: Add settings category
def add_settings_category(component_manager):
    """Register Tips settings category in the main settings window"""
    print("[TIPS] add_settings_category called!")
    print(f"[TIPS] component_manager: {component_manager}")
    print(f"[TIPS] settings_frame: {component_manager.settings_frame if component_manager else 'None'}")

    def create_tips_settings_panel(parent):
        print(f"[TIPS] create_tips_settings_panel called with parent: {parent}")
        """Create tips settings panel"""
        panel = wx.Panel(parent)
        vbox = wx.BoxSizer(wx.VERTICAL)

        interval_label = wx.StaticText(panel, label=_("Speak tips:"))
        interval_keys = list(INTERVAL_OPTIONS.keys())
        interval_labels = [INTERVAL_LABELS.get(k, k) for k in interval_keys]
        interval_choice = wx.Choice(panel, choices=interval_labels)

        # Store reference for loading/saving later
        panel.interval_choice = interval_choice

        vbox.Add(interval_label, flag=wx.ALL, border=10)
        vbox.Add(interval_choice, flag=wx.ALL | wx.EXPAND, border=10)

        panel.SetSizer(vbox)
        return panel

    def load_tips_settings(panel):
        """Load tips settings into panel"""
        current_interval = config['Tips'].get('interval', 'every_15_minutes')
        if current_interval in _LEGACY_KEY_MAP:
            current_interval = _LEGACY_KEY_MAP[current_interval]
        try:
            idx = interval_keys.index(current_interval)
            panel.interval_choice.SetSelection(idx)
        except ValueError:
            panel.interval_choice.SetSelection(3)

    def save_tips_settings(panel):
        """Save tips settings from panel"""
        selected_idx = panel.interval_choice.GetSelection()
        if selected_idx != wx.NOT_FOUND:
            selected_key = interval_keys[selected_idx]
            config['Tips']['interval'] = selected_key
        with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        if tip_manager:
            tip_manager.update_settings()

    # Register the category
    component_manager.register_settings_category(_("Tips"), create_tips_settings_panel, save_tips_settings, load_tips_settings)

# Legacy add_settings hook (deprecated but kept for compatibility)
def add_settings(settings_frame):
    """Legacy hook - not used with new category system"""
    pass

# Inicjalizacja komponentu
def initialize(app=None):
    global tip_manager
    tip_manager = TipManager()
    tip_manager.start()

# Globalna zmienna tip_manager
tip_manager = None


# ===========================================================================
# Titan actions - what Titan, its AI and other add-ons can ask this component
# ===========================================================================
# The tips are Titan's own written help, one line each. That makes them the
# right thing to answer "how do I ..." with - the AI reading the user's real
# documentation rather than guessing at an interface it cannot see. So the
# useful actions are searching them and reading one out, not just turning the
# reminder on and off.

try:
    from src.titan_core.actions import fails, needs
except Exception:                       # Titan not importable - actions unused
    def fails(reason):
        return reason

    def needs(name, prompt, options=None, kind='string', default=''):
        return prompt


def action_random_tip():
    """Say one of Titan's tips, as the reminder does."""
    tips = load_tips()
    if not tips:
        return fails("Titan has no tips installed.")
    tip = random.choice(tips)
    speak(_("Tip: %s") % tip)
    return tip


def action_search_tips(query="", limit=10):
    """Find the tips that mention something."""
    tips = load_tips()
    if not tips:
        return fails("Titan has no tips installed.")
    wanted = str(query or '').strip().lower()
    try:
        count = max(1, min(int(limit or 10), 50))
    except (TypeError, ValueError):
        count = 10
    found = [t for t in tips if not wanted or wanted in t.lower()]
    if not found:
        return f"None of Titan's {len(tips)} tips mention '{query}'."
    shown = found[:count]
    header = (f"{len(found)} of Titan's {len(tips)} tips mention '{query}'"
              if wanted else f"{len(tips)} tips")
    return header + ":\n" + "\n".join(f"- {t}" for t in shown)


def action_get_interval():
    """Say how often Titan shows a tip."""
    option = config['Tips'].get('interval', 'every_15_minutes')
    option = _LEGACY_KEY_MAP.get(option, option)
    if option == 'disabled':
        return "Tips are switched off."
    seconds = INTERVAL_OPTIONS.get(option)
    if not seconds:
        return "Tips are switched off."
    return f"Titan shows a tip every {seconds // 60} minutes."


def action_set_interval(minutes):
    """Change how often Titan shows a tip, or switch tips off."""
    try:
        wanted = int(minutes)
    except (TypeError, ValueError):
        return needs('minutes', "How many minutes between tips? Use 0 to "
                                "switch them off.")
    if wanted <= 0:
        option = 'disabled'
    else:
        # Only the intervals the settings panel offers exist, so the closest
        # one is chosen rather than inventing a value the panel cannot show.
        choices = [(key, value // 60) for key, value in INTERVAL_OPTIONS.items()
                   if value]
        option = min(choices, key=lambda item: abs(item[1] - wanted))[0]
    config['Tips']['interval'] = option
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as handle:
            config.write(handle)
    except OSError as e:
        return fails(f"Could not save the tip interval: {e}")
    if tip_manager is not None:
        try:
            tip_manager.update_settings()
        except Exception:
            pass
    if option == 'disabled':
        return "Tips are switched off."
    return (f"Titan will show a tip every "
            f"{INTERVAL_OPTIONS[option] // 60} minutes.")


TITAN_ACTIONS = [
    {'name': 'random_tip',
     'summary': "Say one of Titan's tips out loud.",
     'run': action_random_tip},
    {'name': 'search_tips',
     'summary': "Search Titan's own tips - its written help, one line each. "
                "Use this when the user asks how to do something in Titan.",
     'params': {'query': {'type': 'string',
                          'description': "What to look for. Leave empty to "
                                         "list them all."},
                'limit': {'type': 'integer',
                          'description': "How many to return (default 10)."}},
     'run': action_search_tips},
    {'name': 'get_interval',
     'summary': "Say how often Titan shows a tip.",
     'run': action_get_interval},
    {'name': 'set_interval',
     'summary': "Change how often Titan shows a tip, or switch tips off.",
     'params': {'minutes': {'type': 'integer', 'required': True,
                            'description': "Minutes between tips, or 0 to "
                                           "switch them off."}},
     'risk': 'confirm', 'run': action_set_interval},
]
