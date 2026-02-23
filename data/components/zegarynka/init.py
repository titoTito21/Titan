# -*- coding: utf-8 -*-
"""
Zegarynka (Clock Chime) Component for TCE Launcher
Announces the current time at regular intervals with a chime sound.
"""

import os
import sys
import platform
import threading
import time
import configparser

# Add component directory to path
COMPONENT_DIR = os.path.dirname(__file__)
if COMPONENT_DIR not in sys.path:
    sys.path.insert(0, COMPONENT_DIR)

# Add TCE root directory to path
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

# wxPython
try:
    import wx
    WX_AVAILABLE = True
except ImportError:
    WX_AVAILABLE = False

# Sound
try:
    from src.titan_core.sound import play_sound
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False
    print("[zegarynka] Warning: sound module not available")

# Settings
try:
    from src.settings.settings import get_setting
    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False
    def get_setting(key, default='', section='general'):
        return default

# Translation
try:
    import gettext
    LANGUAGES_DIR = os.path.join(COMPONENT_DIR, 'languages')
    _lang = get_setting('language', 'pl') if SETTINGS_AVAILABLE else 'pl'
    _translation = gettext.translation('zegarynka', localedir=LANGUAGES_DIR, languages=[_lang], fallback=True)
    _ = _translation.gettext
except Exception:
    def _(text):
        return text


# ===== Clock Settings =====

def _get_clock_config_path():
    """Return path to clock.ini in the Titan config directory."""
    p = platform.system()
    if p == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
        base = os.path.join(base, 'titosoft', 'Titan')
    elif p == 'Darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'titosoft', 'Titan')
    else:
        base = os.path.join(os.path.expanduser('~'), '.config', 'titosoft', 'Titan')
    return os.path.join(base, 'clock.ini')


def load_clock_settings():
    """Load settings from clock.ini, returning a dict with defaults."""
    config = configparser.ConfigParser()
    path = _get_clock_config_path()
    if os.path.exists(path):
        try:
            config.read(path, encoding='utf-8')
        except Exception as e:
            print(f"[zegarynka] Error reading clock.ini: {e}")

    return {
        'enabled':  config.getboolean('clock', 'enabled',  fallback=True),
        'interval': config.getint    ('clock', 'interval', fallback=30),
    }


def save_clock_settings(s):
    """Save settings dict to clock.ini."""
    config = configparser.ConfigParser()
    config['clock'] = {
        'enabled':  str(int(s.get('enabled', True))),
        'interval': str(s.get('interval', 30)),
    }
    path = _get_clock_config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            config.write(f)
    except Exception as e:
        print(f"[zegarynka] Error saving clock.ini: {e}")


# ===== TTS =====

# Titan TTS (stereo speech) - optional, loaded lazily
_speak_stereo_fn = None

def _get_speak_stereo():
    """Lazily import speak_stereo to avoid circular imports at module load time."""
    global _speak_stereo_fn
    if _speak_stereo_fn is None:
        try:
            from src.titan_core.stereo_speech import speak_stereo
            _speak_stereo_fn = speak_stereo
        except Exception:
            pass
    return _speak_stereo_fn


def _speak(text):
    """Speak text respecting TCE TTS settings (Titan TTS or ao3)."""
    # Check if Titan TTS (stereo speech) is enabled in TCE settings
    use_titan_tts = False
    try:
        use_titan_tts = get_setting('stereo_speech', 'False', 'invisible_interface').lower() in ('true', '1')
    except Exception:
        pass

    if use_titan_tts:
        speak_stereo = _get_speak_stereo()
        if speak_stereo:
            try:
                speak_stereo(text, position=0.0, pitch_offset=0, async_mode=False)
                return
            except Exception as e:
                print(f"[zegarynka] Titan TTS error: {e}, falling back to ao3")

    # ao3 fallback (also catches running screen readers)
    try:
        import accessible_output3.outputs.auto as _ao3
        _ao3.Auto().speak(text, interrupt=False)
    except Exception as e:
        print(f"[zegarynka] TTS failed: {e}")


# ===== Time to Words =====

