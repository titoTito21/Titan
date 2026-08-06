# -*- coding: utf-8 -*-
"""Progress bars, announced while they move.

A progress bar is the one control a screen reader must report without being
asked: the user is waiting for it, and it says nothing when it changes. NVDA
answers this with a beep whose pitch rises with the value. Titan Access does the
same, and adds what Titan can do that NVDA cannot:

* the beep is **positioned**: 0% is hard left, 100% is hard right, so the
  progress is heard travelling across the stereo image (and, in 3D sound mode,
  through the same pan Titan uses everywhere else),
* the pitch still rises with the value, so the two cues agree, and
* **every ten percent is spoken** ("thirty percent"), so a user who is not
  listening closely to the tone still knows where it is.

What is monitored is the progress bar in the FOREGROUND window - the one the
user is waiting for. A bar that finishes, disappears or belongs to a window the
user has left stops being reported at once.

Everything runs on one slow background thread, created only when a progress bar
is actually found, and every reading is bounded and guarded: this must never be
able to stall the reader, whatever the watched application does.

# LOCALE KEYS TO ADD: progress.percent = {0} percent
# LOCALE KEYS TO ADD: progress.complete = complete
# LOCALE KEYS TO ADD: progress.started = {0}, in progress
"""

import threading
import time

from titan_access.localization import L
from titan_access.settings_store import AnnouncementMode

# How often a live progress bar is read.
_TICK_S = 0.35
# How often the foreground window is searched for a progress bar when none is
# being watched. A search is a bounded tree walk, so it is kept rare.
_SEARCH_S = 1.5
# Bounds for that search.
_SEARCH_DEPTH = 8
_SEARCH_NODES = 400

# The tone is NVDA's, exactly: ``beepMinHZ * 2 ** (percentage / 25.0)`` for 40
# ms, with beepMinHZ defaulting to 110 Hz -- so 0% is a low A, and the pitch
# doubles every quarter of the way (about 1760 Hz at 100%). Taken from NVDA's
# own ``NVDAObjects/behaviors.py`` ProgressBar.event_valueChange, so a user
# coming from NVDA hears the progress they already know.
_BASE_HZ = 110.0
_TONE_MS = 40

# NVDA's two throttles, with its defaults: beep on every 1% of movement, speak
# on every 10%.
_BEEP_INTERVAL = 1.0
_SPEECH_INTERVAL = 10.0


def _percent(value, minimum, maximum):
    """Value in a range -> 0..100, or None when the range says nothing."""
    try:
        value = float(value)
        minimum = float(minimum)
        maximum = float(maximum)
    except (TypeError, ValueError):
        return None
    if maximum <= minimum:
        return None
    percent = (value - minimum) / (maximum - minimum) * 100.0
    return max(0.0, min(100.0, percent))


def pan_for_percent(percent):
    """0% hard left (-1.0) .. 100% hard right (+1.0)."""
    return max(-1.0, min(1.0, (percent / 50.0) - 1.0))


def tone_for_percent(percent):
    """Rising pitch, NVDA's curve: 110 Hz at 0%, ~1760 Hz at 100%."""
    return _BASE_HZ * (2.0 ** (percent / 25.0))


