# -*- coding: utf-8 -*-
import os
import sys
import keyboard
import speech_recognition as sr
import pygame
import platform
import threading
import time
import configparser
import wx
import json
from sound import play_sound

# Global variables
is_dictating = False
speaking_lock = threading.Lock()
dictating_lock = threading.Lock()

# Function to get resource path
def resource_path(relative_path):
    """Returns absolute path to resource"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Paths
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), 'data', 'appsettings', 'tDictate.ini')
DICTIONARY_PATH = resource_path(os.path.join('data', 'ixidb', 'dictionary.json'))

# Default settings
DEFAULT_SETTINGS = {
    'announce_ready': 'True',
    'input_mode': 'Hurtem',
    'speech_engine': 'google',
    'noise_threshold': '3000',
    'recognition_attempts': '3'
}

# Load settings
settings = configparser.ConfigParser()
if not os.path.exists(SETTINGS_PATH):
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    settings['tDictate'] = DEFAULT_SETTINGS
    with open(SETTINGS_PATH, 'w', encoding='utf-8') as configfile:
        settings.write(configfile)
else:
    with open(SETTINGS_PATH, 'r', encoding='utf-8') as configfile:
        settings.read_file(configfile)

# Load punctuation dictionary
with open(DICTIONARY_PATH, 'r', encoding='utf-8') as f:
    punctuation_dict = json.load(f)

# Helper functions
def speak(text):
    def speak_thread():
        with speaking_lock:
            system = platform.system()
            if system == 'Windows':
                import win32com.client
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(text)
            elif system == 'Darwin':  # macOS
                os.system(f"say '{text}'")
            else:  # Assume Linux
                os.system(f"spd-say '{text}'")
    threading.Thread(target=speak_thread).start()

def is_text_field_focused():
    # This function is a placeholder. Implement platform-specific checks if needed.
    return True

def replace_punctuation(text):
    words = text.split()
    result = []
    i = 0
    while i < len(words):
        combined = words[i].lower()
        match_found = False
        for j in range(i + 1, len(words) + 1):
            if combined in punctuation_dict:
                result.append(punctuation_dict[combined])
                i = j
                match_found = True
                break
            if j < len(words):
                combined += f" {words[j].lower()}"
        if not match_found:
            result.append(words[i])
            i += 1
    return ' '.join(result).replace(' .', '.').replace(' ,', ',').replace(' !', '!').replace(' ?', '?').replace(' &', '&').replace(' #', '#')

# Speech recognition function
def dictate():
    global is_dictating
    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        recognizer.energy_threshold = int(settings['tDictate']['noise_threshold'])

    while is_dictating:
        with mic as source:
            try:
                audio = recognizer.listen(source, timeout=5)
                text = None
                for attempt in range(int(settings['tDictate']['recognition_attempts'])):
                    try:
                        text = recognizer.recognize_google(audio, language='pl-PL')
                        break
                    except sr.UnknownValueError:
                        if attempt == int(settings['tDictate']['recognition_attempts']) - 1:
                            play_sound('srerror.ogg')
                            speak("Błąd dyktowania, nie rozpoznano mowy.")
                    except sr.RequestError:
                        play_sound('srerror.ogg')
                        speak("Błąd dyktowania, błąd połączenia z internetem.")
                        break

                if text:
                    text = replace_punctuation(text)
                    if is_text_field_focused():
                        if settings['tDictate']['input_mode'] == 'Hurtem':
                            keyboard.write(text)
                        elif settings['tDictate']['input_mode'] == '1 słowo':
                            words = text.split()
                            for word in words:
                                keyboard.write(word + ' ')
                        elif settings['tDictate']['input_mode'] == 'Jeden klawisz':
                            for char in text:
                                keyboard.write(char)
                    else:
                        play_sound('srerror.ogg')
                        speak("Błąd dyktowania, nie jesteś w polu tekstowym.")
            except sr.WaitTimeoutError:
                pass  # Timeout, continue listening
            except Exception as e:
                play_sound('srerror.ogg')
                speak(f"Błąd dyktowania: {str(e)}")
        time.sleep(1)

def toggle_dictation():
    global is_dictating
    with dictating_lock:
        if is_dictating:
            is_dictating = False
            play_sound('srend.ogg')
        else:
            is_dictating = True
            play_sound('srbegin.ogg')
            threading.Thread(target=dictate).start()

def show_settings_dialog():
    app = wx.App(False)
    frame = wx.Frame(None, wx.ID_ANY, "Ustawienia tDictate")
    panel = wx.Panel(frame, wx.ID_ANY)

    vbox = wx.BoxSizer(wx.VERTICAL)

    # Announce ready checkbox
    announce_ready_checkbox = wx.CheckBox(panel, label="Oznajmiaj gotowość do działania")
    announce_ready_checkbox.SetValue(settings.getboolean('tDictate', 'announce_ready'))
    vbox.Add(announce_ready_checkbox, flag=wx.ALL, border=5)

    # Input mode
    input_mode_sizer = wx.BoxSizer(wx.HORIZONTAL)
    input_mode_label = wx.StaticText(panel, label="Tryb wpisywania tekstu")
    input_mode_choice = wx.Choice(panel, choices=["Jeden klawisz", "1 słowo", "Hurtem"])
    input_mode_choice.SetStringSelection(settings['tDictate']['input_mode'])
    input_mode_sizer.Add(input_mode_label, 0, wx.ALL | wx.CENTER, 5)
    input_mode_sizer.Add(input_mode_choice, 1, wx.ALL | wx.EXPAND, 5)
    vbox.Add(input_mode_sizer, flag=wx.EXPAND)

    # Speech engine
    speech_engine_sizer = wx.BoxSizer(wx.HORIZONTAL)
    speech_engine_label = wx.StaticText(panel, label="Silnik rozpoznawania mowy")
    speech_engine_choice = wx.Choice(panel, choices=["google"])
    speech_engine_choice.SetStringSelection(settings['tDictate']['speech_engine'])
    speech_engine_sizer.Add(speech_engine_label, 0, wx.ALL | wx.CENTER, 5)
    speech_engine_sizer.Add(speech_engine_choice, 1, wx.ALL | wx.EXPAND, 5)
    vbox.Add(speech_engine_sizer, flag=wx.EXPAND)

    # Noise threshold
    noise_threshold_sizer = wx.BoxSizer(wx.HORIZONTAL)
    noise_threshold_label = wx.StaticText(panel, label="Próg szumu (im wyższa wartość, tym mniej czuły mikrofon)")
    noise_threshold_slider = wx.Slider(panel, value=int(settings['tDictate']['noise_threshold']), minValue=1000, maxValue=10000, style=wx.SL_LABELS)
    noise_threshold_sizer.Add(noise_threshold_label, 0, wx.ALL | wx.CENTER, 5)
    noise_threshold_sizer.Add(noise_threshold_slider, 1, wx.ALL | wx.EXPAND, 5)
    vbox.Add(noise_threshold_sizer, flag=wx.EXPAND)

    # Recognition attempts
    recognition_attempts_sizer = wx.BoxSizer(wx.HORIZONTAL)
    recognition_attempts_label = wx.StaticText(panel, label="Liczba prób rozpoznawania mowy")
    recognition_attempts_slider = wx.Slider(panel, value=int(settings['tDictate']['recognition_attempts']), minValue=1, maxValue=5, style=wx.SL_LABELS)
    recognition_attempts_sizer.Add(recognition_attempts_label, 0, wx.ALL | wx.CENTER, 5)
    recognition_attempts_sizer.Add(recognition_attempts_slider, 1, wx.ALL | wx.EXPAND, 5)
    vbox.Add(recognition_attempts_sizer, flag=wx.EXPAND)

    # Save and Cancel buttons
    buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
    save_button = wx.Button(panel, label="Zapisz")
    cancel_button = wx.Button(panel, label="Anuluj")
    buttons_sizer.Add(save_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)
    buttons_sizer.Add(cancel_button, 0, wx.ALL | wx.ALIGN_CENTER, 5)
    vbox.Add(buttons_sizer, flag=wx.ALIGN_CENTER)

    def on_save(event):
        settings['tDictate']['announce_ready'] = str(announce_ready_checkbox.GetValue())
        settings['tDictate']['input_mode'] = input_mode_choice.GetStringSelection()
        settings['tDictate']['speech_engine'] = speech_engine_choice.GetStringSelection()
        settings['tDictate']['noise_threshold'] = str(noise_threshold_slider.GetValue())
        settings['tDictate']['recognition_attempts'] = str(recognition_attempts_slider.GetValue())
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as configfile:
            settings.write(configfile)
        frame.Close()

    def on_cancel(event):
        frame.Close()

    save_button.Bind(wx.EVT_BUTTON, on_save)
    cancel_button.Bind(wx.EVT_BUTTON, on_cancel)

    panel.SetSizer(vbox)
    frame.Show()
    app.MainLoop()

def add_menu(menubar):
    component_menu = wx.Menu()
    tdictate_item = component_menu.Append(wx.ID_ANY, "tDictate...")
    menubar.Append(component_menu, "Ustawienia komponentów")
    menubar.Bind(wx.EVT_MENU, lambda event: show_settings_dialog(), tdictate_item)

# Initialize component
def initialize(app=None):
    # Initialize sound
    pygame.mixer.init()
    if settings.getboolean('tDictate', 'announce_ready'):
        speak("tDictate gotowy. Naciśnij Control+Shift+D, aby rozpocząć lub zakończyć dyktowanie.")
    keyboard.add_hotkey('ctrl+shift+d', toggle_dictation)

if __name__ == '__main__':
    initialize()
    while True:
        time.sleep(1)  # Keep the main thread alive
