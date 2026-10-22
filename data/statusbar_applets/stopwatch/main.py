"""
Stopwatch Statusbar Applet (Stoper)

Provides a stopwatch with start/pause, reset, and lap times directly on the Titan status bar,
plus an accessible control dialog when activated.
"""

import os
import json
import time
import gettext
import threading

_APPLET_DIR = os.path.dirname(os.path.abspath(__file__))
_LANGUAGES_DIR = os.path.join(_APPLET_DIR, "languages")
_STATE_LOCK = threading.Lock()
_STATE_FILE = os.path.join(_APPLET_DIR, "stopwatch_state.json")

_TICK_LOCK = threading.Lock()
_TICK_THREAD = None
_LAST_TICK_SECOND = -1


def _get_translator():
    try:
        from src.settings.settings import get_setting
        lang = get_setting('language', 'pl')
    except Exception:
        lang = 'pl'
    try:
        trans = gettext.translation('stopwatch', localedir=_LANGUAGES_DIR, languages=[lang], fallback=True)
        return trans.gettext
    except Exception:
        return lambda x: x


# Initialize module-level _ (also injected by StatusbarAppletManager)
_ = _get_translator()


def _t(msg: str) -> str:
    """Translate using dynamic language lookup so language changes apply immediately."""
    try:
        return _get_translator()(msg)
    except Exception:
        return _(msg)


def _load_state() -> dict:
    default_state = {
        "running": False,
        "start_timestamp": 0.0,
        "accumulated": 0.0,
        "laps": []
    }
    with _STATE_LOCK:
        if not os.path.exists(_STATE_FILE):
            return default_state
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return default_state
            return {
                "running": bool(data.get("running", False)),
                "start_timestamp": float(data.get("start_timestamp", 0.0)),
                "accumulated": float(data.get("accumulated", 0.0)),
                "laps": list(data.get("laps", []))
            }
        except Exception:
            return default_state


