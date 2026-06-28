# -*- coding: utf-8 -*-
"""Settings store for Titan Access.

Direct Python port of the C# ``Settings/SettingsManager.cs``. Keeps the exact
same INI sections, keys, defaults and value encodings so the file is compatible
with the original C# screen reader and so the TCE settings category (a 1:1 port
of the C# ``SettingsDialog``) reads/writes the same store.

INI location (matches C#):  %APPDATA%/titosoft/Titan/screenreader/screenReader.ini

This module has **no** dependency on Titan internals, so the screen reader runs
standalone as well as inside the launcher.
"""

import os
import platform
import threading


# --------------------------------------------------------------------------- #
# Enums (mirror C# enums; encoded as their PascalCase names in the INI)
# --------------------------------------------------------------------------- #
class AnnouncementMode:
    NONE = "None"
    SOUND = "Sound"
    SPEECH = "Speech"
    SPEECH_AND_SOUND = "SpeechAndSound"
    ALL = (NONE, SOUND, SPEECH, SPEECH_AND_SOUND)

    @staticmethod
    def speaks(mode):
        return mode in (AnnouncementMode.SPEECH, AnnouncementMode.SPEECH_AND_SOUND)

    @staticmethod
    def plays(mode):
        return mode in (AnnouncementMode.SOUND, AnnouncementMode.SPEECH_AND_SOUND)

    @staticmethod
    def normalize(value, default="SpeechAndSound"):
        v = (value or "").strip().lower()
        return {
            "none": "None", "brak": "None",
            "sound": "Sound", "dźwięk": "Sound", "dzwiek": "Sound",
            "speech": "Speech", "mowa": "Speech",
            "speechandsound": "SpeechAndSound", "mowa i dźwięk": "SpeechAndSound",
        }.get(v, default)


class ScreenReaderModifier:
    INSERT = "Insert"
    CAPSLOCK = "CapsLock"
    INSERT_AND_CAPSLOCK = "InsertAndCapsLock"
    ALL = (INSERT, CAPSLOCK, INSERT_AND_CAPSLOCK)

    @staticmethod
    def normalize(value, default="InsertAndCapsLock"):
        v = (value or "").strip().lower()
        return {
            "insert": "Insert",
            "capslock": "CapsLock",
            "insertandcapslock": "InsertAndCapsLock",
        }.get(v, default)


class KeyboardEchoSetting:
    NONE = "None"
    CHARACTERS = "Characters"
    WORDS = "Words"
    CHARACTERS_AND_WORDS = "CharactersAndWords"
    ALL = (NONE, CHARACTERS, WORDS, CHARACTERS_AND_WORDS)

    @staticmethod
    def echo_chars(value):
        return value in (KeyboardEchoSetting.CHARACTERS,
                         KeyboardEchoSetting.CHARACTERS_AND_WORDS)

    @staticmethod
    def echo_words(value):
        return value in (KeyboardEchoSetting.WORDS,
                         KeyboardEchoSetting.CHARACTERS_AND_WORDS)

    @staticmethod
    def normalize(value, default="CharactersAndWords"):
        v = (value or "").strip().lower()
        return {
            "none": "None", "brak": "None",
            "characters": "Characters", "znaki": "Characters",
            "words": "Words", "słowa": "Words", "slowa": "Words",
            "charactersandwords": "CharactersAndWords",
            "znaki i słowa": "CharactersAndWords",
        }.get(v, default)


# --------------------------------------------------------------------------- #
# Section / key names (mirror C# constants)
# --------------------------------------------------------------------------- #
SEC_SPEECH = "Speech"
SEC_GENERAL = "General"
SEC_VERBOSITY = "Verbosity"
SEC_NAVIGATION = "Navigation"
SEC_TEXT_EDITING = "TextEditing"
SEC_DIAL = "Dial"