_POLISH_HOURS = [
    "północ",               # 0
    "pierwsza",             # 1
    "druga",                # 2
    "trzecia",              # 3
    "czwarta",              # 4
    "piąta",                # 5
    "szósta",               # 6
    "siódma",               # 7
    "ósma",                 # 8
    "dziewiąta",            # 9
    "dziesiąta",            # 10
    "jedenasta",            # 11
    "dwunasta",             # 12
    "trzynasta",            # 13
    "czternasta",           # 14
    "piętnasta",            # 15
    "szesnasta",            # 16
    "siedemnasta",          # 17
    "osiemnasta",           # 18
    "dziewiętnasta",        # 19
    "dwudziesta",           # 20
    "dwudziesta pierwsza",  # 21
    "dwudziesta druga",     # 22
    "dwudziesta trzecia",   # 23
]

_POLISH_ONES = [
    "", "jeden", "dwa", "trzy", "cztery", "pięć",
    "sześć", "siedem", "osiem", "dziewięć",
    "dziesięć", "jedenaście", "dwanaście", "trzynaście",
    "czternaście", "piętnaście", "szesnaście", "siedemnaście",
    "osiemnaście", "dziewiętnaście",
]

_POLISH_TENS = {
    2: "dwadzieścia",
    3: "trzydzieści",
    4: "czterdzieści",
    5: "pięćdziesiąt",
}

_ENGLISH_HOURS = [
    "midnight", "one", "two", "three", "four", "five", "six",
    "seven", "eight", "nine", "ten", "eleven", "twelve",
    "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty", "twenty one", "twenty two", "twenty three",
]

