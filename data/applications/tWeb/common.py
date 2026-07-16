# -*- coding: utf-8 -*-
"""Shared helpers for the tWeb package: config, speech, sound, skin.

Split out of web.py so browser_tab.py / downloads.py / history.py /
bookmarks.py / findbar.py can all import these without a circular import
back to web.py (which now imports them).
"""
import os
import platform
import configparser
import pygame
from translation import _

try:
    from src.titan_core.skin_manager import apply_skin_to_window
except ImportError:
    apply_skin_to_window = None


def _apply_skin_to_tree(window):
    if not apply_skin_to_window or not window:
        return
    try:
        apply_skin_to_window(window)
    except Exception:
        return
    for child in window.GetChildren():
        _apply_skin_to_tree(child)


# TCE Speech: use Titan TTS engine (stereo speech) when available
try:
    from src.titan_core.tce_speech import speak as _tce_speak
except ImportError:
    _tce_speak = None

if _tce_speak is not None:
    def _speak(text):
        _tce_speak(text)
else:
    # Standalone fallback (outside Titan environment)
    try:
        import accessible_output3.outputs.auto as _ao3
        _speaker = _ao3.Auto()
    except Exception:
        _speaker = None

    def _speak(text):
        """Announce text via accessible_output3 with cross-platform fallback."""
        if _speaker:
            try:
                _speaker.speak(text, interrupt=True)
                return
            except Exception:
                pass
        try:
            import subprocess
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

pygame.mixer.init()


# Legacy alias so existing code using `speaker.speak(...)` still works
class _SpeakerCompat:
    def speak(self, text, interrupt=False):
        _speak(text)


speaker = _SpeakerCompat()


def speak(text):
    speaker.speak(text)


def play_sound(sound_file):
    sound_path = os.path.join('sfx', sound_file)
    if not os.path.exists(sound_path):
        print(_("Nie znaleziono pliku dźwiękowego: {}").format(sound_path))
        return
    try:
        sound = pygame.mixer.Sound(sound_path)
        sound.play()
    except Exception as e:
        print(_("Nie można odtworzyć dźwięku: {}").format(e))


def get_config_path():
    if platform.system() == 'Windows':
        appdata = os.getenv('APPDATA')
        config_dir = os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings')
    elif platform.system() == 'Darwin':  # macOS
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings')
    else:
        home = os.path.expanduser('~')
        config_dir = os.path.join(home, '.config', 'Titosoft', 'Titan', 'appsettings')
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    return os.path.join(config_dir, 'tbrowser.ini')


def get_data_path(filename):
    """Path for a JSON data file (downloads/history/bookmarks) alongside the ini config."""
    config_dir = os.path.dirname(get_config_path())
    return os.path.join(config_dir, filename)


CONFIG_PATH = get_config_path()

DEFAULT_SETTINGS = {
    'announcements': {
        'announce_page_summary': 'True',
        'loading_messages': 'True'
    },
    'interface': {
        'view_mode': 'edge'
    },
    'privacy': {
        'block_cookie_banners': 'False'
    },
    'history': {
        'max_entries': '500'
    }
}

config = configparser.ConfigParser()
if not os.path.exists(CONFIG_PATH):
    # Jeśli pliku nie ma, tworzymy go z domyślnymi ustawieniami
    config.read_dict(DEFAULT_SETTINGS)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
        config.write(configfile)
else:
    config.read(CONFIG_PATH, encoding='utf-8')

    # Uzupełniamy ewentualnie brakujące sekcje/klucze
    for section in DEFAULT_SETTINGS:
        if section not in config:
            config[section] = DEFAULT_SETTINGS[section]
        else:
            for key in DEFAULT_SETTINGS[section]:
                if key not in config[section]:
                    config[section][key] = DEFAULT_SETTINGS[section][key]

    with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
        config.write(configfile)


def save_config():
    with open(CONFIG_PATH, 'w', encoding='utf-8') as configfile:
        config.write(configfile)