# (section, key) -> default value (string-encoded, exactly like C# SetDefaults)
DEFAULTS = {
    # Speech
    (SEC_SPEECH, "Synthesizer"): "SAPI5",
    (SEC_SPEECH, "Voice"): "",
    (SEC_SPEECH, "Rate"): "0",
    (SEC_SPEECH, "Volume"): "100",
    (SEC_SPEECH, "Pitch"): "0",
    # General
    # Whether the screen reader is enabled (auto-starts with the component when
    # true). Toggled live by the "Enable screen reader" checkbox / the hotkey.
    (SEC_GENERAL, "Enabled"): "false",
    (SEC_GENERAL, "MuteOutsideTCE"): "false",
    (SEC_GENERAL, "StartupAnnouncement"): "SpeechAndSound",
    (SEC_GENERAL, "TCEEntrySound"): "true",
    (SEC_GENERAL, "Modifier"): "InsertAndCapsLock",
    (SEC_GENERAL, "WelcomeMessage"): "Czytnik ekranu uruchomiony",
    (SEC_GENERAL, "SpeakHints"): "true",
    (SEC_GENERAL, "Language"): "pl",
    # Titan-specific additions (not in C#) — positional audio / virtual screen.
    # Sounds are always stereo-panned; speech is centered unless VirtualScreen
    # is on, then speech is panned to the element position too.
    (SEC_GENERAL, "VirtualScreen"): "false",
    (SEC_GENERAL, "EnableMSAA"): "true",
    # NVDA controller server: when true (and the native helper DLL is present),
    # apps using nvdaControllerClient.dll speak through Titan Access.
    (SEC_GENERAL, "NvdaControllerServer"): "true",
    # Verbosity
    (SEC_VERBOSITY, "AnnounceBasicControls"): "true",
    (SEC_VERBOSITY, "AnnounceBlockControls"): "true",
    (SEC_VERBOSITY, "AnnounceListPosition"): "true",
    (SEC_VERBOSITY, "MenuItemCount"): "true",
    (SEC_VERBOSITY, "MenuName"): "true",
    (SEC_VERBOSITY, "MenuSounds"): "true",
    (SEC_VERBOSITY, "ElementName"): "true",
    (SEC_VERBOSITY, "ElementType"): "true",
    (SEC_VERBOSITY, "ElementState"): "true",
    (SEC_VERBOSITY, "ElementParameter"): "true",
    (SEC_VERBOSITY, "ToggleKeysMode"): "SpeechAndSound",
    # Navigation
    (SEC_NAVIGATION, "AdvancedNavigation"): "false",
    (SEC_NAVIGATION, "AnnounceControlTypesNavigation"): "true",
    (SEC_NAVIGATION, "AnnounceHierarchyLevel"): "true",
    (SEC_NAVIGATION, "WindowBoundsMode"): "SpeechAndSound",
    (SEC_NAVIGATION, "PhoneticInDial"): "true",
    # Simple review mode (NVDA-style flattened object navigation: skip
    # layout-only containers while walking the UIA tree).
    (SEC_NAVIGATION, "SimpleReviewMode"): "true",
    # Dial
    (SEC_DIAL, "DialCharacters"): "true",
    (SEC_DIAL, "DialWords"): "true",
    (SEC_DIAL, "DialButtons"): "true",
    (SEC_DIAL, "DialHeadings"): "true",
    (SEC_DIAL, "DialVolume"): "true",
    (SEC_DIAL, "DialSpeed"): "true",
    (SEC_DIAL, "DialVoice"): "true",
    (SEC_DIAL, "DialSynthesizer"): "true",
    (SEC_DIAL, "DialImportantPlaces"): "true",
    # TextEditing
    (SEC_TEXT_EDITING, "PhoneticLetters"): "true",
    (SEC_TEXT_EDITING, "KeyboardEcho"): "CharactersAndWords",
    (SEC_TEXT_EDITING, "AnnounceTextBounds"): "true",
}

_TRUE = {"true", "1", "yes", "tak"}
_FALSE = {"false", "0", "no", "nie"}


def _config_path():
    """Return %APPDATA%/titosoft/Titan/screenreader/screenReader.ini (cross-platform)."""
    p = platform.system()
    if p == "Windows":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        base = os.path.join(base, "titosoft", "Titan")
    elif p == "Darwin":
        base = os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", "titosoft", "Titan")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config", "titosoft", "Titan")
    return os.path.join(base, "screenreader", "screenReader.ini")


