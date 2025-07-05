# -*- coding: utf-8 -*-
import os
import sys
import threading
import time
import random
import configparser
import wx
import platform
from sound import play_sound, resource_path

# Ścieżki
def get_config_path():
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA')
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

# Opcje interwałów
INTERVAL_OPTIONS = {
    'co minutę': 60,
    'co 5 minut': 5 * 60,
    'co 10 minut': 10 * 60,
    'co 15 minut': 15 * 60,
    'co godzinę': 60 * 60,
    'wyłączone': None
}

DEFAULT_SETTINGS = {
    'interval': 'co 15 minut'
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

# Ładowanie porad
def load_tips():
    tips = []
    if os.path.exists(TIPS_FILE_PATH):
        with open(TIPS_FILE_PATH, 'r', encoding='utf-8') as f:
            tips = f.readlines()
        tips = [tip.strip() for tip in tips if tip.strip()]
    else:
        print(f"Nie znaleziono pliku z poradami: {TIPS_FILE_PATH}")
    return tips

# Funkcja mowy
def speak(text):
    def speak_thread():
        system = platform.system()
        if system == 'Windows':
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
        elif system == 'Darwin':  # macOS
            os.system(f"say '{text}'")
        else:  # Zakładamy Linux
            os.system(f"spd-say '{text}'")
    threading.Thread(target=speak_thread).start()

# Klasa TipManager
class TipManager(threading.Thread):
    def __init__(self):
        super().__init__()
        self.running = True
        self.tips = load_tips()
        self.interval_option = config['Tips'].get('interval', 'co 15 minut')
        self.interval = INTERVAL_OPTIONS.get(self.interval_option)
    
    def run(self):
        while self.running and self.interval is not None and self.tips:
            time.sleep(self.interval)
            if not self.running:
                break
            play_sound('tip.ogg')
            time.sleep(2)
            tip = random.choice(self.tips)
            speak(f"Porada: {tip}")
    
    def update_settings(self):
        self.interval_option = config['Tips'].get('interval', 'co 15 minut')
        self.interval = INTERVAL_OPTIONS.get(self.interval_option)
    
    def stop(self):
        self.running = False

# Okno ustawień
def show_settings_dialog(parent):
    app = wx.App(False)
    frame = wx.Frame(parent, wx.ID_ANY, "Ustawienia porad")
    panel = wx.Panel(frame, wx.ID_ANY)

    vbox = wx.BoxSizer(wx.VERTICAL)

    interval_label = wx.StaticText(panel, label="Mów porady:")
    interval_choices = list(INTERVAL_OPTIONS.keys())
    interval_choice = wx.Choice(panel, choices=interval_choices)
    current_interval = config['Tips'].get('interval', 'co 15 minut')
    interval_choice.SetStringSelection(current_interval)

    save_button = wx.Button(panel, label="Zapisz")
    cancel_button = wx.Button(panel, label="Anuluj")

    def on_save(event):
        selected_interval = interval_choice.GetStringSelection()
        config['Tips']['interval'] = selected_interval
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
def on_tips_settings_action(parent_frame):
    show_settings_dialog()

def add_menu(component_manager):
    component_manager.register_menu_function("Ustawienia porad", on_tips_settings_action)

# Inicjalizacja komponentu
def initialize(app=None):
    global tip_manager
    tip_manager = TipManager()
    tip_manager.start()

# Globalna zmienna tip_manager
tip_manager = None