class ProgressMonitor:
    """Watches the foreground window's progress bar and reports it."""

    def __init__(self, engine):
        self.engine = engine
        self._thread = None
        self._running = False
        self._lock = threading.RLock()

        # What is being watched: a UIA Control, or an (IAccessible, child) pair.
        self._target = None
        self._target_kind = ""       # 'uia' | 'msaa'
        self._target_name = ""
        self._hwnd = 0
        self._last_percent = None
        self._last_beep_percent = None
        self._last_spoken_percent = None
        self._last_search = 0.0
        self._announced = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self):
        if self._running:
            return self
        self._running = True
        self._thread = threading.Thread(target=self._loop,
                                        name="TitanAccessProgress", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------ #
    # Focus hint
    # ------------------------------------------------------------------ #
    def on_focus(self, obj):
        """Take the focused control as the watched bar when it is one.

        Cheaper and more accurate than searching: if the user has tabbed to the
        progress bar, that is certainly the one they care about.
        """
        if obj is None:
            return
        try:
            if obj.role != "progressbar":
                return
        except Exception:
            return
        native = getattr(obj, "native", None)
        if native is None:
            return
        with self._lock:
            self._target = native
            self._target_kind = "uia"
            self._target_name = (getattr(obj, "name", "") or "").strip()
            self._hwnd = getattr(obj, "hwnd", 0) or 0
            self._last_percent = None
            self._last_beep_percent = None
            self._last_spoken_percent = None
            self._announced = False

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #
    def _mode(self):
        try:
            raw = self.engine.settings.get("Reader", "ProgressMode")
        except Exception:
            raw = ""
        return AnnouncementMode.normalize(raw or "SpeechAndSound")

    def _loop(self):
        # UIA lives in COM; this thread owns its own apartment so nothing it
        # does can be marshalled onto (and therefore block) the reader's.
        try:
            import ctypes
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        except Exception:
            pass
        while self._running:
            try:
                self._tick()
            except Exception as e:
                print(f"[TitanAccess] progress monitor error: {e}")
            time.sleep(_TICK_S)
        try:
            import ctypes
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass

    def _tick(self):
        mode = self._mode()
        if mode == AnnouncementMode.NONE:
            self._forget()
            return
        if self.engine is not None and getattr(self.engine, "_muted_for_foreground", None):
            try:
                if self.engine._muted_for_foreground():
                    return
            except Exception:
                pass
        percent = self._read_percent()
        if percent is None:
            # Nothing (or nothing any more) to watch: look for a bar, rarely.
            now = time.time()
            if (now - self._last_search) >= _SEARCH_S:
                self._last_search = now
                self._find_progress_bar()
            return
        self._report(percent, mode)

    def _forget(self):
        with self._lock:
            self._target = None
            self._target_kind = ""
            self._last_percent = None
            self._last_beep_percent = None
            self._last_spoken_percent = None
            self._announced = False

    # ------------------------------------------------------------------ #
    # Reading the value
    # ------------------------------------------------------------------ #
    def _read_percent(self):
        with self._lock:
            target, kind = self._target, self._target_kind
        if target is None:
            return None
        try:
            if kind == "uia":
                return self._read_uia(target)
            if kind == "msaa":
                return self._read_msaa(target)
        except Exception:
            # The bar (or its window) is gone.
            self._forget()
        return None

    @staticmethod
    def _read_uia(control):
        try:
            if not control.Exists(0, 0):
                return None
        except Exception:
            pass
        try:
            pattern = control.GetRangeValuePattern()
        except Exception:
            pattern = None
        if pattern is not None:
            try:
                return _percent(pattern.Value, pattern.Minimum, pattern.Maximum)
            except Exception:
                pass
        # Some bars expose only a value string ("45%").
        try:
            pattern = control.GetValuePattern()
            if pattern is not None:
                return _parse_percent_text(pattern.Value)
        except Exception:
            pass
        try:
            return _parse_percent_text(control.Name)
        except Exception:
            return None

    @staticmethod
    def _read_msaa(target):
        acc, child_id = target
        try:
            return _parse_percent_text(acc.accValue(child_id))
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Finding a bar
    # ------------------------------------------------------------------ #
    def _find_progress_bar(self):
        """Bounded search of the foreground window for a live progress bar."""
        try:
            import uiautomation as auto
        except Exception:
            return
        from titan_access import virtual_buffer as vbuf
        hwnd = vbuf.foreground_hwnd()
        if not hwnd:
            return
        try:
            window = auto.ControlFromHandle(hwnd)
        except Exception:
            window = None
        if window is None:
            return
        from collections import deque
        queue = deque([(window, 0)])
        seen = 0
        while queue:
            node, depth = queue.popleft()
            if depth >= _SEARCH_DEPTH:
                continue
            try:
                children = node.GetChildren()
            except Exception:
                children = []
            for child in children or []:
                seen += 1
                if seen > _SEARCH_NODES:
                    return
                try:
                    if child.ControlTypeName == "ProgressBarControl":
                        if self._read_uia(child) is None:
                            continue
                        with self._lock:
                            self._target = child
                            self._target_kind = "uia"
                            self._target_name = (child.Name or "").strip()
                            self._hwnd = hwnd
                            self._last_percent = None
                            self._last_beep_percent = None
                            self._last_spoken_percent = None
                            self._announced = False
                        return
                except Exception:
                    pass
                queue.append((child, depth + 1))

    # ------------------------------------------------------------------ #
    # Reporting (NVDA's ProgressBar.event_valueChange, with Titan's stereo)
    # ------------------------------------------------------------------ #
    def _report(self, percent, mode):
        with self._lock:
            last_beep = self._last_beep_percent
            last_speech = self._last_spoken_percent
            name = self._target_name
            announced = self._announced

        # A restart (100% -> 0%) is movement too, so both throttles compare the
        # ABSOLUTE change, exactly as NVDA's per-bar caches do.
        beep_due = last_beep is None or abs(percent - last_beep) >= self._beep_interval()
        speech_due = (last_speech is None
                      or abs(percent - last_speech) >= self._speech_interval())
        finished = percent >= 99.5 and (last_speech is None or last_speech < 99.5)
        if not beep_due and not speech_due and not finished:
            return

        with self._lock:
            self._last_percent = percent
            self._announced = True

        if beep_due and AnnouncementMode.plays(mode):
            with self._lock:
                self._last_beep_percent = percent
            self._beep(percent)

        if not AnnouncementMode.speaks(mode):
            return
        if not announced and name:
            # First sighting: say what it is, so a beep travelling across the
            # stereo image is not a mystery.
            self.engine.speak(L("progress.started", name), interrupt=False)
        if not (speech_due or finished):
            return
        with self._lock:
            self._last_spoken_percent = percent
        if finished:
            self.engine.speak(L("progress.complete"), interrupt=False)
            return
        self.engine.speak(L("progress.percent", int(percent)), interrupt=False)

    def _beep(self, percent):
        """One NVDA beep, panned to where the progress has got to.

        Pitch is NVDA's (``110 * 2 ** (percent / 25)``, 40 ms); the pan is what
        Titan adds -- 0% hard left, 100% hard right -- so the bar is also heard
        travelling across the stereo image.
        """
        sound = getattr(self.engine, "sound", None)
        if sound is None:
            return
        try:
            sound.play_tone(frequency=tone_for_percent(percent),
                            duration_ms=_TONE_MS,
                            pan=pan_for_percent(percent), gain=0.35)
        except Exception:
            pass

    def _beep_interval(self):
        return self._interval("ProgressBeepInterval", _BEEP_INTERVAL, 0.5, 100.0)

    def _speech_interval(self):
        return self._interval("ProgressSpeechInterval", _SPEECH_INTERVAL, 1.0, 100.0)

    def _interval(self, key, default, low, high):
        try:
            value = float(str(self.engine.settings.get("Reader", key)).strip())
        except Exception:
            return default
        if value <= 0:
            return default
        return max(low, min(high, value))


def _parse_percent_text(text):
    """Pull a percentage out of a value string ('45%', '45', '45 %')."""
    if text in (None, ""):
        return None
    raw = str(text).strip().replace("%", "").replace(",", ".").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, value))