def config_dir():
    """Return the screen reader's settings directory.

    This is where ``screenReader.ini`` lives (``…/titosoft/Titan/screenreader``);
    user data such as downloaded application modules is kept in subfolders here so
    everything stays inside the Titan screen reader's own settings location.
    """
    return os.path.dirname(_config_path())


class SettingsStore:
    """Thread-safe INI settings store, 1:1 with the C# ``SettingsManager``.

    Use :func:`get_settings` for the process-wide singleton. Reads are cheap
    (in-memory dict); call :meth:`save` to persist and :meth:`reload` to pick up
    changes written by another process (e.g. the standalone reader vs the TCE
    settings dialog).
    """

    def __init__(self, path=None):
        self._path = path or _config_path()
        self._lock = threading.RLock()
        # section -> {key(lower): (original_key, value)} ; keep original case for write
        self._sections = {}
        self.load()

    # -- path -------------------------------------------------------------- #
    @property
    def path(self):
        return self._path

    # -- low-level ---------------------------------------------------------- #
    def _ensure_section(self, section):
        if section not in self._sections:
            self._sections[section] = {}
        return self._sections[section]

    def get(self, section, key, default=""):
        with self._lock:
            sec = self._sections.get(section)
            if sec:
                entry = sec.get(key.lower())
                if entry is not None:
                    return entry[1]
            return DEFAULTS.get((section, key), default)

    def set(self, section, key, value):
        with self._lock:
            sec = self._ensure_section(section)
            sec[key.lower()] = (key, "" if value is None else str(value))

    def get_int(self, section, key, default=0):
        try:
            return int(str(self.get(section, key, str(default))).strip())
        except (TypeError, ValueError):
            return default

    def set_int(self, section, key, value):
        self.set(section, key, str(int(value)))

    def get_bool(self, section, key, default=False):
        v = str(self.get(section, key, "true" if default else "false")).strip().lower()
        if v in _TRUE:
            return True
        if v in _FALSE:
            return False
        return default

    def set_bool(self, section, key, value):
        self.set(section, key, "true" if value else "false")

    # -- persistence -------------------------------------------------------- #
    def set_defaults(self):
        with self._lock:
            for (section, key), value in DEFAULTS.items():
                # Only fill in missing keys, don't clobber user values.
                if self._sections.get(section, {}).get(key.lower()) is None:
                    self.set(section, key, value)

    def load(self):
        with self._lock:
            self._sections = {}
            if not os.path.exists(self._path):
                self.set_defaults()
                return
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    current = ""
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith(";") or s.startswith("#"):
                            continue
                        if s.startswith("[") and s.endswith("]"):
                            current = s[1:-1]
                            self._ensure_section(current)
                            continue
                        eq = s.find("=")
                        if eq > 0 and current:
                            k = s[:eq].strip()
                            val = s[eq + 1:].strip()
                            self._ensure_section(current)[k.lower()] = (k, val)
            except Exception as e:
                print(f"[TitanAccess] settings load error: {e}")
            # Backfill any keys absent from the file with defaults.
            self.set_defaults()

    reload = load

    def save(self):
        import datetime
        with self._lock:
            lines = ["; Titan Access Screen Reader Settings",
                     f"; Generated: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}", ""]
            for section, entries in self._sections.items():
                lines.append(f"[{section}]")
                for _lk, (orig_key, value) in entries.items():
                    lines.append(f"{orig_key}={value}")
                lines.append("")
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                with open(self._path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            except Exception as e:
                print(f"[TitanAccess] settings save error: {e}")

    # -- typed convenience accessors (mirror C# properties) ----------------- #
    # Speech
    @property
    def synthesizer(self): return self.get(SEC_SPEECH, "Synthesizer", "SAPI5")
    @synthesizer.setter
    def synthesizer(self, v): self.set(SEC_SPEECH, "Synthesizer", v)

    @property
    def voice(self): return self.get(SEC_SPEECH, "Voice", "")
    @voice.setter
    def voice(self, v): self.set(SEC_SPEECH, "Voice", v)

    @property
    def rate(self): return self.get_int(SEC_SPEECH, "Rate", 0)
    @rate.setter
    def rate(self, v): self.set_int(SEC_SPEECH, "Rate", v)

    @property
    def volume(self): return self.get_int(SEC_SPEECH, "Volume", 100)
    @volume.setter
    def volume(self, v): self.set_int(SEC_SPEECH, "Volume", v)

    @property
    def pitch(self): return self.get_int(SEC_SPEECH, "Pitch", 0)
    @pitch.setter
    def pitch(self, v): self.set_int(SEC_SPEECH, "Pitch", v)

    # General
    @property
    def enabled(self): return self.get_bool(SEC_GENERAL, "Enabled", False)
    @enabled.setter
    def enabled(self, v): self.set_bool(SEC_GENERAL, "Enabled", v)

    @property
    def mute_outside_tce(self): return self.get_bool(SEC_GENERAL, "MuteOutsideTCE", False)
    @mute_outside_tce.setter
    def mute_outside_tce(self, v): self.set_bool(SEC_GENERAL, "MuteOutsideTCE", v)

    @property
    def startup_announcement(self):
        return AnnouncementMode.normalize(self.get(SEC_GENERAL, "StartupAnnouncement"))
    @startup_announcement.setter
    def startup_announcement(self, v): self.set(SEC_GENERAL, "StartupAnnouncement", v)

    @property
    def tce_entry_sound(self): return self.get_bool(SEC_GENERAL, "TCEEntrySound", True)
    @tce_entry_sound.setter
    def tce_entry_sound(self, v): self.set_bool(SEC_GENERAL, "TCEEntrySound", v)

    @property
    def modifier(self):
        return ScreenReaderModifier.normalize(self.get(SEC_GENERAL, "Modifier"))
    @modifier.setter
    def modifier(self, v): self.set(SEC_GENERAL, "Modifier", v)

    @property
    def welcome_message(self):
        return self.get(SEC_GENERAL, "WelcomeMessage", "Czytnik ekranu uruchomiony")
    @welcome_message.setter
    def welcome_message(self, v): self.set(SEC_GENERAL, "WelcomeMessage", v)

    @property
    def speak_hints(self): return self.get_bool(SEC_GENERAL, "SpeakHints", True)
    @speak_hints.setter
    def speak_hints(self, v): self.set_bool(SEC_GENERAL, "SpeakHints", v)

    @property
    def language(self):
        v = self.get(SEC_GENERAL, "Language", "pl").strip().lower()
        return v if v in ("pl", "en") else "pl"
    @language.setter
    def language(self, v): self.set(SEC_GENERAL, "Language", "en" if str(v).strip().lower() == "en" else "pl")

    @property
    def virtual_screen(self): return self.get_bool(SEC_GENERAL, "VirtualScreen", False)
    @virtual_screen.setter
    def virtual_screen(self, v): self.set_bool(SEC_GENERAL, "VirtualScreen", v)

    # TextEditing
    @property
    def phonetic_letters(self): return self.get_bool(SEC_TEXT_EDITING, "PhoneticLetters", True)
    @phonetic_letters.setter
    def phonetic_letters(self, v): self.set_bool(SEC_TEXT_EDITING, "PhoneticLetters", v)

    @property
    def keyboard_echo(self):
        return KeyboardEchoSetting.normalize(self.get(SEC_TEXT_EDITING, "KeyboardEcho"))
    @keyboard_echo.setter
    def keyboard_echo(self, v): self.set(SEC_TEXT_EDITING, "KeyboardEcho", v)

    @property
    def announce_text_bounds(self): return self.get_bool(SEC_TEXT_EDITING, "AnnounceTextBounds", True)
    @announce_text_bounds.setter
    def announce_text_bounds(self, v): self.set_bool(SEC_TEXT_EDITING, "AnnounceTextBounds", v)


# --------------------------------------------------------------------------- #
# Process-wide singleton
# --------------------------------------------------------------------------- #
_instance = None
_instance_lock = threading.Lock()


def get_settings():
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SettingsStore()
    return _instance
