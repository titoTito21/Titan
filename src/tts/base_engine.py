"""
TitanTTS Engine Base Class
===========================
Abstract base for all TitanTTS engines (built-in and plugins).

Engine categories:
  - 'titantts': Native TitanTTS engines (ElevenLabs, Milena, custom plugins)
  - 'platform': Platform/system engines (eSpeak, SAPI5, macOS Speech, Speech Dispatcher)

Config fields system:
  Each engine can define custom configuration fields via get_config_fields().
  The settings UI dynamically renders controls for these fields.
  Field types: text, password, choice, slider, checkbox
"""

import abc


class TitanTTSEngine(abc.ABC):
    """
    Base class for TitanTTS engines.

    Class attributes (override in subclass):
        engine_id (str):       Unique engine identifier (e.g. 'elevenlabs')
        engine_name (str):     Display name (e.g. 'ElevenLabs TTS')
        engine_category (str): 'titantts' or 'platform'
        needs_lock_release (bool): True if generate() is slow (API/subprocess)

    Abstract methods (must implement):
        is_available() -> bool
        generate(text, pitch_offset) -> AudioSegment | None
        get_voices() -> list[dict]
        set_voice(voice_id)

    Optional overrides:
        set_rate(rate), set_volume(volume), stop(), clear_cache()
        get_config_fields(), configure(key, value), get_config(key)
    """

    engine_id = ''
    engine_name = ''
    engine_category = 'platform'
    needs_lock_release = False

    @abc.abstractmethod
    def is_available(self):
        """Return True if this engine can produce speech on this platform."""
        ...

    @abc.abstractmethod
    def generate(self, text, pitch_offset=0):
        """
        Synthesize text to pydub.AudioSegment or None.

        Args:
            text (str): Text to speak.
            pitch_offset (int): Semitone shift -10..+10.

        Returns:
            pydub.AudioSegment or None
        """
        ...

    @abc.abstractmethod
    def get_voices(self):
        """
        Return list of available voices.

        Returns:
            list of {'id': str, 'display_name': str} dicts, or empty list.
        """
        ...

    @abc.abstractmethod
    def set_voice(self, voice_id):
        """Set active voice by ID string."""
        ...

    def set_rate(self, rate):
        """Set speech rate (-10 to +10). Override per engine."""
        pass

    def set_volume(self, volume):
        """Set speech volume (0-100). Override per engine."""
        pass

    def stop(self):
        """Stop any in-progress generation. Override if needed."""
        pass

    def clear_cache(self):
        """Clear any cached audio data. Override if engine uses caching."""
        pass

    # ------------------------------------------------------------------
    # Config fields system
    # ------------------------------------------------------------------

    @classmethod
    def get_config_fields(cls):
        """
        Return a list of engine-specific configuration field descriptors.

        Each field is a dict with keys:
            key (str):      Config key (stored in settings as engine.{id}.{key})
            label (str):    Display label for the UI control
            type (str):     Control type: 'text', 'password', 'choice', 'slider', 'checkbox'
            default:        Default value
            tooltip (str):  Optional tooltip text
            options (list): For 'choice' type: list of (value, display_name) tuples
            min (int):      For 'slider' type: minimum value
            max (int):      For 'slider' type: maximum value

        Returns:
            list of field descriptor dicts
        """
        return []

    def configure(self, key, value):
        """
        Apply a configuration value.

        Called when settings are loaded or when the user changes a value in the UI.
        The engine should store the value internally and apply it.

        Args:
            key (str): Config key matching a field from get_config_fields()
            value: The value to apply
        """
        pass

    def get_config(self, key, default=None):
        """
        Read a configuration value.

        Args:
            key (str): Config key matching a field from get_config_fields()
            default: Value to return if key is not set

        Returns:
            The current value, or default
        """
        return default
