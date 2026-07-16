# -*- coding: utf-8 -*-
"""Shared helpers for the tMedia package: config, speech, sound, skin.

Mirrors data/applications/tWeb/common.py so tmedia.py / MediaCatalog.py /
YoutubeSearch.py / player.py can all import these directly instead of
reaching up a GetParent() chain to whichever Frame happens to be their
ancestor.
"""
import os
import platform
import configparser
from pygame import mixer
from translation import _

try:
    from src.titan_core.skin_manager import apply_skin_to_window
except ImportError:
    apply_skin_to_window = None


def apply_skin(window):
    if not apply_skin_to_window or not window:
        return
    try:
        apply_skin_to_window(window)
    except Exception:
        return
    for child in window.GetChildren():
        apply_skin(child)


# TCE Speech: use Titan TTS engine (stereo speech) when available
try:
    from src.titan_core.tce_speech import speak as _tce_speak
except ImportError:
    _tce_speak = None

if _tce_speak is not None:
    def _raw_speak(text):
        _tce_speak(text)
else:
    # Standalone fallback (outside Titan environment)
    try:
        import accessible_output3.outputs.auto as _ao3
        _speaker = _ao3.Auto()
    except Exception:
        _speaker = None

    def _raw_speak(text):
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


def get_config_path():
    _plat = platform.system()
    if _plat == 'Windows':
        appdata = os.getenv('APPDATA') or os.path.expanduser('~')
        config_dir = os.path.join(appdata, 'Titosoft', 'Titan', 'appsettings')
    elif _plat == 'Darwin':
        config_dir = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings')
    else:
        config_dir = os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan', 'appsettings')
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
    return os.path.join(config_dir, 'media.ini')


CONFIG_PATH = get_config_path()

config = configparser.ConfigParser()
if os.path.exists(CONFIG_PATH):
    config.read(CONFIG_PATH)
else:
    config['DEFAULT'] = {
        'sound_effects': 'True',
        'tts_enabled': 'False',
        'player': 'tplayer',
    }
    with open(CONFIG_PATH, 'w') as configfile:
        config.write(configfile)


def save_config():
    with open(CONFIG_PATH, 'w') as configfile:
        config.write(configfile)


def tts_enabled():
    return config.getboolean('DEFAULT', 'tts_enabled', fallback=False)


def speak(text):
    """Announce text via Titan TTS, gated by the tMedia 'Speech output' setting."""
    if tts_enabled():
        _raw_speak(text)


mixer.init()
_SOUND_NAMES = ('ding', 'done', 'enter', 'enteringtplayer', 'sound_on', 'loading', 'click')
_sounds = {}
for _name in _SOUND_NAMES:
    try:
        _sounds[_name] = mixer.Sound(os.path.join('sfx', '%s.ogg' % _name))
    except Exception:
        pass


def sound_effects_enabled():
    return config.getboolean('DEFAULT', 'sound_effects', fallback=True)


def play_sound(name, loop=False):
    if not sound_effects_enabled():
        return None
    sound = _sounds.get(name)
    if not sound:
        return None
    return sound.play(-1 if loop else 0)


def stop_sound(name=None, channel=None):
    if channel is not None:
        channel.stop()
    elif name:
        sound = _sounds.get(name)
        if sound:
            sound.stop()