def _save_state(state: dict) -> None:
    with _STATE_LOCK:
        try:
            with open(_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving stopwatch state: {e}")


def get_elapsed_seconds(state: dict = None) -> float:
    if state is None:
        state = _load_state()
    elapsed = float(state.get("accumulated", 0.0))
    if state.get("running"):
        start_ts = float(state.get("start_timestamp", 0.0))
        if start_ts > 0:
            elapsed += max(0.0, time.time() - start_ts)
    return elapsed


def format_duration(seconds: float) -> str:
    total_secs = int(max(0, seconds))
    hours, rem = divmod(total_secs, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _theme_has_click_sound() -> bool:
    """Check if core/click.ogg exists in the active Titan sound theme (or fallback theme if enabled)."""
    try:
        from src.settings.settings import load_settings
        from src.titan_core import sound as titan_sound
        from src.platform_utils import find_resource

        settings = load_settings()
        sound_settings = settings.get('sound', {})
        theme_name = str(sound_settings.get('theme', getattr(titan_sound, 'current_theme', 'default'))).strip() or 'default'
        fallback_to_default = str(sound_settings.get('fallback_to_default_theme', 'False')).lower() in ('true', '1')

        rel_primary = os.path.join('sfx', theme_name, 'core', 'click.ogg')
        path_primary = find_resource(rel_primary)
        if path_primary and os.path.exists(path_primary):
            return True

        sfx_dir = titan_sound.get_sfx_directory()
        if sfx_dir and os.path.exists(os.path.join(sfx_dir, 'core', 'click.ogg')):
            return True

        if fallback_to_default and theme_name != 'default':
            rel_default = os.path.join('sfx', 'default', 'core', 'click.ogg')
            path_default = find_resource(rel_default)
            if path_default and os.path.exists(path_default):
                return True

        return False
    except Exception:
        return False


def _play_tick_click() -> None:
    """Play core/click.ogg if it exists in the current sound theme."""
    try:
        if not _theme_has_click_sound():
            return
        from src.titan_core.sound import play_sound
        play_sound("core/click.ogg")
    except Exception:
        pass


def _tick_worker() -> None:
    """Background worker that plays core/click.ogg once every elapsed second while running."""
    global _LAST_TICK_SECOND
    while True:
        try:
            state = _load_state()
            if state.get("running"):
                current_sec = int(get_elapsed_seconds(state))
                with _TICK_LOCK:
                    should_tick = (current_sec > 0 and current_sec != _LAST_TICK_SECOND)
                    if should_tick:
                        _LAST_TICK_SECOND = current_sec
                if should_tick:
                    _play_tick_click()
            else:
                with _TICK_LOCK:
                    _LAST_TICK_SECOND = -1
        except Exception:
            pass
        time.sleep(0.1)


def _ensure_tick_thread() -> None:
    global _TICK_THREAD
    with _TICK_LOCK:
        if _TICK_THREAD is None or not _TICK_THREAD.is_alive():
            _TICK_THREAD = threading.Thread(target=_tick_worker, name="StopwatchTickThread", daemon=True)
            _TICK_THREAD.start()


def _speak_and_cue(text: str, sound_file: str = None, pan: float = 0.0):
    try:
        if sound_file:
            from src.titan_core.sound import play_sound
            play_sound(sound_file, pan=0.5 + (pan * 0.5))
    except Exception:
        pass
    try:
        from src.titan_core.stereo_speech import speak_stereo
        speak_stereo(text, position=pan, interrupt=True)
    except Exception:
        pass


def start_stopwatch() -> dict:
    _ensure_tick_thread()
    state = _load_state()
    if not state["running"]:
        state["running"] = True
        state["start_timestamp"] = time.time()
        _save_state(state)
    return state


def pause_stopwatch() -> dict:
    state = _load_state()
    if state["running"]:
        state["accumulated"] = get_elapsed_seconds(state)
        state["running"] = False
        state["start_timestamp"] = 0.0
        _save_state(state)
    return state


def toggle_stopwatch() -> dict:
    state = _load_state()
    if state["running"]:
        return pause_stopwatch()
    return start_stopwatch()


def reset_stopwatch() -> dict:
    global _LAST_TICK_SECOND
    with _TICK_LOCK:
        _LAST_TICK_SECOND = -1
    state = {
        "running": False,
        "start_timestamp": 0.0,
        "accumulated": 0.0,
        "laps": []
    }
    _save_state(state)
    return state


def add_lap() -> str:
    state = _load_state()
    elapsed = get_elapsed_seconds(state)
    formatted = format_duration(elapsed)
    lap_no = len(state["laps"]) + 1
    lap_entry = f"#{lap_no}: {formatted}"
    state["laps"].append(lap_entry)
    _save_state(state)
    return lap_entry


def get_statusbar_item_info() -> dict:
    """
    Return applet metadata for StatusbarAppletManager.
    """
    _ensure_tick_thread()
    return {
        "name": _t("Stopwatch"),
        "update_interval": 1
    }


def get_statusbar_item_text() -> str:
    """
    Return the current stopwatch text for the status bar.
    """
    try:
        _ensure_tick_thread()
        state = _load_state()
        elapsed = get_elapsed_seconds(state)
        formatted = format_duration(elapsed)
        if state["running"]:
            status = _t("running")
        elif elapsed > 0:
            status = _t("paused")
        else:
            status = _t("ready")

        laps_count = len(state.get("laps", []))
        if laps_count > 0:
            lap_info = _t(", laps: {count}").format(count=laps_count)
        else:
            lap_info = ""

        label = _t("Stopwatch")
        return f"{label}: {formatted} ({status}{lap_info})"
    except Exception as e:
        print(f"Error in stopwatch get_statusbar_item_text: {e}")
        return _t("Stopwatch: error")


def on_statusbar_item_activate(parent_frame=None):
    """
    Open the accessible Stopwatch control window when activated from the statusbar,
    or toggle the stopwatch if no GUI is available.
    """
    _ensure_tick_thread()
    try:
        import wx
        app = wx.GetApp()
        if app is not None:
            dlg = StopwatchDialog(parent_frame)
            dlg.ShowModal()
            dlg.Destroy()
            return
    except Exception as e:
        print(f"Stopwatch GUI fallback: {e}")

    # Fallback if wx is not running
    state = toggle_stopwatch()
    elapsed = format_duration(get_elapsed_seconds(state))
    if state["running"]:
        _speak_and_cue(_t("Stopwatch started: {time}").format(time=elapsed), "core/SELECT.ogg", -0.3)
    else:
        _speak_and_cue(_t("Stopwatch paused: {time}").format(time=elapsed), "core/SELECT.ogg", 0.3)


try:
    import wx

    class StopwatchDialog(wx.Dialog):
        def __init__(self, parent):
            super().__init__(
                parent,
                title=_t("Stopwatch"),
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
            )
            self.SetSize((420, 340))
            self._build_ui()
            self._refresh_ui()

            self._timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
            self._timer.Start(250)
            self.Bind(wx.EVT_CLOSE, self._on_close)

        def _build_ui(self):
            panel = wx.Panel(self)
            main_sizer = wx.BoxSizer(wx.VERTICAL)

            lbl_title = wx.StaticText(panel, label=_t("Current stopwatch time:"))
            main_sizer.Add(lbl_title, 0, wx.ALL, 8)

            self.time_display = wx.TextCtrl(
                panel,
                value="00:00",
                style=wx.TE_READONLY | wx.TE_CENTER
            )
            font = self.time_display.GetFont()
            font.SetPointSize(16)
            font.SetWeight(wx.FONTWEIGHT_BOLD)
            self.time_display.SetFont(font)
            self.time_display.SetName(_t("Stopwatch time"))
            main_sizer.Add(self.time_display, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

            self.btn_toggle = wx.Button(panel, label=_t("&Start"))
            self.btn_lap = wx.Button(panel, label=_t("&Lap"))
            self.btn_reset = wx.Button(panel, label=_t("&Reset"))
            self.btn_close = wx.Button(panel, id=wx.ID_CANCEL, label=_t("&Close"))

            btn_sizer.Add(self.btn_toggle, 1, wx.ALL, 4)
            btn_sizer.Add(self.btn_lap, 1, wx.ALL, 4)
            btn_sizer.Add(self.btn_reset, 1, wx.ALL, 4)
            btn_sizer.Add(self.btn_close, 1, wx.ALL, 4)

            main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)

            lbl_laps = wx.StaticText(panel, label=_t("Recorded laps:"))
            main_sizer.Add(lbl_laps, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)

            self.laps_list = wx.ListBox(panel)
            self.laps_list.SetName(_t("Lap list"))
            main_sizer.Add(self.laps_list, 1, wx.EXPAND | wx.ALL, 8)

            panel.SetSizer(main_sizer)

            self.btn_toggle.Bind(wx.EVT_BUTTON, self._on_toggle)
            self.btn_lap.Bind(wx.EVT_BUTTON, self._on_lap)
            self.btn_reset.Bind(wx.EVT_BUTTON, self._on_reset)
            self.btn_close.Bind(wx.EVT_BUTTON, lambda e: self.Close())

            self.btn_toggle.SetFocus()

        def _refresh_ui(self):
            state = _load_state()
            elapsed = get_elapsed_seconds(state)
            formatted = format_duration(elapsed)
            if self.time_display.GetValue() != formatted:
                self.time_display.SetValue(formatted)

            if state["running"]:
                new_label = _t("&Pause")
            elif elapsed > 0:
                new_label = _t("&Resume")
            else:
                new_label = _t("&Start")

            if self.btn_toggle.GetLabel() != new_label:
                self.btn_toggle.SetLabel(new_label)

            laps = state.get("laps", [])
            if self.laps_list.GetCount() != len(laps):
                self.laps_list.Set(laps)
                if laps:
                    self.laps_list.SetSelection(len(laps) - 1)

        def _on_timer(self, event):
            self._refresh_ui()

        def _on_toggle(self, event):
            state = toggle_stopwatch()
            elapsed = format_duration(get_elapsed_seconds(state))
            self._refresh_ui()
            if state["running"]:
                _speak_and_cue(_t("Started: {time}").format(time=elapsed), "core/SELECT.ogg", -0.4)
            else:
                _speak_and_cue(_t("Paused: {time}").format(time=elapsed), "core/SELECT.ogg", 0.0)

        def _on_lap(self, event):
            lap_entry = add_lap()
            self._refresh_ui()
            _speak_and_cue(_t("Lap {lap}").format(lap=lap_entry), "core/FOCUS_EXPANDED.ogg", 0.4)

        def _on_reset(self, event):
            reset_stopwatch()
            self._refresh_ui()
            _speak_and_cue(_t("Stopwatch reset"), "core/CLOSE.ogg", 0.0)

        def _on_close(self, event):
            if self._timer.IsRunning():
                self._timer.Stop()
            self.EndModal(wx.ID_CANCEL)

except Exception:
    pass
