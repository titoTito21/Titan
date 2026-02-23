# -*- coding: utf-8 -*-
"""
TCE Speech - Unified speech API for TCE applications and games.

Provides access to Titan's TTS engine (StereoSpeech) when enabled in settings,
with fallback to accessible_output3 / platform TTS when disabled or unavailable.

Works in both development mode and compiled (PyInstaller) mode.

Usage in apps/games:
    try:
        from src.titan_core.tce_speech import speak, speak_async, stop
    except ImportError:
        # Standalone fallback (outside Titan environment)
        speak = None

    if speak:
        speak("Hello world")
        speak("Left side", position=-0.5)
        speak("Right side", position=0.5)
"""

import os
import sys
import platform
import threading


# ---------------------------------------------------------------------------
# Settings reader — same format as src/settings/settings.py (no configparser)
# ---------------------------------------------------------------------------

def _get_settings_path():
    """Get path to Titan settings file."""
    p = platform.system()
    if p == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
    elif p == 'Darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
    return os.path.join(base, 'titosoft', 'Titan', 'bg5settings.ini')


_settings_cache = None


def _load_settings():
    """Load all settings from Titan config file (same parser as settings.py)."""
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache
    path = _get_settings_path()
    settings = {}
    if not os.path.exists(path):
        return settings
    try:
        with open(path, 'r', encoding='utf-8') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                    settings[current_section] = {}
                elif '=' in line and current_section:
                    key, value = line.split('=', 1)
                    settings[current_section][key.strip()] = value.strip()
    except Exception:
        pass
    _settings_cache = settings
    return settings


def _get_setting(key, default='', section='general'):
    """Read a single setting from Titan config file."""
    return _load_settings().get(section, {}).get(key, default)


# ---------------------------------------------------------------------------
# Basic TTS engine (accessible_output3 + platform fallback)
# ---------------------------------------------------------------------------

class _BasicEngine:
    """Simple TTS using accessible_output3 with cross-platform fallback.
    Used when Titan TTS / stereo speech is disabled."""

    def __init__(self):
        self._ao3 = None
        try:
            import accessible_output3.outputs.auto
            self._ao3 = accessible_output3.outputs.auto.Auto()
        except Exception:
            pass

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0):
        if self._ao3:
            try:
                self._ao3.speak(text, interrupt=interrupt)
                return
            except Exception:
                pass
        # Platform fallback
        try:
            p = platform.system()
            if p == 'Windows':
                import win32com.client
                win32com.client.Dispatch("SAPI.SpVoice").Speak(text)
            elif p == 'Darwin':
                import subprocess
                subprocess.Popen(['say', text])
            else:
                import subprocess
                subprocess.Popen(['spd-say', text])
        except Exception:
            pass

    def speak_async(self, text, position=0.0, interrupt=True, pitch_offset=0):
        t = threading.Thread(
            target=self.speak,
            args=(text, position, interrupt, pitch_offset),
            daemon=True
        )
        t.start()

    def stop(self):
        pass


# ---------------------------------------------------------------------------
# Apply user settings to StereoSpeech instance
# ---------------------------------------------------------------------------

