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