_ENGLISH_ONES = [
    "", "one", "two", "three", "four", "five",
    "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]

_ENGLISH_TENS = {
    2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
}


def _minutes_to_polish(minutes):
    if minutes == 0:
        return ""
    if minutes < 20:
        return _POLISH_ONES[minutes]
    tens, ones = divmod(minutes, 10)
    result = _POLISH_TENS[tens]
    if ones:
        result += " " + _POLISH_ONES[ones]
    return result


def _minutes_to_english(minutes):
    if minutes == 0:
        return ""
    if minutes < 20:
        return _ENGLISH_ONES[minutes]
    tens, ones = divmod(minutes, 10)
    result = _ENGLISH_TENS[tens]
    if ones:
        result += " " + _ENGLISH_ONES[ones]
    return result


def time_to_words(hour, minute, lang='pl'):
    """Convert hour/minute to spoken words in Polish or English."""
    hour = hour % 24
    if lang == 'pl':
        hour_word = _POLISH_HOURS[hour]
        minute_word = _minutes_to_polish(minute)
        return f"{hour_word} {minute_word}".strip()
    else:
        hour_word = _ENGLISH_HOURS[hour]
        if minute == 0:
            return "midnight" if hour == 0 else f"{hour_word} o'clock"
        return f"{hour_word} {_minutes_to_english(minute)}"


# ===== Background Clock Thread =====

class _ClockThread(threading.Thread):
    """Daemon thread that monitors time and triggers announcements."""

    def __init__(self):
        super().__init__(daemon=True, name="ZegarynkaThread")
        self._stop_event = threading.Event()
        self._last_announced = None  # (hour, minute) — prevents duplicate announcements
        self.settings = load_clock_settings()

    def reload_settings(self):
        """Reload settings from clock.ini (called after settings are saved)."""
        self.settings = load_clock_settings()
        print(f"[zegarynka] Settings reloaded: {self.settings}")

    def _should_announce(self, hour, minute):
        """Return True if we should announce at this (hour, minute)."""
        interval = self.settings.get('interval', 30)
        if interval == 15:
            trigger = minute in (0, 15, 30, 45)
        elif interval == 30:
            trigger = minute in (0, 30)
        else:   # 60 minutes
            trigger = minute == 0

        if not trigger:
            return False
        if self._last_announced == (hour, minute):
            return False    # Already announced this slot
        return True

    def _announce(self, hour, minute):
        """Play chime, wait 1 second, then speak the time."""
        try:
            if SOUND_AVAILABLE:
                play_sound('ui/cuckoo.ogg')
            time.sleep(1.0)

            lang = get_setting('language', 'pl') if SETTINGS_AVAILABLE else 'pl'
            text = time_to_words(hour, minute, lang)
            _speak(text)

            self._last_announced = (hour, minute)
            print(f"[zegarynka] Announced: {hour:02d}:{minute:02d} -> {text!r}")
        except Exception as e:
            print(f"[zegarynka] Error during announcement: {e}")

    def run(self):
        print("[zegarynka] Clock thread started")
        while not self._stop_event.is_set():
            try:
                if self.settings.get('enabled', True):
                    t = time.localtime()
                    if self._should_announce(t.tm_hour, t.tm_min):
                        self._announce(t.tm_hour, t.tm_min)
            except Exception as e:
                print(f"[zegarynka] Error in clock loop: {e}")

            # Sleep in 5-second intervals so stop() responds quickly
            for _ in range(6):
                if self._stop_event.is_set():
                    break
                time.sleep(5)

        print("[zegarynka] Clock thread stopped")

    def stop(self):
        self._stop_event.set()


# ===== Settings Panel =====

def add_settings_category(component_manager):
    """Register a settings category in the TCE Settings window."""
    if not WX_AVAILABLE:
        return

    def build_panel(parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        panel.enable_cb = wx.CheckBox(panel, label=_("Enable clock chime"))
        sizer.Add(panel.enable_cb, 0, wx.ALL, 8)

        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(wx.StaticText(panel, label=_("Announce time every:")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        panel.interval_choice = wx.Choice(panel, choices=[
            _("15 minutes"),
            _("30 minutes"),
            _("1 hour"),
        ])
        row.Add(panel.interval_choice, 0)
        sizer.Add(row, 0, wx.ALL, 8)

        panel.SetSizer(sizer)
        return panel

    def load_panel(panel):
        s = load_clock_settings()
        panel.enable_cb.SetValue(s['enabled'])
        idx = {15: 0, 30: 1, 60: 2}.get(s['interval'], 1)
        panel.interval_choice.SetSelection(idx)

    def save_panel(panel):
        enabled = panel.enable_cb.GetValue()
        sel = panel.interval_choice.GetSelection()
        interval = [15, 30, 60][sel] if sel != wx.NOT_FOUND else 30
        save_clock_settings({
            'enabled': enabled,
            'interval': interval,
        })
        if _clock_thread is not None:
            _clock_thread.reload_settings()
        print(f"[zegarynka] Settings saved: enabled={enabled}, interval={interval} min")

    component_manager.register_settings_category(
        _("Clock / Zegarynka"),
        build_panel,
        save_panel,
        load_panel,
    )


# ===== Component Interface =====

_clock_thread = None


def initialize(app=None):
    """Start the background clock thread."""
    global _clock_thread
    try:
        print("[zegarynka] Initializing clock chime component...")
        _clock_thread = _ClockThread()
        _clock_thread.start()
        print("[zegarynka] Clock chime component initialized")
    except Exception as e:
        print(f"[zegarynka] Error during initialization: {e}")
        import traceback
        traceback.print_exc()


def shutdown():
    """Stop the background clock thread."""
    global _clock_thread
    try:
        print("[zegarynka] Shutting down clock chime component...")
        if _clock_thread is not None:
            _clock_thread.stop()
            _clock_thread.join(timeout=3.0)
            _clock_thread = None
        print("[zegarynka] Clock chime component shutdown complete")
    except Exception as e:
        print(f"[zegarynka] Error during shutdown: {e}")
        import traceback
        traceback.print_exc()


# ===== Standalone Test =====

if __name__ == '__main__':
    print("=" * 60)
    print("Zegarynka (Clock Chime) - Standalone Test")
    print("=" * 60)

    test_times = [(0, 0), (1, 0), (12, 0), (15, 50), (16, 0), (20, 15), (23, 30)]
    print("\n[Polish]")
    for h, m in test_times:
        print(f"  {h:02d}:{m:02d}  ->  {time_to_words(h, m, 'pl')}")

    print("\n[English]")
    for h, m in test_times:
        print(f"  {h:02d}:{m:02d}  ->  {time_to_words(h, m, 'en')}")

    print("\nStarting component (runs for 12 seconds)...")
    initialize()
    time.sleep(12)
    shutdown()
    print("\nTest completed!")