def _apply_stereo_settings(stereo):
    """Apply engine, voice, rate, and volume settings from bg5settings.ini."""
    try:
        # Debug: show what settings we're reading
        stereo_section = _load_settings().get('stereo_speech', {})
        print(f"[tce_speech] Settings from [stereo_speech]: {stereo_section}")

        # 1. Set engine
        engine = _get_setting('engine', 'espeak', 'stereo_speech')
        print(f"[tce_speech] Setting engine: {engine}")
        stereo.set_engine(engine)

        # 2. Set rate (-10 to +10)
        try:
            rate = int(_get_setting('rate', '0', 'stereo_speech'))
            stereo.set_rate(rate)
        except (ValueError, TypeError):
            pass

        # 3. Set volume (0-100)
        try:
            volume = int(_get_setting('volume', '100', 'stereo_speech'))
            stereo.set_volume(volume)
        except (ValueError, TypeError):
            pass

        # 4. Set ElevenLabs API key (before loading voices)
        elevenlabs_key = _get_setting('elevenlabs_api_key', '', 'stereo_speech')
        if elevenlabs_key and hasattr(stereo, 'set_elevenlabs_api_key'):
            stereo.set_elevenlabs_api_key(elevenlabs_key)

        # 5. Set voice (stored as ID/name, need to find matching index)
        voice_id = _get_setting('voice', '', 'stereo_speech')
        print(f"[tce_speech] Setting voice: '{voice_id}'")
        try:
            voices = stereo.get_available_voices()
            if voice_id:
                found = False
                for i, v in enumerate(voices):
                    if isinstance(v, dict):
                        if v.get('id') == voice_id:
                            stereo.set_voice(i)
                            print(f"[tce_speech] Voice matched at index {i}: {v.get('display_name', v.get('id'))}")
                            found = True
                            break
                    elif str(v) == voice_id:
                        stereo.set_voice(i)
                        print(f"[tce_speech] Voice matched at index {i}: {v}")
                        found = True
                        break
                if not found and voices:
                    # Voice not found — use first available
                    stereo.set_voice(0)
                    print(f"[tce_speech] Voice '{voice_id}' not found, using first available")
            elif voices:
                # No voice saved — use first available as default
                stereo.set_voice(0)
                print(f"[tce_speech] No voice saved, using first available")
        except Exception as e:
            print(f"[tce_speech] Error setting voice: {e}")

    except Exception as e:
        print(f"[tce_speech] Error applying settings: {e}")


# ---------------------------------------------------------------------------
# Lazy-initialized global speaker
# ---------------------------------------------------------------------------

_speaker = None
_init_lock = threading.Lock()
_initialized = False


def _init():
    """Lazy-initialize the speech engine based on Titan settings."""
    global _speaker, _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return

        stereo_enabled = (
            _get_setting('stereo_speech', 'False', 'invisible_interface')
            .strip().lower() == 'true'
        )

        if stereo_enabled:
            try:
                from src.titan_core.stereo_speech import StereoSpeech
                _speaker = StereoSpeech()
                _apply_stereo_settings(_speaker)
                _initialized = True
                return
            except Exception as e:
                print(f"[tce_speech] StereoSpeech init failed, using basic engine: {e}")

        # Stereo disabled or StereoSpeech unavailable — use basic engine
        _speaker = _BasicEngine()
        _initialized = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text, position=0.0, interrupt=True, pitch_offset=0):
    """Speak text with optional stereo positioning.

    Args:
        text: The text to speak.
        position: Stereo position from -1.0 (left) to 1.0 (right), 0.0 = center.
                  Only effective when Titan TTS (stereo speech) is enabled.
        interrupt: If True, stop any current speech before speaking.
        pitch_offset: Pitch offset (engine-dependent).
    """
    _init()
    if _speaker:
        if interrupt and hasattr(_speaker, 'stop'):
            _speaker.stop()
        # StereoSpeech.speak() uses (text, position, pitch_offset) — no interrupt param
        # _BasicEngine.speak() accepts interrupt via keyword
        if isinstance(_speaker, _BasicEngine):
            _speaker.speak(text, position=position, interrupt=interrupt, pitch_offset=pitch_offset)
        else:
            _speaker.speak(text, position=position, pitch_offset=pitch_offset)


def speak_async(text, position=0.0, interrupt=True, pitch_offset=0):
    """Speak text asynchronously (non-blocking).

    Same parameters as speak().
    """
    _init()
    if _speaker:
        if isinstance(_speaker, _BasicEngine):
            _speaker.speak_async(text, position=position, interrupt=interrupt, pitch_offset=pitch_offset)
        else:
            if interrupt and hasattr(_speaker, 'stop'):
                _speaker.stop()
            _speaker.speak_async(text, position=position, pitch_offset=pitch_offset)


def stop():
    """Stop any current speech."""
    _init()
    if _speaker:
        _speaker.stop()
